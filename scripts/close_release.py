#!/usr/bin/env python3
"""Write and verify the minimal local v1 release-closeout archive."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_contracts import (  # noqa: E402
    ContractError,
    RELEASE_TASK_ID_RE,
    canonical_json,
    load_persisted_plan_specs,
    load_json,
    object_digest,
    parse_rfc3339,
    validate_candidate_evidence,
    validate_cross_record_set,
    validate_master_card,
    validate_master_transition,
    validate_plan,
    validate_release_closeout,
    validate_worker_card,
    value_digest,
)


TERMINAL_DISPATCH_STATES = {"INTEGRATED", "CANCELLED", "SUPERSEDED"}
ARCHIVE_NAMES = ("dispatch-plan.json", "master-card.active.json", "closeout.json")
WORKER_CARD_SIDECAR = "WORKTREE_TASK.json"


class CloseoutError(ValueError):
    """A fail-closed closeout precondition or persistence error."""


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def compact_json(value: dict[str, Any]) -> bytes:
    return canonical_json(value)


def read_json_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CloseoutError(f"cannot read {label} at {path}: {error}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CloseoutError(f"{label} is not valid UTF-8 JSON at {path}: {error}") from error
    if not isinstance(value, dict):
        raise CloseoutError(f"{label} must be a JSON object")
    return raw, value


def safe_release_task_id(value: Any) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 256 or not RELEASE_TASK_ID_RE.fullmatch(value):
        raise CloseoutError("release_task_id is not archive-safe")
    return value


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def archive_directory(plan: dict[str, Any]) -> Path:
    release_task_id = safe_release_task_id(plan["release_task_id"])
    state_root = Path(plan["state_root"])
    if not state_root.is_absolute():
        raise CloseoutError("Plan state_root must be absolute")
    try:
        state_root_real = state_root.resolve(strict=False)
        boundary = (state_root_real / "history" / "releases").resolve(strict=False)
        archive = (boundary / release_task_id).resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise CloseoutError(f"cannot resolve closeout archive boundary: {error}") from error
    if not path_is_within(boundary, state_root_real) or not path_is_within(archive, boundary):
        raise CloseoutError("closeout archive path escapes state_root/history/releases")
    return archive


def check_archive_directory(archive: Path) -> None:
    if not os.path.lexists(archive):
        return
    if archive.is_symlink() or not archive.is_dir():
        raise CloseoutError(f"archive locator is not a directory: {archive}")
    allowed_temps = tuple(f".{name}.tmp-" for name in ARCHIVE_NAMES)
    for child in archive.iterdir():
        if child.name in ARCHIVE_NAMES:
            continue
        if not child.name.startswith(allowed_temps):
            raise CloseoutError(f"unexpected authoritative archive entry: {child.name}")


def sync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def existing_bytes(path: Path, expected: bytes) -> bool:
    if not os.path.lexists(path):
        return False
    if path.is_symlink() or not path.is_file():
        raise CloseoutError(f"archive path is not a regular file: {path}")
    try:
        actual = path.read_bytes()
    except OSError as error:
        raise CloseoutError(f"cannot read existing archive file {path}: {error}") from error
    if actual != expected:
        raise CloseoutError(f"conflicting bytes at archive path: {path}")
    return True


def require_regular_file(path: Path, label: str) -> None:
    if not os.path.lexists(path) or path.is_symlink() or not path.is_file():
        raise CloseoutError(f"{label} is not a regular file: {path}")


def write_once(path: Path, data: bytes) -> bool:
    """Install a final archive file without replacing an existing name."""
    if existing_bytes(path, data):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not existing_bytes(path, data):
                raise CloseoutError(f"archive path appeared with conflicting bytes: {path}")
            return False
        sync_directory(path.parent)
    except CloseoutError:
        raise
    except OSError as error:
        raise CloseoutError(f"cannot atomically install {path}: {error}") from error
    try:
        temporary.unlink()
    except OSError as error:
        raise CloseoutError(f"archive installed but temporary sibling remains at {temporary}: {error}") from error
    return True


def replace_live(path: Path, expected_old: bytes, replacement: bytes) -> bool:
    if not os.path.lexists(path) or path.is_symlink() or not path.is_file():
        raise CloseoutError(f"live Master Card is not a regular file: {path}")
    actual = path.read_bytes()
    if actual == replacement:
        return False
    if actual != expected_old:
        raise CloseoutError("live Master Card changed before the final closeout transition")
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as handle:
            handle.write(replacement)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        if path.read_bytes() != expected_old:
            raise CloseoutError("live Master Card changed during closeout validation")
        os.replace(temporary, path)
        sync_directory(path.parent)
    except CloseoutError:
        raise
    except OSError as error:
        raise CloseoutError(f"cannot atomically replace live Master Card: {error}") from error
    return True


def timestamp_after(value: str, requested: str | None) -> str:
    minimum = parse_rfc3339(value, "Master Card.updated_at")
    if requested is None:
        candidate = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    else:
        candidate = parse_rfc3339(requested, "closeout timestamp")
        if candidate is None:
            raise CloseoutError("closeout timestamp may not be null")
    if candidate <= minimum:
        candidate = minimum + dt.timedelta(seconds=1)
    return candidate.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty_live_candidate() -> dict[str, Any]:
    return {"release_head_sha": None, "gate_input_digest": None, "status": "NONE", "checks": []}


def idle_projection(active: dict[str, Any], timestamp: str) -> dict[str, Any]:
    idle = copy.deepcopy(active)
    idle.update({
        "state": "IDLE",
        "record_revision": active["record_revision"] + 1,
        "updated_at": timestamp,
        "release_task_id": None,
        "plan_revision": None,
        "dispatch_plan_path": None,
        "dispatch_plan_digest": None,
        "frozen_baseline_sha": None,
        "candidate_evidence": empty_live_candidate(),
        "blocker": None,
    })
    return idle


def git_output(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=repo_root, text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise CloseoutError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def git_snapshot(repo_root: Path) -> tuple[str, str]:
    head = git_output(repo_root, "rev-parse", "HEAD")
    tree = git_output(repo_root, "rev-parse", "HEAD^{tree}")
    if git_output(repo_root, "cat-file", "-t", head) != "commit":
        raise CloseoutError("candidate HEAD is not a reachable commit")
    if git_output(repo_root, "status", "--porcelain", "--untracked-files=all"):
        raise CloseoutError("Master worktree is not clean at closeout")
    return head, tree


def assert_git_snapshot(repo_root: Path, expected_head: str, expected_tree: str) -> None:
    head, tree = git_snapshot(repo_root)
    if (head, tree) != (expected_head, expected_tree):
        raise CloseoutError("Git HEAD or tree changed during closeout validation")


def assert_source_bytes(path: Path, expected: bytes, label: str) -> None:
    try:
        actual = path.read_bytes()
    except OSError as error:
        raise CloseoutError(f"cannot re-read {label} at {path}: {error}") from error
    if actual != expected:
        raise CloseoutError(f"{label} changed during closeout validation: {path}")


def assert_worker_cards_unchanged(worker_cards: list[tuple[Path, dict[str, Any]]],
                                  schema: dict[str, Any]) -> None:
    for path, expected in worker_cards:
        require_regular_file(path, "Worker Card")
        _, current = read_json_bytes(path, "Worker Card")
        try:
            validate_worker_card(current, schema)
        except (ContractError, KeyError, TypeError) as error:
            raise CloseoutError(f"Worker Card changed to an invalid value at {path}: {error}") from error
        if current != expected or current["state"] != "IDLE":
            raise CloseoutError(f"Worker Card changed during closeout validation: {path}")


def assert_sources_unchanged(plan_path: Path, plan_bytes: bytes, plan: dict[str, Any],
                             specs: dict[str, dict[str, Any]], worker_cards: list[tuple[Path, dict[str, Any]]],
                             schema: dict[str, Any]) -> None:
    assert_source_bytes(plan_path, plan_bytes, "Dispatch Plan")
    try:
        current_specs = load_persisted_plan_specs(plan, schema)
    except (ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise CloseoutError(f"Task Specs changed during closeout validation: {error}") from error
    if current_specs != specs:
        raise CloseoutError("Task Specs changed during closeout validation")
    assert_worker_cards_unchanged(worker_cards, schema)


def safe_worker_card_path(path: Path, label: str = "Worker Card") -> Path:
    if not path.is_absolute():
        path = Path.cwd() / path
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        # macOS exposes /var and /tmp as root-level compatibility aliases;
        # reject user-created path links below those OS boundaries.
        if current.is_symlink() and current not in {Path("/var"), Path("/tmp"), Path("/home")}:
            raise CloseoutError(f"{label} path contains a symlink component: {current}")
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise CloseoutError(f"cannot canonicalize {label} path {path}: {error}") from error


def expected_worker_worktrees(plan: dict[str, Any]) -> dict[Path, str]:
    worktrees: dict[Path, str] = {}
    for task in plan["tasks"]:
        raw = Path(task["worktree"])
        canonical = safe_worker_card_path(raw, "Plan worktree")
        if not canonical.is_dir() or canonical.is_symlink():
            raise CloseoutError(f"Plan worktree is not a regular directory: {raw}")
        previous = worktrees.get(canonical)
        if previous is not None and previous != task["worktree"]:
            raise CloseoutError(f"Plan contains aliased Worker worktrees: {previous}, {task['worktree']}")
        worktrees[canonical] = task["worktree"]
    return worktrees


def select_worker_card_paths(plan: dict[str, Any], requested: list[Path] | None) -> list[Path]:
    expected = expected_worker_worktrees(plan)
    if not requested:
        return [worktree / WORKER_CARD_SIDECAR for worktree in sorted(expected)]
    canonical: list[Path] = []
    for path in requested:
        resolved = safe_worker_card_path(path)
        if resolved in canonical:
            raise CloseoutError("duplicate Worker Card input path")
        canonical.append(resolved)
    return canonical


def load_worker_cards(paths: list[Path], schema: dict[str, Any]) -> list[tuple[Path, dict[str, Any]]]:
    if len({str(safe_worker_card_path(path)) for path in paths}) != len(paths):
        raise CloseoutError("duplicate Worker Card input path")
    cards: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        path = safe_worker_card_path(path)
        require_regular_file(path, "Worker Card")
        _, card = read_json_bytes(path, "Worker Card")
        try:
            validate_worker_card(card, schema)
        except (ContractError, KeyError, TypeError) as error:
            raise CloseoutError(f"invalid Worker Card {path}: {error}") from error
        if card["state"] != "IDLE":
            raise CloseoutError(f"Worker Card is not IDLE: {path}")
        cards.append((path, card))
    return cards


def validate_sources(repo_root: Path, plan_path: Path, plan: dict[str, Any], specs: dict[str, dict[str, Any]],
                     master: dict[str, Any], worker_cards: list[tuple[Path, dict[str, Any]]],
                     requested_release_task_id: str | None, schema: dict[str, Any]) -> tuple[str, str]:
    release_task_id = safe_release_task_id(plan["release_task_id"])
    if requested_release_task_id is not None and requested_release_task_id != release_task_id:
        raise CloseoutError("requested release_task_id differs from the Plan")
    if master["state"] != "ACTIVE" or master["blocker"] is not None:
        raise CloseoutError("closeout requires an ACTIVE, unblocked Master Card")
    nonterminal = [task["task_id"] for task in plan["tasks"]
                   if task["dispatch_status"] not in TERMINAL_DISPATCH_STATES]
    if nonterminal:
        raise CloseoutError(f"nonterminal Dispatch entries prevent closeout: {nonterminal}")
    if any(handoff["state"] == "RECEIVED" for handoff in master["worker_handoffs"]):
        raise CloseoutError("RECEIVED Worker handoff prevents closeout")
    try:
        validate_cross_record_set(plan, None, master, plan_path, specs)
    except (ContractError, KeyError, TypeError) as error:
        raise CloseoutError(f"Plan/Master closeout consistency failed: {error}") from error

    expected_worktrees = expected_worker_worktrees(plan)
    if len(worker_cards) != len(expected_worktrees):
        raise CloseoutError(
            f"Worker Card reconciliation count differs from bound worktrees: "
            f"expected={len(expected_worktrees)}, observed={len(worker_cards)}"
        )
    observed_worktrees: set[Path] = set()
    latest_by_worktree: dict[Path, dict[str, Any]] = {}
    for index, task in enumerate(plan["tasks"]):
        if task["dispatch_status"] not in TERMINAL_DISPATCH_STATES:
            continue
        worktree = safe_worker_card_path(Path(task["worktree"]), "Plan worktree")
        current = latest_by_worktree.get(worktree)
        rank = (task["task_spec_plan_revision"], task["task_spec_revision"], index)
        if current is None or rank > current["_closeout_rank"]:
            latest_by_worktree[worktree] = {**task, "_closeout_rank": rank}
    for path, card in worker_cards:
        history = card["last_task"]
        if history["task_id"] is None:
            raise CloseoutError(f"Worker Card has no bound last_task for closeout: {path}")
        history_spec = specs.get(history["task_id"])
        if history_spec is None:
            raise CloseoutError(f"Worker Card history is not in the closeout Plan: {path}")
        history_worktree = safe_worker_card_path(Path(history_spec["worktree"]), "Worker Card history worktree")
        if history_worktree not in expected_worktrees:
            raise CloseoutError(f"Worker Card history points outside the closeout worktree set: {path}")
        if history_worktree in observed_worktrees:
            raise CloseoutError(f"duplicate Worker Card for closeout worktree: {history_worktree}")
        observed_worktrees.add(history_worktree)
        if path.name == WORKER_CARD_SIDECAR:
            if path.parent not in expected_worktrees:
                raise CloseoutError(f"extra Worker Card sidecar path: {path}")
            if history_worktree != path.parent:
                raise CloseoutError(f"Worker Card sidecar crosses worktree boundary: {path}")
        latest = latest_by_worktree.get(history_worktree)
        if latest is None or (history["task_id"], history["task_spec_revision"], history["task_spec_digest"]) != (
                latest["task_id"], latest["task_spec_revision"], latest["task_spec_digest"]):
            raise CloseoutError(f"Worker Card history is stale for its closeout worktree: {path}")
        try:
            validate_cross_record_set(plan, card, master, plan_path, specs)
        except (ContractError, KeyError, TypeError) as error:
            raise CloseoutError(f"Worker Card closeout consistency failed for {path}: {error}") from error
    if observed_worktrees != set(expected_worktrees):
        missing = sorted(str(path) for path in set(expected_worktrees) - observed_worktrees)
        extra = sorted(str(path) for path in observed_worktrees - set(expected_worktrees))
        raise CloseoutError(f"Worker Card reconciliation is incomplete; missing={missing}, extra={extra}")

    candidate = master["candidate_evidence"]
    try:
        validate_candidate_evidence(candidate, schema)
    except (ContractError, KeyError, TypeError) as error:
        raise CloseoutError(f"candidate evidence is invalid: {error}") from error
    if (candidate.get("schema_version") != 2 or candidate.get("legacy") is not None
            or candidate.get("status") != "PASSED"):
        raise CloseoutError("closeout requires fresh schema-v2 PASSED candidate evidence")
    if (candidate["release_task_id"], candidate["plan_revision"], candidate["plan_digest"]) != (
            release_task_id, plan["plan_revision"], plan["plan_digest"]):
        raise CloseoutError("candidate does not bind the current release Plan")

    head, tree = git_snapshot(repo_root)
    if candidate["release_head_sha"] != head:
        raise CloseoutError("candidate release_head_sha differs from the current Master HEAD")
    return head, tree


def build_closeout(plan: dict[str, Any], master: dict[str, Any], plan_bytes: bytes, master_bytes: bytes,
                   head: str, tree: str, timestamp: str) -> dict[str, Any]:
    handoffs = master["worker_handoffs"]
    handoff_digest = value_digest(handoffs)
    closeout: dict[str, Any] = {
        "schema_version": 1,
        "record_kind": "release-closeout",
        "closeout_revision": 1,
        "release_task_id": plan["release_task_id"],
        "outcome": "COMPLETED",
        "protocol": "v1-authoritative",
        "state_root": plan["state_root"],
        "archive_locator": f"history/releases/{plan['release_task_id']}",
        "issued_by": plan["issued_by"],
        "created_at": timestamp,
        "candidate_validated_at": timestamp,
        "dispatch_plan": {
            "locator": "dispatch-plan.json",
            "record_revision": plan["record_revision"],
            "plan_revision": plan["plan_revision"],
            "plan_digest": plan["plan_digest"],
            "archive_digest": digest_bytes(plan_bytes),
        },
        "master_card": {
            "locator": "master-card.active.json",
            "record_revision": master["record_revision"],
            "state": "ACTIVE",
            "release_task_id": master["release_task_id"],
            "plan_revision": master["plan_revision"],
            "dispatch_plan_digest": master["dispatch_plan_digest"],
            "frozen_baseline_sha": master["frozen_baseline_sha"],
            "archive_digest": digest_bytes(master_bytes),
            "handoff_count": len(handoffs),
            "handoff_array_digest": handoff_digest,
        },
        "candidate": {
            "locator": "master-card.active.json#/candidate_evidence",
            "schema_version": 2,
            "release_task_id": master["candidate_evidence"]["release_task_id"],
            "release_head_sha": master["candidate_evidence"]["release_head_sha"],
            "plan_revision": master["candidate_evidence"]["plan_revision"],
            "plan_digest": master["candidate_evidence"]["plan_digest"],
            "status": "PASSED",
            "legacy": None,
            "value_digest": value_digest(master["candidate_evidence"]),
        },
        "git": {
            "final_release_head_sha": head,
            "final_release_tree_sha": tree,
            "head_reachable": True,
        },
        "worker_handoffs": {
            "count": len(handoffs),
            "array_digest": handoff_digest,
            "all_terminal": True,
            "worker_locks": "ALL_IDLE",
        },
        "live_master_transition": {
            "from_state": "ACTIVE",
            "from_record_revision": master["record_revision"],
            "to_state": "IDLE",
            "to_record_revision": master["record_revision"] + 1,
            "worker_handoffs_preserved": True,
        },
        "external_authority": "NONE",
        "closeout_digest": None,
    }
    closeout["closeout_digest"] = object_digest(closeout, "closeout_digest")
    return closeout


def verify_closeout_links(closeout: dict[str, Any], plan: dict[str, Any], master: dict[str, Any],
                          plan_bytes: bytes, master_bytes: bytes, head: str, tree: str,
                          schema: dict[str, Any]) -> None:
    try:
        validate_release_closeout(closeout, schema)
    except (ContractError, KeyError, TypeError) as error:
        raise CloseoutError(f"invalid closeout record: {error}") from error
    if closeout["state_root"] != plan["state_root"] or closeout["issued_by"] != plan["issued_by"]:
        raise CloseoutError("closeout Plan context mismatch")
    if closeout["dispatch_plan"]["record_revision"] != plan["record_revision"]:
        raise CloseoutError("closeout Plan record revision mismatch")
    if closeout["master_card"]["record_revision"] != master["record_revision"]:
        raise CloseoutError("closeout Master record revision mismatch")
    if closeout["master_card"]["state"] != master["state"]:
        raise CloseoutError("closeout Master state mismatch")
    if (closeout["master_card"]["release_task_id"], closeout["master_card"]["plan_revision"],
            closeout["master_card"]["dispatch_plan_digest"], closeout["master_card"]["frozen_baseline_sha"]) != (
                master["release_task_id"], master["plan_revision"], master["dispatch_plan_digest"],
                master["frozen_baseline_sha"]):
        raise CloseoutError("closeout Master release-lock context mismatch")
    if closeout["dispatch_plan"]["archive_digest"] != digest_bytes(plan_bytes):
        raise CloseoutError("closeout Plan archive digest mismatch")
    if closeout["master_card"]["archive_digest"] != digest_bytes(master_bytes):
        raise CloseoutError("closeout Master archive digest mismatch")
    candidate = master["candidate_evidence"]
    if closeout["candidate"]["value_digest"] != value_digest(candidate):
        raise CloseoutError("closeout candidate digest mismatch")
    if closeout["git"]["final_release_head_sha"] != head or closeout["git"]["final_release_tree_sha"] != tree:
        raise CloseoutError("closeout Git binding mismatch")
    if closeout["master_card"]["handoff_count"] != len(master["worker_handoffs"]):
        raise CloseoutError("closeout handoff count does not match archived Master")
    if closeout["master_card"]["handoff_array_digest"] != value_digest(master["worker_handoffs"]):
        raise CloseoutError("closeout handoff digest does not match archived Master")
    if parse_rfc3339(closeout["created_at"], "closeout.created_at") <= parse_rfc3339(
            master["updated_at"], "Master Card.updated_at"):
        raise CloseoutError("closeout timestamp does not advance the ACTIVE Master snapshot")


def archive_paths(archive: Path) -> tuple[Path, Path, Path]:
    return tuple(archive / name for name in ARCHIVE_NAMES)  # type: ignore[return-value]


def close_release(*, repo_root: Path, plan_path: Path, master_card_path: Path,
                  worker_card_paths: list[Path] | None = None, release_task_id: str | None = None,
                  now: str | None = None) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    plan_path = plan_path.resolve(strict=False)
    plan_bytes, plan = read_json_bytes(plan_path, "Dispatch Plan")
    schema = load_json(repo_root / "references" / "contracts.schema.json")
    try:
        validate_plan(plan, schema)
        specs = load_persisted_plan_specs(plan, schema)
    except (ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise CloseoutError(f"Plan validation failed: {error}") from error
    worker_paths = select_worker_card_paths(plan, worker_card_paths)
    workers = load_worker_cards(worker_paths, schema)
    archive = archive_directory(plan)
    check_archive_directory(archive)
    plan_archive_path, master_archive_path, closeout_path = archive_paths(archive)

    require_regular_file(master_card_path, "live Master Card")
    live_master_bytes, live_master = read_json_bytes(master_card_path, "Master Card")
    try:
        validate_master_card(live_master, schema)
    except (ContractError, KeyError, TypeError) as error:
        raise CloseoutError(f"Master Card validation failed: {error}") from error

    if live_master["state"] == "IDLE":
        if not all(os.path.lexists(path) for path in (plan_archive_path, master_archive_path, closeout_path)):
            raise CloseoutError("IDLE Master has no complete matching closeout archive")
        require_regular_file(plan_archive_path, "archived Dispatch Plan")
        require_regular_file(master_archive_path, "archived ACTIVE Master Card")
        require_regular_file(closeout_path, "closeout record")
        archived_plan_bytes, archived_plan = read_json_bytes(plan_archive_path, "archived Dispatch Plan")
        archived_master_bytes, archived_master = read_json_bytes(master_archive_path, "archived ACTIVE Master Card")
        closeout_bytes, closeout = read_json_bytes(closeout_path, "closeout record")
        if archived_plan_bytes != plan_bytes:
            raise CloseoutError("archived Plan bytes conflict with the supplied Plan")
        if archived_master["state"] != "ACTIVE":
            raise CloseoutError("archived Master snapshot is not ACTIVE")
        try:
            validate_plan(archived_plan, schema)
            archived_specs = load_persisted_plan_specs(archived_plan, schema)
            validate_master_card(archived_master, schema)
        except (ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
            raise CloseoutError(f"archived source validation failed: {error}") from error
        head, tree = validate_sources(
            repo_root, plan_path, archived_plan, archived_specs, archived_master, workers,
            release_task_id, schema,
        )
        assert_sources_unchanged(plan_path, plan_bytes, plan, specs, workers, schema)
        verify_closeout_links(closeout, archived_plan, archived_master, plan_bytes, archived_master_bytes,
                              head, tree, schema)
        expected_idle = idle_projection(archived_master, closeout["created_at"])
        try:
            validate_master_card(expected_idle, schema)
            validate_master_transition(
                archived_master, expected_idle, schema, allow_closeout_candidate_reset=True,
            )
        except (ContractError, KeyError, TypeError) as error:
            raise CloseoutError(f"expected IDLE projection is invalid: {error}") from error
        expected_idle_bytes = compact_json(expected_idle)
        if live_master_bytes != expected_idle_bytes:
            raise CloseoutError("live IDLE Master Card does not match the archived closeout projection")
        return {"status": "PASS", "archive": str(archive), "live_master": "IDLE", "idempotent": True}

    if live_master["state"] != "ACTIVE":
        raise CloseoutError("closeout requires an ACTIVE or already-completed IDLE Master Card")
    try:
        head, tree = validate_sources(
            repo_root, plan_path, plan, specs, live_master, workers, release_task_id, schema,
        )
    except (ContractError, KeyError, TypeError) as error:
        raise CloseoutError(f"closeout precondition failed: {error}") from error

    if os.path.lexists(closeout_path):
        if not os.path.lexists(plan_archive_path) or not os.path.lexists(master_archive_path):
            raise CloseoutError("closeout record exists without both immutable source snapshots")
        require_regular_file(plan_archive_path, "archived Dispatch Plan")
        require_regular_file(master_archive_path, "archived ACTIVE Master Card")
        require_regular_file(closeout_path, "closeout record")
        archived_plan_bytes, archived_plan = read_json_bytes(plan_archive_path, "archived Dispatch Plan")
        archived_master_bytes, archived_master = read_json_bytes(master_archive_path, "archived ACTIVE Master Card")
        closeout_bytes, closeout = read_json_bytes(closeout_path, "closeout record")
        if archived_plan_bytes != plan_bytes or archived_master_bytes != live_master_bytes:
            raise CloseoutError("existing immutable archive conflicts with current closeout inputs")
        if archived_plan != plan or archived_master != live_master:
            raise CloseoutError("existing archive parsed values conflict with current closeout inputs")
        verify_closeout_links(closeout, plan, live_master, plan_bytes, live_master_bytes, head, tree, schema)
    else:
        closeout_timestamp = timestamp_after(live_master["updated_at"], now)
        closeout = build_closeout(plan, live_master, plan_bytes, live_master_bytes, head, tree, closeout_timestamp)
        closeout_bytes = compact_json(closeout)
        try:
            validate_release_closeout(closeout, schema)
        except (ContractError, KeyError, TypeError) as error:
            raise CloseoutError(f"constructed closeout is invalid: {error}") from error

    expected_idle = idle_projection(live_master, closeout["created_at"])
    try:
        validate_master_card(expected_idle, schema)
        validate_master_transition(
            live_master, expected_idle, schema, allow_closeout_candidate_reset=True,
        )
    except (ContractError, KeyError, TypeError) as error:
        raise CloseoutError(f"expected IDLE projection is invalid: {error}") from error
    expected_idle_bytes = compact_json(expected_idle)

    assert_sources_unchanged(plan_path, plan_bytes, plan, specs, workers, schema)
    require_regular_file(master_card_path, "live Master Card")
    assert_source_bytes(master_card_path, live_master_bytes, "live Master Card")
    assert_git_snapshot(repo_root, head, tree)
    for path, expected in (
        (plan_archive_path, plan_bytes),
        (master_archive_path, live_master_bytes),
        (closeout_path, closeout_bytes),
    ):
        existing_bytes(path, expected)
    check_archive_directory(archive)
    archive.mkdir(parents=True, exist_ok=True)
    write_once(plan_archive_path, plan_bytes)
    if plan_archive_path.read_bytes() != plan_bytes:
        raise CloseoutError("Plan archive readback mismatch")
    assert_sources_unchanged(plan_path, plan_bytes, plan, specs, workers, schema)
    require_regular_file(master_card_path, "live Master Card")
    assert_source_bytes(master_card_path, live_master_bytes, "live Master Card")
    assert_git_snapshot(repo_root, head, tree)
    write_once(master_archive_path, live_master_bytes)
    if master_archive_path.read_bytes() != live_master_bytes:
        raise CloseoutError("ACTIVE Master archive readback mismatch")
    assert_sources_unchanged(plan_path, plan_bytes, plan, specs, workers, schema)
    require_regular_file(master_card_path, "live Master Card")
    assert_source_bytes(master_card_path, live_master_bytes, "live Master Card")
    assert_git_snapshot(repo_root, head, tree)
    write_once(closeout_path, closeout_bytes)
    readback_closeout_bytes, readback_closeout = read_json_bytes(closeout_path, "closeout record")
    if readback_closeout_bytes != closeout_bytes:
        raise CloseoutError("closeout archive readback bytes changed")
    verify_closeout_links(readback_closeout, plan, live_master, plan_bytes, live_master_bytes, head, tree, schema)
    assert_sources_unchanged(plan_path, plan_bytes, plan, specs, workers, schema)
    require_regular_file(master_card_path, "live Master Card")
    assert_source_bytes(master_card_path, live_master_bytes, "live Master Card")
    assert_git_snapshot(repo_root, head, tree)

    current_live_bytes = master_card_path.read_bytes()
    if current_live_bytes == expected_idle_bytes:
        return {"status": "PASS", "archive": str(archive), "live_master": "IDLE", "idempotent": True}
    if current_live_bytes != live_master_bytes:
        raise CloseoutError("live Master Card changed before closeout transition")
    replaced = replace_live(master_card_path, live_master_bytes, expected_idle_bytes)
    final_bytes, final_master = read_json_bytes(master_card_path, "live Master Card")
    if final_bytes != expected_idle_bytes:
        raise CloseoutError("live Master Card closeout readback mismatch")
    try:
        validate_master_card(final_master, schema)
        validate_master_transition(
            live_master, final_master, schema, allow_closeout_candidate_reset=True,
        )
    except (ContractError, KeyError, TypeError) as error:
        raise CloseoutError(f"live Master closeout readback is invalid: {error}") from error
    if final_master["worker_handoffs"] != live_master["worker_handoffs"]:
        raise CloseoutError("live Master closeout did not preserve worker_handoffs")
    return {"status": "PASS", "archive": str(archive), "live_master": "IDLE", "idempotent": not replaced}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--master-card-json", type=Path)
    parser.add_argument("--worker-card-json", type=Path, action="append", default=[])
    parser.add_argument("--release-task-id")
    parser.add_argument("--now", help="RFC 3339 timestamp for deterministic local tests")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    plan = args.plan or repo_root / ".codex" / "multi-worktree-release" / "dispatch-plan.json"
    master = args.master_card_json or repo_root / ".codex" / "multi-worktree-release" / "master-card.json"
    try:
        result = close_release(
            repo_root=repo_root,
            plan_path=plan,
            master_card_path=master,
            worker_card_paths=list(args.worker_card_json),
            release_task_id=args.release_task_id,
            now=args.now,
        )
    except (CloseoutError, ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print(f"release closeout: FAIL {error}", file=sys.stderr)
        return 1
    print(
        f"release closeout: PASS archive={result['archive']} live_master={result['live_master']} "
        f"idempotent={str(result['idempotent']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

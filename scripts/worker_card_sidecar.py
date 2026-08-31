#!/usr/bin/env python3
"""Bootstrap one canonical, ignored Worker Card sidecar from Master evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_contracts import (  # noqa: E402
    ContractError,
    canonical_json,
    default_authorization_v2,
    load_json,
    load_persisted_plan_specs,
    validate_cross_record_set,
    validate_master_card,
    validate_plan,
    validate_worker_card,
    value_digest,
)


SIDECAR_NAME = "WORKTREE_TASK.json"
TERMINAL_DISPATCH_STATES = {"INTEGRATED", "CANCELLED", "SUPERSEDED"}


class SidecarError(ValueError):
    """A fail-closed sidecar precondition or persistence error."""


def _absolute(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise SidecarError(f"{label} must be an absolute path")
    return path


def _reject_symlink_components(path: Path, label: str) -> Path:
    """Reject symlinks in the supplied path without resolving through them."""
    path = _absolute(path, label)
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            is_link = current.is_symlink()
        except OSError as error:
            raise SidecarError(f"cannot inspect {label} at {current}: {error}") from error
        # macOS exposes /var and /tmp as root-level compatibility aliases;
        # reject user-created path links below those OS boundaries.
        if is_link and current not in {Path("/var"), Path("/tmp"), Path("/home")}:
            raise SidecarError(f"{label} contains a symlink component: {current}")
    return path


def _canonical(path: Path, label: str) -> Path:
    path = _reject_symlink_components(path, label)
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise SidecarError(f"cannot canonicalize {label}: {error}") from error


def _regular_file(path: Path, label: str) -> Path:
    path = _reject_symlink_components(path, label)
    if not path.is_file():
        raise SidecarError(f"{label} is not a regular file: {path}")
    return path


def _directory(path: Path, label: str) -> Path:
    path = _canonical(path, label)
    if not path.is_dir() or path.is_symlink():
        raise SidecarError(f"{label} is not a regular directory: {path}")
    return path


def _read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    _regular_file(path, label)
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SidecarError(f"{label} is not valid UTF-8 JSON at {path}: {error}") from error
    if not isinstance(value, dict):
        raise SidecarError(f"{label} must be a JSON object: {path}")
    return raw, value


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _existing_or_install(path: Path, data: bytes) -> bool:
    """Install exact bytes once; return False when equal bytes already exist."""
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            raise SidecarError(f"Worker Card sidecar is not a regular file: {path}")
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise SidecarError(f"cannot read existing Worker Card sidecar: {error}") from error
        if existing != data:
            raise SidecarError(f"conflicting bytes at Worker Card sidecar: {path}")
        return False

    if not path.parent.is_dir() or path.parent.is_symlink():
        raise SidecarError(f"Worker Card sidecar parent is not a regular directory: {path.parent}")
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
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise SidecarError(f"conflicting bytes at Worker Card sidecar: {path}")
            return False
        _sync_directory(path.parent)
        return True
    except SidecarError:
        raise
    except OSError as error:
        raise SidecarError(f"cannot atomically install Worker Card sidecar: {error}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise SidecarError(f"sidecar installed but temporary sibling remains: {temporary}") from error


def _idle_card(updated_at: str, handoff: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "IDLE",
        "record_revision": 1,
        "updated_at": updated_at,
        "task_id": None,
        "task_spec_revision": None,
        "task_spec_digest": None,
        "task_spec_path": None,
        "plan_revision": None,
        "dispatch_wave": None,
        "source_thread_id": None,
        "issued_at": None,
        "supersedes_task_id": None,
        "worker_generation": None,
        "frozen_baseline_sha": None,
        "allowed_paths": [],
        "forbidden_paths": [],
        "authorization": default_authorization_v2(),
        "acceptance_commands": [],
        "blocker_kind": None,
        "blocked_since": None,
        "recovery_owner": None,
        "blocker": None,
        "worker_commit_sha": None,
        "integrated_as_sha": None,
        "release_head_sha": None,
        "last_task": {
            "task_id": handoff["task_id"],
            "task_spec_revision": handoff["task_spec_revision"],
            "task_spec_digest": handoff["task_spec_digest"],
            "outcome": "COMPLETED",
            "worker_commit_sha": handoff["worker_commit_sha"],
            "integrated_as_sha": handoff["integrated_as_sha"],
        },
    }


def _matching_handoff(plan: dict[str, Any], specs: dict[str, dict[str, Any]],
                      master: dict[str, Any], task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    entries = {task["task_id"]: task for task in plan["tasks"]}
    entry = entries.get(task_id)
    spec = specs.get(task_id)
    if entry is None or spec is None:
        raise SidecarError(f"task is absent from the current Plan: {task_id}")
    if entry["dispatch_status"] != "INTEGRATED":
        raise SidecarError("sidecar bootstrap requires an INTEGRATED Dispatch entry")
    matches = [handoff for handoff in master["worker_handoffs"]
               if (handoff["task_id"], handoff["task_spec_revision"], handoff["task_spec_digest"])
               == (entry["task_id"], entry["task_spec_revision"], entry["task_spec_digest"])]
    integrated = [handoff for handoff in matches if handoff["state"] == "INTEGRATED"]
    if len(integrated) != 1:
        raise SidecarError("current task lacks exactly one matching INTEGRATED Master handoff")
    handoff = integrated[0]
    expected = {
        "role": spec["owner_role"],
        "task_spec_revision": entry["task_spec_revision"],
        "task_spec_digest": entry["task_spec_digest"],
        "plan_revision": entry["task_spec_plan_revision"],
        "dispatch_wave": entry["dispatch_wave"],
        "source_thread_id": spec["source_thread_id"],
        "frozen_baseline_sha": entry["expected_head"],
        "authorization_envelope_digest": spec["authorization"]["envelope_digest"],
        "acceptance_digest": value_digest(spec["acceptance"]),
    }
    mismatch = [field for field, value in expected.items() if handoff.get(field) != value]
    if mismatch or handoff.get("integrated_as_sha") is None:
        raise SidecarError(f"matching Master handoff identity mismatch: {mismatch or ['integrated_as_sha']}")
    return spec, handoff


def _validate_inputs(repo_root: Path, plan_path: Path, master_card_path: Path,
                     task_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any],
                                              dict[str, Any], Path]:
    repo_root = _directory(repo_root, "Master repository")
    plan_path = _regular_file(_canonical(plan_path, "Dispatch Plan"), "Dispatch Plan")
    master_card_path = _regular_file(_canonical(master_card_path, "Master Card"), "Master Card")
    _, plan = _read_json(plan_path, "Dispatch Plan")
    schema_path = _canonical(repo_root / "references" / "contracts.schema.json", "contract Schema")
    try:
        schema = load_json(schema_path)
        validate_plan(plan, schema)
        specs = load_persisted_plan_specs(plan, schema)
    except (ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise SidecarError(f"Plan validation failed: {error}") from error
    _, master = _read_json(master_card_path, "Master Card")
    try:
        validate_master_card(master, schema)
        validate_cross_record_set(plan, None, master, plan_path, specs)
    except (ContractError, KeyError, TypeError) as error:
        raise SidecarError(f"Master/Plan validation failed: {error}") from error
    if master["state"] != "ACTIVE" or master["blocker"] is not None:
        raise SidecarError("sidecar bootstrap requires an ACTIVE, unblocked Master Card")
    if any(task["dispatch_status"] not in TERMINAL_DISPATCH_STATES for task in plan["tasks"]):
        raise SidecarError("sidecar bootstrap requires a terminal current Plan")
    try:
        spec, handoff = _matching_handoff(plan, specs, master, task_id)
    except (ContractError, KeyError, TypeError) as error:
        raise SidecarError(f"Master handoff validation failed: {error}") from error
    worktree = _directory(Path(spec["worktree"]), "Worker worktree")
    return plan, spec, handoff, master, schema, worktree


def bootstrap_worker_card(*, repo_root: Path, plan_path: Path, master_card_path: Path,
                          task_id: str, worker_card_path: Path | None = None) -> dict[str, Any]:
    """Create or verify one IDLE sidecar from terminal Plan/Master evidence."""
    if not isinstance(task_id, str) or not task_id:
        raise SidecarError("task_id must be a non-empty string")
    _, _, handoff, master, schema, worktree = _validate_inputs(
        repo_root, plan_path, master_card_path, task_id,
    )
    expected_path = worktree / SIDECAR_NAME
    target = expected_path if worker_card_path is None else _canonical(worker_card_path, "Worker Card sidecar")
    if target != expected_path:
        raise SidecarError("Worker Card sidecar must be exactly beside its bound Worker worktree")
    if target.name != SIDECAR_NAME:
        raise SidecarError(f"Worker Card sidecar must be named {SIDECAR_NAME}")
    card = _idle_card(master["updated_at"], handoff)
    try:
        validate_worker_card(card, schema)
    except (ContractError, KeyError, TypeError) as error:
        raise SidecarError(f"constructed Worker Card is invalid: {error}") from error
    data = canonical_json(card)

    if target.exists():
        raw, existing = _read_json(target, "Worker Card sidecar")
        try:
            validate_worker_card(existing, schema)
        except (ContractError, KeyError, TypeError) as error:
            raise SidecarError(f"existing Worker Card sidecar is invalid: {error}") from error
        if existing["state"] != "IDLE":
            raise SidecarError("sidecar bootstrap cannot alter a non-IDLE Worker Card")
        if raw != data:
            raise SidecarError(f"existing Worker Card sidecar conflicts with Master evidence: {target}")
        return existing

    _existing_or_install(target, data)
    readback, result = _read_json(target, "Worker Card sidecar")
    if readback != data:
        raise SidecarError("Worker Card sidecar readback bytes changed")
    try:
        validate_worker_card(result, schema)
    except (ContractError, KeyError, TypeError) as error:
        raise SidecarError(f"Worker Card sidecar readback is invalid: {error}") from error
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--master-card-json", type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--worker-card-json", "--worker-card-path", dest="worker_card_json", type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    plan_path = args.plan or repo_root / ".codex" / "multi-worktree-release" / "dispatch-plan.json"
    master_card_path = args.master_card_json or repo_root / ".codex" / "multi-worktree-release" / "master-card.json"
    try:
        card = bootstrap_worker_card(
            repo_root=repo_root,
            plan_path=plan_path,
            master_card_path=master_card_path,
            task_id=args.task_id,
            worker_card_path=args.worker_card_json,
        )
    except (SidecarError, ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print(f"worker card sidecar: FAIL {error}", file=sys.stderr)
        return 1
    print(f"worker card sidecar: PASS path={args.worker_card_json or '<derived>'} state={card['state']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

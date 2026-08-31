#!/usr/bin/env python3
"""Persist one canonical Worker Card sidecar from Master or Worker evidence."""

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
    validate_worker_transition,
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


def _load_context(repo_root: Path, plan_path: Path, master_card_path: Path) -> tuple[
    dict[str, Any], dict[str, dict[str, Any]], dict[str, Any], dict[str, Any], Path
]:
    """Load and validate the current Master-owned records without writing them."""
    repo_root = _directory(repo_root, "Master repository")
    plan_path = _regular_file(_canonical(plan_path, "Dispatch Plan"), "Dispatch Plan")
    master_card_path = _regular_file(_canonical(master_card_path, "Master Card"), "Master Card")
    schema_path = _regular_file(
        _canonical(repo_root / "references" / "contracts.schema.json", "contract Schema"),
        "contract Schema",
    )
    try:
        schema = load_json(schema_path)
        _, plan = _read_json(plan_path, "Dispatch Plan")
        validate_plan(plan, schema)
        specs = load_persisted_plan_specs(plan, schema)
        _, master = _read_json(master_card_path, "Master Card")
        validate_master_card(master, schema)
        validate_cross_record_set(plan, None, master, plan_path, specs)
    except (ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        raise SidecarError(f"Master/Plan validation failed: {error}") from error
    if master["state"] != "ACTIVE" or master["blocker"] is not None:
        raise SidecarError("Worker Card transition requires an ACTIVE, unblocked Master Card")
    return plan, specs, master, schema, plan_path


def _resolve_task_id(task_id: str | None, card: dict[str, Any], worker_card_path: Path | None,
                    specs: dict[str, dict[str, Any]]) -> str:
    if task_id is not None:
        if not isinstance(task_id, str) or not task_id:
            raise SidecarError("task_id must be a non-empty string")
        return task_id
    card_task_id = card.get("task_id")
    if isinstance(card_task_id, str) and card_task_id:
        return card_task_id
    if worker_card_path is None:
        raise SidecarError("IDLE Worker Card transition requires task_id or an existing sidecar path")
    target = _canonical(worker_card_path, "Worker Card sidecar")
    candidates = [task_id for task_id, spec in specs.items()
                  if _canonical(Path(spec["worktree"]) / SIDECAR_NAME, "Worker worktree sidecar") == target]
    if len(candidates) != 1:
        raise SidecarError(f"sidecar path does not identify exactly one Plan task: {target}")
    return candidates[0]


def _expected_sidecar(spec: dict[str, Any]) -> Path:
    worktree = _directory(Path(spec["worktree"]), "Worker worktree")
    return worktree / SIDECAR_NAME


def _handoff_matches(master: dict[str, Any], card: dict[str, Any]) -> list[dict[str, Any]]:
    identity = (card["task_id"], card["task_spec_revision"], card["task_spec_digest"],
                card["source_thread_id"])
    return [handoff for handoff in master["worker_handoffs"]
            if (handoff["task_id"], handoff["task_spec_revision"], handoff["task_spec_digest"],
                handoff["source_thread_id"]) == identity]


def _handoff_mismatches(handoff: dict[str, Any], entry: dict[str, Any],
                        spec: dict[str, Any]) -> list[str]:
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
    return [field for field, value in expected.items() if handoff.get(field) != value]


def _require_rework_handoff(master: dict[str, Any], entry: dict[str, Any], spec: dict[str, Any],
                            current: dict[str, Any], previous: dict[str, Any] | None = None) -> None:
    if previous is None:
        candidates = [handoff for handoff in master["worker_handoffs"]
                      if handoff["state"] == "REWORK_REQUESTED"
                      and handoff["task_id"] == current["task_id"]
                      and handoff["source_thread_id"] == current["source_thread_id"]
                      and handoff["task_spec_revision"] < current["task_spec_revision"]]
    else:
        candidates = [handoff for handoff in master["worker_handoffs"]
                      if handoff["state"] == "REWORK_REQUESTED"
                      and (handoff["task_id"], handoff["task_spec_revision"],
                           handoff["task_spec_digest"], handoff["source_thread_id"])
                      == (previous["task_id"], previous["task_spec_revision"],
                          previous["task_spec_digest"], previous["source_thread_id"])]
    if len(candidates) != 1:
        raise SidecarError("Worker reactivation requires exactly one preserved REWORK_REQUESTED handoff")
    handoff = candidates[0]
    mismatches = []
    if handoff["role"] != spec["owner_role"]:
        mismatches.append("role")
    if handoff["frozen_baseline_sha"] != entry["expected_head"]:
        mismatches.append("frozen_baseline_sha")
    if handoff["authorization_envelope_digest"] != spec["authorization"]["envelope_digest"]:
        mismatches.append("authorization_envelope_digest")
    if handoff["plan_revision"] >= current["plan_revision"]:
        mismatches.append("plan_revision")
    if handoff["worker_commit_sha"] is None or handoff["integrated_as_sha"] is not None:
        mismatches.append("worker_commit_sha/integrated_as_sha")
    if previous is not None and previous["worker_commit_sha"] is not None:
        if handoff["worker_commit_sha"] != previous["worker_commit_sha"]:
            mismatches.append("worker_commit_sha")
    if mismatches:
        raise SidecarError(f"preserved rework handoff mismatch: {mismatches}")


def _validate_received_handoff(master: dict[str, Any], entry: dict[str, Any], spec: dict[str, Any],
                               card: dict[str, Any]) -> None:
    """Validate an acknowledgment when Master has already recorded this handoff.

    A Worker may publish its AWAITING record before Master appends RECEIVED.  In
    that interval the current PUBLISHED Plan and the validated Worker commit are
    the available evidence; a conflicting or malformed existing acknowledgment
    is never ignored.
    """
    matches = _handoff_matches(master, card)
    if not matches:
        return
    if len(matches) != 1:
        raise SidecarError("current task has duplicate Master handoff identities")
    handoff = matches[0]
    mismatches = _handoff_mismatches(handoff, entry, spec)
    if handoff["state"] != "RECEIVED":
        mismatches.append("state")
    if handoff["worker_commit_sha"] != card["worker_commit_sha"]:
        mismatches.append("worker_commit_sha")
    if handoff["integrated_as_sha"] is not None:
        mismatches.append("integrated_as_sha")
    if mismatches:
        raise SidecarError(f"current Master RECEIVED handoff mismatch: {mismatches}")


def _validate_current_card(card: dict[str, Any], plan: dict[str, Any],
                           specs: dict[str, dict[str, Any]], master: dict[str, Any],
                           schema: dict[str, Any], plan_path: Path) -> None:
    try:
        validate_worker_card(card, schema)
        if card["state"] == "AWAITING_INTEGRATION":
            # The Worker writes this handoff before Master acknowledges receipt.
            validate_cross_record_set(plan, card, None, plan_path, specs)
            entry = next(task for task in plan["tasks"] if task["task_id"] == card["task_id"])
            _validate_received_handoff(master, entry, specs[card["task_id"]], card)
        else:
            validate_cross_record_set(plan, card, master, plan_path, specs)
    except (ContractError, KeyError, StopIteration, TypeError) as error:
        raise SidecarError(f"Worker Card validation failed: {error}") from error


def _read_canonical_card(path: Path, schema: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    raw, card = _read_json(path, "Worker Card sidecar")
    try:
        validate_worker_card(card, schema)
        canonical = canonical_json(card)
    except (ContractError, KeyError, TypeError) as error:
        raise SidecarError(f"existing Worker Card sidecar is invalid: {error}") from error
    if raw != canonical:
        raise SidecarError("Worker Card sidecar is not canonical JSON")
    return raw, card


def _replace_if_unchanged(path: Path, expected: bytes, data: bytes) -> bool:
    """Atomically replace one canonical sidecar only when its bytes are unchanged."""
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            raise SidecarError(f"Worker Card sidecar is not a regular file: {path}")
        try:
            current = path.read_bytes()
        except OSError as error:
            raise SidecarError(f"cannot read Worker Card sidecar before replace: {error}") from error
        if current == data:
            return False
        if current != expected:
            raise SidecarError(f"Worker Card sidecar bytes changed during transition: {path}")
    else:
        raise SidecarError(f"Worker Card sidecar disappeared during transition: {path}")

    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise SidecarError(f"Worker Card sidecar bytes changed during transition: {path}")
        try:
            os.replace(temporary, path)
        except OSError as error:
            raise SidecarError(f"cannot atomically replace Worker Card sidecar: {error}") from error
        _sync_directory(path.parent)
        try:
            readback = path.read_bytes()
        except OSError as error:
            raise SidecarError(f"cannot read Worker Card sidecar after replace: {error}") from error
        if readback != data:
            raise SidecarError("Worker Card sidecar readback bytes changed")
        return True
    except SidecarError:
        raise
    except OSError as error:
        raise SidecarError(f"cannot atomically replace Worker Card sidecar: {error}") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise SidecarError(f"sidecar replaced but temporary sibling remains: {temporary}") from error


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


def _validate_transition_evidence(previous: dict[str, Any], current: dict[str, Any],
                                  plan: dict[str, Any], spec: dict[str, Any],
                                  master: dict[str, Any]) -> None:
    try:
        transition = validate_worker_transition(previous, current)
    except ContractError as error:
        raise SidecarError(f"Worker Card transition is invalid: {error}") from error
    if transition == "NOOP":
        return
    if previous["state"] == current["state"]:
        raise SidecarError("Worker Card sidecar accepts state transitions, not same-state rewrites")

    transition_task_id = current["task_id"] or previous["task_id"]
    entry = next(task for task in plan["tasks"] if task["task_id"] == transition_task_id)
    previous_revision = previous["task_spec_revision"]
    previous_history_revision = previous["last_task"]["task_spec_revision"]
    old_revision = previous_revision if previous_revision is not None else previous_history_revision
    if current["state"] == "ACTIVE":
        rework = previous["state"] == "AWAITING_INTEGRATION"
        rework = rework or (old_revision is not None and current["task_spec_revision"] > old_revision)
        if rework:
            _require_rework_handoff(master, entry, spec, current, previous)
    elif current["state"] == "AWAITING_INTEGRATION":
        _validate_received_handoff(master, entry, spec, current)


def _validate_initial_activation(card: dict[str, Any], entry: dict[str, Any], spec: dict[str, Any],
                                 master: dict[str, Any]) -> None:
    if card["state"] != "ACTIVE":
        raise SidecarError("missing prior Worker Card is allowed only for ACTIVE activation")
    if card["task_spec_revision"] > 1:
        _require_rework_handoff(master, entry, spec, card)


def transition_worker_card(*, repo_root: Path, plan_path: Path, master_card_path: Path,
                           card: dict[str, Any], task_id: str | None = None,
                           worker_card_path: Path | None = None) -> dict[str, Any]:
    """Atomically persist one Worker-owned complete JSON Card transition.

    The input is a JSON object supplied by the Worker; the Markdown projection
    is deliberately outside this operation.  A missing sidecar is accepted only
    for a validated ACTIVE activation.  Every later write compares the exact
    previous canonical bytes before replacing the fixed sidecar path.
    """
    if not isinstance(card, dict):
        raise SidecarError("Worker Card transition requires a complete JSON object")
    plan, specs, master, schema, plan_path = _load_context(repo_root, plan_path, master_card_path)
    resolved_task_id = _resolve_task_id(task_id, card, worker_card_path, specs)
    spec = specs.get(resolved_task_id)
    if spec is None:
        raise SidecarError(f"task is absent from the current Plan: {resolved_task_id}")
    entry = next((task for task in plan["tasks"] if task["task_id"] == resolved_task_id), None)
    if entry is None:
        raise SidecarError(f"task is absent from the current Plan: {resolved_task_id}")
    target_expected = _expected_sidecar(spec)
    target = target_expected if worker_card_path is None else _canonical(worker_card_path, "Worker Card sidecar")
    if target != target_expected or target.name != SIDECAR_NAME:
        raise SidecarError("Worker Card sidecar must be exactly beside its bound Worker worktree")

    _validate_current_card(card, plan, specs, master, schema, plan_path)
    data = canonical_json(card)
    if os.path.lexists(target):
        raw, previous = _read_canonical_card(target, schema)
        if raw == data:
            return card
        _validate_transition_evidence(previous, card, plan, spec, master)
        _replace_if_unchanged(target, raw, data)
    else:
        _validate_initial_activation(card, entry, spec, master)
        _existing_or_install(target, data)

    readback, result = _read_canonical_card(target, schema)
    if readback != data:
        raise SidecarError("Worker Card sidecar readback bytes changed")
    _validate_current_card(result, plan, specs, master, schema, plan_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--master-card-json", type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--worker-card-json", "--worker-card-path", dest="worker_card_json", type=Path)
    parser.add_argument("--transition", action="store_true")
    parser.add_argument("--card-json", "--transition-card-json", dest="transition_card_json", type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    plan_path = args.plan or repo_root / ".codex" / "multi-worktree-release" / "dispatch-plan.json"
    master_card_path = args.master_card_json or repo_root / ".codex" / "multi-worktree-release" / "master-card.json"
    try:
        if args.transition:
            if args.transition_card_json is None:
                raise SidecarError("--transition requires --card-json")
            _, card = _read_json(
                _canonical(args.transition_card_json, "transition Worker Card input"),
                "transition Worker Card input",
            )
            card = transition_worker_card(
                repo_root=repo_root,
                plan_path=plan_path,
                master_card_path=master_card_path,
                task_id=args.task_id,
                worker_card_path=args.worker_card_json,
                card=card,
            )
        else:
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

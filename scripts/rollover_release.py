#!/usr/bin/env python3
"""Atomically open a new v1 STRICT release after a verified closeout."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import close_release  # noqa: E402
from validate_contracts import (  # noqa: E402
    ContractError,
    RELEASE_TASK_ID_RE,
    canonical_json,
    load_json,
    load_persisted_plan_specs,
    make_plan_snapshot_ref,
    object_digest,
    parse_rfc3339,
    validate_cross_record_set,
    validate_master_card,
    validate_master_transition,
    validate_plan,
    validate_release_closeout,
    validate_release_rollover,
    value_digest,
)


class RolloverError(ValueError):
    """A fail-closed release-rollover precondition or persistence error."""


def read_json_bytes(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise RolloverError(f"cannot read {label} at {path}: {error}") from error
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RolloverError(f"{label} is not valid UTF-8 JSON at {path}: {error}") from error
    if not isinstance(value, dict):
        raise RolloverError(f"{label} must be a JSON object")
    return raw, value


def digest_bytes(value: bytes) -> str:
    return close_release.digest_bytes(value)


def require_regular_file(path: Path, label: str) -> None:
    if not os.path.lexists(path) or path.is_symlink() or not path.is_file():
        raise RolloverError(f"{label} is not a regular file: {path}")


def safe_release_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not RELEASE_TASK_ID_RE.fullmatch(value):
        raise RolloverError(f"{label} is not a safe release_task_id")
    return value


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def safe_rollover_receipt_path(state_root: Path, next_release_task_id: str) -> Path:
    if not state_root.is_absolute():
        raise RolloverError("state_root must be absolute")
    try:
        root = state_root.resolve(strict=False)
        boundary = (root / "history" / "rollovers").resolve(strict=False)
        receipt = (boundary / f"{next_release_task_id}.json").resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise RolloverError(f"cannot canonicalize rollover receipt path: {error}") from error
    if not path_is_within(boundary, root) or not path_is_within(receipt, boundary):
        raise RolloverError("rollover receipt path escapes state_root/history/rollovers")
    return receipt


def verify_receipt_path(path: Path) -> None:
    parent = path.parent
    current = Path(parent.anchor)
    for component in parent.parts[1:]:
        current /= component
        if current.is_symlink():
            raise RolloverError(f"rollover receipt path contains a symlink component: {current}")
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
        raise RolloverError(f"rollover receipt is not a regular file: {path}")


def verify_archive(*, repo_root: Path, live_plan_path: Path, state_root: Path,
                   previous_release: str, schema: dict[str, Any]
                   ) -> tuple[dict[str, Any], dict[str, Any], bytes, dict[str, Any], bytes,
                              dict[str, Any], bytes]:
    previous_release = safe_release_id(previous_release, "previous release_task_id")
    state_root = state_root.resolve(strict=False)
    archive = state_root / "history" / "releases" / previous_release
    plan_path = archive / "dispatch-plan.json"
    master_path = archive / "master-card.active.json"
    closeout_path = archive / "closeout.json"
    for path, label in ((plan_path, "archived Dispatch Plan"),
                        (master_path, "archived ACTIVE Master Card"),
                        (closeout_path, "release closeout")):
        require_regular_file(path, label)
    archived_plan_bytes, archived_plan = read_json_bytes(plan_path, "archived Dispatch Plan")
    archived_master_bytes, archived_master = read_json_bytes(master_path, "archived ACTIVE Master Card")
    closeout_bytes, closeout = read_json_bytes(closeout_path, "release closeout")
    try:
        validate_release_closeout(closeout, schema)
        validate_plan(archived_plan, schema)
        archived_specs = load_persisted_plan_specs(archived_plan, schema, historical=True)
        validate_master_card(archived_master, schema, historical=True)
        archived_ref = make_plan_snapshot_ref(
            plan_path, archived_plan, live_plan_path.resolve(strict=False), "previous",
        )
        validate_cross_record_set(archived_plan, None, archived_master, plan_path, archived_specs, archived_ref)
    except (ContractError, OSError, json.JSONDecodeError) as error:
        raise RolloverError(f"archived release is invalid: {error}") from error
    if closeout["release_task_id"] != previous_release:
        raise RolloverError("closeout release_task_id differs from live Plan")
    if closeout["dispatch_plan"]["archive_digest"] != digest_bytes(archived_plan_bytes):
        raise RolloverError("closeout archived Plan digest mismatch")
    if closeout["master_card"]["archive_digest"] != digest_bytes(archived_master_bytes):
        raise RolloverError("closeout archived Master digest mismatch")
    if closeout["worker_handoffs"]["array_digest"] != value_digest(archived_master["worker_handoffs"]):
        raise RolloverError("closeout Worker handoff digest mismatch")
    if closeout["worker_handoffs"]["count"] != len(archived_master["worker_handoffs"]):
        raise RolloverError("closeout Worker handoff count mismatch")
    release_head = closeout["git"]["final_release_head_sha"]
    result = subprocess.run(
        ["git", "show", "-s", "--format=%T", release_head],
        cwd=repo_root, text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise RolloverError("closeout release HEAD is no longer reachable")
    release_tree = result.stdout.strip()
    try:
        close_release.verify_closeout_links(
            closeout, archived_plan, archived_master, archived_plan_bytes, archived_master_bytes,
            release_head, release_tree, schema,
        )
    except close_release.CloseoutError as error:
        raise RolloverError(f"archived closeout semantics are invalid: {error}") from error
    expected_idle = close_release.idle_projection(archived_master, closeout["created_at"])
    expected_idle_bytes = canonical_json(expected_idle)
    try:
        validate_master_card(expected_idle, schema)
        validate_master_transition(
            archived_master, expected_idle, schema, allow_closeout_candidate_reset=True,
        )
    except ContractError as error:
        raise RolloverError(f"closeout IDLE projection is invalid: {error}") from error
    return (
        closeout, archived_plan, archived_plan_bytes, archived_master,
        archived_master_bytes, expected_idle, expected_idle_bytes,
    )


def validate_target(*, repo_root: Path, live_plan_path: Path,
                    source_plan: dict[str, Any], source_master: dict[str, Any],
                    target_plan: dict[str, Any], target_master: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        validate_plan(target_plan, schema)
        target_specs = load_persisted_plan_specs(target_plan, schema)
        validate_master_card(target_master, schema)
        validate_cross_record_set(target_plan, None, target_master, live_plan_path, target_specs)
        validate_master_transition(
            source_master, target_master, schema, allow_release_rollover=True,
        )
    except (ContractError, OSError, json.JSONDecodeError) as error:
        raise RolloverError(f"next release target is invalid: {error}") from error
    if Path(target_plan["state_root"]).resolve(strict=False) != Path(source_plan["state_root"]).resolve(strict=False):
        raise RolloverError("next Plan state_root differs from the closed release")
    if Path(target_plan["task_specs_root"]).resolve(strict=False) != Path(source_plan["task_specs_root"]).resolve(strict=False):
        raise RolloverError("next Plan task_specs_root differs from the closed release")
    if target_plan["release_task_id"] == source_plan["release_task_id"]:
        raise RolloverError("next Plan must use a new release_task_id")
    if target_plan["plan_revision"] != 1 or target_plan["record_revision"] != 1:
        raise RolloverError("a new release must start at plan_revision=1 and record_revision=1")
    if target_master["state"] != "ACTIVE" or target_master["worker_handoffs"]:
        raise RolloverError("next Master must be ACTIVE with no inherited Worker handoffs")
    if target_master["candidate_evidence"] != close_release.empty_live_candidate():
        raise RolloverError("next Master must start with the canonical empty candidate")
    if target_master["record_revision"] != source_master["record_revision"] + 1:
        raise RolloverError("next Master record_revision must advance exactly once")
    source_time = parse_rfc3339(source_master["updated_at"], "source Master updated_at")
    target_time = parse_rfc3339(target_master["updated_at"], "target Master updated_at")
    if target_time <= source_time:
        raise RolloverError("next Master updated_at must advance")
    head, _ = close_release.git_snapshot(repo_root)
    if target_master["frozen_baseline_sha"] != head:
        raise RolloverError("next Master frozen baseline differs from current Git HEAD")
    if not target_plan["tasks"]:
        raise RolloverError("next release must contain at least one published or gated task")
    if any(task["expected_head"] != head for task in target_plan["tasks"]):
        raise RolloverError("next Plan task baseline differs from current Git HEAD")


def build_receipt(*, source_plan: dict[str, Any], source_plan_bytes: bytes,
                  source_master_bytes: bytes, closeout: dict[str, Any],
                  target_plan: dict[str, Any], target_plan_bytes: bytes,
                  target_master_bytes: bytes) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "record_kind": "release-rollover",
        "rollover_revision": 1,
        "state_root": source_plan["state_root"],
        "issued_by": target_plan["issued_by"],
        "created_at": target_plan["updated_at"],
        "previous_release_task_id": source_plan["release_task_id"],
        "previous_closeout": {
            "locator": f"history/releases/{source_plan['release_task_id']}/closeout.json",
            "closeout_digest": closeout["closeout_digest"],
            "dispatch_plan_digest": closeout["dispatch_plan"]["archive_digest"],
            "master_card_digest": closeout["master_card"]["archive_digest"],
        },
        "next_release_task_id": target_plan["release_task_id"],
        "source_live_plan": {"locator": "dispatch-plan.json", "value_digest": digest_bytes(source_plan_bytes)},
        "source_live_master_card": {
            "locator": "master-card.json", "value_digest": digest_bytes(source_master_bytes),
        },
        "target_live_plan": {"locator": "dispatch-plan.json", "value_digest": digest_bytes(target_plan_bytes)},
        "target_live_master_card": {
            "locator": "master-card.json", "value_digest": digest_bytes(target_master_bytes),
        },
        "rollover_digest": None,
    }
    receipt["rollover_digest"] = object_digest(receipt, "rollover_digest")
    return receipt


def receipt_matches(receipt: dict[str, Any], expected: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        validate_release_rollover(receipt, schema)
    except ContractError as error:
        raise RolloverError(f"existing rollover receipt is invalid: {error}") from error
    if receipt != expected:
        raise RolloverError("existing rollover receipt conflicts with requested release transition")


def replace_live(path: Path, expected: bytes, replacement: bytes, label: str) -> bool:
    try:
        return close_release.replace_live(path, expected, replacement)
    except close_release.CloseoutError as error:
        raise RolloverError(f"cannot replace live {label}: {error}") from error


def rollover_release(*, repo_root: Path, plan_path: Path, master_card_path: Path,
                     next_plan_path: Path, next_master_card_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    plan_path = plan_path.resolve(strict=False)
    master_card_path = master_card_path.resolve(strict=False)
    next_plan_path = next_plan_path.resolve(strict=False)
    next_master_card_path = next_master_card_path.resolve(strict=False)
    if next_plan_path == plan_path or next_master_card_path == master_card_path:
        raise RolloverError("next release staging inputs must not be the live Plan or Master paths")
    require_regular_file(plan_path, "live Dispatch Plan")
    require_regular_file(master_card_path, "live Master Card")
    require_regular_file(next_plan_path, "next Dispatch Plan staging input")
    require_regular_file(next_master_card_path, "next Master Card staging input")
    current_plan_bytes, current_plan = read_json_bytes(plan_path, "live Dispatch Plan")
    current_master_bytes, _current_master = read_json_bytes(master_card_path, "live Master Card")
    target_plan_bytes, target_plan = read_json_bytes(next_plan_path, "next Dispatch Plan")
    target_master_bytes, target_master = read_json_bytes(next_master_card_path, "next Master Card")
    schema = load_json(repo_root / "references" / "contracts.schema.json")
    if not isinstance(schema, dict):
        raise RolloverError("contracts schema is not an object")
    try:
        validate_plan(target_plan, schema)
    except ContractError as error:
        raise RolloverError(f"next Dispatch Plan staging input is invalid: {error}") from error
    receipt_path = safe_rollover_receipt_path(Path(target_plan["state_root"]), target_plan["release_task_id"])
    verify_receipt_path(receipt_path)
    existing_receipt = None
    if os.path.lexists(receipt_path):
        _, existing_receipt = read_json_bytes(receipt_path, "existing rollover receipt")
        try:
            validate_release_rollover(existing_receipt, schema)
        except ContractError as error:
            raise RolloverError(f"existing rollover receipt is invalid: {error}") from error
        previous_release = existing_receipt["previous_release_task_id"]
    else:
        try:
            validate_plan(current_plan, schema)
        except ContractError as error:
            raise RolloverError(f"live Dispatch Plan is invalid: {error}") from error
        previous_release = current_plan["release_task_id"]
    (
        closeout, source_plan, source_plan_bytes, _, _, source_master,
        source_master_bytes,
    ) = verify_archive(
        repo_root=repo_root, live_plan_path=plan_path, state_root=Path(target_plan["state_root"]),
        previous_release=previous_release, schema=schema,
    )
    if Path(source_plan["state_root"]).resolve(strict=False) != Path(target_plan["state_root"]).resolve(strict=False):
        raise RolloverError("next Plan state_root differs from the closed release")
    if current_plan_bytes not in {source_plan_bytes, target_plan_bytes}:
        raise RolloverError("live Dispatch Plan differs from both the closeout source and rollover target")
    if current_master_bytes not in {source_master_bytes, target_master_bytes}:
        raise RolloverError("live Master Card differs from both the closeout source and rollover target")
    if current_plan_bytes == source_plan_bytes and current_master_bytes != source_master_bytes:
        raise RolloverError("live Master Card differs from the closeout IDLE projection")
    if current_plan_bytes == target_plan_bytes and current_master_bytes not in {source_master_bytes, target_master_bytes}:
        raise RolloverError("interrupted rollover has an unknown live Master Card")
    validate_target(
        repo_root=repo_root, live_plan_path=plan_path,
        source_plan=source_plan, source_master=source_master, target_plan=target_plan,
        target_master=target_master, schema=schema,
    )
    receipt = build_receipt(
        source_plan=source_plan, source_plan_bytes=source_plan_bytes,
        source_master_bytes=source_master_bytes, closeout=closeout,
        target_plan=target_plan, target_plan_bytes=target_plan_bytes,
        target_master_bytes=target_master_bytes,
    )
    try:
        validate_release_rollover(receipt, schema)
    except ContractError as error:
        raise RolloverError(f"constructed rollover receipt is invalid: {error}") from error
    receipt_bytes = canonical_json(receipt)
    if existing_receipt is not None:
        existing_bytes, existing = read_json_bytes(receipt_path, "existing rollover receipt")
        receipt_matches(existing, receipt, schema)
        if existing_bytes != receipt_bytes:
            raise RolloverError("existing rollover receipt bytes are non-canonical")
    else:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            close_release.write_once(receipt_path, receipt_bytes)
        except close_release.CloseoutError as error:
            raise RolloverError(f"cannot install rollover receipt: {error}") from error
        if receipt_path.read_bytes() != receipt_bytes:
            raise RolloverError("rollover receipt readback mismatch")

    replaced_plan = replace_live(plan_path, source_plan_bytes, target_plan_bytes, "Dispatch Plan")
    current_plan_bytes, current_plan = read_json_bytes(plan_path, "live Dispatch Plan")
    if current_plan_bytes != target_plan_bytes or current_plan != target_plan:
        raise RolloverError("live Dispatch Plan rollover readback mismatch")
    replaced_master = replace_live(master_card_path, source_master_bytes, target_master_bytes, "Master Card")
    current_master_bytes, current_master = read_json_bytes(master_card_path, "live Master Card")
    if current_master_bytes != target_master_bytes or current_master != target_master:
        raise RolloverError("live Master Card rollover readback mismatch")
    try:
        specs = load_persisted_plan_specs(target_plan, schema)
        validate_cross_record_set(target_plan, None, target_master, plan_path, specs)
        validate_release_rollover(load_json(receipt_path), schema)
    except (ContractError, OSError, json.JSONDecodeError) as error:
        raise RolloverError(f"rollover readback validation failed: {error}") from error
    return {
        "status": "PASS",
        "receipt": str(receipt_path),
        "idempotent": not replaced_plan and not replaced_master,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--master-card-json", type=Path)
    parser.add_argument("--next-plan-json", type=Path, required=True)
    parser.add_argument("--next-master-card-json", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    plan = args.plan or repo_root / ".codex" / "multi-worktree-release" / "dispatch-plan.json"
    master = args.master_card_json or repo_root / ".codex" / "multi-worktree-release" / "master-card.json"
    try:
        result = rollover_release(
            repo_root=repo_root, plan_path=plan, master_card_path=master,
            next_plan_path=args.next_plan_json, next_master_card_path=args.next_master_card_json,
        )
    except (RolloverError, ContractError, OSError, json.JSONDecodeError) as error:
        print(f"release rollover: FAIL {error}", file=sys.stderr)
        return 1
    print(f"release rollover: PASS receipt={result['receipt']} idempotent={str(result['idempotent']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

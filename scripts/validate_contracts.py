#!/usr/bin/env python3
"""Validate multi-worktree release contracts without third-party packages."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SUPERSEDE_FIELDS = {"objective", "owner_role", "worktree", "expected_head", "authorization"}
DISPATCH_TRANSITIONS = {
    "GATED": {"READY", "CANCELLED", "SUPERSEDED"},
    "READY": {"PUBLISHED", "CANCELLED", "SUPERSEDED"},
    "PUBLISHED": {"BLOCKED", "INTEGRATED", "CANCELLED", "SUPERSEDED"},
    "BLOCKED": {"PUBLISHED", "CANCELLED", "SUPERSEDED"},
    "INTEGRATED": set(),
    "CANCELLED": set(),
    "SUPERSEDED": set(),
}
WORKER_TRANSITIONS = {
    "IDLE": {"ACTIVE"},
    "ACTIVE": {"AWAITING_INTEGRATION", "BLOCKED", "IDLE"},
    "AWAITING_INTEGRATION": {"ACTIVE", "BLOCKED", "IDLE"},
    "BLOCKED": {"ACTIVE", "IDLE"},
}
MASTER_TRANSITIONS = {
    "IDLE": {"ACTIVE"},
    "ACTIVE": {"BLOCKED", "IDLE"},
    "BLOCKED": {"ACTIVE", "IDLE"},
}
HANDOFF_TRANSITIONS = {
    "RECEIVED": {"INTEGRATED", "REWORK_REQUESTED"},
    "INTEGRATED": set(),
    "REWORK_REQUESTED": set(),
}
TERMINAL_DISPATCH_STATES = {"INTEGRATED", "CANCELLED", "SUPERSEDED"}
HISTORICAL_DIAGNOSTIC_IDS = tuple(f"H{number:02d}" for number in range(1, 32))
HISTORICAL_CLI_PAIRS = (
    ("previous_plan", "plan", "H01", "--previous-plan requires --plan"),
    ("previous_worker_card", "worker_card_json", "H02",
     "--previous-worker-card requires --worker-card-json"),
    ("previous_master_card", "master_card_json", "H03",
     "--previous-master-card requires --master-card-json"),
)
WORKER_ASSIGNMENT_FIELDS = (
    "task_id", "task_spec_revision", "task_spec_digest", "task_spec_path", "plan_revision", "dispatch_wave",
    "source_thread_id", "issued_at", "supersedes_task_id", "worker_generation", "frozen_baseline_sha",
    "allowed_paths", "forbidden_paths", "authorization", "acceptance_commands",
)
HANDOFF_IDENTITY_FIELDS = ("task_id", "task_spec_revision", "task_spec_digest", "source_thread_id")


class ContractError(ValueError):
    pass


class HistoricalUsageError(ValueError):
    pass


def historical_error(diagnostic_id: str, message: str) -> None:
    if diagnostic_id not in HISTORICAL_DIAGNOSTIC_IDS:
        raise AssertionError(f"unknown historical diagnostic ID: {diagnostic_id}")
    raise ContractError(f"[{diagnostic_id}] {message}")


def canonical_json(value: Any) -> bytes:
    ensure_canonical_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def ensure_canonical_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise ContractError(f"floating-point digest input is forbidden at {path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            ensure_canonical_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"non-string object key is forbidden at {path}")
            ensure_canonical_value(item, f"{path}.{key}")
        return
    raise ContractError(f"unsupported digest input type at {path}: {type(value).__name__}")


def object_digest(value: dict[str, Any], digest_field: str) -> str:
    candidate = copy.deepcopy(value)
    candidate[digest_field] = None
    return "sha256:" + hashlib.sha256(canonical_json(candidate)).hexdigest()


def value_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_previous_json(path: Path, label: str) -> Any:
    try:
        return load_json(path)
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError) as error:
        historical_error("H04", f"cannot read previous {label} at {path}: {error}")
    except json.JSONDecodeError as error:
        historical_error("H05", f"previous {label} is not valid JSON at {path}: {error}")


def require_exact_fields(value: dict[str, Any], required: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing or extra:
        raise ContractError(f"{label} field mismatch; missing={missing}, extra={extra}")


def schema_required(schema: dict[str, Any], definition: str) -> set[str]:
    return set(schema["$defs"][definition]["required"])


def validate_positive_integer(value: Any, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContractError(f"{label} must be a positive integer")


def validate_digest(value: Any, label: str, allow_null: bool = False) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise ContractError(f"{label} must use sha256:<64-lowercase-hex>")


def validate_sha(value: Any, label: str, allow_null: bool = False) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ContractError(f"{label} must be a full 40-character lowercase Git SHA")


def parse_rfc3339(value: Any, label: str, allow_null: bool = False) -> dt.datetime | None:
    if value is None and allow_null:
        return None
    if not isinstance(value, str):
        raise ContractError(f"{label} must be an RFC 3339 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError(f"{label} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return parsed


def validate_rfc3339(value: Any, label: str, allow_null: bool = False) -> None:
    parse_rfc3339(value, label, allow_null=allow_null)


def validate_authorization(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "authorization"), "authorization")
    if value["schema_version"] != 1:
        raise ContractError("authorization.schema_version must be 1")
    for field in ("real_external_call", "create_execution", "publish", "destructive_operation", "fresh_execution_required"):
        if not isinstance(value[field], bool):
            raise ContractError(f"authorization.{field} must be boolean")
    if not isinstance(value["max_calls"], int) or isinstance(value["max_calls"], bool) or value["max_calls"] < 0:
        raise ContractError("authorization.max_calls must be a non-negative integer")
    if not isinstance(value["max_cost"], int) or isinstance(value["max_cost"], bool) or value["max_cost"] < 0:
        raise ContractError("authorization.max_cost must be a non-negative integer")
    if value["fresh_execution_required"] and value["resume_execution_id"] is not None:
        raise ContractError("fresh execution and resume ID are mutually exclusive")
    validate_digest(value["controlled_input_digest"], "controlled_input_digest", allow_null=True)
    validate_digest(value["envelope_digest"], "envelope_digest", allow_null=True)
    validate_rfc3339(value["expires_at"], "authorization.expires_at", allow_null=True)
    if value["envelope_digest"] is not None:
        expected = object_digest(value, "envelope_digest")
        if value["envelope_digest"] != expected:
            raise ContractError("authorization envelope digest mismatch")
    if value["controlled_input"] is not None:
        if value["controlled_input_digest"] != value_digest(value["controlled_input"]):
            raise ContractError("controlled-input digest mismatch")
    allowed = any(value[field] for field in
                  ("real_external_call", "create_execution", "publish", "destructive_operation"))
    if allowed:
        required_context = ("target", "controlled_input", "controlled_input_digest", "route", "provider", "expires_at")
        missing = [field for field in required_context if value[field] is None]
        if missing:
            raise ContractError(f"allowed authority is missing bounded context: {missing}")
    if (value["real_external_call"] or value["create_execution"]) and value["max_calls"] < 1:
        raise ContractError("external calls or executions require a positive max_calls limit")
    if value["max_cost"] > 0 and value["cost_unit"] is None:
        raise ContractError("positive max_cost requires cost_unit")


def validate_task_spec(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "task_spec"), "task spec")
    if value["schema_version"] != 1:
        raise ContractError("task_spec.schema_version must be 1")
    validate_positive_integer(value["task_spec_revision"], "task_spec.task_spec_revision")
    validate_positive_integer(value["plan_revision"], "task_spec.plan_revision")
    validate_positive_integer(value["dispatch_wave"], "task_spec.dispatch_wave")
    validate_authorization(value["authorization"], schema)
    validate_rfc3339(value["issued_at"], "task_spec.issued_at")
    for field in ("task_spec_path", "worktree"):
        if not Path(value[field]).is_absolute():
            raise ContractError(f"task_spec.{field} must be absolute")
    validate_sha(value["expected_head"], "task_spec.expected_head")
    validate_digest(value["task_spec_digest"], "task_spec_digest")
    if value["task_spec_digest"] != object_digest(value, "task_spec_digest"):
        raise ContractError("task spec digest mismatch")


def validate_plan(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "dispatch_plan"), "dispatch plan")
    require_exact_fields(value["validation"], schema_required(schema, "plan_validation"), "plan validation")
    validate_positive_integer(value["record_revision"], "dispatch_plan.record_revision")
    validate_positive_integer(value["plan_revision"], "dispatch_plan.plan_revision")
    validate_rfc3339(value["issued_at"], "dispatch_plan.issued_at")
    validate_rfc3339(value["updated_at"], "dispatch_plan.updated_at")
    for field in ("state_root", "task_specs_root"):
        if not Path(value[field]).is_absolute():
            raise ContractError(f"dispatch plan {field} must be absolute")
    validate_digest(value["plan_digest"], "plan_digest")
    if value["plan_digest"] != object_digest(value, "plan_digest"):
        raise ContractError("dispatch plan digest mismatch")
    task_required = schema_required(schema, "dispatch_task")
    ids: list[str] = []
    entries: dict[str, dict[str, Any]] = {}
    active_worktrees: dict[str, str] = {}
    for task in value["tasks"]:
        require_exact_fields(task, task_required, "dispatch task")
        task_id = task["task_id"]
        validate_positive_integer(task["task_spec_revision"], f"{task_id}.task_spec_revision")
        validate_positive_integer(task["task_spec_plan_revision"], f"{task_id}.task_spec_plan_revision")
        validate_positive_integer(task["dispatch_wave"], f"{task_id}.dispatch_wave")
        if task_id in entries:
            raise ContractError(f"duplicate task ID: {task_id}")
        ids.append(task_id)
        entries[task_id] = task
        for field in ("task_spec_path", "worktree"):
            if not Path(task[field]).is_absolute():
                raise ContractError(f"{task_id}.{field} must be absolute")
        validate_sha(task["expected_head"], f"{task_id}.expected_head")
        if task["dispatch_status"] not in set(
                schema["$defs"]["dispatch_task"]["properties"]["dispatch_status"]["enum"]):
            raise ContractError(f"unknown Dispatch status for {task_id}: {task['dispatch_status']}")
        if task["revision_decision"] not in set(
                schema["$defs"]["dispatch_task"]["properties"]["revision_decision"]["enum"]):
            raise ContractError(f"unknown revision decision for {task_id}: {task['revision_decision']}")
        if task["dispatch_status"] not in {"INTEGRATED", "SUPERSEDED", "CANCELLED"}:
            prior = active_worktrees.get(task["worktree"])
            if prior:
                raise ContractError(f"active tasks {prior} and {task_id} share worktree {task['worktree']}")
            active_worktrees[task["worktree"]] = task_id
        for field in ("task_spec_digest", "acceptance_digest", "authorization_envelope_digest"):
            validate_digest(task[field], f"{task_id}.{field}")
        decision = task["revision_decision"]
        issued_plan = task["task_spec_plan_revision"]
        if issued_plan > value["plan_revision"]:
            raise ContractError(f"{task_id} was issued under a future plan revision")
        if decision in {"NEW", "REVISE"} and issued_plan != value["plan_revision"]:
            raise ContractError(f"{task_id} {decision} must bind to the current plan revision")
        if decision == "GRANDFATHER" and issued_plan >= value["plan_revision"]:
            raise ContractError(f"{task_id} GRANDFATHER must preserve an older task-spec plan revision")
    known = set(ids)
    for task_id, task in entries.items():
        unknown = (set(task["blocked_by"]) | set(task["parallel_with"])) - known
        if unknown:
            raise ContractError(f"{task_id} references unknown tasks: {sorted(unknown)}")
        for peer in task["parallel_with"]:
            if task_id not in entries[peer]["parallel_with"]:
                raise ContractError(f"parallel_with is not symmetric: {task_id}, {peer}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ContractError(f"dependency cycle includes {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in entries[task_id]["blocked_by"]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in ids:
        visit(task_id)
    ready_statuses = {"READY", "PUBLISHED", "INTEGRATED"}
    if any(task["dispatch_status"] in ready_statuses for task in entries.values()):
        pass_fields = set(schema_required(schema, "plan_validation")) - {"semantic_ownership_overlap"}
        failed = [field for field in pass_fields if value["validation"][field] != "PASS"]
        if failed or value["validation"]["semantic_ownership_overlap"] != "NONE":
            raise ContractError(f"ready/published plan has failed validation: {failed}")


def load_persisted_plan_specs(value: dict[str, Any], schema: dict[str, Any],
                              historical: bool = False) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for entry in value["tasks"]:
        path = Path(entry["task_spec_path"])
        if not path.is_file():
            if historical:
                historical_error("H16", f"historical persisted task spec not found: {path}")
            raise ContractError(f"persisted task spec not found: {path}")
        try:
            spec = load_json(path)
            validate_task_spec(spec, schema)
        except (ContractError, OSError, json.JSONDecodeError) as error:
            if historical:
                historical_error("H16", f"historical persisted task spec is unverifiable at {path}: {error}")
            raise
        equality = {
            "task_id": "task_id",
            "task_spec_revision": "task_spec_revision",
            "task_spec_digest": "task_spec_digest",
            "task_spec_path": "task_spec_path",
            "task_spec_plan_revision": "plan_revision",
            "owner_role": "owner_role",
            "worktree": "worktree",
            "branch": "branch",
            "expected_head": "expected_head",
        }
        mismatched = [entry_field for entry_field, spec_field in equality.items()
                      if entry[entry_field] != spec[spec_field]]
        if mismatched:
            if historical:
                historical_error("H16", f"historical plan/task-spec mismatch for {entry['task_id']}: {mismatched}")
            raise ContractError(f"plan/task-spec mismatch for {entry['task_id']}: {mismatched}")
        if entry["authorization_envelope_digest"] != spec["authorization"]["envelope_digest"]:
            if historical:
                historical_error("H16", f"historical authorization digest mismatch for {entry['task_id']}")
            raise ContractError(f"authorization digest mismatch for {entry['task_id']}")
        if entry["acceptance_digest"] != value_digest(spec["acceptance"]):
            if historical:
                historical_error("H16", f"historical acceptance digest mismatch for {entry['task_id']}")
            raise ContractError(f"acceptance digest mismatch for {entry['task_id']}")
        specs[entry["task_id"]] = spec
    return specs


def validate_persisted_plan_specs(value: dict[str, Any], schema: dict[str, Any]) -> None:
    load_persisted_plan_specs(value, schema)


def validate_worker_card(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "worker_card"), "Worker card")
    if value["schema_version"] != 1:
        raise ContractError("worker_card.schema_version must be 1")
    validate_positive_integer(value["record_revision"], "worker_card.record_revision")
    validate_authorization(value["authorization"], schema)
    validate_rfc3339(value["updated_at"], "worker_card.updated_at")
    validate_rfc3339(value["issued_at"], "worker_card.issued_at", allow_null=True)
    states = set(schema["$defs"]["worker_state"]["enum"])
    if value["state"] not in states:
        raise ContractError(f"unknown Worker state: {value['state']}")
    require_exact_fields(value["last_task"], schema_required(schema, "last_task"), "last_task")
    validate_digest(value["task_spec_digest"], "task_spec_digest", allow_null=True)
    validate_digest(value["last_task"]["task_spec_digest"], "last_task.task_spec_digest", allow_null=True)
    for field in ("frozen_baseline_sha", "worker_commit_sha", "integrated_as_sha", "release_head_sha"):
        validate_sha(value[field], f"worker_card.{field}", allow_null=True)
    for field in ("worker_commit_sha", "integrated_as_sha"):
        validate_sha(value["last_task"][field], f"last_task.{field}", allow_null=True)
    validate_rfc3339(value["blocked_since"], "worker_card.blocked_since", allow_null=True)
    if value["state"] == "IDLE":
        nullable_lock_fields = (
            "task_id", "task_spec_revision", "task_spec_digest", "task_spec_path", "plan_revision", "dispatch_wave",
            "source_thread_id", "issued_at", "supersedes_task_id", "worker_generation", "frozen_baseline_sha",
            "blocker_kind", "blocked_since", "recovery_owner", "blocker", "worker_commit_sha", "integrated_as_sha",
            "release_head_sha",
        )
        uncleared = [field for field in nullable_lock_fields if value[field] is not None]
        if uncleared or value["allowed_paths"] or value["forbidden_paths"] or value["acceptance_commands"]:
            raise ContractError(f"IDLE Worker card retains active lock fields: {uncleared}")
        denied = default_authorization()
        if value["authorization"] != denied:
            raise ContractError("IDLE Worker card authorization must be the canonical default-deny envelope")
    else:
        required_lock_fields = ("task_id", "task_spec_revision", "task_spec_digest", "task_spec_path", "plan_revision",
                                "dispatch_wave", "source_thread_id", "issued_at", "worker_generation", "frozen_baseline_sha")
        missing = [field for field in required_lock_fields if value[field] is None]
        if missing:
            raise ContractError(f"non-IDLE Worker card is missing lock fields: {missing}")
        for field in ("task_spec_revision", "plan_revision", "dispatch_wave"):
            validate_positive_integer(value[field], f"worker_card.{field}")
        if not Path(value["task_spec_path"]).is_absolute():
            raise ContractError("worker_card.task_spec_path must be absolute")
    if value["state"] == "AWAITING_INTEGRATION" and value["worker_commit_sha"] is None:
        historical_error("H17", "AWAITING_INTEGRATION Worker card requires worker_commit_sha")
    if value["state"] in {"ACTIVE", "AWAITING_INTEGRATION"}:
        blocker_fields = ("blocker_kind", "blocked_since", "recovery_owner", "blocker")
        stale = [field for field in blocker_fields if value[field] is not None]
        if stale:
            raise ContractError(f"{value['state']} Worker card retains blocker evidence: {stale}")
    if value["state"] == "ACTIVE" and any(
            value[field] is not None for field in ("worker_commit_sha", "integrated_as_sha", "release_head_sha")):
        raise ContractError("ACTIVE Worker card retains commit or release evidence")
    if value["state"] == "AWAITING_INTEGRATION" and any(
            value[field] is not None for field in ("integrated_as_sha", "release_head_sha")):
        historical_error("H17", "AWAITING_INTEGRATION cannot retain integration or release evidence")
    if value["state"] == "BLOCKED":
        required_blocker_fields = ("blocker_kind", "blocker", "blocked_since", "recovery_owner")
        missing = [field for field in required_blocker_fields if value[field] is None]
        if missing:
            historical_error("H21", f"BLOCKED Worker card is missing recovery evidence: {missing}")
        if value["integrated_as_sha"] is not None or value["release_head_sha"] is not None:
            historical_error("H21", "BLOCKED Worker card cannot retain integration or release evidence")
    last_task = value["last_task"]
    if last_task["task_id"] is None:
        stale = [field for field, item in last_task.items() if field != "task_id" and item is not None]
        if stale:
            raise ContractError(f"empty last_task retains historical fields: {stale}")
    else:
        required_history = ("task_spec_revision", "task_spec_digest", "outcome")
        missing = [field for field in required_history if last_task[field] is None]
        if missing:
            raise ContractError(f"last_task is missing completed identity fields: {missing}")


def validate_master_card(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "master_card"), "Master card")
    if value["schema_version"] != 1:
        raise ContractError("master_card.schema_version must be 1")
    validate_positive_integer(value["record_revision"], "master_card.record_revision")
    if value["state"] not in set(schema["$defs"]["master_state"]["enum"]):
        raise ContractError(f"unknown Master state: {value['state']}")
    validate_rfc3339(value["updated_at"], "master_card.updated_at")
    validate_digest(value["dispatch_plan_digest"], "dispatch_plan_digest", allow_null=True)
    validate_sha(value["frozen_baseline_sha"], "master_card.frozen_baseline_sha", allow_null=True)
    handoff_required = schema_required(schema, "worker_handoff")
    handoff_identities: set[tuple[Any, ...]] = set()
    for handoff in value["worker_handoffs"]:
        require_exact_fields(handoff, handoff_required, "Worker handoff")
        identity = tuple(handoff[field] for field in HANDOFF_IDENTITY_FIELDS)
        if identity in handoff_identities:
            raise ContractError(f"duplicate Worker handoff identity: {identity}")
        handoff_identities.add(identity)
        validate_positive_integer(handoff["task_spec_revision"], "handoff.task_spec_revision")
        validate_positive_integer(handoff["plan_revision"], "handoff.plan_revision")
        validate_positive_integer(handoff["dispatch_wave"], "handoff.dispatch_wave")
        for field in ("task_spec_digest", "authorization_envelope_digest", "acceptance_digest"):
            validate_digest(handoff[field], f"handoff.{field}")
        if handoff["state"] not in set(schema["$defs"]["worker_handoff"]["properties"]["state"]["enum"]):
            raise ContractError(f"unknown Worker handoff state: {handoff['state']}")
        validate_sha(handoff["frozen_baseline_sha"], "handoff.frozen_baseline_sha")
        validate_sha(handoff["worker_commit_sha"], "handoff.worker_commit_sha")
        validate_sha(handoff["integrated_as_sha"], "handoff.integrated_as_sha", allow_null=True)
        if handoff["state"] == "INTEGRATED" and handoff["integrated_as_sha"] is None:
            historical_error("H23", "INTEGRATED Worker handoff requires integrated_as_sha")
        if handoff["state"] != "INTEGRATED" and handoff["integrated_as_sha"] is not None:
            raise ContractError(f"{handoff['state']} Worker handoff cannot retain integrated_as_sha")
    evidence = value["candidate_evidence"]
    require_exact_fields(evidence, schema_required(schema, "candidate_evidence"), "candidate evidence")
    validate_digest(evidence["gate_input_digest"], "gate_input_digest", allow_null=True)
    validate_sha(evidence["release_head_sha"], "candidate release_head_sha", allow_null=True)
    if evidence["status"] not in set(schema["$defs"]["candidate_evidence"]["properties"]["status"]["enum"]):
        raise ContractError(f"unknown candidate status: {evidence['status']}")
    for check in evidence["checks"]:
        require_exact_fields(check, {"command", "result", "evidence_digest"}, "candidate check")
        if not isinstance(check["command"], str) or not check["command"]:
            raise ContractError("candidate check command must be non-empty")
        if check["result"] not in {"PASS", "FAIL"}:
            raise ContractError(f"unknown candidate check result: {check['result']}")
        validate_digest(check["evidence_digest"], "candidate check evidence_digest")
    if evidence["status"] == "NONE" and any((evidence["release_head_sha"], evidence["gate_input_digest"], evidence["checks"])):
        historical_error("H24", "candidate status NONE cannot retain candidate evidence")
    if evidence["status"] in {"STALE", "PASSED", "FAILED"} and (
        evidence["release_head_sha"] is None or evidence["gate_input_digest"] is None or not evidence["checks"]
    ):
        raise ContractError(f"candidate status {evidence['status']} requires HEAD, gate digest, and checks")
    if value["state"] == "IDLE" and any(value[field] is not None for field in
                                           ("release_task_id", "plan_revision", "dispatch_plan_path", "dispatch_plan_digest",
                                            "frozen_baseline_sha", "blocker")):
        raise ContractError("IDLE Master card retains active release lock fields")
    if value["state"] != "IDLE":
        required_lock_fields = ("release_task_id", "plan_revision", "dispatch_plan_path", "dispatch_plan_digest",
                                "frozen_baseline_sha")
        missing = [field for field in required_lock_fields if value[field] is None]
        if missing:
            raise ContractError(f"non-IDLE Master card is missing release lock fields: {missing}")
        validate_positive_integer(value["plan_revision"], "master_card.plan_revision")
        if not Path(value["dispatch_plan_path"]).is_absolute():
            raise ContractError("master_card.dispatch_plan_path must be absolute")
    if value["state"] == "BLOCKED" and value["blocker"] is None:
        raise ContractError("BLOCKED Master card requires blocker evidence")
    if value["state"] == "ACTIVE" and value["blocker"] is not None:
        raise ContractError("ACTIVE Master card retains blocker evidence")


def classify_task_change(old: dict[str, Any], new: dict[str, Any]) -> str:
    if old["task_id"] != new["task_id"]:
        return "SUPERSEDE"
    if any(old.get(field) != new.get(field) for field in SUPERSEDE_FIELDS):
        return "SUPERSEDE"
    old_compare = {key: value for key, value in old.items() if key not in {"task_spec_revision", "task_spec_digest", "plan_revision"}}
    new_compare = {key: value for key, value in new.items() if key not in {"task_spec_revision", "task_spec_digest", "plan_revision"}}
    if old_compare == new_compare:
        return "GRANDFATHER"
    if new["task_spec_revision"] <= old["task_spec_revision"]:
        raise ContractError("changed executable content requires a higher task revision")
    if new["task_spec_digest"] == old["task_spec_digest"]:
        raise ContractError("changed executable content requires a new task-spec digest")
    return "REVISE"


def candidate_invalidation(old_head: str, new_head: str, old_gate_digest: str, new_gate_digest: str) -> str:
    if old_head != new_head:
        return "ALL"
    if old_gate_digest != new_gate_digest:
        return "AFFECTED"
    return "NONE"


def validate_previous_pairing(args: argparse.Namespace) -> None:
    for previous_field, current_field, diagnostic_id, message in HISTORICAL_CLI_PAIRS:
        if getattr(args, previous_field, None) is not None and getattr(args, current_field, None) is None:
            raise HistoricalUsageError(f"[{diagnostic_id}] {message}")


def historical_mode(args: argparse.Namespace) -> bool:
    return any(getattr(args, previous_field, None) is not None
               for previous_field, _, _, _ in HISTORICAL_CLI_PAIRS)


def validate_historical_schema_pair(previous: Any, current: Any, label: str) -> None:
    if not isinstance(previous, dict) or not isinstance(current, dict):
        historical_error("H06", f"{label} snapshots must be complete JSON objects")
    if previous.get("schema_version") != 1 or current.get("schema_version") != 1:
        historical_error("H06", f"{label} previous/current schema_version must both be 1")


def validate_record_transition(previous: dict[str, Any], current: dict[str, Any], label: str) -> str:
    validate_historical_schema_pair(previous, current, label)
    previous_revision = previous.get("record_revision")
    current_revision = current.get("record_revision")
    validate_positive_integer(previous_revision, f"previous {label}.record_revision")
    validate_positive_integer(current_revision, f"current {label}.record_revision")
    if current_revision < previous_revision:
        historical_error("H07", f"{label} record_revision regressed: {previous_revision} -> {current_revision}")
    previous_time = parse_rfc3339(previous.get("updated_at"), f"previous {label}.updated_at")
    current_time = parse_rfc3339(current.get("updated_at"), f"current {label}.updated_at")
    if current_time < previous_time:
        historical_error("H09", f"{label} updated_at moved backwards")
    if current_revision == previous_revision:
        if current != previous:
            historical_error("H08", f"{label} changed without incrementing record_revision")
        return "NOOP"
    return "FORWARD"


def plan_semantic_projection(plan: dict[str, Any]) -> dict[str, Any]:
    projection = copy.deepcopy(plan)
    for field in ("record_revision", "updated_at", "plan_digest", "validation", "ready_wave", "blocked_tasks"):
        projection.pop(field, None)
    for task in projection["tasks"]:
        task.pop("dispatch_status", None)
    return projection


def validate_dispatch_status_transition(previous: str, current: str, task_id: str) -> None:
    if previous == current:
        return
    if previous in TERMINAL_DISPATCH_STATES:
        historical_error("H13", f"terminal task {task_id} cannot transition {previous} -> {current}")
    if current not in DISPATCH_TRANSITIONS.get(previous, set()):
        historical_error("H12", f"task {task_id} has illegal Dispatch transition {previous} -> {current}")


def validate_plan_transition(previous: dict[str, Any], current: dict[str, Any]) -> str:
    transition = validate_record_transition(previous, current, "Dispatch Plan")
    previous_plan_revision = previous["plan_revision"]
    current_plan_revision = current["plan_revision"]
    if current_plan_revision < previous_plan_revision:
        historical_error("H10", f"plan_revision regressed: {previous_plan_revision} -> {current_plan_revision}")

    previous_tasks = {task["task_id"]: task for task in previous["tasks"]}
    current_tasks = {task["task_id"]: task for task in current["tasks"]}
    removed = sorted(set(previous_tasks) - set(current_tasks))
    if removed:
        historical_error("H11", f"current plan removed historical task IDs: {removed}")

    for task_id, previous_task in previous_tasks.items():
        current_task = current_tasks[task_id]
        validate_dispatch_status_transition(previous_task["dispatch_status"], current_task["dispatch_status"], task_id)
        previous_revision = previous_task["task_spec_revision"]
        current_revision = current_task["task_spec_revision"]
        if current_revision < previous_revision:
            historical_error("H14", f"task {task_id} task_spec_revision regressed")
        if current_revision == previous_revision and current_task["task_spec_digest"] != previous_task["task_spec_digest"]:
            historical_error("H14", f"task {task_id} changed digest without a higher task revision")
        if current_revision > previous_revision and current_task["task_spec_digest"] == previous_task["task_spec_digest"]:
            historical_error("H14", f"task {task_id} raised its revision without a new digest")
        supersede_identity_fields = ("owner_role", "worktree", "branch", "expected_head",
                                     "authorization_envelope_digest")
        changed_identity = [field for field in supersede_identity_fields
                            if current_task[field] != previous_task[field]]
        if changed_identity:
            historical_error("H14", f"task {task_id} changed supersession identity in place: {changed_identity}")
        if previous_task["dispatch_status"] in TERMINAL_DISPATCH_STATES:
            preserved_previous = {key: value for key, value in previous_task.items()
                                  if key not in {"revision_decision", "dispatch_status"}}
            preserved_current = {key: value for key, value in current_task.items()
                                 if key not in {"revision_decision", "dispatch_status"}}
            if preserved_current != preserved_previous:
                historical_error("H13", f"terminal task {task_id} changed preserved evidence")

        decision = current_task["revision_decision"]
        if current_plan_revision > previous_plan_revision:
            if decision == "GRANDFATHER":
                grandfather_previous = {key: value for key, value in previous_task.items()
                                        if key not in {"revision_decision", "dispatch_status"}}
                grandfather_current = {key: value for key, value in current_task.items()
                                       if key not in {"revision_decision", "dispatch_status"}}
                if grandfather_current != grandfather_previous:
                    historical_error("H15", f"task {task_id} GRANDFATHER changed its preserved assignment")
                if current_task["task_spec_plan_revision"] != previous_task["task_spec_plan_revision"]:
                    historical_error("H15", f"task {task_id} GRANDFATHER lost its original plan revision")
            elif decision == "REVISE":
                if current_revision <= previous_revision or current_task["task_spec_digest"] == previous_task["task_spec_digest"]:
                    historical_error("H14", f"task {task_id} REVISE lacks a higher revision and new digest")
                if current_task["task_spec_plan_revision"] != current_plan_revision:
                    historical_error("H14", f"task {task_id} REVISE is not bound to the current plan revision")
            elif decision == "NEW" and previous_task["dispatch_status"] not in TERMINAL_DISPATCH_STATES:
                historical_error("H14", f"existing active task {task_id} cannot remain NEW in a later plan revision")
            elif decision == "SUPERSEDE" and current_task["dispatch_status"] != "SUPERSEDED":
                historical_error("H14", f"task {task_id} SUPERSEDE decision requires SUPERSEDED status")
            elif decision == "CANCELLED" and current_task["dispatch_status"] != "CANCELLED":
                historical_error("H14", f"task {task_id} CANCELLED decision requires CANCELLED status")

    added = sorted(set(current_tasks) - set(previous_tasks))
    if added and current_plan_revision == previous_plan_revision:
        historical_error("H11", f"same plan_revision added tasks: {added}")
    for task_id in added:
        if current_tasks[task_id]["revision_decision"] != "NEW":
            historical_error("H14", f"new task {task_id} must use revision_decision NEW")

    if current_plan_revision == previous_plan_revision and plan_semantic_projection(current) != plan_semantic_projection(previous):
        historical_error("H11", "semantic Dispatch Plan content changed without incrementing plan_revision")
    return transition


def worker_identity_subset(card: dict[str, Any], fields: tuple[str, ...] = WORKER_ASSIGNMENT_FIELDS) -> dict[str, Any]:
    return {field: card[field] for field in fields}


def validate_worker_last_task(previous: dict[str, Any], current: dict[str, Any]) -> None:
    history = current["last_task"]
    identity_fields = ("task_id", "task_spec_revision", "task_spec_digest")
    mismatched = [field for field in identity_fields if history[field] != previous[field]]
    if mismatched:
        historical_error("H18", f"IDLE last_task does not preserve prior Worker identity: {mismatched}")
    if history["outcome"] not in {"COMPLETED", "CANCELLED", "SUPERSEDED"}:
        historical_error("H18", "IDLE last_task is missing a terminal outcome")
    if previous["state"] != "AWAITING_INTEGRATION" and history["outcome"] == "COMPLETED":
        historical_error("H18", "successful completion must transition from AWAITING_INTEGRATION")
    if previous["worker_commit_sha"] is not None and history["worker_commit_sha"] != previous["worker_commit_sha"]:
        historical_error("H18", "IDLE last_task changed the handed-off Worker commit")
    if history["outcome"] == "COMPLETED" and history["integrated_as_sha"] is None:
        historical_error("H18", "COMPLETED last_task requires integrated_as_sha")


def validate_rework_assignment(previous: dict[str, Any], current: dict[str, Any]) -> None:
    if current["task_id"] != previous["task_id"]:
        historical_error("H19", "rework changed task_id instead of using the published recovery assignment")
    if current["task_spec_revision"] <= previous["task_spec_revision"]:
        historical_error("H19", "rework requires a higher task_spec_revision")
    if current["task_spec_digest"] == previous["task_spec_digest"]:
        historical_error("H19", "rework requires a new task_spec_digest")
    immutable = ("source_thread_id", "worker_generation", "frozen_baseline_sha", "authorization")
    changed = [field for field in immutable if current[field] != previous[field]]
    if changed:
        historical_error("H19", f"rework changed immutable assignment fields: {changed}")
    if any(current[field] is not None for field in ("worker_commit_sha", "integrated_as_sha", "release_head_sha")):
        historical_error("H19", "ACTIVE rework card retained prior commit or release evidence")


def validate_worker_transition(previous: dict[str, Any], current: dict[str, Any]) -> str:
    transition = validate_record_transition(previous, current, "Worker Card")
    previous_state = previous["state"]
    current_state = current["state"]
    if previous_state != current_state and current_state not in WORKER_TRANSITIONS.get(previous_state, set()):
        historical_error("H18", f"illegal Worker transition {previous_state} -> {current_state}")
    if transition == "NOOP":
        return transition

    if previous_state == "IDLE" and current_state == "IDLE":
        if previous["last_task"]["task_id"] is not None and current["last_task"] != previous["last_task"]:
            historical_error("H18", "IDLE Worker rewrote its retained last_task evidence")
        return transition
    if previous_state == "IDLE" and current_state == "ACTIVE":
        if current["last_task"] != previous["last_task"]:
            historical_error("H18", "Worker activation rewrote retained last_task evidence")
        return transition
    if current_state == "IDLE" and previous_state != "IDLE":
        validate_worker_last_task(previous, current)
        return transition
    if previous_state == "AWAITING_INTEGRATION" and current_state == "ACTIVE":
        validate_rework_assignment(previous, current)
        return transition
    if previous_state == "BLOCKED" and current_state == "ACTIVE" and (
        current["task_spec_revision"] > previous["task_spec_revision"]
    ):
        validate_rework_assignment(previous, current)
        return transition

    if previous_state != "IDLE" and current_state != "IDLE":
        previous_assignment = worker_identity_subset(previous)
        current_assignment = worker_identity_subset(current)
        if previous_assignment != current_assignment:
            historical_error("H20", f"Worker assignment identity changed during {previous_state} -> {current_state}")
    if current_state == "AWAITING_INTEGRATION":
        if current["worker_commit_sha"] is None or current["integrated_as_sha"] is not None:
            historical_error("H17", "AWAITING_INTEGRATION requires a Worker SHA and no integration mapping")
        if previous_state == "AWAITING_INTEGRATION" and current["worker_commit_sha"] != previous["worker_commit_sha"]:
            historical_error("H17", "AWAITING_INTEGRATION rewrote the handed-off Worker commit")
    if current_state == "BLOCKED" and previous["worker_commit_sha"] is not None:
        if current["worker_commit_sha"] != previous["worker_commit_sha"]:
            historical_error("H21", "BLOCKED transition did not preserve the handed-off commit")
    return transition


def handoff_identity(handoff: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(handoff[field] for field in HANDOFF_IDENTITY_FIELDS)


def validate_candidate_transition(previous: dict[str, Any], current: dict[str, Any]) -> None:
    previous_status = previous["status"]
    current_status = current["status"]
    if (previous["release_head_sha"] != current["release_head_sha"]
            and previous_status in {"PASSED", "FAILED"}
            and current_status in {"PASSED", "FAILED"}):
        historical_error("H25", "candidate evidence remained usable after release_head_sha changed")
    if (previous["gate_input_digest"] != current["gate_input_digest"]
            and previous_status in {"PASSED", "FAILED"}
            and current_status in {"PASSED", "FAILED"}
            and previous["checks"] == current["checks"]):
        historical_error("H25", "candidate evidence remained usable after gate inputs changed")
    same_inputs = (previous["release_head_sha"] == current["release_head_sha"]
                   and previous["gate_input_digest"] == current["gate_input_digest"])
    flipped_result = {previous_status, current_status} == {"PASSED", "FAILED"}
    if same_inputs and flipped_result and previous["checks"] == current["checks"]:
        historical_error("H26", "candidate result flipped without new check evidence")


def validate_master_transition(previous: dict[str, Any], current: dict[str, Any]) -> str:
    transition = validate_record_transition(previous, current, "Master Card")
    previous_state = previous["state"]
    current_state = current["state"]
    if previous_state != current_state and current_state not in MASTER_TRANSITIONS.get(previous_state, set()):
        historical_error("H22", f"illegal Master transition {previous_state} -> {current_state}")
    if transition == "NOOP":
        return transition

    if previous_state != "IDLE" and current_state != "IDLE":
        immutable_lock = ("release_task_id", "dispatch_plan_path", "frozen_baseline_sha")
        changed = [field for field in immutable_lock if current[field] != previous[field]]
        if changed:
            historical_error("H22", f"Master release identity changed in place: {changed}")
        if current["plan_revision"] < previous["plan_revision"]:
            historical_error("H22", "Master plan_revision regressed")
        if (current["plan_revision"] > previous["plan_revision"]
                and current["dispatch_plan_digest"] == previous["dispatch_plan_digest"]):
            historical_error("H22", "Master plan revision advanced without a new plan digest")

    previous_handoffs = {handoff_identity(item): item for item in previous["worker_handoffs"]}
    current_handoffs = {handoff_identity(item): item for item in current["worker_handoffs"]}
    previous_order = [handoff_identity(item) for item in previous["worker_handoffs"]]
    current_order = [handoff_identity(item) for item in current["worker_handoffs"]]
    if current_order[:len(previous_order)] != previous_order:
        historical_error("H22", "Master reordered prior Worker handoff history")
    removed = sorted(set(previous_handoffs) - set(current_handoffs), key=repr)
    if removed:
        historical_error("H22", f"Master removed historical Worker handoffs: {removed}")
    for identity, previous_handoff in previous_handoffs.items():
        current_handoff = current_handoffs[identity]
        immutable_previous = {key: value for key, value in previous_handoff.items()
                              if key not in {"state", "integrated_as_sha"}}
        immutable_current = {key: value for key, value in current_handoff.items()
                             if key not in {"state", "integrated_as_sha"}}
        if immutable_current != immutable_previous:
            historical_error("H22", f"Master rewrote immutable handoff evidence for {identity}")
        old_state = previous_handoff["state"]
        new_state = current_handoff["state"]
        if old_state != new_state and new_state not in HANDOFF_TRANSITIONS.get(old_state, set()):
            historical_error("H22", f"illegal handoff transition {old_state} -> {new_state} for {identity}")
        if old_state in {"INTEGRATED", "REWORK_REQUESTED"} and current_handoff != previous_handoff:
            historical_error("H22", f"terminal handoff changed for {identity}")
    validate_candidate_transition(previous["candidate_evidence"], current["candidate_evidence"])
    return transition


def validate_plan_worker_consistency(plan: dict[str, Any], worker: dict[str, Any],
                                     task_specs: dict[str, dict[str, Any]]) -> None:
    entries = {task["task_id"]: task for task in plan["tasks"]}
    if worker["state"] == "IDLE":
        history = worker["last_task"]
        if history["task_id"] is None:
            return
        entry = entries.get(history["task_id"])
        if entry is None:
            historical_error("H20", f"IDLE Worker last_task {history['task_id']} is absent from the plan")
        expected_status = {"COMPLETED": "INTEGRATED", "CANCELLED": "CANCELLED",
                           "SUPERSEDED": "SUPERSEDED"}[history["outcome"]]
        if entry["dispatch_status"] != expected_status:
            historical_error("H20", "IDLE Worker last_task disagrees with terminal Dispatch status")
        if (entry["task_spec_revision"] != history["task_spec_revision"]
                or entry["task_spec_digest"] != history["task_spec_digest"]):
            historical_error("H20", "IDLE Worker last_task disagrees with plan task identity")
        return

    entry = entries.get(worker["task_id"])
    spec = task_specs.get(worker["task_id"])
    if entry is None or spec is None:
        historical_error("H20", f"active Worker task {worker['task_id']} is absent from plan/spec records")
    direct_pairs = {
        "task_spec_revision": "task_spec_revision",
        "task_spec_digest": "task_spec_digest",
        "task_spec_path": "task_spec_path",
        "dispatch_wave": "dispatch_wave",
        "frozen_baseline_sha": "expected_head",
    }
    mismatched = [worker_field for worker_field, entry_field in direct_pairs.items()
                  if worker[worker_field] != entry[entry_field]]
    if mismatched:
        historical_error("H20", f"Plan/Worker identity mismatch: {mismatched}")
    if worker["plan_revision"] != plan["plan_revision"]:
        grandfather_ok = (entry["revision_decision"] == "GRANDFATHER"
                          and worker["plan_revision"] == entry["task_spec_plan_revision"])
        if not grandfather_ok:
            historical_error("H20", "Worker plan fence does not match current or grandfathered plan revision")
    expected_dispatch = {"ACTIVE": "PUBLISHED", "AWAITING_INTEGRATION": "PUBLISHED", "BLOCKED": "BLOCKED"}
    if entry["dispatch_status"] != expected_dispatch[worker["state"]]:
        historical_error("H20", f"Worker state {worker['state']} disagrees with Dispatch {entry['dispatch_status']}")
    spec_pairs = {
        "source_thread_id": "source_thread_id", "issued_at": "issued_at",
        "supersedes_task_id": "supersedes_task_id", "worker_generation": "generation",
        "allowed_paths": "allowed_paths", "forbidden_paths": "forbidden_paths",
        "authorization": "authorization", "acceptance_commands": "acceptance",
    }
    mismatched = [worker_field for worker_field, spec_field in spec_pairs.items()
                  if worker[worker_field] != spec[spec_field]]
    if mismatched:
        historical_error("H20", f"Task Spec/Worker assignment mismatch: {mismatched}")
    if worker["authorization"]["envelope_digest"] != entry["authorization_envelope_digest"]:
        historical_error("H20", "Worker authorization digest disagrees with plan")


def validate_plan_master_consistency(plan: dict[str, Any], master: dict[str, Any], plan_path: Path | None,
                                     task_specs: dict[str, dict[str, Any]] | None = None) -> None:
    entries = {task["task_id"]: task for task in plan["tasks"]}
    if master["state"] != "IDLE":
        mismatched: list[str] = []
        if master["release_task_id"] != plan["release_task_id"]:
            mismatched.append("release_task_id")
        if master["plan_revision"] != plan["plan_revision"]:
            mismatched.append("plan_revision")
        if master["dispatch_plan_digest"] != plan["plan_digest"]:
            mismatched.append("dispatch_plan_digest")
        if plan_path is not None and Path(master["dispatch_plan_path"]).resolve() != plan_path.resolve():
            mismatched.append("dispatch_plan_path")
        if master["frozen_baseline_sha"] not in {entry["expected_head"] for entry in entries.values()}:
            mismatched.append("frozen_baseline_sha")
        if mismatched:
            historical_error("H27", f"Plan/Master release lock mismatch: {mismatched}")
    for handoff in master["worker_handoffs"]:
        entry = entries.get(handoff["task_id"])
        if entry is None:
            historical_error("H27", f"Master handoff references unknown plan task {handoff['task_id']}")
        handoff_revision = handoff["task_spec_revision"]
        current_revision = entry["task_spec_revision"]
        if handoff_revision < current_revision:
            preserved_rework = (
                handoff["state"] == "REWORK_REQUESTED"
                and entry["revision_decision"] == "REVISE"
                and handoff["task_spec_digest"] != entry["task_spec_digest"]
                and handoff["plan_revision"] < entry["task_spec_plan_revision"]
                and handoff["plan_revision"] <= plan["plan_revision"]
                and handoff["frozen_baseline_sha"] == entry["expected_head"]
                and handoff["authorization_envelope_digest"] == entry["authorization_envelope_digest"]
            )
            spec = (task_specs or {}).get(handoff["task_id"])
            if spec is not None:
                preserved_rework = preserved_rework and (
                    handoff["source_thread_id"] == spec["source_thread_id"]
                    and handoff["role"] == spec["owner_role"]
                )
            if not preserved_rework:
                historical_error("H27", f"incompatible prior-revision handoff for {handoff['task_id']}")
            continue
        if handoff_revision > current_revision:
            historical_error("H27", f"future-revision handoff for {handoff['task_id']}")
        equality = {
            "task_spec_revision": "task_spec_revision", "task_spec_digest": "task_spec_digest",
            "dispatch_wave": "dispatch_wave", "frozen_baseline_sha": "expected_head",
            "authorization_envelope_digest": "authorization_envelope_digest",
            "acceptance_digest": "acceptance_digest",
        }
        mismatched = [handoff_field for handoff_field, entry_field in equality.items()
                      if handoff[handoff_field] != entry[entry_field]]
        if handoff["plan_revision"] > plan["plan_revision"]:
            mismatched.append("plan_revision")
        spec = (task_specs or {}).get(handoff["task_id"])
        if spec is not None:
            if handoff["source_thread_id"] != spec["source_thread_id"]:
                mismatched.append("source_thread_id")
            if handoff["role"] != spec["owner_role"]:
                mismatched.append("role")
        if mismatched:
            historical_error("H27", f"Plan/Master handoff mismatch for {handoff['task_id']}: {mismatched}")
    for task_id, entry in entries.items():
        if entry["dispatch_status"] != "INTEGRATED":
            continue
        matches = [handoff for handoff in master["worker_handoffs"]
                   if (handoff["task_id"], handoff["task_spec_revision"], handoff["task_spec_digest"])
                   == (task_id, entry["task_spec_revision"], entry["task_spec_digest"])]
        if not matches or not any(handoff["state"] == "INTEGRATED" for handoff in matches):
            historical_error("H29", f"INTEGRATED plan task {task_id} lacks an integrated Master handoff")
    if master["candidate_evidence"]["status"] == "PASSED":
        nonterminal = [task_id for task_id, entry in entries.items()
                       if entry["dispatch_status"] not in TERMINAL_DISPATCH_STATES]
        if nonterminal:
            historical_error("H29", f"PASSED candidate retains nonterminal plan tasks: {nonterminal}")


def validate_worker_master_consistency(worker: dict[str, Any], master: dict[str, Any]) -> None:
    handoffs = {handoff_identity(item): item for item in master["worker_handoffs"]}
    if worker["state"] == "AWAITING_INTEGRATION":
        identity = (worker["task_id"], worker["task_spec_revision"], worker["task_spec_digest"],
                    worker["source_thread_id"])
        handoff = handoffs.get(identity)
        if handoff is None or handoff["state"] != "RECEIVED":
            historical_error("H28", "AWAITING_INTEGRATION Worker lacks matching RECEIVED Master handoff")
        if handoff["worker_commit_sha"] != worker["worker_commit_sha"] or handoff["integrated_as_sha"] is not None:
            historical_error("H28", "Worker/Master received handoff evidence does not match")
    if worker["state"] == "IDLE" and worker["last_task"]["outcome"] == "COMPLETED":
        history = worker["last_task"]
        candidates = [handoff for identity, handoff in handoffs.items()
                      if identity[:3] == (history["task_id"], history["task_spec_revision"], history["task_spec_digest"])]
        if not candidates:
            historical_error("H29", "COMPLETED Worker last_task lacks matching Master handoff")
        if not any(handoff["state"] == "INTEGRATED"
                   and handoff["worker_commit_sha"] == history["worker_commit_sha"]
                   and handoff["integrated_as_sha"] == history["integrated_as_sha"] for handoff in candidates):
            historical_error("H29", "integrated Master handoff does not match Worker last_task mapping")


def validate_cross_record_set(plan: dict[str, Any] | None, worker: dict[str, Any] | None,
                              master: dict[str, Any] | None, plan_path: Path | None,
                              task_specs: dict[str, dict[str, Any]] | None) -> dict[str, str]:
    results = {"plan-worker": "NOT_RUN", "plan-master": "NOT_RUN", "worker-master": "NOT_RUN"}
    if plan is not None and worker is not None:
        validate_plan_worker_consistency(plan, worker, task_specs or {})
        results["plan-worker"] = "PASS"
    if plan is not None and master is not None:
        validate_plan_master_consistency(plan, master, plan_path, task_specs)
        results["plan-master"] = "PASS"
    if worker is not None and master is not None:
        validate_worker_master_consistency(worker, master)
        results["worker-master"] = "PASS"
    return results


def historical_completeness(previous_plan: Any, previous_worker: Any, previous_master: Any) -> str:
    return "complete" if all(item is not None for item in (previous_plan, previous_worker, previous_master)) else "partial"


def print_historical_report(pair_results: list[tuple[str, dict[str, Any], dict[str, Any], str]],
                            previous_cross: dict[str, str], current_cross: dict[str, str],
                            completeness: str) -> None:
    print(f"historical validation mode: {completeness}")
    for label, previous, current, transition in pair_results:
        state_evidence = (f"state_transition={previous['state']}->{current['state']}"
                          if "state" in previous else "dispatch_transitions=checked")
        print(f"historical {label}: PASS transition={transition} {state_evidence} "
              f"record_revision={previous['record_revision']}->{current['record_revision']} "
              f"previous_snapshot_digest={value_digest(previous)} current_snapshot_digest={value_digest(current)}")
    for phase, results in (("previous", previous_cross), ("current", current_cross)):
        for relation in ("plan-worker", "plan-master", "worker-master"):
            print(f"historical cross-record {phase} {relation}: {results[relation]}")
    print("historical validation: PASS")


def extract_code_block(text: str, marker: str) -> str:
    start = text.index(marker)
    fence = text.index("```", start)
    body_start = text.index("\n", fence) + 1
    body_end = text.index("```", body_start)
    return text[body_start:body_end]


def yaml_like_keys(block: str, indent: int) -> set[str]:
    pattern = re.compile(rf"^ {{{indent}}}([a-z_]+):", re.MULTILINE)
    return set(pattern.findall(block))


def nested_mapping_keys(block: str, parent: str) -> set[str]:
    lines = block.splitlines()
    try:
        start = lines.index(f"{parent}:") + 1
    except ValueError as error:
        raise ContractError(f"missing {parent} mapping") from error
    nested: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        nested.append(line)
    return yaml_like_keys("\n".join(nested), 2)


def validate_documented_contracts(repo_root: Path, schema: dict[str, Any]) -> None:
    methodology = (repo_root / "references" / "methodology.md").read_text(encoding="utf-8")
    canonical = extract_code_block(methodology, "## Canonical authorization envelope")
    task = extract_code_block(methodology, "## Task publication contract")
    worker = extract_code_block(methodology, "Worker card:")
    master = extract_code_block(methodology, "Master card uses a list")
    plan = extract_code_block(methodology, "The plan is versioned and contains at least:")
    required = schema_required(schema, "authorization")
    for label, block in (("canonical authorization", canonical), ("task authorization", task), ("Worker authorization", worker)):
        keys = nested_mapping_keys(block, "authorization")
        if keys != required:
            raise ContractError(f"{label} fields drifted from schema; missing={sorted(required-keys)}, extra={sorted(keys-required)}")
    projections = (("task spec", task, "task_spec"), ("Worker card", worker, "worker_card"),
                   ("Master card", master, "master_card"), ("Dispatch Plan", plan, "dispatch_plan"))
    for label, block, definition in projections:
        keys = yaml_like_keys(block, 0)
        required_keys = schema_required(schema, definition)
        if keys != required_keys:
            raise ContractError(f"{label} top-level fields drifted from schema; "
                                f"missing={sorted(required_keys-keys)}, extra={sorted(keys-required_keys)}")
    dispatch_enum = set(schema["$defs"]["dispatch_task"]["properties"]["dispatch_status"]["enum"])
    decision_enum = set(schema["$defs"]["dispatch_task"]["properties"]["revision_decision"]["enum"])
    for label, block in (("methodology plan", plan),
                         ("template plan", extract_code_block((repo_root / "references" / "templates.md").read_text(encoding="utf-8"),
                                                              "## Task Dependency and Dispatch Plan"))):
        dispatch_line = re.search(r"^\s+dispatch_status: (.+)$", block, re.MULTILINE)
        decision_line = re.search(r"^\s+revision_decision: (.+)$", block, re.MULTILINE)
        if not dispatch_line or set(dispatch_line.group(1).split(" | ")) != dispatch_enum:
            raise ContractError(f"{label} dispatch-status enum drifted from schema")
        if not decision_line or set(decision_line.group(1).split(" | ")) != decision_enum:
            raise ContractError(f"{label} revision-decision enum drifted from schema")
    default_path = ".codex/multi-worktree-release/dispatch-plan.json"
    historical = schema.get("x-historical-validation", {})
    expected_pairs = [
        {"previous": "--previous-plan", "current": "--plan", "diagnostic": "H01"},
        {"previous": "--previous-worker-card", "current": "--worker-card-json", "diagnostic": "H02"},
        {"previous": "--previous-master-card", "current": "--master-card-json", "diagnostic": "H03"},
    ]
    if historical.get("schema_version") != 1 or historical.get("cli_pairs") != expected_pairs:
        raise ContractError("historical CLI metadata drifted from validator")
    if historical.get("results") != ["PASS", "FAIL", "NOT_RUN"]:
        raise ContractError("historical result metadata drifted from validator")
    if tuple(historical.get("diagnostic_ids", [])) != HISTORICAL_DIAGNOSTIC_IDS:
        raise ContractError("historical diagnostic metadata drifted from validator")
    for relative in ("SKILL.md", "references/methodology.md", "references/templates.md"):
        contents = (repo_root / relative).read_text(encoding="utf-8")
        if default_path not in contents:
            raise ContractError(f"default dispatch path missing from {relative}")
        required_history_terms = (
            "--previous-plan", "--plan", "--previous-worker-card", "--worker-card-json",
            "--previous-master-card", "--master-card-json", "PASS", "FAIL", "NOT_RUN",
        )
        missing_history_terms = [term for term in required_history_terms if term not in contents]
        if missing_history_terms:
            raise ContractError(f"historical CLI contract missing from {relative}: {missing_history_terms}")


def default_authorization() -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "real_external_call": False,
        "create_execution": False,
        "publish": False,
        "destructive_operation": False,
        "target": None,
        "controlled_input": None,
        "controlled_input_digest": None,
        "route": None,
        "provider": None,
        "max_calls": 0,
        "max_cost": 0,
        "cost_unit": None,
        "fresh_execution_required": True,
        "resume_execution_id": None,
        "expires_at": None,
        "envelope_digest": None,
    }
    value["envelope_digest"] = object_digest(value, "envelope_digest")
    return value


class ContractScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = ACTIVE_SCHEMA

    def test_default_deny_authorization_is_complete_and_valid(self) -> None:
        validate_authorization(default_authorization(), self.schema)

    def test_fresh_run_rejects_resume(self) -> None:
        value = default_authorization()
        value["resume_execution_id"] = "run-123"
        value["envelope_digest"] = object_digest(value, "envelope_digest")
        with self.assertRaises(ContractError):
            validate_authorization(value, self.schema)

    def test_authorization_field_omission_is_invalid(self) -> None:
        value = default_authorization()
        del value["max_cost"]
        with self.assertRaises(ContractError):
            validate_authorization(value, self.schema)

    def test_allowed_authority_requires_bounded_context_and_input_digest(self) -> None:
        value = default_authorization()
        value["real_external_call"] = True
        value["max_calls"] = 1
        value["envelope_digest"] = object_digest(value, "envelope_digest")
        with self.assertRaises(ContractError):
            validate_authorization(value, self.schema)
        value.update({"target": "service", "controlled_input": {"id": 1}, "route": "api", "provider": "provider",
                      "expires_at": "2026-01-01T00:00:00Z"})
        value["controlled_input_digest"] = value_digest(value["controlled_input"])
        value["envelope_digest"] = object_digest(value, "envelope_digest")
        validate_authorization(value, self.schema)

    def test_floating_point_digest_input_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            value_digest({"cost": 1.5})

    def test_revision_and_supersession_decisions(self) -> None:
        old = {"task_id": "A", "task_spec_revision": 1, "task_spec_digest": "sha256:" + "1" * 64,
               "plan_revision": 1, "objective": "x", "owner_role": "api", "worktree": "/w", "expected_head": "a" * 40,
               "authorization": default_authorization(), "acceptance": ["test-a"]}
        same = copy.deepcopy(old)
        same["plan_revision"] = 2
        self.assertEqual(classify_task_change(old, same), "GRANDFATHER")
        revised = copy.deepcopy(same)
        revised["acceptance"] = ["test-a", "test-b"]
        revised["task_spec_revision"] = 2
        revised["task_spec_digest"] = "sha256:" + "2" * 64
        self.assertEqual(classify_task_change(old, revised), "REVISE")
        moved = copy.deepcopy(revised)
        moved["worktree"] = "/other"
        self.assertEqual(classify_task_change(old, moved), "SUPERSEDE")

    def test_state_transitions_and_terminals(self) -> None:
        self.assertIn("PUBLISHED", DISPATCH_TRANSITIONS["READY"])
        self.assertIn("BLOCKED", DISPATCH_TRANSITIONS["PUBLISHED"])
        self.assertFalse(DISPATCH_TRANSITIONS["INTEGRATED"])
        self.assertIn("AWAITING_INTEGRATION", WORKER_TRANSITIONS["ACTIVE"])
        self.assertIn("IDLE", WORKER_TRANSITIONS["AWAITING_INTEGRATION"])

    def test_idle_worker_card_must_clear_lock_and_authority(self) -> None:
        card = make_idle_worker_card()
        validate_worker_card(card, self.schema)
        card["task_id"] = "stale-task"
        with self.assertRaises(ContractError):
            validate_worker_card(card, self.schema)

    def test_candidate_invalidation_scope(self) -> None:
        self.assertEqual(candidate_invalidation("a", "b", "x", "x"), "ALL")
        self.assertEqual(candidate_invalidation("a", "a", "x", "y"), "AFFECTED")
        self.assertEqual(candidate_invalidation("a", "a", "x", "x"), "NONE")

    def test_dependency_cycle_is_rejected(self) -> None:
        plan = make_plan([make_dispatch_task("A", ["B"]), make_dispatch_task("B", ["A"])])
        with self.assertRaises(ContractError):
            validate_plan(plan, self.schema)

    def test_unknown_and_asymmetric_plan_edges_are_rejected(self) -> None:
        unknown = make_plan([make_dispatch_task("A", ["missing"])])
        with self.assertRaises(ContractError):
            validate_plan(unknown, self.schema)
        task_a = make_dispatch_task("A")
        task_b = make_dispatch_task("B")
        task_a["parallel_with"] = ["B"]
        asymmetric = make_plan([task_a, task_b])
        with self.assertRaises(ContractError):
            validate_plan(asymmetric, self.schema)

    def test_grandfather_preserves_older_task_spec_plan_revision(self) -> None:
        task = make_dispatch_task("A")
        task["revision_decision"] = "GRANDFATHER"
        plan = make_plan([task])
        plan["plan_revision"] = 2
        plan["plan_digest"] = object_digest(plan, "plan_digest")
        validate_plan(plan, self.schema)
        task["task_spec_plan_revision"] = 2
        plan["plan_digest"] = object_digest(plan, "plan_digest")
        with self.assertRaises(ContractError):
            validate_plan(plan, self.schema)

    def test_task_spec_digest_detects_content_tampering(self) -> None:
        task = make_task_spec()
        validate_task_spec(task, self.schema)
        task["objective"] = "tampered"
        with self.assertRaises(ContractError):
            validate_task_spec(task, self.schema)

    def test_blocked_worker_requires_recovery_evidence(self) -> None:
        card = make_active_worker_card()
        card["state"] = "BLOCKED"
        with self.assertRaises(ContractError):
            validate_worker_card(card, self.schema)
        card["blocker_kind"] = "DEPENDENCY"
        card["blocker"] = "waiting for contract"
        card["blocked_since"] = "2026-01-01T00:01:00Z"
        card["recovery_owner"] = "master-1"
        validate_worker_card(card, self.schema)

    def test_idle_master_card_cannot_retain_active_lock(self) -> None:
        card = make_idle_master_card()
        validate_master_card(card, self.schema)
        card["release_task_id"] = "stale-release"
        with self.assertRaises(ContractError):
            validate_master_card(card, self.schema)


class HistoricalContractScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = ACTIVE_SCHEMA

    def assert_historical(self, diagnostic_id: str, operation: Any) -> None:
        with self.assertRaisesRegex(ContractError, rf"\[{diagnostic_id}\]"):
            operation()

    def test_h01_h03_previous_options_require_current_counterparts(self) -> None:
        fields = ("previous_plan", "previous_worker_card", "previous_master_card")
        diagnostics = ("H01", "H02", "H03")
        for field, diagnostic_id in zip(fields, diagnostics):
            with self.subTest(diagnostic_id=diagnostic_id):
                args = argparse.Namespace(previous_plan=None, plan=None, previous_worker_card=None,
                                          worker_card_json=None, previous_master_card=None, master_card_json=None)
                setattr(args, field, Path("previous.json"))
                with self.assertRaisesRegex(HistoricalUsageError, rf"\[{diagnostic_id}\]"):
                    validate_previous_pairing(args)

    def test_h04_h06_previous_input_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assert_historical("H04", lambda: load_previous_json(root / "missing.json", "Worker Card"))
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            self.assert_historical("H05", lambda: load_previous_json(malformed, "Worker Card"))
        self.assert_historical("H06", lambda: validate_historical_schema_pair(
            {"schema_version": 2}, {"schema_version": 1}, "Worker Card"))

    def test_h07_h09_record_fences(self) -> None:
        previous = make_idle_worker_card()
        previous["record_revision"] = 2
        current = copy.deepcopy(previous)
        current["record_revision"] = 1
        self.assert_historical("H07", lambda: validate_record_transition(previous, current, "Worker Card"))
        current = copy.deepcopy(previous)
        current["updated_at"] = "2026-01-01T00:01:00Z"
        self.assert_historical("H08", lambda: validate_record_transition(previous, current, "Worker Card"))
        current["record_revision"] = 2
        current["updated_at"] = "2025-12-31T23:59:00Z"
        self.assert_historical("H09", lambda: validate_record_transition(previous, current, "Worker Card"))

    def test_h10_h15_plan_transition_matrix(self) -> None:
        previous = make_plan([make_dispatch_task("A")])

        current = advance_record(previous)
        current["plan_revision"] = 0
        self.assert_historical("H10", lambda: validate_plan_transition(previous, current))

        current = advance_record(previous)
        current["tasks"].append(make_dispatch_task("B"))
        self.assert_historical("H11", lambda: validate_plan_transition(previous, current))

        current = advance_record(previous)
        current["tasks"][0]["dispatch_status"] = "PUBLISHED"
        current["plan_digest"] = object_digest(current, "plan_digest")
        self.assertEqual(validate_plan_transition(previous, current), "FORWARD")
        illegal = advance_record(current)
        illegal["tasks"][0]["dispatch_status"] = "READY"
        self.assert_historical("H12", lambda: validate_plan_transition(current, illegal))

        terminal = copy.deepcopy(current)
        terminal["tasks"][0]["dispatch_status"] = "INTEGRATED"
        terminal["plan_digest"] = object_digest(terminal, "plan_digest")
        reopened = advance_record(terminal)
        reopened["tasks"][0]["dispatch_status"] = "BLOCKED"
        self.assert_historical("H13", lambda: validate_plan_transition(terminal, reopened))

        revised = advance_record(previous)
        revised["plan_revision"] = 2
        revised["tasks"][0]["task_spec_revision"] = 2
        revised["tasks"][0]["revision_decision"] = "REVISE"
        revised["tasks"][0]["task_spec_plan_revision"] = 2
        self.assert_historical("H14", lambda: validate_plan_transition(previous, revised))

        grandfather = advance_record(previous)
        grandfather["plan_revision"] = 2
        grandfather["tasks"][0]["revision_decision"] = "GRANDFATHER"
        grandfather["tasks"][0]["task_spec_plan_revision"] = 2
        self.assert_historical("H15", lambda: validate_plan_transition(previous, grandfather))

    def test_h16_h21_worker_history_matrix(self) -> None:
        plan = make_plan([make_dispatch_task("A")])
        self.assert_historical("H16", lambda: load_persisted_plan_specs(plan, self.schema, historical=True))

        active = make_active_worker_card()
        awaiting = advance_record(active)
        awaiting["state"] = "AWAITING_INTEGRATION"
        self.assert_historical("H17", lambda: validate_worker_card(awaiting, self.schema))

        idle = advance_record(active)
        idle.update(make_idle_worker_card())
        idle["record_revision"] = 3
        idle["updated_at"] = "2026-01-01T00:01:00Z"
        self.assert_historical("H18", lambda: validate_worker_transition(active, idle))

        awaiting["worker_commit_sha"] = "b" * 40
        validate_worker_card(awaiting, self.schema)
        self.assertEqual(validate_worker_transition(active, awaiting), "FORWARD")
        active_again = advance_record(awaiting)
        active_again["state"] = "ACTIVE"
        active_again["worker_commit_sha"] = None
        self.assert_historical("H19", lambda: validate_worker_transition(awaiting, active_again))

        bound_plan, spec, bound_worker = make_bound_plan_worker()
        validate_plan_worker_consistency(bound_plan, bound_worker, {"A": spec})
        bound_worker["frozen_baseline_sha"] = "c" * 40
        self.assert_historical("H20", lambda: validate_plan_worker_consistency(
            bound_plan, bound_worker, {"A": spec}))

        blocked = copy.deepcopy(active)
        blocked["state"] = "BLOCKED"
        self.assert_historical("H21", lambda: validate_worker_card(blocked, self.schema))

    def test_h22_h29_master_and_cross_record_matrix(self) -> None:
        previous = make_active_master_card()
        previous["worker_handoffs"] = [make_received_handoff()]
        accepted = advance_record(previous)
        accepted["worker_handoffs"][0]["state"] = "INTEGRATED"
        accepted["worker_handoffs"][0]["integrated_as_sha"] = "c" * 40
        validate_master_card(accepted, self.schema)
        self.assertEqual(validate_master_transition(previous, accepted), "FORWARD")
        current = advance_record(previous)
        current["worker_handoffs"] = []
        self.assert_historical("H22", lambda: validate_master_transition(previous, current))

        integrated = make_active_master_card()
        handoff = make_received_handoff()
        handoff["state"] = "INTEGRATED"
        integrated["worker_handoffs"] = [handoff]
        self.assert_historical("H23", lambda: validate_master_card(integrated, self.schema))

        none_with_head = make_idle_master_card()
        none_with_head["candidate_evidence"]["release_head_sha"] = "a" * 40
        self.assert_historical("H24", lambda: validate_master_card(none_with_head, self.schema))

        old_candidate = make_candidate("PASSED", "a" * 40, "PASS")
        new_candidate = make_candidate("PASSED", "b" * 40, "PASS")
        self.assert_historical("H25", lambda: validate_candidate_transition(old_candidate, new_candidate))
        flipped = make_candidate("FAILED", "a" * 40, "PASS")
        self.assert_historical("H26", lambda: validate_candidate_transition(old_candidate, flipped))

        plan = make_plan([make_dispatch_task("A")])
        master = make_active_master_card(plan)
        master["dispatch_plan_digest"] = "sha256:" + "b" * 64
        self.assert_historical("H27", lambda: validate_plan_master_consistency(
            plan, master, Path("/state/dispatch-plan.json")))

        awaiting = make_active_worker_card()
        awaiting["state"] = "AWAITING_INTEGRATION"
        awaiting["worker_commit_sha"] = "b" * 40
        self.assert_historical("H28", lambda: validate_worker_master_consistency(
            awaiting, make_active_master_card()))

        idle = make_idle_worker_card()
        idle["last_task"] = {
            "task_id": "A", "task_spec_revision": 1, "task_spec_digest": "sha256:" + "a" * 64,
            "outcome": "COMPLETED", "worker_commit_sha": "b" * 40, "integrated_as_sha": "c" * 40,
        }
        self.assert_historical("H29", lambda: validate_worker_master_consistency(
            idle, make_idle_master_card()))

    def test_h30_h31_reporting_and_legacy_mode(self) -> None:
        self.assertEqual(historical_completeness({}, None, None), "partial")
        partial = validate_cross_record_set({}, None, None, None, {})
        self.assertTrue(all(result == "NOT_RUN" for result in partial.values()))
        args = argparse.Namespace(previous_plan=None, previous_worker_card=None, previous_master_card=None)
        self.assertFalse(historical_mode(args))

    def test_complete_cross_record_snapshot_passes(self) -> None:
        plan, spec, worker = make_bound_plan_worker()
        worker["state"] = "AWAITING_INTEGRATION"
        worker["worker_commit_sha"] = "b" * 40
        master = make_active_master_card(plan)
        handoff = make_received_handoff()
        handoff.update({
            "task_spec_digest": spec["task_spec_digest"],
            "authorization_envelope_digest": spec["authorization"]["envelope_digest"],
            "acceptance_digest": value_digest(spec["acceptance"]),
        })
        master["worker_handoffs"] = [handoff]
        results = validate_cross_record_set(plan, worker, master, Path("/state/dispatch-plan.json"), {"A": spec})
        self.assertEqual(results, {"plan-worker": "PASS", "plan-master": "PASS", "worker-master": "PASS"})

    def test_status_only_plan_digest_synchronizes_master_without_semantic_revision(self) -> None:
        spec = make_task_spec()
        previous_plan = make_plan_for_spec(spec, "READY")
        current_plan = advance_record(previous_plan)
        current_plan["tasks"][0]["dispatch_status"] = "PUBLISHED"
        current_plan["plan_digest"] = object_digest(current_plan, "plan_digest")
        previous_master = make_active_master_card(previous_plan)
        current_master = advance_record(previous_master)
        current_master["dispatch_plan_digest"] = current_plan["plan_digest"]

        self.assertEqual(validate_plan_transition(previous_plan, current_plan), "FORWARD")
        self.assertEqual(validate_master_transition(previous_master, current_master), "FORWARD")
        validate_plan_master_consistency(current_plan, current_master, Path("/state/dispatch-plan.json"), {"A": spec})

    def test_master_digest_sync_preserves_release_fences(self) -> None:
        plan = make_plan([make_dispatch_task("A")])
        previous = make_active_master_card(plan)
        for field, replacement in (
            ("release_task_id", "other-release"),
            ("dispatch_plan_path", "/state/other-plan.json"),
            ("frozen_baseline_sha", "c" * 40),
        ):
            with self.subTest(field=field):
                current = advance_record(previous)
                current[field] = replacement
                self.assert_historical("H22", lambda: validate_master_transition(previous, current))
        current = advance_record(previous)
        current["plan_revision"] += 1
        self.assert_historical("H22", lambda: validate_master_transition(previous, current))

        mismatches = {
            "release_task_id": {"release_task_id": "other-release"},
            "plan_revision": {"plan_revision": 2},
            "dispatch_plan_path": {"dispatch_plan_path": "/state/other-plan.json"},
            "dispatch_plan_digest": {"dispatch_plan_digest": "sha256:" + "f" * 64},
            "frozen_baseline_sha": {"frozen_baseline_sha": "c" * 40},
        }
        for label, changes in mismatches.items():
            with self.subTest(cross_record=label):
                master = make_active_master_card(plan)
                master.update(changes)
                self.assert_historical("H27", lambda: validate_plan_master_consistency(
                    plan, master, Path("/state/dispatch-plan.json")))

    def test_preserved_prior_rework_handoff_matches_revised_plan_entry(self) -> None:
        spec = make_revised_task_spec()
        plan = make_plan_for_spec(spec, "PUBLISHED", plan_revision=2, revision_decision="REVISE")
        master = make_active_master_card(plan)
        master["worker_handoffs"] = [make_prior_rework_handoff(spec)]
        validate_plan_master_consistency(plan, master, Path("/state/dispatch-plan.json"), {"A": spec})

    def test_incompatible_prior_revision_handoffs_remain_rejected(self) -> None:
        spec = make_revised_task_spec()
        plan = make_plan_for_spec(spec, "PUBLISHED", plan_revision=2, revision_decision="REVISE")
        mutations = {
            "nonterminal": {"state": "RECEIVED"},
            "integrated": {"state": "INTEGRATED", "integrated_as_sha": "c" * 40},
            "future": {"task_spec_revision": 3},
            "equal-revision-wrong-digest": {"task_spec_revision": 2},
            "rewritten-authority": {"authorization_envelope_digest": "sha256:" + "f" * 64},
        }
        for label, changes in mutations.items():
            with self.subTest(label=label):
                handoff = make_prior_rework_handoff(spec)
                handoff.update(changes)
                master = make_active_master_card(plan)
                master["worker_handoffs"] = [handoff]
                self.assert_historical("H27", lambda: validate_plan_master_consistency(
                    plan, master, Path("/state/dispatch-plan.json"), {"A": spec}))

        previous = make_active_master_card(plan)
        previous["worker_handoffs"] = [make_prior_rework_handoff(spec)]
        current = advance_record(previous)
        current["worker_handoffs"][0]["worker_commit_sha"] = "d" * 40
        self.assert_historical("H22", lambda: validate_master_transition(previous, current))

    def test_public_cli_status_only_plan_and_master_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = make_task_spec_at(root / "task.json")
            write_json_fixture(Path(spec["task_spec_path"]), spec)
            previous_plan = make_plan_for_spec(spec, "READY")
            current_plan = advance_record(previous_plan)
            current_plan["tasks"][0]["dispatch_status"] = "PUBLISHED"
            current_plan["plan_digest"] = object_digest(current_plan, "plan_digest")
            previous_plan_path = root / "previous-plan.json"
            current_plan_path = root / "current-plan.json"
            write_json_fixture(previous_plan_path, previous_plan)
            write_json_fixture(current_plan_path, current_plan)

            previous_master = make_active_master_card(previous_plan, str(current_plan_path))
            current_master = advance_record(previous_master)
            current_master["dispatch_plan_digest"] = current_plan["plan_digest"]
            previous_master_path = root / "previous-master.json"
            current_master_path = root / "current-master.json"
            write_json_fixture(previous_master_path, previous_master)
            write_json_fixture(current_master_path, current_master)

            plan_result = run_public_cli(
                "--plan", str(current_plan_path), "--previous-plan", str(previous_plan_path),
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            self.assertIn("historical dispatch-plan: PASS transition=FORWARD", plan_result.stdout)

            master_result = run_public_cli(
                "--plan", str(current_plan_path),
                "--master-card-json", str(current_master_path),
                "--previous-master-card", str(previous_master_path),
            )
            self.assertEqual(master_result.returncode, 0, master_result.stderr)
            self.assertIn("historical master-card: PASS transition=FORWARD", master_result.stdout)
            self.assertIn("historical cross-record current plan-master: PASS", master_result.stdout)

    def test_public_cli_preserved_rework_handoff_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = make_revised_task_spec(root / "task-r2.json")
            write_json_fixture(Path(spec["task_spec_path"]), spec)
            plan = make_plan_for_spec(spec, "PUBLISHED", plan_revision=2, revision_decision="REVISE")
            plan_path = root / "dispatch-plan.json"
            write_json_fixture(plan_path, plan)
            master = make_active_master_card(plan, str(plan_path))
            master["worker_handoffs"] = [make_prior_rework_handoff(spec)]
            previous_master_path = root / "previous-master.json"
            current_master_path = root / "current-master.json"
            write_json_fixture(previous_master_path, master)
            write_json_fixture(current_master_path, master)

            result = run_public_cli(
                "--plan", str(plan_path),
                "--master-card-json", str(current_master_path),
                "--previous-master-card", str(previous_master_path),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("historical master-card: PASS transition=NOOP", result.stdout)
            self.assertIn("historical cross-record current plan-master: PASS", result.stdout)


def make_dispatch_task(task_id: str, blocked_by: list[str] | None = None) -> dict[str, Any]:
    digest = "sha256:" + "a" * 64
    return {
        "task_id": task_id,
        "task_spec_revision": 1,
        "task_spec_digest": digest,
        "task_spec_path": f"/state/tasks/{task_id}.json",
        "task_spec_plan_revision": 1,
        "revision_decision": "NEW",
        "owner_role": task_id,
        "worktree": f"/worktrees/{task_id}",
        "branch": f"task/{task_id}",
        "expected_head": "a" * 40,
        "acceptance_digest": digest,
        "authorization_envelope_digest": digest,
        "dispatch_status": "GATED" if blocked_by else "READY",
        "dispatch_wave": 1,
        "blocked_by": blocked_by or [],
        "parallel_with": [],
    }


def make_plan(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    plan = {
        "schema_version": 1,
        "record_revision": 1,
        "plan_revision": 1,
        "plan_digest": None,
        "issued_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "release_task_id": "release-1",
        "issued_by": "master-1",
        "state_root": "/state",
        "task_specs_root": "/state/tasks",
        "tasks": tasks,
        "validation": {
            "unique_task_ids": "PASS",
            "known_dependency_references": "PASS",
            "acyclic_dependencies": "PASS",
            "worktree_preflight": "PASS",
            "semantic_ownership_overlap": "NONE",
            "persisted_task_specs": "PASS",
            "task_spec_digests": "PASS",
            "plan_digest": "PASS",
            "atomic_persistence": "PASS",
        },
        "ready_wave": 1,
        "blocked_tasks": [task["task_id"] for task in tasks if task["blocked_by"]],
    }
    plan["plan_digest"] = object_digest(plan, "plan_digest")
    return plan


def make_task_spec() -> dict[str, Any]:
    task = {
        "schema_version": 1,
        "task_id": "A",
        "task_spec_revision": 1,
        "task_spec_digest": None,
        "task_spec_path": "/state/tasks/A.json",
        "plan_revision": 1,
        "dispatch_wave": 1,
        "source_thread_id": "master-1",
        "issued_at": "2026-01-01T00:00:00Z",
        "supersedes_task_id": None,
        "generation": "worker-1",
        "owner_role": "api",
        "worktree": "/worktrees/A",
        "branch": "task/A",
        "expected_head": "a" * 40,
        "task_class": "implementation",
        "objective": "implement A",
        "current_state": {"verified": True},
        "allowed_paths": ["src/A"],
        "forbidden_paths": ["src/B"],
        "inputs": [{"path": "contract.json", "revision": "v1"}],
        "outputs": ["src/A"],
        "derived_outputs": {"recompute_on_master": []},
        "dependencies": {"upstream_commits": [], "parallel_with": [], "blocked_by": []},
        "authorization": default_authorization(),
        "acceptance": ["test A"],
        "commit_message": "feat: implement A",
        "stop_conditions": ["baseline-mismatch"],
    }
    task["task_spec_digest"] = object_digest(task, "task_spec_digest")
    return task


def make_idle_worker_card() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "IDLE",
        "record_revision": 1,
        "updated_at": "2026-01-01T00:00:00Z",
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
        "authorization": default_authorization(),
        "acceptance_commands": [],
        "blocker_kind": None,
        "blocked_since": None,
        "recovery_owner": None,
        "blocker": None,
        "worker_commit_sha": None,
        "integrated_as_sha": None,
        "release_head_sha": None,
        "last_task": {
            "task_id": None,
            "task_spec_revision": None,
            "task_spec_digest": None,
            "outcome": None,
            "worker_commit_sha": None,
            "integrated_as_sha": None,
        },
    }


def make_active_worker_card() -> dict[str, Any]:
    card = make_idle_worker_card()
    card.update({
        "state": "ACTIVE",
        "record_revision": 2,
        "task_id": "A",
        "task_spec_revision": 1,
        "task_spec_digest": "sha256:" + "a" * 64,
        "task_spec_path": "/state/tasks/A.json",
        "plan_revision": 1,
        "dispatch_wave": 1,
        "source_thread_id": "master-1",
        "issued_at": "2026-01-01T00:00:00Z",
        "worker_generation": "worker-1",
        "frozen_baseline_sha": "a" * 40,
        "allowed_paths": ["src/A"],
        "forbidden_paths": ["src/B"],
        "acceptance_commands": ["test A"],
    })
    return card


def make_idle_master_card() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "IDLE",
        "record_revision": 1,
        "updated_at": "2026-01-01T00:00:00Z",
        "release_task_id": None,
        "plan_revision": None,
        "dispatch_plan_path": None,
        "dispatch_plan_digest": None,
        "frozen_baseline_sha": None,
        "worker_handoffs": [],
        "candidate_evidence": {"release_head_sha": None, "gate_input_digest": None, "status": "NONE", "checks": []},
        "blocker": None,
    }


def make_active_master_card(plan: dict[str, Any] | None = None, plan_path: str = "/state/dispatch-plan.json") -> dict[str, Any]:
    plan = plan or make_plan([make_dispatch_task("A")])
    card = make_idle_master_card()
    card.update({
        "state": "ACTIVE",
        "record_revision": 2,
        "updated_at": "2026-01-01T00:01:00Z",
        "release_task_id": plan["release_task_id"],
        "plan_revision": plan["plan_revision"],
        "dispatch_plan_path": plan_path,
        "dispatch_plan_digest": plan["plan_digest"],
        "frozen_baseline_sha": "a" * 40,
    })
    return card


def make_received_handoff() -> dict[str, Any]:
    digest = "sha256:" + "a" * 64
    return {
        "state": "RECEIVED",
        "task_id": "A",
        "role": "api",
        "task_spec_revision": 1,
        "task_spec_digest": digest,
        "plan_revision": 1,
        "dispatch_wave": 1,
        "source_thread_id": "master-1",
        "frozen_baseline_sha": "a" * 40,
        "authorization_envelope_digest": digest,
        "acceptance_digest": digest,
        "worker_commit_sha": "b" * 40,
        "integrated_as_sha": None,
    }


def advance_record(value: dict[str, Any]) -> dict[str, Any]:
    advanced = copy.deepcopy(value)
    advanced["record_revision"] += 1
    advanced["updated_at"] = "2026-01-01T00:01:00Z"
    if "plan_digest" in advanced:
        advanced["plan_digest"] = object_digest(advanced, "plan_digest")
    return advanced


def make_bound_plan_worker() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    spec = make_task_spec()
    task = make_dispatch_task("A")
    task.update({
        "task_spec_digest": spec["task_spec_digest"],
        "task_spec_path": spec["task_spec_path"],
        "owner_role": spec["owner_role"],
        "worktree": spec["worktree"],
        "branch": spec["branch"],
        "expected_head": spec["expected_head"],
        "acceptance_digest": value_digest(spec["acceptance"]),
        "authorization_envelope_digest": spec["authorization"]["envelope_digest"],
        "dispatch_status": "PUBLISHED",
    })
    plan = make_plan([task])
    worker = make_active_worker_card()
    worker.update({
        "task_spec_digest": spec["task_spec_digest"],
        "authorization": copy.deepcopy(spec["authorization"]),
    })
    return plan, spec, worker


def make_candidate(status: str, head: str, result: str) -> dict[str, Any]:
    return {
        "release_head_sha": head,
        "gate_input_digest": "sha256:" + "d" * 64,
        "status": status,
        "checks": [{"command": "test", "result": result, "evidence_digest": "sha256:" + "e" * 64}],
    }


def make_task_spec_at(path: Path) -> dict[str, Any]:
    spec = make_task_spec()
    spec["task_spec_path"] = str(path)
    spec["task_spec_digest"] = object_digest(spec, "task_spec_digest")
    return spec


def make_revised_task_spec(path: Path | None = None) -> dict[str, Any]:
    spec = make_task_spec_at(path or Path("/state/tasks/A-r2.json"))
    spec.update({
        "task_spec_revision": 2,
        "plan_revision": 2,
        "objective": "implement revised A",
        "acceptance": ["test revised A"],
    })
    spec["task_spec_digest"] = object_digest(spec, "task_spec_digest")
    return spec


def make_plan_for_spec(spec: dict[str, Any], dispatch_status: str, plan_revision: int | None = None,
                       revision_decision: str = "NEW") -> dict[str, Any]:
    effective_plan_revision = plan_revision or spec["plan_revision"]
    task = make_dispatch_task(spec["task_id"])
    task.update({
        "task_spec_revision": spec["task_spec_revision"],
        "task_spec_digest": spec["task_spec_digest"],
        "task_spec_path": spec["task_spec_path"],
        "task_spec_plan_revision": spec["plan_revision"],
        "revision_decision": revision_decision,
        "owner_role": spec["owner_role"],
        "worktree": spec["worktree"],
        "branch": spec["branch"],
        "expected_head": spec["expected_head"],
        "acceptance_digest": value_digest(spec["acceptance"]),
        "authorization_envelope_digest": spec["authorization"]["envelope_digest"],
        "dispatch_status": dispatch_status,
        "dispatch_wave": spec["dispatch_wave"],
    })
    plan = make_plan([task])
    plan["plan_revision"] = effective_plan_revision
    plan["plan_digest"] = object_digest(plan, "plan_digest")
    return plan


def make_prior_rework_handoff(current_spec: dict[str, Any]) -> dict[str, Any]:
    handoff = make_received_handoff()
    handoff.update({
        "state": "REWORK_REQUESTED",
        "task_spec_digest": "sha256:" + "1" * 64,
        "source_thread_id": current_spec["source_thread_id"],
        "role": current_spec["owner_role"],
        "frozen_baseline_sha": current_spec["expected_head"],
        "authorization_envelope_digest": current_spec["authorization"]["envelope_digest"],
        "acceptance_digest": "sha256:" + "2" * 64,
    })
    return handoff


def write_json_fixture(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def run_public_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(Path(__file__).resolve()), "--skip-self-test", *arguments]
    return subprocess.run(command, text=True, capture_output=True, timeout=15, check=False)


ACTIVE_SCHEMA: dict[str, Any] = {}


def run_self_tests() -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--previous-plan", type=Path)
    parser.add_argument("--task-spec", type=Path)
    parser.add_argument("--worker-card-json", type=Path)
    parser.add_argument("--previous-worker-card", type=Path)
    parser.add_argument("--master-card-json", type=Path)
    parser.add_argument("--previous-master-card", type=Path)
    parser.add_argument("--skip-self-test", action="store_true")
    args = parser.parse_args()

    try:
        validate_previous_pairing(args)
    except HistoricalUsageError as error:
        parser.error(str(error))
    is_historical = historical_mode(args)

    repo_root = args.repo_root.resolve()
    schema_path = repo_root / "references" / "contracts.schema.json"
    schema = load_json(schema_path)
    global ACTIVE_SCHEMA
    ACTIVE_SCHEMA = schema

    current_plan = current_worker = current_master = None
    previous_plan = previous_worker = previous_master = None
    current_specs: dict[str, dict[str, Any]] = {}
    previous_specs: dict[str, dict[str, Any]] = {}
    pair_results: list[tuple[str, dict[str, Any], dict[str, Any], str]] = []
    previous_cross = {"plan-worker": "NOT_RUN", "plan-master": "NOT_RUN", "worker-master": "NOT_RUN"}
    current_cross = copy.deepcopy(previous_cross)
    try:
        validate_documented_contracts(repo_root, schema)
        if args.plan:
            current_plan = load_json(args.plan)
            validate_plan(current_plan, schema)
            current_specs = load_persisted_plan_specs(current_plan, schema)
        if args.task_spec:
            validate_task_spec(load_json(args.task_spec), schema)
        if args.worker_card_json:
            current_worker = load_json(args.worker_card_json)
            validate_worker_card(current_worker, schema)
        if args.master_card_json:
            current_master = load_json(args.master_card_json)
            validate_master_card(current_master, schema)

        if args.previous_plan:
            previous_plan = load_previous_json(args.previous_plan, "Dispatch Plan")
            validate_historical_schema_pair(previous_plan, current_plan, "Dispatch Plan")
            validate_plan(previous_plan, schema)
            previous_specs = load_persisted_plan_specs(previous_plan, schema, historical=True)
            pair_results.append(("dispatch-plan", previous_plan, current_plan,
                                 validate_plan_transition(previous_plan, current_plan)))
        if args.previous_worker_card:
            previous_worker = load_previous_json(args.previous_worker_card, "Worker Card")
            validate_historical_schema_pair(previous_worker, current_worker, "Worker Card")
            validate_worker_card(previous_worker, schema)
            pair_results.append(("worker-card", previous_worker, current_worker,
                                 validate_worker_transition(previous_worker, current_worker)))
        if args.previous_master_card:
            previous_master = load_previous_json(args.previous_master_card, "Master Card")
            validate_historical_schema_pair(previous_master, current_master, "Master Card")
            validate_master_card(previous_master, schema)
            pair_results.append(("master-card", previous_master, current_master,
                                 validate_master_transition(previous_master, current_master)))

        if is_historical:
            previous_cross = validate_cross_record_set(previous_plan, previous_worker, previous_master,
                                                        args.previous_plan, previous_specs)
            current_cross = validate_cross_record_set(current_plan, current_worker, current_master,
                                                       args.plan, current_specs)
    except (ContractError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        prefix = "historical validation: FAIL" if is_historical else "contract validation failed:"
        print(f"{prefix} {error}", file=sys.stderr)
        return 1

    if not args.skip_self_test and not run_self_tests():
        return 1
    if is_historical:
        print_historical_report(pair_results, previous_cross, current_cross,
                                historical_completeness(previous_plan, previous_worker, previous_master))
    print("contract validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
from typing import Any, Dict, List, Literal, TypedDict, Union, cast


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
MODEL_OWNER_DEFAULTS = {
    "master": {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "service_tier": "default",
        "selection_reason": "owner-default:master",
    },
    "ordinary_worker": {
        "model": "gpt-5.6-luna",
        "reasoning_effort": "max",
        "service_tier": "priority",
        "selection_reason": "owner-default:ordinary-worker",
    },
    "complex_worker": {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "service_tier": "default",
        "selection_reason": "owner-default:complex-worker",
    },
}
MODEL_REASON_TO_OWNER = {
    profile["selection_reason"]: owner for owner, profile in MODEL_OWNER_DEFAULTS.items()
}


class ContractError(ValueError):
    pass


class HistoricalUsageError(ValueError):
    pass


CanonicalValue = Union[None, bool, int, str, List["CanonicalValue"], Dict[str, "CanonicalValue"]]


class TargetScope(TypedDict):
    paths: list[str]
    refs: list[str]


class StructuredTarget(TypedDict):
    kind: Literal["service", "execution", "publication", "resource"]
    id: str
    transport: Literal["local", "remote"]
    scope: TargetScope


class CapabilityGrant(TypedDict):
    allowed: bool
    target: StructuredTarget | None
    route: str | None
    provider: str | None
    max_calls: int
    max_cost: int
    cost_unit: str | None


class ExecutionCapabilityGrant(CapabilityGrant):
    fresh_execution_required: bool
    resume_execution_id: str | None


class AuthorizationCapabilities(TypedDict):
    external_call: CapabilityGrant
    create_execution: ExecutionCapabilityGrant
    publish: CapabilityGrant
    destructive_operation: CapabilityGrant


class AuthorizationV2(TypedDict):
    schema_version: Literal[2]
    capabilities: AuthorizationCapabilities
    controlled_input: CanonicalValue
    controlled_input_digest: str | None
    expires_at: str | None
    envelope_digest: str


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


def schema_properties(schema: dict[str, Any], definition: str) -> set[str]:
    return set(schema["$defs"][definition]["properties"])


def require_schema_fields(value: dict[str, Any], schema: dict[str, Any],
                          definition: str, label: str) -> None:
    actual = set(value)
    required = schema_required(schema, definition)
    allowed = schema_properties(schema, definition)
    missing = sorted(required - actual)
    extra = sorted(actual - allowed)
    if missing or extra:
        raise ContractError(f"{label} field mismatch; missing={missing}, extra={extra}")


def validate_string_list(value: Any, label: str, *, canonical: bool = False) -> None:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ContractError(f"{label} entries must be non-empty strings")
    if len(set(value)) != len(value):
        raise ContractError(f"{label} must not contain duplicates")
    if canonical and value != sorted(value, key=lambda item: item.encode("utf-8")):
        raise ContractError(f"{label} must use canonical UTF-8 order")


def validate_model_profile(value: Any, schema: dict[str, Any], label: str = "model_profile") -> None:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    require_exact_fields(value, schema_required(schema, "model_profile"), label)
    for field in ("model", "reasoning_effort", "service_tier", "selection_reason"):
        if not isinstance(value[field], str) or not value[field]:
            raise ContractError(f"{label}.{field} must be a non-empty string")
    reason = value["selection_reason"]
    owner = MODEL_REASON_TO_OWNER.get(reason)
    if owner is None or value != MODEL_OWNER_DEFAULTS[owner]:
        raise ContractError(f"{label} uses an unsupported model/reasoning/service-tier combination")


def validate_model_policy(value: Any, schema: dict[str, Any], plan_revision: int) -> None:
    if not isinstance(value, dict):
        raise ContractError("model_policy must be an object")
    require_exact_fields(value, schema_required(schema, "model_policy"), "model_policy")
    if value["schema_version"] != 1:
        raise ContractError("model_policy.schema_version must be 1")
    validate_positive_integer(value["enforced_from_plan_revision"],
                              "model_policy.enforced_from_plan_revision")
    if value["enforced_from_plan_revision"] > plan_revision:
        raise ContractError("model_policy enforcement cannot begin in a future plan revision")
    defaults = value["owner_defaults"]
    if not isinstance(defaults, dict):
        raise ContractError("model_policy.owner_defaults must be an object")
    require_exact_fields(defaults, schema_required(schema, "model_owner_defaults"),
                         "model_policy.owner_defaults")
    for owner, expected in MODEL_OWNER_DEFAULTS.items():
        validate_model_profile(defaults[owner], schema, f"model_policy.owner_defaults.{owner}")
        if defaults[owner] != expected:
            raise ContractError(f"model_policy owner default drifted for {owner}")


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


def validate_authorization_v1(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "authorization_v1"), "authorization v1")
    if not isinstance(value["schema_version"], int) or isinstance(value["schema_version"], bool) or value["schema_version"] != 1:
        raise ContractError("authorization.schema_version must be 1")
    for field in ("real_external_call", "create_execution", "publish", "destructive_operation", "fresh_execution_required"):
        if not isinstance(value[field], bool):
            raise ContractError(f"authorization.{field} must be boolean")
    if not isinstance(value["max_calls"], int) or isinstance(value["max_calls"], bool) or value["max_calls"] < 0:
        raise ContractError("authorization.max_calls must be a non-negative integer")
    if not isinstance(value["max_cost"], int) or isinstance(value["max_cost"], bool) or value["max_cost"] < 0:
        raise ContractError("authorization.max_cost must be a non-negative integer")
    for field in ("target", "route", "provider", "cost_unit", "resume_execution_id"):
        if value[field] is not None and not isinstance(value[field], str):
            raise ContractError(f"authorization.{field} must be null or a string")
    if value["fresh_execution_required"] and value["resume_execution_id"] is not None:
        raise ContractError("fresh execution and resume ID are mutually exclusive")
    validate_digest(value["controlled_input_digest"], "controlled_input_digest", allow_null=True)
    validate_digest(value["envelope_digest"], "envelope_digest", allow_null=True)
    validate_rfc3339(value["expires_at"], "authorization.expires_at", allow_null=True)
    if value["envelope_digest"] is not None:
        expected = object_digest(value, "envelope_digest")
        if value["envelope_digest"] != expected:
            raise ContractError("authorization envelope digest mismatch")
    ensure_canonical_value(value["controlled_input"], "authorization.controlled_input")
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


def validate_non_negative_integer(value: Any, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(f"{label} must be a non-negative integer")


def validate_nullable_nonempty_string(value: Any, label: str) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ContractError(f"{label} must be null or a non-empty string")


def validate_authorization_scope(value: Any, schema: dict[str, Any], label: str) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    require_exact_fields(value, schema_required(schema, "target_scope"), label)
    for field in ("paths", "refs"):
        entries = value[field]
        if not isinstance(entries, list):
            raise ContractError(f"{label}.{field} must be an array")
        if any(not isinstance(item, str) or not item for item in entries):
            raise ContractError(f"{label}.{field} entries must be non-empty strings")
        if any("*" in item for item in entries):
            raise ContractError(f"{label}.{field} may not contain wildcard scope")
        if len(set(entries)) != len(entries):
            raise ContractError(f"{label}.{field} must not contain duplicates")
        if entries != sorted(entries, key=lambda item: item.encode("utf-8")):
            raise ContractError(f"{label}.{field} must use canonical UTF-8 order")


def validate_authorization_target(value: Any, schema: dict[str, Any], capability: str,
                                  expected_kind: str, require_scope: bool) -> str:
    label = f"authorization.capabilities.{capability}.target"
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a structured object")
    definition = f"authorization_target_{expected_kind}"
    require_exact_fields(value, schema_required(schema, definition), label)
    if value["kind"] != expected_kind:
        raise ContractError(f"{label}.kind must be {expected_kind}")
    if not isinstance(value["id"], str) or not value["id"]:
        raise ContractError(f"{label}.id must be a non-empty string")
    transport = value["transport"]
    allowed_transports = {"remote"} if capability == "external_call" else {"local", "remote"}
    if transport not in allowed_transports:
        raise ContractError(f"{label}.transport must be one of {sorted(allowed_transports)}")
    validate_authorization_scope(value["scope"], schema, f"{label}.scope")
    if require_scope and not (value["scope"]["paths"] or value["scope"]["refs"]):
        raise ContractError(f"{label}.scope must contain at least one path or ref")
    return transport


def validate_authorization_grant(value: Any, schema: dict[str, Any], capability: str,
                                 expected_kind: str) -> bool:
    label = f"authorization.capabilities.{capability}"
    definition = f"authorization_grant_{capability}"
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    require_exact_fields(value, schema_required(schema, definition), label)
    if not isinstance(value["allowed"], bool):
        raise ContractError(f"{label}.allowed must be boolean")
    for field in ("route", "provider", "cost_unit"):
        validate_nullable_nonempty_string(value[field], f"{label}.{field}")
    validate_non_negative_integer(value["max_calls"], f"{label}.max_calls")
    validate_non_negative_integer(value["max_cost"], f"{label}.max_cost")
    if value["max_cost"] == 0 and value["cost_unit"] is not None:
        raise ContractError(f"{label}.cost_unit must be null when max_cost is zero")
    if value["max_cost"] > 0 and value["cost_unit"] is None:
        raise ContractError(f"{label}.cost_unit is required when max_cost is positive")

    is_execution = capability == "create_execution"
    if is_execution:
        if not isinstance(value["fresh_execution_required"], bool):
            raise ContractError(f"{label}.fresh_execution_required must be boolean")
        validate_nullable_nonempty_string(value["resume_execution_id"], f"{label}.resume_execution_id")

    if not value["allowed"]:
        canonical = {
            "allowed": False,
            "target": None,
            "route": None,
            "provider": None,
            "max_calls": 0,
            "max_cost": 0,
            "cost_unit": None,
        }
        if is_execution:
            canonical.update({"fresh_execution_required": True, "resume_execution_id": None})
        if value != canonical:
            raise ContractError(f"{label} denied grant must use canonical default-deny values")
        return False

    transport = validate_authorization_target(
        value["target"], schema, capability, expected_kind,
        require_scope=capability in {"publish", "destructive_operation"},
    )
    if transport == "remote":
        if value["route"] is None or value["provider"] is None:
            raise ContractError(f"{label} remote target requires route and provider")
    elif value["route"] is not None or value["provider"] is not None:
        raise ContractError(f"{label} local target requires null route and provider")
    if capability in {"external_call", "create_execution"}:
        if value["max_calls"] < 1:
            raise ContractError(f"{label} requires a positive max_calls limit")
    elif value["max_calls"] != 0:
        raise ContractError(f"{label}.max_calls must be zero")
    if is_execution:
        fresh = value["fresh_execution_required"]
        resume_id = value["resume_execution_id"]
        if fresh and resume_id is not None:
            raise ContractError(f"{label} fresh execution requires null resume_execution_id")
        if not fresh and resume_id is None:
            raise ContractError(f"{label} resumed execution requires an exact resume_execution_id")
    return True


def validate_authorization_v2(value: dict[str, Any], schema: dict[str, Any],
                              now: dt.datetime | None = None, enforce_expiry: bool = True) -> None:
    require_exact_fields(value, schema_required(schema, "authorization_v2"), "authorization v2")
    if not isinstance(value["schema_version"], int) or isinstance(value["schema_version"], bool) or value["schema_version"] != 2:
        raise ContractError("authorization.schema_version must be 2")
    capabilities = value["capabilities"]
    if not isinstance(capabilities, dict):
        raise ContractError("authorization.capabilities must be an object")
    expected_capabilities = {"external_call", "create_execution", "publish", "destructive_operation"}
    require_exact_fields(capabilities, expected_capabilities, "authorization.capabilities")
    kinds = {
        "external_call": "service",
        "create_execution": "execution",
        "publish": "publication",
        "destructive_operation": "resource",
    }
    allowed = [name for name, kind in kinds.items()
               if validate_authorization_grant(capabilities[name], schema, name, kind)]
    ensure_canonical_value(value["controlled_input"], "authorization.controlled_input")
    validate_digest(value["controlled_input_digest"], "authorization.controlled_input_digest", allow_null=True)
    expiration = parse_rfc3339(value["expires_at"], "authorization.expires_at", allow_null=True)
    validate_digest(value["envelope_digest"], "authorization.envelope_digest")
    if value["envelope_digest"] != object_digest(value, "envelope_digest"):
        raise ContractError("authorization envelope digest mismatch")
    if allowed:
        if value["controlled_input"] is None or value["controlled_input_digest"] is None or expiration is None:
            raise ContractError("allowed v2 authority requires controlled input, its digest, and expiry")
        if value["controlled_input_digest"] != value_digest(value["controlled_input"]):
            raise ContractError("controlled-input digest mismatch")
        if enforce_expiry:
            current = now or dt.datetime.now(dt.timezone.utc)
            if current.tzinfo is None:
                raise ContractError("authorization validation time must include a timezone")
            if expiration <= current:
                raise ContractError("authorization v2 envelope is expired")
    elif any(value[field] is not None for field in ("controlled_input", "controlled_input_digest", "expires_at")):
        raise ContractError("all-denied v2 authorization must clear controlled input, digest, and expiry")


def validate_authorization(value: dict[str, Any], schema: dict[str, Any],
                           now: dt.datetime | None = None, enforce_expiry: bool = True) -> None:
    if not isinstance(value, dict):
        raise ContractError("authorization must be an object")
    version = value.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ContractError("authorization.schema_version must be an integer")
    if version == 1:
        validate_authorization_v1(value, schema)
    elif version == 2:
        validate_authorization_v2(value, schema, now=now, enforce_expiry=enforce_expiry)
    else:
        raise ContractError("authorization.schema_version must be 1 or 2")


def validate_execution_request(value: dict[str, Any], schema: dict[str, Any],
                               requested_resume_execution_id: str | None,
                               now: dt.datetime | None = None) -> None:
    """Bind an execution request to the v2 grant's exact fresh/resume mode."""
    validate_authorization(value, schema, now=now)
    if value["schema_version"] != 2:
        raise ContractError("execution request matching requires authorization v2")
    grant = value["capabilities"]["create_execution"]
    if not grant["allowed"]:
        raise ContractError("create_execution is not authorized")
    validate_nullable_nonempty_string(requested_resume_execution_id, "requested_resume_execution_id")
    if grant["fresh_execution_required"]:
        if requested_resume_execution_id is not None:
            raise ContractError("fresh execution request cannot resume an execution")
    elif requested_resume_execution_id != grant["resume_execution_id"]:
        raise ContractError("requested resume execution ID does not match the authorized exact ID")


def validate_task_spec(value: dict[str, Any], schema: dict[str, Any],
                       enforce_authorization_expiry: bool = True) -> None:
    require_schema_fields(value, schema, "task_spec", "task spec")
    if value["schema_version"] != 1:
        raise ContractError("task_spec.schema_version must be 1")
    validate_positive_integer(value["task_spec_revision"], "task_spec.task_spec_revision")
    validate_positive_integer(value["plan_revision"], "task_spec.plan_revision")
    validate_positive_integer(value["dispatch_wave"], "task_spec.dispatch_wave")
    validate_authorization(value["authorization"], schema, enforce_expiry=enforce_authorization_expiry)
    dependencies = value["dependencies"]
    if not isinstance(dependencies, dict):
        raise ContractError("task_spec.dependencies must be an object")
    require_exact_fields(dependencies, schema_required(schema, "task_dependencies"),
                         "task_spec.dependencies")
    for field in ("upstream_commits", "parallel_with", "blocked_by"):
        validate_string_list(dependencies[field], f"task_spec.dependencies.{field}")
    for sha in dependencies["upstream_commits"]:
        validate_sha(sha, "task_spec.dependencies.upstream_commits entry")
    if "model_profile" in value:
        validate_model_profile(value["model_profile"], schema, "task_spec.model_profile")
    validate_rfc3339(value["issued_at"], "task_spec.issued_at")
    for field in ("task_spec_path", "worktree"):
        if not Path(value[field]).is_absolute():
            raise ContractError(f"task_spec.{field} must be absolute")
    validate_sha(value["expected_head"], "task_spec.expected_head")
    validate_digest(value["task_spec_digest"], "task_spec_digest")
    if value["task_spec_digest"] != object_digest(value, "task_spec_digest"):
        raise ContractError("task spec digest mismatch")


def validate_plan(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_schema_fields(value, schema, "dispatch_plan", "dispatch plan")
    require_exact_fields(value["validation"], schema_required(schema, "plan_validation"), "plan validation")
    validate_positive_integer(value["record_revision"], "dispatch_plan.record_revision")
    validate_positive_integer(value["plan_revision"], "dispatch_plan.plan_revision")
    if "model_policy" in value:
        validate_model_policy(value["model_policy"], schema, value["plan_revision"])
    validate_rfc3339(value["issued_at"], "dispatch_plan.issued_at")
    validate_rfc3339(value["updated_at"], "dispatch_plan.updated_at")
    for field in ("state_root", "task_specs_root"):
        if not Path(value[field]).is_absolute():
            raise ContractError(f"dispatch plan {field} must be absolute")
    validate_digest(value["plan_digest"], "plan_digest")
    if value["plan_digest"] != object_digest(value, "plan_digest"):
        raise ContractError("dispatch plan digest mismatch")
    ids: list[str] = []
    entries: dict[str, dict[str, Any]] = {}
    active_worktrees: dict[str, str] = {}
    for task in value["tasks"]:
        require_schema_fields(task, schema, "dispatch_task", "dispatch task")
        task_id = task["task_id"]
        if not isinstance(task_id, str) or not task_id:
            raise ContractError("dispatch task_id must be a non-empty string")
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
        for field in ("blocked_by", "parallel_with"):
            validate_string_list(task[field], f"{task_id}.{field}")
            if task_id in task[field]:
                raise ContractError(f"{task_id}.{field} may not reference itself")
        if "model_profile" in task:
            validate_model_profile(task["model_profile"], schema, f"{task_id}.model_profile")
        decision = task["revision_decision"]
        issued_plan = task["task_spec_plan_revision"]
        if issued_plan > value["plan_revision"]:
            raise ContractError(f"{task_id} was issued under a future plan revision")
        if decision in {"NEW", "REVISE"} and issued_plan != value["plan_revision"]:
            raise ContractError(f"{task_id} {decision} must bind to the current plan revision")
        if decision == "GRANDFATHER" and issued_plan >= value["plan_revision"]:
            raise ContractError(f"{task_id} GRANDFATHER must preserve an older task-spec plan revision")
    policy = value.get("model_policy")
    if policy is None:
        profiled = sorted(task_id for task_id, task in entries.items() if "model_profile" in task)
        if profiled:
            raise ContractError(f"model_profile requires a persisted model_policy fence: {profiled}")
    else:
        fence = policy["enforced_from_plan_revision"]
        missing_profiles = sorted(
            task_id for task_id, task in entries.items()
            if task["task_spec_plan_revision"] >= fence and "model_profile" not in task
        )
        if missing_profiles:
            raise ContractError(f"model_policy requires Dispatch model_profile: {missing_profiles}")
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
    expected_blocked = sorted(
        task_id for task_id, task in entries.items()
        if task["dispatch_status"] in {"GATED", "BLOCKED"}
    )
    if value["blocked_tasks"] != expected_blocked:
        raise ContractError(
            f"blocked_tasks mismatch: expected={expected_blocked}, actual={value['blocked_tasks']}"
        )
    frontier = [task["dispatch_wave"] for task in entries.values()
                if task["dispatch_status"] in {"READY", "PUBLISHED"}]
    expected_ready_wave = min(frontier) if frontier else None
    if value["ready_wave"] != expected_ready_wave:
        raise ContractError(
            f"ready_wave mismatch: expected={expected_ready_wave}, actual={value['ready_wave']}"
        )
    ready_statuses = {"READY", "PUBLISHED", "INTEGRATED"}
    if any(task["dispatch_status"] in ready_statuses for task in entries.values()):
        pass_fields = set(schema_required(schema, "plan_validation")) - {"semantic_ownership_overlap"}
        failed = [field for field in pass_fields if value["validation"][field] != "PASS"]
        if failed or value["validation"]["semantic_ownership_overlap"] != "NONE":
            raise ContractError(f"ready/published plan has failed validation: {failed}")


def graph_enforcement_applies(plan: dict[str, Any], entry: dict[str, Any],
                              spec: dict[str, Any], historical: bool) -> bool:
    policy = plan.get("model_policy")
    if policy is not None and entry["task_spec_plan_revision"] >= policy["enforced_from_plan_revision"]:
        return True
    if "model_profile" in entry or "model_profile" in spec:
        return True
    return not historical and entry["dispatch_status"] not in TERMINAL_DISPATCH_STATES


def owned_paths(spec: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in spec["allowed_paths"]:
        if not isinstance(item, str) or not item or item == "WORKTREE_TASK.md":
            continue
        paths.append(item.rstrip("/"))
    return paths


def paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def validate_dispatch_graph_and_model_routing(plan: dict[str, Any], specs: dict[str, dict[str, Any]],
                                              schema: dict[str, Any], historical: bool = False) -> None:
    entries = {entry["task_id"]: entry for entry in plan["tasks"]}
    known = set(entries)
    policy = plan.get("model_policy")

    if policy is None:
        profiled_specs = sorted(task_id for task_id, spec in specs.items() if "model_profile" in spec)
        if profiled_specs:
            raise ContractError(f"Task Spec model_profile requires a persisted model_policy fence: {profiled_specs}")
    else:
        fence = policy["enforced_from_plan_revision"]
        for task_id, entry in entries.items():
            spec = specs[task_id]
            required = entry["task_spec_plan_revision"] >= fence
            entry_has = "model_profile" in entry
            spec_has = "model_profile" in spec
            if required and (not entry_has or not spec_has):
                raise ContractError(f"model_policy requires Task Spec and Dispatch model_profile for {task_id}")
            if entry_has != spec_has:
                raise ContractError(f"model_profile presence mismatch for {task_id}")
            if entry_has:
                validate_model_profile(entry["model_profile"], schema, f"{task_id}.model_profile")
                validate_model_profile(spec["model_profile"], schema, f"task_spec.{task_id}.model_profile")
                if entry["model_profile"] != spec["model_profile"]:
                    raise ContractError(f"Dispatch/Task Spec model_profile mismatch for {task_id}")
                if entry["model_profile"] not in policy["owner_defaults"].values():
                    raise ContractError(f"{task_id}.model_profile is not an owner-policy default")

    static_dependencies = {
        task_id: list(spec["dependencies"]["blocked_by"]) for task_id, spec in specs.items()
    }
    static_parallel = {
        task_id: list(spec["dependencies"]["parallel_with"]) for task_id, spec in specs.items()
    }
    enforced = {
        task_id for task_id, entry in entries.items()
        if graph_enforcement_applies(plan, entry, specs[task_id], historical)
    }

    for task_id in enforced:
        for field, values in (("blocked_by", static_dependencies[task_id]),
                              ("parallel_with", static_parallel[task_id]),
                              ("plan.blocked_by", entries[task_id]["blocked_by"]),
                              ("plan.parallel_with", entries[task_id]["parallel_with"])):
            validate_string_list(values, f"{task_id}.{field}", canonical=True)
            if task_id in values:
                raise ContractError(f"{task_id}.{field} may not reference itself")
            unknown = set(values) - known
            if unknown:
                raise ContractError(f"{task_id}.{field} references unknown tasks: {sorted(unknown)}")
        if entries[task_id]["parallel_with"] != static_parallel[task_id]:
            raise ContractError(f"Dispatch/Task Spec parallel_with mismatch for {task_id}")

    visiting: list[str] = []
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            cycle = visiting[visiting.index(task_id):] + [task_id]
            raise ContractError(f"static dependency cycle: {' -> '.join(cycle)}")
        if task_id in visited:
            return
        visiting.append(task_id)
        for dependency in static_dependencies.get(task_id, []):
            if dependency in known:
                visit(dependency)
        visiting.pop()
        visited.add(task_id)

    for task_id in enforced:
        visit(task_id)

    reachability_cache: dict[tuple[str, str], bool] = {}

    def reachable(start: str, target: str, seen: set[str] | None = None) -> bool:
        key = (start, target)
        if key in reachability_cache:
            return reachability_cache[key]
        current_seen = set() if seen is None else seen
        if start in current_seen:
            return False
        current_seen.add(start)
        result = any(
            dependency == target or reachable(dependency, target, current_seen.copy())
            for dependency in static_dependencies.get(start, []) if dependency in known
        )
        reachability_cache[key] = result
        return result

    for task_id in enforced:
        dependencies = static_dependencies[task_id]
        for dependency in dependencies:
            for peer in dependencies:
                if dependency != peer and reachable(peer, dependency):
                    raise ContractError(
                        f"{task_id}.blocked_by contains redundant transitive dependency {dependency}"
                    )

    wave_cache: dict[str, int] = {}

    def derived_wave(task_id: str) -> int:
        if task_id in wave_cache:
            return wave_cache[task_id]
        if task_id not in enforced:
            return entries[task_id]["dispatch_wave"]
        dependencies = static_dependencies[task_id]
        result = 1 if not dependencies else 1 + max(derived_wave(item) for item in dependencies)
        wave_cache[task_id] = result
        return result

    for task_id in enforced:
        expected_wave = derived_wave(task_id)
        entry = entries[task_id]
        spec = specs[task_id]
        if entry["dispatch_wave"] != expected_wave or spec["dispatch_wave"] != expected_wave:
            raise ContractError(
                f"{task_id} dispatch_wave mismatch: expected={expected_wave}, "
                f"plan={entry['dispatch_wave']}, task_spec={spec['dispatch_wave']}"
            )

        unresolved = [dependency for dependency in static_dependencies[task_id]
                      if entries[dependency]["dispatch_status"] != "INTEGRATED"]
        live = entry["blocked_by"]
        status = entry["dispatch_status"]
        if status in {"GATED", "BLOCKED"}:
            if live != unresolved:
                raise ContractError(
                    f"{task_id} live blocker mismatch: expected={unresolved}, actual={live}"
                )
        elif status in {"READY", "PUBLISHED", "INTEGRATED"}:
            if unresolved or live:
                raise ContractError(
                    f"{task_id} status {status} requires resolved dependencies and empty blocked_by"
                )
        elif live:
            raise ContractError(f"terminal task {task_id} must clear live blocked_by")

    parallel_pairs: set[tuple[str, str]] = set()
    for task_id in enforced:
        for peer in static_parallel[task_id]:
            if task_id not in static_parallel.get(peer, []):
                raise ContractError(f"Task Spec parallel_with is not symmetric: {task_id}, {peer}")
            pair = tuple(sorted((task_id, peer)))
            if pair in parallel_pairs:
                continue
            parallel_pairs.add(pair)
            left, right = pair
            if reachable(left, right) or reachable(right, left):
                raise ContractError(f"parallel dependency conflict between {left} and {right}")
            if entries[left]["dispatch_wave"] != entries[right]["dispatch_wave"]:
                raise ContractError(f"parallel peers have unequal waves: {left}, {right}")
            if entries[left]["worktree"] == entries[right]["worktree"]:
                raise ContractError(f"parallel peers share worktree: {left}, {right}")
            overlaps = sorted(
                {f"{left}:{left_path} <-> {right}:{right_path}"
                 for left_path in owned_paths(specs[left]) for right_path in owned_paths(specs[right])
                 if paths_overlap(left_path, right_path)}
            )
            if overlaps:
                raise ContractError(f"parallel semantic ownership conflict: {overlaps}")


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
            enforce_expiry = not historical and entry["dispatch_status"] not in TERMINAL_DISPATCH_STATES
            validate_task_spec(spec, schema, enforce_authorization_expiry=enforce_expiry)
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
    validate_dispatch_graph_and_model_routing(value, specs, schema, historical=historical)
    return specs


def validate_persisted_plan_specs(value: dict[str, Any], schema: dict[str, Any]) -> None:
    load_persisted_plan_specs(value, schema)


def validate_worker_card(value: dict[str, Any], schema: dict[str, Any],
                         enforce_authorization_expiry: bool = True) -> None:
    require_exact_fields(value, schema_required(schema, "worker_card"), "Worker card")
    if value["schema_version"] != 1:
        raise ContractError("worker_card.schema_version must be 1")
    validate_positive_integer(value["record_revision"], "worker_card.record_revision")
    validate_authorization(value["authorization"], schema, enforce_expiry=enforce_authorization_expiry)
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
        denied_envelopes = (default_authorization(), default_authorization_v2())
        if value["authorization"] not in denied_envelopes:
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


def validate_master_card(value: dict[str, Any], schema: dict[str, Any], *, historical: bool = False) -> None:
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
    validate_candidate_evidence(evidence, schema)
    if (evidence.get("schema_version") != 2 and evidence["status"] in {"PASSED", "FAILED"}
            and not historical):
        raise ContractError(
            "current Master Card cannot use aggregate-only v1 PASSED/FAILED evidence; migrate it to v2 STALE"
        )
    if evidence.get("schema_version") == 2 and evidence["status"] != "NONE" and evidence["legacy"] is None:
        if evidence["release_task_id"] != value["release_task_id"]:
            raise ContractError("candidate release_task_id differs from the Master release lock")
        if evidence["plan_revision"] != value["plan_revision"]:
            raise ContractError("candidate plan_revision mixes a different Master semantic fence")
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


STABLE_EVIDENCE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
POSITION_ID_RE = re.compile(r"^(?:gate|check|item|row|index)-?[0-9]+$")
CANDIDATE_SOURCE_KINDS = {
    "git-commit", "git-tree", "file", "dispatch-plan", "task-spec", "acceptance", "gate-registry",
    "projection", "toolchain", "authorization",
}
WHOLE_CANDIDATE_REASONS = {
    "HEAD_CHANGED", "REGISTRY_AMBIGUOUS", "MAPPING_AMBIGUOUS", "DIGEST_UNVERIFIABLE",
    "PROVENANCE_UNVERIFIABLE", "REVISION_MIXED", "ATOMICITY_UNPROVEN",
}
SECRET_TEXT_RE = re.compile(
    r"-----BEGIN |(?:api[_-]?key|password|token)\s*[:=]|://[^/@\s:]+:[^/@\s]+@",
    re.IGNORECASE,
)


def validate_bounded_text(value: Any, label: str, *, maximum: int, allow_null: bool = False) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise ContractError(f"{label} must be a non-empty string of at most {maximum} UTF-8 bytes")
    if SECRET_TEXT_RE.search(value):
        raise ContractError(f"{label} appears to contain secret material")


def validate_bounded_canonical(value: Any, label: str, *, maximum: int = 16384) -> None:
    encoded = canonical_json(value)
    if len(encoded) > maximum:
        raise ContractError(f"{label} exceeds the {maximum}-byte persisted-manifest limit")

    def inspect(item: Any, path: str) -> None:
        if isinstance(item, str) and SECRET_TEXT_RE.search(item):
            raise ContractError(f"{label} appears to contain secret material at {path}")
        if isinstance(item, list):
            for index, child in enumerate(item):
                inspect(child, f"{path}[{index}]")
        elif isinstance(item, dict):
            for key, child in item.items():
                inspect(child, f"{path}.{key}")

    inspect(value, "$")


def validate_stable_evidence_id(value: Any, label: str) -> None:
    if (not isinstance(value, str) or len(value.encode("utf-8")) > 96
            or not STABLE_EVIDENCE_ID_RE.fullmatch(value)):
        raise ContractError(f"{label} must be a stable lowercase kebab-case identifier")
    if POSITION_ID_RE.fullmatch(value) or SHA_RE.fullmatch(value):
        raise ContractError(f"{label} must not be position-derived or content-derived")


def sorted_utf8(values: list[str]) -> list[str]:
    return sorted(values, key=lambda item: item.encode("utf-8"))


def validate_candidate_v1(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "candidate_evidence_v1"), "candidate evidence v1")
    validate_digest(value["gate_input_digest"], "gate_input_digest", allow_null=True)
    validate_sha(value["release_head_sha"], "candidate release_head_sha", allow_null=True)
    if value["status"] not in {"NONE", "STALE", "PASSED", "FAILED"}:
        raise ContractError(f"unknown candidate status: {value['status']}")
    if not isinstance(value["checks"], list):
        raise ContractError("candidate checks must be an array")
    for check in value["checks"]:
        if not isinstance(check, dict):
            raise ContractError("candidate check must be an object")
        require_exact_fields(check, {"command", "result", "evidence_digest"}, "candidate check v1")
        validate_bounded_text(check["command"], "candidate check command", maximum=1024)
        if check["result"] not in {"PASS", "FAIL"}:
            raise ContractError(f"unknown candidate check result: {check['result']}")
        validate_digest(check["evidence_digest"], "candidate check evidence_digest")
    if value["status"] == "NONE" and any((value["release_head_sha"], value["gate_input_digest"], value["checks"])):
        historical_error("H24", "candidate status NONE cannot retain candidate evidence")
    if value["status"] in {"STALE", "PASSED", "FAILED"} and (
        value["release_head_sha"] is None or value["gate_input_digest"] is None or not value["checks"]
    ):
        raise ContractError(f"candidate status {value['status']} requires HEAD, gate digest, and checks")


def validate_registry_check(value: Any, schema: dict[str, Any], label: str) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    require_exact_fields(value, schema_required(schema, "candidate_registry_check"), label)
    validate_stable_evidence_id(value["check_id"], f"{label}.check_id")
    validate_positive_integer(value["check_revision"], f"{label}.check_revision")
    for field in ("command_spec", "runner_policy"):
        validate_bounded_canonical(value[field], f"{label}.{field}")
        validate_digest(value[f"{field}_digest"], f"{label}.{field}_digest")
        if value[f"{field}_digest"] != value_digest(value[field]):
            raise ContractError(f"{label}.{field}_digest does not match its canonical manifest")
    validate_string_list(value["input_source_ids"], f"{label}.input_source_ids", canonical=True)
    if not value["input_source_ids"]:
        raise ContractError(f"{label}.input_source_ids must not be empty")
    for source_id in value["input_source_ids"]:
        validate_stable_evidence_id(source_id, f"{label}.input_source_ids")


def validate_candidate_registry(value: Any, schema: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ContractError("candidate Gate registry must be a non-empty array")
    if len(value) > 64:
        raise ContractError("candidate Gate registry exceeds 64 Gates")
    gate_ids = [item.get("gate_id") if isinstance(item, dict) else None for item in value]
    if any(not isinstance(item, str) for item in gate_ids) or gate_ids != sorted_utf8(cast(list[str], gate_ids)):
        raise ContractError("candidate Gate registry must use canonical gate_id order")
    registry: dict[tuple[str, int], dict[str, Any]] = {}
    logical_gate_ids: set[str] = set()
    for index, gate in enumerate(value):
        label = f"candidate gate_registry[{index}]"
        if not isinstance(gate, dict):
            raise ContractError(f"{label} must be an object")
        require_exact_fields(gate, schema_required(schema, "candidate_registry_gate"), label)
        validate_stable_evidence_id(gate["gate_id"], f"{label}.gate_id")
        validate_positive_integer(gate["gate_revision"], f"{label}.gate_revision")
        if not isinstance(gate["required"], bool):
            raise ContractError(f"{label}.required must be boolean")
        identity = (gate["gate_id"], gate["gate_revision"])
        if identity in registry or gate["gate_id"] in logical_gate_ids:
            raise ContractError(f"duplicate or ambiguous Gate identity: {identity}")
        registry[identity] = gate
        logical_gate_ids.add(gate["gate_id"])
        for field in ("gate_definition", "runner_policy"):
            validate_bounded_canonical(gate[field], f"{label}.{field}")
            validate_digest(gate[f"{field}_digest"], f"{label}.{field}_digest")
            if gate[f"{field}_digest"] != value_digest(gate[field]):
                raise ContractError(f"{label}.{field}_digest does not match its canonical manifest")
        checks = gate["checks"]
        if not isinstance(checks, list) or not checks or len(checks) > 64:
            raise ContractError(f"{label}.checks must contain 1..64 checks")
        check_ids = [item.get("check_id") if isinstance(item, dict) else None for item in checks]
        if any(not isinstance(item, str) for item in check_ids) or check_ids != sorted_utf8(cast(list[str], check_ids)):
            raise ContractError(f"{label}.checks must use canonical check_id order")
        seen_checks: set[tuple[str, int]] = set()
        logical_check_ids: set[str] = set()
        for check_index, check in enumerate(checks):
            check_label = f"{label}.checks[{check_index}]"
            validate_registry_check(check, schema, check_label)
            check_identity = (check["check_id"], check["check_revision"])
            if check_identity in seen_checks or check["check_id"] in logical_check_ids:
                raise ContractError(f"duplicate or ambiguous check identity in {gate['gate_id']}: {check_identity}")
            seen_checks.add(check_identity)
            logical_check_ids.add(check["check_id"])
    if not any(gate["required"] for gate in value):
        raise ContractError("candidate Gate registry must contain at least one required Gate")
    return registry


def validate_candidate_source(value: Any, schema: dict[str, Any], label: str) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    require_exact_fields(value, schema_required(schema, "candidate_input_source"), label)
    validate_stable_evidence_id(value["source_id"], f"{label}.source_id")
    if value["kind"] not in CANDIDATE_SOURCE_KINDS:
        raise ContractError(f"{label}.kind is unknown")
    validate_bounded_text(value["locator"], f"{label}.locator", maximum=512)
    validate_bounded_text(value["revision"], f"{label}.revision", maximum=256, allow_null=True)
    validate_digest(value["value_digest"], f"{label}.value_digest")


def candidate_check_input_digest(gate: dict[str, Any], registry_gate: dict[str, Any],
                                 check: dict[str, Any], registry_check: dict[str, Any]) -> str:
    sources = {source["source_id"]: source for source in gate["input_sources"]}
    resolved = [sources[source_id] for source_id in registry_check["input_source_ids"]]
    return value_digest({
        "schema_version": 1,
        "gate_id": gate["gate_id"],
        "gate_revision": gate["gate_revision"],
        "check_id": check["check_id"],
        "check_revision": check["check_revision"],
        "command_spec_digest": registry_check["command_spec_digest"],
        "input_source_ids": registry_check["input_source_ids"],
        "input_sources": resolved,
        "runner_policy_digest": registry_check["runner_policy_digest"],
    })


def candidate_gate_input_digest(gate: dict[str, Any], registry_gate: dict[str, Any],
                                check_input_digests: dict[tuple[str, int], str]) -> str:
    return value_digest({
        "schema_version": 1,
        "gate_id": gate["gate_id"],
        "gate_revision": gate["gate_revision"],
        "required": gate["required"],
        "gate_definition_digest": registry_gate["gate_definition_digest"],
        "input_sources": gate["input_sources"],
        "checks": [
            {
                "check_id": check["check_id"],
                "check_revision": check["check_revision"],
                "input_digest": check_input_digests[(check["check_id"], check["check_revision"])],
            }
            for check in registry_gate["checks"]
        ],
        "runner_policy_digest": registry_gate["runner_policy_digest"],
    })


def candidate_gate_input_summary(value: dict[str, Any], gate_inputs: dict[tuple[str, int], str]) -> str:
    return value_digest({
        "schema_version": 1,
        "release_task_id": value["release_task_id"],
        "release_head_sha": value["release_head_sha"],
        "gates": [
            {
                "gate_id": gate["gate_id"],
                "gate_revision": gate["gate_revision"],
                "required": gate["required"],
                "input_digest": gate_inputs[(gate["gate_id"], gate["gate_revision"])],
            }
            for gate in value["gates"]
        ],
    })


def candidate_check_evidence_digest(gate: dict[str, Any], check: dict[str, Any]) -> str:
    return value_digest({
        "schema_version": 1,
        "gate_id": gate["gate_id"],
        "gate_revision": gate["gate_revision"],
        "check_id": check["check_id"],
        "check_revision": check["check_revision"],
        "input_digest": check["input_digest"],
        "result": check["result"],
        "exit_code": check["exit_code"],
        "stdout_digest": check["stdout_digest"],
        "stderr_digest": check["stderr_digest"],
        "observed_artifacts": check["observed_artifacts"],
        "runner_digest": check["runner_digest"],
        "execution_ref": check["execution_ref"],
        "observed_at": check["observed_at"],
    })


def candidate_gate_evidence_digest(gate: dict[str, Any]) -> str:
    return value_digest({
        "schema_version": 1,
        "gate_id": gate["gate_id"],
        "gate_revision": gate["gate_revision"],
        "input_digest": gate["input_digest"],
        "checks": [
            {
                "check_id": check["check_id"],
                "check_revision": check["check_revision"],
                "result": check["result"],
                "evidence_digest": check["evidence_digest"],
            }
            for check in gate["checks"]
        ],
    })


def aggregate_candidate_status(gates: list[dict[str, Any]]) -> str:
    required = [gate for gate in gates if gate["required"]]
    if not required or any(gate["status"] in {"NONE", "STALE"} for gate in required):
        return "STALE"
    if any(gate["status"] == "FAILED" for gate in required):
        return "FAILED"
    if all(gate["status"] == "PASSED" for gate in required):
        return "PASSED"
    return "STALE"


def validate_candidate_check(check: Any, gate: dict[str, Any], registry_check: dict[str, Any],
                             expected_input_digest: str, schema: dict[str, Any], label: str) -> None:
    if not isinstance(check, dict):
        raise ContractError(f"{label} must be an object")
    require_exact_fields(check, schema_required(schema, "candidate_check_v2"), label)
    validate_stable_evidence_id(check["check_id"], f"{label}.check_id")
    validate_positive_integer(check["check_revision"], f"{label}.check_revision")
    if (check["check_id"], check["check_revision"]) != (
        registry_check["check_id"], registry_check["check_revision"]
    ):
        raise ContractError(f"{label} does not match its registered check identity")
    validate_bounded_text(check["command"], f"{label}.command", maximum=1024)
    validate_string_list(check["input_source_ids"], f"{label}.input_source_ids", canonical=True)
    if check["input_source_ids"] != registry_check["input_source_ids"]:
        raise ContractError(f"{label}.input_source_ids differs from the registered dependency map")
    if check["result"] not in {"PASS", "FAIL"}:
        raise ContractError(f"{label}.result is unknown")
    for field in ("input_digest", "evidence_digest", "stdout_digest", "stderr_digest", "runner_digest"):
        validate_digest(check[field], f"{label}.{field}")
    if check["input_digest"] != expected_input_digest:
        raise ContractError(f"{label}.input_digest does not match its canonical input envelope")
    validate_bounded_text(check["execution_ref"], f"{label}.execution_ref", maximum=256)
    if not isinstance(check["exit_code"], int) or isinstance(check["exit_code"], bool):
        raise ContractError(f"{label}.exit_code must be an integer")
    validate_rfc3339(check["observed_at"], f"{label}.observed_at")
    artifacts = check["observed_artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) > 64:
        raise ContractError(f"{label}.observed_artifacts must contain at most 64 entries")
    locators: list[str] = []
    for artifact_index, artifact in enumerate(artifacts):
        artifact_label = f"{label}.observed_artifacts[{artifact_index}]"
        if not isinstance(artifact, dict):
            raise ContractError(f"{artifact_label} must be an object")
        require_exact_fields(artifact, schema_required(schema, "candidate_observed_artifact"), artifact_label)
        validate_bounded_text(artifact["locator"], f"{artifact_label}.locator", maximum=512)
        validate_digest(artifact["value_digest"], f"{artifact_label}.value_digest")
        locators.append(artifact["locator"])
    if locators != sorted_utf8(locators) or len(set(locators)) != len(locators):
        raise ContractError(f"{label}.observed_artifacts must use unique canonical locator order")
    command_spec = registry_check["command_spec"]
    if not isinstance(command_spec, dict) or not isinstance(command_spec.get("success_exit_codes"), list):
        raise ContractError(f"{label} registered command_spec must declare success_exit_codes")
    success_codes = command_spec["success_exit_codes"]
    if (not success_codes or any(not isinstance(code, int) or isinstance(code, bool) for code in success_codes)
            or len(set(success_codes)) != len(success_codes)):
        raise ContractError(f"{label} success_exit_codes must be unique integers")
    expected_result = "PASS" if check["exit_code"] in success_codes else "FAIL"
    if check["result"] != expected_result:
        raise ContractError(f"{label}.result contradicts exit_code and the registered success predicate")
    if check["evidence_digest"] != candidate_check_evidence_digest(gate, check):
        raise ContractError(f"{label}.evidence_digest does not match its canonical evidence envelope")


def validate_fallback_candidate(value: dict[str, Any], schema: dict[str, Any]) -> None:
    if value["status"] != "STALE" or value["gate_registry"] or value["gate_registry_digest"] is not None:
        raise ContractError("unmapped candidate fallback must be STALE with no asserted Gate registry")
    if value["gate_input_digest"] is not None or not value["gates"]:
        raise ContractError("unmapped candidate fallback must not assert an aggregate input digest")
    identities: set[tuple[str, int]] = set()
    for index, gate in enumerate(value["gates"]):
        label = f"candidate fallback gates[{index}]"
        if not isinstance(gate, dict):
            raise ContractError(f"{label} must be an object")
        require_exact_fields(gate, schema_required(schema, "candidate_gate_v2"), label)
        validate_stable_evidence_id(gate["gate_id"], f"{label}.gate_id")
        validate_positive_integer(gate["gate_revision"], f"{label}.gate_revision")
        identity = (gate["gate_id"], gate["gate_revision"])
        if identity in identities:
            raise ContractError(f"duplicate fallback Gate identity: {identity}")
        identities.add(identity)
        if not isinstance(gate["required"], bool):
            raise ContractError(f"{label}.required must be boolean")
        if (gate["status"] != "STALE" or gate["input_digest"] is not None
                or gate["evidence_digest"] is not None or gate["checks"]):
            raise ContractError(f"{label} must clear all unverifiable current evidence")
        if gate["invalidation_reason"] not in WHOLE_CANDIDATE_REASONS:
            raise ContractError(f"{label} must record a whole-candidate fallback reason")
        sources = gate["input_sources"]
        if not isinstance(sources, list) or len(sources) > 64:
            raise ContractError(f"{label}.input_sources must be an array")
        source_ids = [item.get("source_id") if isinstance(item, dict) else None for item in sources]
        if any(not isinstance(item, str) for item in source_ids) or source_ids != sorted_utf8(cast(list[str], source_ids)):
            raise ContractError(f"{label}.input_sources must use canonical source_id order")
        if len(set(cast(list[str], source_ids))) != len(source_ids):
            raise ContractError(f"{label}.input_sources contains duplicate source IDs")
        for source_index, source in enumerate(sources):
            validate_candidate_source(source, schema, f"{label}.input_sources[{source_index}]")


def validate_candidate_v2(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "candidate_evidence_v2"), "candidate evidence v2")
    if value["schema_version"] != 2 or isinstance(value["schema_version"], bool):
        raise ContractError("candidate_evidence.schema_version must be 2")
    validate_bounded_text(value["release_task_id"], "candidate release_task_id", maximum=256, allow_null=True)
    validate_sha(value["release_head_sha"], "candidate release_head_sha", allow_null=True)
    if value["plan_revision"] is not None:
        validate_positive_integer(value["plan_revision"], "candidate plan_revision")
    for field in ("plan_digest", "gate_registry_digest", "gate_input_digest"):
        validate_digest(value[field], f"candidate {field}", allow_null=True)
    if value["status"] not in {"NONE", "STALE", "PASSED", "FAILED"}:
        raise ContractError(f"unknown candidate status: {value['status']}")
    if not isinstance(value["gates"], list) or not isinstance(value["gate_registry"], list):
        raise ContractError("candidate gates and gate_registry must be arrays")
    legacy = value["legacy"]
    if legacy is not None:
        if not isinstance(legacy, dict):
            raise ContractError("candidate legacy audit must be an object or null")
        require_exact_fields(legacy, schema_required(schema, "candidate_legacy_audit"), "candidate legacy audit")
        if legacy["reason"] != "LEGACY_AGGREGATE_ONLY":
            raise ContractError("candidate legacy reason is unknown")
        validate_candidate_v1(legacy["original"], schema)
        validate_digest(legacy["original_digest"], "candidate legacy original_digest")
        if legacy["original_digest"] != value_digest(legacy["original"]):
            raise ContractError("candidate legacy original_digest does not preserve the original record")
        has_material = any((legacy["original"]["release_head_sha"], legacy["original"]["gate_input_digest"],
                            legacy["original"]["checks"]))
        expected_status = "STALE" if has_material else "NONE"
        if value["status"] != expected_status:
            raise ContractError(f"legacy migration must produce {expected_status}")
        if value["gates"] or value["gate_registry"] or any(
            value[field] is not None for field in ("gate_registry_digest", "gate_input_digest")
        ):
            raise ContractError("legacy migration must not synthesize Gate identity or per-Gate digests")
        return
    if value["status"] == "NONE":
        retained = (
            value["release_task_id"], value["release_head_sha"], value["plan_revision"], value["plan_digest"],
            value["gate_registry_digest"], value["gate_input_digest"], value["gate_registry"], value["gates"],
        )
        if any(retained):
            historical_error("H24", "candidate status NONE cannot retain candidate evidence")
        return
    if value["release_task_id"] is None or value["release_head_sha"] is None or value["plan_revision"] is None:
        raise ContractError("non-NONE candidate v2 requires release task, exact HEAD, and plan fence")
    if not value["gate_registry"] and value["status"] == "STALE":
        validate_fallback_candidate(value, schema)
        return
    registry = validate_candidate_registry(value["gate_registry"], schema)
    if value["gate_registry_digest"] != value_digest({"schema_version": 1, "gates": value["gate_registry"]}):
        raise ContractError("candidate gate_registry_digest does not match the canonical registry")
    gate_ids = [item.get("gate_id") if isinstance(item, dict) else None for item in value["gates"]]
    if any(not isinstance(item, str) for item in gate_ids) or gate_ids != sorted_utf8(cast(list[str], gate_ids)):
        raise ContractError("candidate gates must use canonical gate_id order")
    if len(value["gates"]) != len(registry):
        raise ContractError("candidate Gate membership is incomplete or contains unknown rows")
    gate_inputs: dict[tuple[str, int], str] = {}
    gate_identities: set[tuple[str, int]] = set()
    for gate_index, gate in enumerate(value["gates"]):
        label = f"candidate gates[{gate_index}]"
        if not isinstance(gate, dict):
            raise ContractError(f"{label} must be an object")
        require_exact_fields(gate, schema_required(schema, "candidate_gate_v2"), label)
        validate_stable_evidence_id(gate["gate_id"], f"{label}.gate_id")
        validate_positive_integer(gate["gate_revision"], f"{label}.gate_revision")
        identity = (gate["gate_id"], gate["gate_revision"])
        if identity in gate_identities:
            raise ContractError(f"duplicate candidate Gate identity: {identity}")
        gate_identities.add(identity)
        registry_gate = registry.get(identity)
        if registry_gate is None:
            raise ContractError(f"unknown or revision-mismatched candidate Gate identity: {identity}")
        if gate["required"] is not registry_gate["required"]:
            raise ContractError(f"{label}.required differs from the Gate registry")
        sources = gate["input_sources"]
        if not isinstance(sources, list) or not sources or len(sources) > 64:
            raise ContractError(f"{label}.input_sources must contain 1..64 sources")
        source_ids = [item.get("source_id") if isinstance(item, dict) else None for item in sources]
        if any(not isinstance(item, str) for item in source_ids) or source_ids != sorted_utf8(cast(list[str], source_ids)):
            raise ContractError(f"{label}.input_sources must use canonical source_id order")
        if len(set(cast(list[str], source_ids))) != len(source_ids):
            raise ContractError(f"{label}.input_sources contains duplicate source IDs")
        for source_index, source in enumerate(sources):
            validate_candidate_source(source, schema, f"{label}.input_sources[{source_index}]")
        integrated = [source for source in sources if source["source_id"] == "integrated-tree"]
        if (len(integrated) != 1 or integrated[0]["kind"] != "git-commit"
                or integrated[0]["revision"] != value["release_head_sha"]):
            raise ContractError(f"{label} is not bound to the exact integrated release_head_sha")
        registry_checks = {
            (check["check_id"], check["check_revision"]): check for check in registry_gate["checks"]
        }
        declared_sources = set(cast(list[str], source_ids))
        for registry_check in registry_gate["checks"]:
            if not set(registry_check["input_source_ids"]).issubset(declared_sources):
                raise ContractError(f"{label} has an incomplete registered source dependency map")
        check_inputs: dict[tuple[str, int], str] = {}
        for registry_check in registry_gate["checks"]:
            key = (registry_check["check_id"], registry_check["check_revision"])
            check_inputs[key] = candidate_check_input_digest(gate, registry_gate, registry_check, registry_check)
        expected_gate_input = candidate_gate_input_digest(gate, registry_gate, check_inputs)
        gate_inputs[identity] = expected_gate_input
        if gate["status"] in {"PASSED", "FAILED"}:
            if gate["input_digest"] != expected_gate_input or gate["evidence_digest"] is None:
                raise ContractError(f"{label} current result is not bound to its exact input manifest")
            if gate["invalidation_reason"] is not None:
                raise ContractError(f"{label} current result cannot retain an invalidation reason")
            checks = gate["checks"]
            if not isinstance(checks, list) or len(checks) != len(registry_checks):
                raise ContractError(f"{label} current result has incomplete check membership")
            check_ids = [item.get("check_id") if isinstance(item, dict) else None for item in checks]
            if any(not isinstance(item, str) for item in check_ids) or check_ids != sorted_utf8(cast(list[str], check_ids)):
                raise ContractError(f"{label}.checks must use canonical check_id order")
            seen_checks: set[tuple[str, int]] = set()
            for check_index, check in enumerate(checks):
                if not isinstance(check, dict):
                    raise ContractError(f"{label}.checks[{check_index}] must be an object")
                check_identity = (check.get("check_id"), check.get("check_revision"))
                if check_identity in seen_checks or check_identity not in registry_checks:
                    raise ContractError(f"duplicate or unknown check identity in {label}: {check_identity}")
                seen_checks.add(cast(tuple[str, int], check_identity))
                validate_candidate_check(
                    check, gate, registry_checks[cast(tuple[str, int], check_identity)],
                    check_inputs[cast(tuple[str, int], check_identity)], schema, f"{label}.checks[{check_index}]",
                )
            expected_gate_status = "FAILED" if any(check["result"] == "FAIL" for check in checks) else "PASSED"
            if gate["status"] != expected_gate_status:
                raise ContractError(f"{label}.status contradicts its current check results")
            if gate["evidence_digest"] != candidate_gate_evidence_digest(gate):
                raise ContractError(f"{label}.evidence_digest does not match its canonical evidence envelope")
        elif gate["status"] in {"STALE", "NONE"}:
            if (gate["input_digest"] is not None or gate["evidence_digest"] is not None or gate["checks"]
                    or gate["invalidation_reason"] is None):
                raise ContractError(f"{label} stale/none row must clear evidence and record a reason")
        else:
            raise ContractError(f"{label}.status is unknown")
    expected_summary = candidate_gate_input_summary(value, gate_inputs)
    if value["gate_input_digest"] != expected_summary:
        raise ContractError("candidate gate_input_digest does not match the per-Gate input manifests")
    expected_status = aggregate_candidate_status(value["gates"])
    if value["status"] != expected_status:
        raise ContractError(f"candidate status must aggregate to {expected_status}")


def validate_candidate_evidence(value: Any, schema: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ContractError("candidate evidence must be an object")
    if value.get("schema_version") == 2:
        validate_candidate_v2(value, schema)
    else:
        validate_candidate_v1(value, schema)


def candidate_manifest_digests(value: dict[str, Any]) -> dict[str, str]:
    registry = {gate["gate_id"]: gate for gate in value["gate_registry"]}
    result: dict[str, str] = {}
    for gate in value["gates"]:
        registry_gate = registry[gate["gate_id"]]
        check_inputs: dict[tuple[str, int], str] = {}
        for registry_check in registry_gate["checks"]:
            identity = (registry_check["check_id"], registry_check["check_revision"])
            check_inputs[identity] = candidate_check_input_digest(
                gate, registry_gate, registry_check, registry_check,
            )
        result[gate["gate_id"]] = candidate_gate_input_digest(gate, registry_gate, check_inputs)
    return result


def legacy_v1_has_evidence(value: dict[str, Any]) -> bool:
    return any((value["release_head_sha"], value["gate_input_digest"], value["checks"]))


def evaluate_candidate_invalidation(previous: dict[str, Any], current: dict[str, Any],
                                    schema: dict[str, Any]) -> tuple[str, list[str]]:
    """Return NONE, AFFECTED, or ALL without mutating either evidence record."""
    validate_candidate_evidence(previous, schema)
    validate_candidate_evidence(current, schema)
    current_gate_ids = sorted_utf8([
        gate["gate_id"] for gate in current.get("gates", []) if isinstance(gate, dict) and "gate_id" in gate
    ])
    if previous.get("schema_version") != 2 or current.get("schema_version") != 2:
        legacy_values = [value for value in (previous, current) if value.get("schema_version") != 2]
        if any(legacy_v1_has_evidence(value) for value in legacy_values):
            return "ALL", current_gate_ids
        return "NONE", []
    if previous.get("legacy") is not None or current.get("legacy") is not None:
        if previous == current:
            return "NONE", []
        return "ALL", current_gate_ids
    if (previous.get("release_task_id"), previous.get("release_head_sha")) != (
        current.get("release_task_id"), current.get("release_head_sha")
    ):
        return "ALL", current_gate_ids
    if not previous.get("gate_registry") or not current.get("gate_registry"):
        return "ALL", current_gate_ids
    previous_membership = {
        gate["gate_id"]: gate["required"] for gate in previous["gate_registry"]
    }
    current_membership = {
        gate["gate_id"]: gate["required"] for gate in current["gate_registry"]
    }
    if previous_membership != current_membership:
        return "ALL", current_gate_ids
    try:
        previous_inputs = candidate_manifest_digests(previous)
        current_inputs = candidate_manifest_digests(current)
    except (ContractError, KeyError, TypeError):
        return "ALL", current_gate_ids
    affected = sorted_utf8([
        gate_id for gate_id in current_membership if previous_inputs.get(gate_id) != current_inputs.get(gate_id)
    ])
    return ("AFFECTED", affected) if affected else ("NONE", [])


def migrate_candidate_evidence(value: dict[str, Any], schema: dict[str, Any], *,
                               release_task_id: str | None = None, plan_revision: int | None = None,
                               plan_digest: str | None = None) -> dict[str, Any]:
    if value.get("schema_version") == 2:
        validate_candidate_v2(value, schema)
        return copy.deepcopy(value)
    validate_candidate_v1(value, schema)
    if release_task_id is not None:
        validate_bounded_text(release_task_id, "release_task_id", maximum=256)
    if plan_revision is not None:
        validate_positive_integer(plan_revision, "plan_revision")
    validate_digest(plan_digest, "plan_digest", allow_null=True)
    has_material = legacy_v1_has_evidence(value)
    migrated = {
        "schema_version": 2,
        "release_task_id": release_task_id,
        "release_head_sha": value["release_head_sha"],
        "plan_revision": plan_revision,
        "plan_digest": plan_digest,
        "gate_registry_digest": None,
        "gate_registry": [],
        "gate_input_digest": None,
        "status": "STALE" if has_material else "NONE",
        "legacy": {
            "reason": "LEGACY_AGGREGATE_ONLY",
            "original_digest": value_digest(value),
            "original": copy.deepcopy(value),
        },
        "gates": [],
    }
    validate_candidate_v2(migrated, schema)
    return migrated


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
    previous_version = previous.get("schema_version", 1)
    current_version = current.get("schema_version", 1)
    if previous_version == 1 and current_version == 2:
        legacy = current.get("legacy")
        if not isinstance(legacy, dict) or legacy.get("original") != previous:
            historical_error("H25", "v1 candidate migration did not preserve the exact aggregate record")
        if current["status"] not in {"NONE", "STALE"}:
            historical_error("H25", "v1 candidate migration promoted aggregate evidence")
        return
    if previous_version == 2 and current_version == 1:
        historical_error("H25", "candidate evidence cannot downgrade from per-Gate v2 to aggregate v1")
    if previous_version == 2 and current_version == 2:
        if previous.get("legacy") is not None or current.get("legacy") is not None:
            if previous != current:
                historical_error("H25", "migrated legacy audit evidence was rewritten")
            return
        previous_identity = (previous.get("release_task_id"), previous.get("release_head_sha"))
        current_identity = (current.get("release_task_id"), current.get("release_head_sha"))
        previous_gates = {
            (gate["gate_id"], gate["gate_revision"]): gate for gate in previous.get("gates", [])
        }
        current_gates = {
            (gate["gate_id"], gate["gate_revision"]): gate for gate in current.get("gates", [])
        }
        membership_changed = set(previous_gates) != set(current_gates)
        for identity in set(previous_gates) & set(current_gates):
            old_gate = previous_gates[identity]
            new_gate = current_gates[identity]
            old_current = old_gate.get("status") in {"PASSED", "FAILED"}
            new_current = new_gate.get("status") in {"PASSED", "FAILED"}
            evidence_reused = (old_gate.get("evidence_digest") is not None
                               and old_gate.get("evidence_digest") == new_gate.get("evidence_digest"))
            input_changed = old_gate.get("input_digest") != new_gate.get("input_digest")
            if previous_identity != current_identity and old_current and new_current and evidence_reused:
                historical_error("H25", "per-Gate evidence was reused for a different candidate identity")
            if membership_changed and old_current and new_current and evidence_reused:
                historical_error("H25", "Gate membership changed while prior evidence remained current")
            if input_changed and old_current and new_current and evidence_reused:
                historical_error("H25", "per-Gate evidence remained usable after its relevant inputs changed")
            if (not input_changed and old_current and new_current
                    and {old_gate["status"], new_gate["status"]} == {"PASSED", "FAILED"}
                    and evidence_reused):
                historical_error("H26", "per-Gate result flipped without new evidence")
        return
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
            revision_lineage = (
                entry["revision_decision"] == "REVISE"
                or (
                    entry["revision_decision"] == "GRANDFATHER"
                    and entry["task_spec_plan_revision"] < plan["plan_revision"]
                )
            )
            preserved_rework = (
                handoff["state"] == "REWORK_REQUESTED"
                and revision_lineage
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


def child_mapping_keys(block: str, parent: str, parent_indent: int) -> set[str]:
    lines = block.splitlines()
    marker = " " * parent_indent + f"{parent}:"
    try:
        start = lines.index(marker) + 1
    except ValueError as error:
        raise ContractError(f"missing {parent} mapping at indentation {parent_indent}") from error
    child_indent = parent_indent + 2
    children: list[str] = []
    for line in lines[start:]:
        if line.strip() and len(line) - len(line.lstrip(" ")) <= parent_indent:
            break
        children.append(line)
    return yaml_like_keys("\n".join(children), child_indent)


def validate_documented_contracts(repo_root: Path, schema: dict[str, Any]) -> None:
    methodology = (repo_root / "references" / "methodology.md").read_text(encoding="utf-8")
    templates = (repo_root / "references" / "templates.md").read_text(encoding="utf-8")
    canonical = extract_code_block(methodology, "## Canonical authorization envelope")
    task = extract_code_block(methodology, "## Task publication contract")
    worker = extract_code_block(methodology, "Worker card:")
    master = extract_code_block(methodology, "Master card uses a list")
    plan = extract_code_block(methodology, "The plan is versioned and contains at least:")
    template_plan = extract_code_block(templates, "## Task Dependency and Dispatch Plan")
    required = schema_required(schema, "authorization_v2")
    for label, block in (("canonical authorization", canonical), ("task authorization", task), ("Worker authorization", worker)):
        keys = nested_mapping_keys(block, "authorization")
        if keys != required:
            raise ContractError(f"{label} fields drifted from schema; missing={sorted(required-keys)}, extra={sorted(keys-required)}")
        capability_keys = child_mapping_keys(block, "capabilities", 2)
        expected_capabilities = {"external_call", "create_execution", "publish", "destructive_operation"}
        if capability_keys != expected_capabilities:
            raise ContractError(f"{label} capability fields drifted from schema")
        for capability in expected_capabilities:
            grant_keys = child_mapping_keys(block, capability, 4)
            schema_keys = schema_required(schema, f"authorization_grant_{capability}")
            if grant_keys != schema_keys:
                raise ContractError(f"{label} {capability} grant fields drifted from schema; "
                                    f"missing={sorted(schema_keys-grant_keys)}, extra={sorted(grant_keys-schema_keys)}")
    projections = (("task spec", task, "task_spec", True), ("Worker card", worker, "worker_card", False),
                   ("Master card", master, "master_card", False),
                   ("Dispatch Plan", plan, "dispatch_plan", True))
    for label, block, definition, include_optional in projections:
        keys = yaml_like_keys(block, 0)
        expected_keys = schema_properties(schema, definition) if include_optional else schema_required(schema, definition)
        if keys != expected_keys:
            raise ContractError(f"{label} top-level fields drifted from schema; "
                                f"missing={sorted(expected_keys-keys)}, extra={sorted(keys-expected_keys)}")
    expected_profile_keys = schema_required(schema, "model_profile")
    for label, block, indent in (("task spec", task, 0), ("Dispatch Plan", plan, 4)):
        profile_keys = (nested_mapping_keys(block, "model_profile") if indent == 0
                        else child_mapping_keys(block, "model_profile", indent))
        if profile_keys != expected_profile_keys:
            raise ContractError(f"{label} model_profile fields drifted from schema")
    policy_keys = nested_mapping_keys(plan, "model_policy")
    if policy_keys != schema_required(schema, "model_policy"):
        raise ContractError("Dispatch Plan model_policy fields drifted from schema")
    owner_defaults = child_mapping_keys(plan, "owner_defaults", 2)
    if owner_defaults != schema_required(schema, "model_owner_defaults"):
        raise ContractError("Dispatch Plan model owner-default keys drifted from schema")
    if yaml_like_keys(template_plan, 0) != schema_properties(schema, "dispatch_plan"):
        raise ContractError("template Dispatch Plan top-level fields drifted from schema")
    if child_mapping_keys(template_plan, "model_profile", 4) != expected_profile_keys:
        raise ContractError("template Dispatch Plan model_profile fields drifted from schema")
    if nested_mapping_keys(template_plan, "model_policy") != schema_required(schema, "model_policy"):
        raise ContractError("template Dispatch Plan model_policy fields drifted from schema")
    if child_mapping_keys(template_plan, "owner_defaults", 2) != schema_required(schema, "model_owner_defaults"):
        raise ContractError("template Dispatch Plan model owner-default keys drifted from schema")
    dispatch_enum = set(schema["$defs"]["dispatch_task"]["properties"]["dispatch_status"]["enum"])
    decision_enum = set(schema["$defs"]["dispatch_task"]["properties"]["revision_decision"]["enum"])
    for label, block in (("methodology plan", plan), ("template plan", template_plan)):
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
        model_terms = (
            "gpt-5.6-sol", "gpt-5.6-luna", "service_tier", "owner-default:master",
            "owner-default:ordinary-worker", "owner-default:complex-worker",
        )
        missing_model_terms = [term for term in model_terms if term not in contents]
        if missing_model_terms:
            raise ContractError(f"model-routing contract missing from {relative}: {missing_model_terms}")


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


def default_authorization_grant(execution: bool = False) -> CapabilityGrant | ExecutionCapabilityGrant:
    grant: dict[str, Any] = {
        "allowed": False,
        "target": None,
        "route": None,
        "provider": None,
        "max_calls": 0,
        "max_cost": 0,
        "cost_unit": None,
    }
    if execution:
        grant.update({"fresh_execution_required": True, "resume_execution_id": None})
    return grant


def default_authorization_v2() -> AuthorizationV2:
    value = {
        "schema_version": 2,
        "capabilities": {
            "external_call": default_authorization_grant(),
            "create_execution": default_authorization_grant(execution=True),
            "publish": default_authorization_grant(),
            "destructive_operation": default_authorization_grant(),
        },
        "controlled_input": None,
        "controlled_input_digest": None,
        "expires_at": None,
        "envelope_digest": None,
    }
    value["envelope_digest"] = object_digest(value, "envelope_digest")
    return cast(AuthorizationV2, value)


def adapt_authorization_v1_to_v2(value: dict[str, Any], schema: dict[str, Any]) -> AuthorizationV2:
    """Return a new v2 default-deny value for the only unambiguous v1 envelope."""
    source = copy.deepcopy(value)
    validate_authorization_v1(source, schema)
    capability_fields = ("real_external_call", "create_execution", "publish", "destructive_operation")
    allowed = [field for field in capability_fields if source[field]]
    if len(allowed) > 1:
        raise ContractError("v1 adapter rejects envelopes with multiple allowed capabilities")
    if allowed:
        raise ContractError(
            f"v1 adapter cannot prove structured kind, transport, and scope for allowed string target: {allowed[0]}"
        )
    if source != default_authorization():
        raise ContractError("v1 adapter accepts only the canonical all-denied envelope")
    adapted = default_authorization_v2()
    if adapted["envelope_digest"] == source["envelope_digest"]:
        raise ContractError("v1 adapter must compute a distinct v2 envelope digest")
    return adapted


def make_allowed_authorization_v2(*capability_names: str,
                                  resume_execution_id: str | None = None) -> AuthorizationV2:
    value = default_authorization_v2()
    targets = {
        "external_call": {
            "kind": "service", "id": "service.example", "transport": "remote",
            "scope": {"paths": [], "refs": ["operation.read"]},
        },
        "create_execution": {
            "kind": "execution", "id": "runner.local", "transport": "local",
            "scope": {"paths": ["jobs/build"], "refs": []},
        },
        "publish": {
            "kind": "publication", "id": "registry.example", "transport": "remote",
            "scope": {"paths": [], "refs": ["release/candidate"]},
        },
        "destructive_operation": {
            "kind": "resource", "id": "workspace.cache", "transport": "local",
            "scope": {"paths": ["cache/item"], "refs": []},
        },
    }
    for name in capability_names:
        grant = value["capabilities"][name]
        grant.update({"allowed": True, "target": copy.deepcopy(targets[name])})
        if grant["target"]["transport"] == "remote":
            grant.update({"route": "api", "provider": "example"})
        if name in {"external_call", "create_execution"}:
            grant["max_calls"] = 1
        if name == "create_execution" and resume_execution_id is not None:
            grant.update({"fresh_execution_required": False, "resume_execution_id": resume_execution_id})
    value["controlled_input"] = {"request": "bounded", "sequence": 1}
    value["controlled_input_digest"] = value_digest(value["controlled_input"])
    value["expires_at"] = "2100-01-01T00:00:00Z"
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

    def test_v2_default_deny_and_every_capability_shape(self) -> None:
        denied = default_authorization_v2()
        validate_authorization(denied, self.schema)
        value = make_allowed_authorization_v2(
            "external_call", "create_execution", "publish", "destructive_operation",
        )
        value["capabilities"]["external_call"].update({"max_cost": 25, "cost_unit": "USD-cent"})
        value["envelope_digest"] = object_digest(value, "envelope_digest")
        validate_authorization(value, self.schema)
        self.assertEqual(value["capabilities"]["external_call"]["target"]["kind"], "service")
        self.assertEqual(value["capabilities"]["create_execution"]["target"]["kind"], "execution")
        self.assertEqual(value["capabilities"]["publish"]["target"]["kind"], "publication")
        self.assertEqual(value["capabilities"]["destructive_operation"]["target"]["kind"], "resource")

    def test_v2_fresh_and_exact_resume_semantics(self) -> None:
        fresh = make_allowed_authorization_v2("create_execution")
        validate_authorization(fresh, self.schema)
        validate_execution_request(fresh, self.schema, None)
        with self.assertRaises(ContractError):
            validate_execution_request(fresh, self.schema, "run-unexpected")
        resumed = make_allowed_authorization_v2("create_execution", resume_execution_id="run-exact-123")
        validate_authorization(resumed, self.schema)
        validate_execution_request(resumed, self.schema, "run-exact-123")
        with self.assertRaises(ContractError):
            validate_execution_request(resumed, self.schema, "run-other")
        for field, invalid in (("resume_execution_id", "run-unexpected"),
                               ("fresh_execution_required", False)):
            value = make_allowed_authorization_v2("create_execution")
            value["capabilities"]["create_execution"][field] = invalid
            value["envelope_digest"] = object_digest(value, "envelope_digest")
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_authorization(value, self.schema)

    def test_v2_capabilities_are_independent(self) -> None:
        value = make_allowed_authorization_v2("external_call")
        value["capabilities"]["create_execution"]["max_calls"] = 1
        value["envelope_digest"] = object_digest(value, "envelope_digest")
        with self.assertRaises(ContractError):
            validate_authorization(value, self.schema)
        value = make_allowed_authorization_v2("publish")
        value["capabilities"]["publish"]["target"] = copy.deepcopy(
            make_allowed_authorization_v2("external_call")["capabilities"]["external_call"]["target"]
        )
        value["envelope_digest"] = object_digest(value, "envelope_digest")
        with self.assertRaises(ContractError):
            validate_authorization(value, self.schema)

    def test_v2_negative_field_target_scope_route_budget_and_digest_cases(self) -> None:
        cases: list[tuple[str, Any]] = []

        missing_root = default_authorization_v2()
        del missing_root["expires_at"]
        cases.append(("missing root field", missing_root))
        extra_root = default_authorization_v2()
        extra_root["legacy_target"] = None
        cases.append(("extra root field", extra_root))
        wrong_version = default_authorization_v2()
        wrong_version["schema_version"] = True
        cases.append(("wrong schema version type", wrong_version))
        missing_capability = default_authorization_v2()
        del missing_capability["capabilities"]["publish"]
        cases.append(("missing capability", missing_capability))
        missing_grant_field = default_authorization_v2()
        del missing_grant_field["capabilities"]["publish"]["max_cost"]
        cases.append(("missing grant field", missing_grant_field))
        leaked_field = default_authorization_v2()
        leaked_field["capabilities"]["external_call"]["fresh_execution_required"] = True
        cases.append(("execution field leakage", leaked_field))

        mutations = {
            "allowed wrong type": ("allowed", 1),
            "target wrong type": ("target", "service.example"),
            "wrong target kind": ("target.kind", "execution"),
            "wrong target transport": ("target.transport", "local"),
            "empty target id": ("target.id", ""),
            "missing route": ("route", None),
            "missing provider": ("provider", None),
            "zero calls": ("max_calls", 0),
            "boolean calls": ("max_calls", True),
            "floating calls": ("max_calls", 1.5),
            "negative cost": ("max_cost", -1),
            "floating cost": ("max_cost", 1.5),
            "unit without cost": ("cost_unit", "USD-cent"),
        }
        for label, (path, replacement) in mutations.items():
            value = make_allowed_authorization_v2("external_call")
            if path.startswith("target."):
                value["capabilities"]["external_call"]["target"][path.split(".")[1]] = replacement
            else:
                value["capabilities"]["external_call"][path] = replacement
            if not isinstance(replacement, float):
                value["envelope_digest"] = object_digest(value, "envelope_digest")
            cases.append((label, value))

        for label, paths in (
            ("wildcard scope", ["*"]),
            ("unsorted scope", ["z", "a"]),
            ("duplicate scope", ["a", "a"]),
            ("empty scope entry", [""]),
        ):
            value = make_allowed_authorization_v2("external_call")
            value["capabilities"]["external_call"]["target"]["scope"]["paths"] = paths
            value["envelope_digest"] = object_digest(value, "envelope_digest")
            cases.append((label, value))
        scope_missing = make_allowed_authorization_v2("external_call")
        del scope_missing["capabilities"]["external_call"]["target"]["scope"]["refs"]
        scope_missing["envelope_digest"] = object_digest(scope_missing, "envelope_digest")
        cases.append(("missing scope field", scope_missing))
        scope_wrong_type = make_allowed_authorization_v2("external_call")
        scope_wrong_type["capabilities"]["external_call"]["target"]["scope"]["paths"] = [1]
        scope_wrong_type["envelope_digest"] = object_digest(scope_wrong_type, "envelope_digest")
        cases.append(("wrong scope member type", scope_wrong_type))
        extra_target = make_allowed_authorization_v2("external_call")
        extra_target["capabilities"]["external_call"]["target"]["namespace"] = "unexpected"
        extra_target["envelope_digest"] = object_digest(extra_target, "envelope_digest")
        cases.append(("extra target field", extra_target))

        local_route = make_allowed_authorization_v2("create_execution")
        local_route["capabilities"]["create_execution"].update({"route": "local", "provider": "host"})
        local_route["envelope_digest"] = object_digest(local_route, "envelope_digest")
        cases.append(("local route leakage", local_route))
        publish_calls = make_allowed_authorization_v2("publish")
        publish_calls["capabilities"]["publish"]["max_calls"] = 1
        publish_calls["envelope_digest"] = object_digest(publish_calls, "envelope_digest")
        cases.append(("publish call budget", publish_calls))
        empty_publish_scope = make_allowed_authorization_v2("publish")
        empty_publish_scope["capabilities"]["publish"]["target"]["scope"] = {"paths": [], "refs": []}
        empty_publish_scope["envelope_digest"] = object_digest(empty_publish_scope, "envelope_digest")
        cases.append(("empty publish scope", empty_publish_scope))
        positive_without_unit = make_allowed_authorization_v2("external_call")
        positive_without_unit["capabilities"]["external_call"]["max_cost"] = 1
        positive_without_unit["envelope_digest"] = object_digest(positive_without_unit, "envelope_digest")
        cases.append(("positive cost without unit", positive_without_unit))

        bad_input_digest = make_allowed_authorization_v2("external_call")
        bad_input_digest["controlled_input_digest"] = "sha256:" + "0" * 64
        bad_input_digest["envelope_digest"] = object_digest(bad_input_digest, "envelope_digest")
        cases.append(("controlled input digest mismatch", bad_input_digest))
        missing_input_digest = make_allowed_authorization_v2("external_call")
        missing_input_digest["controlled_input_digest"] = None
        missing_input_digest["envelope_digest"] = object_digest(missing_input_digest, "envelope_digest")
        cases.append(("controlled input digest missing", missing_input_digest))
        bad_envelope_digest = make_allowed_authorization_v2("external_call")
        bad_envelope_digest["envelope_digest"] = "sha256:" + "0" * 64
        cases.append(("envelope digest mismatch", bad_envelope_digest))
        old_digest = make_allowed_authorization_v2("external_call")
        old_digest["envelope_digest"] = default_authorization()["envelope_digest"]
        cases.append(("v1 digest reuse", old_digest))
        float_input = make_allowed_authorization_v2("external_call")
        float_input["controlled_input"] = {"cost": 1.5}
        cases.append(("floating controlled input", float_input))
        malformed_expiry = make_allowed_authorization_v2("external_call")
        malformed_expiry["expires_at"] = "not-a-time"
        malformed_expiry["envelope_digest"] = object_digest(malformed_expiry, "envelope_digest")
        cases.append(("malformed expiry", malformed_expiry))

        for label, value in cases:
            with self.subTest(case=label), self.assertRaises(ContractError):
                validate_authorization(value, self.schema)

    def test_v2_expiry_and_global_default_deny_rules(self) -> None:
        expired = make_allowed_authorization_v2("external_call")
        expired["expires_at"] = "2025-01-01T00:00:00Z"
        expired["envelope_digest"] = object_digest(expired, "envelope_digest")
        with self.assertRaises(ContractError):
            validate_authorization(expired, self.schema, now=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
        validate_authorization(expired, self.schema, enforce_expiry=False)
        at_expiry = make_allowed_authorization_v2("external_call")
        at_expiry["expires_at"] = "2026-01-01T00:00:00Z"
        at_expiry["envelope_digest"] = object_digest(at_expiry, "envelope_digest")
        with self.assertRaises(ContractError):
            validate_authorization(at_expiry, self.schema,
                                   now=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
        missing = make_allowed_authorization_v2("external_call")
        missing["expires_at"] = None
        missing["envelope_digest"] = object_digest(missing, "envelope_digest")
        with self.assertRaises(ContractError):
            validate_authorization(missing, self.schema)
        denied = default_authorization_v2()
        denied["controlled_input"] = {"stale": True}
        denied["controlled_input_digest"] = value_digest(denied["controlled_input"])
        denied["envelope_digest"] = object_digest(denied, "envelope_digest")
        with self.assertRaises(ContractError):
            validate_authorization(denied, self.schema)

    def test_v1_adapter_is_read_only_strict_and_rehashes_v2(self) -> None:
        source = default_authorization()
        before = copy.deepcopy(source)
        adapted = adapt_authorization_v1_to_v2(source, self.schema)
        self.assertEqual(source, before)
        self.assertEqual(adapted, default_authorization_v2())
        self.assertNotEqual(adapted["envelope_digest"], source["envelope_digest"])
        validate_authorization(adapted, self.schema)

        ambiguous = default_authorization()
        ambiguous.update({
            "real_external_call": True, "target": "service.example", "controlled_input": {"request": 1},
            "route": "api", "provider": "example", "max_calls": 1, "expires_at": "2100-01-01T00:00:00Z",
        })
        ambiguous["controlled_input_digest"] = value_digest(ambiguous["controlled_input"])
        ambiguous["envelope_digest"] = object_digest(ambiguous, "envelope_digest")
        with self.assertRaisesRegex(ContractError, "cannot prove structured"):
            adapt_authorization_v1_to_v2(ambiguous, self.schema)

        multi = copy.deepcopy(ambiguous)
        multi["create_execution"] = True
        multi["envelope_digest"] = object_digest(multi, "envelope_digest")
        with self.assertRaisesRegex(ContractError, "multiple allowed"):
            adapt_authorization_v1_to_v2(multi, self.schema)

        noncanonical_deny = default_authorization()
        noncanonical_deny["target"] = "stale"
        noncanonical_deny["envelope_digest"] = object_digest(noncanonical_deny, "envelope_digest")
        with self.assertRaisesRegex(ContractError, "canonical all-denied"):
            adapt_authorization_v1_to_v2(noncanonical_deny, self.schema)

    def test_authorization_schema_python_exact_field_parity(self) -> None:
        self.assertEqual(schema_required(self.schema, "authorization_v2"), {
            "schema_version", "capabilities", "controlled_input", "controlled_input_digest", "expires_at",
            "envelope_digest",
        })
        common = {"allowed", "target", "route", "provider", "max_calls", "max_cost", "cost_unit"}
        self.assertEqual(schema_required(self.schema, "authorization_grant_external_call"), common)
        self.assertEqual(schema_required(self.schema, "authorization_grant_publish"), common)
        self.assertEqual(schema_required(self.schema, "authorization_grant_destructive_operation"), common)
        self.assertEqual(schema_required(self.schema, "authorization_grant_create_execution"),
                         common | {"fresh_execution_required", "resume_execution_id"})
        for definition in (
            "authorization_v1", "authorization_v2", "target_scope", "structured_target", "authorization_target_service",
            "authorization_target_execution", "authorization_target_publication", "authorization_target_resource",
            "authorization_grant_external_call", "authorization_grant_create_execution",
            "authorization_grant_publish", "authorization_grant_destructive_operation",
        ):
            self.assertFalse(self.schema["$defs"][definition]["additionalProperties"])

    def test_public_cli_accepts_v1_and_v2_task_specs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in (1, 2):
                path = root / f"task-v{version}.json"
                spec = make_task_spec_at(path)
                if version == 2:
                    spec["authorization"] = make_allowed_authorization_v2("external_call", "create_execution")
                spec["task_spec_digest"] = object_digest(spec, "task_spec_digest")
                write_json_fixture(path, spec)
                result = run_public_cli("--task-spec", str(path))
                with self.subTest(version=version):
                    self.assertEqual(result.returncode, 0, result.stderr)

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
        v2_card = copy.deepcopy(card)
        v2_card["authorization"] = default_authorization_v2()
        validate_worker_card(v2_card, self.schema)
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

    def test_public_cli_accepts_graph_positive_fixtures(self) -> None:
        fixtures = {
            "multi-wave": {
                "A": {"status": "PUBLISHED", "parallel": ["B"]},
                "B": {"status": "READY", "parallel": ["A"]},
                "C": {"status": "GATED", "dependencies": ["A"]},
            },
            "resolved-blocker": {
                "A": {"status": "INTEGRATED"},
                "B": {"status": "READY", "dependencies": ["A"]},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, nodes in fixtures.items():
                with self.subTest(name=name):
                    root = Path(directory) / name
                    plan, specs = make_graph_bundle(root, nodes)
                    result = run_public_cli("--plan", str(write_graph_bundle(root, plan, specs)))
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_cli_rejects_n01_n17_graph_matrix(self) -> None:
        def entry(plan: dict[str, Any], task_id: str) -> dict[str, Any]:
            return next(item for item in plan["tasks"] if item["task_id"] == task_id)

        def n01(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["B"]["dependencies"]["blocked_by"] = ["MISSING"]

        def n02(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["B"]["dependencies"]["blocked_by"] = ["B"]

        def n03(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["A"]["dependencies"]["blocked_by"] = ["B"]

        def n04(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["C"]["dependencies"]["blocked_by"] = ["A", "B"]

        def n05(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["B"]["dependencies"]["parallel_with"] = []
            entry(plan, "B")["parallel_with"] = []

        def n06(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["B"]["dependencies"]["blocked_by"] = ["A"]
            specs["B"]["dispatch_wave"] = 2
            task = entry(plan, "B")
            task.update({"dispatch_status": "GATED", "dispatch_wave": 2, "blocked_by": ["A"]})
            plan["blocked_tasks"] = ["B"]

        def n07(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["A"]["dependencies"]["parallel_with"] = ["C"]
            specs["C"]["dependencies"]["parallel_with"] = ["A"]
            entry(plan, "A")["parallel_with"] = ["C"]
            entry(plan, "C")["parallel_with"] = ["A"]

        def n08(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["A"]["dependencies"]["parallel_with"] = ["B"]
            specs["B"]["dependencies"]["parallel_with"] = ["A"]
            entry(plan, "A")["parallel_with"] = ["B"]
            entry(plan, "B")["parallel_with"] = ["A"]

        def n09(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["B"]["dispatch_wave"] = 1
            entry(plan, "B")["dispatch_wave"] = 1

        def n10(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            entry(plan, "B").update({"dispatch_status": "READY", "blocked_by": []})
            plan["blocked_tasks"] = []

        def n11(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            entry(plan, "B").update({"dispatch_status": "GATED", "blocked_by": ["A"]})
            plan.update({"blocked_tasks": ["B"], "ready_wave": None})

        def n12(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            entry(plan, "B")["dispatch_status"] = "PUBLISHED"
            plan["blocked_tasks"] = []

        def n13(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            plan["blocked_tasks"] = []

        def n14(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            plan["blocked_tasks"] = ["A"]

        def n15(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            plan["ready_wave"] = 2

        def n16(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            plan["ready_wave"] = 1

        def n17(plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> None:
            specs["A"]["dependencies"]["parallel_with"] = []

        cases = (
            ("N01", {"A": {"status": "READY"}, "B": {"dependencies": ["A"]}}, n01, "unknown tasks"),
            ("N02", {"A": {"status": "READY"}, "B": {"dependencies": ["A"]}}, n02, "reference itself"),
            ("N03", {"A": {"status": "READY"}, "B": {"dependencies": ["A"]}}, n03, "static dependency cycle"),
            ("N04", {"A": {"status": "READY"}, "B": {"dependencies": ["A"]},
                     "C": {"dependencies": ["B"]}}, n04, "redundant transitive dependency"),
            ("N05", {"A": {"parallel": ["B"]}, "B": {"parallel": ["A"]}}, n05, "not symmetric"),
            ("N06", {"A": {"parallel": ["B"]}, "B": {"parallel": ["A"]}}, n06,
             "parallel dependency conflict"),
            ("N07", {"A": {}, "B": {"dependencies": ["A"]}, "C": {"dependencies": ["B"]}}, n07,
             "parallel dependency conflict"),
            ("N08", {"A": {"status": "READY"}, "B": {"status": "READY", "dependencies": ["C"]},
                     "C": {"status": "INTEGRATED"}}, n08, "unequal waves"),
            ("N09", {"A": {}, "B": {"dependencies": ["A"]}}, n09, "dispatch_wave mismatch"),
            ("N10", {"A": {"status": "PUBLISHED"}, "B": {"dependencies": ["A"]}}, n10,
             "status READY requires resolved dependencies"),
            ("N11", {"A": {"status": "INTEGRATED"}, "B": {"status": "READY", "dependencies": ["A"]}},
             n11, "live blocker mismatch"),
            ("N12", {"A": {"status": "READY"}, "B": {"dependencies": ["A"]}}, n12,
             "status PUBLISHED requires resolved dependencies"),
            ("N13", {"A": {"status": "GATED"}}, n13, "blocked_tasks mismatch"),
            ("N14", {"A": {"status": "INTEGRATED"}}, n14, "blocked_tasks mismatch"),
            ("N15", {"A": {"status": "READY"}, "B": {"status": "READY", "dependencies": ["C"]},
                     "C": {"status": "INTEGRATED"}}, n15, "ready_wave mismatch"),
            ("N16", {"A": {"status": "INTEGRATED"}}, n16, "ready_wave mismatch"),
            ("N17", {"A": {"parallel": ["B"]}, "B": {"parallel": ["A"]}}, n17,
             "Dispatch/Task Spec parallel_with mismatch"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for diagnostic_id, nodes, mutate, expected in cases:
                with self.subTest(diagnostic_id=diagnostic_id):
                    root = Path(directory) / diagnostic_id
                    plan, specs = make_graph_bundle(root, nodes)
                    mutate(plan, specs)
                    result = run_public_cli("--plan", str(write_graph_bundle(root, plan, specs)))
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn(expected, result.stderr)

    def test_public_cli_rejects_parallel_ownership_and_cancelled_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlap_root = root / "overlap"
            overlap_nodes = {
                "A": {"parallel": ["B"], "allowed_paths": ["src/shared"]},
                "B": {"parallel": ["A"], "allowed_paths": ["src/shared/child"]},
            }
            plan, specs = make_graph_bundle(overlap_root, overlap_nodes)
            overlap = run_public_cli("--plan", str(write_graph_bundle(overlap_root, plan, specs)))
            self.assertEqual(overlap.returncode, 1)
            self.assertIn("parallel semantic ownership conflict", overlap.stderr)

            cancelled_root = root / "cancelled"
            plan, specs = make_graph_bundle(cancelled_root, {
                "A": {"status": "CANCELLED"},
                "B": {"dependencies": ["A"]},
            })
            downstream = next(item for item in plan["tasks"] if item["task_id"] == "B")
            downstream.update({"dispatch_status": "READY", "blocked_by": []})
            plan.update({"blocked_tasks": [], "ready_wave": 2})
            cancelled = run_public_cli("--plan", str(write_graph_bundle(cancelled_root, plan, specs)))
            self.assertEqual(cancelled.returncode, 1)
            self.assertIn("status READY requires resolved dependencies", cancelled.stderr)

    def test_model_routing_policy_fence_and_exact_profiles(self) -> None:
        self.assertEqual(MODEL_OWNER_DEFAULTS, {
            "master": {"model": "gpt-5.6-sol", "reasoning_effort": "high", "service_tier": "default",
                       "selection_reason": "owner-default:master"},
            "ordinary_worker": {"model": "gpt-5.6-luna", "reasoning_effort": "max",
                                "service_tier": "priority", "selection_reason": "owner-default:ordinary-worker"},
            "complex_worker": {"model": "gpt-5.6-sol", "reasoning_effort": "high",
                               "service_tier": "default", "selection_reason": "owner-default:complex-worker"},
        })
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_root = root / "legacy"
            legacy_plan, legacy_specs = make_graph_bundle(legacy_root, {"A": {}}, persist_model_policy=False)
            legacy = run_public_cli("--plan", str(write_graph_bundle(legacy_root, legacy_plan, legacy_specs)))
            self.assertEqual(legacy.returncode, 0, legacy.stderr)

            grandfather_root = root / "grandfather"
            grandfather_plan, grandfather_specs = make_graph_bundle(
                grandfather_root, {"A": {"status": "INTEGRATED"}}, persist_model_policy=False,
            )
            grandfather_plan["plan_revision"] = 2
            grandfather_plan["model_policy"] = make_model_policy(enforced_from_plan_revision=2)
            grandfather_plan["tasks"][0]["revision_decision"] = "GRANDFATHER"
            grandfather = run_public_cli(
                "--plan", str(write_graph_bundle(grandfather_root, grandfather_plan, grandfather_specs)),
            )
            self.assertEqual(grandfather.returncode, 0, grandfather.stderr)

            fenced_root = root / "fenced"
            fenced_plan, fenced_specs = make_graph_bundle(fenced_root, {"A": {"model_owner": "complex_worker"}})
            fenced = run_public_cli("--plan", str(write_graph_bundle(fenced_root, fenced_plan, fenced_specs)))
            self.assertEqual(fenced.returncode, 0, fenced.stderr)

            missing_root = root / "missing"
            missing_plan, missing_specs = make_graph_bundle(missing_root, {"A": {}})
            del missing_specs["A"]["model_profile"]
            missing = run_public_cli("--plan", str(write_graph_bundle(missing_root, missing_plan, missing_specs)))
            self.assertEqual(missing.returncode, 1)
            self.assertIn("requires Task Spec and Dispatch model_profile", missing.stderr)

            mismatch_root = root / "mismatch"
            mismatch_plan, mismatch_specs = make_graph_bundle(mismatch_root, {"A": {}})
            mismatch_specs["A"]["model_profile"] = make_model_profile("complex_worker")
            mismatch = run_public_cli("--plan", str(write_graph_bundle(mismatch_root, mismatch_plan, mismatch_specs)))
            self.assertEqual(mismatch.returncode, 1)
            self.assertIn("Dispatch/Task Spec model_profile mismatch", mismatch.stderr)

            unsupported_root = root / "unsupported"
            unsupported_plan, unsupported_specs = make_graph_bundle(unsupported_root, {"A": {}})
            unsupported_specs["A"]["model_profile"]["service_tier"] = "default"
            unsupported_plan["tasks"][0]["model_profile"]["service_tier"] = "default"
            unsupported = run_public_cli(
                "--plan", str(write_graph_bundle(unsupported_root, unsupported_plan, unsupported_specs)),
            )
            self.assertEqual(unsupported.returncode, 1)
            self.assertIn("unsupported model/reasoning/service-tier combination", unsupported.stderr)

    def test_model_profile_is_not_authorization_and_changes_require_revision(self) -> None:
        profile = make_model_profile("ordinary_worker")
        profile["route"] = "external-api"
        with self.assertRaisesRegex(ContractError, "field mismatch"):
            validate_model_profile(profile, self.schema)

        authorization = default_authorization()
        authorization["service_tier"] = "priority"
        authorization["envelope_digest"] = object_digest(authorization, "envelope_digest")
        with self.assertRaisesRegex(ContractError, "field mismatch"):
            validate_authorization(authorization, self.schema)

        task = make_task_spec()
        task["model_profile"] = make_model_profile("ordinary_worker")
        task["task_spec_digest"] = object_digest(task, "task_spec_digest")
        self.assertFalse(task["authorization"]["real_external_call"])
        self.assertFalse(task["authorization"]["create_execution"])
        self.assertFalse(task["authorization"]["publish"])
        self.assertFalse(task["authorization"]["destructive_operation"])

        changed = copy.deepcopy(task)
        changed["model_profile"] = make_model_profile("complex_worker")
        with self.assertRaisesRegex(ContractError, "higher task revision"):
            classify_task_change(task, changed)
        changed["task_spec_revision"] = 2
        changed["task_spec_digest"] = object_digest(changed, "task_spec_digest")
        self.assertEqual(classify_task_change(task, changed), "REVISE")


class CandidateEvidenceScenarios(unittest.TestCase):
    """Executable N01-N21 matrix plus positive and migration fixtures."""

    def setUp(self) -> None:
        self.schema = ACTIVE_SCHEMA

    def assert_rejected(self, candidate: dict[str, Any]) -> None:
        with self.assertRaises(ContractError):
            validate_candidate_evidence(candidate, self.schema)

    def test_positive_current_candidate(self) -> None:
        candidate = make_candidate_v2()
        validate_candidate_evidence(candidate, self.schema)
        self.assertEqual(candidate["status"], "PASSED")

    def test_n01_duplicate_and_position_derived_gate_identity(self) -> None:
        duplicate = make_candidate_v2()
        duplicate["gates"].append(copy.deepcopy(duplicate["gates"][0]))
        self.assert_rejected(duplicate)
        positional = make_candidate_v2()
        positional["gate_registry"][0]["gate_id"] = "gate-1"
        positional["gates"][0]["gate_id"] = "gate-1"
        self.assert_rejected(positional)

    def test_n02_unknown_gate_and_check_identity(self) -> None:
        unknown_gate = make_candidate_v2()
        unknown_gate["gates"][0]["gate_id"] = "unknown-gate"
        self.assert_rejected(unknown_gate)
        unknown_check = make_candidate_v2()
        unknown_check["gates"][0]["checks"][0]["check_id"] = "unknown-check"
        self.assert_rejected(unknown_check)

    def test_n03_required_gate_missing(self) -> None:
        candidate = make_candidate_v2()
        candidate["gates"].pop()
        self.assert_rejected(candidate)

    def test_n04_aggregate_pass_cannot_hide_stale_gate(self) -> None:
        candidate = make_candidate_v2(stale_gates={"targeted-tests"})
        candidate["status"] = "PASSED"
        self.assert_rejected(candidate)

    def test_n05_gate_input_digest_mismatch(self) -> None:
        candidate = make_candidate_v2()
        candidate["gates"][0]["input_digest"] = "sha256:" + "0" * 64
        self.assert_rejected(candidate)

    def test_n06_changed_check_input_cannot_reuse_evidence(self) -> None:
        candidate = make_candidate_v2()
        gate = candidate["gates"][1]
        gate["input_sources"][0]["value_digest"] = value_digest({"commands": ["changed"]})
        refresh_candidate_inputs(candidate, refresh_evidence=False)
        self.assert_rejected(candidate)

    def test_n07_gate_evidence_digest_mismatch(self) -> None:
        candidate = make_candidate_v2()
        candidate["gates"][0]["evidence_digest"] = "sha256:" + "0" * 64
        self.assert_rejected(candidate)

    def test_n08_result_provenance_and_artifact_contradiction(self) -> None:
        candidate = make_candidate_v2()
        candidate["gates"][0]["checks"][0]["exit_code"] = 1
        candidate["gates"][0]["checks"][0]["evidence_digest"] = candidate_check_evidence_digest(
            candidate["gates"][0], candidate["gates"][0]["checks"][0],
        )
        self.assert_rejected(candidate)

    def test_n09_head_change_rejects_old_binding(self) -> None:
        candidate = make_candidate_v2()
        candidate["release_head_sha"] = "b" * 40
        self.assert_rejected(candidate)

    def test_n10_selective_invalidation_preserves_unaffected_gate(self) -> None:
        previous = make_candidate_v2()
        candidate = make_candidate_v2(plan_revision=2, stale_gates={"targeted-tests"})
        validate_candidate_evidence(candidate, self.schema)
        scope, affected = evaluate_candidate_invalidation(previous, candidate, self.schema)
        statuses = {gate["gate_id"]: gate["status"] for gate in candidate["gates"]}
        self.assertEqual(statuses, {"base-relative-audit": "PASSED", "targeted-tests": "STALE"})
        self.assertEqual((scope, affected), ("AFFECTED", ["targeted-tests"]))
        self.assertEqual(candidate["status"], "STALE")

    def test_n11_missing_mapping_uses_whole_candidate_fallback(self) -> None:
        candidate = make_whole_candidate_stale("MAPPING_AMBIGUOUS")
        validate_candidate_evidence(candidate, self.schema)
        self.assertTrue(all(gate["status"] == "STALE" for gate in candidate["gates"]))

    def test_n12a_status_only_plan_write_does_not_invalidate(self) -> None:
        previous = make_candidate_v2()
        current = copy.deepcopy(previous)
        current["plan_revision"] = 2
        current["plan_digest"] = value_digest({"status_only_write": 2})
        validate_candidate_evidence(current, self.schema)
        validate_candidate_transition(previous, current)
        self.assertEqual(evaluate_candidate_invalidation(previous, current, self.schema), ("NONE", []))
        self.assertEqual(current["gate_input_digest"], previous["gate_input_digest"])

    def test_n12b_semantic_source_change_is_selective(self) -> None:
        current = make_candidate_v2(plan_revision=2, stale_gates={"targeted-tests"})
        validate_candidate_evidence(current, self.schema)
        self.assertEqual(current["gates"][0]["status"], "PASSED")
        self.assertEqual(current["gates"][1]["status"], "STALE")

    def test_n12_unmapped_semantic_change_stales_every_gate(self) -> None:
        candidate = make_whole_candidate_stale("MAPPING_AMBIGUOUS")
        validate_candidate_evidence(candidate, self.schema)

    def test_n13_required_set_change_is_incomplete_until_revalidated(self) -> None:
        candidate = make_whole_candidate_stale("REGISTRY_AMBIGUOUS")
        validate_candidate_evidence(candidate, self.schema)
        self.assertEqual(candidate["status"], "STALE")

    def test_n14_legacy_evidence_migrates_to_stale_without_identity_synthesis(self) -> None:
        legacy = make_candidate("PASSED", "a" * 40, "PASS")
        migrated = migrate_candidate_evidence(
            legacy, self.schema, release_task_id="release-1", plan_revision=1,
            plan_digest=value_digest({"plan": 1}),
        )
        validate_candidate_evidence(migrated, self.schema)
        self.assertEqual(migrated["status"], "STALE")
        self.assertEqual(migrated["gates"], [])
        self.assertEqual(migrated["legacy"]["original"], legacy)

    def test_n15_legacy_none_remains_none(self) -> None:
        legacy = {"release_head_sha": None, "gate_input_digest": None, "status": "NONE", "checks": []}
        migrated = migrate_candidate_evidence(legacy, self.schema)
        validate_candidate_evidence(migrated, self.schema)
        self.assertEqual(migrated["status"], "NONE")

    def test_current_master_fences_legacy_passed_and_failed_but_preserves_read_compatibility(self) -> None:
        for status, result in (("PASSED", "PASS"), ("FAILED", "FAIL")):
            with self.subTest(status=status):
                legacy = make_candidate(status, "a" * 40, result)
                validate_candidate_evidence(legacy, self.schema)
                master = make_active_master_card()
                master["candidate_evidence"] = legacy
                with self.assertRaisesRegex(ContractError, "migrate it to v2 STALE"):
                    validate_master_card(master, self.schema)
                validate_master_card(master, self.schema, historical=True)

        stale_master = make_active_master_card()
        stale_master["candidate_evidence"] = make_candidate("STALE", "a" * 40, "PASS")
        validate_master_card(stale_master, self.schema)

    def test_legacy_comparison_is_conservative_except_for_empty_none(self) -> None:
        legacy = make_candidate("PASSED", "a" * 40, "PASS")
        self.assertEqual(evaluate_candidate_invalidation(legacy, legacy, self.schema), ("ALL", []))
        empty = {"release_head_sha": None, "gate_input_digest": None, "status": "NONE", "checks": []}
        self.assertEqual(evaluate_candidate_invalidation(empty, empty, self.schema), ("NONE", []))

    def test_n16_explicit_optional_failure_does_not_fail_candidate(self) -> None:
        candidate = make_candidate_v2(optional_targeted=True, failed_gates={"targeted-tests"})
        validate_candidate_evidence(candidate, self.schema)
        self.assertEqual(candidate["status"], "PASSED")

    def test_n17_unknown_requiredness_is_rejected(self) -> None:
        candidate = make_candidate_v2()
        candidate["gate_registry"][0]["required"] = None
        candidate["gates"][0]["required"] = None
        self.assert_rejected(candidate)

    def test_n18_secret_or_unbounded_output_is_rejected(self) -> None:
        secret = make_candidate_v2()
        secret["gates"][0]["input_sources"][0]["locator"] = "https://user:password@example.invalid/data"
        self.assert_rejected(secret)
        unbounded = make_candidate_v2()
        unbounded["gates"][0]["checks"][0]["command"] = "x" * 1025
        self.assert_rejected(unbounded)

    def test_n19_mixed_plan_fence_is_rejected_by_master_card(self) -> None:
        master = make_active_master_card()
        master["candidate_evidence"] = make_candidate_v2(plan_revision=2)
        with self.assertRaises(ContractError):
            validate_master_card(master, self.schema)

    def test_n20_stale_precedes_valid_failure(self) -> None:
        candidate = make_candidate_v2(
            stale_gates={"base-relative-audit"}, failed_gates={"targeted-tests"},
        )
        validate_candidate_evidence(candidate, self.schema)
        self.assertEqual(candidate["status"], "STALE")

    def test_n21_tracked_validator_change_means_new_head_and_all_stale(self) -> None:
        previous = make_candidate_v2(head="a" * 40)
        current = make_whole_candidate_stale("HEAD_CHANGED")
        current["release_head_sha"] = "b" * 40
        validate_candidate_evidence(current, self.schema)
        validate_candidate_transition(previous, current)
        self.assertEqual(evaluate_candidate_invalidation(previous, current, self.schema), (
            "ALL", ["base-relative-audit", "targeted-tests"],
        ))
        self.assertTrue(all(gate["status"] == "STALE" for gate in current["gates"]))

    def test_migration_is_idempotent(self) -> None:
        legacy = make_candidate("FAILED", "a" * 40, "FAIL")
        once = migrate_candidate_evidence(legacy, self.schema, release_task_id="release-1", plan_revision=1)
        twice = migrate_candidate_evidence(once, self.schema, release_task_id="ignored", plan_revision=99)
        self.assertEqual(once, twice)

    def test_public_cli_candidate_fixtures_and_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid_path = root / "candidate-v2.json"
            write_json_fixture(valid_path, make_candidate_v2())
            valid = run_public_cli("--candidate-evidence-json", str(valid_path))
            self.assertEqual(valid.returncode, 0, valid.stderr)

            selective_path = root / "candidate-selective.json"
            write_json_fixture(selective_path, make_candidate_v2(
                plan_revision=2, stale_gates={"targeted-tests"},
            ))
            compared = run_public_cli(
                "--previous-candidate-evidence-json", str(valid_path),
                "--candidate-evidence-json", str(selective_path),
            )
            self.assertEqual(compared.returncode, 0, compared.stderr)
            self.assertIn("candidate invalidation: AFFECTED gates=targeted-tests", compared.stdout)

            invalid = make_candidate_v2()
            invalid["gate_input_digest"] = "sha256:" + "0" * 64
            invalid_path = root / "candidate-invalid.json"
            write_json_fixture(invalid_path, invalid)
            rejected = run_public_cli("--candidate-evidence-json", str(invalid_path))
            self.assertEqual(rejected.returncode, 1, rejected.stdout)

            legacy_path = root / "candidate-v1.json"
            write_json_fixture(legacy_path, make_candidate("PASSED", "a" * 40, "PASS"))
            legacy_comparison = run_public_cli(
                "--previous-candidate-evidence-json", str(legacy_path),
                "--candidate-evidence-json", str(legacy_path),
            )
            self.assertEqual(legacy_comparison.returncode, 0, legacy_comparison.stderr)
            self.assertIn("candidate invalidation: ALL gates=none", legacy_comparison.stdout)

            legacy_none_path = root / "candidate-v1-none.json"
            write_json_fixture(legacy_none_path, {
                "release_head_sha": None, "gate_input_digest": None, "status": "NONE", "checks": [],
            })
            none_comparison = run_public_cli(
                "--previous-candidate-evidence-json", str(legacy_none_path),
                "--candidate-evidence-json", str(legacy_none_path),
            )
            self.assertEqual(none_comparison.returncode, 0, none_comparison.stderr)
            self.assertIn("candidate invalidation: NONE gates=none", none_comparison.stdout)

            migrated = run_public_cli(
                "--candidate-evidence-json", str(legacy_path), "--migrate-candidate-evidence",
                "--release-task-id", "release-1", "--candidate-plan-revision", "1",
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            projection = json.loads(migrated.stdout.splitlines()[0])
            self.assertEqual(projection["status"], "STALE")
            self.assertEqual(projection["legacy"]["original"]["status"], "PASSED")

            previous_master = make_active_master_card()
            previous_master["candidate_evidence"] = make_candidate("PASSED", "a" * 40, "PASS")
            current_master = advance_record(previous_master)
            current_master["candidate_evidence"] = migrate_candidate_evidence(
                previous_master["candidate_evidence"], self.schema,
                release_task_id=previous_master["release_task_id"],
                plan_revision=previous_master["plan_revision"],
                plan_digest=previous_master["dispatch_plan_digest"],
            )
            previous_master_path = root / "master-v1-passed.json"
            current_master_path = root / "master-v2-stale.json"
            write_json_fixture(previous_master_path, previous_master)
            write_json_fixture(current_master_path, current_master)
            current_rejected = run_public_cli("--master-card-json", str(previous_master_path))
            self.assertEqual(current_rejected.returncode, 1, current_rejected.stdout)
            failed_master = make_active_master_card()
            failed_master["candidate_evidence"] = make_candidate("FAILED", "a" * 40, "FAIL")
            failed_master_path = root / "master-v1-failed.json"
            write_json_fixture(failed_master_path, failed_master)
            failed_rejected = run_public_cli("--master-card-json", str(failed_master_path))
            self.assertEqual(failed_rejected.returncode, 1, failed_rejected.stdout)
            historical_migration = run_public_cli(
                "--previous-master-card", str(previous_master_path),
                "--master-card-json", str(current_master_path),
            )
            self.assertEqual(historical_migration.returncode, 0, historical_migration.stderr)
            self.assertIn("historical master-card: PASS", historical_migration.stdout)


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

    def test_preserved_prior_rework_handoff_matches_later_grandfather_entry(self) -> None:
        spec = make_revised_task_spec()
        plan = make_plan_for_spec(spec, "PUBLISHED", plan_revision=3, revision_decision="GRANDFATHER")
        master = make_active_master_card(plan)
        master["worker_handoffs"] = [make_prior_rework_handoff(spec)]
        validate_plan_master_consistency(plan, master, Path("/state/dispatch-plan.json"), {"A": spec})

    def test_incompatible_grandfather_rework_history_remains_rejected(self) -> None:
        spec = make_revised_task_spec()
        plan = make_plan_for_spec(spec, "PUBLISHED", plan_revision=3, revision_decision="GRANDFATHER")
        mutations = {
            "nonterminal": {"state": "RECEIVED"},
            "integrated": {"state": "INTEGRATED", "integrated_as_sha": "c" * 40},
            "equal-revision": {"task_spec_revision": 2},
            "future-revision": {"task_spec_revision": 3},
            "same-digest": {"task_spec_digest": spec["task_spec_digest"]},
            "changed-authority": {"authorization_envelope_digest": "sha256:" + "f" * 64},
            "changed-source": {"source_thread_id": "other-master"},
            "changed-role": {"role": "other-role"},
            "changed-baseline": {"frozen_baseline_sha": "c" * 40},
            "lost-revise-fence": {"plan_revision": spec["plan_revision"]},
        }
        for label, changes in mutations.items():
            with self.subTest(label=label):
                handoff = make_prior_rework_handoff(spec)
                handoff.update(changes)
                master = make_active_master_card(plan)
                master["worker_handoffs"] = [handoff]
                self.assert_historical("H27", lambda: validate_plan_master_consistency(
                    plan, master, Path("/state/dispatch-plan.json"), {"A": spec}))

        invalid_plan = copy.deepcopy(plan)
        invalid_plan["tasks"][0]["task_spec_plan_revision"] = invalid_plan["plan_revision"]
        master = make_active_master_card(invalid_plan)
        master["worker_handoffs"] = [make_prior_rework_handoff(spec)]
        self.assert_historical("H27", lambda: validate_plan_master_consistency(
            invalid_plan, master, Path("/state/dispatch-plan.json"), {"A": spec}))

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

    def test_public_cli_current_only_grandfather_history_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = make_revised_task_spec(root / "task-r2.json")
            write_json_fixture(Path(spec["task_spec_path"]), spec)
            plan = make_plan_for_spec(spec, "PUBLISHED", plan_revision=3, revision_decision="GRANDFATHER")
            plan_path = root / "dispatch-plan.json"
            write_json_fixture(plan_path, plan)
            master = make_active_master_card(plan, str(plan_path))
            master["worker_handoffs"] = [make_prior_rework_handoff(spec)]
            master_path = root / "master-card.json"
            write_json_fixture(master_path, master)

            result = run_public_cli("--plan", str(plan_path), "--master-card-json", str(master_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "contract validation: PASS\n")

            mismatched_master = copy.deepcopy(master)
            mismatched_master["dispatch_plan_digest"] = "sha256:" + "f" * 64
            mismatched_master_path = root / "mismatched-master-card.json"
            write_json_fixture(mismatched_master_path, mismatched_master)
            negative = run_public_cli(
                "--plan", str(plan_path), "--master-card-json", str(mismatched_master_path),
            )
            self.assertEqual(negative.returncode, 1)
            self.assertIn("contract validation failed: [H27] Plan/Master release lock mismatch", negative.stderr)


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
        "ready_wave": min(
            (task["dispatch_wave"] for task in tasks
             if task["dispatch_status"] in {"READY", "PUBLISHED"}),
            default=None,
        ),
        "blocked_tasks": sorted(
            task["task_id"] for task in tasks
            if task["dispatch_status"] in {"GATED", "BLOCKED"}
        ),
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


def make_model_profile(owner: str) -> dict[str, Any]:
    return copy.deepcopy(MODEL_OWNER_DEFAULTS[owner])


def make_model_policy(enforced_from_plan_revision: int = 1) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "enforced_from_plan_revision": enforced_from_plan_revision,
        "owner_defaults": copy.deepcopy(MODEL_OWNER_DEFAULTS),
    }


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


def make_candidate_registry_gate(gate_id: str, check_id: str, source_ids: list[str], *,
                                 required: bool = True) -> dict[str, Any]:
    command_spec = {
        "argv": ["python3", "scripts/validate_contracts.py"] if check_id == "contract-validator"
        else ["git", "diff", "--check"],
        "success_exit_codes": [0],
        "timeout_seconds": 300,
    }
    check_runner = {"network": "denied", "runner": "local", "working_tree": "integrated-master"}
    gate_definition = {"predicate": "all-checks-pass", "required": required}
    gate_runner = {"atomic_result": True, "network": "denied"}
    return {
        "gate_id": gate_id,
        "gate_revision": 1,
        "required": required,
        "gate_definition": gate_definition,
        "gate_definition_digest": value_digest(gate_definition),
        "runner_policy": gate_runner,
        "runner_policy_digest": value_digest(gate_runner),
        "checks": [{
            "check_id": check_id,
            "check_revision": 1,
            "command_spec": command_spec,
            "command_spec_digest": value_digest(command_spec),
            "runner_policy": check_runner,
            "runner_policy_digest": value_digest(check_runner),
            "input_source_ids": sorted_utf8(source_ids),
        }],
    }


def make_candidate_source(source_id: str, kind: str, locator: str, revision: str | None,
                          semantic_value: Any) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "kind": kind,
        "locator": locator,
        "revision": revision,
        "value_digest": value_digest(semantic_value),
    }


def make_candidate_v2(*, head: str = "a" * 40, plan_revision: int = 1,
                      plan_digest: str | None = None, stale_gates: set[str] | None = None,
                      failed_gates: set[str] | None = None, optional_targeted: bool = False) -> dict[str, Any]:
    stale_gates = stale_gates or set()
    failed_gates = failed_gates or set()
    plan_digest = plan_digest or value_digest({"semantic_plan": 1})
    registry = [
        make_candidate_registry_gate(
            "base-relative-audit", "diff-integrity", ["base-tree", "integrated-tree"], required=True,
        ),
        make_candidate_registry_gate(
            "targeted-tests", "contract-validator", ["acceptance-policy", "integrated-tree"],
            required=not optional_targeted,
        ),
    ]
    gates: list[dict[str, Any]] = []
    source_sets = {
        "base-relative-audit": [
            make_candidate_source("base-tree", "git-commit", "task-frozen-baseline", "b" * 40,
                                  {"commit": "b" * 40}),
            make_candidate_source("integrated-tree", "git-commit", "master-integrated-tree", head,
                                  {"commit": head}),
        ],
        "targeted-tests": [
            make_candidate_source("acceptance-policy", "acceptance",
                                  "dispatch-plan#task.targeted-tests.acceptance",
                                  f"plan-revision-{plan_revision}", {"commands": ["contracts"]}),
            make_candidate_source("integrated-tree", "git-commit", "master-integrated-tree", head,
                                  {"commit": head}),
        ],
    }
    for registry_gate in registry:
        gate_id = registry_gate["gate_id"]
        gate = {
            "gate_id": gate_id,
            "gate_revision": registry_gate["gate_revision"],
            "required": registry_gate["required"],
            "status": "STALE" if gate_id in stale_gates else "PASSED",
            "input_digest": None,
            "evidence_digest": None,
            "input_sources": source_sets[gate_id],
            "checks": [],
            "invalidation_reason": "INPUT_SOURCE_CHANGED" if gate_id in stale_gates else None,
        }
        registry_check = registry_gate["checks"][0]
        check_input = candidate_check_input_digest(gate, registry_gate, registry_check, registry_check)
        if gate_id not in stale_gates:
            failed = gate_id in failed_gates
            check = {
                "check_id": registry_check["check_id"],
                "check_revision": registry_check["check_revision"],
                "command": " ".join(registry_check["command_spec"]["argv"]),
                "input_source_ids": registry_check["input_source_ids"],
                "result": "FAIL" if failed else "PASS",
                "input_digest": check_input,
                "evidence_digest": None,
                "execution_ref": f"local-master-{gate_id}-001",
                "exit_code": 1 if failed else 0,
                "stdout_digest": value_digest({"bounded_output": gate_id}),
                "stderr_digest": value_digest({"bounded_error": failed}),
                "observed_artifacts": [],
                "runner_digest": value_digest({"runner": "local", "version": 1}),
                "observed_at": "2026-08-30T00:00:00Z",
            }
            check["evidence_digest"] = candidate_check_evidence_digest(gate, check)
            gate["checks"] = [check]
            gate["input_digest"] = candidate_gate_input_digest(
                gate, registry_gate, {(check["check_id"], check["check_revision"]): check_input},
            )
            gate["status"] = "FAILED" if failed else "PASSED"
            gate["evidence_digest"] = candidate_gate_evidence_digest(gate)
        gates.append(gate)
    candidate = {
        "schema_version": 2,
        "release_task_id": "release-1",
        "release_head_sha": head,
        "plan_revision": plan_revision,
        "plan_digest": plan_digest,
        "gate_registry_digest": value_digest({"schema_version": 1, "gates": registry}),
        "gate_registry": registry,
        "gate_input_digest": None,
        "status": aggregate_candidate_status(gates),
        "legacy": None,
        "gates": gates,
    }
    registry_by_id = {(gate["gate_id"], gate["gate_revision"]): gate for gate in registry}
    gate_inputs: dict[tuple[str, int], str] = {}
    for gate in gates:
        registry_gate = registry_by_id[(gate["gate_id"], gate["gate_revision"])]
        check_inputs = {}
        for registry_check in registry_gate["checks"]:
            key = (registry_check["check_id"], registry_check["check_revision"])
            check_inputs[key] = candidate_check_input_digest(gate, registry_gate, registry_check, registry_check)
        gate_inputs[(gate["gate_id"], gate["gate_revision"])] = candidate_gate_input_digest(
            gate, registry_gate, check_inputs,
        )
    candidate["gate_input_digest"] = candidate_gate_input_summary(candidate, gate_inputs)
    return candidate


def make_whole_candidate_stale(reason: str = "MAPPING_AMBIGUOUS") -> dict[str, Any]:
    candidate = make_candidate_v2()
    candidate.update({"gate_registry": [], "gate_registry_digest": None, "gate_input_digest": None, "status": "STALE"})
    for gate in candidate["gates"]:
        gate.update({
            "status": "STALE", "input_digest": None, "evidence_digest": None, "checks": [],
            "invalidation_reason": reason,
        })
    return candidate


def refresh_candidate_inputs(candidate: dict[str, Any], *, refresh_evidence: bool = False) -> None:
    registry = {
        (gate["gate_id"], gate["gate_revision"]): gate for gate in candidate["gate_registry"]
    }
    candidate["gate_registry_digest"] = value_digest({
        "schema_version": 1, "gates": candidate["gate_registry"],
    })
    gate_inputs: dict[tuple[str, int], str] = {}
    for gate in candidate["gates"]:
        identity = (gate["gate_id"], gate["gate_revision"])
        registry_gate = registry[identity]
        check_inputs: dict[tuple[str, int], str] = {}
        evidence_checks = {
            (check["check_id"], check["check_revision"]): check for check in gate["checks"]
        }
        for registry_check in registry_gate["checks"]:
            check_identity = (registry_check["check_id"], registry_check["check_revision"])
            check_input = candidate_check_input_digest(gate, registry_gate, registry_check, registry_check)
            check_inputs[check_identity] = check_input
            evidence_check = evidence_checks.get(check_identity)
            if evidence_check is not None:
                evidence_check["input_digest"] = check_input
                if refresh_evidence:
                    evidence_check["evidence_digest"] = candidate_check_evidence_digest(gate, evidence_check)
        gate_input = candidate_gate_input_digest(gate, registry_gate, check_inputs)
        gate_inputs[identity] = gate_input
        if gate["status"] in {"PASSED", "FAILED"}:
            gate["input_digest"] = gate_input
            if refresh_evidence:
                gate["evidence_digest"] = candidate_gate_evidence_digest(gate)
    candidate["gate_input_digest"] = candidate_gate_input_summary(candidate, gate_inputs)


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


def make_graph_bundle(root: Path, nodes: dict[str, dict[str, Any]], *,
                      persist_model_policy: bool = True) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    specs: dict[str, dict[str, Any]] = {}
    waves: dict[str, int] = {}

    def wave(task_id: str, visiting: set[str] | None = None) -> int:
        if task_id in waves:
            return waves[task_id]
        path = set() if visiting is None else visiting
        if task_id in path:
            raise ValueError("fixture dependencies must be acyclic")
        path.add(task_id)
        dependencies = nodes[task_id].get("dependencies", [])
        result = 1 if not dependencies else 1 + max(wave(item, path.copy()) for item in dependencies)
        waves[task_id] = result
        return result

    for task_id in nodes:
        wave(task_id)

    for index, task_id in enumerate(sorted(nodes), start=1):
        node = nodes[task_id]
        spec = make_task_spec()
        spec_path = root / "tasks" / f"{task_id}.json"
        spec.update({
            "task_id": task_id,
            "task_spec_path": str(spec_path),
            "dispatch_wave": node.get("wave", waves[task_id]),
            "owner_role": node.get("owner_role", "ordinary-worker"),
            "worktree": node.get("worktree", str(root / "worktrees" / task_id)),
            "branch": f"task/{task_id}",
            "expected_head": f"{index:040x}",
            "objective": f"implement {task_id}",
            "allowed_paths": node.get("allowed_paths", [f"src/{task_id}"]),
            "forbidden_paths": [],
            "outputs": node.get("allowed_paths", [f"src/{task_id}"]),
            "dependencies": {
                "upstream_commits": [],
                "parallel_with": list(node.get("parallel", [])),
                "blocked_by": list(node.get("dependencies", [])),
            },
            "acceptance": [f"test {task_id}"],
            "commit_message": f"feat: implement {task_id}",
        })
        if persist_model_policy:
            spec["model_profile"] = make_model_profile(node.get("model_owner", "ordinary_worker"))
        spec["task_spec_digest"] = object_digest(spec, "task_spec_digest")
        specs[task_id] = spec

    entries: list[dict[str, Any]] = []
    for task_id in sorted(nodes):
        node = nodes[task_id]
        spec = specs[task_id]
        status = node.get("status", "READY" if not node.get("dependencies") else "GATED")
        unresolved = [
            dependency for dependency in node.get("dependencies", [])
            if nodes[dependency].get("status", "READY" if not nodes[dependency].get("dependencies") else "GATED")
            != "INTEGRATED"
        ]
        live = node.get("live", unresolved if status in {"GATED", "BLOCKED"} else [])
        entry = make_dispatch_task(task_id)
        entry.update({
            "task_spec_digest": spec["task_spec_digest"],
            "task_spec_path": spec["task_spec_path"],
            "owner_role": spec["owner_role"],
            "worktree": spec["worktree"],
            "branch": spec["branch"],
            "expected_head": spec["expected_head"],
            "acceptance_digest": value_digest(spec["acceptance"]),
            "authorization_envelope_digest": spec["authorization"]["envelope_digest"],
            "dispatch_status": status,
            "dispatch_wave": spec["dispatch_wave"],
            "blocked_by": list(live),
            "parallel_with": list(node.get("parallel", [])),
        })
        if persist_model_policy:
            entry["model_profile"] = copy.deepcopy(spec["model_profile"])
        entries.append(entry)

    plan = make_plan(entries)
    plan.update({
        "state_root": str(root),
        "task_specs_root": str(root / "tasks"),
    })
    if persist_model_policy:
        plan["model_policy"] = make_model_policy()
    plan["plan_digest"] = object_digest(plan, "plan_digest")
    return plan, specs


def write_graph_bundle(root: Path, plan: dict[str, Any], specs: dict[str, dict[str, Any]]) -> Path:
    entries = {entry["task_id"]: entry for entry in plan["tasks"]}
    for task_id, spec in specs.items():
        spec["task_spec_digest"] = object_digest(spec, "task_spec_digest")
        entries[task_id]["task_spec_digest"] = spec["task_spec_digest"]
        path = Path(spec["task_spec_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_fixture(path, spec)
    plan["plan_digest"] = object_digest(plan, "plan_digest")
    plan_path = root / "dispatch-plan.json"
    write_json_fixture(plan_path, plan)
    return plan_path


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


def run_candidate_evidence_tests() -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CandidateEvidenceScenarios)
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
    parser.add_argument("--candidate-evidence-json", type=Path)
    parser.add_argument("--previous-candidate-evidence-json", type=Path)
    parser.add_argument("--migrate-candidate-evidence", action="store_true")
    parser.add_argument("--release-task-id")
    parser.add_argument("--candidate-plan-revision", type=int)
    parser.add_argument("--candidate-plan-digest")
    parser.add_argument("--candidate-evidence-self-test", action="store_true")
    parser.add_argument("--skip-self-test", action="store_true")
    args = parser.parse_args()

    if args.migrate_candidate_evidence and args.candidate_evidence_json is None:
        parser.error("--migrate-candidate-evidence requires --candidate-evidence-json")
    if args.previous_candidate_evidence_json and args.candidate_evidence_json is None:
        parser.error("--previous-candidate-evidence-json requires --candidate-evidence-json")
    if args.previous_candidate_evidence_json and args.migrate_candidate_evidence:
        parser.error("candidate comparison and migration are separate operations")

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
        if args.candidate_evidence_json:
            candidate = load_json(args.candidate_evidence_json)
            if args.migrate_candidate_evidence:
                candidate = migrate_candidate_evidence(
                    candidate, schema, release_task_id=args.release_task_id,
                    plan_revision=args.candidate_plan_revision, plan_digest=args.candidate_plan_digest,
                )
                print(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            else:
                validate_candidate_evidence(candidate, schema)
                if args.previous_candidate_evidence_json:
                    previous_candidate = load_previous_json(
                        args.previous_candidate_evidence_json, "candidate evidence",
                    )
                    scope, affected = evaluate_candidate_invalidation(previous_candidate, candidate, schema)
                    print(f"candidate invalidation: {scope} gates={','.join(affected) if affected else 'none'}")

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
            validate_worker_card(previous_worker, schema, enforce_authorization_expiry=False)
            pair_results.append(("worker-card", previous_worker, current_worker,
                                 validate_worker_transition(previous_worker, current_worker)))
        if args.previous_master_card:
            previous_master = load_previous_json(args.previous_master_card, "Master Card")
            validate_historical_schema_pair(previous_master, current_master, "Master Card")
            validate_master_card(previous_master, schema, historical=True)
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

    if not args.skip_self_test:
        selected_tests_passed = (
            run_candidate_evidence_tests() if args.candidate_evidence_self_test else run_self_tests()
        )
        if not selected_tests_passed:
            return 1
    if is_historical:
        print_historical_report(pair_results, previous_cross, current_cross,
                                historical_completeness(previous_plan, previous_worker, previous_master))
    print("contract validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

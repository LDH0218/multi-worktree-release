#!/usr/bin/env python3
"""Validate multi-worktree release contracts without third-party packages."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path
from typing import Any


DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
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


class ContractError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def object_digest(value: dict[str, Any], digest_field: str) -> str:
    candidate = copy.deepcopy(value)
    candidate[digest_field] = None
    return "sha256:" + hashlib.sha256(canonical_json(candidate)).hexdigest()


def value_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_exact_fields(value: dict[str, Any], required: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing or extra:
        raise ContractError(f"{label} field mismatch; missing={missing}, extra={extra}")


def schema_required(schema: dict[str, Any], definition: str) -> set[str]:
    return set(schema["$defs"][definition]["required"])


def validate_digest(value: Any, label: str, allow_null: bool = False) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise ContractError(f"{label} must use sha256:<64-lowercase-hex>")


def validate_rfc3339(value: Any, label: str, allow_null: bool = False) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str):
        raise ContractError(f"{label} must be an RFC 3339 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError(f"{label} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")


def validate_authorization(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "authorization"), "authorization")
    if value["schema_version"] != 1:
        raise ContractError("authorization.schema_version must be 1")
    for field in ("real_external_call", "create_execution", "publish", "destructive_operation", "fresh_execution_required"):
        if not isinstance(value[field], bool):
            raise ContractError(f"authorization.{field} must be boolean")
    if not isinstance(value["max_calls"], int) or isinstance(value["max_calls"], bool) or value["max_calls"] < 0:
        raise ContractError("authorization.max_calls must be a non-negative integer")
    if not isinstance(value["max_cost"], (int, float)) or isinstance(value["max_cost"], bool) or value["max_cost"] < 0:
        raise ContractError("authorization.max_cost must be a non-negative number")
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
    validate_authorization(value["authorization"], schema)
    validate_rfc3339(value["issued_at"], "task_spec.issued_at")
    validate_digest(value["task_spec_digest"], "task_spec_digest")
    if value["task_spec_digest"] != object_digest(value, "task_spec_digest"):
        raise ContractError("task spec digest mismatch")


def validate_plan(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "dispatch_plan"), "dispatch plan")
    require_exact_fields(value["validation"], schema_required(schema, "plan_validation"), "plan validation")
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
        if task_id in entries:
            raise ContractError(f"duplicate task ID: {task_id}")
        ids.append(task_id)
        entries[task_id] = task
        for field in ("task_spec_path", "worktree"):
            if not Path(task[field]).is_absolute():
                raise ContractError(f"{task_id}.{field} must be absolute")
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


def validate_persisted_plan_specs(value: dict[str, Any], schema: dict[str, Any]) -> None:
    for entry in value["tasks"]:
        path = Path(entry["task_spec_path"])
        if not path.is_file():
            raise ContractError(f"persisted task spec not found: {path}")
        spec = load_json(path)
        validate_task_spec(spec, schema)
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
            raise ContractError(f"plan/task-spec mismatch for {entry['task_id']}: {mismatched}")
        if entry["authorization_envelope_digest"] != spec["authorization"]["envelope_digest"]:
            raise ContractError(f"authorization digest mismatch for {entry['task_id']}")
        if entry["acceptance_digest"] != value_digest(spec["acceptance"]):
            raise ContractError(f"acceptance digest mismatch for {entry['task_id']}")


def validate_worker_card(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "worker_card"), "Worker card")
    validate_authorization(value["authorization"], schema)
    validate_rfc3339(value["updated_at"], "worker_card.updated_at")
    validate_rfc3339(value["issued_at"], "worker_card.issued_at", allow_null=True)
    states = set(schema["$defs"]["worker_state"]["enum"])
    if value["state"] not in states:
        raise ContractError(f"unknown Worker state: {value['state']}")
    require_exact_fields(value["last_task"], schema_required(schema, "last_task"), "last_task")
    validate_digest(value["task_spec_digest"], "task_spec_digest", allow_null=True)
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
    if value["state"] == "BLOCKED" and (value["blocker_kind"] is None or value["blocker"] is None):
        raise ContractError("BLOCKED Worker card requires blocker_kind and blocker")


def validate_master_card(value: dict[str, Any], schema: dict[str, Any]) -> None:
    require_exact_fields(value, schema_required(schema, "master_card"), "Master card")
    if value["state"] not in set(schema["$defs"]["master_state"]["enum"]):
        raise ContractError(f"unknown Master state: {value['state']}")
    validate_rfc3339(value["updated_at"], "master_card.updated_at")
    validate_digest(value["dispatch_plan_digest"], "dispatch_plan_digest", allow_null=True)
    handoff_required = schema_required(schema, "worker_handoff")
    for handoff in value["worker_handoffs"]:
        require_exact_fields(handoff, handoff_required, "Worker handoff")
        for field in ("task_spec_digest", "authorization_envelope_digest", "acceptance_digest"):
            validate_digest(handoff[field], f"handoff.{field}")
    evidence = value["candidate_evidence"]
    require_exact_fields(evidence, schema_required(schema, "candidate_evidence"), "candidate evidence")
    validate_digest(evidence["gate_input_digest"], "gate_input_digest", allow_null=True)
    if evidence["status"] == "NONE" and any((evidence["release_head_sha"], evidence["gate_input_digest"], evidence["checks"])):
        raise ContractError("candidate status NONE cannot retain candidate evidence")
    if evidence["status"] in {"PASSED", "FAILED"} and (
        evidence["release_head_sha"] is None or evidence["gate_input_digest"] is None or not evidence["checks"]
    ):
        raise ContractError(f"candidate status {evidence['status']} requires HEAD, gate digest, and checks")
    if value["state"] == "IDLE" and any(value[field] is not None for field in
                                           ("release_task_id", "plan_revision", "dispatch_plan_path", "dispatch_plan_digest",
                                            "frozen_baseline_sha", "blocker")):
        raise ContractError("IDLE Master card retains active release lock fields")


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
    for relative in ("SKILL.md", "references/methodology.md", "references/templates.md"):
        if default_path not in (repo_root / relative).read_text(encoding="utf-8"):
            raise ContractError(f"default dispatch path missing from {relative}")


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
        validate_worker_card(card, self.schema)

    def test_idle_master_card_cannot_retain_active_lock(self) -> None:
        card = make_idle_master_card()
        validate_master_card(card, self.schema)
        card["release_task_id"] = "stale-release"
        with self.assertRaises(ContractError):
            validate_master_card(card, self.schema)


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


ACTIVE_SCHEMA: dict[str, Any] = {}


def run_self_tests() -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContractScenarios)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--task-spec", type=Path)
    parser.add_argument("--worker-card-json", type=Path)
    parser.add_argument("--master-card-json", type=Path)
    parser.add_argument("--skip-self-test", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    schema_path = repo_root / "references" / "contracts.schema.json"
    schema = load_json(schema_path)
    global ACTIVE_SCHEMA
    ACTIVE_SCHEMA = schema

    try:
        validate_documented_contracts(repo_root, schema)
        if args.plan:
            plan = load_json(args.plan)
            validate_plan(plan, schema)
            validate_persisted_plan_specs(plan, schema)
        if args.task_spec:
            validate_task_spec(load_json(args.task_spec), schema)
        if args.worker_card_json:
            validate_worker_card(load_json(args.worker_card_json), schema)
        if args.master_card_json:
            validate_master_card(load_json(args.master_card_json), schema)
    except (ContractError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"contract validation failed: {error}", file=sys.stderr)
        return 1

    if not args.skip_self_test and not run_self_tests():
        return 1
    print("contract validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Formal temporary-directory regressions for the preserved audit findings."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import close_release
import validate_contracts as contracts
import worker_card_sidecar
from test_close_release import CloseoutFixture, WorkerTransitionFixture, write_json


REPO_ROOT = Path(__file__).resolve().parents[1]


def active_card_for(spec: dict[str, object]) -> dict[str, object]:
    card = contracts.make_active_worker_card()
    card.update({
        "task_id": spec["task_id"],
        "task_spec_revision": spec["task_spec_revision"],
        "task_spec_digest": spec["task_spec_digest"],
        "task_spec_path": spec["task_spec_path"],
        "plan_revision": spec["plan_revision"],
        "dispatch_wave": spec["dispatch_wave"],
        "source_thread_id": spec["source_thread_id"],
        "issued_at": spec["issued_at"],
        "supersedes_task_id": spec["supersedes_task_id"],
        "worker_generation": spec["generation"],
        "frozen_baseline_sha": spec["expected_head"],
        "allowed_paths": copy.deepcopy(spec["allowed_paths"]),
        "forbidden_paths": copy.deepcopy(spec["forbidden_paths"]),
        "authorization": copy.deepcopy(spec["authorization"]),
        "acceptance_commands": copy.deepcopy(spec["acceptance"]),
        "record_revision": 2,
        "updated_at": "2026-01-01T00:01:00Z",
    })
    return card


class IdentityAndCloseoutAuditTests(unittest.TestCase):
    def test_explicit_task_id_mismatch_preserves_both_real_cards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, specs = contracts.make_graph_bundle(
                root,
                {
                    "a": {"status": "PUBLISHED", "parallel": ["b"]},
                    "b": {"status": "PUBLISHED", "parallel": ["a"]},
                },
            )
            plan_path = root / "dispatch-plan.json"
            master_path = root / "master-card.json"
            for task_id, spec in specs.items():
                worktree = Path(spec["worktree"])
                worktree.mkdir(parents=True)
                write_json(Path(spec["task_spec_path"]), spec)
                write_json(worktree / worker_card_sidecar.SIDECAR_NAME,
                           contracts.make_idle_worker_card())
            plan["plan_digest"] = contracts.object_digest(plan, "plan_digest")
            write_json(plan_path, plan)
            master = contracts.make_active_master_card(plan, str(plan_path))
            master["frozen_baseline_sha"] = specs["a"]["expected_head"]
            write_json(master_path, master)

            card_a_path = Path(specs["a"]["worktree"]) / worker_card_sidecar.SIDECAR_NAME
            card_b_path = Path(specs["b"]["worktree"]) / worker_card_sidecar.SIDECAR_NAME
            before_a = card_a_path.read_bytes()
            before_b = card_b_path.read_bytes()
            with self.assertRaises(worker_card_sidecar.SidecarError):
                worker_card_sidecar.transition_worker_card(
                    repo_root=REPO_ROOT,
                    plan_path=plan_path,
                    master_card_path=master_path,
                    task_id="a",
                    worker_card_path=card_a_path,
                    card=active_card_for(specs["b"]),
                )
            self.assertEqual(card_a_path.read_bytes(), before_a)
            self.assertEqual(card_b_path.read_bytes(), before_b)

            worker_card_sidecar.transition_worker_card(
                repo_root=REPO_ROOT,
                plan_path=plan_path,
                master_card_path=master_path,
                task_id="a",
                worker_card_path=card_a_path,
                card=active_card_for(specs["a"]),
            )
            active_a = card_a_path.read_bytes()
            with self.assertRaises(worker_card_sidecar.SidecarError):
                worker_card_sidecar.transition_worker_card(
                    repo_root=REPO_ROOT,
                    plan_path=plan_path,
                    master_card_path=master_path,
                    task_id="a",
                    worker_card_path=card_a_path,
                    card=active_card_for(specs["b"]),
                )
            self.assertEqual(card_a_path.read_bytes(), active_a)
            self.assertEqual(card_b_path.read_bytes(), before_b)

    def test_closeout_reconciles_noncanonical_copy_but_reads_live_canonical_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            cached = fixture.root / "cached-idle.json"
            cached.write_bytes(fixture.worker_path.read_bytes())
            active = json.loads(fixture.worker_path.read_text(encoding="utf-8"))
            spec = contracts.load_json(fixture.spec_path)
            plan = contracts.load_json(fixture.plan_path)
            active.update({
                "state": "ACTIVE",
                "record_revision": 2,
                "task_id": spec["task_id"],
                "task_spec_revision": spec["task_spec_revision"],
                "task_spec_digest": spec["task_spec_digest"],
                "task_spec_path": spec["task_spec_path"],
                "plan_revision": plan["plan_revision"],
                "dispatch_wave": spec["dispatch_wave"],
                "source_thread_id": spec["source_thread_id"],
                "issued_at": spec["issued_at"],
                "worker_generation": spec["generation"],
                "frozen_baseline_sha": spec["expected_head"],
                "allowed_paths": spec["allowed_paths"],
                "forbidden_paths": spec["forbidden_paths"],
                "authorization": spec["authorization"],
                "acceptance_commands": spec["acceptance"],
            })
            write_json(fixture.worker_path, active)
            before_master = fixture.master_path.read_bytes()
            with self.assertRaises(close_release.CloseoutError):
                close_release.close_release(
                    repo_root=fixture.repo,
                    plan_path=fixture.plan_path,
                    master_card_path=fixture.master_path,
                    worker_card_paths=[cached],
                    now="2026-08-31T00:00:00Z",
                )
            self.assertEqual(fixture.worker_path.read_bytes(), write_json_bytes(active))
            self.assertEqual(fixture.master_path.read_bytes(), before_master)
            self.assertFalse(fixture.archive.exists())


class RecoveryAndHistoryAuditTests(unittest.TestCase):
    def test_expired_cancelled_worker_snapshot_can_return_to_idle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            spec = contracts.load_json(fixture.spec_path)
            authorization = contracts.make_allowed_authorization_v2("external_call")
            authorization["expires_at"] = "2026-01-01T00:10:00Z"
            authorization["envelope_digest"] = contracts.object_digest(
                authorization, "envelope_digest",
            )
            spec["authorization"] = authorization
            spec["task_spec_digest"] = contracts.object_digest(spec, "task_spec_digest")
            write_json(fixture.spec_path, spec)

            plan = contracts.make_plan_for_spec(spec, "CANCELLED")
            plan.update({
                "state_root": str(fixture.state),
                "task_specs_root": str(fixture.tasks_root),
                "release_task_id": "release-transition",
                "ready_wave": None,
                "blocked_tasks": [],
            })
            plan["plan_digest"] = contracts.object_digest(plan, "plan_digest")
            write_json(fixture.plan_path, plan)
            master = contracts.make_active_master_card(plan, str(fixture.plan_path))
            master["frozen_baseline_sha"] = fixture.baseline
            write_json(fixture.master_path, master)

            previous = active_card_for(spec)
            write_json(fixture.worker_path, previous)
            current = contracts.make_idle_worker_card()
            current.update({
                "record_revision": 3,
                "updated_at": "2026-01-01T00:20:00Z",
                "last_task": {
                    "task_id": spec["task_id"],
                    "task_spec_revision": spec["task_spec_revision"],
                    "task_spec_digest": spec["task_spec_digest"],
                    "outcome": "CANCELLED",
                    "worker_commit_sha": None,
                    "integrated_as_sha": None,
                },
            })
            result = worker_card_sidecar.transition_worker_card(
                repo_root=REPO_ROOT,
                plan_path=fixture.plan_path,
                master_card_path=fixture.master_path,
                task_id=spec["task_id"],
                worker_card_path=fixture.worker_path,
                card=current,
            )
            self.assertEqual(result["state"], "IDLE")
            self.assertEqual(result["last_task"]["outcome"], "CANCELLED")

    def test_uncommitted_blocked_revision_recovers_without_rework_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            old_spec = contracts.load_json(fixture.spec_path)
            old = fixture.active()
            old.update({
                "state": "BLOCKED",
                "record_revision": 2,
                "blocker_kind": "WORKTREE",
                "blocker": "acceptance clarification required",
                "blocked_since": "2026-01-01T00:01:00Z",
                "recovery_owner": "master-1",
            })
            write_json(fixture.worker_path, old)

            new_spec = copy.deepcopy(old_spec)
            new_spec.update({
                "task_spec_path": str(fixture.tasks_root / "worker-task-r2.json"),
                "task_spec_revision": 2,
                "plan_revision": 2,
                "acceptance": ["test clarified edge condition"],
            })
            new_spec["task_spec_digest"] = contracts.object_digest(new_spec, "task_spec_digest")
            write_json(Path(new_spec["task_spec_path"]), new_spec)
            plan = contracts.make_plan_for_spec(
                new_spec, "PUBLISHED", plan_revision=2, revision_decision="REVISE",
            )
            plan.update({
                "state_root": str(fixture.state),
                "task_specs_root": str(fixture.tasks_root),
                "release_task_id": "release-transition",
            })
            plan["plan_digest"] = contracts.object_digest(plan, "plan_digest")
            write_json(fixture.plan_path, plan)
            master = contracts.make_active_master_card(plan, str(fixture.plan_path))
            master["frozen_baseline_sha"] = fixture.baseline
            write_json(fixture.master_path, master)

            current = active_card_for(new_spec)
            current["record_revision"] = 3
            current["updated_at"] = "2026-01-01T00:02:00Z"
            result = worker_card_sidecar.transition_worker_card(
                repo_root=REPO_ROOT,
                plan_path=fixture.plan_path,
                master_card_path=fixture.master_path,
                task_id=new_spec["task_id"],
                worker_card_path=fixture.worker_path,
                card=current,
            )
            self.assertEqual(result["state"], "ACTIVE")
            self.assertEqual(result["task_spec_revision"], 2)

    def test_active_worktree_identity_normalizes_aliases_without_rewriting_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared"
            shared.mkdir()
            aliased_plan, _ = contracts.make_graph_bundle(
                root / "aliased",
                {
                    "a": {"status": "PUBLISHED", "parallel": ["b"], "worktree": str(shared)},
                    "b": {"status": "PUBLISHED", "parallel": ["a"], "worktree": str(shared) + "/."},
                },
            )
            aliased_plan["plan_digest"] = contracts.object_digest(aliased_plan, "plan_digest")
            with self.assertRaisesRegex(contracts.ContractError, "share worktree"):
                contracts.validate_plan(aliased_plan, contracts.load_json(REPO_ROOT / "references/contracts.schema.json"))

            separate_root = root / "separate"
            distinct_a = separate_root / "a"
            distinct_b = separate_root / "b"
            distinct_a.mkdir(parents=True)
            distinct_b.mkdir()
            distinct_plan, _ = contracts.make_graph_bundle(
                separate_root,
                {
                    "a": {"status": "PUBLISHED", "parallel": ["b"], "worktree": str(distinct_a)},
                    "b": {"status": "PUBLISHED", "parallel": ["a"], "worktree": str(distinct_b)},
                },
            )
            distinct_plan["plan_digest"] = contracts.object_digest(distinct_plan, "plan_digest")
            contracts.validate_plan(distinct_plan, contracts.load_json(REPO_ROOT / "references/contracts.schema.json"))

    def test_same_task_immutable_changes_are_not_revise(self) -> None:
        schema = contracts.load_json(REPO_ROOT / "references/contracts.schema.json")
        fields = {
            "objective": "a different objective",
            "owner_role": "different-owner",
            "worktree": "/other/worktree",
            "expected_head": "b" * 40,
            "authorization": contracts.make_allowed_authorization_v2("external_call"),
        }
        for field, replacement in fields.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                old_spec_path = root / "tasks" / "task.json"
                old_spec = contracts.make_task_spec_at(old_spec_path)
                old_plan = contracts.make_plan_for_spec(old_spec, "PUBLISHED")
                old_plan.update({"state_root": str(root), "task_specs_root": str(root / "tasks")})
                current_spec = copy.deepcopy(old_spec)
                current_spec.update({
                    "task_spec_path": str(root / "tasks" / "task-r2.json"),
                    "task_spec_revision": 2,
                    "plan_revision": 2,
                    field: copy.deepcopy(replacement),
                })
                current_spec["task_spec_digest"] = contracts.object_digest(
                    current_spec, "task_spec_digest",
                )
                current_entry = copy.deepcopy(old_plan["tasks"][0])
                current_entry.update({
                    "task_spec_revision": 2,
                    "task_spec_digest": current_spec["task_spec_digest"],
                    "task_spec_path": current_spec["task_spec_path"],
                    "task_spec_plan_revision": 2,
                    "revision_decision": "REVISE",
                    "owner_role": current_spec["owner_role"],
                    "worktree": current_spec["worktree"],
                    "branch": current_spec["branch"],
                    "expected_head": current_spec["expected_head"],
                    "acceptance_digest": contracts.value_digest(current_spec["acceptance"]),
                    "authorization_envelope_digest": current_spec["authorization"]["envelope_digest"],
                })
                current_plan = copy.deepcopy(old_plan)
                current_plan.update({
                    "plan_revision": 2,
                    "record_revision": 2,
                    "updated_at": "2026-01-01T00:02:00Z",
                    "tasks": [current_entry],
                })
                current_plan["plan_digest"] = contracts.object_digest(current_plan, "plan_digest")
                with self.assertRaisesRegex(contracts.ContractError, r"\[H14\]"):
                    contracts.validate_plan_transition(
                        old_plan, current_plan, {"A": old_spec}, {"A": current_spec},
                    )

    def test_legal_supersede_preserves_predecessor_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_plan, specs = contracts.make_supersession_bundle(root)
            current_plan.update({
                "record_revision": 2,
                "updated_at": "2026-01-01T00:02:00Z",
            })
            previous_plan = copy.deepcopy(current_plan)
            previous_plan.update({
                "record_revision": 1,
                "plan_revision": 1,
                "updated_at": "2026-01-01T00:01:00Z",
                "tasks": [copy.deepcopy(next(item for item in current_plan["tasks"]
                                             if item["task_id"] == "old"))],
                "ready_wave": 1,
                "blocked_tasks": [],
            })
            previous_plan["tasks"][0].update({
                "revision_decision": "NEW",
                "dispatch_status": "PUBLISHED",
                "task_spec_plan_revision": 1,
            })
            previous_plan["plan_digest"] = contracts.object_digest(previous_plan, "plan_digest")
            current_plan["plan_digest"] = contracts.object_digest(current_plan, "plan_digest")
            contracts.validate_plan_transition(
                previous_plan, current_plan,
                {"old": copy.deepcopy(specs["old"])}, specs,
            )

    def test_full_plan_worker_master_cli_rejects_objective_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = WorkerTransitionFixture(root)
            old_spec = contracts.load_json(fixture.spec_path)
            old_plan = contracts.load_json(fixture.plan_path)
            old_plan["tasks"][0].update({"dispatch_status": "BLOCKED", "blocked_by": []})
            old_plan.update({"ready_wave": None, "blocked_tasks": ["worker-task"]})
            old_plan["plan_digest"] = contracts.object_digest(old_plan, "plan_digest")
            old_plan_path = root / "previous-plan.json"
            write_json(old_plan_path, old_plan)
            old_master = contracts.make_active_master_card(old_plan, str(old_plan_path))
            old_master["frozen_baseline_sha"] = fixture.baseline
            old_master_path = root / "previous-master.json"
            write_json(old_master_path, old_master)
            old_worker = fixture.active()
            old_worker.update({
                "state": "BLOCKED",
                "blocker_kind": "WORKTREE",
                "blocker": "await decision",
                "blocked_since": "2026-01-01T00:01:00Z",
                "recovery_owner": "master-1",
            })
            old_worker_path = root / "previous-worker.json"
            write_json(old_worker_path, old_worker)

            new_spec = copy.deepcopy(old_spec)
            new_spec.update({
                "task_spec_path": str(fixture.tasks_root / "worker-task-r2.json"),
                "task_spec_revision": 2,
                "plan_revision": 2,
                "objective": "a different business objective",
                "acceptance": ["test revised objective"],
            })
            new_spec["task_spec_digest"] = contracts.object_digest(new_spec, "task_spec_digest")
            write_json(Path(new_spec["task_spec_path"]), new_spec)
            current_plan = contracts.make_plan_for_spec(
                new_spec, "PUBLISHED", plan_revision=2, revision_decision="REVISE",
            )
            current_plan.update({
                "record_revision": 2,
                "state_root": str(fixture.state),
                "task_specs_root": str(fixture.tasks_root),
                "release_task_id": "release-transition",
                "updated_at": "2026-01-01T00:02:00Z",
            })
            current_plan["plan_digest"] = contracts.object_digest(current_plan, "plan_digest")
            current_plan_path = root / "current-plan.json"
            write_json(current_plan_path, current_plan)
            current_master = contracts.make_active_master_card(current_plan, str(current_plan_path))
            current_master["frozen_baseline_sha"] = fixture.baseline
            current_master["record_revision"] = old_master["record_revision"] + 1
            current_master["updated_at"] = "2026-01-01T00:02:00Z"
            current_master_path = root / "current-master.json"
            write_json(current_master_path, current_master)
            current_worker = active_card_for(new_spec)
            current_worker["record_revision"] = 3
            current_worker["updated_at"] = "2026-01-01T00:02:00Z"
            current_worker_path = root / "current-worker.json"
            write_json(current_worker_path, current_worker)

            command = [
                sys.executable,
                str(REPO_ROOT / "scripts" / "validate_contracts.py"),
                "--repo-root", str(REPO_ROOT),
                "--skip-self-test",
                "--previous-plan", str(old_plan_path),
                "--plan", str(current_plan_path),
                "--previous-worker-card", str(old_worker_path),
                "--worker-card-json", str(current_worker_path),
                "--previous-master-card", str(old_master_path),
                "--master-card-json", str(current_master_path),
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("[H14]", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


def write_json_bytes(value: dict[str, object]) -> bytes:
    return contracts.canonical_json(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)

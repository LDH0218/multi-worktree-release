"""Formal temporary-directory regressions for the preserved audit findings."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import close_release
import validate_contracts as contracts
import worker_card_sidecar
from test_close_release import CloseoutFixture, write_json


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


def write_json_bytes(value: dict[str, object]) -> bytes:
    return contracts.canonical_json(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)

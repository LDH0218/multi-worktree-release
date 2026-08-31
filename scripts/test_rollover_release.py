#!/usr/bin/env python3
"""Offline release-rollover tests using a closed temporary v1 release."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import close_release
import rollover_release
import validate_contracts as contracts
from test_close_release import CloseoutFixture, write_json


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_next_release(fixture: CloseoutFixture) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    next_worktree = fixture.root / "next-worker-worktree"
    next_worktree.mkdir()
    spec_path = fixture.tasks_root / "next-worker-task.json"
    spec = contracts.make_task_spec_at(spec_path)
    spec.update({
        "task_id": "next-worker-task",
        "source_thread_id": "master-next",
        "owner_role": "next-api",
        "worktree": str(next_worktree),
        "branch": "task/next-worker-task",
        "expected_head": fixture.head,
        "plan_revision": 1,
        "objective": "open the next release work item",
        "commit_message": "feat: next release work",
    })
    spec["task_spec_digest"] = contracts.object_digest(spec, "task_spec_digest")
    write_json(spec_path, spec)
    plan = contracts.make_plan_for_spec(spec, "PUBLISHED", plan_revision=1)
    plan.update({
        "record_revision": 1,
        "release_task_id": "release-2",
        "issued_by": "master-next",
        "state_root": str(fixture.state),
        "task_specs_root": str(fixture.tasks_root),
        "issued_at": "2026-01-02T00:00:01Z",
        "updated_at": "2026-01-02T00:00:01Z",
    })
    plan["plan_digest"] = contracts.object_digest(plan, "plan_digest")
    master = contracts.make_active_master_card(plan, str(fixture.plan_path))
    master.update({
        "record_revision": json.loads(fixture.master_path.read_text())["record_revision"] + 1,
        "updated_at": "2026-01-02T00:00:02Z",
        "frozen_baseline_sha": fixture.head,
        "worker_handoffs": [],
        "candidate_evidence": close_release.empty_live_candidate(),
    })
    staging = fixture.root / "staging"
    staging.mkdir()
    plan_path = staging / "next-plan.json"
    master_path = staging / "next-master-card.json"
    write_json(plan_path, plan)
    write_json(master_path, master)
    return plan_path, master_path, plan, master


class ReleaseRolloverTests(unittest.TestCase):
    def closed_fixture(self, root: Path) -> CloseoutFixture:
        fixture = CloseoutFixture(root)
        result = fixture.close(now="2026-01-02T00:00:00Z")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(json.loads(fixture.master_path.read_text())["state"], "IDLE")
        return fixture

    def test_rollover_is_idempotent_and_old_worktree_is_not_reopened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.closed_fixture(Path(temporary))
            archived = {path.name: path.read_bytes() for path in fixture.archive.iterdir()}
            shutil.rmtree(fixture.worker_worktree)
            next_plan_path, next_master_path, next_plan, next_master = build_next_release(fixture)

            first = rollover_release.rollover_release(
                repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                next_plan_path=next_plan_path, next_master_card_path=next_master_path,
            )
            self.assertEqual(first["status"], "PASS")
            self.assertFalse(first["idempotent"])
            self.assertEqual(json.loads(fixture.plan_path.read_text()), next_plan)
            self.assertEqual(json.loads(fixture.master_path.read_text()), next_master)
            self.assertEqual(archived, {path.name: path.read_bytes() for path in fixture.archive.iterdir()})
            receipt_path = Path(first["receipt"])
            schema = contracts.load_json(fixture.repo / "references" / "contracts.schema.json")
            contracts.validate_release_rollover(contracts.load_json(receipt_path), schema)

            second = rollover_release.rollover_release(
                repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                next_plan_path=next_plan_path, next_master_card_path=next_master_path,
            )
            self.assertTrue(second["idempotent"])
            command = [
                sys.executable, str(REPO_ROOT / "scripts" / "validate_contracts.py"), "--skip-self-test",
                "--repo-root", str(REPO_ROOT), "--plan", str(fixture.plan_path),
                "--master-card-json", str(fixture.master_path), "--release-rollover-json", str(receipt_path),
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("release rollover: PASS", result.stdout)

    def test_interruption_after_plan_replacement_recovers_from_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.closed_fixture(Path(temporary))
            next_plan_path, next_master_path, next_plan, next_master = build_next_release(fixture)
            source_master = fixture.master_path.read_bytes()
            original = rollover_release.replace_live

            def interrupted(path: Path, expected: bytes, replacement: bytes, label: str) -> bool:
                if label == "Master Card":
                    raise rollover_release.RolloverError("simulated interruption")
                return original(path, expected, replacement, label)

            with patch.object(rollover_release, "replace_live", side_effect=interrupted):
                with self.assertRaisesRegex(rollover_release.RolloverError, "simulated interruption"):
                    rollover_release.rollover_release(
                        repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                        next_plan_path=next_plan_path, next_master_card_path=next_master_path,
                    )
            self.assertEqual(json.loads(fixture.plan_path.read_text()), next_plan)
            self.assertEqual(fixture.master_path.read_bytes(), source_master)

            recovered = rollover_release.rollover_release(
                repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                next_plan_path=next_plan_path, next_master_card_path=next_master_path,
            )
            self.assertFalse(recovered["idempotent"])
            self.assertEqual(json.loads(fixture.master_path.read_text()), next_master)

    def test_invalid_target_or_source_drift_fails_before_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.closed_fixture(Path(temporary))
            next_plan_path, next_master_path, _, next_master = build_next_release(fixture)
            before_plan = fixture.plan_path.read_bytes()
            before_master = fixture.master_path.read_bytes()
            invalid = copy.deepcopy(next_master)
            invalid["worker_handoffs"] = [copy.deepcopy(json.loads(before_master.decode())["worker_handoffs"][0])]
            write_json(next_master_path, invalid)

            with self.assertRaisesRegex(rollover_release.RolloverError, "next release target"):
                rollover_release.rollover_release(
                    repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                    next_plan_path=next_plan_path, next_master_card_path=next_master_path,
                )
            self.assertEqual(fixture.plan_path.read_bytes(), before_plan)
            self.assertEqual(fixture.master_path.read_bytes(), before_master)
            self.assertFalse((fixture.state / "history" / "rollovers" / "release-2.json").exists())

            write_json(next_master_path, next_master)
            fixture.plan_path.write_bytes(before_plan + b"\n")
            with self.assertRaisesRegex(rollover_release.RolloverError, "live Dispatch Plan differs"):
                rollover_release.rollover_release(
                    repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                    next_plan_path=next_plan_path, next_master_card_path=next_master_path,
                )

    def test_semantically_tampered_archived_closeout_fails_before_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.closed_fixture(Path(temporary))
            next_plan_path, next_master_path, _, _ = build_next_release(fixture)
            before_plan = fixture.plan_path.read_bytes()
            before_master = fixture.master_path.read_bytes()
            closeout_path = fixture.archive / "closeout.json"
            closeout = json.loads(closeout_path.read_text())
            closeout["candidate"]["value_digest"] = "sha256:" + "0" * 64
            closeout["closeout_digest"] = contracts.object_digest(closeout, "closeout_digest")
            write_json(closeout_path, closeout)

            with self.assertRaisesRegex(rollover_release.RolloverError, "archived closeout semantics"):
                rollover_release.rollover_release(
                    repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                    next_plan_path=next_plan_path, next_master_card_path=next_master_path,
                )
            self.assertEqual(fixture.plan_path.read_bytes(), before_plan)
            self.assertEqual(fixture.master_path.read_bytes(), before_master)
            self.assertFalse((fixture.state / "history" / "rollovers" / "release-2.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)

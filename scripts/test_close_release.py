"""Offline closeout and historical Plan-locator contract tests."""

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
import validate_contracts as contracts


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = Path(__file__).with_name("validate_contracts.py")


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contracts.canonical_json(value))


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


class CloseoutFixture:
    """Build all records outside a temporary clean Git repository."""

    def __init__(self, root: Path, status: str = "INTEGRATED", *, candidate_head: str | None = None,
                 stale_candidate: bool = False, release_task_id: str = "release-1") -> None:
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        (self.repo / "references").mkdir()
        shutil.copyfile(REPO_ROOT / "references/contracts.schema.json",
                        self.repo / "references/contracts.schema.json")
        run(["git", "init", "-q", "-b", "main"], self.repo)
        run(["git", "config", "user.email", "fixture@example.invalid"], self.repo)
        run(["git", "config", "user.name", "Closeout Fixture"], self.repo)
        run(["git", "add", "references/contracts.schema.json"], self.repo)
        run(["git", "commit", "-qm", "schema"], self.repo)
        self.baseline = run(["git", "rev-parse", "HEAD"], self.repo)
        (self.repo / "tracked.txt").write_text("final\n", encoding="utf-8")
        run(["git", "add", "tracked.txt"], self.repo)
        run(["git", "commit", "-qm", "final"], self.repo)
        self.head = run(["git", "rev-parse", "HEAD"], self.repo)
        self.tree = run(["git", "rev-parse", "HEAD^{tree}"], self.repo)

        self.state = root / "state"
        self.tasks_root = self.state / "tasks"
        self.tasks_root.mkdir(parents=True)
        self.spec_path = self.tasks_root / "worker-task.json"
        self.plan_path = self.state / "dispatch-plan.json"
        self.master_path = self.state / "master-card.json"
        self.worker_path = root / "worker-card.json"
        self._write_records(status, candidate_head, stale_candidate, release_task_id)

    def _write_records(self, status: str, candidate_head: str | None, stale_candidate: bool,
                       release_task_id: str) -> None:
        spec = contracts.make_task_spec_at(self.spec_path)
        spec.update({
            "task_id": "worker-task",
            "source_thread_id": "master-1",
            "owner_role": "api",
            "worktree": str(self.root / "worker-worktree"),
            "branch": "task/worker-task",
            "expected_head": self.baseline,
            "objective": "fixture closeout task",
        })
        spec["task_spec_digest"] = contracts.object_digest(spec, "task_spec_digest")
        write_json(self.spec_path, spec)

        plan = contracts.make_plan_for_spec(spec, status)
        plan.update({
            "state_root": str(self.state),
            "task_specs_root": str(self.tasks_root),
            "release_task_id": release_task_id,
        })
        plan["plan_digest"] = contracts.object_digest(plan, "plan_digest")
        write_json(self.plan_path, plan)

        master = contracts.make_active_master_card(plan, str(self.plan_path))
        master["frozen_baseline_sha"] = self.baseline
        evidence_head = candidate_head or self.head
        candidate = contracts.make_candidate_v2(
            head=evidence_head,
            plan_revision=plan["plan_revision"],
            plan_digest=plan["plan_digest"],
            stale_gates={"targeted-tests"} if stale_candidate else None,
        )
        candidate["release_task_id"] = release_task_id
        if release_task_id != "release-1":
            contracts.refresh_candidate_inputs(candidate, refresh_evidence=True)
        master["candidate_evidence"] = candidate

        worker = contracts.make_idle_worker_card()
        if status in {"INTEGRATED", "CANCELLED", "SUPERSEDED"}:
            outcome = {"INTEGRATED": "COMPLETED", "CANCELLED": "CANCELLED",
                       "SUPERSEDED": "SUPERSEDED"}[status]
            worker["last_task"] = {
                "task_id": spec["task_id"],
                "task_spec_revision": spec["task_spec_revision"],
                "task_spec_digest": spec["task_spec_digest"],
                "outcome": outcome,
                "worker_commit_sha": self.head if outcome == "COMPLETED" else None,
                "integrated_as_sha": self.head if outcome == "COMPLETED" else None,
            }
        if status == "INTEGRATED":
            handoff = contracts.make_received_handoff()
            handoff.update({
                "state": "INTEGRATED",
                "task_id": spec["task_id"],
                "role": spec["owner_role"],
                "task_spec_revision": spec["task_spec_revision"],
                "task_spec_digest": spec["task_spec_digest"],
                "plan_revision": plan["plan_revision"],
                "dispatch_wave": spec["dispatch_wave"],
                "source_thread_id": spec["source_thread_id"],
                "frozen_baseline_sha": self.baseline,
                "authorization_envelope_digest": spec["authorization"]["envelope_digest"],
                "acceptance_digest": contracts.value_digest(spec["acceptance"]),
                "worker_commit_sha": self.head,
                "integrated_as_sha": self.head,
            })
            master["worker_handoffs"] = [handoff]
        write_json(self.master_path, master)
        write_json(self.worker_path, worker)
        self.active_master_bytes = self.master_path.read_bytes()
        self.worker_bytes = self.worker_path.read_bytes()

    @property
    def archive(self) -> Path:
        return self.state / "history" / "releases" / "release-1"

    def close(self, **kwargs: object) -> dict[str, object]:
        return close_release.close_release(
            repo_root=self.repo,
            plan_path=self.plan_path,
            master_card_path=self.master_path,
            worker_card_paths=[self.worker_path],
            **kwargs,
        )

    def assert_active_and_unarchived(self, test: unittest.TestCase) -> None:
        test.assertEqual(self.master_path.read_bytes(), self.active_master_bytes)
        if self.archive.exists():
            test.assertFalse(any(path.name in close_release.ARCHIVE_NAMES for path in self.archive.iterdir()))


class CloseReleaseTests(unittest.TestCase):
    def test_normal_closeout_archives_exact_three_files_and_preserves_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            result = fixture.close(now="2026-08-31T00:00:00Z")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(sorted(path.name for path in fixture.archive.iterdir()),
                             sorted(close_release.ARCHIVE_NAMES))
            self.assertEqual((fixture.archive / "dispatch-plan.json").read_bytes(),
                             fixture.plan_path.read_bytes())
            self.assertEqual((fixture.archive / "master-card.active.json").read_bytes(),
                             fixture.active_master_bytes)
            closeout = json.loads((fixture.archive / "closeout.json").read_text())
            schema = json.loads((fixture.repo / "references/contracts.schema.json").read_text())
            contracts.validate_release_closeout(closeout, schema)
            live = json.loads(fixture.master_path.read_text())
            archived = json.loads(fixture.active_master_bytes)
            self.assertEqual(live["state"], "IDLE")
            self.assertEqual(live["worker_handoffs"], archived["worker_handoffs"])
            self.assertEqual(fixture.worker_path.read_bytes(), fixture.worker_bytes)

    def test_cancellation_is_terminal_but_has_no_invented_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory), status="CANCELLED")
            fixture.close(now="2026-08-31T00:00:00Z")
            live = json.loads(fixture.master_path.read_text())
            closeout = json.loads((fixture.archive / "closeout.json").read_text())
            self.assertEqual(live["state"], "IDLE")
            self.assertEqual(live["worker_handoffs"], [])
            self.assertEqual(closeout["worker_handoffs"]["count"], 0)

    def test_duplicate_execution_is_an_idempotent_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            first = fixture.close(now="2026-08-31T00:00:00Z")
            archive_bytes = {path.name: path.read_bytes() for path in fixture.archive.iterdir()}
            second = fixture.close(now="2027-01-01T00:00:00Z")
            self.assertFalse(first["idempotent"])
            self.assertTrue(second["idempotent"])
            self.assertEqual(archive_bytes,
                             {path.name: path.read_bytes() for path in fixture.archive.iterdir()})

    def test_nonterminal_task_stale_candidate_and_head_mismatch_fail_closed(self) -> None:
        cases = (("nonterminal", {"status": "PUBLISHED"}),
                 ("stale-candidate", {"stale_candidate": True}),
                 ("head-mismatch", {"candidate_head": "a" * 40}))
        for name, options in cases:
            with self.subTest(scenario=name), tempfile.TemporaryDirectory() as directory:
                fixture = CloseoutFixture(Path(directory), **options)
                with self.assertRaises(close_release.CloseoutError):
                    fixture.close(now="2026-08-31T00:00:00Z")
                fixture.assert_active_and_unarchived(self)

    def test_conflicting_plan_master_and_closeout_bytes_never_overwrite(self) -> None:
        for conflict_name in close_release.ARCHIVE_NAMES:
            with self.subTest(path=conflict_name), tempfile.TemporaryDirectory() as directory:
                fixture = CloseoutFixture(Path(directory))
                fixture.archive.mkdir(parents=True)
                conflict = fixture.archive / conflict_name
                conflict.write_bytes(b"{\"conflict\":true}\n")
                with self.assertRaises(close_release.CloseoutError):
                    fixture.close(now="2026-08-31T00:00:00Z")
                self.assertEqual(conflict.read_bytes(), b"{\"conflict\":true}\n")
                self.assertEqual(fixture.master_path.read_bytes(), fixture.active_master_bytes)

    def test_interruption_after_each_archive_prefix_recovers_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            original = close_release.write_once
            calls = 0

            def interrupt_after_first(path: Path, data: bytes) -> bool:
                nonlocal calls
                result = original(path, data)
                calls += 1
                if calls == 1:
                    raise close_release.CloseoutError("simulated archive interruption")
                return result

            with patch.object(close_release, "write_once", side_effect=interrupt_after_first):
                with self.assertRaises(close_release.CloseoutError):
                    fixture.close(now="2026-08-31T00:00:00Z")
            self.assertTrue((fixture.archive / "dispatch-plan.json").exists())
            self.assertFalse((fixture.archive / "master-card.active.json").exists())
            self.assertEqual(fixture.master_path.read_bytes(), fixture.active_master_bytes)
            fixture.close(now="2026-08-31T00:00:00Z")
            self.assertEqual(sorted(path.name for path in fixture.archive.iterdir()),
                             sorted(close_release.ARCHIVE_NAMES))

    def test_interruption_after_closeout_only_retries_final_live_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            with patch.object(close_release, "replace_live",
                              side_effect=close_release.CloseoutError("simulated live interruption")):
                with self.assertRaises(close_release.CloseoutError):
                    fixture.close(now="2026-08-31T00:00:00Z")
            self.assertEqual(sorted(path.name for path in fixture.archive.iterdir()),
                             sorted(close_release.ARCHIVE_NAMES))
            self.assertEqual(fixture.master_path.read_bytes(), fixture.active_master_bytes)
            fixture.close(now="2026-08-31T00:00:00Z")
            self.assertEqual(json.loads(fixture.master_path.read_text())["state"], "IDLE")

    def test_unsafe_release_id_and_symlinked_archive_parent_fail_before_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory), release_task_id="../escape")
            with self.assertRaises(close_release.CloseoutError):
                fixture.close(now="2026-08-31T00:00:00Z")
            fixture.assert_active_and_unarchived(self)

        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            outside = fixture.root / "outside"
            outside.mkdir()
            (fixture.state / "history").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(close_release.CloseoutError):
                fixture.close(now="2026-08-31T00:00:00Z")
            self.assertEqual(fixture.master_path.read_bytes(), fixture.active_master_bytes)
            self.assertFalse((outside / "releases").exists())

    def test_standalone_closeout_record_is_schema_first_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            fixture.close(now="2026-08-31T00:00:00Z")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), "--skip-self-test", "--release-closeout-json",
                 str(fixture.archive / "closeout.json")],
                cwd=REPO_ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("release closeout: PASS", result.stdout)

    def test_closeout_cli_accepts_explicit_local_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            result = subprocess.run(
                [sys.executable, str(Path(close_release.__file__)), "--repo-root", str(fixture.repo),
                 "--plan", str(fixture.plan_path), "--master-card-json", str(fixture.master_path),
                 "--worker-card-json", str(fixture.worker_path), "--now", "2026-08-31T00:00:00Z"],
                cwd=REPO_ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("live_master=IDLE", result.stdout)


class LocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        state = self.root / "state"
        tasks = state / "tasks"
        tasks.mkdir(parents=True)
        spec_path = tasks / "locator-task.json"
        spec = contracts.make_task_spec_at(spec_path)
        spec.update({
            "task_id": "locator-task",
            "source_thread_id": "master-1",
            "owner_role": "api",
            "worktree": str(self.root / "worker"),
            "branch": "task/locator-task",
            "expected_head": "a" * 40,
        })
        spec["task_spec_digest"] = contracts.object_digest(spec, "task_spec_digest")
        write_json(spec_path, spec)
        self.plan = contracts.make_plan_for_spec(spec, "PUBLISHED")
        self.plan.update({"state_root": str(state), "task_specs_root": str(tasks)})
        self.plan["plan_digest"] = contracts.object_digest(self.plan, "plan_digest")
        self.current_plan_path = state / "current-plan.json"
        write_json(self.current_plan_path, self.plan)
        self.previous = copy.deepcopy(self.plan)
        self.previous.update({"record_revision": 1, "updated_at": "2025-12-31T23:59:00Z"})
        self.previous["plan_digest"] = contracts.object_digest(self.previous, "plan_digest")
        self.previous_plan_path = state / "previous-plan.json"
        write_json(self.previous_plan_path, self.previous)
        self.plan.update({"record_revision": 2, "updated_at": "2026-01-01T00:01:00Z"})
        self.plan["plan_digest"] = contracts.object_digest(self.plan, "plan_digest")
        write_json(self.current_plan_path, self.plan)
        self.normative = self.root / "normative" / "dispatch-plan.json"
        master = contracts.make_active_master_card(self.plan, str(self.current_plan_path))
        self.master_path = state / "master-card.json"
        write_json(self.master_path, master)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def validator(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), "--skip-self-test", "--repo-root", str(REPO_ROOT),
             *arguments], cwd=REPO_ROOT, text=True, capture_output=True, check=False,
        )

    def set_master_locator(self, locator: Path) -> None:
        master = json.loads(self.master_path.read_text())
        master["dispatch_plan_path"] = str(locator)
        write_json(self.master_path, master)

    def test_locator_option_pairing_and_absolute_form_have_stable_usage_errors(self) -> None:
        for option in ("--plan-locator", "--previous-plan-locator"):
            with self.subTest(option=option):
                missing = self.validator(option, str(self.normative))
                self.assertEqual(missing.returncode, 2)
                self.assertIn("[L01]", missing.stderr)
        relative = self.validator("--plan", str(self.current_plan_path), "--plan-locator", "relative.json")
        self.assertEqual(relative.returncode, 2)
        self.assertIn("[L02]", relative.stderr)
        precedence = self.validator(
            "--previous-plan", str(self.previous_plan_path), "--previous-plan-locator", str(self.normative),
        )
        self.assertEqual(precedence.returncode, 2)
        self.assertIn("[H01]", precedence.stderr)

    def test_locator_noop_keeps_legacy_output_and_explicit_context_reports_identity(self) -> None:
        legacy = self.validator("--plan", str(self.current_plan_path), "--master-card-json", str(self.master_path))
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertEqual(legacy.stdout, "contract validation: PASS\n")
        self.set_master_locator(self.normative)
        explicit = self.validator(
            "--plan", str(self.current_plan_path), "--master-card-json", str(self.master_path),
            "--plan-locator", str(self.normative),
        )
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertIn("role=current", explicit.stdout)
        self.assertIn("physical_input=" + str(self.current_plan_path), explicit.stdout)
        self.assertIn("effective_locator=" + str(self.normative.resolve()), explicit.stdout)
        self.assertIn("locator_source=explicit", explicit.stdout)
        self.assertIn("check=plan-master-locator", explicit.stdout)

    def test_locator_mismatch_remains_h27_and_symlink_locator_canonicalizes(self) -> None:
        self.set_master_locator(self.normative)
        mismatch = self.validator(
            "--plan", str(self.current_plan_path), "--master-card-json", str(self.master_path),
            "--plan-locator", str(self.root / "other" / "dispatch-plan.json"),
        )
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("[H27]", mismatch.stderr)
        target = self.root / "normative-target.json"
        locator_link = self.root / "normative-link.json"
        locator_link.symlink_to(target)
        self.set_master_locator(target)
        symlinked = self.validator(
            "--plan", str(self.current_plan_path), "--master-card-json", str(self.master_path),
            "--plan-locator", str(locator_link),
        )
        self.assertEqual(symlinked.returncode, 0, symlinked.stderr)
        self.assertIn("effective_locator=" + str(target.resolve()), symlinked.stdout)

    def test_archived_previous_and_current_locators_are_reported_independently(self) -> None:
        self.set_master_locator(self.normative)
        result = self.validator(
            "--plan", str(self.current_plan_path), "--previous-plan", str(self.previous_plan_path),
            "--master-card-json", str(self.master_path), "--plan-locator", str(self.normative),
            "--previous-plan-locator", str(self.normative),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("role=current", result.stdout)
        self.assertIn("role=previous", result.stdout)
        self.assertIn("physical_input=" + str(self.previous_plan_path), result.stdout)
        self.assertGreaterEqual(result.stdout.count("locator_source=explicit"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

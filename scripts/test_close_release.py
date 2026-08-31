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
import worker_card_sidecar


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
        self.worker_worktree = root / "worker-worktree"
        self.worker_worktree.mkdir()
        self.worker_path = self.worker_worktree / close_release.WORKER_CARD_SIDECAR
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

    def bootstrap_sidecar(self) -> dict[str, object]:
        return worker_card_sidecar.bootstrap_worker_card(
            repo_root=self.repo,
            plan_path=self.plan_path,
            master_card_path=self.master_path,
            task_id="worker-task",
        )

    def assert_active_and_unarchived(self, test: unittest.TestCase) -> None:
        test.assertEqual(self.master_path.read_bytes(), self.active_master_bytes)
        if self.archive.exists():
            test.assertFalse(any(path.name in close_release.ARCHIVE_NAMES for path in self.archive.iterdir()))


class FiveWorktreeFixture:
    """Build five terminal assignments and their Master handoff evidence."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        (self.repo / "references").mkdir()
        shutil.copyfile(REPO_ROOT / "references/contracts.schema.json",
                        self.repo / "references/contracts.schema.json")
        run(["git", "init", "-q", "-b", "main"], self.repo)
        run(["git", "config", "user.email", "fixture@example.invalid"], self.repo)
        run(["git", "config", "user.name", "Five Worktree Fixture"], self.repo)
        run(["git", "add", "references/contracts.schema.json"], self.repo)
        run(["git", "commit", "-qm", "schema"], self.repo)
        (self.repo / "tracked.txt").write_text("final\n", encoding="utf-8")
        run(["git", "add", "tracked.txt"], self.repo)
        run(["git", "commit", "-qm", "final"], self.repo)
        self.head = run(["git", "rev-parse", "HEAD"], self.repo)

        self.state = root / "state"
        self.tasks_root = self.state / "tasks"
        self.tasks_root.mkdir(parents=True)
        self.plan_path = self.state / "dispatch-plan.json"
        self.master_path = self.state / "master-card.json"
        nodes: dict[str, dict[str, object]] = {}
        self.worktrees: dict[str, Path] = {}
        for index in range(5):
            task_id = f"worker-{index}"
            worktree = root / task_id
            worktree.mkdir()
            self.worktrees[task_id] = worktree
            nodes[task_id] = {
                "status": "INTEGRATED",
                "owner_role": task_id,
                "worktree": str(worktree),
                "allowed_paths": [f"src/{task_id}"],
            }
        self.plan, self.specs = contracts.make_graph_bundle(self.state, nodes)
        self.plan.update({"release_task_id": "release-five", "updated_at": "2026-01-01T00:02:00Z"})
        self.plan["plan_digest"] = contracts.object_digest(self.plan, "plan_digest")
        for spec in self.specs.values():
            write_json(Path(spec["task_spec_path"]), spec)
        write_json(self.plan_path, self.plan)

        master = contracts.make_active_master_card(self.plan, str(self.plan_path))
        master["frozen_baseline_sha"] = self.plan["tasks"][0]["expected_head"]
        candidate = contracts.make_candidate_v2(
            head=self.head, plan_revision=self.plan["plan_revision"], plan_digest=self.plan["plan_digest"],
        )
        candidate["release_task_id"] = self.plan["release_task_id"]
        contracts.refresh_candidate_inputs(candidate, refresh_evidence=True)
        master["candidate_evidence"] = candidate
        handoffs = []
        for entry in self.plan["tasks"]:
            spec = self.specs[entry["task_id"]]
            handoff = contracts.make_received_handoff()
            handoff.update({
                "state": "INTEGRATED",
                "task_id": entry["task_id"],
                "role": spec["owner_role"],
                "task_spec_revision": entry["task_spec_revision"],
                "task_spec_digest": entry["task_spec_digest"],
                "plan_revision": entry["task_spec_plan_revision"],
                "dispatch_wave": entry["dispatch_wave"],
                "source_thread_id": spec["source_thread_id"],
                "frozen_baseline_sha": entry["expected_head"],
                "authorization_envelope_digest": spec["authorization"]["envelope_digest"],
                "acceptance_digest": contracts.value_digest(spec["acceptance"]),
                "worker_commit_sha": self.head,
                "integrated_as_sha": self.head,
            })
            handoffs.append(handoff)
        master["worker_handoffs"] = handoffs
        write_json(self.master_path, master)

    def bootstrap_all(self) -> dict[str, dict[str, object]]:
        cards: dict[str, dict[str, object]] = {}
        for task_id, worktree in self.worktrees.items():
            cards[task_id] = worker_card_sidecar.bootstrap_worker_card(
                repo_root=self.repo,
                plan_path=self.plan_path,
                master_card_path=self.master_path,
                task_id=task_id,
                worker_card_path=worktree / worker_card_sidecar.SIDECAR_NAME,
            )
        return cards

    @property
    def archive(self) -> Path:
        return self.state / "history" / "releases" / "release-five"


class WorkerTransitionFixture:
    """Build a one-task PUBLISHED graph for Worker-owned sidecar transitions."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        (self.repo / "references").mkdir()
        shutil.copyfile(REPO_ROOT / "references/contracts.schema.json",
                        self.repo / "references/contracts.schema.json")
        run(["git", "init", "-q", "-b", "main"], self.repo)
        run(["git", "config", "user.email", "fixture@example.invalid"], self.repo)
        run(["git", "config", "user.name", "Transition Fixture"], self.repo)
        run(["git", "add", "references/contracts.schema.json"], self.repo)
        run(["git", "commit", "-qm", "schema"], self.repo)
        self.baseline = run(["git", "rev-parse", "HEAD"], self.repo)
        (self.repo / "tracked.txt").write_text("final\n", encoding="utf-8")
        run(["git", "add", "tracked.txt"], self.repo)
        run(["git", "commit", "-qm", "final"], self.repo)
        self.head = run(["git", "rev-parse", "HEAD"], self.repo)

        self.state = root / "state"
        self.tasks_root = self.state / "tasks"
        self.tasks_root.mkdir(parents=True)
        self.spec_path = self.tasks_root / "worker-task.json"
        self.plan_path = self.state / "dispatch-plan.json"
        self.master_path = self.state / "master-card.json"
        self.worktree = root / "worker-worktree"
        self.worktree.mkdir()
        self.worker_path = self.worktree / worker_card_sidecar.SIDECAR_NAME
        self._build_records()

    def _build_records(self) -> None:
        self.spec = contracts.make_task_spec_at(self.spec_path)
        self.spec.update({
            "task_id": "worker-task",
            "source_thread_id": "master-1",
            "owner_role": "api",
            "worktree": str(self.worktree),
            "branch": "task/worker-task",
            "expected_head": self.baseline,
            "objective": "fixture Worker transition task",
        })
        self.spec["task_spec_digest"] = contracts.object_digest(self.spec, "task_spec_digest")
        write_json(self.spec_path, self.spec)
        self.plan = contracts.make_plan_for_spec(self.spec, "PUBLISHED")
        self.plan.update({
            "state_root": str(self.state),
            "task_specs_root": str(self.tasks_root),
            "release_task_id": "release-transition",
        })
        self.plan["plan_digest"] = contracts.object_digest(self.plan, "plan_digest")
        write_json(self.plan_path, self.plan)

        self.master = contracts.make_active_master_card(self.plan, str(self.plan_path))
        self.master["frozen_baseline_sha"] = self.baseline
        candidate = contracts.make_candidate_v2(
            head=self.head, plan_revision=self.plan["plan_revision"], plan_digest=self.plan["plan_digest"],
            stale_gates={"targeted-tests"},
        )
        candidate["release_task_id"] = self.plan["release_task_id"]
        contracts.refresh_candidate_inputs(candidate, refresh_evidence=True)
        self.master["candidate_evidence"] = candidate
        write_json(self.master_path, self.master)

        idle = contracts.make_idle_worker_card()
        idle["updated_at"] = "2026-01-01T00:00:00Z"
        write_json(self.worker_path, idle)

    def active(self) -> dict[str, object]:
        card = contracts.make_active_worker_card()
        card.update({
            "record_revision": 2,
            "updated_at": "2026-01-01T00:01:00Z",
            "task_id": self.spec["task_id"],
            "task_spec_revision": self.spec["task_spec_revision"],
            "task_spec_digest": self.spec["task_spec_digest"],
            "task_spec_path": self.spec["task_spec_path"],
            "plan_revision": self.plan["plan_revision"],
            "dispatch_wave": self.spec["dispatch_wave"],
            "source_thread_id": self.spec["source_thread_id"],
            "issued_at": self.spec["issued_at"],
            "supersedes_task_id": self.spec["supersedes_task_id"],
            "worker_generation": self.spec["generation"],
            "frozen_baseline_sha": self.spec["expected_head"],
            "allowed_paths": self.spec["allowed_paths"],
            "forbidden_paths": self.spec["forbidden_paths"],
            "authorization": copy.deepcopy(self.spec["authorization"]),
            "acceptance_commands": self.spec["acceptance"],
        })
        return card

    def awaiting(self) -> dict[str, object]:
        card = self.active()
        card.update({
            "state": "AWAITING_INTEGRATION",
            "record_revision": 3,
            "updated_at": "2026-01-01T00:02:00Z",
            "worker_commit_sha": self.head,
        })
        return card

    def integrate(self) -> None:
        self.plan["tasks"][0]["dispatch_status"] = "INTEGRATED"
        self.plan["record_revision"] += 1
        self.plan["updated_at"] = "2026-01-01T00:03:00Z"
        self.plan["ready_wave"] = None
        self.plan["blocked_tasks"] = []
        self.plan["plan_digest"] = contracts.object_digest(self.plan, "plan_digest")
        write_json(self.plan_path, self.plan)

        handoff = contracts.make_received_handoff()
        handoff.update({
            "state": "INTEGRATED",
            "task_id": self.spec["task_id"],
            "role": self.spec["owner_role"],
            "task_spec_revision": self.spec["task_spec_revision"],
            "task_spec_digest": self.spec["task_spec_digest"],
            "plan_revision": self.spec["plan_revision"],
            "dispatch_wave": self.spec["dispatch_wave"],
            "source_thread_id": self.spec["source_thread_id"],
            "frozen_baseline_sha": self.spec["expected_head"],
            "authorization_envelope_digest": self.spec["authorization"]["envelope_digest"],
            "acceptance_digest": contracts.value_digest(self.spec["acceptance"]),
            "worker_commit_sha": self.head,
            "integrated_as_sha": self.head,
        })
        self.master["worker_handoffs"] = [handoff]
        self.master["record_revision"] += 1
        self.master["updated_at"] = "2026-01-01T00:03:00Z"
        self.master["plan_revision"] = self.plan["plan_revision"]
        self.master["dispatch_plan_digest"] = self.plan["plan_digest"]
        candidate = contracts.make_candidate_v2(
            head=self.head, plan_revision=self.plan["plan_revision"], plan_digest=self.plan["plan_digest"],
        )
        candidate["release_task_id"] = self.plan["release_task_id"]
        contracts.refresh_candidate_inputs(candidate, refresh_evidence=True)
        self.master["candidate_evidence"] = candidate
        write_json(self.master_path, self.master)

    def idle_after_integration(self) -> dict[str, object]:
        card = contracts.make_idle_worker_card()
        card.update({
            "record_revision": 4,
            "updated_at": "2026-01-01T00:04:00Z",
            "last_task": {
                "task_id": self.spec["task_id"],
                "task_spec_revision": self.spec["task_spec_revision"],
                "task_spec_digest": self.spec["task_spec_digest"],
                "outcome": "COMPLETED",
                "worker_commit_sha": self.head,
                "integrated_as_sha": self.head,
            },
        })
        return card


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

    def test_closeout_discovers_sidecar_when_explicit_inputs_are_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            result = close_release.close_release(
                repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                now="2026-08-31T00:00:00Z",
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(json.loads(fixture.master_path.read_text())["state"], "IDLE")

    def test_master_bootstrap_is_schema_valid_idempotent_and_preserves_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            fixture.worker_path.unlink()
            plan_bytes = fixture.plan_path.read_bytes()
            master_bytes = fixture.master_path.read_bytes()
            first = fixture.bootstrap_sidecar()
            first_bytes = fixture.worker_path.read_bytes()
            second = fixture.bootstrap_sidecar()
            self.assertEqual(first, second)
            self.assertEqual(first_bytes, fixture.worker_path.read_bytes())
            self.assertEqual(first["state"], "IDLE")
            self.assertEqual(first["last_task"]["task_id"], "worker-task")
            self.assertEqual(fixture.plan_path.read_bytes(), plan_bytes)
            self.assertEqual(fixture.master_path.read_bytes(), master_bytes)

    def test_master_bootstrap_interruption_after_install_retries_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            fixture.worker_path.unlink()
            original = worker_card_sidecar._existing_or_install

            def interrupt(path: Path, data: bytes) -> bool:
                result = original(path, data)
                raise worker_card_sidecar.SidecarError("simulated sidecar interruption")

            with patch.object(worker_card_sidecar, "_existing_or_install", side_effect=interrupt):
                with self.assertRaises(worker_card_sidecar.SidecarError):
                    fixture.bootstrap_sidecar()
            installed = fixture.worker_path.read_bytes()
            fixture.bootstrap_sidecar()
            self.assertEqual(installed, fixture.worker_path.read_bytes())

    def test_master_bootstrap_rejects_conflict_nonterminal_missing_and_mismatched_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            fixture.worker_path.unlink()
            fixture.bootstrap_sidecar()
            conflict = json.loads(fixture.worker_path.read_text())
            conflict["updated_at"] = "2026-01-01T00:02:00Z"
            write_json(fixture.worker_path, conflict)
            conflict_bytes = fixture.worker_path.read_bytes()
            with self.assertRaises(worker_card_sidecar.SidecarError):
                fixture.bootstrap_sidecar()
            self.assertEqual(fixture.worker_path.read_bytes(), conflict_bytes)

        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory), status="PUBLISHED")
            fixture.worker_path.unlink()
            with self.assertRaises(worker_card_sidecar.SidecarError):
                fixture.bootstrap_sidecar()
            self.assertFalse(fixture.worker_path.exists())

        for mutation in ("missing", "mismatched"):
            with self.subTest(handoff=mutation), tempfile.TemporaryDirectory() as directory:
                fixture = CloseoutFixture(Path(directory))
                master = json.loads(fixture.master_path.read_text())
                if mutation == "missing":
                    master["worker_handoffs"] = []
                else:
                    master["worker_handoffs"][0]["role"] = "other-role"
                write_json(fixture.master_path, master)
                fixture.worker_path.unlink()
                with self.assertRaises(worker_card_sidecar.SidecarError):
                    fixture.bootstrap_sidecar()
                self.assertFalse(fixture.worker_path.exists())

    def test_master_bootstrap_rejects_unsafe_target_and_non_idle_existing_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            outside = fixture.root / "outside.json"
            outside.write_bytes(b"outside")
            fixture.worker_path.unlink()
            fixture.worker_path.symlink_to(outside)
            with self.assertRaises(worker_card_sidecar.SidecarError):
                fixture.bootstrap_sidecar()
            self.assertEqual(outside.read_bytes(), b"outside")

        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            active = contracts.make_active_worker_card()
            write_json(fixture.worker_path, active)
            active_bytes = fixture.worker_path.read_bytes()
            with self.assertRaises(worker_card_sidecar.SidecarError):
                fixture.bootstrap_sidecar()
            self.assertEqual(fixture.worker_path.read_bytes(), active_bytes)

    def test_closeout_rejects_missing_duplicate_extra_symlink_invalid_non_idle_stale_and_cross_worktree(self) -> None:
        cases = ("missing", "duplicate", "extra", "symlink", "invalid", "non-idle", "stale", "cross-worktree")
        for scenario in cases:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                fixture = CloseoutFixture(Path(directory))
                if scenario == "missing":
                    fixture.worker_path.unlink()
                    paths = None
                elif scenario == "duplicate":
                    paths = [fixture.worker_path, fixture.worker_path]
                elif scenario == "extra":
                    extra = fixture.root / "extra-worker.json"
                    extra.write_bytes(fixture.worker_path.read_bytes())
                    paths = [fixture.worker_path, extra]
                elif scenario == "symlink":
                    outside = fixture.root / "outside.json"
                    outside.write_bytes(fixture.worker_path.read_bytes())
                    fixture.worker_path.unlink()
                    fixture.worker_path.symlink_to(outside)
                    paths = None
                elif scenario == "invalid":
                    fixture.worker_path.write_bytes(b"{}")
                    paths = None
                elif scenario == "non-idle":
                    write_json(fixture.worker_path, contracts.make_active_worker_card())
                    paths = None
                elif scenario == "stale":
                    stale = json.loads(fixture.worker_path.read_text())
                    stale["last_task"] = {
                        "task_id": "missing-task",
                        "task_spec_revision": 1,
                        "task_spec_digest": "sha256:" + "f" * 64,
                        "outcome": "COMPLETED",
                        "worker_commit_sha": "a" * 40,
                        "integrated_as_sha": "b" * 40,
                    }
                    write_json(fixture.worker_path, stale)
                    paths = None
                else:
                    other = fixture.root / "other-worker"
                    other.mkdir()
                    other_card = other / close_release.WORKER_CARD_SIDECAR
                    other_card.write_bytes(fixture.worker_path.read_bytes())
                    paths = [other_card]
                with self.assertRaises(close_release.CloseoutError):
                    close_release.close_release(
                        repo_root=fixture.repo, plan_path=fixture.plan_path,
                        master_card_path=fixture.master_path, worker_card_paths=paths,
                        now="2026-08-31T00:00:00Z",
                    )
                fixture.assert_active_and_unarchived(self)

    def test_closeout_keeps_explicit_json_inputs_when_they_reconcile_to_the_same_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = CloseoutFixture(Path(directory))
            legacy_input = fixture.root / "legacy-worker-card.json"
            legacy_input.write_bytes(fixture.worker_path.read_bytes())
            result = close_release.close_release(
                repo_root=fixture.repo, plan_path=fixture.plan_path,
                master_card_path=fixture.master_path, worker_card_paths=[legacy_input],
                now="2026-08-31T00:00:00Z",
            )
            self.assertEqual(result["status"], "PASS")

    def test_five_worktree_bootstrap_and_discovered_closeout_drill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = FiveWorktreeFixture(Path(directory))
            cards = fixture.bootstrap_all()
            self.assertEqual(set(cards), set(fixture.worktrees))
            sidecar_bytes = {
                task_id: (worktree / worker_card_sidecar.SIDECAR_NAME).read_bytes()
                for task_id, worktree in fixture.worktrees.items()
            }
            result = close_release.close_release(
                repo_root=fixture.repo, plan_path=fixture.plan_path, master_card_path=fixture.master_path,
                now="2026-08-31T00:00:00Z",
            )
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(sorted(path.name for path in fixture.archive.iterdir()),
                             sorted(close_release.ARCHIVE_NAMES))
            self.assertEqual(json.loads(fixture.master_path.read_text())["state"], "IDLE")
            self.assertEqual(sidecar_bytes, {
                task_id: (worktree / worker_card_sidecar.SIDECAR_NAME).read_bytes()
                for task_id, worktree in fixture.worktrees.items()
            })


class WorkerTransitionTests(unittest.TestCase):
    def transition(self, fixture: WorkerTransitionFixture, card: dict[str, object], **kwargs: object) -> dict[str, object]:
        worker_card_path = kwargs.pop("worker_card_path", fixture.worker_path)
        return worker_card_sidecar.transition_worker_card(
            repo_root=fixture.repo,
            plan_path=fixture.plan_path,
            master_card_path=fixture.master_path,
            task_id="worker-task",
            worker_card_path=worker_card_path,
            card=card,
            **kwargs,
        )

    def test_idle_active_awaiting_idle_lifecycle_uses_json_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            (fixture.worktree / "WORKTREE_TASK.md").write_text("human-only projection\n", encoding="utf-8")
            active = fixture.active()
            self.assertEqual(self.transition(fixture, active)["state"], "ACTIVE")
            awaiting = fixture.awaiting()
            self.assertEqual(self.transition(fixture, awaiting)["state"], "AWAITING_INTEGRATION")
            fixture.integrate()
            idle = fixture.idle_after_integration()
            result = worker_card_sidecar.transition_worker_card(
                repo_root=fixture.repo, plan_path=fixture.plan_path,
                master_card_path=fixture.master_path, worker_card_path=fixture.worker_path,
                card=idle,
            )
            self.assertEqual(result["state"], "IDLE")
            self.assertEqual((fixture.worktree / "WORKTREE_TASK.md").read_text(encoding="utf-8"),
                             "human-only projection\n")
            self.assertEqual(json.loads(fixture.worker_path.read_text())["last_task"]["integrated_as_sha"],
                             fixture.head)

    def test_missing_sidecar_only_allows_initial_active_and_equal_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            fixture.worker_path.unlink()
            active = fixture.active()
            first = self.transition(fixture, active)
            first_bytes = fixture.worker_path.read_bytes()
            second = self.transition(fixture, active)
            self.assertEqual(first, second)
            self.assertEqual(first_bytes, fixture.worker_path.read_bytes())

    def test_missing_sidecar_allows_only_current_revision_with_preserved_rework(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            old_digest = fixture.spec["task_spec_digest"]
            old_acceptance_digest = contracts.value_digest(fixture.spec["acceptance"])
            fixture.spec["task_spec_revision"] = 2
            fixture.spec["plan_revision"] = 2
            fixture.spec["acceptance"] = ["test revised Worker transition task"]
            fixture.spec["task_spec_digest"] = contracts.object_digest(fixture.spec, "task_spec_digest")
            write_json(fixture.spec_path, fixture.spec)
            fixture.plan = contracts.make_plan_for_spec(
                fixture.spec, "PUBLISHED", plan_revision=2, revision_decision="REVISE",
            )
            fixture.plan.update({
                "state_root": str(fixture.state),
                "task_specs_root": str(fixture.tasks_root),
                "release_task_id": "release-transition",
            })
            fixture.plan["plan_digest"] = contracts.object_digest(fixture.plan, "plan_digest")
            write_json(fixture.plan_path, fixture.plan)
            fixture.master = contracts.make_active_master_card(fixture.plan, str(fixture.plan_path))
            fixture.master["frozen_baseline_sha"] = fixture.baseline
            candidate = contracts.make_candidate_v2(
                head=fixture.head, plan_revision=2, plan_digest=fixture.plan["plan_digest"],
                stale_gates={"targeted-tests"},
            )
            candidate["release_task_id"] = fixture.plan["release_task_id"]
            contracts.refresh_candidate_inputs(candidate, refresh_evidence=True)
            fixture.master["candidate_evidence"] = candidate
            handoff = contracts.make_received_handoff()
            handoff.update({
                "state": "REWORK_REQUESTED",
                "task_id": fixture.spec["task_id"],
                "role": fixture.spec["owner_role"],
                "task_spec_revision": 1,
                "task_spec_digest": old_digest,
                "plan_revision": 1,
                "dispatch_wave": fixture.spec["dispatch_wave"],
                "source_thread_id": fixture.spec["source_thread_id"],
                "frozen_baseline_sha": fixture.spec["expected_head"],
                "authorization_envelope_digest": fixture.spec["authorization"]["envelope_digest"],
                "acceptance_digest": old_acceptance_digest,
                "worker_commit_sha": fixture.head,
                "integrated_as_sha": None,
            })
            fixture.master["worker_handoffs"] = [handoff]
            write_json(fixture.master_path, fixture.master)
            fixture.worker_path.unlink()
            result = self.transition(fixture, fixture.active())
            self.assertEqual(result["task_spec_revision"], 2)
            self.assertEqual(result["state"], "ACTIVE")

    def test_missing_prior_awaiting_is_rejected_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            fixture.worker_path.unlink()
            with self.assertRaises(worker_card_sidecar.SidecarError):
                self.transition(fixture, fixture.awaiting())
            self.assertFalse(fixture.worker_path.exists())

    def test_transition_rejects_stale_identity_wrong_path_and_same_state_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            self.transition(fixture, fixture.active())
            original = fixture.worker_path.read_bytes()

            stale = fixture.awaiting()
            stale["task_spec_digest"] = "sha256:" + "f" * 64
            with self.subTest(scenario="stale identity"), self.assertRaises(worker_card_sidecar.SidecarError):
                self.transition(fixture, stale)
            self.assertEqual(original, fixture.worker_path.read_bytes())

            with self.subTest(scenario="cross worktree path"), self.assertRaises(worker_card_sidecar.SidecarError):
                self.transition(fixture, fixture.awaiting(), worker_card_path=fixture.root / "other" / "WORKTREE_TASK.json")
            self.assertEqual(original, fixture.worker_path.read_bytes())

            same_state = fixture.active()
            same_state["record_revision"] = 3
            same_state["updated_at"] = "2026-01-01T00:02:00Z"
            with self.subTest(scenario="same state"), self.assertRaises(worker_card_sidecar.SidecarError):
                self.transition(fixture, same_state)
            self.assertEqual(original, fixture.worker_path.read_bytes())

    def test_transition_rejects_symlink_and_record_revision_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            self.transition(fixture, fixture.active())
            outside = fixture.root / "outside.json"
            outside.write_bytes(fixture.worker_path.read_bytes())
            fixture.worker_path.unlink()
            fixture.worker_path.symlink_to(outside)
            with self.subTest(scenario="sidecar symlink"), self.assertRaises(worker_card_sidecar.SidecarError):
                self.transition(fixture, fixture.awaiting())
            self.assertEqual(fixture.worker_path.read_bytes(), outside.read_bytes())

        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            self.transition(fixture, fixture.active())
            regressed = fixture.awaiting()
            regressed["record_revision"] = 1
            with self.assertRaises(worker_card_sidecar.SidecarError):
                self.transition(fixture, regressed)

    def test_bytes_changed_during_replace_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            self.transition(fixture, fixture.active())
            changed = b"raced bytes\n"
            original = worker_card_sidecar._replace_if_unchanged

            def race(path: Path, expected: bytes, data: bytes) -> bool:
                path.write_bytes(changed)
                return original(path, expected, data)

            with patch.object(worker_card_sidecar, "_replace_if_unchanged", side_effect=race):
                with self.assertRaises(worker_card_sidecar.SidecarError):
                    self.transition(fixture, fixture.awaiting())
            self.assertEqual(fixture.worker_path.read_bytes(), changed)

    def test_interrupted_replace_is_recoverable_by_equal_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            self.transition(fixture, fixture.active())
            awaiting = fixture.awaiting()
            expected = contracts.canonical_json(awaiting)
            replace = worker_card_sidecar.os.replace

            def interrupt(source: str, target: str) -> None:
                replace(source, target)
                raise worker_card_sidecar.SidecarError("simulated post-replace interruption")

            with patch.object(worker_card_sidecar.os, "replace", side_effect=interrupt):
                with self.assertRaises(worker_card_sidecar.SidecarError):
                    self.transition(fixture, awaiting)
            self.assertEqual(fixture.worker_path.read_bytes(), expected)
            self.assertEqual(self.transition(fixture, awaiting)["state"], "AWAITING_INTEGRATION")

    def test_existing_received_handoff_must_match_worker_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = WorkerTransitionFixture(Path(directory))
            self.transition(fixture, fixture.active())
            handoff = contracts.make_received_handoff()
            handoff.update({
                "task_id": fixture.spec["task_id"],
                "role": fixture.spec["owner_role"],
                "task_spec_revision": fixture.spec["task_spec_revision"],
                "task_spec_digest": fixture.spec["task_spec_digest"],
                "plan_revision": fixture.spec["plan_revision"],
                "dispatch_wave": fixture.spec["dispatch_wave"],
                "source_thread_id": fixture.spec["source_thread_id"],
                "frozen_baseline_sha": fixture.spec["expected_head"],
                "authorization_envelope_digest": fixture.spec["authorization"]["envelope_digest"],
                "acceptance_digest": contracts.value_digest(fixture.spec["acceptance"]),
                "worker_commit_sha": "a" * 40,
            })
            fixture.master["worker_handoffs"] = [handoff]
            fixture.master["record_revision"] += 1
            fixture.master["updated_at"] = "2026-01-01T00:02:00Z"
            write_json(fixture.master_path, fixture.master)
            with self.assertRaises(worker_card_sidecar.SidecarError):
                self.transition(fixture, fixture.awaiting())


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

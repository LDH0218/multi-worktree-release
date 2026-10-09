"""Real temporary Git operations and public Card CLI, not live conversation scheduling."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import validate_contracts as contracts
from test_close_release import WorkerTransitionFixture, run, write_json

ROOT = Path(__file__).resolve().parents[1]


def git_fixture(root):
    fixture = WorkerTransitionFixture(root)
    card = fixture.worker_path.read_bytes()
    fixture.worker_path.unlink()
    fixture.worktree.rmdir()
    with (fixture.repo / ".git/info/exclude").open("a") as out:
        out.write("\nWORKTREE_TASK.json\n")
    run(["git", "worktree", "add", "-q", "-b", fixture.spec["branch"],
         str(fixture.worktree), fixture.baseline], fixture.repo)
    fixture.worker_path.write_bytes(card)
    return fixture


def advance(fixture, state, sha=None, task_id=None):
    argv = [sys.executable, str(ROOT / "scripts/worker_card_sidecar.py"),
            "--repo-root", str(fixture.repo), "--skill-root", str(ROOT),
            "--plan", str(fixture.plan_path), "--master-card-json", str(fixture.master_path),
            "--task-id", task_id or fixture.spec["task_id"], "--advance", state]
    if sha is not None:
        argv += ["--worker-commit", sha]
    return subprocess.run(argv, text=True, capture_output=True,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=20)


class DeliveryPathsTests(unittest.TestCase):
    def test_generated_cards_complete_actual_git_lifecycle_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            f = git_fixture(Path(directory))
            result = advance(f, "ACTIVE")
            self.assertEqual(result.returncode, 0, result.stderr)
            card = json.loads(f.worker_path.read_text())
            self.assertEqual(card["authorization"], f.spec["authorization"])
            self.assertEqual(card["task_spec_digest"], f.spec["task_spec_digest"])
            (f.worktree / "src").mkdir()
            (f.worktree / "src/api.py").write_text("RESULT = 'actual worker result'\n")
            run(["git", "add", "src/api.py"], f.worktree)
            run(["git", "commit", "-qm", "worker result"], f.worktree)
            f.head = run(["git", "rev-parse", "HEAD"], f.worktree)
            result = advance(f, "AWAITING_INTEGRATION", f.head)
            self.assertEqual(result.returncode, 0, result.stderr)
            before = f.worker_path.read_bytes()
            self.assertEqual(advance(f, "AWAITING_INTEGRATION", f.head).returncode, 0)
            self.assertEqual(f.worker_path.read_bytes(), before)
            # The Master performs the actual integration, then records its exact mapping.
            run(["git", "cherry-pick", f.head], f.repo)
            integrated = run(["git", "rev-parse", "HEAD"], f.repo)
            f.integrate()
            f.master["worker_handoffs"][0]["integrated_as_sha"] = integrated
            write_json(f.master_path, f.master)
            result = advance(f, "IDLE")
            self.assertEqual(result.returncode, 0, result.stderr)
            last = json.loads(f.worker_path.read_text())["last_task"]
            self.assertEqual(last["worker_commit_sha"], f.head)
            self.assertEqual(last["integrated_as_sha"], integrated)
            before = f.worker_path.read_bytes()
            self.assertEqual(advance(f, "IDLE").returncode, 0)
            self.assertEqual(f.worker_path.read_bytes(), before)

    def test_wrong_head_task_dirty_tree_and_unaccepted_idle_do_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            f = git_fixture(Path(directory))
            before = f.worker_path.read_bytes()
            self.assertNotEqual(advance(f, "ACTIVE", task_id="wrong-task").returncode, 0)
            (f.worktree / "unexpected.txt").write_text("preserve me\n")
            self.assertNotEqual(advance(f, "ACTIVE").returncode, 0)
            self.assertEqual(f.worker_path.read_bytes(), before)
            (f.worktree / "unexpected.txt").unlink()
            run(["git", "commit", "--allow-empty", "-qm", "different HEAD"], f.worktree)
            self.assertNotEqual(advance(f, "ACTIVE").returncode, 0)
            self.assertEqual(f.worker_path.read_bytes(), before)
        with tempfile.TemporaryDirectory() as directory:
            f = git_fixture(Path(directory))
            self.assertEqual(advance(f, "ACTIVE").returncode, 0)
            before = f.worker_path.read_bytes()
            self.assertNotEqual(advance(f, "AWAITING_INTEGRATION", f.head).returncode, 0)
            self.assertEqual(f.worker_path.read_bytes(), before)
            self.assertNotEqual(advance(f, "IDLE").returncode, 0)
            self.assertEqual(f.worker_path.read_bytes(), before)

    def test_cancel_after_local_writer_exit_preserves_dirty_material_and_blocks_old_task(self):
        with tempfile.TemporaryDirectory() as directory:
            f = git_fixture(Path(directory))
            self.assertEqual(advance(f, "ACTIVE").returncode, 0)
            process = subprocess.Popen(
                [sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('worker draft\\n'); print('ready',flush=True); input()",
                 str(f.worktree / "draft.txt")], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                # Bounded communication is concrete process-exit evidence for this local test.
                _, error = process.communicate("stop\n", timeout=10)
                self.assertEqual(process.returncode, 0, error)
                draft = (f.worktree / "draft.txt").read_bytes()
                f.plan["tasks"][0]["dispatch_status"] = "CANCELLED"
                f.plan["tasks"][0]["revision_decision"] = "CANCELLED"
                f.plan["record_revision"] += 1
                f.plan["ready_wave"] = None
                f.plan["plan_digest"] = contracts.object_digest(f.plan, "plan_digest")
                f.master["dispatch_plan_digest"] = f.plan["plan_digest"]
                f.master["record_revision"] += 1
                write_json(f.plan_path, f.plan)
                write_json(f.master_path, f.master)
                result = advance(f, "IDLE")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(f.worker_path.read_text())["last_task"]["outcome"], "CANCELLED")
                before = f.worker_path.read_bytes()
                self.assertNotEqual(advance(f, "ACTIVE").returncode, 0)
                self.assertEqual(f.worker_path.read_bytes(), before)
                self.assertEqual((f.worktree / "draft.txt").read_bytes(), draft)
                run(["git", "cat-file", "-e", f.baseline + "^{commit}"], f.repo)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=10)

    def test_multiple_local_corrections_and_normal_push_without_release_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote, repo = root / "remote.git", root / "repo"
            repo.mkdir()
            run(["git", "init", "--bare", "-q", str(remote)], root)
            run(["git", "init", "-q", "-b", "main"], repo)
            run(["git", "config", "user.email", "fixture@example.invalid"], repo)
            run(["git", "config", "user.name", "Delivery Fixture"], repo)
            target = repo / "result.txt"
            results = []
            for value in ("bad-one", "bad-two", "correct"):
                target.write_text(value)
                result = subprocess.run([sys.executable, "-c",
                                         "from pathlib import Path; raise SystemExit(0 if Path('result.txt').read_text()=='correct' else 1)"], cwd=repo)
                results.append(result.returncode)
            self.assertEqual(results, [1, 1, 0])
            run(["git", "add", "result.txt"], repo)
            run(["git", "commit", "-qm", "bounded correction"], repo)
            run(["git", "remote", "add", "origin", str(remote)], repo)
            # This local bare target is authorized by this test; no network publication.
            run(["git", "push", "-q", "origin", "main"], repo)
            self.assertEqual(run(["git", "rev-parse", "HEAD"], repo),
                             run(["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"], root))
            self.assertFalse((repo / ".codex").exists())
            self.assertFalse((repo / "WORKTREE_TASK.json").exists())


if __name__ == "__main__":
    unittest.main()

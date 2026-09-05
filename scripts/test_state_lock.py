"""Process-level regressions for the cooperating state-root lock."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from state_lock import StateLockConflict, exclusive_state_lock


SCRIPT_DIR = Path(__file__).resolve().parent


def wait_for(path: Path, process: subprocess.Popen[str], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"lock holder exited early: {stdout!r} {stderr!r}")
        time.sleep(0.01)
    process.kill()
    stdout, stderr = process.communicate()
    raise AssertionError(f"timed out waiting for lock holder: {stdout!r} {stderr!r}")


def start_holder(state_root: Path, ready: Path, release: Path) -> subprocess.Popen[str]:
    code = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from state_lock import exclusive_state_lock\n"
        "root,ready,release=sys.argv[1:]\n"
        "with exclusive_state_lock(Path(root), timeout=5):\n"
        "    Path(ready).write_text('ready', encoding='utf-8')\n"
        "    while not Path(release).exists(): time.sleep(0.01)\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SCRIPT_DIR)
    return subprocess.Popen(
        [sys.executable, "-c", code, str(state_root), str(ready), str(release)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
    )


class StateLockProcessTests(unittest.TestCase):
    def test_competing_process_times_out_without_business_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"
            state_root.mkdir()
            business = root / "business.json"
            business.write_bytes(b"authoritative\n")
            ready = root / "ready"
            release = root / "release"
            holder = start_holder(state_root, ready, release)
            try:
                wait_for(ready, holder)
                with self.assertRaises(StateLockConflict):
                    with exclusive_state_lock(state_root, timeout=0.1):
                        raise AssertionError("the competing writer unexpectedly acquired the lock")
                self.assertEqual(business.read_bytes(), b"authoritative\n")
                self.assertEqual(
                    sorted(path.name for path in state_root.iterdir()),
                    [".mwr-state.lock"],
                )
                self.assertFalse((state_root / "history" / "releases").exists())
            finally:
                release.write_text("release", encoding="utf-8")
                stdout, stderr = holder.communicate(timeout=5)
                self.assertEqual(holder.returncode, 0, f"{stdout}\n{stderr}")
            self.assertTrue((state_root / ".mwr-state.lock").is_file())

    def test_process_exit_releases_lock_without_lock_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_root = root / "state"
            state_root.mkdir()
            ready = root / "ready"
            code = (
                "import os,sys\n"
                "from pathlib import Path\n"
                "from state_lock import exclusive_state_lock\n"
                "with exclusive_state_lock(Path(sys.argv[1]), timeout=5):\n"
                "    Path(sys.argv[2]).write_text('ready', encoding='utf-8')\n"
                "    os._exit(0)\n"
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(SCRIPT_DIR)
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(state_root), str(ready)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment,
            )
            wait_for(ready, process)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, f"{stdout}\n{stderr}")
            carrier = state_root / ".mwr-state.lock"
            self.assertTrue(carrier.is_file())
            with exclusive_state_lock(state_root, timeout=0.1):
                self.assertTrue(carrier.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Small process lock for cooperating multi-worktree state writers."""

from __future__ import annotations

import contextlib
import errno
import json
import os
import time
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported runtime is POSIX.
    fcntl = None  # type: ignore[assignment]


LOCK_FILENAME = ".mwr-state.lock"
MAX_WAIT_SECONDS = 5.0


class StateLockError(RuntimeError):
    """A state-root lock could not be established or released safely."""


class StateLockConflict(StateLockError):
    """Another cooperating writer held the state-root lock until timeout."""


def canonical_state_root(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise StateLockError("state_root must be absolute")
    try:
        canonical = path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise StateLockError(f"cannot canonicalize state_root: {error}") from error
    if not canonical.is_dir() or canonical.is_symlink():
        raise StateLockError(f"state_root is not a regular directory: {canonical}")
    return canonical


def lock_path(state_root: str | Path) -> Path:
    return canonical_state_root(state_root) / LOCK_FILENAME


def plan_state_root(plan_path: str | Path) -> Path:
    path = Path(plan_path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StateLockError(f"cannot read Plan state_root before locking: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("state_root"), str):
        raise StateLockError("Plan state_root is missing before locking")
    return canonical_state_root(value["state_root"])


def _try_lock(descriptor: int) -> bool:
    if fcntl is None:
        raise StateLockError("exclusive state locking requires the POSIX fcntl module")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise StateLockError(f"cannot acquire state-root lock: {error}") from error


@contextlib.contextmanager
def exclusive_state_lock(state_root: str | Path, *, timeout: float = MAX_WAIT_SECONDS
                         ) -> Iterator[Path]:
    """Hold one persistent lock carrier until the writer finishes read/validate/write/readback."""
    if timeout < 0 or timeout > MAX_WAIT_SECONDS:
        raise StateLockError(f"state-root lock timeout must be between 0 and {MAX_WAIT_SECONDS:g} seconds")
    root = canonical_state_root(state_root)
    carrier = root / LOCK_FILENAME
    if os.path.lexists(carrier) and (carrier.is_symlink() or not carrier.is_file()):
        raise StateLockError(f"state-root lock carrier is not a regular file: {carrier}")
    try:
        descriptor = os.open(str(carrier), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as error:
        raise StateLockError(f"cannot open state-root lock carrier {carrier}: {error}") from error

    acquired = False
    started = time.monotonic()
    try:
        while not _try_lock(descriptor):
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                raise StateLockConflict(
                    f"state-root lock busy after {timeout:g}s: {carrier}"
                )
            time.sleep(min(0.05, timeout - elapsed))
        acquired = True
        yield carrier
    finally:
        if acquired and fcntl is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError as error:
                raise StateLockError(f"cannot release state-root lock {carrier}: {error}") from error
        try:
            os.close(descriptor)
        except OSError as error:
            raise StateLockError(f"cannot close state-root lock carrier {carrier}: {error}") from error

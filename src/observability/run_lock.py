"""Phase 7 cross-process run lock for weekly_run + daily_upload.

Both entrypoints + manual invocations share a single lock file
(`data/.weekly_run.lock`) so they cannot overlap. The lock is a hard
fail (raises RunLockHeld) — not a queue. Callers either run cleanly
or exit with the lock_held outcome and a logs/alerts.md row.

Windows-only (msvcrt). The deployment is single-machine Windows; tests
run on Windows. msvcrt is imported inside the function so this module
loads cleanly on any platform — only the function fails on non-Windows.
"""

from __future__ import annotations

import errno
import os
import platform
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class RunLockHeld(Exception):
    """Raised when another process already holds the run lock."""


@contextmanager
def acquire_run_lock(lock_path: str | Path) -> Iterator[None]:
    """Hard-fail context manager. Raises RunLockHeld if another process
    holds the lock. On success, holds the lock for the with-block duration
    and releases on exit (including on exception inside the block).

    The lock file path is created if missing and left behind on release —
    deleting it would race the next acquirer. The msvcrt advisory byte
    lock is what actually serializes; the file is just a sentinel.
    """
    if platform.system() != "Windows":
        raise RuntimeError("run lock requires Windows (msvcrt); not supported on this platform")

    import msvcrt  # imported inside fn so module loads on non-Windows for collection.

    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    locked = False
    try:
        try:
            # Lock the first byte of the file. With LK_NBLCK this is non-blocking:
            # raises OSError immediately if another process has it.
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            locked = True
        except OSError as exc:
            # errno 13 (EACCES) or 33 (EDEADLK) — the lock is held by someone else.
            if exc.errno in (errno.EACCES, errno.EDEADLK, 13, 33):
                raise RunLockHeld(f"lock held: {lock_path}") from exc
            raise
        yield
    finally:
        if locked:
            try:
                # Seek to the start before unlocking — msvcrt.locking acts at the
                # current file position, and we may have advanced it via writes.
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass

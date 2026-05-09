"""Phase 7 tests for src.observability.run_lock.

Windows-only by deployment. Tests are skipped on non-Windows platforms.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

from src.observability.run_lock import RunLockHeld, acquire_run_lock

pytestmark = pytest.mark.skipif(
    platform.system() != "Windows",
    reason="run lock requires Windows (msvcrt)",
)


def test_acquire_releases_on_normal_exit(tmp_path):
    lock = tmp_path / "lock"
    with acquire_run_lock(lock):
        pass
    # Second acquire works because the first released the byte lock.
    with acquire_run_lock(lock):
        pass


def test_acquire_raises_when_held_by_another_fd(tmp_path):
    """A separate fd holding the byte lock blocks acquire_run_lock."""
    import msvcrt
    lock = tmp_path / "lock"
    fd = os.open(str(lock), os.O_CREAT | os.O_RDWR)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        with pytest.raises(RunLockHeld):
            with acquire_run_lock(lock):
                pass
    finally:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(fd)


def test_acquire_releases_on_exception_in_block(tmp_path):
    """Exception inside the with-block still releases the lock."""
    lock = tmp_path / "lock"
    with pytest.raises(RuntimeError, match="boom"):
        with acquire_run_lock(lock):
            raise RuntimeError("boom")
    # Acquire works again after the exception path released.
    with acquire_run_lock(lock):
        pass


def test_lock_file_created_if_missing(tmp_path):
    """First acquire creates the sentinel file under a missing parent dir."""
    lock = tmp_path / "subdir" / "data" / ".weekly_run.lock"
    assert not lock.exists()
    with acquire_run_lock(lock):
        assert lock.exists()
    # File is left behind on release (deletion would race the next acquirer).
    assert lock.exists()

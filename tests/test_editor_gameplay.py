"""Gameplay rotation: round-robin, cursor wrap, ffprobe-once, render-fail safety."""

from __future__ import annotations

from pathlib import Path

from src.editor import gameplay as gp
from src.editor import ffmpeg_runner
from src.state import Repository, connect, initialize_schema


def _make_repo(tmp_path: Path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _make_pool(tmp_path: Path) -> tuple[list[str], Path]:
    """Three real (empty) files so .exists() passes; ffprobe is monkeypatched."""
    pool_dir = tmp_path / "data" / "gameplay"
    pool_dir.mkdir(parents=True)
    files = ["data/gameplay/subway.mp4", "data/gameplay/minecraft.mp4", "data/gameplay/gta.mp4"]
    for f in files:
        (tmp_path / f).write_bytes(b"\x00")
    return files, tmp_path


def _patch_probe(monkeypatch, duration_s: float):
    calls = {"n": 0}

    def fake_probe(path):
        calls["n"] += 1
        return duration_s

    monkeypatch.setattr(ffmpeg_runner, "ffprobe_duration_seconds", fake_probe)
    return calls


# ---- round-robin ------------------------------------------------------------


def test_round_robin_pointer_0_1_2_0(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    pool, root = _make_pool(tmp_path)
    _patch_probe(monkeypatch, 600.0)

    visited: list[str] = []
    for _ in range(4):
        with repo.tx():
            res = gp.reserve_next_segment(repo, root, pool, clip_duration_s=30.0)
            assert res is not None
            visited.append(res.file_name)
            gp.commit_advance(repo, res)

    assert visited == [pool[0], pool[1], pool[2], pool[0]]


def test_cursor_advances_per_call(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    pool, root = _make_pool(tmp_path)
    _patch_probe(monkeypatch, 600.0)

    offsets_for_subway: list[float] = []
    for _ in range(4):  # four full pool rounds = 4 visits to subway? actually 4 / 3 = 2
        with repo.tx():
            res = gp.reserve_next_segment(repo, root, pool, clip_duration_s=30.0)
            assert res is not None
            if res.file_name == pool[0]:
                offsets_for_subway.append(res.offset_s)
            gp.commit_advance(repo, res)

    # First subway visit: offset 0; second: 30 (one full clip later).
    assert offsets_for_subway[0] == 0.0
    assert offsets_for_subway[1] == 30.0


# ---- cursor wrap ------------------------------------------------------------


def test_cursor_wraps_near_end_of_file(tmp_path, monkeypatch):
    """last_offset_s=595, file_duration=600, clip=30 -> wraps to 0."""
    repo = _make_repo(tmp_path)
    pool, root = _make_pool(tmp_path)
    _patch_probe(monkeypatch, 600.0)

    # Pre-seed cursor at 595s on subway.
    repo.advance_gameplay_state(
        file_name=pool[0],
        new_offset_s=595.0,
        file_duration_s=600.0,
        new_pointer_index=0,
    )

    res = gp.reserve_next_segment(repo, root, pool, clip_duration_s=30.0)
    assert res is not None
    assert res.file_name == pool[0]
    assert res.offset_s == 0.0  # wrapped


# ---- ffprobe-once -----------------------------------------------------------


def test_ffprobe_called_once_per_file(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    pool, root = _make_pool(tmp_path)
    calls = _patch_probe(monkeypatch, 600.0)

    # First reserve probes subway and commits the duration.
    with repo.tx():
        res = gp.reserve_next_segment(repo, root, pool, clip_duration_s=30.0)
        assert res is not None
        gp.commit_advance(repo, res)

    after_first = calls["n"]
    assert after_first == 1

    # After full round-robin, come back to subway: should NOT probe again.
    for _ in range(3):  # advance through minecraft, gta, back to subway
        with repo.tx():
            res = gp.reserve_next_segment(repo, root, pool, clip_duration_s=30.0)
            assert res is not None
            gp.commit_advance(repo, res)

    # Probed once for each of the 3 files (1 + 2 more = 3 total). subway should NOT re-probe.
    assert calls["n"] == 3


# ---- render-fail safety -----------------------------------------------------


def test_render_failure_does_not_advance(tmp_path, monkeypatch):
    """If commit_advance is never called, pointer + cursor stay put."""
    repo = _make_repo(tmp_path)
    pool, root = _make_pool(tmp_path)
    _patch_probe(monkeypatch, 600.0)

    pointer_before = repo.read_gameplay_pointer()
    offset_before, _ = repo.read_gameplay_cursor(pool[0])

    res = gp.reserve_next_segment(repo, root, pool, clip_duration_s=30.0)
    assert res is not None
    # Render "failed" — do NOT call commit_advance.

    pointer_after = repo.read_gameplay_pointer()
    offset_after, _ = repo.read_gameplay_cursor(pool[0])
    assert pointer_after == pointer_before
    assert offset_after == offset_before


# ---- edge cases -------------------------------------------------------------


def test_empty_pool_returns_none(tmp_path):
    repo = _make_repo(tmp_path)
    res = gp.reserve_next_segment(repo, tmp_path, [], clip_duration_s=30.0)
    assert res is None


def test_missing_gameplay_file_returns_none(tmp_path):
    repo = _make_repo(tmp_path)
    res = gp.reserve_next_segment(
        repo, tmp_path, ["data/gameplay/nonexistent.mp4"], clip_duration_s=30.0
    )
    assert res is None


def test_unprobeable_file_returns_none(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    pool, root = _make_pool(tmp_path)
    monkeypatch.setattr(ffmpeg_runner, "ffprobe_duration_seconds", lambda p: None)
    res = gp.reserve_next_segment(repo, root, pool, clip_duration_s=30.0)
    assert res is None

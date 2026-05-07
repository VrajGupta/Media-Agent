"""Pivot.3 background music: track listing + deterministic clip-track pick."""

from __future__ import annotations

from pathlib import Path

from src.editor.music import (
    SUPPORTED_EXTENSIONS,
    list_music_tracks,
    pick_track_for_clip,
    resolve_music_for_clip,
)

from tests.conftest import StubConfig


def _seed(music_dir: Path, names: list[str]) -> list[Path]:
    music_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for n in names:
        p = music_dir / n
        p.write_bytes(b"\x00" * 16)
        paths.append(p)
    return paths


def test_list_music_tracks_filters_by_extension(tmp_path):
    cfg = StubConfig(tmp_path)
    music_dir = Path(cfg.paths.music_dir)
    _seed(music_dir, ["a.mp3", "b.m4a", "c.wav", "d.txt", "e.png"])
    tracks = list_music_tracks(cfg)
    names = [p.name for p in tracks]
    assert "d.txt" not in names
    assert "e.png" not in names
    assert names == ["a.mp3", "b.m4a", "c.wav"]   # alphabetical


def test_list_music_tracks_supports_all_advertised_extensions(tmp_path):
    cfg = StubConfig(tmp_path)
    music_dir = Path(cfg.paths.music_dir)
    fake_files = [f"track{i}{ext}" for i, ext in enumerate(SUPPORTED_EXTENSIONS)]
    _seed(music_dir, fake_files)
    tracks = list_music_tracks(cfg)
    assert len(tracks) == len(SUPPORTED_EXTENSIONS)


def test_list_music_tracks_empty_when_dir_missing(tmp_path):
    cfg = StubConfig(tmp_path)
    Path(cfg.paths.music_dir).rmdir()  # remove the auto-created dir
    tracks = list_music_tracks(cfg)
    assert tracks == []


def test_list_music_tracks_empty_dir_returns_empty(tmp_path):
    cfg = StubConfig(tmp_path)
    tracks = list_music_tracks(cfg)
    assert tracks == []


def test_pick_track_deterministic_for_same_clip_id(tmp_path):
    cfg = StubConfig(tmp_path)
    music_dir = Path(cfg.paths.music_dir)
    paths = _seed(music_dir, ["a.mp3", "b.mp3", "c.mp3", "d.mp3"])
    pick1 = pick_track_for_clip("clip_xyz_30_60", paths)
    pick2 = pick_track_for_clip("clip_xyz_30_60", paths)
    assert pick1 == pick2
    assert pick1 in paths


def test_pick_track_distributes_across_pool(tmp_path):
    """Different clip_ids should not all collapse to the same track."""
    cfg = StubConfig(tmp_path)
    music_dir = Path(cfg.paths.music_dir)
    paths = _seed(music_dir, [f"track_{i}.mp3" for i in range(4)])
    selections = {pick_track_for_clip(f"clip_{i}_30_60", paths) for i in range(40)}
    # 40 clip_ids → expect at least 3 of 4 tracks hit (uniform-ish via SHA1).
    assert len(selections) >= 3


def test_pick_track_empty_pool_returns_none():
    assert pick_track_for_clip("any_clip", []) is None


def test_resolve_music_for_clip_returns_none_when_disabled(tmp_path):
    cfg = StubConfig(tmp_path, music_enabled=False)
    music_dir = Path(cfg.paths.music_dir)
    _seed(music_dir, ["a.mp3"])
    assert resolve_music_for_clip(cfg, "any_clip") is None


def test_resolve_music_for_clip_returns_track_when_enabled(tmp_path):
    cfg = StubConfig(tmp_path, music_enabled=True)
    music_dir = Path(cfg.paths.music_dir)
    paths = _seed(music_dir, ["a.mp3", "b.mp3"])
    picked = resolve_music_for_clip(cfg, "any_clip")
    assert picked in paths


def test_resolve_music_for_clip_returns_none_when_pool_empty(tmp_path):
    cfg = StubConfig(tmp_path, music_enabled=True)
    assert resolve_music_for_clip(cfg, "any_clip") is None

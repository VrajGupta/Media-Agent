"""Issue 11 — render_from_script --reuse-shots/--order mode.

Tests exercise public helpers through their interfaces only.
No GPU, no OpenRouter, no real ffmpeg required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.render_from_script import (
    parse_shot_order,
    resolve_reused_shot_paths,
    stable_clip_id,
)


def test_parse_shot_order_splits_comma_separated_indices():
    assert parse_shot_order("3,2,1,0") == [3, 2, 1, 0]


def test_parse_shot_order_rejects_wrong_count():
    with pytest.raises(ValueError, match="exactly 4"):
        parse_shot_order("3,2,1", expected_count=4)


def test_resolve_reused_shot_paths_returns_paths_in_play_order(tmp_path: Path):
    script_id = "7cb41305-b39b-4cc2-855b-067e03549d25"
    prefix = script_id[:8]
    for i in range(4):
        (tmp_path / f"{prefix}_shot_{i}.mp4").write_bytes(b"fake")

    paths = resolve_reused_shot_paths(tmp_path, script_id, [3, 2, 1, 0])

    assert [p.name for p in paths] == [
        f"{prefix}_shot_3.mp4",
        f"{prefix}_shot_2.mp4",
        f"{prefix}_shot_1.mp4",
        f"{prefix}_shot_0.mp4",
    ]


def test_resolve_reused_shot_paths_raises_when_file_missing(tmp_path: Path):
    script_id = "7cb41305-b39b-4cc2-855b-067e03549d25"
    prefix = script_id[:8]
    (tmp_path / f"{prefix}_shot_0.mp4").write_bytes(b"fake")

    with pytest.raises(FileNotFoundError, match="shot_3"):
        resolve_reused_shot_paths(tmp_path, script_id, [3, 0])


def test_stable_clip_id_is_deterministic_for_script_id():
    script_id = "7cb41305-b39b-4cc2-855b-067e03549d25"
    assert stable_clip_id(script_id) == stable_clip_id(script_id)
    assert len(stable_clip_id(script_id)) == 36

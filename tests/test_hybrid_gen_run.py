"""P7.5 — assembler crossfade argv + hybrid routing helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.assembler.build import build_assembler_argv, write_concat_list
from src.gen_run import count_ai_video_shots, _generate_clip


def _base_args(tmp_path):
    shots = [tmp_path / f"shot_{i:02d}.mp4" for i in range(2)]
    for p in shots:
        p.write_bytes(b"x")
    concat_list = tmp_path / "concat.txt"
    write_concat_list(shots, concat_list)
    narration = tmp_path / "narration.mp3"
    narration.write_bytes(b"x")
    output = tmp_path / "out.mp4"
    return concat_list, narration, output, shots


def test_crossfade_disabled_matches_concat_demuxer_argv(tmp_path):
    concat_list, narration, output, _ = _base_args(tmp_path)
    baseline = build_assembler_argv(
        concat_list, narration, output, total_duration_s=8.0,
        crossfade_enabled=False,
    )
    regression = build_assembler_argv(
        concat_list, narration, output, total_duration_s=8.0,
        crossfade_enabled=False,
        shot_paths=None,
    )
    assert baseline == regression


def test_crossfade_enabled_emits_xfade(tmp_path):
    concat_list, narration, output, shots = _base_args(tmp_path)
    argv = build_assembler_argv(
        concat_list,
        narration,
        output,
        total_duration_s=7.75,
        shot_paths=shots,
        crossfade_enabled=True,
        crossfade_duration_s=0.25,
        shot_durations_s=[4.0, 4.0],
    )
    fg = " ".join(argv)
    assert "xfade" in fg
    assert "duration=0.25" in fg


def test_count_ai_video_shots_only_counts_ai_video():
    shots = [
        {"kind": "real_image", "entity": "logo"},
        {"kind": "ai_video", "prompt": "broll"},
        {"kind": "ai_video", "prompt": "broll2"},
    ]
    assert count_ai_video_shots(shots) == 2


def test_generate_clip_routes_only_ai_video_to_kling(tmp_path):
    from tests.test_gen_run import _GenStubConfig, _hybrid_script

    cfg = _GenStubConfig(tmp_path)
    script = _hybrid_script("s1", "Hybrid")
    fake_shot = tmp_path / "ai.mp4"
    fake_shot.write_bytes(b"x")
    real_shot = tmp_path / "real.mp4"
    real_shot.write_bytes(b"x")

    def _fake_ffmpeg(argv, output_path):
        output_path.write_bytes(b"assembled")
        return MagicMock(returncode=0, output_size_bytes=100)

    with patch("src.gen_run.generate_shots", return_value=[fake_shot, fake_shot]) as p_gen, \
         patch("src.gen_run._render_real_image_shot", return_value=real_shot) as p_kb, \
         patch("src.gen_run.synthesize"), \
         patch("src.gen_run.align", return_value=[]), \
         patch("src.gen_run.write_line_ass_file"), \
         patch("src.gen_run.run_ffmpeg", side_effect=_fake_ffmpeg), \
         patch("src.gen_run.OpenRouterKlingClient"):
        out = _generate_clip(script, cfg, MagicMock(), openrouter_api_key="sk-test", dry_run=False)

    p_gen.assert_called_once()
    assert len(p_gen.call_args[0][0]) == 2
    assert p_kb.call_count == 2
    assert out is not None


def test_image_fetch_failure_skips_clip_without_crashing_batch(tmp_path):
    from src.gen_run import run_generation
    from tests.test_gen_run import _GenStubConfig, _hybrid_script, _new_repo
    from src.image_fetch.errors import ImageFetchError

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)
    scripts = [_hybrid_script("ok", "Good"), _hybrid_script("bad", "Bad")]
    calls = [0]

    def _clip_side_effect(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            raise ImageFetchError("no image")
        return tmp_path / "out.mp4"

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=scripts), \
         patch("src.policy_gate.run_all", return_value=[]), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()), \
         patch("src.gen_run._generate_clip", side_effect=_clip_side_effect):
        success, summary = run_generation(
            repo=repo, cfg=cfg, dry_run=False, openrouter_api_key="sk-test",
        )
    assert success is True
    assert summary["stages"]["generate_clips"]["count"] == 1

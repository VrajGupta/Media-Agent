"""Unit tests for scripter.shot_plan — licensed-only degrade (ADR-0003)."""

from __future__ import annotations

from src.scripter.shot_plan import resolve_shot_plan


def _hybrid_shots():
    return [
        {"kind": "real_image", "entity": "OpenAI logo", "duration_s": 4},
        {"kind": "ai_video", "prompt": "abstract data flow", "duration_s": 4},
        {"kind": "real_image", "entity": "RTX 5090", "duration_s": 4},
        {"kind": "ai_video", "prompt": "server room lights", "duration_s": 4},
    ]


def test_all_licensed_hits_leaves_shot_list_unchanged():
    shots = _hybrid_shots()
    probe_calls: list[tuple[str, str | None]] = []

    def probe(entity, query):
        probe_calls.append((entity, query))
        return True

    resolved, billable = resolve_shot_plan(shots, licensed_probe=probe)

    assert resolved == shots
    assert billable == 2
    assert len(probe_calls) == 2


def test_licensed_miss_degrades_real_image_to_ai_video():
    shots = _hybrid_shots()

    def probe(entity, _query):
        return entity != "RTX 5090"

    resolved, billable = resolve_shot_plan(shots, licensed_probe=probe)

    assert resolved[0]["kind"] == "real_image"
    assert resolved[1]["kind"] == "ai_video"
    assert resolved[2]["kind"] == "ai_video"
    assert "RTX 5090" in resolved[2]["prompt"]
    assert billable == 3


def test_generate_clip_resolves_shots_before_kling_submission(tmp_path):
    from unittest.mock import MagicMock, patch

    from src.gen_run import _generate_clip
    from tests.test_gen_run import _GenStubConfig, _hybrid_script

    cfg = _GenStubConfig(tmp_path)
    script = _hybrid_script("s26", "Licensed degrade")
    fake_shot = tmp_path / "ai.mp4"
    fake_shot.write_bytes(b"x")
    real_shot = tmp_path / "real.mp4"
    real_shot.write_bytes(b"x")
    order: list[str] = []

    def _probe(entity, _query, _cfg):
        order.append(f"probe:{entity}")
        return entity != "RTX 5090"

    def _gen_shots(shots, *_args, **_kwargs):
        order.append(f"kling:{len(shots)}")
        return [fake_shot] * len(shots)

    def _ffmpeg(argv, output_path):
        output_path.write_bytes(b"x")
        return MagicMock(returncode=0, output_size_bytes=100)

    with patch("src.gen_run.probe_licensed_image", side_effect=_probe), \
         patch("src.gen_run.generate_shots", side_effect=_gen_shots), \
         patch("src.gen_run._render_real_image_shot", return_value=real_shot), \
         patch("src.gen_run.synthesize"), \
         patch("src.gen_run.align", return_value=[]), \
         patch("src.gen_run.write_line_ass_file"), \
         patch("src.gen_run.run_ffmpeg", side_effect=_ffmpeg), \
         patch("src.gen_run.OpenRouterKlingClient"):
        _generate_clip(script, cfg, MagicMock(), openrouter_api_key="sk-test", dry_run=False)

    assert order.index("probe:OpenAI logo") < order.index("kling:3")
    assert order.index("probe:RTX 5090") < order.index("kling:3")

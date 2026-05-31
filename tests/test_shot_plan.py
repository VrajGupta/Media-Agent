"""Unit tests for scripter.shot_plan — licensed-only degrade (ADR-0003)."""

from __future__ import annotations

from src.image_fetch.base import ImageAsset
from src.scripter.shot_plan import resolve_shot_plan


def _asset(entity: str) -> ImageAsset:
    return ImageAsset(
        path=f"/cache/{entity.replace(' ', '_')}.jpg",
        source="logo",
        license="CC0",
        source_url="https://example.com/logo",
        width=1080,
        height=1920,
    )


def _hybrid_shots():
    return [
        {"kind": "real_image", "entity": "OpenAI logo", "duration_s": 4},
        {"kind": "ai_video", "prompt": "abstract data flow", "duration_s": 4},
        {"kind": "real_image", "entity": "RTX 5090", "duration_s": 4},
        {"kind": "ai_video", "prompt": "server room lights", "duration_s": 4},
    ]


def test_all_licensed_hits_carry_resolved_assets():
    shots = _hybrid_shots()
    resolver_calls: list[tuple[str, str | None]] = []

    def resolver(entity, query):
        resolver_calls.append((entity, query))
        return _asset(entity)

    resolved, billable = resolve_shot_plan(shots, licensed_resolver=resolver)

    assert billable == 2
    assert len(resolver_calls) == 2
    assert resolved[0]["kind"] == "real_image"
    assert resolved[0]["image_asset"].path.endswith("OpenAI_logo.jpg")
    assert resolved[2]["kind"] == "real_image"
    assert resolved[2]["image_asset"].source == "logo"
    assert resolved[1]["kind"] == "ai_video"
    assert "image_asset" not in resolved[1]


def test_licensed_miss_degrades_real_image_to_ai_video():
    shots = _hybrid_shots()

    def resolver(entity, _query):
        return None if entity == "RTX 5090" else _asset(entity)

    resolved, billable = resolve_shot_plan(shots, licensed_resolver=resolver)

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

    def _resolver(entity, _query, *_rest):
        order.append(f"resolve:{entity}")
        return None if entity == "RTX 5090" else _asset(entity)

    def _gen_shots(shots, *_args, **_kwargs):
        order.append(f"kling:{len(shots)}")
        return [fake_shot] * len(shots)

    def _ffmpeg(argv, output_path):
        output_path.write_bytes(b"x")
        return MagicMock(returncode=0, output_size_bytes=100)

    with patch("src.gen_run.resolve_licensed_image", side_effect=_resolver), \
         patch("src.gen_run.generate_shots", side_effect=_gen_shots), \
         patch("src.gen_run._render_real_image_shot", return_value=real_shot) as p_kb, \
         patch("src.gen_run.synthesize"), \
         patch("src.gen_run.align", return_value=[]), \
         patch("src.gen_run.write_line_ass_file"), \
         patch("src.gen_run.run_ffmpeg", side_effect=_ffmpeg), \
         patch("src.gen_run.OpenRouterKlingClient"):
        _generate_clip(script, cfg, MagicMock(), openrouter_api_key="sk-test", dry_run=False)

    assert order.index("resolve:OpenAI logo") < order.index("kling:3")
    assert order.index("resolve:RTX 5090") < order.index("kling:3")
    assert p_kb.call_count == 1
    assert p_kb.call_args[0][0]["image_asset"].source == "logo"


def test_render_reuses_cached_asset_without_second_fetch(tmp_path):
    from unittest.mock import MagicMock, patch

    from src.gen_run import _generate_clip
    from tests.test_gen_run import _GenStubConfig, _hybrid_script

    cfg = _GenStubConfig(tmp_path)
    script = _hybrid_script("s27", "Cached asset")
    fake_shot = tmp_path / "ai.mp4"
    fake_shot.write_bytes(b"x")
    real_shot = tmp_path / "real.mp4"
    real_shot.write_bytes(b"x")
    resolved = [
        {**script["shots"][0], "image_asset": _asset("OpenAI logo")},
        script["shots"][1],
        {**script["shots"][2], "image_asset": _asset("RTX 5090")},
        script["shots"][3],
    ]

    def _ffmpeg(argv, output_path):
        output_path.write_bytes(b"x")
        return MagicMock(returncode=0, output_size_bytes=100)

    with patch("src.gen_run.fetch_image") as p_fetch, \
         patch("src.gen_run.generate_shots", return_value=[fake_shot, fake_shot]), \
         patch("src.gen_run._render_real_image_shot", return_value=real_shot) as p_kb, \
         patch("src.gen_run.synthesize"), \
         patch("src.gen_run.align", return_value=[]), \
         patch("src.gen_run.write_line_ass_file"), \
         patch("src.gen_run.run_ffmpeg", side_effect=_ffmpeg), \
         patch("src.gen_run.OpenRouterKlingClient"):
        _generate_clip(
            script, cfg, MagicMock(),
            openrouter_api_key="sk-test",
            dry_run=False,
            resolved_shots=resolved,
        )

    p_fetch.assert_not_called()
    assert all("image_asset" in call.args[0] for call in p_kb.call_args_list)

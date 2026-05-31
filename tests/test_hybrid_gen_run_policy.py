"""Issue 35/37 — hybrid gen_run resolver + pre-billing policy tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.image_fetch.base import ImageAsset
from src.policy_gate.evaluator import PolicyVerdict


def _asset(entity: str) -> ImageAsset:
    return ImageAsset(
        path=f"/cache/{entity.replace(' ', '_')}.jpg",
        source="logo",
        license="CC0",
        source_url="https://example.com/logo",
        width=1080,
        height=1920,
    )


def test_four_ai_video_shots_rejected_before_billing(tmp_path):
    from src.gen_run import run_generation
    from tests.test_gen_run import _GenStubConfig, _hybrid_script, _new_repo

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)
    cfg.ai_gen.per_clip_cost_cents_max = 250
    script = _hybrid_script("all-ai", "All AI")

    def _resolver(_entity, _query, *_rest):
        return None

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=[script]), \
         patch("src.gen_run.evaluate_clip_policy", return_value=PolicyVerdict(passed=True)), \
         patch("src.gen_run.resolve_licensed_image", side_effect=_resolver), \
         patch("src.gen_run.generate_shots") as p_gen, \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()):
        success, summary = run_generation(
            repo=repo, cfg=cfg, dry_run=False, openrouter_api_key="sk-test",
        )

    assert success is True
    p_gen.assert_not_called()
    assert summary["stages"]["generate_clips"]["count"] == 0


def test_policy_violation_skips_script_without_kling(tmp_path):
    from src.gen_run import run_generation
    from tests.test_gen_run import _GenStubConfig, _hybrid_script, _new_repo

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)
    scripts = [_hybrid_script("bad", "Bad"), _hybrid_script("good", "Good")]
    verdicts = {
        "bad": PolicyVerdict(passed=False, failed_check="banlist", failed_value="badword"),
        "good": PolicyVerdict(passed=True),
    }

    def _policy(_cfg, narration, title, **_kw):
        key = "bad" if "Bad" in title else "good"
        return verdicts[key]

    fake_shot = Path(tmp_path) / "shot.mp4"
    fake_shot.write_bytes(b"x")

    def _ffmpeg(_argv, output_path):
        output_path.write_bytes(b"x")
        return MagicMock(returncode=0, output_size_bytes=100)

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=scripts), \
         patch("src.gen_run.evaluate_clip_policy", side_effect=_policy), \
         patch("src.gen_run.resolve_licensed_image", side_effect=lambda e, q, cfg=None: _asset(e)), \
         patch("src.gen_run.generate_shots", return_value=[fake_shot, fake_shot]) as p_gen, \
         patch("src.gen_run._render_real_image_shot", return_value=fake_shot), \
         patch("src.gen_run.synthesize"), \
         patch("src.gen_run.align", return_value=[]), \
         patch("src.gen_run.write_line_ass_file"), \
         patch("src.gen_run.run_ffmpeg", side_effect=_ffmpeg), \
         patch("src.gen_run.OpenRouterKlingClient") as p_client, \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()):
        success, summary = run_generation(
            repo=repo, cfg=cfg, dry_run=False, openrouter_api_key="sk-test",
        )

    assert success is True
    assert p_client.call_count == 1
    assert p_gen.call_count == 1
    assert summary["stages"]["generate_clips"]["count"] == 1


def test_resolve_shot_plan_called_once_per_script(tmp_path):
    from src.gen_run import run_generation
    from tests.test_gen_run import _GenStubConfig, _hybrid_script, _new_repo

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)
    script = _hybrid_script("once", "Once")
    fake_shot = Path(tmp_path) / "shot.mp4"
    fake_shot.write_bytes(b"x")
    resolve_calls = {"n": 0}

    real_resolve = __import__("src.scripter.shot_plan", fromlist=["resolve_shot_plan"]).resolve_shot_plan

    def _counting_resolve(*args, **kwargs):
        resolve_calls["n"] += 1
        return real_resolve(*args, **kwargs)

    def _ffmpeg(_argv, output_path):
        output_path.write_bytes(b"x")
        return MagicMock(returncode=0, output_size_bytes=100)

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=[script]), \
         patch("src.gen_run.evaluate_clip_policy", return_value=PolicyVerdict(passed=True)), \
         patch("src.gen_run.resolve_licensed_image", side_effect=lambda e, q, cfg=None: _asset(e)), \
         patch("src.gen_run.resolve_shot_plan", side_effect=_counting_resolve) as p_resolve, \
         patch("src.gen_run.generate_shots", return_value=[fake_shot, fake_shot]), \
         patch("src.gen_run._render_real_image_shot", return_value=fake_shot), \
         patch("src.gen_run.synthesize"), \
         patch("src.gen_run.align", return_value=[]), \
         patch("src.gen_run.write_line_ass_file"), \
         patch("src.gen_run.run_ffmpeg", side_effect=_ffmpeg), \
         patch("src.gen_run.OpenRouterKlingClient"), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()):
        run_generation(repo=repo, cfg=cfg, dry_run=False, openrouter_api_key="sk-test")

    assert p_resolve.call_count == 1

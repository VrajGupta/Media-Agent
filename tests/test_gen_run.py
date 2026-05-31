"""gen_run orchestrator tests — pipeline + run row + alerts.

Mocks every stage so tests exercise orchestration logic without
invoking Kling, Whisper, Edge TTS, ffmpeg, Ollama, or any network.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.policy_gate.evaluator import PolicyVerdict
from src.state import Repository, connect, initialize_schema


class _AiGenStub:
    model = "kwaivgi/kling-v3.0-std"
    per_clip_cost_cents_max = 350
    daily_spend_cents_ceiling = 500
    max_concurrent = 2
    shot_duration_s = 5
    style_suffix = "editorial, 9:16"


class _NarrationStub:
    engine = "edge"
    kokoro_voice = "am_michael"
    voice = "en-US-GuyNeural"
    rate = "+10%"
    pitch = "+0Hz"


class _AssemblerStub:
    crossfade_enabled = False
    crossfade_duration_s = 0.25


class _ScripterStub:
    weekly_clip_target = 2
    style_suffix = ""
    quality_floor = 6.0
    candidate_pool_size = 4
    categories = ["tech"]
    narration_word_count_min = 30
    narration_word_count_max = 50
    banned_tokens: list[str] = []
    retry_on_failure = 1


class _ImageFetchStub:
    sources = ["logo", "wikimedia", "openverse", "web"]
    min_resolution = 512
    max_candidates_per_source = 5
    web_fallback_enabled = True
    living_person_patterns = ["portrait of", "photo of"]


class _Paths:
    def __init__(self, tmp_path):
        logs = Path(tmp_path) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        self.logs_dir = str(logs)
        self.state_db = str(Path(tmp_path) / "state.db")
        self.pending_dir = str(Path(tmp_path) / "output" / "pending")
        self.rejected_dir = str(Path(tmp_path) / "output" / "rejected")
        self.images_dir = str(Path(tmp_path) / "data" / "images")


class _GenStubConfig:
    def __init__(self, tmp_path):
        self.project_root = Path(tmp_path)
        self.paths = _Paths(tmp_path)
        self.ai_gen = _AiGenStub()
        self.narration = _NarrationStub()
        self.assembler = _AssemblerStub()
        self.image_fetch = _ImageFetchStub()
        self.scripter = _ScripterStub()
        self.clips_per_day = 2
        self.days_per_run = 7
        self.upload_slots = ["09:00", "17:00"]
        self.timezone = "Asia/Singapore"
        self.human_review = True
        self.output_resolution = [1080, 1920]
        self.ollama_model = "qwen2.5:3b-instruct"
        self.output_fps = 30
        self.nvenc_preset = "p5"
        self.nvenc_cq = 23
        self.loudness_target_lufs = -14.0
        self.music_volume_db = -15.0
        self.blurred_bg_sigma = 20
        self.ken_burns_zoom_rate = 0.0015

    def abs_path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.project_root / p)


def _hybrid_script(script_id: str, title: str) -> dict:
    return {
        "script_id": script_id,
        "title": title,
        "narration": "n" * 35,
        "shots": [
            {"kind": "real_image", "entity": "OpenAI logo", "duration_s": 4},
            {"kind": "ai_video", "prompt": "abstract data flow", "duration_s": 4},
            {"kind": "real_image", "entity": "RTX 5090", "duration_s": 4},
            {"kind": "ai_video", "prompt": "server room lights", "duration_s": 4},
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_repo(tmp_path) -> Repository:
    db = Path(tmp_path) / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _all_stages_patched():
    return [
        patch("src.gen_run.fetch_unscripted_topics", return_value=[]),
        patch("src.gen_run.run_stage_a", return_value=[]),
        patch("src.gen_run.run_stage_b", return_value=[]),
        patch("src.gen_run.run_stage_c", return_value=[]),
        patch("src.quality_screen.run_all", return_value=[]),
        patch("src.slot_planner.run_all", return_value=[]),
        patch("src.retention.run_all", return_value=MagicMock()),
    ]


# ---------------------------------------------------------------------------
# Tracer bullet
# ---------------------------------------------------------------------------


def test_run_generation_returns_success_tuple(tmp_path):
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    patches = _all_stages_patched()
    for p in patches:
        p.start()
    try:
        success, summary = run_generation(repo=repo, cfg=cfg, dry_run=True)
    finally:
        for p in patches:
            p.stop()

    assert success is True
    assert isinstance(summary, dict)


# ---------------------------------------------------------------------------
# Stage calls
# ---------------------------------------------------------------------------


def test_calls_fetch_unscripted_topics(tmp_path):
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]) as p_ti, \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=[]), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()):
        run_generation(repo=repo, cfg=cfg, dry_run=True)

    p_ti.assert_called_once_with(cfg, repo, dry_run=True)


def test_calls_batch_stages(tmp_path):
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=[]), \
         patch("src.quality_screen.run_all", return_value=[]) as p_qs, \
         patch("src.slot_planner.run_all", return_value=[]) as p_sp, \
         patch("src.retention.run_all", return_value=MagicMock()) as p_ret:
        run_generation(repo=repo, cfg=cfg, dry_run=True)

    p_qs.assert_called_once()
    p_sp.assert_called_once()
    p_ret.assert_called_once()


def test_generate_shots_called_once_per_script(tmp_path):
    """generate_shots invoked once for each script selected by scripter_c."""
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    fake_scripts = [
        _hybrid_script("aaa", "T1"),
        _hybrid_script("bbb", "T2"),
    ]

    fake_shot = Path(tmp_path) / "shot_00.mp4"
    fake_shot.write_bytes(b"fake")

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=fake_scripts), \
         patch("src.gen_run.evaluate_clip_policy", return_value=PolicyVerdict(passed=True)), \
         patch("src.gen_run.resolve_licensed_image", return_value=MagicMock(path=str(tmp_path / "img.jpg"), source="logo", license="CC0", source_url="https://x", width=1080, height=1920)), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()), \
         patch("src.gen_run.fetch_image") as p_fetch, \
         patch("src.gen_run._render_real_image_shot", return_value=fake_shot), \
         patch("src.gen_run.generate_shots", return_value=[fake_shot]) as p_gen, \
         patch("src.gen_run.synthesize") as p_synth, \
         patch("src.gen_run.align", return_value=[]) as p_align, \
         patch("src.gen_run.write_line_ass_file") as p_ass, \
         patch("src.gen_run.run_ffmpeg", return_value=MagicMock(returncode=0, output_size_bytes=1024)) as p_ffmpeg, \
         patch("src.gen_run.OpenRouterKlingClient") as p_client:
        run_generation(repo=repo, cfg=cfg, dry_run=False,
                       openrouter_api_key="sk-test")

    assert p_gen.call_count == 2
    assert p_fetch.call_count == 0


def test_dry_run_skips_generate_shots_and_synthesize(tmp_path):
    """Under --dry-run, Kling and Edge TTS are never invoked."""
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    fake_scripts = [
        _hybrid_script("aaa", "T1"),
    ]

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=fake_scripts), \
         patch("src.gen_run.evaluate_clip_policy", return_value=PolicyVerdict(passed=True)), \
         patch("src.gen_run.resolve_licensed_image", return_value=MagicMock(path=str(tmp_path / "img.jpg"), source="logo", license="CC0", source_url="https://x", width=1080, height=1920)), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()), \
         patch("src.gen_run.generate_shots") as p_gen, \
         patch("src.gen_run.synthesize") as p_synth:
        success, _ = run_generation(repo=repo, cfg=cfg, dry_run=True)

    assert success is True
    p_gen.assert_not_called()
    p_synth.assert_not_called()


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_stage_failure_halts_and_records_error(tmp_path):
    """If quality_screen raises, generate_shots is not called and DB records success=0."""
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    fake_scripts = [
        {"script_id": "aaa", "title": "T1", "narration": "n1", "shots": []},
    ]

    with patch("src.gen_run.fetch_unscripted_topics", return_value=[]), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=fake_scripts), \
         patch("src.gen_run.evaluate_clip_policy", return_value=PolicyVerdict(passed=True)), \
         patch("src.gen_run.resolve_licensed_image", return_value=None), \
         patch("src.quality_screen.run_all", side_effect=RuntimeError("screen boom")), \
         patch("src.slot_planner.run_all") as p_sp, \
         patch("src.retention.run_all") as p_ret, \
         patch("src.gen_run.generate_shots") as p_gen:
        with pytest.raises(RuntimeError, match="screen boom"):
            run_generation(repo=repo, cfg=cfg, dry_run=True)

    p_gen.assert_not_called()
    p_sp.assert_not_called()

    row = repo.conn.execute(
        "SELECT success, summary_json FROM runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["success"] == 0
    parsed = json.loads(row["summary_json"])
    assert "RuntimeError" in parsed["error"]
    assert "screen boom" in parsed["error"]

    alerts = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "gen_run_failed" in alerts


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def test_run_row_written_with_kind_generation(tmp_path):
    """DB runs row has kind='generation' and success=1 on happy path."""
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    patches = _all_stages_patched()
    for p in patches:
        p.start()
    try:
        run_generation(repo=repo, cfg=cfg, dry_run=True)
    finally:
        for p in patches:
            p.stop()

    row = repo.conn.execute(
        "SELECT kind, success, summary_json FROM runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert row["kind"] == "generation"
    assert row["success"] == 1
    parsed = json.loads(row["summary_json"])
    assert "stages" in parsed


def test_success_alert_written(tmp_path):
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    patches = _all_stages_patched()
    for p in patches:
        p.start()
    try:
        run_generation(repo=repo, cfg=cfg, dry_run=True)
    finally:
        for p in patches:
            p.stop()

    alerts = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "gen_run_finished" in alerts


def test_runs_md_appended_on_success(tmp_path):
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    patches = _all_stages_patched()
    for p in patches:
        p.start()
    try:
        run_generation(repo=repo, cfg=cfg, dry_run=True)
    finally:
        for p in patches:
            p.stop()

    runs_md = (Path(cfg.paths.logs_dir) / "runs.md").read_text()
    assert "# Runs" in runs_md
    assert "| generation |" in runs_md
    assert "true" in runs_md


def test_runs_md_appended_on_failure(tmp_path):
    from src.gen_run import run_generation

    repo = _new_repo(tmp_path)
    cfg = _GenStubConfig(tmp_path)

    with patch("src.gen_run.fetch_unscripted_topics", side_effect=RuntimeError("ingest down")), \
         patch("src.gen_run.run_stage_a", return_value=[]), \
         patch("src.gen_run.run_stage_b", return_value=[]), \
         patch("src.gen_run.run_stage_c", return_value=[]), \
         patch("src.quality_screen.run_all", return_value=[]), \
         patch("src.slot_planner.run_all", return_value=[]), \
         patch("src.retention.run_all", return_value=MagicMock()):
        with pytest.raises(RuntimeError):
            run_generation(repo=repo, cfg=cfg, dry_run=True)

    runs_md = (Path(cfg.paths.logs_dir) / "runs.md").read_text()
    assert "| generation |" in runs_md
    assert "false" in runs_md
    assert "RuntimeError" in runs_md

"""P4 — Config: Pivot.6 sub-models and dead-field removal.

Tests that verify:
1. AiGenConfig, ScripterConfig, NarrationConfig, SubtitlesConfig, ComplianceConfig exist as importable classes
2. These sub-models are fields on Config
3. Retention gains Pivot.6 TTL fields (ai_gen_shots, narration, scripts)
4. Dead legacy discovery/download/lang_detect/selector/render fields are gone
5. config.yaml round-trips through the new model without error
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config_loader.loader import (
    AiGenConfig,
    ComplianceConfig,
    Config,
    NarrationConfig,
    ScripterConfig,
    SubtitlesConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# Minimal valid Pivot.6 config dict
# ---------------------------------------------------------------------------


def _minimal_config(**overrides) -> dict:
    base: dict = {
        "clips_per_day": 4,
        "days_per_run": 7,
        "upload_slots": ["09:00"],
        "timezone": "Asia/Singapore",
        "ollama_model": "qwen2.5:3b-instruct",
        "whisper_model": "large-v3",
        "whisper_compute_type": "int8_float16",
        "whisper_device": "cuda",
        "human_review": True,
        "banlist": [],
        "hook_sanity_min_score": 3,
        "profanity_max_score": 5,
        "dedup_lookback_days": 90,
        "phash_min_hamming": 8,
        "loudness_target_lufs": -14.0,
        "nvenc_preset": "p5",
        "nvenc_cq": 23,
        "output_resolution": [1080, 1920],
        "youtube_quota_daily_units": 10000,
        "youtube_quota_ceiling_units": 9000,
        "videos_insert_unit_cost": 1600,
        "retention": {
            "output_post_upload": 7,
            "rejected_clips": 30,
            "dup_hashes": 90,
            "quota_usage": 90,
            "vacuum_every_days": 30,
            "ai_gen_shots": 7,
            "narration": 14,
            "scripts": 90,
        },
        "paths": {
            "state_db": "data/state.db",
            "pending_dir": "output/pending",
            "approved_dir": "output/approved",
            "rejected_dir": "output/rejected",
            "dry_run_dir": "output/dry_run",
            "logs_dir": "logs",
            "oauth_token": "data/oauth_token.json",
            "client_secrets": "data/client_secret.json",
        },
        "ai_gen": {
            "model": "kwaivgi/kling-v3.0-std",
            "per_clip_cost_cents_max": 50,
            "daily_spend_cents_ceiling": 1000,
            "max_concurrent": 2,
            "shots_per_clip_min": 4,
            "shots_per_clip_max": 6,
            "shot_duration_s": 5,
            "style_suffix": "3D animated, Pixar-shaded",
        },
        "scripter": {
            "topic_pool": ["weird_biology", "deep_sea"],
            "target_word_count": 80,
        },
        "narration": {
            "voice": "en-US-GuyNeural",
            "rate": "-8%",
            "pitch": "-2Hz",
        },
        "subtitles": {
            "position_x": 540,
            "position_y": 1500,
        },
        "compliance": {
            "ai_disclosure": True,
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Sub-model construction (standalone)
# ---------------------------------------------------------------------------


def test_ai_gen_config_fields():
    ai_gen = AiGenConfig(
        model="kwaivgi/kling-v3.0-std",
        per_clip_cost_cents_max=50,
        daily_spend_cents_ceiling=1000,
        max_concurrent=2,
        shots_per_clip_min=4,
        shots_per_clip_max=6,
        shot_duration_s=5,
        style_suffix="3D animated",
    )
    assert ai_gen.model == "kwaivgi/kling-v3.0-std"
    assert ai_gen.daily_spend_cents_ceiling == 1000
    assert ai_gen.shots_per_clip_min == 4


def test_scripter_config_fields():
    s = ScripterConfig(topic_pool=["weird_biology", "deep_sea"], target_word_count=80)
    assert "weird_biology" in s.topic_pool
    assert s.target_word_count == 80


def test_narration_config_fields():
    n = NarrationConfig(voice="en-US-GuyNeural", rate="-8%", pitch="-2Hz")
    assert n.voice == "en-US-GuyNeural"
    assert n.rate == "-8%"


def test_subtitles_config_fields():
    sub = SubtitlesConfig(position_x=540, position_y=1500)
    assert sub.position_x == 540
    assert sub.position_y == 1500


def test_compliance_config_fields():
    c = ComplianceConfig(ai_disclosure=True)
    assert c.ai_disclosure is True


# ---------------------------------------------------------------------------
# Sub-models attached to Config
# ---------------------------------------------------------------------------


def test_config_has_ai_gen_submodel():
    cfg = Config(**_minimal_config())
    assert isinstance(cfg.ai_gen, AiGenConfig)
    assert cfg.ai_gen.model == "kwaivgi/kling-v3.0-std"


def test_config_has_scripter_submodel():
    cfg = Config(**_minimal_config())
    assert isinstance(cfg.scripter, ScripterConfig)
    assert "weird_biology" in cfg.scripter.topic_pool


def test_config_has_narration_submodel():
    cfg = Config(**_minimal_config())
    assert isinstance(cfg.narration, NarrationConfig)
    assert cfg.narration.voice == "en-US-GuyNeural"


def test_config_has_subtitles_submodel():
    cfg = Config(**_minimal_config())
    assert isinstance(cfg.subtitles, SubtitlesConfig)
    assert cfg.subtitles.position_x == 540


def test_config_has_compliance_submodel():
    cfg = Config(**_minimal_config())
    assert isinstance(cfg.compliance, ComplianceConfig)
    assert cfg.compliance.ai_disclosure is True


# ---------------------------------------------------------------------------
# Retention: Pivot.6 TTL fields
# ---------------------------------------------------------------------------


def test_retention_has_ai_gen_shots_ttl():
    cfg = Config(**_minimal_config())
    assert cfg.retention.ai_gen_shots == 7


def test_retention_has_narration_ttl():
    cfg = Config(**_minimal_config())
    assert cfg.retention.narration == 14


def test_retention_has_scripts_ttl():
    cfg = Config(**_minimal_config())
    assert cfg.retention.scripts == 90


# ---------------------------------------------------------------------------
# Dead fields: no longer on Config
# ---------------------------------------------------------------------------


DEAD_DISCOVERY = (
    "keywords",
    "search_max_results_per_keyword",
    "discovery_max_inspected_per_keyword",
    "discovery_min_interval_hours",
    "min_source_duration_seconds",
    "recency_window_days",
    "virality_score_threshold",
    "search_list_unit_cost",
    "videos_list_unit_cost",
)
DEAD_DOWNLOAD = (
    "disk_soft_cap_gb",
    "disk_hard_cap_gb",
    "free_disk_safety_floor_gb",
    "download_min_height",
    "download_max_height",
    "download_estimated_bytes_per_video",
)
DEAD_LANG = ("lang_detect_threshold", "lang_detect_target_lang")
DEAD_SELECTOR = (
    "clip_min_seconds",
    "clip_max_seconds",
    "clips_per_video",
    "selector_max_candidates",
    "caption_min_confidence",
    "caption_prefer_manual",
)
DEAD_RENDER = (
    "render_strategy",
    "source_pane_aspect",
    "dialogue_reverb_enabled",
    "dialogue_reverb_aecho",
    "copyright_acknowledgement",
)


@pytest.mark.parametrize("field", DEAD_DISCOVERY + DEAD_DOWNLOAD + DEAD_LANG + DEAD_SELECTOR + DEAD_RENDER)
def test_dead_field_absent(field):
    cfg = Config(**_minimal_config())
    assert not hasattr(cfg, field), f"retired field {field!r} still on Config"


# ---------------------------------------------------------------------------
# config.yaml round-trip
# ---------------------------------------------------------------------------


def test_config_yaml_loads_cleanly():
    cfg = load_config(Path("config.yaml"))
    assert cfg.ai_gen.model == "kwaivgi/kling-v3.0-std"
    assert cfg.compliance.ai_disclosure is True
    assert cfg.retention.ai_gen_shots == 7
    assert cfg.clips_per_day == 1
    assert cfg.upload_weekdays == frozenset({1, 3})

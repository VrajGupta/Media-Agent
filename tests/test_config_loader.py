"""Pivot.0 — typed config validation for new render + caption + copyright fields.

Validates that:
- A valid blurred_bg config loads cleanly with the expected typed values.
- An invalid render_strategy enum is rejected at load time.
- caption_min_confidence outside [0.0, 1.0] is rejected.
- copyright_acknowledgement is optional and loads as None when absent.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from src.config_loader import load_config


def _minimal_config_dict() -> dict:
    """Smallest config payload that satisfies every required field in Config.

    Mirrors the live config.yaml shape post-pivot. Keep this in sync with
    src/config_loader/loader.py when fields are added.
    """
    return {
        "clips_per_day": 4,
        "days_per_run": 7,
        "upload_slots": ["09:00"],
        "timezone": "Asia/Singapore",
        "keywords": ["best movie scenes"],
        "search_max_results_per_keyword": 50,
        "min_source_duration_seconds": 300,
        "recency_window_days": 30,
        "virality_score_threshold": 1.0,
        "whisper_model": "large-v3",
        "whisper_compute_type": "int8_float16",
        "whisper_device": "cuda",
        "ollama_model": "qwen2.5:3b-instruct",
        "clip_min_seconds": 30,
        "clip_max_seconds": 60,
        "clips_per_video": 2,
        "human_review": True,
        "banlist": [],
        "hook_sanity_min_score": 3,
        "profanity_max_score": 5,
        "min_speech_density": 1.5,
        "min_word_confidence": 0.6,
        "dedup_lookback_days": 90,
        "phash_min_hamming": 8,
        "output_resolution": [1080, 1920],
        "render_strategy": "blurred_bg",
        "blurred_bg_sigma": 20,
        "source_pane_aspect": "16:9",
        "nvenc_preset": "p5",
        "nvenc_cq": 23,
        "loudness_target_lufs": -14.0,
        "copyright_acknowledgement": "movie_clips_v1",
        "youtube_quota_daily_units": 10000,
        "youtube_quota_ceiling_units": 9000,
        "videos_insert_unit_cost": 1600,
        "search_list_unit_cost": 100,
        "videos_list_unit_cost": 1,
        "retention": {
            "raw_video": 14,
            "transcript": 90,
            "output_post_upload": 7,
            "rejected_clips": 30,
            "dup_hashes": 90,
            "quota_usage": 90,
            "vacuum_every_days": 30,
        },
        "paths": {
            "state_db": "data/state.db",
            "raw_dir": "data/raw",
            "transcripts_dir": "data/transcripts",
            "pending_dir": "output/pending",
            "approved_dir": "output/approved",
            "rejected_dir": "output/rejected",
            "dry_run_dir": "output/dry_run",
            "logs_dir": "logs",
            "oauth_token": "data/oauth_token.json",
            "client_secrets": "data/client_secret.json",
        },
    }


def _write_yaml(tmp_path, payload: dict):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_valid_blurred_bg_config_loads(tmp_path):
    """A valid post-pivot config produces a Config object with the expected
    typed values for every new pivot field.
    """
    cfg_path = _write_yaml(tmp_path, _minimal_config_dict())
    cfg = load_config(cfg_path)
    assert cfg.render_strategy == "blurred_bg"
    assert cfg.blurred_bg_sigma == 20
    assert cfg.source_pane_aspect == "16:9"
    assert cfg.caption_min_confidence == 0.7  # default applied
    assert cfg.caption_prefer_manual is True   # default applied
    assert cfg.copyright_acknowledgement == "movie_clips_v1"


def test_invalid_render_strategy_raises(tmp_path):
    """Literal validation rejects unknown render strategies. This is a
    typo guard — accidentally writing 'blured_bg' must fail loudly at load
    time, not silently fall through to a missing-filter ffmpeg crash later.
    """
    payload = _minimal_config_dict()
    payload["render_strategy"] = "blured_bg"  # typo
    cfg_path = _write_yaml(tmp_path, payload)
    with pytest.raises(ValidationError) as exc_info:
        load_config(cfg_path)
    # Pydantic v2 surfaces the offending field name in the error message.
    assert "render_strategy" in str(exc_info.value)


def test_out_of_range_caption_confidence_raises(tmp_path):
    """caption_min_confidence is a probability in [0.0, 1.0]. Values outside
    that range are nonsensical (negative confidence; >1.0) and indicate a
    config error worth surfacing now.
    """
    payload = _minimal_config_dict()
    payload["caption_min_confidence"] = 1.5  # out of range
    cfg_path = _write_yaml(tmp_path, payload)
    with pytest.raises(ValidationError) as exc_info:
        load_config(cfg_path)
    assert "caption_min_confidence" in str(exc_info.value)


def test_missing_copyright_ack_loads_as_none(tmp_path):
    """copyright_acknowledgement is optional. A config without it loads
    successfully with the field set to None — bootstrap --check will surface
    this as a WARN line, but it must not gate normal operation.
    """
    payload = _minimal_config_dict()
    del payload["copyright_acknowledgement"]
    cfg_path = _write_yaml(tmp_path, payload)
    cfg = load_config(cfg_path)
    assert cfg.copyright_acknowledgement is None

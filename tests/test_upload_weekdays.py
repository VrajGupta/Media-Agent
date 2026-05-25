"""Issue 14 — upload_weekdays config parsing tests."""

from __future__ import annotations

import pytest

from src.config_loader.loader import Config
from src.config_loader.weekdays import parse_upload_weekdays


def test_parse_upload_weekdays_short_names_case_insensitive():
    assert parse_upload_weekdays(["Tue", "thu"]) == frozenset({1, 3})


def test_parse_upload_weekdays_full_names():
    assert parse_upload_weekdays(["Tuesday", "Thursday"]) == frozenset({1, 3})


def test_parse_upload_weekdays_integer_tokens():
    assert parse_upload_weekdays([1, 3]) == frozenset({1, 3})


def test_parse_upload_weekdays_empty_means_all_days():
    assert parse_upload_weekdays([]) == frozenset(range(7))
    assert parse_upload_weekdays(None) == frozenset(range(7))


def test_parse_upload_weekdays_rejects_unknown_token():
    with pytest.raises(ValueError, match="unrecognized weekday"):
        parse_upload_weekdays(["tuesday", "notaday"])


def test_config_coerces_upload_weekdays_from_yaml_list():
    cfg = Config(
        clips_per_day=1,
        days_per_run=7,
        upload_slots=["09:00"],
        timezone="Asia/Singapore",
        upload_weekdays=["tue", "thu"],
        whisper_model="large-v3",
        whisper_compute_type="int8_float16",
        whisper_device="cuda",
        ollama_model="qwen2.5:3b-instruct",
        human_review=True,
        banlist=[],
        hook_sanity_min_score=3,
        profanity_max_score=5,
        dedup_lookback_days=90,
        phash_min_hamming=8,
        output_resolution=[1080, 1920],
        nvenc_preset="p5",
        nvenc_cq=23,
        loudness_target_lufs=-14.0,
        youtube_quota_daily_units=10000,
        youtube_quota_ceiling_units=9000,
        videos_insert_unit_cost=1600,
        ai_gen={"per_clip_cost_cents_max": 350, "daily_spend_cents_ceiling": 500},
        retention={
            "output_post_upload": 7,
            "rejected_clips": 30,
            "dup_hashes": 90,
            "quota_usage": 90,
            "vacuum_every_days": 30,
        },
        paths={
            "state_db": "data/state.db",
            "pending_dir": "output/pending",
            "approved_dir": "output/approved",
            "rejected_dir": "output/rejected",
            "dry_run_dir": "output/dry_run",
            "logs_dir": "logs",
            "oauth_token": "data/oauth_token.json",
            "client_secrets": "data/client_secret.json",
        },
    )
    assert cfg.upload_weekdays == frozenset({1, 3})


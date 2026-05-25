"""P7.1 — Tagged shot schema: normalize_shots + validate_script extension.

Tests verify observable behavior through public seams only.
No Ollama, no network, no GPU.
"""

from __future__ import annotations

import pytest

from src.scripter.shots import normalize_shots
from src.scripter.runner import validate_script
from src.config_loader.loader import AiGenConfig
from types import SimpleNamespace


def _make_cfg(tmp_path, *, wc_min=30, wc_max=50):
    s = SimpleNamespace(
        narration_word_count_min=wc_min,
        narration_word_count_max=wc_max,
        banned_tokens=["<<placeholder>>", "I think", "as an AI"],
    )
    return SimpleNamespace(scripter=s)


def _good_narration():
    return (
        "OpenAI just dropped GPT-5 and it demolishes every reasoning benchmark "
        "by a staggering margin. Two hundred billion parameters trained on "
        "synthetic chain-of-thought data. Performance on math and code simply "
        "breaks the leaderboard. This changes everything we thought about AI."
    )


def test_normalize_shots_coerces_bare_string_to_ai_video():
    result = normalize_shots(["A glowing chip on a dark desk"])
    assert result == [
        {
            "kind": "ai_video",
            "prompt": "A glowing chip on a dark desk",
            "duration_s": 4,
        }
    ]


def test_normalize_shots_accepts_valid_real_image_dict():
    result = normalize_shots([
        {"kind": "real_image", "entity": "NVIDIA RTX 5090 graphics card"},
    ])
    assert result == [
        {
            "kind": "real_image",
            "entity": "NVIDIA RTX 5090 graphics card",
            "duration_s": 4,
        }
    ]


def test_normalize_shots_accepts_valid_ai_video_dict():
    result = normalize_shots([
        {"kind": "ai_video", "prompt": "Abstract blue data streams flowing through dark space"},
    ])
    assert result == [
        {
            "kind": "ai_video",
            "prompt": "Abstract blue data streams flowing through dark space",
            "duration_s": 4,
        }
    ]


def test_normalize_shots_raises_when_real_image_missing_entity():
    with pytest.raises(ValueError, match="entity"):
        normalize_shots([{"kind": "real_image"}])


def test_normalize_shots_raises_when_ai_video_missing_prompt():
    with pytest.raises(ValueError, match="prompt"):
        normalize_shots([{"kind": "ai_video"}])


def test_normalize_shots_raises_on_unknown_kind():
    with pytest.raises(ValueError, match="unknown shot kind"):
        normalize_shots([{"kind": "stock_footage", "entity": "something"}])


def test_validate_script_accepts_tagged_hybrid_shots(tmp_path):
    cfg = _make_cfg(tmp_path)
    script = {
        "title": "RTX 5090 Launches",
        "narration": _good_narration(),
        "shots": [
            {"kind": "real_image", "entity": "NVIDIA RTX 5090 graphics card"},
            {"kind": "ai_video", "prompt": "Abstract GPU architecture diagram glowing"},
            {"kind": "real_image", "entity": "OpenAI logo"},
            {"kind": "ai_video", "prompt": "Data center corridor with blue server lights"},
        ],
    }
    valid, reason = validate_script(script, cfg)
    assert valid is True
    assert reason is None


def test_validate_script_rejects_invalid_shot_kind(tmp_path):
    cfg = _make_cfg(tmp_path)
    script = {
        "title": "Bad Script",
        "narration": _good_narration(),
        "shots": [
            {"kind": "real_image", "entity": "RTX 5090"},
            {"kind": "real_image", "entity": "OpenAI logo"},
            {"kind": "real_image", "entity": "TSMC fab"},
            {"kind": "stock_footage", "entity": "something"},
        ],
    }
    valid, reason = validate_script(script, cfg)
    assert valid is False
    assert reason is not None


def test_legacy_string_shots_json_round_trips_through_normalize_shots():
    legacy = [
        "A glowing chip on a dark desk",
        "Engineer stares at holographic display",
        "Stock ticker spikes in red",
        "Phone screen glows with headline text",
    ]
    result = normalize_shots(legacy)
    assert len(result) == 4
    assert all(s["kind"] == "ai_video" for s in result)
    assert result[0]["prompt"] == legacy[0]


def test_ai_gen_config_accepts_one_to_three_ai_video_shots():
    ai_gen = AiGenConfig(
        model="kwaivgi/kling-v3.0-std",
        per_clip_cost_cents_max=50,
        daily_spend_cents_ceiling=1000,
        shots_per_clip_min=1,
        shots_per_clip_max=3,
    )
    assert ai_gen.shots_per_clip_min == 1
    assert ai_gen.shots_per_clip_max == 3

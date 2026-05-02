"""Mean Whisper word-confidence check."""

from __future__ import annotations

from src.quality_screen.confidence import mean_word_confidence, passes_confidence


def _w(prob: float | None) -> dict:
    out = {"start": 0.0, "end": 0.5, "word": "x"}
    if prob is not None:
        out["probability"] = prob
    return out


def test_mean_above_threshold_passes():
    words = [_w(0.95), _w(0.85), _w(0.80)]  # mean 0.866...
    ok, conf = passes_confidence(words, min_conf=0.6)
    assert ok is True
    assert abs(conf - (0.95 + 0.85 + 0.80) / 3) < 1e-9


def test_missing_probability_field_treated_as_zero():
    """Words missing `probability` default to 0.0 — mean is dragged down."""
    words = [_w(0.95), _w(None), _w(0.95)]   # mean 0.633
    ok_pass, conf_pass = passes_confidence(words, min_conf=0.6)
    assert ok_pass is True
    # Two missing tip the mean below 0.6:
    words2 = [_w(0.95), _w(None), _w(None)]  # mean 0.316
    ok_fail, conf_fail = passes_confidence(words2, min_conf=0.6)
    assert ok_fail is False
    assert conf_fail < 0.6


def test_empty_word_list_rejects():
    ok, conf = passes_confidence([], min_conf=0.6)
    assert ok is False
    assert conf == 0.0
    assert mean_word_confidence([]) == 0.0

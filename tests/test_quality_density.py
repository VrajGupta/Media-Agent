"""Speech-density check."""

from __future__ import annotations

from src.quality_screen.density import passes_density, speech_density


def _w(start: float, end: float, word: str) -> dict:
    return {"start": start, "end": end, "word": word}


def test_density_above_threshold_passes():
    # 60 words across 30 s → 2.0 wps; min 1.5 → pass
    words = [_w(i * 0.5, i * 0.5 + 0.4, f"w{i}") for i in range(60)]
    ok, density = passes_density(words, duration_s=30.0, min_density=1.5)
    assert ok is True
    assert abs(density - 2.0) < 1e-9


def test_density_below_threshold_rejects():
    # 30 words across 30 s → 1.0 wps; min 1.5 → reject
    words = [_w(i, i + 0.4, f"w{i}") for i in range(30)]
    ok, density = passes_density(words, duration_s=30.0, min_density=1.5)
    assert ok is False
    assert abs(density - 1.0) < 1e-9


def test_zero_words_or_zero_duration_rejects():
    ok, density = passes_density([], duration_s=30.0, min_density=1.5)
    assert ok is False
    assert density == 0.0
    # Defensive: nonpositive duration short-circuits to 0.0
    ok2, density2 = passes_density(
        [_w(0, 1, "x"), _w(1, 2, "y")], duration_s=0.0, min_density=1.5,
    )
    assert ok2 is False
    assert density2 == 0.0
    # Sanity: speech_density helper agrees.
    assert speech_density([], 30.0) == 0.0

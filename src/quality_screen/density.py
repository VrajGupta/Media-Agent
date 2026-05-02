"""Speech-density check (Phase 4.5).

Words inside the clip window divided by clip duration. The caller passes
clip-window-filtered words via src/transcripts/clip_text.py.
"""

from __future__ import annotations


def speech_density(window_words: list[dict], duration_s: float) -> float:
    """Words per second over the clip duration. Returns 0.0 for nonpositive
    duration so callers always reject in degenerate cases.
    """
    if duration_s <= 0:
        return 0.0
    return len(window_words) / duration_s


def passes_density(window_words: list[dict], duration_s: float, min_density: float) -> tuple[bool, float]:
    d = speech_density(window_words, duration_s)
    return (d >= min_density, d)

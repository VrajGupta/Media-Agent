"""Mean Whisper word-confidence check (Phase 4.5).

Words missing the `probability` field default to 0.0 — we treat their
absence as a reject signal (Whisper normally always populates it; missing
data means upstream broke). Empty word lists also produce 0.0.
"""

from __future__ import annotations


def mean_word_confidence(window_words: list[dict]) -> float:
    if not window_words:
        return 0.0
    total = 0.0
    for w in window_words:
        try:
            total += float(w.get("probability", 0.0))
        except (TypeError, ValueError):
            total += 0.0
    return total / len(window_words)


def passes_confidence(window_words: list[dict], min_conf: float) -> tuple[bool, float]:
    c = mean_word_confidence(window_words)
    return (c >= min_conf, c)

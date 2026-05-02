"""Profanity scoring via better-profanity.

We pre-load the default word list once at module import; better-profanity's
`load_censor_words()` is idempotent and side-effect-free for our purposes.

Score is `100 * censored_word_count / total_word_count` so it fits a 0..10
scale at typical thresholds (cfg.profanity_max_score=5 means roughly "≤5%
of words flagged"). Empty text scores 0.
"""

from __future__ import annotations

from better_profanity import profanity as _profanity

_profanity.load_censor_words()


def score_profanity(text: str) -> float:
    """Return a 0..100 percentage of words flagged as profane."""
    if not text or not text.strip():
        return 0.0
    words = text.split()
    if not words:
        return 0.0
    flagged = sum(1 for w in words if _profanity.contains_profanity(w))
    return 100.0 * flagged / len(words)


def is_profane(text: str, max_score: float) -> tuple[bool, float]:
    """Return (is_over_threshold, score). True iff score > max_score."""
    score = score_profanity(text)
    return (score > max_score, score)

"""better-profanity scoring."""

from __future__ import annotations

from src.policy_gate.profanity import is_profane, score_profanity


def test_clean_text_scores_zero():
    assert score_profanity("hello world this is fine") == 0.0


def test_profane_text_scores_above_zero_and_threshold_compares():
    text = "this is fucking nuts"
    score = score_profanity(text)
    assert score > 0.0
    assert is_profane(text, max_score=5.0)[0] is True


def test_score_proportional_to_word_count():
    """One profane word in many should score lower than one in a few."""
    short = "fuck"
    long_ = "fuck " + " ".join(["clean"] * 99)
    assert score_profanity(short) > score_profanity(long_)


def test_empty_text_scores_zero_and_passes_threshold():
    assert score_profanity("") == 0.0
    assert score_profanity("   \n  ") == 0.0
    over, score = is_profane("", max_score=5.0)
    assert over is False
    assert score == 0.0

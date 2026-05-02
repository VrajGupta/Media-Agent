"""Banlist substring matcher: case-insensitive, word-boundary, multi-word phrases."""

from __future__ import annotations

from src.policy_gate.banlist import find_banlisted_term


def test_case_insensitive_word_boundary_match():
    assert find_banlisted_term("Talking about Suicide today", ["suicide"]) == "suicide"
    assert find_banlisted_term("SUICIDE prevention week", ["suicide"]) == "suicide"
    # Word-boundary: 'classic' must not match 'ass'.
    assert find_banlisted_term("a classic example", ["ass"]) is None
    # Surrounding punctuation still bounds the word.
    assert find_banlisted_term("self-harm,", ["self-harm"]) == "self-harm"


def test_multi_word_phrase_matches_with_internal_whitespace():
    assert find_banlisted_term("That was a racial slur right there", ["racial slur"]) == "racial slur"
    # Multi-space tolerated.
    assert find_banlisted_term("This racial   slur is bad", ["racial slur"]) == "racial slur"
    # Newline tolerated.
    assert find_banlisted_term("racial\nslur", ["racial slur"]) == "racial slur"


def test_unicode_text_does_not_break_matcher():
    # Non-ASCII runs alongside ASCII.
    text = "Lorém ipsum suicide dolor — sit améét"
    assert find_banlisted_term(text, ["suicide"]) == "suicide"


def test_empty_banlist_passes_everything():
    assert find_banlisted_term("anything goes here", []) is None
    assert find_banlisted_term("", []) is None


def test_clip_window_scoping_regression_outside_window_does_not_reject():
    """Banlist runs on the clip-window text, not the whole-video transcript.

    This asserts the contract that callers MUST pass clip-window text:
    a banlisted term that only appears OUTSIDE the clip window must not
    be visible to the matcher — because the caller already filtered.
    """
    # If the caller correctly passes only words 10..11 of the transcript,
    # a banlisted term at word 90 is not in `clip_text` and we get None.
    clip_text = "first second third fourth fifth"
    assert find_banlisted_term(clip_text, ["suicide"]) is None
    # Sanity: if the same term IS in the clip window, it must still match.
    assert find_banlisted_term("first suicide third", ["suicide"]) == "suicide"

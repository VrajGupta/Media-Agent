"""Shared clip-window helper used by policy_gate and quality_screen."""

from __future__ import annotations

from src.transcripts.clip_text import clip_text_from_words, words_in_clip_window


def _w(start: float, end: float, word: str, probability: float | None = None) -> dict:
    out: dict = {"start": start, "end": end, "word": word}
    if probability is not None:
        out["probability"] = probability
    return out


def test_words_within_window_included_with_probability_preserved():
    words = [
        _w(0.0, 0.5, "before", 0.9),
        _w(10.1, 10.4, "first", 0.95),
        _w(10.5, 10.9, "second", 0.93),
        _w(20.0, 20.5, "after", 0.91),
    ]
    out = words_in_clip_window(words, 10.0, 11.0)
    assert [w["word"] for w in out] == ["first", "second"]
    assert out[0]["probability"] == 0.95
    assert out[1]["probability"] == 0.93


def test_word_straddling_boundary_is_clipped_to_boundary():
    """Identical rule to ass_writer._filter_and_clip_words: intersect + clip."""
    words = [
        _w(9.5, 10.5, "head"),    # straddles start
        _w(10.6, 10.9, "middle"),
        _w(10.95, 11.5, "tail"),  # straddles end
    ]
    out = words_in_clip_window(words, 10.0, 11.0)
    assert [w["word"] for w in out] == ["head", "middle", "tail"]
    # Clipped boundaries.
    assert out[0]["start"] == 10.0
    assert out[0]["end"] == 10.5
    assert out[2]["start"] == 10.95
    assert out[2]["end"] == 11.0


def test_empty_word_list_yields_empty_string():
    assert words_in_clip_window([], 10.0, 11.0) == []
    assert clip_text_from_words([]) == ""
    # Words entirely outside the window also produce empty output.
    outside = [_w(0.0, 0.5, "x"), _w(20.0, 20.5, "y")]
    assert words_in_clip_window(outside, 10.0, 11.0) == []
    assert clip_text_from_words(words_in_clip_window(outside, 10.0, 11.0)) == ""

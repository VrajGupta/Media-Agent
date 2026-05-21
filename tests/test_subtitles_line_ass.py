"""Tests for subtitles.line_ass — line-at-a-time ASS writer (Pivot.6)."""
from __future__ import annotations

from src.subtitles.line_ass import render_line_ass, wrap_words_to_lines


def _w(word: str, start: float, end: float) -> dict:
    return {"word": word, "start": start, "end": end}


def _dialogue_lines(ass: str) -> list[str]:
    return [l for l in ass.splitlines() if l.startswith("Dialogue:")]


# ---------------------------------------------------------------------------
# Tracer bullet — wrap_words_to_lines
# ---------------------------------------------------------------------------


def test_short_sentence_fits_on_one_line():
    words = [_w("Google", 0.0, 0.5), _w("dropped", 0.5, 1.0), _w("Gemma", 1.0, 1.5)]
    lines = wrap_words_to_lines(words)
    assert len(lines) == 1
    start, end, text = lines[0]
    assert start == 0.0
    assert end == 1.5
    assert text == "Google dropped Gemma"


# ---------------------------------------------------------------------------
# Line breaking
# ---------------------------------------------------------------------------


def test_long_sentence_each_line_within_28_chars():
    words = [_w(f"word{i}", float(i), float(i) + 0.5) for i in range(10)]
    lines = wrap_words_to_lines(words)
    for _, _, text in lines:
        assert len(text) <= 28, f"line too long: {text!r}"


def test_lines_break_at_word_boundaries():
    sentence = "Scientists built an AI that edits its own code at runtime"
    word_list = sentence.split()
    words = [_w(w, float(i) * 0.3, float(i) * 0.3 + 0.25) for i, w in enumerate(word_list)]
    lines = wrap_words_to_lines(words)
    reconstructed = " ".join(text for _, _, text in lines)
    assert reconstructed == sentence


def test_line_timing_spans_its_words():
    words = [_w("Hello", 1.0, 1.4), _w("world", 1.5, 1.9)]
    lines = wrap_words_to_lines(words)
    assert lines[0][0] == 1.0
    assert lines[0][1] == 1.9


def test_single_long_word_gets_its_own_line():
    words = [_w("supercalifragilisticexpialidocious", 0.0, 1.0)]
    lines = wrap_words_to_lines(words)
    assert len(lines) == 1
    assert lines[0][2] == "supercalifragilisticexpialidocious"


# ---------------------------------------------------------------------------
# render_line_ass — ASS output shape
# ---------------------------------------------------------------------------


def test_render_produces_valid_ass_header():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    assert "[Script Info]" in ass
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass


def test_render_dialogue_has_pos_540_1500():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    dlines = _dialogue_lines(ass)
    assert len(dlines) == 1
    assert r"\pos(540,1500)" in dlines[0]


def test_render_dialogue_has_fade_in():
    ass = render_line_ass([_w("hi", 0.0, 0.5)])
    dlines = _dialogue_lines(ass)
    assert r"\fad(100,0)" in dlines[0]


def test_render_empty_words_header_only():
    ass = render_line_ass([])
    assert "[Script Info]" in ass
    assert "Dialogue:" not in ass


def test_render_line_text_is_words_joined():
    ass = render_line_ass([_w("Hello", 0.0, 0.4), _w("world", 0.5, 0.9)])
    dlines = _dialogue_lines(ass)
    assert "Hello world" in dlines[0]


def test_render_timing_in_ass_format():
    ass = render_line_ass([_w("test", 2.0, 2.8)])
    dlines = _dialogue_lines(ass)
    parts = dlines[0].split(",")
    assert "0:00:02" in parts[1]


def test_render_non_overlapping_lines():
    words = [_w(f"word{i}", float(i) * 0.3, float(i) * 0.3 + 0.25) for i in range(20)]
    ass = render_line_ass(words)
    dlines = _dialogue_lines(ass)
    for i in range(len(dlines) - 1):
        end_i = dlines[i].split(",")[2]
        start_next = dlines[i + 1].split(",")[1]
        assert end_i <= start_next, f"line {i} ends {end_i!r} but line {i+1} starts {start_next!r}"


def test_render_escapes_ass_metacharacters():
    ass = render_line_ass([_w("hello{world}", 0.0, 0.5)])
    assert "hello{world}" not in ass
    assert r"hello\{world\}" in ass


def test_render_custom_max_chars_produces_more_lines():
    words = [_w(f"word{i}", float(i) * 0.3, float(i) * 0.3 + 0.25) for i in range(8)]
    lines_10 = wrap_words_to_lines(words, max_chars=10)
    lines_28 = wrap_words_to_lines(words, max_chars=28)
    assert len(lines_10) >= len(lines_28)

"""ASS subtitle writer tests — chunking, drift, escaping, clipping."""

from __future__ import annotations

from src.subtitles.ass_writer import (
    ANCHOR_X,
    ANCHOR_Y,
    ASS_HEADER,
    escape_ass_text,
    render_ass,
)


def _word(start: float, end: float, text: str, prob: float = 0.9):
    return {"start": start, "end": end, "word": text, "probability": prob}


# ---- single word ------------------------------------------------------------


def test_single_word_emits_one_dialogue_line():
    words = [_word(10.0, 11.0, "hello")]
    ass = render_ass(words, clip_start_s=10.0, clip_end_s=11.0)
    lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(lines) == 1
    assert "\\k100" in lines[0]   # 1.0s = 100 cs
    assert "hello" in lines[0]


# ---- non-overlapping 2-word chunks -----------------------------------------


def test_4_words_at_2wps_chunks_into_2_pairs_no_overlap():
    """4 words @ 2 wps over 2s window: chunks 1-2 and 3-4. Line 1 End == Line 2 Start."""
    words = [
        _word(0.0, 0.5, "a"),
        _word(0.5, 1.0, "b"),
        _word(1.0, 1.5, "c"),
        _word(1.5, 2.0, "d"),
    ]
    ass = render_ass(words, clip_start_s=0.0, clip_end_s=2.0)
    dlines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(dlines) == 2
    # Extract End of line1 and Start of line2.
    parts1 = dlines[0].split(",")
    parts2 = dlines[1].split(",")
    end1 = parts1[2]
    start2 = parts2[1]
    assert end1 == start2  # exact match — no overlap


def test_fast_speech_falls_back_to_one_word_chunks():
    """A pair spanning < 0.5s (rate > 4 wps) drops to 1-word chunks."""
    words = [
        _word(0.0, 0.1, "fast"),
        _word(0.1, 0.2, "talk"),
        _word(0.2, 0.3, "burst"),
    ]
    ass = render_ass(words, clip_start_s=0.0, clip_end_s=1.0)
    dlines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    # Expect 3 single-word lines (one per word) since rate is 10 wps.
    assert len(dlines) == 3


# ---- drift correction -------------------------------------------------------


def test_drift_under_50ms_over_60s_clip():
    """240 words evenly spaced across 60 s. Sum of \\kN cs should be within
    5 cs (50 ms) of 6000 cs total."""
    n = 240
    duration = 60.0
    step = duration / n
    words = [_word(i * step, (i + 1) * step, f"w{i}") for i in range(n)]
    ass = render_ass(words, clip_start_s=0.0, clip_end_s=60.0)
    # Sum every \kN occurrence.
    import re
    total_cs = sum(int(m) for m in re.findall(r"\\k(\d+)", ass))
    assert abs(total_cs - 6000) <= 5  # 50 ms tolerance


# ---- clipping to clip window -----------------------------------------------


def test_words_outside_clip_window_dropped():
    words = [
        _word(0.0, 1.0, "before"),
        _word(50.0, 51.0, "during"),
        _word(100.0, 101.0, "after"),
    ]
    ass = render_ass(words, clip_start_s=40.0, clip_end_s=60.0)
    assert "during" in ass
    assert "before" not in ass
    assert "after" not in ass


def test_word_straddling_boundary_clipped():
    """Word [9.5, 10.5] with clip [10.0, 20.0] should appear with start=0.0, end=0.5."""
    words = [_word(9.5, 10.5, "edge")]
    ass = render_ass(words, clip_start_s=10.0, clip_end_s=20.0)
    dlines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert len(dlines) == 1
    parts = dlines[0].split(",")
    assert parts[1] == "0:00:00.00"   # start at 0
    assert parts[2] == "0:00:00.50"   # end at 0.5s


# ---- escaping ---------------------------------------------------------------


def test_ass_text_escapes_braces_and_backslash():
    assert escape_ass_text("hello {world}") == "hello \\{world\\}"
    assert escape_ass_text("c:\\path") == "c:\\\\path"
    assert escape_ass_text("line\nbreak") == "line break"


def test_apostrophe_unchanged():
    """Apostrophe is NOT an ASS dialogue metacharacter; must NOT be escaped here.
    (Filter-path quoting is a separate concern, handled in ffmpeg_runner.)"""
    assert escape_ass_text("it's") == "it's"


# ---- empty / edge -----------------------------------------------------------


def test_empty_words_emits_header_only():
    ass = render_ass([], clip_start_s=0.0, clip_end_s=10.0)
    assert ass == ASS_HEADER


def test_header_includes_play_res_and_style():
    ass = render_ass([_word(0.0, 1.0, "hi")], clip_start_s=0.0, clip_end_s=1.0)
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Style: Karaoke,Impact,120" in ass
    # Alignment 5 (middle-center) is the 19th field of Style.
    style_line = next(l for l in ass.splitlines() if l.startswith("Style: Karaoke"))
    fields = style_line[len("Style: "):].split(",")
    # Field index 18 (0-based) is Alignment.
    assert fields[18] == "5"


# ---- Pivot.3: subtitle position moved to (540, 1500) -----------------------


def test_subtitle_anchor_is_pivot3_position():
    """Pivot.3 moved subtitle anchor from (540, 1340) to (540, 1500) so the
    text sits clear of the centered 1080x608 foreground band."""
    assert ANCHOR_X == 540
    assert ANCHOR_Y == 1500


def test_dialogue_pos_tag_uses_pivot3_position():
    """Render output includes \\pos(540,1500) on dialogue lines."""
    ass = render_ass([_word(0.0, 1.0, "hi")], clip_start_s=0.0, clip_end_s=1.0)
    assert "\\pos(540,1500)" in ass
    assert "\\pos(540,1340)" not in ass

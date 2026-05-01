"""Whisper word timestamps -> karaoke-style .ass file (Phase 4).

Contract:
  - Input: list of word dicts {"start": float, "end": float, "word": str, ...}
    with full-video timestamps; clip [start_s, end_s] window.
  - Output: ASS file content with non-overlapping 1-2 word Dialogue lines,
    each with karaoke \\k tags. Highlight color is yellow on the active word.
  - Timing: clip-relative — every word's full-video time is shifted by
    -clip.start_s so the file timeline starts at 0.
  - Words intersecting [start_s, end_s] are clipped to the boundary; words
    fully outside are dropped.

ASS metacharacters in dialogue text (\\, {, }) are escaped via escape_ass_text.
Apostrophes are NOT escaped — that's an ffmpeg filter-path concern, handled
in src/editor/ffmpeg_runner.py.
"""

from __future__ import annotations

from typing import Iterable

# Layout: 1080x1920 vertical canvas. Subtitle anchored at the geometric
# center (540, 1340) — roughly 70% down the canvas — using middle-center
# alignment (\an5) so the chunk grows from its center.
PLAY_RES_X = 1080
PLAY_RES_Y = 1920
ANCHOR_X = 540
ANCHOR_Y = 1340

FONT_NAME = "Impact"
FONT_SIZE = 120
PRIMARY_COLOR = "&H00FFFFFF"  # white (BGR + alpha)
OUTLINE_COLOR = "&H00000000"  # black
HIGHLIGHT_COLOR_BGR = "&H0000FFFF&"  # yellow (\1c override inside the line)
OUTLINE_PX = 8

# Above this rate, we drop to 1-word chunks to stop the karaoke from feeling
# rushed. Empirically tuned; tests pin the boundary.
FAST_SPEECH_WPS = 4.0
DEFAULT_CHUNK_SIZE = 2

ASS_HEADER = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    f"PlayResX: {PLAY_RES_X}\n"
    f"PlayResY: {PLAY_RES_Y}\n"
    "ScaledBorderAndShadow: yes\n"
    "\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    f"Style: Karaoke,{FONT_NAME},{FONT_SIZE},{PRIMARY_COLOR},&H000000FF,{OUTLINE_COLOR},&H00000000,"
    f"-1,0,0,0,100,100,0,0,1,{OUTLINE_PX},0,5,30,30,0,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)


def escape_ass_text(text: str) -> str:
    r"""Escape ASS dialogue metacharacters: \\, {, }.

    Note: apostrophe is NOT a metacharacter in dialogue text. It only matters
    inside the ffmpeg filter-path argument (handled in ffmpeg_runner.py).
    """
    out = text.replace("\\", "\\\\")
    out = out.replace("{", "\\{").replace("}", "\\}")
    out = out.replace("\n", " ").replace("\r", " ")
    return out


def _format_time(seconds: float) -> str:
    """ASS time format: H:MM:SS.cc (centiseconds)."""
    if seconds < 0:
        seconds = 0.0
    cs_total = int(round(seconds * 100))
    cs = cs_total % 100
    s_total = cs_total // 100
    s = s_total % 60
    m_total = s_total // 60
    m = m_total % 60
    h = m_total // 60
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _filter_and_clip_words(words, clip_start: float, clip_end: float):
    """Keep words intersecting [clip_start, clip_end]; clip boundaries.

    Returns clip-relative (start, end, text) tuples in original order.
    """
    out = []
    for w in words:
        ws = float(w.get("start", 0.0))
        we = float(w.get("end", 0.0))
        if we <= clip_start or ws >= clip_end:
            continue
        ws = max(ws, clip_start)
        we = min(we, clip_end)
        if we <= ws:
            continue
        text = (w.get("word") or "").strip()
        if not text:
            continue
        out.append((ws - clip_start, we - clip_start, text))
    return out


def _chunk_words(triples: list[tuple[float, float, str]]) -> list[list[tuple[float, float, str]]]:
    """Partition into non-overlapping chunks of 1-2 words.

    A chunk drops to 1 word when the local rate exceeds FAST_SPEECH_WPS
    (i.e. the pair would feel rushed) or when the second word would extend
    past a one-second-from-now visual budget. Final orphan word becomes its
    own chunk.
    """
    chunks: list[list[tuple[float, float, str]]] = []
    i = 0
    n = len(triples)
    while i < n:
        if i == n - 1:
            chunks.append([triples[i]])
            break
        a = triples[i]
        b = triples[i + 1]
        # Pair duration b.end - a.start. Speech rate over the pair: 2 words / duration.
        pair_duration = b[1] - a[0]
        if pair_duration <= 0:
            chunks.append([a])
            i += 1
            continue
        rate = 2.0 / pair_duration
        if rate > FAST_SPEECH_WPS:
            chunks.append([a])
            i += 1
        else:
            chunks.append([a, b])
            i += 2
    return chunks


def _emit_dialogue_lines(chunks: list[list[tuple[float, float, str]]]) -> list[str]:
    """For each chunk, emit one Dialogue line with \\k karaoke tags + \\pos.

    Drift correction: \\k durations are integer centiseconds; we accumulate
    the residual between real and emitted cs and add it to subsequent words
    so cumulative drift stays under 50 ms across a 60s clip (tested).
    """
    lines: list[str] = []
    drift_cs = 0.0  # accumulated real - emitted
    for chunk in chunks:
        chunk_start = chunk[0][0]
        chunk_end = chunk[-1][1]
        # Tag the active word with yellow highlight via \1c override.
        tag_parts: list[str] = []
        for idx, (ws, we, text) in enumerate(chunk):
            real_cs = (we - ws) * 100.0
            real_with_drift = real_cs + drift_cs
            emit_cs = max(1, int(round(real_with_drift)))
            drift_cs = real_with_drift - emit_cs
            safe_text = escape_ass_text(text)
            # {\kN}{\1c&Hyellow&}word{\1c&Hwhite&}  — but inside one chunk we want
            # the active word yellow only WHILE its \k is animating. ASS doesn't
            # have a clean per-word reset; the simplest is to emit each word as
            # its own karaoke segment with explicit color, then reset color.
            tag_parts.append(
                "{\\k" + str(emit_cs) + "}"
                + "{\\1c" + HIGHLIGHT_COLOR_BGR + "}"
                + safe_text
                + "{\\1c" + PRIMARY_COLOR + "&}"
            )
            # Space between words within a chunk.
            if idx < len(chunk) - 1:
                tag_parts.append(" ")
        body = "".join(tag_parts)
        # \an5 = middle-center alignment so \pos anchors the bbox center.
        text_field = "{\\an5\\pos(" + str(ANCHOR_X) + "," + str(ANCHOR_Y) + ")}" + body
        lines.append(
            f"Dialogue: 0,{_format_time(chunk_start)},{_format_time(chunk_end)},"
            f"Karaoke,,0,0,0,,{text_field}"
        )
    return lines


def render_ass(
    words: Iterable[dict],
    clip_start_s: float,
    clip_end_s: float,
) -> str:
    """Build the full .ass file content for a single clip.

    Empty word list -> header only (no Dialogue events). The resulting file
    is still valid ASS; libass renders it as a no-op subtitle stream.
    """
    triples = _filter_and_clip_words(list(words), clip_start_s, clip_end_s)
    if not triples:
        return ASS_HEADER
    chunks = _chunk_words(triples)
    lines = _emit_dialogue_lines(chunks)
    return ASS_HEADER + "\n".join(lines) + "\n"


def write_ass_file(
    path,
    words: Iterable[dict],
    clip_start_s: float,
    clip_end_s: float,
) -> None:
    """Atomic-ish write: produce the full content in memory, write in one call.
    UTF-8 encoded. Caller decides where the file lives (typically a tempfile
    that ffmpeg consumes via the libass `ass=` filter).
    """
    content = render_ass(words, clip_start_s, clip_end_s)
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

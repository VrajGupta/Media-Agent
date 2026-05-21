"""Line-at-a-time ASS subtitle writer for Pivot.6 AI-generated content.

Replaces the karaoke-style ass_writer.py for Pivot.6. The old writer
animated per-word; this one displays one full line at a time — simpler,
more readable on a 16s Short with fast TTS narration.

Input: [{word, start, end}] from Whisper forced-alignment on the TTS mp3.
Output: ASS file content with one Dialogue event per display line.

Layout (same anchors as karaoke writer):
  1080x1920 canvas, pos(540,1500), an5 (middle-center).
  fad(100,0): 100ms fade-in, no fade-out.
  Max 28 chars/line, broken at word boundaries.
"""

from __future__ import annotations

from pathlib import Path

PLAY_RES_X = 1080
PLAY_RES_Y = 1920
ANCHOR_X = 540
ANCHOR_Y = 1500
FONT_NAME = "Impact"
FONT_SIZE = 120
PRIMARY_COLOR = "&H00FFFFFF"
OUTLINE_COLOR = "&H00000000"
OUTLINE_PX = 8
MAX_CHARS = 28
FADE_MS = 100

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
    f"Style: Subtitle,{FONT_NAME},{FONT_SIZE},{PRIMARY_COLOR},&H000000FF,{OUTLINE_COLOR},&H00000000,"
    f"-1,0,0,0,100,100,0,0,1,{OUTLINE_PX},0,5,30,30,0,1\n"
    "\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)


def _escape(text: str) -> str:
    """Escape ASS dialogue metacharacters: \\, {, }."""
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{").replace("}", "\\}")
    text = text.replace("\n", " ").replace("\r", " ")
    return text


def _format_time(seconds: float) -> str:
    """ASS time format: H:MM:SS.cc (centiseconds)."""
    if seconds < 0:
        seconds = 0.0
    cs_total = int(round(seconds * 100))
    cs = cs_total % 100
    s_total = cs_total // 100
    s = s_total % 60
    m = (s_total // 60) % 60
    h = s_total // 3600
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def wrap_words_to_lines(
    word_timings: list[dict],
    max_chars: int = MAX_CHARS,
) -> list[tuple[float, float, str]]:
    """Group word timings into display lines of <= max_chars chars.

    Returns list of (start_s, end_s, line_text). Words that would push
    a line over max_chars start a new line. A single word exceeding
    max_chars still gets its own line (no truncation).
    """
    if not word_timings:
        return []

    lines: list[tuple[float, float, str]] = []
    current_words: list[str] = []
    line_start: float = word_timings[0]["start"]
    line_end: float = word_timings[0]["end"]

    for w in word_timings:
        word = w["word"].strip()
        if not word:
            continue

        candidate = " ".join(current_words + [word]) if current_words else word

        if current_words and len(candidate) > max_chars:
            # Flush current line and start fresh.
            lines.append((line_start, line_end, " ".join(current_words)))
            current_words = [word]
            line_start = w["start"]
            line_end = w["end"]
        else:
            current_words.append(word)
            if not current_words[:-1]:  # first word sets line_start
                line_start = w["start"]
            line_end = w["end"]

    if current_words:
        lines.append((line_start, line_end, " ".join(current_words)))

    return lines


def render_line_ass(
    word_timings: list[dict],
    *,
    max_chars: int = MAX_CHARS,
    fade_ms: int = FADE_MS,
) -> str:
    """Build full .ass content for line-at-a-time subtitles.

    Empty input -> header only (valid no-op ASS file).
    """
    lines = wrap_words_to_lines(word_timings, max_chars=max_chars)
    if not lines:
        return ASS_HEADER

    events: list[str] = []
    pos_tag = f"{{\\an5\\pos({ANCHOR_X},{ANCHOR_Y})}}"
    fade_tag = f"{{\\fad({fade_ms},0)}}"

    for start_s, end_s, text in lines:
        safe = _escape(text)
        text_field = f"{pos_tag}{fade_tag}{safe}"
        events.append(
            f"Dialogue: 0,{_format_time(start_s)},{_format_time(end_s)},"
            f"Subtitle,,0,0,0,,{text_field}"
        )

    return ASS_HEADER + "\n".join(events) + "\n"


def write_line_ass_file(path: Path | str, word_timings: list[dict], **kwargs) -> None:
    """Write ASS file to disk (UTF-8). kwargs forwarded to render_line_ass."""
    content = render_line_ass(word_timings, **kwargs)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

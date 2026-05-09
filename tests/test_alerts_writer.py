"""Phase 7 regression tests for alerts.py — UTF-8 round-trip + UTC timestamp."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.observability.alerts import append_alert


def test_append_creates_file_with_utf8_header(tmp_path):
    """Non-ASCII bytes in the message must round-trip byte-exact when read as UTF-8."""
    message = "movie clip rejected: title contains 日本語"
    append_alert(tmp_path, kind="rejected_policy", message=message)
    content = (tmp_path / "alerts.md").read_text(encoding="utf-8")
    assert "日本語" in content
    assert "# Alerts" in content
    assert "| timestamp_utc | kind | message |" in content


def test_timestamp_is_utc(tmp_path):
    """The formatted timestamp must reflect UTC, not local time."""
    fixed = datetime(2026, 5, 8, 12, 34, 56, tzinfo=timezone.utc)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    with patch("src.observability.alerts.datetime", _FrozenDatetime):
        append_alert(tmp_path, kind="weekly_run_finished", message="ok")
    content = (tmp_path / "alerts.md").read_text(encoding="utf-8")
    assert "2026-05-08 12:34:56" in content


def test_append_handles_pipes_and_newlines(tmp_path):
    """Pipes in the message are escaped; newlines collapse to a single space."""
    append_alert(tmp_path, kind="upload_failed", message="status=403 | reason=quota\nexceeded")
    content = (tmp_path / "alerts.md").read_text(encoding="utf-8")
    # Newline → space; pipe → \|
    assert "status=403 \\| reason=quota exceeded" in content
    # The header table separator is a literal "| --- | --- | --- |" so just
    # check the appended row didn't smuggle a raw pipe through.
    last_line = [l for l in content.splitlines() if "upload_failed" in l][0]
    assert "\\|" in last_line
    assert "\n" not in last_line  # already split by splitlines, but sanity-check

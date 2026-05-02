"""Final-duration check."""

from __future__ import annotations

from src.quality_screen import duration as duration_mod
from src.quality_screen.duration import passes_duration, probe_duration


def test_in_range_duration_passes():
    ok, d = passes_duration(33.6)
    assert ok is True
    assert d == 33.6


def test_under_25_seconds_rejects():
    ok, d = passes_duration(18.0)
    assert ok is False
    assert d == 18.0


def test_over_65_seconds_rejects():
    ok, d = passes_duration(80.0)
    assert ok is False
    assert d == 80.0


def test_probe_failure_returns_none(monkeypatch, tmp_path):
    """A None result is the foundational fail-soft signal — runner aborts."""
    fake = tmp_path / "x.mp4"
    fake.write_bytes(b"\x00")
    monkeypatch.setattr(
        duration_mod, "ffprobe_duration_seconds",
        lambda p: None,
    )
    assert probe_duration(fake) is None

"""Post-render loudness check.

Tests stub `subprocess.run` so no real ffmpeg is invoked. The two-tier
classification (pass / warn / reject) is exercised against the parsed input_i.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from src.quality_screen import loudness as loud_mod
from src.quality_screen.loudness import classify_loudness, measure_loudness


_LOUDNORM_OUTPUT = """\
ffmpeg version 8.1
... (some lines) ...
[Parsed_loudnorm @ 0xabcd]
{
    "input_i" : "{value}",
    "input_lra" : "12.0",
    "input_tp" : "-1.5",
    "target_offset" : "0.0"
}
"""


def _stub_run(stderr: str, returncode: int = 0):
    def fake_run(argv, **kwargs):
        assert argv[0] != "" and "-f" in argv and "null" in argv
        return SimpleNamespace(stdout="", stderr=stderr, returncode=returncode)
    return fake_run


def test_classify_loudness_three_tiers():
    target = -14.0
    assert classify_loudness(-14.0, target) == "pass"
    assert classify_loudness(-14.4, target) == "pass"
    assert classify_loudness(-15.2, target) == "warn"
    assert classify_loudness(-12.6, target) == "warn"
    assert classify_loudness(-10.0, target) == "reject"
    assert classify_loudness(-18.0, target) == "reject"


def test_measure_loudness_parses_input_i_from_stderr(monkeypatch, tmp_path):
    fake = tmp_path / "out.mp4"
    fake.write_bytes(b"\x00" * 4096)
    stderr = _LOUDNORM_OUTPUT.replace("{value}", "-14.20")
    monkeypatch.setattr(loud_mod.subprocess, "run", _stub_run(stderr))

    m = measure_loudness(fake)
    assert m.infrastructure_failed is False
    assert abs(m.input_i - (-14.20)) < 1e-9


def test_measure_loudness_subprocess_error_returns_infrastructure_failed(monkeypatch, tmp_path):
    fake = tmp_path / "out.mp4"
    fake.write_bytes(b"\x00")

    def fake_run(argv, **kwargs):
        raise subprocess.SubprocessError("crash")

    monkeypatch.setattr(loud_mod.subprocess, "run", fake_run)
    m = measure_loudness(fake)
    assert m.infrastructure_failed is True
    assert "crash" in m.reason


def test_measure_loudness_malformed_json_returns_infrastructure_failed(monkeypatch, tmp_path):
    """ffmpeg ran but stderr lacks the loudnorm JSON block."""
    fake = tmp_path / "out.mp4"
    fake.write_bytes(b"\x00")
    monkeypatch.setattr(
        loud_mod.subprocess, "run",
        _stub_run("frame=  100 fps= 99 q=22.0 size=  1024kB\n"),
    )
    m = measure_loudness(fake)
    assert m.infrastructure_failed is True
    assert "parse failed" in m.reason


def test_loudness_warn_band_classified_as_warn():
    """Verify the boundary value -15.2 LUFS lands in 'warn' (±0.5..±1.5)."""
    assert classify_loudness(-15.2, target_lufs=-14.0) == "warn"
    assert classify_loudness(-12.6, target_lufs=-14.0) == "warn"
    # Edge: exactly ±0.5 is a pass; exactly ±1.5 is a warn.
    assert classify_loudness(-14.5, target_lufs=-14.0) == "pass"
    assert classify_loudness(-15.5, target_lufs=-14.0) == "warn"


def test_loudness_reject_band():
    """Beyond ±1.5 LUFS rejects."""
    assert classify_loudness(-15.6, target_lufs=-14.0) == "reject"
    assert classify_loudness(-12.4, target_lufs=-14.0) == "reject"

"""Unit tests for narration.synth — no live Edge TTS calls."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.narration.synth import synthesize


def _mock_communicate(dest_bytes: bytes = b"fake-mp3"):
    """Returns a patched edge_tts.Communicate that writes fake bytes to dest."""
    async def _fake_save(path: str) -> None:
        Path(path).write_bytes(dest_bytes)

    mock_com = MagicMock()
    mock_com.save = _fake_save
    return mock_com


# ---------------------------------------------------------------------------
# Tracer bullet
# ---------------------------------------------------------------------------


def test_synthesize_returns_dest_path(tmp_path):
    dest = tmp_path / "narration.mp3"
    with patch("src.narration.synth.edge_tts.Communicate", return_value=_mock_communicate()):
        result = synthesize("Hello world", dest)
    assert result == dest


# ---------------------------------------------------------------------------
# Correct parameters
# ---------------------------------------------------------------------------


def test_synthesize_passes_correct_voice_rate_pitch(tmp_path):
    dest = tmp_path / "out.mp3"
    with patch("src.narration.synth.edge_tts.Communicate", return_value=_mock_communicate()) as MockCom:
        synthesize("test text", dest, voice="en-US-GuyNeural", rate="+10%", pitch="+0Hz")
    MockCom.assert_called_once_with("test text", "en-US-GuyNeural", rate="+10%", pitch="+0Hz")


def test_synthesize_default_voice_is_guy_neural(tmp_path):
    dest = tmp_path / "out.mp3"
    with patch("src.narration.synth.edge_tts.Communicate", return_value=_mock_communicate()) as MockCom:
        synthesize("text", dest)
    args, kwargs = MockCom.call_args
    assert args[1] == "en-US-GuyNeural"


def test_synthesize_default_rate_is_ten_percent(tmp_path):
    dest = tmp_path / "out.mp3"
    with patch("src.narration.synth.edge_tts.Communicate", return_value=_mock_communicate()) as MockCom:
        synthesize("text", dest)
    _, kwargs = MockCom.call_args
    assert kwargs["rate"] == "+10%"


def test_synthesize_default_pitch_is_zero(tmp_path):
    dest = tmp_path / "out.mp3"
    with patch("src.narration.synth.edge_tts.Communicate", return_value=_mock_communicate()) as MockCom:
        synthesize("text", dest)
    _, kwargs = MockCom.call_args
    assert kwargs["pitch"] == "+0Hz"


# ---------------------------------------------------------------------------
# Parent dir creation
# ---------------------------------------------------------------------------


def test_synthesize_creates_parent_dirs(tmp_path):
    dest = tmp_path / "a" / "b" / "narration.mp3"
    with patch("src.narration.synth.edge_tts.Communicate", return_value=_mock_communicate()):
        synthesize("text", dest)
    assert dest.parent.exists()

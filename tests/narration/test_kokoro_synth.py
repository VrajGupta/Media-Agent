"""P7.2 — Kokoro narration engine + Edge fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config_loader.loader import NarrationConfig
from src.narration.synth import synthesize


def _mock_edge():
    async def _fake_save(path: str) -> None:
        Path(path).write_bytes(b"edge-mp3")

    mock_com = MagicMock()
    mock_com.save = _fake_save
    return mock_com


def test_synthesize_routes_to_kokoro_when_engine_kokoro(tmp_path):
    dest = tmp_path / "narration.mp3"
    with patch("src.narration.synth._synthesize_kokoro", return_value=dest) as mock_kokoro:
        result = synthesize("Hello", dest, engine="kokoro", kokoro_voice="am_michael")
    mock_kokoro.assert_called_once_with("Hello", dest, kokoro_voice="am_michael")
    assert result == dest


def test_synthesize_routes_to_edge_when_engine_edge(tmp_path):
    dest = tmp_path / "narration.mp3"
    with patch("src.narration.synth.edge_tts.Communicate", return_value=_mock_edge()) as mock_edge:
        with patch("src.narration.synth._synthesize_kokoro") as mock_kokoro:
            synthesize("Hello", dest, engine="edge")
    mock_kokoro.assert_not_called()
    mock_edge.assert_called_once()


def test_synthesize_falls_back_to_edge_when_kokoro_fails(tmp_path):
    dest = tmp_path / "narration.mp3"
    with patch("src.narration.synth._synthesize_kokoro", side_effect=RuntimeError("no espeak-ng")):
        with patch("src.narration.synth.edge_tts.Communicate", return_value=_mock_edge()) as mock_edge:
            result = synthesize("Hello", dest, engine="kokoro")
    assert result == dest
    mock_edge.assert_called_once()


def test_narration_config_defaults_to_kokoro():
    cfg = NarrationConfig()
    assert cfg.engine == "kokoro"
    assert cfg.kokoro_voice == "am_michael"


def test_narration_config_rejects_invalid_engine():
    with pytest.raises(ValueError):
        NarrationConfig(engine="azure")

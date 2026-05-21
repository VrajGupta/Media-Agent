"""Unit tests for narration.aligner — no live Whisper calls."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.narration.aligner import align


def _make_model(words_per_segment: list[list[tuple[str, float, float]]]):
    """Build a mock WhisperModel whose transcribe() returns fake segments."""

    def _make_word(word, start, end):
        w = MagicMock()
        w.word = word
        w.start = start
        w.end = end
        return w

    segments = []
    for seg_words in words_per_segment:
        seg = MagicMock()
        seg.words = [_make_word(w, s, e) for w, s, e in seg_words]
        segments.append(seg)

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (iter(segments), MagicMock())
    return mock_model


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


def test_align_returns_list_of_word_dicts(tmp_path):
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"fake")

    fake_model = _make_model([[("Hello", 0.0, 0.4), ("world", 0.5, 0.9)]])

    with patch("src.narration.aligner.WhisperModel", return_value=fake_model):
        result = align(audio)

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0] == {"word": "Hello", "start": 0.0, "end": 0.4}
    assert result[1] == {"word": "world", "start": 0.5, "end": 0.9}


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


def test_align_calls_transcribe_with_word_timestamps(tmp_path):
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"fake")

    fake_model = _make_model([[("test", 0.0, 0.3)]])

    with patch("src.narration.aligner.WhisperModel", return_value=fake_model):
        align(audio)

    call_kwargs = fake_model.transcribe.call_args[1]
    assert call_kwargs.get("word_timestamps") is True


def test_align_empty_segments_returns_empty_list(tmp_path):
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"fake")

    fake_model = _make_model([])  # no segments
    with patch("src.narration.aligner.WhisperModel", return_value=fake_model):
        result = align(audio)

    assert result == []


def test_align_strips_leading_whitespace_from_words(tmp_path):
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"fake")

    fake_model = _make_model([[(" Hello", 0.0, 0.4), (" world", 0.5, 0.9)]])

    with patch("src.narration.aligner.WhisperModel", return_value=fake_model):
        result = align(audio)

    assert result[0]["word"] == "Hello"
    assert result[1]["word"] == "world"

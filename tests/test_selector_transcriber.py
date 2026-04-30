"""Tests for selector.transcriber: cache + atomic write + Whisper iteration.

No GPU/CUDA touched — Whisper is replaced by SimpleNamespace stubs.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.selector import transcriber as tx


def _stub_word(start: float, end: float, word: str, prob: float = 0.9):
    return SimpleNamespace(start=start, end=end, word=word, probability=prob)


def _stub_segment(start: float, end: float, text: str, words: list):
    return SimpleNamespace(start=start, end=end, text=text, words=words)


class _StubModel:
    """faster_whisper.WhisperModel stand-in. Returns canned segments."""

    def __init__(self, segments, language="en", language_probability=0.95, duration=120.0):
        self._segments = segments
        self._language = language
        self._language_probability = language_probability
        self._duration = duration

    def transcribe(self, *args, **kwargs):
        info = SimpleNamespace(
            language=self._language,
            language_probability=self._language_probability,
            duration=self._duration,
        )
        return iter(self._segments), info


class _RaisingModel:
    """Raises mid-iteration to simulate Whisper failure during streaming."""

    def __init__(self, fail_after: int = 1):
        self._fail_after = fail_after

    def transcribe(self, *args, **kwargs):
        info = SimpleNamespace(language="en", language_probability=0.95, duration=120.0)

        def _gen():
            yield _stub_segment(0.0, 5.0, "hello", [_stub_word(0.0, 1.0, "hello")])
            if self._fail_after <= 1:
                raise RuntimeError("simulated CUDA OOM mid-stream")

        return _gen(), info


# ---- atomic_write -----------------------------------------------------------


def test_atomic_write_promotes_tmp(tmp_path):
    transcripts = tmp_path / "transcripts"
    t = tx.Transcript(
        video_id="v1", model="large-v3", compute_type="int8_float16",
        duration_seconds=120.0, language="en", language_probability=0.99,
        segments=[],
    )
    tx.atomic_write(transcripts, t)
    final = transcripts / "v1.json"
    tmp = transcripts / "v1.json.tmp"
    assert final.exists()
    assert not tmp.exists()
    payload = json.loads(final.read_text())
    assert payload["video_id"] == "v1"
    assert payload["schema_version"] == tx.CACHE_SCHEMA_VERSION


def test_atomic_write_replaces_existing(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    final = transcripts / "v1.json"
    final.write_text('{"old": true}')
    t = tx.Transcript(
        video_id="v1", model="large-v3", compute_type="int8_float16",
        duration_seconds=120.0, language="en", language_probability=0.99,
        segments=[],
    )
    tx.atomic_write(transcripts, t)
    assert json.loads(final.read_text())["video_id"] == "v1"


# ---- read_cached ------------------------------------------------------------


def test_cache_hit_returns_transcript(tmp_path):
    transcripts = tmp_path / "transcripts"
    t = tx.Transcript(
        video_id="v1", model="large-v3", compute_type="int8_float16",
        duration_seconds=120.0, language="en", language_probability=0.99,
        segments=[{"start": 0.0, "end": 5.0, "text": "hi", "words": []}],
    )
    tx.atomic_write(transcripts, t)
    got = tx.read_cached(transcripts, "v1", "large-v3", "int8_float16")
    assert got is not None
    assert got.video_id == "v1"
    assert got.segments[0]["text"] == "hi"


def test_cache_miss_when_file_absent(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    assert tx.read_cached(transcripts, "v1", "large-v3", "int8_float16") is None


def test_cache_miss_on_model_mismatch(tmp_path):
    """User swapped whisper_model in config — silently re-transcribe."""
    transcripts = tmp_path / "transcripts"
    t = tx.Transcript(
        video_id="v1", model="large-v3", compute_type="int8_float16",
        duration_seconds=120.0, language="en", language_probability=0.99,
        segments=[],
    )
    tx.atomic_write(transcripts, t)
    assert tx.read_cached(transcripts, "v1", "medium.en", "int8_float16") is None


def test_cache_miss_on_compute_type_mismatch(tmp_path):
    transcripts = tmp_path / "transcripts"
    t = tx.Transcript(
        video_id="v1", model="large-v3", compute_type="int8_float16",
        duration_seconds=120.0, language="en", language_probability=0.99,
        segments=[],
    )
    tx.atomic_write(transcripts, t)
    assert tx.read_cached(transcripts, "v1", "large-v3", "float16") is None


def test_cache_miss_on_schema_version_bump(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "v1.json").write_text(json.dumps({
        "schema_version": 999, "video_id": "v1", "model": "large-v3",
        "compute_type": "int8_float16", "duration_seconds": 1, "language": "en",
        "language_probability": 0.9, "segments": [],
    }))
    assert tx.read_cached(transcripts, "v1", "large-v3", "int8_float16") is None


def test_cache_miss_on_corrupt_json(tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "v1.json").write_text("{not json")
    assert tx.read_cached(transcripts, "v1", "large-v3", "int8_float16") is None


# ---- run_whisper ------------------------------------------------------------


def test_run_whisper_serializes_segments_and_words(tmp_path):
    model = _StubModel(
        segments=[
            _stub_segment(0.0, 5.0, "hello world", [
                _stub_word(0.0, 1.0, "hello", 0.95),
                _stub_word(1.0, 2.0, "world", 0.9),
            ]),
            _stub_segment(5.0, 10.0, "second segment", [
                _stub_word(5.0, 6.0, "second", 0.92),
            ]),
        ],
        duration=10.0,
    )
    t = tx.run_whisper(model, tmp_path / "v.mp4", "v1", "large-v3", "int8_float16")
    assert t.video_id == "v1"
    assert t.model == "large-v3"
    assert t.compute_type == "int8_float16"
    assert t.duration_seconds == 10.0
    assert t.language == "en"
    assert len(t.segments) == 2
    assert t.segments[0]["text"] == "hello world"
    assert len(t.segments[0]["words"]) == 2
    assert t.segments[0]["words"][0]["word"] == "hello"
    assert t.segments[0]["words"][0]["probability"] == 0.95


def test_run_whisper_failure_does_not_promote_tmp(tmp_path):
    """Critical: mid-stream Whisper failure leaves no temp file behind and no final cache."""
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    model = _RaisingModel()

    with pytest.raises(RuntimeError, match="simulated CUDA OOM"):
        t = tx.run_whisper(model, tmp_path / "v.mp4", "v1", "large-v3", "int8_float16")
        # If we got here, atomic_write would be called by caller — but we shouldn't.
        tx.atomic_write(transcripts, t)

    # No final cache, no orphan .tmp file.
    assert not (transcripts / "v1.json").exists()
    assert not (transcripts / "v1.json.tmp").exists()

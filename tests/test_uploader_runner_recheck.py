"""Slice 9 — _resolve_recheck_inputs helper unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.uploader.runner import _resolve_recheck_inputs


class _FakeRow(dict):
    pass


def _ai_clip(narration="AI is wild.", title="GPT-5 Analysis",
             hook="GPT-5 is here", suggested_title="GPT-5"):
    r = _FakeRow()
    r["content_kind"] = "ai_generated"
    r["hook"] = hook
    r["suggested_title"] = suggested_title
    r["video_id"] = None
    return r


def _ai_script(narration="AI is wild.", title="GPT-5 Analysis"):
    r = _FakeRow()
    r["narration"] = narration
    r["title"] = title
    return r


def _sourced_clip(video_id="v1", hook="Movie hook", suggested_title="Backup"):
    r = _FakeRow()
    r["content_kind"] = "sourced"
    r["video_id"] = video_id
    r["hook"] = hook
    r["suggested_title"] = suggested_title
    r["start_s"] = 0.0
    r["end_s"] = 10.0
    return r


def _write_transcript(tmp_path: Path, video_id: str, words: list[dict]) -> None:
    payload = {
        "schema_version": 1, "video_id": video_id,
        "model": "large-v3", "compute_type": "int8_float16",
        "duration_seconds": 30.0, "language": "en", "language_probability": 0.99,
        "segments": [{"start": 0.0, "end": 10.0, "text": "x", "words": words}],
    }
    (tmp_path / f"{video_id}.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# AI-gen path
# ---------------------------------------------------------------------------

def test_ai_gen_returns_narration_and_title(tmp_path):
    clip_text, recheck_title = _resolve_recheck_inputs(
        clip_row=_ai_clip(),
        script_row=_ai_script(narration="AI is wild.", title="GPT-5 Analysis"),
        transcripts_dir=tmp_path,
    )
    assert clip_text == "AI is wild."
    assert recheck_title == "GPT-5 Analysis"


def test_ai_gen_does_not_read_filesystem(tmp_path):
    # No transcript file written — should not raise
    _resolve_recheck_inputs(
        clip_row=_ai_clip(hook="Hook"),
        script_row=_ai_script(),
        transcripts_dir=tmp_path,
    )


# ---------------------------------------------------------------------------
# Sourced path
# ---------------------------------------------------------------------------

def test_sourced_returns_transcript_derived_text(tmp_path):
    words = [
        {"start": 1.0, "end": 1.5, "word": "hello", "probability": 0.99},
        {"start": 2.0, "end": 2.5, "word": "world", "probability": 0.99},
    ]
    _write_transcript(tmp_path, "v1", words)
    clip = _sourced_clip(video_id="v1")
    clip["start_s"] = 0.0
    clip["end_s"] = 5.0
    clip_text, recheck_title = _resolve_recheck_inputs(
        clip_row=clip,
        script_row=None,
        transcripts_dir=tmp_path,
    )
    assert "hello" in clip_text
    assert recheck_title == "Movie hook"


def test_sourced_missing_transcript_returns_sentinel(tmp_path):
    result = _resolve_recheck_inputs(
        clip_row=_sourced_clip(video_id="missing"),
        script_row=None,
        transcripts_dir=tmp_path,
    )
    assert result is None

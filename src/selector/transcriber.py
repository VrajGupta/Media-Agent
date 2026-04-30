"""Full-video Whisper transcription with on-disk JSON cache (Phase 3).

Per video:
  1. Read cached transcript if (model, compute_type) match config.
  2. Otherwise run Whisper, serialize to <id>.json.tmp, os.replace() to final.
  3. Failure mid-iteration leaves no temp file promoted; caller keeps status=lang_ok.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from loguru import logger

CACHE_SCHEMA_VERSION = 1


class TranscribeError(Exception):
    """Raised when Whisper inference or serialization fails."""


@dataclass
class Transcript:
    video_id: str
    model: str
    compute_type: str
    duration_seconds: float
    language: str
    language_probability: float
    segments: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "video_id": self.video_id,
            "model": self.model,
            "compute_type": self.compute_type,
            "duration_seconds": self.duration_seconds,
            "language": self.language,
            "language_probability": self.language_probability,
            "segments": self.segments,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Transcript":
        return cls(
            video_id=payload["video_id"],
            model=payload["model"],
            compute_type=payload["compute_type"],
            duration_seconds=float(payload["duration_seconds"]),
            language=payload["language"],
            language_probability=float(payload["language_probability"]),
            segments=payload["segments"],
        )


def cache_path(transcripts_dir: Path, video_id: str) -> Path:
    return transcripts_dir / f"{video_id}.json"


def read_cached(
    transcripts_dir: Path,
    video_id: str,
    expected_model: str,
    expected_compute_type: str,
) -> Optional[Transcript]:
    """Return the cached Transcript iff (model, compute_type) match config.

    On any mismatch, schema-version bump, or read error, return None and let
    the caller re-transcribe. The caller is responsible for not deleting the
    stale file — os.replace() in atomic_write will overwrite it.
    """
    path = cache_path(transcripts_dir, video_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"transcript cache unreadable for {video_id}: {exc}")
        return None
    if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return None
    if payload.get("model") != expected_model:
        return None
    if payload.get("compute_type") != expected_compute_type:
        return None
    try:
        return Transcript.from_payload(payload)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning(f"transcript cache malformed for {video_id}: {exc}")
        return None


def atomic_write(transcripts_dir: Path, transcript: Transcript) -> None:
    """Write to <id>.json.tmp then os.replace() to <id>.json.

    Ensures the cache file either doesn't exist or is complete + valid — there
    is no readable partial state. If the json.dumps or write fails, the .tmp
    file is unlinked so it doesn't accumulate.
    """
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    final_path = cache_path(transcripts_dir, transcript.video_id)
    tmp_path = final_path.with_suffix(".json.tmp")
    try:
        payload = json.dumps(transcript.to_payload(), ensure_ascii=False)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, final_path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def run_whisper(model, video_path: Path, video_id: str, model_name: str, compute_type: str) -> Transcript:
    """Iterate the Whisper segments generator and assemble a Transcript.

    `model` is a faster_whisper.WhisperModel (or compatible stub). We MUST iterate
    `segments` to materialize them — Whisper streams. word_timestamps=True so
    Phase 4's ASS subtitle generator can read straight from the cache.

    Any exception during iteration propagates; caller does NOT promote the temp
    file, leaves video at lang_ok.
    """
    segments_iter, info = model.transcribe(
        str(video_path),
        beam_size=1,
        language="en",
        vad_filter=False,
        word_timestamps=True,
    )

    serialized: list[dict[str, Any]] = []
    last_end = 0.0
    for seg in segments_iter:
        words_payload: list[dict[str, Any]] = []
        seg_words = getattr(seg, "words", None) or []
        for w in seg_words:
            words_payload.append({
                "start": float(getattr(w, "start", 0.0) or 0.0),
                "end": float(getattr(w, "end", 0.0) or 0.0),
                "word": getattr(w, "word", ""),
                "probability": float(getattr(w, "probability", 0.0) or 0.0),
            })
        seg_end = float(getattr(seg, "end", 0.0) or 0.0)
        serialized.append({
            "start": float(getattr(seg, "start", 0.0) or 0.0),
            "end": seg_end,
            "text": getattr(seg, "text", ""),
            "words": words_payload,
        })
        if seg_end > last_end:
            last_end = seg_end

    duration = float(getattr(info, "duration", 0.0) or last_end)
    return Transcript(
        video_id=video_id,
        model=model_name,
        compute_type=compute_type,
        duration_seconds=duration,
        language=getattr(info, "language", "en"),
        language_probability=float(getattr(info, "language_probability", 0.0) or 0.0),
        segments=serialized,
    )

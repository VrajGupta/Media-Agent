"""Whisper word-timestamp extraction for narration alignment (Pivot.6).

Transcribes the TTS narration MP3 with word_timestamps=True to get
per-word start/end times. These feed directly into line_ass.py to
produce synchronized line-at-a-time subtitles.

TTS audio (Edge TTS) is clean and clear — Whisper accuracy on TTS is
very high (~99%+), so regular transcription with word timestamps gives
results that are equivalent to true forced alignment for our use case.
"""

from __future__ import annotations

from pathlib import Path

from faster_whisper import WhisperModel


def _load_whisper_model(
    model_size: str,
    *,
    device: str,
    compute_type: str,
) -> WhisperModel:
    try:
        return WhisperModel(model_size, device=device, compute_type=compute_type)
    except RuntimeError:
        if device != "cuda":
            raise
        return WhisperModel(model_size, device="cpu", compute_type="int8")


def align(
    audio_path: Path,
    *,
    model_size: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "int8_float16",
) -> list[dict]:
    """Transcribe audio with word timestamps. Returns [{word, start, end}].

    Loads the Whisper model fresh each call — caller should cache the result
    rather than re-running alignment. Model load is ~2s on GPU.

    When ``device='cuda'`` and CUDA libraries are unavailable, falls back to
    CPU with ``compute_type='int8'``.
    """
    model = _load_whisper_model(model_size, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(str(audio_path), word_timestamps=True)
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            words.append({
                "word": w.word.strip(),
                "start": w.start,
                "end": w.end,
            })
    return words

"""Narration synthesis — Kokoro local (Pivot.7) with Edge TTS fallback."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import edge_tts
from loguru import logger


async def _run_edge(text: str, dest: Path, voice: str, rate: str, pitch: str) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(str(dest))


def _synthesize_edge(
    text: str,
    dest: Path,
    *,
    voice: str,
    rate: str,
    pitch: str,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run_edge(text, dest, voice, rate, pitch))
    return dest


def _synthesize_kokoro(text: str, dest: Path, *, kokoro_voice: str) -> Path:
    from src.narration.kokoro_engine import synthesize_kokoro

    return synthesize_kokoro(text, dest, voice=kokoro_voice)


def synthesize(
    text: str,
    dest: Path,
    *,
    voice: str = "en-US-GuyNeural",
    rate: str = "+10%",
    pitch: str = "+0Hz",
    engine: Literal["kokoro", "edge"] = "kokoro",
    kokoro_voice: str = "am_michael",
) -> Path:
    """Generate MP3 from text. Routes to Kokoro or Edge; Kokoro failures fall back to Edge."""
    if engine == "edge":
        return _synthesize_edge(text, dest, voice=voice, rate=rate, pitch=pitch)
    try:
        return _synthesize_kokoro(text, dest, kokoro_voice=kokoro_voice)
    except Exception as exc:
        logger.warning("Kokoro unavailable, falling back to Edge TTS (degraded mode): {}", exc)
        return _synthesize_edge(text, dest, voice=voice, rate=rate, pitch=pitch)

"""Edge TTS narration synthesis (Pivot.6).

Wraps the edge-tts async API in a synchronous function so the rest of the
pipeline can call it without managing an event loop.

Voice: en-US-GuyNeural (+10% rate, +0Hz pitch) — natural conversational pacing.
Output: MP3 written to dest path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts


async def _run(text: str, dest: Path, voice: str, rate: str, pitch: str) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(str(dest))


def synthesize(
    text: str,
    dest: Path,
    *,
    voice: str = "en-US-GuyNeural",
    rate: str = "+10%",
    pitch: str = "+0Hz",
) -> Path:
    """Generate MP3 from text using Edge TTS. Returns dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run(text, dest, voice, rate, pitch))
    return dest

"""Kokoro-82M local TTS backend (Pivot.7)."""

from __future__ import annotations

from pathlib import Path


def synthesize_kokoro(text: str, dest: Path, *, voice: str) -> Path:
    """Generate speech audio at dest using Kokoro-82M. Returns dest."""
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    dest.parent.mkdir(parents=True, exist_ok=True)
    pipeline = KPipeline(lang_code="a")
    chunks: list[np.ndarray] = []
    sample_rate = 24000
    for _, _, audio in pipeline(text, voice=voice):
        chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        raise RuntimeError("Kokoro produced no audio")
    merged = np.concatenate(chunks)
    wav_path = dest.with_suffix(".wav")
    sf.write(str(wav_path), merged, sample_rate)
    if dest.suffix.lower() == ".mp3":
        _wav_to_mp3(wav_path, dest)
        wav_path.unlink(missing_ok=True)
    else:
        wav_path.replace(dest)
    return dest


def _wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    result = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path), str(mp3_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg wav→mp3 failed: {result.stderr.strip()}")

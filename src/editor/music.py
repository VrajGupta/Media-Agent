"""Background music selection (Pivot.3).

User drops royalty-free trendy tracks (phonk, lo-fi, anything) into
`data/music/`. The editor picks one deterministically per clip via a SHA1
hash of the clip_id modulo the track count — same clip → same track across
reruns. Tracks shorter than the rendered clip are looped by ffmpeg's
`aloop` filter; longer tracks are trimmed by `atrim`.

This module is **stateless** — there's no music_cursor table. Determinism
comes from the hash, which is reproducible regardless of when the editor
runs. New tracks added to data/music/ will rotate into the pool naturally
on the next render pass; existing rendered clips don't get re-rendered.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Optional

from src.config_loader import Config


# Audio extensions ffmpeg can decode without extra muxers. Listed here so
# random files (e.g. a stray .txt or .DS_Store) in data/music/ don't get
# accidentally selected.
SUPPORTED_EXTENSIONS = (".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac")


def list_music_tracks(cfg: Config) -> List[Path]:
    """Return supported audio files in cfg.paths.music_dir, sorted alphabetically.

    Sorted ordering (rather than mtime) makes the rotation deterministic
    even when files are touched/copied. Returns [] when the directory is
    missing or empty — caller falls back to dialogue-only.
    """
    music_dir = cfg.abs_path(cfg.paths.music_dir)
    if not music_dir.exists() or not music_dir.is_dir():
        return []
    tracks: List[Path] = []
    for f in sorted(music_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() in SUPPORTED_EXTENSIONS:
            tracks.append(f)
    return tracks


def pick_track_for_clip(clip_id: str, tracks: List[Path]) -> Optional[Path]:
    """Deterministically pick a track for a clip_id via sha1 modulo.

    Returns None if `tracks` is empty. Deterministic so reruns of the editor
    on the same clip pick the same track — important for `--force` reruns
    where the user would not expect the music to swap.
    """
    if not tracks:
        return None
    digest = hashlib.sha1(clip_id.encode("utf-8")).digest()
    # Use the first 8 bytes as a 64-bit unsigned int for the modulo. SHA1's
    # distribution is uniform enough that any byte slice works; first 8 is
    # conventional for hash-based partitioning.
    idx = int.from_bytes(digest[:8], "big") % len(tracks)
    return tracks[idx]


def resolve_music_for_clip(cfg: Config, clip_id: str) -> Optional[Path]:
    """Convenience: list + pick, returning None when music is disabled or
    no tracks are available. The editor invokes this once per clip."""
    if not getattr(cfg, "music_enabled", True):
        return None
    tracks = list_music_tracks(cfg)
    return pick_track_for_clip(clip_id, tracks)

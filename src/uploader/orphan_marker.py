"""Orphan-marker fence for the post-upload persistence sequence.

The fence ensures that a YouTube videos.insert success is NEVER followed by
a re-upload on the next run, even if every subsequent DB write fails. The
marker file is written atomically *before* any DB write that would otherwise
be the only signal of API success.

Sequence:
  1. API succeeds, returns videoId.
  2. write_marker(...)  — atomic tmp+os.replace under output/orphans/.
  3. set_clip_youtube_id(...)  — narrow tx writing youtube_video_id.
  4. set_clip_status('uploaded', ...) + upsert_upload(...)  — wider tx.
  5. unlink_marker(...)  — best-effort cleanup.

Recovery:
  - Runner startup calls scan_orphans() and validates each marker against
    the DB. Inconsistent markers (DB doesn't yet reflect the upload) abort
    the run with `orphan_reconcile_required` so the user can patch state
    manually. Consistent markers (DB already reflects the upload) are
    silently cleaned up.

Design note: this module owns FILESYSTEM state only. DB validation happens
in the runner so the marker code stays pure-FS and trivially testable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


_MARKER_SUFFIX = ".json"


@dataclass(frozen=True)
class OrphanMarker:
    """Filesystem record of a successful API call before DB persistence.

    Fields are written verbatim to JSON. The user reads this file when
    reconciling state after a failure.
    """
    clip_id: str
    youtube_video_id: str
    padded_publish_at_utc: str       # ISO 8601 with 'Z' suffix
    quota_units_used: int
    uploaded_at_utc: str             # ISO 8601 with 'Z' suffix


def _marker_path(orphans_dir: Path, clip_id: str) -> Path:
    return orphans_dir / f"{clip_id}{_MARKER_SUFFIX}"


def write_marker(
    orphans_dir: Path,
    *,
    clip_id: str,
    youtube_video_id: str,
    padded_publish_at_utc: str,
    quota_units_used: int,
) -> Path:
    """Atomically write the orphan marker for `clip_id`.

    Atomicity: write to a NamedTemporaryFile in the same directory, then
    os.replace() onto the final path. If this raises (disk full, permission
    denied), the caller MUST treat the upload as catastrophically incomplete
    — abort the runner immediately, do NOT attempt the DB writes.

    Returns the final marker path on success.
    """
    orphans_dir.mkdir(parents=True, exist_ok=True)
    final_path = _marker_path(orphans_dir, clip_id)
    payload = {
        "clip_id": clip_id,
        "youtube_video_id": youtube_video_id,
        "padded_publish_at_utc": padded_publish_at_utc,
        "quota_units_used": int(quota_units_used),
        "uploaded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # tempfile in same dir so os.replace is atomic across the same volume.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=str(orphans_dir),
        prefix=f".{clip_id}_",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(payload, tmp, indent=2)
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(final_path))
    return final_path


def read_marker(marker_path: Path) -> Optional[OrphanMarker]:
    """Parse a marker file. Returns None if the file is unreadable or
    malformed — the runner reconcile gate will surface a separate alert.
    """
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return OrphanMarker(
            clip_id=str(payload["clip_id"]),
            youtube_video_id=str(payload["youtube_video_id"]),
            padded_publish_at_utc=str(payload["padded_publish_at_utc"]),
            quota_units_used=int(payload["quota_units_used"]),
            uploaded_at_utc=str(payload["uploaded_at_utc"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def unlink_marker(orphans_dir: Path, clip_id: str) -> bool:
    """Best-effort delete of the marker. Returns True on success or if the
    file was already gone; False on OSError. Failures are logged by the
    caller but never raise — the next-run scan will harmlessly find a
    consistent-DB marker and clean it up.
    """
    path = _marker_path(orphans_dir, clip_id)
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def scan_orphans(orphans_dir: Path) -> list[OrphanMarker]:
    """List all valid orphan markers in `orphans_dir`. Malformed files are
    silently dropped — the runner caller is responsible for surfacing them
    via alert if it cares.
    """
    if not orphans_dir.exists():
        return []
    markers: list[OrphanMarker] = []
    for entry in sorted(orphans_dir.iterdir()):
        if not entry.is_file() or not entry.name.endswith(_MARKER_SUFFIX):
            continue
        if entry.name.startswith("."):
            # Skip in-flight tmp files (NamedTemporaryFile prefix is `.{clip_id}_`).
            continue
        marker = read_marker(entry)
        if marker is not None:
            markers.append(marker)
    return markers


def db_is_consistent_with_marker(
    conn: sqlite3.Connection,
    marker: OrphanMarker,
) -> bool:
    """A marker is "consistent" iff the DB already reflects the upload:
    clips.status='uploaded' AND clips.youtube_video_id matches the marker
    AND an uploads row exists for the clip.

    A consistent marker means step 10-post (unlink) failed but everything
    else succeeded — safe to silently clean up. An inconsistent marker
    means the run died between API success and full DB persistence; the
    user must reconcile manually before another upload run.
    """
    row = conn.execute(
        "SELECT status, youtube_video_id FROM clips WHERE clip_id=?",
        (marker.clip_id,),
    ).fetchone()
    if row is None:
        return False
    if row["status"] != "uploaded":
        return False
    if (row["youtube_video_id"] or "") != marker.youtube_video_id:
        return False
    upl = conn.execute(
        "SELECT 1 FROM uploads WHERE clip_id=?",
        (marker.clip_id,),
    ).fetchone()
    return upl is not None

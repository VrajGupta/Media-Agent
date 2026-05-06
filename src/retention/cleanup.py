"""Phase 6 retention skeleton.

This module enumerates retention candidates per category but DOES NOT delete
anything in Phase 6 — `dry_run=True` is hard-coded by weekly_run's pipeline.
Phase 7 will flip the kill switch after live disk validation on the user's PC.

Categories (see agents.md §10):
  - data/raw/*.mp4        → 14 days post-download AND all derived clips uploaded
  - data/transcripts/*.json → 90-day TTL
  - output/pending/*.mp4
  - output/approved/*.mp4   → 7 days post-uploaded
  - output/rejected/*.mp4   → 30-day TTL (mtime-based)
  - dup_hashes              → 90-day TTL (created_at)
  - quota_usage             → 90-day TTL (date)
  - SQLite VACUUM           → once every cfg.retention.vacuum_every_days

Each helper is a pure (or near-pure) "list candidates" function. Tests
verify the threshold math without hitting the filesystem with real ages.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from loguru import logger

from src.config_loader import Config
from src.state import Repository


@dataclass
class RetentionResult:
    """Per-category candidate counts for the retention sweep.

    In dry-run mode (Phase 6 default), `deleted_*` counts are always zero;
    `would_delete_*` is what Phase 7 will eventually act on.
    """
    dry_run: bool = True
    would_delete_raw: List[str] = field(default_factory=list)
    would_delete_transcripts: List[str] = field(default_factory=list)
    would_delete_output_pending: List[str] = field(default_factory=list)
    would_delete_output_approved: List[str] = field(default_factory=list)
    would_delete_output_rejected: List[str] = field(default_factory=list)
    would_prune_dup_hashes: int = 0
    would_prune_quota_usage: int = 0
    would_vacuum: bool = False


def _file_age_days(path: Path, now: datetime | None = None) -> float:
    """Return the file's age in days based on mtime."""
    now = now or datetime.now(timezone.utc)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (now - mtime).total_seconds() / 86400.0


def list_raw_candidates(
    repo: Repository,
    cfg: Config,
    *,
    now: datetime | None = None,
) -> List[str]:
    """data/raw/*.mp4 → delete iff age >= retention.raw_video days AND every
    derived clip is uploaded (or the video has zero clips).

    Returns the list of absolute mp4 paths that would be deleted.
    """
    raw_dir = cfg.abs_path(cfg.paths.raw_dir)
    if not raw_dir.exists():
        return []
    threshold_days = int(cfg.retention.raw_video)
    candidates: List[str] = []
    for f in raw_dir.glob("*.mp4"):
        if _file_age_days(f, now=now) < threshold_days:
            continue
        video_id = f.stem  # raw filenames are {video_id}.mp4
        # Are there any clips for this video that haven't been uploaded?
        outstanding = repo.conn.execute(
            "SELECT 1 FROM clips WHERE video_id=? AND status != 'uploaded' LIMIT 1",
            (video_id,),
        ).fetchone()
        if outstanding is not None:
            continue
        candidates.append(str(f))
    return candidates


def list_transcript_candidates(
    cfg: Config,
    *,
    now: datetime | None = None,
) -> List[str]:
    """data/transcripts/*.json → 90-day TTL by mtime."""
    transcripts_dir = cfg.abs_path(cfg.paths.transcripts_dir)
    if not transcripts_dir.exists():
        return []
    threshold_days = int(cfg.retention.transcript)
    return [
        str(f) for f in transcripts_dir.glob("*.json")
        if _file_age_days(f, now=now) >= threshold_days
    ]


def list_output_post_upload_candidates(
    repo: Repository,
    cfg: Config,
    *,
    now: datetime | None = None,
) -> tuple[List[str], List[str]]:
    """output/pending/*.mp4 + output/approved/*.mp4 whose clip is uploaded
    >= retention.output_post_upload days ago.

    Returns (pending_paths, approved_paths).
    """
    threshold_days = int(cfg.retention.output_post_upload)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=threshold_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    rows = repo.conn.execute(
        "SELECT clip_id, output_path FROM clips "
        "WHERE status='uploaded' AND updated_at <= ?",
        (cutoff_iso,),
    ).fetchall()

    pending_dir = cfg.abs_path(cfg.paths.pending_dir)
    approved_dir = cfg.abs_path(cfg.paths.approved_dir)
    pending_paths: List[str] = []
    approved_paths: List[str] = []
    for r in rows:
        if not r["output_path"]:
            continue
        p = Path(r["output_path"])
        if not p.exists():
            continue
        try:
            p_resolved = p.resolve()
            if p_resolved.is_relative_to(pending_dir.resolve()):
                pending_paths.append(str(p))
            elif p_resolved.is_relative_to(approved_dir.resolve()):
                approved_paths.append(str(p))
        except (ValueError, OSError):
            continue
    return (pending_paths, approved_paths)


def list_rejected_candidates(
    cfg: Config,
    *,
    now: datetime | None = None,
) -> List[str]:
    """output/rejected/*.mp4 → 30-day TTL by mtime (no DB lookup)."""
    rejected_dir = cfg.abs_path(cfg.paths.rejected_dir)
    if not rejected_dir.exists():
        return []
    threshold_days = int(cfg.retention.rejected_clips)
    return [
        str(f) for f in rejected_dir.glob("*.mp4")
        if _file_age_days(f, now=now) >= threshold_days
    ]


def count_dup_hashes_to_prune(
    repo: Repository,
    cfg: Config,
    *,
    now: datetime | None = None,
) -> int:
    threshold_days = int(cfg.retention.dup_hashes)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=threshold_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    row = repo.conn.execute(
        "SELECT COUNT(*) AS n FROM dup_hashes WHERE created_at <= ?",
        (cutoff_iso,),
    ).fetchone()
    return int(row["n"]) if row else 0


def count_quota_usage_to_prune(
    repo: Repository,
    cfg: Config,
    *,
    now: datetime | None = None,
) -> int:
    threshold_days = int(cfg.retention.quota_usage)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=threshold_days)
    cutoff_date = cutoff.strftime("%Y-%m-%d")
    row = repo.conn.execute(
        "SELECT COUNT(*) AS n FROM quota_usage WHERE date <= ?",
        (cutoff_date,),
    ).fetchone()
    return int(row["n"]) if row else 0


def run_all(
    repo: Repository,
    cfg: Config,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
) -> RetentionResult:
    """Enumerate retention candidates. Phase 6 hard-codes dry_run=True via
    weekly_run; Phase 7 will pass dry_run=False after live validation.
    """
    if not dry_run:
        # Phase 7 will implement actual deletion. For now, abort loudly so
        # nobody accidentally invokes real-mode without the Phase 7 work.
        raise NotImplementedError(
            "retention.run_all(dry_run=False) is reserved for Phase 7. "
            "Phase 6 is enumeration-only."
        )

    result = RetentionResult(dry_run=True)
    result.would_delete_raw = list_raw_candidates(repo, cfg, now=now)
    result.would_delete_transcripts = list_transcript_candidates(cfg, now=now)
    pending, approved = list_output_post_upload_candidates(repo, cfg, now=now)
    result.would_delete_output_pending = pending
    result.would_delete_output_approved = approved
    result.would_delete_output_rejected = list_rejected_candidates(cfg, now=now)
    result.would_prune_dup_hashes = count_dup_hashes_to_prune(repo, cfg, now=now)
    result.would_prune_quota_usage = count_quota_usage_to_prune(repo, cfg, now=now)

    logger.info(
        "retention (dry-run) candidates: "
        f"raw={len(result.would_delete_raw)} "
        f"transcripts={len(result.would_delete_transcripts)} "
        f"pending={len(result.would_delete_output_pending)} "
        f"approved={len(result.would_delete_output_approved)} "
        f"rejected={len(result.would_delete_output_rejected)} "
        f"dup_hashes={result.would_prune_dup_hashes} "
        f"quota_usage={result.would_prune_quota_usage}"
    )
    return result

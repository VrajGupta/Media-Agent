"""Phase 7 retention sweep.

Phase 6 shipped the enumeration helpers and a kill-switch `run_all` that
raised NotImplementedError on `dry_run=False`. Phase 7 implements actual
deletion + pruning + periodic VACUUM.

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

Path safety: every candidate path is verified to live under the configured
project root before unlink. Symlinks or stale rows pointing outside the
project tree are skipped + alerted (`retention_path_outside_root`).

VACUUM safety: WAL + active readers can refuse VACUUM with SQLITE_BUSY.
We run VACUUM on a freshly-opened standalone connection, catch
OperationalError, and leave the sentinel untouched on failure so the
next sweep retries.
"""

from __future__ import annotations

import functools
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from loguru import logger

from src.config_loader import Config
from src.observability import append_alert
from src.state import Repository

VACUUM_SENTINEL = "data/.last_vacuum"


@dataclass
class RetentionResult:
    """Per-category counts for the retention sweep."""
    dry_run: bool = True
    # Candidate enumeration (always populated).
    would_delete_raw: List[str] = field(default_factory=list)
    would_delete_transcripts: List[str] = field(default_factory=list)
    would_delete_output_pending: List[str] = field(default_factory=list)
    would_delete_output_approved: List[str] = field(default_factory=list)
    would_delete_output_rejected: List[str] = field(default_factory=list)
    would_prune_dup_hashes: int = 0
    would_prune_quota_usage: int = 0
    would_vacuum: bool = False
    # Phase 7 actual deletion counts (zero in dry-run mode).
    deleted_raw: int = 0
    deleted_transcripts: int = 0
    deleted_output_pending: int = 0
    deleted_output_approved: int = 0
    deleted_output_rejected: int = 0
    pruned_dup_hashes: int = 0
    pruned_quota_usage: int = 0
    vacuumed: bool = False
    # Files counted as "already gone" (FileNotFoundError on unlink) — benign,
    # not an error. Separate from delete_errors.
    already_gone: int = 0
    # Real failures (PermissionError, OSError) — sweep continues.
    delete_errors: List[str] = field(default_factory=list)


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


def _safe_unlink(
    path_str: str,
    *,
    root: Path,
    result: RetentionResult,
    logs_dir: Path,
) -> bool:
    """Resolve `path_str`, verify it lives under `root`, then unlink.

    Returns True on success, False on skip/error. Updates result counters.
    """
    p = Path(path_str)
    try:
        resolved = p.resolve()
        root_resolved = root.resolve()
    except (OSError, ValueError):
        result.delete_errors.append(f"resolve failed: {path_str}")
        return False
    try:
        if not resolved.is_relative_to(root_resolved):
            append_alert(
                logs_dir, kind="retention_path_outside_root",
                message=f"refusing to delete {resolved} (outside {root_resolved})",
            )
            return False
    except ValueError:
        # Different drives on Windows — definitely outside root.
        append_alert(
            logs_dir, kind="retention_path_outside_root",
            message=f"refusing to delete {resolved} (outside {root_resolved})",
        )
        return False
    try:
        os.unlink(resolved)
        return True
    except FileNotFoundError:
        # Benign race or prior partial run — not an error.
        result.already_gone += 1
        return False
    except (PermissionError, OSError) as exc:
        result.delete_errors.append(f"{path_str}: {exc}")
        return False


def _vacuum_sentinel_path(cfg: Config) -> Path:
    return cfg.abs_path(VACUUM_SENTINEL)


def _vacuum_due(cfg: Config, *, now: datetime | None = None) -> bool:
    """Read data/.last_vacuum mtime; due iff older than vacuum_every_days
    (or sentinel missing).
    """
    sentinel = _vacuum_sentinel_path(cfg)
    if not sentinel.exists():
        return True
    threshold = int(cfg.retention.vacuum_every_days)
    return _file_age_days(sentinel, now=now) >= threshold


def _run_vacuum(
    cfg: Config,
    *,
    result: RetentionResult,
    logs_dir: Path,
) -> None:
    """Run VACUUM on a fresh standalone connection. Best-effort:
    SQLITE_BUSY (WAL + active readers) → log + alert + DON'T touch sentinel,
    so the next sweep retries.
    """
    db_path = cfg.abs_path(cfg.paths.state_db)
    try:
        # Standalone connection so we don't fight the orchestrator's writer.
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        try:
            conn.execute("VACUUM")
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        logger.warning(f"retention: VACUUM skipped ({exc})")
        append_alert(
            logs_dir, kind="vacuum_skipped",
            message=f"VACUUM refused by SQLite: {exc}",
        )
        result.vacuumed = False
        return
    # On success, touch the sentinel so the next sweep waits vacuum_every_days.
    sentinel = _vacuum_sentinel_path(cfg)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    result.vacuumed = True


def run_all(
    repo: Repository,
    cfg: Config,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
) -> RetentionResult:
    """Enumerate retention candidates. With dry_run=True, only enumerate.
    With dry_run=False, perform deletion + DB pruning + periodic VACUUM.

    Path safety: every file path is resolved + verified under the project
    root before unlink. Files outside the root are skipped with an alert.
    """
    result = RetentionResult(dry_run=dry_run)
    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    alert = functools.partial(append_alert, logs_dir)
    project_root = cfg.abs_path(".")

    # ---- enumerate -----------------------------------------------------------
    result.would_delete_raw = list_raw_candidates(repo, cfg, now=now)
    result.would_delete_transcripts = list_transcript_candidates(cfg, now=now)
    pending, approved = list_output_post_upload_candidates(repo, cfg, now=now)
    result.would_delete_output_pending = pending
    result.would_delete_output_approved = approved
    result.would_delete_output_rejected = list_rejected_candidates(cfg, now=now)
    result.would_prune_dup_hashes = count_dup_hashes_to_prune(repo, cfg, now=now)
    result.would_prune_quota_usage = count_quota_usage_to_prune(repo, cfg, now=now)
    result.would_vacuum = _vacuum_due(cfg, now=now)

    if dry_run:
        logger.info(
            "retention (dry-run) candidates: "
            f"raw={len(result.would_delete_raw)} "
            f"transcripts={len(result.would_delete_transcripts)} "
            f"pending={len(result.would_delete_output_pending)} "
            f"approved={len(result.would_delete_output_approved)} "
            f"rejected={len(result.would_delete_output_rejected)} "
            f"dup_hashes={result.would_prune_dup_hashes} "
            f"quota_usage={result.would_prune_quota_usage} "
            f"vacuum_due={result.would_vacuum}"
        )
        return result

    # ---- delete files (path-safety verified per file) -----------------------
    for p in result.would_delete_raw:
        if _safe_unlink(p, root=project_root, result=result, logs_dir=logs_dir):
            result.deleted_raw += 1
    for p in result.would_delete_transcripts:
        if _safe_unlink(p, root=project_root, result=result, logs_dir=logs_dir):
            result.deleted_transcripts += 1
    for p in result.would_delete_output_pending:
        if _safe_unlink(p, root=project_root, result=result, logs_dir=logs_dir):
            result.deleted_output_pending += 1
    for p in result.would_delete_output_approved:
        if _safe_unlink(p, root=project_root, result=result, logs_dir=logs_dir):
            result.deleted_output_approved += 1
    for p in result.would_delete_output_rejected:
        if _safe_unlink(p, root=project_root, result=result, logs_dir=logs_dir):
            result.deleted_output_rejected += 1

    # ---- prune DB rows (mirror the threshold math used by the count helpers) ---
    if result.would_prune_dup_hashes:
        cutoff_dh = (now or datetime.now(timezone.utc)) - timedelta(
            days=int(cfg.retention.dup_hashes)
        )
        cutoff_dh_iso = cutoff_dh.strftime("%Y-%m-%d %H:%M:%S")
        with repo.tx():
            cur = repo.conn.execute(
                "DELETE FROM dup_hashes WHERE created_at <= ?", (cutoff_dh_iso,),
            )
            result.pruned_dup_hashes = cur.rowcount or 0
    if result.would_prune_quota_usage:
        cutoff_q = (now or datetime.now(timezone.utc)) - timedelta(
            days=int(cfg.retention.quota_usage)
        )
        cutoff_q_date = cutoff_q.strftime("%Y-%m-%d")
        with repo.tx():
            cur = repo.conn.execute(
                "DELETE FROM quota_usage WHERE date <= ?", (cutoff_q_date,),
            )
            result.pruned_quota_usage = cur.rowcount or 0

    # ---- VACUUM (best-effort) -----------------------------------------------
    if result.would_vacuum:
        _run_vacuum(cfg, result=result, logs_dir=logs_dir)

    logger.info(
        "retention (real) sweep: "
        f"raw={result.deleted_raw} transcripts={result.deleted_transcripts} "
        f"pending={result.deleted_output_pending} approved={result.deleted_output_approved} "
        f"rejected={result.deleted_output_rejected} "
        f"dup_hashes={result.pruned_dup_hashes} quota_usage={result.pruned_quota_usage} "
        f"vacuumed={result.vacuumed} already_gone={result.already_gone} "
        f"errors={len(result.delete_errors)}"
    )
    if result.delete_errors:
        alert(
            kind="retention_delete_errors",
            message=f"{len(result.delete_errors)} delete error(s); first: {result.delete_errors[0]}",
        )
    return result

"""Phase 6 daily_upload orchestrator.

Calls Phase 5's `upload_one_clip` directly in a today-window loop. Three
Phase-6-specific concerns layered on top:

1. reconcile_approvals — scans output/approved/ for files dragged in by the
   user; flips matching quality_pass clips to status='approved' and rewrites
   output_path. Honors cfg.human_review (when False, the reconciliation still
   runs but daily_upload also processes quality_pass directly).
2. Today-window filter — `publish_at_utc <= end_of_today_local` (in
   cfg.timezone). Past-due clips ARE included to recover from missed days.
3. recovered_slot detection — when Phase 5's pad_publish_at flags a clip's
   was_padded=True AND the row's intended publish_at_utc was strictly in
   the past at upload time, append a `recovered_slot` alert.

Reuses Phase 5's runner-startup orphan reconcile gate as the first step.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from loguru import logger

from src.config_loader import Config, load_config
from src.observability import append_alert, setup_logging
from src.state import Repository, connect
from src.uploader.publish_at import format_publish_at_iso_z


def _parse_iso_z(s: Optional[str]) -> Optional[datetime]:
    """Parse 'YYYY-MM-DDTHH:MM:SSZ' → tz-aware UTC datetime, else None."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def reconcile_approvals(
    repo: Repository,
    cfg: Config,
    *,
    dry_run: bool = False,
) -> List[str]:
    """Scan output/approved/ for files dragged in by the user; flip matching
    quality_pass clips to status='approved' and rewrite output_path.

    Matches by Path(...).name in Python (not SQL LIKE) so title slugs
    containing '%' or '_' don't interfere with wildcard parsing.

    Idempotent — clips already at status='approved' are skipped silently.

    dry_run=True logs would-be flips without writing — matches Phase 5's
    strict no-DB-writes-in-dry-run contract.
    """
    approved_dir = cfg.abs_path(cfg.paths.approved_dir)
    if not approved_dir.exists():
        return []

    rows = repo.conn.execute(
        "SELECT * FROM clips "
        "WHERE status='quality_pass' "
        "  AND publish_at_utc IS NOT NULL "
        "  AND youtube_video_id IS NULL"
    ).fetchall()
    by_basename: dict[str, sqlite3.Row] = {}
    for r in rows:
        if r["output_path"]:
            by_basename[Path(r["output_path"]).name] = r

    flipped: List[str] = []
    for f in approved_dir.iterdir():
        if not f.is_file() or f.suffix != ".mp4":
            continue
        row = by_basename.get(f.name)
        if row is None:
            continue
        if dry_run:
            logger.info(
                f"[DRY-RUN] reconcile_approvals: would flip {row['clip_id']} "
                f"-> approved at {f}"
            )
            flipped.append(row["clip_id"])
            continue
        with repo.tx():
            repo.set_clip_status(row["clip_id"], "approved", output_path=str(f))
        flipped.append(row["clip_id"])
        logger.info(f"reconcile_approvals: {row['clip_id']} -> approved at {f}")
    return flipped


def _compute_today_window_end(cfg: Config, now: Optional[datetime] = None) -> str:
    """Return end-of-today in cfg.timezone, formatted as UTC ISO Z.

    Used by clips_for_upload_due as the inclusive `<=` upper bound.
    """
    tz = ZoneInfo(cfg.timezone)
    if now is None:
        now_local = datetime.now(tz)
    else:
        now_local = now.astimezone(tz)
    end_of_today = now_local.replace(
        hour=23, minute=59, second=59, microsecond=0,
    )
    return format_publish_at_iso_z(end_of_today.astimezone(timezone.utc))


def run_today(
    *,
    repo: Repository,
    cfg: Config,
    ledger,
    youtube,
    dry_run: bool = False,
    ollama_host: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> tuple[list, int]:
    """Run the daily upload pipeline. Returns (results, exit_code).

    exit_code matches the CLI:
      0 = ok
      4 = orphan_reconcile_required
    """
    # Lazy imports so dry-run never pulls in OAuth-dependent modules until
    # absolutely necessary. (Mirrors uploader/__main__.py's pattern.)
    from src.uploader.runner import (
        UploadOutcome,
        UploadResult,
        reconcile_orphans,
        upload_one_clip,
    )

    logs_dir = cfg.abs_path(cfg.paths.logs_dir)
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # Phase 5's orphan-marker fence. Aborts with exit 4 on inconsistent state.
    ok, orphan_alerts = reconcile_orphans(repo=repo, cfg=cfg)
    if not ok:
        for a in orphan_alerts:
            append_alert(logs_dir, kind="orphan_reconcile_required", message=a)
            print(a, file=sys.stderr)
        return ([], 4)

    flipped = reconcile_approvals(repo, cfg, dry_run=dry_run)
    if flipped:
        logger.info(f"approved {len(flipped)} clip(s) by reconcile: {flipped[:5]}")

    statuses = ("approved",) if cfg.human_review else ("quality_pass", "approved")
    end_of_today_iso = _compute_today_window_end(cfg, now=now_utc)
    rows = repo.clips_for_upload_due(end_of_today_iso, statuses=statuses)
    if not rows:
        logger.info("daily_upload: no candidates for today's window")
        return ([], 0)

    results: List = []
    recovered_clip_ids: List[str] = []
    padded_clip_ids: List[str] = []
    api_rejected: List[str] = []
    api_unreachable: List[str] = []
    quota_exceeded: List[str] = []
    for row in rows:
        result = upload_one_clip(
            repo=repo, cfg=cfg, ledger=ledger, youtube=youtube,
            clip_id=row["clip_id"],
            dry_run=dry_run,
            ollama_host=ollama_host,
            now_utc=now_utc,
        )
        results.append(result)

        # Distinguish recovered_slot (intended past) from generic future-too-near pad.
        if getattr(result, "was_padded", False):
            intended = _parse_iso_z(row["publish_at_utc"])
            if intended is not None and intended < now_utc:
                recovered_clip_ids.append(result.clip_id)
            else:
                padded_clip_ids.append(result.clip_id)

        if result.outcome == UploadOutcome.api_rejected:
            api_rejected.append(f"{result.clip_id}: {result.reason}")
        elif result.outcome == UploadOutcome.api_unreachable:
            api_unreachable.append(f"{result.clip_id}: {result.reason}")
        elif result.outcome == UploadOutcome.quota_exceeded:
            quota_exceeded.append(result.clip_id)
            logger.warning("daily_upload: quota tripped; aborting batch")
            break

    if not dry_run:
        if recovered_clip_ids:
            append_alert(
                logs_dir, kind="recovered_slot",
                message=(
                    f"{len(recovered_clip_ids)} clip(s) had past-due slots "
                    f"recovered: {recovered_clip_ids[:5]}"
                ),
            )
        if padded_clip_ids:
            append_alert(
                logs_dir, kind="publish_at_padded",
                message=(
                    f"{len(padded_clip_ids)} clip(s) had publishAt padded to "
                    f"now+20m: {padded_clip_ids[:5]}"
                ),
            )
        if quota_exceeded:
            append_alert(
                logs_dir, kind="upload_quota_exceeded",
                message=(
                    f"{len(quota_exceeded)} clip(s) skipped after quota cap: "
                    f"{quota_exceeded[:5]}"
                ),
            )

    summary: dict[str, int] = {}
    for r in results:
        key = r.outcome.value
        summary[key] = summary.get(key, 0) + 1
    summary_str = ", ".join(f"{k}={v}" for k, v in sorted(summary.items()))
    logger.info(f"daily_upload summary: {summary_str} (total={len(results)})")
    return (results, 0)


def _print_summary(results) -> None:
    if not results:
        print("(no results)")
        return
    print()
    print(f"{'clip_id':<32} {'outcome':<28} {'reason':<60}")
    print("-" * 130)
    for r in results:
        reason = (r.reason or "")[:60]
        print(f"{r.clip_id[:32]:<32} {r.outcome.value:<28} {reason:<60}")
    print("-" * 130)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"total: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.daily_upload")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="propagate dry-run through reconcile_approvals + upload_one_clip; "
             "no DB writes, no API calls, no OAuth refresh",
    )
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.abs_path(cfg.paths.logs_dir))

    db_path = cfg.abs_path(cfg.paths.state_db)
    if not db_path.exists():
        logger.error(
            f"state.db not found at {db_path}. "
            f"Run `python -m src.bootstrap --init-db` first."
        )
        return 1

    conn = connect(db_path)
    repo = Repository(conn)

    try:
        # Build expensive shared clients only in real-upload mode.
        from src.quota_ledger import QuotaLedger
        ledger = QuotaLedger(repo.conn, ceiling_units=int(cfg.youtube_quota_ceiling_units))
        youtube = None
        if not args.dry_run:
            from src.integrations.youtube import build_youtube_client
            youtube = build_youtube_client(cfg)
        ollama_host = os.environ.get("OLLAMA_HOST")

        results, code = run_today(
            repo=repo, cfg=cfg, ledger=ledger, youtube=youtube,
            dry_run=args.dry_run, ollama_host=ollama_host,
        )
        _print_summary(results)
        return code
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

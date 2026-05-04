"""Phase 5 uploader CLI.

Examples:
    python -m src.uploader                                       # all clips ready for upload
    python -m src.uploader --clip-id <id>                        # single clip
    python -m src.uploader --clip-id <id> --publish-at <ISO>     # set publish_at_utc inline
    python -m src.uploader --dry-run                             # bulk dry-run (only clips with publish_at_utc)
    python -m src.uploader --dry-run --clip-id <id> --publish-at <ISO>
                                                                  # single-clip dry-run, no DB write
    python -m src.uploader --config alt.yaml

Exit codes:
    0  ok
    1  state.db missing
    2  --clip-id not found in DB
    3  invalid --publish-at value (parse failure or naive datetime)
    4  orphan_reconcile_required (inconsistent marker found at startup)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from src.config_loader import load_config
from src.observability import setup_logging
from src.state import Repository, connect


def _parse_publish_at(value: str) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp; require timezone offset.

    Accepts 'Z' (UTC) or '+HH:MM' offsets. Returns None on parse failure or
    naive datetime so the CLI can exit cleanly with code 3.
    """
    if not value:
        return None
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return None
    return dt.astimezone(timezone.utc)


def _print_summary(results) -> None:
    if not results:
        print("(no results)")
        return
    print()
    print(f"{'clip_id':<32} {'outcome':<28} {'youtube_video_id':<14} {'reason':<40}")
    print("-" * 120)
    for r in results:
        yt_id = (r.youtube_video_id or "")[:14]
        reason = (r.reason or "")[:40]
        print(f"{r.clip_id[:32]:<32} {r.outcome.value:<28} {yt_id:<14} {reason:<40}")
    print("-" * 120)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"total: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.uploader")
    parser.add_argument("--clip-id", help="upload a single clip instead of the full queue")
    parser.add_argument(
        "--publish-at",
        help="ISO 8601 with timezone offset; only valid with --clip-id. "
             "Sets clips.publish_at_utc (real mode) or carries in-memory (--dry-run).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the insert body and write it to output/dry_run/{clip_id}.json. "
             "No API call. No DB write. No OAuth refresh. No ledger record.",
    )
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    if args.publish_at and not args.clip_id:
        print("--publish-at requires --clip-id", file=sys.stderr)
        return 3

    cfg = load_config(args.config)
    setup_logging(cfg.abs_path(cfg.paths.logs_dir))

    db_path = cfg.abs_path(cfg.paths.state_db)
    if not db_path.exists():
        logger.error(f"state.db not found at {db_path}. Run `python -m src.bootstrap --init-db` first.")
        return 1

    explicit_publish_at = None
    if args.publish_at:
        explicit_publish_at = _parse_publish_at(args.publish_at)
        if explicit_publish_at is None:
            print(
                f"Invalid --publish-at {args.publish_at!r}: must be ISO 8601 with timezone (e.g. "
                "'2026-05-04T13:00:00Z' or '2026-05-04T13:00:00+00:00').",
                file=sys.stderr,
            )
            return 3

    conn = connect(db_path)
    repo = Repository(conn)

    try:
        # Lazy-import to avoid OAuth cost in dry-run-only / single-clip-dry-run paths.
        from src.uploader.runner import (
            UploadOutcome,
            reconcile_orphans,
            run_all,
            upload_one_clip,
        )

        # Orphan reconcile gate runs FIRST so a poisoned state aborts before any
        # API call, dry-run JSON, or single-clip lookup.
        ok, reconcile_alerts = reconcile_orphans(repo=repo, cfg=cfg)
        if not ok:
            for a in reconcile_alerts:
                from src.observability import append_alert
                append_alert(
                    cfg.abs_path(cfg.paths.logs_dir),
                    kind="orphan_reconcile_required", message=a,
                )
                print(a, file=sys.stderr)
            return 4

        # Build the YouTube client only in real-upload paths. Dry-run skips
        # this so OAuth tokens never refresh during offline lints.
        youtube = None
        ledger = None
        if not args.dry_run:
            from src.integrations.youtube import build_youtube_client
            from src.quota_ledger import QuotaLedger
            youtube = build_youtube_client(cfg)
            ledger = QuotaLedger(repo.conn, ceiling_units=int(cfg.youtube_quota_ceiling_units))
        else:
            # Dry-run still needs a ledger object so resumable.do_resumable_upload's
            # signature is consistent — but resumable is never actually called in
            # dry-run because runner.py short-circuits before step 9.
            from src.quota_ledger import QuotaLedger
            ledger = QuotaLedger(repo.conn, ceiling_units=int(cfg.youtube_quota_ceiling_units))

        ollama_host = os.environ.get("OLLAMA_HOST")

        if args.clip_id:
            row = repo.conn.execute(
                "SELECT clip_id FROM clips WHERE clip_id=?", (args.clip_id,)
            ).fetchone()
            if row is None:
                print(f"clip_id {args.clip_id!r} not in DB.", file=sys.stderr)
                return 2
            result = upload_one_clip(
                repo=repo, cfg=cfg, ledger=ledger, youtube=youtube,
                clip_id=args.clip_id,
                dry_run=args.dry_run,
                explicit_publish_at=explicit_publish_at,
                ollama_host=ollama_host,
            )
            _print_summary([result])
            return 0

        results = run_all(
            repo=repo, cfg=cfg, ledger=ledger, youtube=youtube,
            dry_run=args.dry_run, ollama_host=ollama_host,
        )
        _print_summary(results)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

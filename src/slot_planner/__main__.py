"""Phase 6 slot_planner CLI.

Examples:
    python -m src.slot_planner                          # all eligible quality_pass clips
    python -m src.slot_planner --clip-id <id>           # single clip
    python -m src.slot_planner --force                  # re-slot quality_pass clips with publish_at_utc set
                                                        # (gated: never re-slots approved or uploaded)
    python -m src.slot_planner --dry-run                # print allocation, no rename, no DB write
    python -m src.slot_planner --config alt.yaml

Exit codes:
    0  ok
    1  state.db missing
    2  --clip-id not found in DB
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo

from loguru import logger

from src.config_loader import load_config
from src.observability import setup_logging
from src.slot_planner.allocator import allocate_slots
from src.slot_planner.runner import (
    SlotOutcome,
    SlotResult,
    reconcile_slot_renames,
    run_all,
    slot_one_clip,
)
from src.state import Repository, connect


def _print_summary(results: List[SlotResult]) -> None:
    if not results:
        print("(no results)")
        return
    print()
    print(f"{'clip_id':<32} {'outcome':<26} {'publish_slot_local':<20} {'output':<60}")
    print("-" * 140)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
        out = (r.output_path or "")[-60:]
        slot = r.publish_slot_local or ""
        print(f"{r.clip_id[:32]:<32} {r.outcome.value:<26} {slot:<20} {out:<60}")
    print("-" * 140)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"total: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.slot_planner")
    parser.add_argument("--clip-id", help="slot a single clip instead of the full queue")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-slot quality_pass clips with publish_at_utc already set "
             "(gated: never re-slots approved or uploaded clips)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute allocation and print, no rename, no DB writes",
    )
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.abs_path(cfg.paths.logs_dir))

    db_path = cfg.abs_path(cfg.paths.state_db)
    if not db_path.exists():
        logger.error(f"state.db not found at {db_path}. Run `python -m src.bootstrap --init-db` first.")
        return 1

    conn = connect(db_path)
    repo = Repository(conn)

    try:
        if args.clip_id:
            row = repo.conn.execute(
                "SELECT clip_id FROM clips WHERE clip_id=?", (args.clip_id,),
            ).fetchone()
            if row is None:
                print(f"clip_id {args.clip_id!r} not in DB.", file=sys.stderr)
                return 2

            # Single-clip path: still run reconcile to be safe, then allocate
            # one slot from the same grid logic and apply it.
            if not args.dry_run:
                reconcile_slot_renames(repo, cfg)

            now_local = datetime.now(ZoneInfo(cfg.timezone))
            assignments, overflow = allocate_slots(
                clip_ids=[args.clip_id],
                now_local=now_local,
                upload_slots=list(cfg.upload_slots),
                days_per_run=int(cfg.days_per_run),
                clips_per_day=int(cfg.clips_per_day),
                timezone_name=cfg.timezone,
            )
            if not assignments:
                print(
                    f"no eligible slot in next {cfg.days_per_run} days for "
                    f"{args.clip_id} (now={now_local.isoformat()})",
                    file=sys.stderr,
                )
                return 0
            result = slot_one_clip(
                repo=repo, cfg=cfg, clip_id=args.clip_id,
                slot=assignments[0], force=args.force, dry_run=args.dry_run,
            )
            _print_summary([result])
            return 0

        results = run_all(repo, cfg, force=args.force, dry_run=args.dry_run)
        _print_summary(results)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

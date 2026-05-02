"""Quality screen CLI (Phase 4.5).

Examples:
    python -m src.quality_screen                          # all clips at status='rendered' (publish_at_utc null)
    python -m src.quality_screen --clip-id <id>           # single clip
    python -m src.quality_screen --force                  # re-screen rendered/quality_pass/rejected_quality
                                                          # (gated against scheduled/uploaded)
    python -m src.quality_screen --dry-run                # all probes + dedup, no DB writes, no file moves
    python -m src.quality_screen --config alt.yaml
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from src.config_loader import load_config
from src.observability import setup_logging
from src.quality_screen.runner import (
    QualityOutcome,
    QualityResult,
    run_all,
    screen_one_clip,
)
from src.state import Repository, connect


def _print_summary(results: list[QualityResult]) -> None:
    print()
    print(f"{'clip_id':<32} {'outcome':<24} {'dur':>6} {'loud':<6} {'reason':<40}")
    print("-" * 120)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
        loud = r.loudness_band or ""
        reason = (r.reason or "")[:40]
        print(f"{r.clip_id[:32]:<32} {r.outcome.value:<24} {r.duration_s:>6.1f} {loud:<6} {reason:<40}")
    print("-" * 120)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"total: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.quality_screen")
    parser.add_argument("--clip-id", help="screen a single clip instead of the full queue")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-screen clips at status='rendered'/'quality_pass'/'rejected_quality' "
             "(skipped against scheduled/uploaded)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="all probes including ffmpeg loudness + frame extraction, but no DB writes / no file moves",
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

    if args.clip_id:
        row = repo.conn.execute(
            "SELECT clip_id FROM clips WHERE clip_id=?", (args.clip_id,)
        ).fetchone()
        if row is None:
            print(f"clip_id {args.clip_id!r} not in DB.", file=sys.stderr)
            conn.close()
            return 2
        result = screen_one_clip(
            repo=repo, cfg=cfg, clip_id=args.clip_id,
            force=args.force, dry_run=args.dry_run,
        )
        _print_summary([result])
        conn.close()
        return 0

    results = run_all(repo, cfg, force=args.force, dry_run=args.dry_run)
    _print_summary(results)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

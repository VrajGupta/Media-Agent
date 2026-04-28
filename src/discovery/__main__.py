"""Discovery CLI.

Examples:
    python -m src.discovery
    python -m src.discovery --keyword "Joe Rogan"
    python -m src.discovery --force            # bypass cooldown
    python -m src.discovery --dry-run          # API + quota recorded, no DB writes
    python -m src.discovery --config alt.yaml
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from src.config_loader import load_config
from src.discovery.runner import KeywordResult, run_all, run_for_keyword
from src.integrations import build_youtube_client
from src.observability import setup_logging
from src.quota_ledger import QuotaLedger
from src.state import Repository, connect


def _print_summary(results: list[KeywordResult]) -> None:
    print()
    print(f"{'keyword':<20} {'status':<10} {'fetched':>8} {'enriched':>9} {'long':>5} {'pass':>5} {'inserted':>9} {'quota':>6}")
    print("-" * 80)
    for r in results:
        status = "skipped" if r.skipped else "ok"
        print(
            f"{r.keyword[:20]:<20} {status:<10} {r.fetched:>8} {r.enriched:>9} "
            f"{r.passed_duration:>5} {r.passed_threshold:>5} {r.inserted:>9} {r.quota_units_used:>6}"
        )
    total_quota = sum(r.quota_units_used for r in results)
    total_inserted = sum(r.inserted for r in results)
    print("-" * 80)
    print(f"total: inserted={total_inserted} quota_units={total_quota}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.discovery")
    parser.add_argument("--keyword", help="run a single keyword (default: all from config)")
    parser.add_argument("--force", action="store_true", help="bypass cooldown guard")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API calls + quota recorded; no videos/niche/attempts writes",
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
    ledger = QuotaLedger(conn, cfg.youtube_quota_ceiling_units)

    try:
        youtube = build_youtube_client(cfg)
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    if args.keyword:
        result = run_for_keyword(
            cfg, repo, ledger, youtube, args.keyword,
            force=args.force, dry_run=args.dry_run,
        )
        _print_summary([result])
    else:
        results = run_all(
            cfg, repo, ledger, youtube,
            force=args.force, dry_run=args.dry_run,
        )
        _print_summary(results)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

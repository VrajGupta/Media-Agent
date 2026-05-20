"""CLI: python -m src.topic_ingest [--dry-run]

Runs full RSS ingest against cfg.topic_ingest.feeds and prints a summary.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config_loader import load_config
from src.state import Repository, connect, initialize_schema
from src.topic_ingest.runner import fetch_unscripted_topics


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.topic_ingest")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute topics without writing to DB")
    args = parser.parse_args()

    cfg = load_config(args.config)
    db_path = cfg.abs_path(cfg.paths.state_db)
    conn = connect(db_path)
    initialize_schema(conn)
    repo = Repository(conn)

    topics = fetch_unscripted_topics(cfg, repo, dry_run=args.dry_run)

    label = "(dry-run) " if args.dry_run else ""
    print(f"topic_ingest {label}complete: {len(topics)} new topic(s)")
    for t in topics:
        print(f"  [{t['source_feed']}] {t['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

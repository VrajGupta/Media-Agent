"""Phase 6 retention CLI.

Examples:
    python -m src.retention --dry-run            # always dry-run in Phase 6
    python -m src.retention --config alt.yaml

Real deletion is reserved for Phase 7. The CLI prints the candidate list
so the user can sanity-check what would be removed.

Exit codes:
    0  ok
    1  state.db missing
"""

from __future__ import annotations

import argparse

from loguru import logger

from src.config_loader import load_config
from src.observability import setup_logging
from src.retention.cleanup import run_all
from src.state import Repository, connect


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.retention")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="(default in Phase 6) enumerate candidates without deleting",
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
        result = run_all(repo, cfg, dry_run=True)
    finally:
        conn.close()

    print()
    print("retention candidates (Phase 6 dry-run; Phase 7 enables deletion):")
    print(f"  raw videos:          {len(result.would_delete_raw)}")
    print(f"  transcripts:         {len(result.would_delete_transcripts)}")
    print(f"  output/pending:      {len(result.would_delete_output_pending)}")
    print(f"  output/approved:     {len(result.would_delete_output_approved)}")
    print(f"  output/rejected:     {len(result.would_delete_output_rejected)}")
    print(f"  dup_hashes (rows):   {result.would_prune_dup_hashes}")
    print(f"  quota_usage (rows):  {result.would_prune_quota_usage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Phase 7 retention CLI.

Examples:
    python -m src.retention --dry-run            # enumerate candidates, no deletion
    python -m src.retention                      # REAL MODE: actually delete
    python -m src.retention --config alt.yaml

By default (no flag), this performs real deletion. Pass --dry-run to
inspect candidates first. The CLI mirrors the rest of the project: real
mode is the default, dry-run is opt-in.

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
        help="enumerate candidates without deleting (default: real mode)",
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
        result = run_all(repo, cfg, dry_run=args.dry_run)
    finally:
        conn.close()

    label = "dry-run candidates" if args.dry_run else "real-mode results"
    print()
    print(f"retention sweep ({label}):")
    print(f"  raw videos:          would={len(result.would_delete_raw)}  deleted={result.deleted_raw}")
    print(f"  transcripts:         would={len(result.would_delete_transcripts)}  deleted={result.deleted_transcripts}")
    print(f"  output/pending:      would={len(result.would_delete_output_pending)}  deleted={result.deleted_output_pending}")
    print(f"  output/approved:     would={len(result.would_delete_output_approved)}  deleted={result.deleted_output_approved}")
    print(f"  output/rejected:     would={len(result.would_delete_output_rejected)}  deleted={result.deleted_output_rejected}")
    print(f"  dup_hashes (rows):   would={result.would_prune_dup_hashes}  pruned={result.pruned_dup_hashes}")
    print(f"  quota_usage (rows):  would={result.would_prune_quota_usage}  pruned={result.pruned_quota_usage}")
    print(f"  vacuum:              due={result.would_vacuum}  ran={result.vacuumed}")
    print(f"  already_gone:        {result.already_gone}")
    print(f"  delete_errors:       {len(result.delete_errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

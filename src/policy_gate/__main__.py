"""Policy gate CLI (Phase 4.5).

Examples:
    python -m src.policy_gate                           # all clips at status='selected'
    python -m src.policy_gate --clip-id <id>            # single clip
    python -m src.policy_gate --force                   # re-gate selected/policy_pass/rejected_policy
    python -m src.policy_gate --dry-run                 # call Ollama, print verdicts, no DB writes
    python -m src.policy_gate --config alt.yaml
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from src.config_loader import load_config
from src.observability import setup_logging
from src.policy_gate.runner import (
    PolicyOutcome,
    PolicyResult,
    gate_one_clip,
    run_all,
)
from src.state import Repository, connect


def _print_summary(results: list[PolicyResult]) -> None:
    print()
    print(f"{'clip_id':<32} {'outcome':<24} {'check':<14} {'value':<12} {'reason':<30}")
    print("-" * 120)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
        check = r.failed_check or ""
        value = r.failed_value or ""
        reason = (r.reason or "")[:30]
        print(f"{r.clip_id[:32]:<32} {r.outcome.value:<24} {check:<14} {value:<12} {reason:<30}")
    print("-" * 120)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"total: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.policy_gate")
    parser.add_argument("--clip-id", help="gate a single clip instead of the full queue")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-gate clips at status='policy_pass' or 'rejected_policy' "
             "(skipped against rendered/scheduled/uploaded)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="full pipeline including Ollama, but no DB writes",
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
        result = gate_one_clip(
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

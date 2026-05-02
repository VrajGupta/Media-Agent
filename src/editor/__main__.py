"""Editor CLI.

Examples:
    python -m src.editor                            # all clips at status='policy_pass'
    python -m src.editor --clip-id <id>             # single clip
    python -m src.editor --force                    # re-render rendered clips
                                                    # (gated: only if not yet scheduled/uploaded)
    python -m src.editor --dry-run                  # build ASS + argv, no ffmpeg, no DB writes
    python -m src.editor --config alt.yaml

Phase 4.5 introduced policy_gate between selector and editor. Clips must
pass policy_gate (status='policy_pass') before this CLI will render them.
Run `python -m src.policy_gate` first to advance selected clips into
policy_pass / rejected_policy.
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from src.config_loader import load_config
from src.editor.runner import EditorOutcome, EditorResult, render_one_clip, run_all
from src.observability import setup_logging
from src.state import Repository, connect


def _print_summary(results: list[EditorResult]) -> None:
    print()
    print(f"{'clip_id':<32} {'outcome':<26} {'dur':>6} {'output':<60}")
    print("-" * 130)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
        out = (r.output_path or "")[-60:]
        print(f"{r.clip_id[:32]:<32} {r.outcome.value:<26} {r.duration_s:>6.1f} {out:<60}")
    print("-" * 130)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"total: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.editor")
    parser.add_argument("--clip-id", help="render a single clip instead of the full queue")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-render clips at status='rendered' (skipped if already scheduled or uploaded)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build ASS file + ffmpeg argv, print, no subprocess invocation, no DB writes",
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
        row = repo.conn.execute("SELECT clip_id FROM clips WHERE clip_id=?", (args.clip_id,)).fetchone()
        if row is None:
            print(
                f"clip_id {args.clip_id!r} not in DB.",
                file=sys.stderr,
            )
            conn.close()
            return 2
        result = render_one_clip(
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

"""Selector CLI.

Examples:
    python -m src.selector                            # all rows where status in (lang_ok, transcribed)
    python -m src.selector --video-id <id>            # single video
    python -m src.selector --force                    # re-rank from cache (also re-checks selected)
    python -m src.selector --retranscribe             # also re-pay Whisper, overwrites cache
    python -m src.selector --dry-run                  # full pipeline, no DB writes
    python -m src.selector --config alt.yaml
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from src.config_loader import load_config
from src.observability import append_alert, setup_logging
from src.selector.runner import (
    SelectorModelLoadError,
    SelectorOutcome,
    SelectorResult,
    _make_whisper_loader,
    run_all,
    select_one_video,
)
from src.state import Repository, connect


def _print_summary(results: list[SelectorResult]) -> None:
    print()
    print(f"{'video_id':<14} {'outcome':<26} {'method':<16} {'wins':>5} {'clips':>5} {'reason':<30}")
    print("-" * 100)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
        method = r.selection_method or ""
        reason = (r.reason or "")[:30]
        print(f"{r.video_id[:14]:<14} {r.outcome.value:<26} {method:<16} {r.n_windows:>5} {r.n_clips_selected:>5} {reason:<30}")
    print("-" * 100)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"total: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.selector")
    parser.add_argument("--video-id", help="run a single video instead of the full queue")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-rank from cached transcript (also re-runs videos at status='selected')",
    )
    parser.add_argument(
        "--retranscribe",
        action="store_true",
        help="also re-pay Whisper and overwrite the cache",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="full pipeline including Whisper + Ollama, but no DB / file writes",
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

    if args.video_id:
        row = repo.get_video(args.video_id)
        if row is None:
            print(
                f"video_id {args.video_id!r} not in DB; run `python -m src.discovery` first.",
                file=sys.stderr,
            )
            conn.close()
            return 2
        whisper_loader = _make_whisper_loader(cfg)
        try:
            result = select_one_video(
                repo=repo,
                cfg=cfg,
                video_id=args.video_id,
                whisper_model_loader=whisper_loader,
                force=args.force,
                retranscribe=args.retranscribe,
                dry_run=args.dry_run,
            )
        except SelectorModelLoadError as exc:
            logger.error(f"whisper model load failed: {exc}")
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="selector_model_load",
                message=f"whisper model load failed: {exc}",
            )
            conn.close()
            return 1
        _print_summary([result])
        conn.close()
        return 0

    try:
        results = run_all(
            repo, cfg,
            force=args.force,
            retranscribe=args.retranscribe,
            dry_run=args.dry_run,
        )
    except SelectorModelLoadError as exc:
        logger.error(f"whisper model load failed: {exc}")
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="selector_model_load",
            message=f"whisper model load failed: {exc}",
        )
        conn.close()
        return 1

    _print_summary(results)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

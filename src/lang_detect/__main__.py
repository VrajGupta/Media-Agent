"""Language detection CLI.

Examples:
    python -m src.lang_detect                       # all rows where status='downloaded'
    python -m src.lang_detect --video-id <id>       # single video
    python -m src.lang_detect --force               # also re-check status='lang_ok'
    python -m src.lang_detect --dry-run             # detect + print verdict, no DB writes
    python -m src.lang_detect --config alt.yaml
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from src.config_loader import load_config
from src.lang_detect.runner import (
    LangDetectModelLoadError,
    LangDetectOutcome,
    LangDetectResult,
    LangDetector,
    detect_one,
    preflight_status,
    run_all,
)
from src.observability import append_alert, setup_logging
from src.state import Repository, connect


def _print_summary(results: list[LangDetectResult]) -> None:
    print()
    print(f"{'video_id':<14} {'outcome':<26} {'lang':<6} {'conf':>6} {'reason':<30}")
    print("-" * 86)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.outcome.value] = counts.get(r.outcome.value, 0) + 1
        lang = r.detected_lang or ""
        conf = f"{r.confidence:.2f}" if r.confidence is not None else ""
        reason = (r.reason or "")[:30]
        print(f"{r.video_id[:14]:<14} {r.outcome.value:<26} {lang:<6} {conf:>6} {reason:<30}")
    print("-" * 86)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"total: {summary}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.lang_detect")
    parser.add_argument("--video-id", help="run a single video instead of the full downloaded queue")
    parser.add_argument(
        "--force",
        action="store_true",
        help="also re-check rows already at status='lang_ok' (can flip to rejected_language)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run Whisper + print verdict, no DB writes",
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

        skip = preflight_status(row, args.force)
        if skip is not None:
            print(f"skip: {skip.value}")
            conn.close()
            return 0

        try:
            detector = LangDetector(cfg)
        except Exception as exc:
            logger.exception("lang_detect model load failed")
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="lang_detect_model_load",
                message=f"lang_detect model load failed: {exc}",
            )
            conn.close()
            return 1

        result = detect_one(detector, repo, cfg, args.video_id, force=args.force, dry_run=args.dry_run)
        _print_summary([result])
        conn.close()
        return 0

    # Batch path.
    try:
        results = run_all(repo, cfg, force=args.force, dry_run=args.dry_run)
    except LangDetectModelLoadError as exc:
        logger.error(f"lang_detect model load failed: {exc}")
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="lang_detect_model_load",
            message=f"lang_detect model load failed: {exc}",
        )
        conn.close()
        return 1

    _print_summary(results)

    error_count = sum(1 for r in results if r.outcome == LangDetectOutcome.error_inference)
    if error_count > 0:
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="lang_detect_inference",
            message=f"lang_detect run: {error_count} inference errors, see agent.log for details",
        )

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

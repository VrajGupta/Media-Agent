"""Downloader CLI.

Examples:
    python -m src.downloader                       # all rows where status='discovered'
    python -m src.downloader --video-id <id>       # single video
    python -m src.downloader --config alt.yaml
"""

from __future__ import annotations

import argparse
import sys

from loguru import logger

from src.config_loader import load_config
from src.downloader.runner import DownloadResult, download_one_video, run_all
from src.observability import setup_logging
from src.state import Repository, connect


def _print_summary(results: list[DownloadResult]) -> None:
    print()
    print(f"{'video_id':<14} {'status':<20} {'detail':<40} {'MB':>8}")
    print("-" * 86)
    by_status: dict[str, int] = {}
    total_bytes = 0
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        total_bytes += r.bytes_downloaded
        mb = r.bytes_downloaded / 1024 / 1024 if r.bytes_downloaded else 0
        print(f"{r.video_id[:14]:<14} {r.status:<20} {r.detail[:40]:<40} {mb:>8.1f}")
    print("-" * 86)
    summary = ", ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
    print(f"total: {summary}; downloaded {total_bytes / 1024 / 1024:.1f} MB")


def main() -> int:
    parser = argparse.ArgumentParser(prog="src.downloader")
    parser.add_argument("--video-id", help="run a single video instead of the full discovered queue")
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
        # Pre-flight check so the user gets a clean exit code for missing rows.
        if repo.get_video(args.video_id) is None:
            print(
                f"video_id {args.video_id!r} not in DB; run `python -m src.discovery` first.",
                file=sys.stderr,
            )
            conn.close()
            return 2
        result = download_one_video(cfg, repo, args.video_id)
        _print_summary([result])
    else:
        results = run_all(cfg, repo)
        _print_summary(results)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

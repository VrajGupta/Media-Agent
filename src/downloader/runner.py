"""Downloader orchestration.

Per-video flow:
  lookup row -> idempotency repair -> free-disk guard -> probe ->
  hard-cap pre-flight -> soft-cap eviction -> download ->
  post-download hard-cap re-check -> status update.

Sequential. No parallelism.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from src.config_loader import Config
from src.downloader import disk_budget, ytdlp_runner
from src.observability import append_alert
from src.state import Repository

GB = 1024 ** 3


@dataclass
class DownloadResult:
    video_id: str
    status: str  # ok | skipped | repaired | rejected_format | rejected_download | disk_full | missing | already_rejected
    detail: str = ""
    bytes_downloaded: int = 0


def _safety_buffer(estimate: int) -> int:
    return int(estimate * 1.2)  # 20% headroom on probe estimates


def download_one_video(
    cfg: Config, repo: Repository, video_id: str
) -> DownloadResult:
    raw_dir = cfg.abs_path(cfg.paths.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest_path = raw_dir / f"{video_id}.mp4"

    row = repo.get_video(video_id)
    if row is None:
        logger.warning(f"video_id {video_id} not in DB")
        return DownloadResult(video_id, "missing", "row not found")

    status = row["status"]

    # ---- 1. Idempotency / repair ----
    if dest_path.exists() and dest_path.stat().st_size > 0:
        if status == "downloaded":
            logger.info(f"skip: {video_id} already downloaded")
            return DownloadResult(video_id, "skipped", "already downloaded",
                                  dest_path.stat().st_size)
        if status == "discovered":
            repo.set_video_status(video_id, "downloaded")
            logger.info(f"repaired orphan: {video_id} file present, status was discovered")
            return DownloadResult(video_id, "repaired",
                                  "file existed; status flipped to downloaded",
                                  dest_path.stat().st_size)
        if status.startswith("rejected_"):
            try:
                dest_path.unlink()
                ytdlp_runner.cleanup_partial(dest_path)
                logger.warning(f"removed stray file for already-rejected {video_id}")
            except OSError as e:
                logger.warning(f"could not remove stray file for {video_id}: {e}")
            return DownloadResult(video_id, "already_rejected", row["rejection_reason"] or status)

    # Already-rejected rows without a file: skip without action.
    if status.startswith("rejected_"):
        logger.info(f"skip: {video_id} already rejected ({row['rejection_reason'] or status})")
        return DownloadResult(video_id, "already_rejected", row["rejection_reason"] or status)

    # 'downloaded' status but file missing: re-fetch.
    if status == "downloaded":
        logger.warning(f"re-fetching {video_id}: status=downloaded but file missing")

    # ---- 2. Free-disk safety floor ----
    floor = cfg.free_disk_safety_floor_gb * GB
    if disk_budget.free_disk_bytes(raw_dir) < floor:
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="disk_safety_floor",
            message=f"filesystem free space below {cfg.free_disk_safety_floor_gb} GB; downloader halting",
        )
        return DownloadResult(video_id, "disk_full", "filesystem free space below safety floor")

    # ---- 3. Probe ----
    probe_out = ytdlp_runner.probe(video_id, cfg.download_min_height, cfg.download_max_height)
    if probe_out.error:
        repo.set_video_status(video_id, "rejected_download", reason=probe_out.error[:200])
        logger.warning(f"probe failed for {video_id}: {probe_out.error[:200]}")
        return DownloadResult(video_id, "rejected_download", probe_out.error[:200])
    if probe_out.available_height is None:
        repo.set_video_status(video_id, "rejected_format",
                              reason=f"no stream >={cfg.download_min_height}p")
        logger.info(f"rejected_format: {video_id} (no stream >={cfg.download_min_height}p)")
        return DownloadResult(video_id, "rejected_format",
                              f"no stream >={cfg.download_min_height}p")

    estimate = _safety_buffer(
        probe_out.filesize_approx_bytes or cfg.download_estimated_bytes_per_video
    )

    # ---- 4. Hard-cap pre-flight ----
    if disk_budget.would_exceed_hard_cap(cfg, raw_dir, estimate):
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="disk_hard_cap",
            message=f"hard cap {cfg.disk_hard_cap_gb} GB reached; aborting download for {video_id}",
        )
        return DownloadResult(video_id, "disk_full", "hard cap reached")

    # ---- 5. Soft-cap eviction (Phase 2: usually a no-op) ----
    if disk_budget.bytes_available(cfg, raw_dir) < estimate:
        report = disk_budget.evict_to_soft_cap(cfg, raw_dir, repo)
        if report.deleted_count:
            logger.info(
                f"eviction freed {report.freed_bytes / GB:.2f} GB ({report.deleted_count} files)"
            )
        else:
            logger.info(
                f"eviction had no eligible victims (halted_reason={report.halted_reason})"
            )

    # ---- 6. Download ----
    out = ytdlp_runner.download_one(
        video_id, dest_path,
        min_height=cfg.download_min_height,
        max_height=cfg.download_max_height,
    )

    # ---- 7. Post-download hard-cap re-check ----
    if out.status == "ok":
        if disk_budget.current_usage_bytes(raw_dir) > cfg.disk_hard_cap_gb * GB:
            try:
                dest_path.unlink()
            except OSError:
                pass
            ytdlp_runner.cleanup_partial(dest_path)
            repo.set_video_status(video_id, "rejected_download",
                                  reason="aborted: hard cap exceeded post-download")
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="disk_hard_cap",
                message=f"hard cap exceeded post-download for {video_id}; file removed",
            )
            return DownloadResult(video_id, "rejected_download", "hard cap exceeded post-download")

    # ---- 8. Status transition ----
    if out.status == "ok":
        repo.set_video_status(video_id, "downloaded")
        logger.info(f"downloaded: {video_id} ({out.filesize_bytes / 1024 / 1024:.1f} MB, {out.height}p)")
        return DownloadResult(video_id, "ok", f"{out.height}p", out.filesize_bytes)

    if out.status == "rejected_format":
        ytdlp_runner.cleanup_partial(dest_path)
        repo.set_video_status(video_id, "rejected_format",
                              reason=out.error_message or "below height floor")
        return DownloadResult(video_id, "rejected_format", out.error_message or "")

    # status == 'error'
    ytdlp_runner.cleanup_partial(dest_path)
    msg = (out.error_message or "unknown error")[:200]
    repo.set_video_status(video_id, "rejected_download", reason=msg)
    logger.warning(f"rejected_download: {video_id} ({msg})")
    return DownloadResult(video_id, "rejected_download", msg)


def run_all(cfg: Config, repo: Repository) -> list[DownloadResult]:
    rows = repo.videos_for_download()
    results: list[DownloadResult] = []
    for row in rows:
        result = download_one_video(cfg, repo, row["video_id"])
        results.append(result)
        if result.status == "disk_full":
            logger.warning("halting downloader: disk_full")
            break
    return results

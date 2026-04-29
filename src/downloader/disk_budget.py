"""Disk-budget guards and eviction for `data/raw/`.

Phase 2 honest caveat: eviction has no eligible victims until Phase 5 starts
uploading clips. The hard cap is what actually protects the disk during Phase 2;
the soft cap is a forward-compatible retention hook.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

GB = 1024 ** 3


def current_usage_bytes(raw_dir: Path) -> int:
    if not raw_dir.exists():
        return 0
    return sum(f.stat().st_size for f in raw_dir.glob("*.mp4") if f.is_file())


def bytes_available(cfg, raw_dir: Path) -> int:
    soft_cap_bytes = cfg.disk_soft_cap_gb * GB
    return soft_cap_bytes - current_usage_bytes(raw_dir)


def would_exceed_hard_cap(cfg, raw_dir: Path, projected_bytes: int) -> bool:
    hard_cap_bytes = cfg.disk_hard_cap_gb * GB
    return current_usage_bytes(raw_dir) + projected_bytes > hard_cap_bytes


def free_disk_bytes(raw_dir: Path) -> int:
    """Filesystem-level free space, distinct from the raw-dir budget."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(raw_dir).free


@dataclass
class EvictionReport:
    deleted_count: int = 0
    freed_bytes: int = 0
    files_deleted: list[str] = field(default_factory=list)
    halted_reason: str = ""  # 'under_soft_cap' | 'no_eligible_victims'


def evict_to_soft_cap(cfg, raw_dir: Path, repo) -> EvictionReport:
    """Delete oldest fully-uploaded raw mp4s until usage <= soft cap."""
    report = EvictionReport()
    soft_cap_bytes = cfg.disk_soft_cap_gb * GB

    if current_usage_bytes(raw_dir) <= soft_cap_bytes:
        report.halted_reason = "under_soft_cap"
        return report

    for video_id in repo.evictable_video_ids():
        if current_usage_bytes(raw_dir) <= soft_cap_bytes:
            report.halted_reason = "under_soft_cap"
            return report

        # Defensive double-check immediately before unlink — closes any race
        # where eligibility changed since the list was queried.
        if not repo.is_raw_evictable(video_id):
            continue

        path = raw_dir / f"{video_id}.mp4"
        if not path.exists():
            continue

        size = path.stat().st_size
        try:
            path.unlink()
        except OSError as e:
            logger.warning(f"eviction failed for {path}: {e}")
            continue

        report.deleted_count += 1
        report.freed_bytes += size
        report.files_deleted.append(str(path))
        logger.info(f"evicted {path.name} ({size / GB:.2f} GB)")

    report.halted_reason = (
        "under_soft_cap"
        if current_usage_bytes(raw_dir) <= soft_cap_bytes
        else "no_eligible_victims"
    )
    return report

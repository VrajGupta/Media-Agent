"""Per-script shot generator — submits N shots concurrently and downloads results.

Usage (from weekly_run / gen_run):
    from src.ai_gen.runner import generate_shots
    shot_paths = generate_shots(shots, dest_dir, client, poll_interval_s=15)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .base import GenerationStatus, Provider


@dataclass
class ShotJob:
    index: int
    prompt: str
    duration_s: int
    external_id: str | None = None
    output_path: Path | None = None
    error: str | None = None
    cost_cents: int | None = None


def generate_shots(
    shots: list[dict],
    dest_dir: Path,
    client: Provider,
    *,
    aspect_ratio: str = "9:16",
    poll_interval_s: int = 15,
    timeout_s: int = 600,
    max_concurrent: int = 2,
    repo=None,
) -> list[Path]:
    """Submit all shots, poll until done, download mp4s, return ordered paths.

    shots: list of {prompt: str, duration_s: int}
    Returns list of Path in the same order as shots.
    Raises RuntimeError if any shot fails.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[ShotJob] = [
        ShotJob(index=i, prompt=s["prompt"], duration_s=s.get("duration_s", 5))
        for i, s in enumerate(shots)
    ]

    # Submit in batches of max_concurrent
    _submit_all(jobs, client, aspect_ratio, max_concurrent)

    # Poll and download
    _wait_and_download(jobs, client, dest_dir, poll_interval_s, timeout_s)

    failed = [j for j in jobs if j.error]
    if failed:
        errs = "; ".join(f"shot {j.index}: {j.error}" for j in failed)
        raise RuntimeError(f"generate_shots: {len(failed)} shot(s) failed — {errs}")

    if repo is not None:
        for job in jobs:
            if job.cost_cents:
                repo.quota_record(
                    "openrouter", job.cost_cents, provider="openrouter",
                )

    return [j.output_path for j in jobs]  # type: ignore[return-value]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _submit_all(
    jobs: list[ShotJob], client: Provider, aspect_ratio: str, max_concurrent: int
) -> None:
    semaphore = threading.Semaphore(max_concurrent)

    def submit_one(job: ShotJob) -> None:
        with semaphore:
            try:
                job.external_id = client.submit(
                    job.prompt,
                    duration_s=job.duration_s,
                    aspect_ratio=aspect_ratio,
                )
                logger.info(
                    "ai_gen: submitted shot {} → external_id={}", job.index, job.external_id
                )
            except Exception as exc:
                job.error = str(exc)
                logger.error("ai_gen: shot {} submit failed: {}", job.index, exc)

    threads = [threading.Thread(target=submit_one, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _wait_and_download(
    jobs: list[ShotJob],
    client: Provider,
    dest_dir: Path,
    poll_interval_s: int,
    timeout_s: int,
) -> None:
    pending = [j for j in jobs if j.external_id and not j.error]

    def process_one(job: ShotJob) -> None:
        try:
            result = client.wait_for_completion(
                job.external_id,  # type: ignore[arg-type]
                poll_interval_s=poll_interval_s,
                timeout_s=timeout_s,
            )
            if result.status == GenerationStatus.SUCCEEDED and result.download_url:
                dest = dest_dir / f"shot_{job.index:02d}.mp4"
                client.download(result.download_url, dest)
                job.output_path = dest
                job.cost_cents = result.cost_cents
                logger.info("ai_gen: shot {} downloaded → {}", job.index, dest)
            else:
                job.error = result.error or "unknown failure"
                logger.error("ai_gen: shot {} failed: {}", job.index, job.error)
        except Exception as exc:
            job.error = str(exc)
            logger.error("ai_gen: shot {} error during wait/download: {}", job.index, exc)

    threads = [threading.Thread(target=process_one, args=(j,)) for j in pending]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

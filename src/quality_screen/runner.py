"""Quality screen orchestration (Phase 4.5): rendered -> quality_pass | rejected_quality.

Per-clip flow:
  preflight status -> probe duration (foundational; abort screen if missing) ->
  collect ALL failures across density, confidence, loudness, dedup ->
  on pass: insert dup_hashes rows + status='quality_pass' (one tx) ->
  on fail: relocate file to output/rejected/, then status='rejected_quality'
           (best-effort consistency: filesystem move + DB are NOT atomic).

Failure handling:
  - missing output file        -> error_no_output, status unchanged.
  - duration probe failure     -> error_probe (foundational), status unchanged.
  - any check fail             -> rejected_quality, file relocated, multi-fail
                                  reasons joined by ';'.
  - loudness measurement fails -> in-band fail-soft (treated as pass with alert).
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger

from src.config_loader import Config
from src.observability import append_alert
from src.quality_screen import (
    confidence as confidence_mod,
    dedup as dedup_mod,
    density as density_mod,
    duration as duration_mod,
    loudness as loudness_mod,
)
from src.state import Repository
from src.transcripts.clip_text import words_in_clip_window


class QualityOutcome(str, Enum):
    quality_pass = "quality_pass"
    rejected_quality = "rejected_quality"
    skipped_wrong_status = "skipped_wrong_status"
    skipped_already_screened = "skipped_already_screened"
    skipped_locked = "skipped_locked"           # scheduled or uploaded
    error_no_output = "error_no_output"
    error_no_transcript = "error_no_transcript"
    error_probe = "error_probe"                 # foundational fail-soft


@dataclass
class QualityResult:
    clip_id: str
    outcome: QualityOutcome
    duration_s: float = 0.0
    output_path: Optional[str] = None
    failures: list[str] = field(default_factory=list)
    loudness_band: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class _BatchAlerts:
    no_output: list[str] = field(default_factory=list)
    no_transcript: list[str] = field(default_factory=list)
    probe_failed: list[str] = field(default_factory=list)
    loudness_warn: list[str] = field(default_factory=list)
    loudness_infra: list[str] = field(default_factory=list)
    move_failed: list[str] = field(default_factory=list)


def _preflight(row: sqlite3.Row, force: bool) -> Optional[QualityOutcome]:
    status = row["status"]
    if row["publish_at_utc"] is not None or row["youtube_video_id"] is not None:
        return QualityOutcome.skipped_locked
    if status not in ("rendered", "quality_pass", "rejected_quality"):
        return QualityOutcome.skipped_wrong_status
    if status in ("quality_pass", "rejected_quality") and not force:
        return QualityOutcome.skipped_already_screened
    return None


def _load_transcript_words(transcripts_dir: Path, video_id: str) -> Optional[list[dict]]:
    path = transcripts_dir / f"{video_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"transcript unreadable for {video_id}: {exc}")
        return None
    words: list[dict] = []
    for seg in payload.get("segments", []) or []:
        words.extend(seg.get("words") or [])
    return words


def _relocate_to_rejected(
    pending_path: Path,
    rejected_dir: Path,
) -> tuple[Path, bool]:
    """Move file from output/pending/ to output/rejected/. Returns (final_path,
    move_succeeded). Best-effort: on OSError, returns (pending_path, False).
    """
    rejected_dir.mkdir(parents=True, exist_ok=True)
    target = rejected_dir / pending_path.name
    try:
        os.replace(str(pending_path), str(target))
        return (target, True)
    except OSError as exc:
        logger.warning(f"rejected-file relocation failed for {pending_path.name}: {exc}")
        return (pending_path, False)


def screen_one_clip(
    *,
    repo: Repository,
    cfg: Config,
    clip_id: str,
    force: bool = False,
    dry_run: bool = False,
) -> QualityResult:
    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id=?", (clip_id,)).fetchone()
    if row is None:
        logger.warning(f"clip_id {clip_id} not in DB")
        return QualityResult(clip_id, QualityOutcome.skipped_wrong_status, reason="not in DB")

    skip = _preflight(row, force)
    if skip is not None:
        return QualityResult(clip_id, skip, output_path=row["output_path"])

    output_path_str = row["output_path"]
    if not output_path_str:
        return QualityResult(
            clip_id, QualityOutcome.error_no_output,
            reason="output_path is null",
        )
    output_path = Path(output_path_str)
    if not output_path.exists() or output_path.stat().st_size == 0:
        return QualityResult(
            clip_id, QualityOutcome.error_no_output,
            output_path=output_path_str,
            reason="rendered file missing",
        )

    # Foundational probe — duration feeds dedup frame timestamps too.
    duration_s = duration_mod.probe_duration(output_path)
    if duration_s is None:
        return QualityResult(
            clip_id, QualityOutcome.error_probe,
            output_path=output_path_str,
            reason="ffprobe failed",
        )

    # Transcript needed for density + confidence.
    video_id = row["video_id"]
    transcripts_dir = cfg.abs_path(cfg.paths.transcripts_dir)
    all_words = _load_transcript_words(transcripts_dir, video_id)
    if all_words is None:
        return QualityResult(
            clip_id, QualityOutcome.error_no_transcript,
            output_path=output_path_str, duration_s=duration_s,
            reason="transcript missing or unreadable",
        )

    start_s = float(row["start_s"])
    end_s = float(row["end_s"])
    window_words = words_in_clip_window(all_words, start_s, end_s)
    clip_window_duration = end_s - start_s

    failures: list[str] = []
    loudness_band: Optional[str] = None
    loudness_infra_failed = False

    # Check 1: duration in [25, 65].
    dur_ok, _ = duration_mod.passes_duration(duration_s)
    if not dur_ok:
        failures.append(f"duration:{duration_s:.1f}")

    # Check 2: speech density.
    den_ok, density = density_mod.passes_density(
        window_words, clip_window_duration, float(cfg.min_speech_density),
    )
    if not den_ok:
        failures.append(f"density:{density:.2f}")

    # Check 3: word confidence.
    conf_ok, conf = confidence_mod.passes_confidence(
        window_words, float(cfg.min_word_confidence),
    )
    if not conf_ok:
        failures.append(f"confidence:{conf:.2f}")

    # Check 4: loudness — three-tier (pass / warn / reject) plus fail-soft.
    measurement = loudness_mod.measure_loudness(output_path)
    if measurement.infrastructure_failed:
        loudness_infra_failed = True
    else:
        band = loudness_mod.classify_loudness(measurement.input_i, cfg.loudness_target_lufs)
        loudness_band = band
        if band == "reject":
            failures.append(f"loudness:{measurement.input_i:.2f}")
        # 'warn' is logged via batch alert below; 'pass' is silent.

    # Check 5: dedup. Compute signals only if we have a pristine duration.
    signals = dedup_mod.compute_signals(output_path, duration_s)
    stored = repo.recent_dup_hashes(int(cfg.dedup_lookback_days))
    # Convert sqlite3.Rows to dicts for the matcher (it reads via __getitem__).
    stored_rows = [{"clip_id": r["clip_id"], "phash": r["phash"], "audio_fp": r["audio_fp"]} for r in stored]
    match = dedup_mod.find_phash_match(
        signals.phashes, stored_rows, min_hamming=int(cfg.phash_min_hamming),
    )
    if match is not None:
        failures.append(f"dedup:{match.matching_clip_id}:hamming={match.hamming_distance}")

    # ---- Apply verdict ------------------------------------------------------

    if failures:
        # Relocate file + flip status.
        if dry_run:
            return QualityResult(
                clip_id, QualityOutcome.rejected_quality,
                output_path=output_path_str, duration_s=duration_s,
                failures=failures, loudness_band=loudness_band,
                reason=";".join(failures),
            )
        rejected_dir = cfg.abs_path(cfg.paths.rejected_dir)
        new_path, moved = _relocate_to_rejected(output_path, rejected_dir)
        repo.set_clip_status(
            clip_id, "rejected_quality",
            reason=";".join(failures),
            output_path=str(new_path),
        )
        result = QualityResult(
            clip_id, QualityOutcome.rejected_quality,
            output_path=str(new_path), duration_s=duration_s,
            failures=failures, loudness_band=loudness_band,
            reason=";".join(failures),
        )
        if not moved:
            result.reason = (result.reason or "") + ";move_failed"
        return result

    # Pass — insert dedup hashes and flip status atomically (DB-only, no
    # filesystem move on the happy path).
    if dry_run:
        return QualityResult(
            clip_id, QualityOutcome.quality_pass,
            output_path=output_path_str, duration_s=duration_s,
            loudness_band=loudness_band,
        )

    dedup_rows = [(clip_id, ph, signals.audio_fp) for ph in signals.phashes]
    with repo.tx():
        repo.insert_dup_hash_rows(dedup_rows)
        repo.set_clip_status(clip_id, "quality_pass", reason=None)

    return QualityResult(
        clip_id, QualityOutcome.quality_pass,
        output_path=output_path_str, duration_s=duration_s,
        loudness_band=loudness_band,
    )


def run_all(
    repo: Repository,
    cfg: Config,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[QualityResult]:
    if force:
        rows = repo.conn.execute(
            "SELECT clip_id FROM clips "
            "WHERE status IN ('rendered','quality_pass','rejected_quality') "
            "AND publish_at_utc IS NULL AND youtube_video_id IS NULL "
            "ORDER BY clip_id"
        ).fetchall()
    else:
        rows = repo.clips_for_quality_screen()

    if not rows:
        logger.info("quality_screen: no candidates")
        return []

    alerts = _BatchAlerts()
    results: list[QualityResult] = []

    for row in rows:
        result = screen_one_clip(
            repo=repo, cfg=cfg, clip_id=row["clip_id"],
            force=force, dry_run=dry_run,
        )
        results.append(result)

        if result.outcome == QualityOutcome.error_no_output:
            alerts.no_output.append(result.clip_id)
        elif result.outcome == QualityOutcome.error_no_transcript:
            alerts.no_transcript.append(result.clip_id)
        elif result.outcome == QualityOutcome.error_probe:
            alerts.probe_failed.append(result.clip_id)
        if result.loudness_band == "warn":
            alerts.loudness_warn.append(result.clip_id)
        if result.reason and "move_failed" in result.reason:
            alerts.move_failed.append(result.clip_id)

    if not dry_run:
        alert = functools.partial(append_alert, cfg.abs_path(cfg.paths.logs_dir))
        if alerts.no_output:
            alert(kind="quality_no_output",
                  message=f"{len(alerts.no_output)} clips lacked rendered file: {alerts.no_output[:5]}")
        if alerts.no_transcript:
            alert(kind="quality_no_transcript",
                  message=f"{len(alerts.no_transcript)} clips lacked transcript: {alerts.no_transcript[:5]}")
        if alerts.probe_failed:
            alert(kind="quality_probe_failed",
                  message=f"{len(alerts.probe_failed)} clips failed ffprobe: {alerts.probe_failed[:5]}")
        if alerts.loudness_warn:
            alert(kind="loudness_warn",
                  message=(
                      f"{len(alerts.loudness_warn)} clips passed loudness in warn band "
                      f"(0.5-1.5 LUFS off target); escalate to two-pass loudnorm "
                      f"if this band fills up: {alerts.loudness_warn[:5]}"
                  ))
        if alerts.move_failed:
            alert(kind="quality_rejected_move_failed",
                  message=f"{len(alerts.move_failed)} rejected_quality clips could not be moved to output/rejected/: {alerts.move_failed[:5]}")

    summary = {o.value: 0 for o in QualityOutcome}
    for r in results:
        summary[r.outcome.value] += 1
    summary_str = ", ".join(f"{k}={v}" for k, v in summary.items() if v)
    logger.info(f"quality_screen summary: {summary_str} (total={len(results)})")
    return results

"""Phase 5 uploader orchestration: quality_pass / approved -> uploaded.

Per-clip flow (upload_one_clip):
  1. Load clip row from DB.
  2. Preflight (youtube_video_id IS NOT NULL → skipped_already_uploaded;
     status NOT IN ('quality_pass', 'approved') → skipped_wrong_status).
  3. Resolve file path with `approved` basename fallback.
  4. Resolve publish_at (real-mode persists --publish-at; dry-run is in-memory).
  5. Pad future-too-near (now + 20 min lead).
  6. Pre-upload policy re-check (using clip.hook or suggested_title — same
     as upload title input).
  7. Build insert body (pure).
  8. Dry-run branch: write JSON, no API, no DB, no OAuth.
  9. Resumable upload via do_resumable_upload (only quota call site).
  10. Persist success — orphan-marker fence + ID-first two-step:
      10-pre: write_marker(...) atomically.
      10a:    set_clip_youtube_id(...) in narrow tx.
      10b:    set_clip_status('uploaded', publish_at_utc) + upsert_upload(...) in tx.
      10-post: unlink_marker(...) (best-effort).

Runner startup (run_all + single-clip CLI both call this):
  reconcile_orphans(...) — scans output/orphans/, validates against DB. Any
  inconsistent marker aborts the run with `orphan_reconcile_required`.
"""

from __future__ import annotations

import functools
import json
import os
import socket
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from googleapiclient.errors import HttpError
from loguru import logger

from src.config_loader import Config
from src.observability import append_alert
from src.policy_gate.evaluator import PolicyVerdict, evaluate_clip_policy
from src.policy_gate import hook_sanity as hook_mod
from src.policy_gate import nsfw as nsfw_mod
from src.policy_gate import topic_filter as topic_mod
from src.quota_ledger import QuotaExceeded, QuotaLedger
from src.state import Repository
from src.transcripts.clip_text import clip_text_from_words, words_in_clip_window
from src.uploader import insert_body as insert_body_mod
from src.uploader import orphan_marker, publish_at as publish_at_mod
from src.uploader.resumable import do_resumable_upload


class UploadOutcome(str, Enum):
    uploaded = "uploaded"
    dry_run = "dry_run"
    skipped_wrong_status = "skipped_wrong_status"
    skipped_already_uploaded = "skipped_already_uploaded"
    rejected_policy_recheck = "rejected_policy_recheck"
    infrastructure_failed = "infrastructure_failed"        # Ollama re-check infra failure
    quota_exceeded = "quota_exceeded"
    api_rejected = "api_rejected"                          # YouTube HttpError (4xx/5xx)
    api_unreachable = "api_unreachable"                    # ConnectionError / timeout
    error_no_output = "error_no_output"                    # missing rendered file
    error_no_transcript = "error_no_transcript"            # transcript missing for re-check
    error_no_publish_at = "error_no_publish_at"
    error_persist_failed = "error_persist_failed"          # DB write after API success failed


@dataclass
class UploadResult:
    clip_id: str
    outcome: UploadOutcome
    youtube_video_id: Optional[str] = None
    padded_publish_at: Optional[str] = None
    was_padded: bool = False
    failed_check: Optional[str] = None
    failed_value: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class _BatchAlerts:
    no_transcript: list[str] = field(default_factory=list)
    no_output: list[str] = field(default_factory=list)
    infra_failures: list[str] = field(default_factory=list)
    api_rejected: list[str] = field(default_factory=list)
    api_unreachable: list[str] = field(default_factory=list)
    quota_exceeded: list[str] = field(default_factory=list)
    publish_at_padded: list[str] = field(default_factory=list)
    persist_failed: list[str] = field(default_factory=list)


def _resolve_file_path(cfg: Config, row: sqlite3.Row) -> Optional[Path]:
    """Resolve the rendered-clip file path with `approved` basename fallback.

    For `approved` clips, the user dragged the file from output/pending/ to
    output/approved/. clips.output_path may still point at the old pending
    path (Phase 6 owns updating it). Try the approved-dir basename first;
    fall back to output_path as-is.
    """
    output_path_str = row["output_path"]
    if not output_path_str:
        return None
    raw_path = Path(output_path_str)
    if row["status"] == "approved":
        approved_dir = cfg.abs_path(cfg.paths.approved_dir)
        approved_candidate = approved_dir / raw_path.name
        if approved_candidate.exists() and approved_candidate.stat().st_size > 0:
            return approved_candidate
    if raw_path.exists() and raw_path.stat().st_size > 0:
        return raw_path
    return None


def _load_transcript_words(transcripts_dir: Path, video_id: str) -> Optional[list[dict]]:
    """Read cached transcript JSON and flatten segments[].words[]."""
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


def _resolve_recheck_inputs(
    *,
    clip_row: Any,
    script_row: Optional[Any],
    transcripts_dir: Path,
) -> Optional[tuple[str, str]]:
    """Return (clip_text, recheck_title) for the policy re-check, or None.

    AI-gen: reads narration + title directly from script_row; no filesystem.
    Sourced: loads Whisper transcript JSON; returns None if missing/unreadable.
    """
    try:
        content_kind = clip_row["content_kind"] or "sourced"
    except (KeyError, IndexError):
        content_kind = "sourced"
    if content_kind == "ai_generated" and script_row is not None:
        return (script_row["narration"], script_row["title"])

    # Sourced path: load transcript from disk.
    video_id = clip_row["video_id"]
    all_words = _load_transcript_words(transcripts_dir, video_id or "")
    if all_words is None:
        return None
    start_s = float(clip_row["start_s"])
    end_s = float(clip_row["end_s"])
    window_words = words_in_clip_window(all_words, start_s, end_s)
    clip_text = clip_text_from_words(window_words)
    recheck_title = (clip_row["hook"] or clip_row["suggested_title"] or "").strip()
    return (clip_text, recheck_title)


def _atomic_write_json(target: Path, payload: dict) -> None:
    """tmp + os.replace atomic write of `payload` to `target`."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=str(target.parent),
        prefix=f".{target.stem}_",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(payload, tmp, indent=2)
        tmp_path = Path(tmp.name)
    os.replace(str(tmp_path), str(target))


def reconcile_orphans(
    *,
    repo: Repository,
    cfg: Config,
) -> tuple[bool, list[str]]:
    """Runner-startup gate: scan output/orphans/, abort on inconsistency.

    Returns (ok, alerts). ok=True means no markers OR all markers were stale
    (DB-consistent) and were cleaned up. ok=False means at least one marker
    is INCONSISTENT with the DB — the runner must abort.

    Alerts are summary strings to be appended to logs/alerts.md by the caller.
    """
    orphans_dir = cfg.abs_path(cfg.paths.orphans_dir)
    markers = orphan_marker.scan_orphans(orphans_dir)
    if not markers:
        return (True, [])

    inconsistent: list[orphan_marker.OrphanMarker] = []
    cleaned: list[str] = []
    for m in markers:
        if orphan_marker.db_is_consistent_with_marker(repo.conn, m):
            # 10-post failure on a previous run; safe to clean up now.
            if orphan_marker.unlink_marker(orphans_dir, m.clip_id):
                cleaned.append(m.clip_id)
        else:
            inconsistent.append(m)

    if inconsistent:
        ids = [f"{m.clip_id}(yt={m.youtube_video_id})" for m in inconsistent]
        alerts = [
            f"orphan_reconcile_required: {len(inconsistent)} inconsistent marker(s) "
            f"in {orphans_dir}; first: {ids[0]}; ALL: {ids[:20]}"
        ]
        return (False, alerts)

    if cleaned:
        logger.info(f"reconcile_orphans cleaned up {len(cleaned)} stale marker(s): {cleaned[:5]}")
    return (True, [])


def upload_one_clip(
    *,
    repo: Repository,
    cfg: Config,
    ledger: QuotaLedger,
    youtube: Any,                # build_youtube_client(cfg) result; may be None in dry-run
    clip_id: str,
    dry_run: bool = False,
    explicit_publish_at: Optional[datetime] = None,
    ollama_host: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> UploadResult:
    """Upload one clip end-to-end. See module docstring for the per-clip flow.

    `explicit_publish_at`: when provided (single-clip CLI --publish-at flag),
    this overrides any DB value AND is persisted in real mode (separate small
    tx before the API call) OR carried in-memory in dry-run mode.

    `now_utc`: injection point for tests so pad_publish_at is deterministic.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id=?", (clip_id,)).fetchone()
    if row is None:
        logger.warning(f"clip_id {clip_id} not in DB")
        return UploadResult(clip_id, UploadOutcome.skipped_wrong_status, reason="not in DB")

    # ---- Step 2: Preflight ------------------------------------------------
    if row["youtube_video_id"]:
        return UploadResult(
            clip_id, UploadOutcome.skipped_already_uploaded,
            youtube_video_id=row["youtube_video_id"],
        )
    if row["status"] not in ("quality_pass", "approved"):
        return UploadResult(clip_id, UploadOutcome.skipped_wrong_status,
                            reason=f"status={row['status']}")

    # ---- Step 3: Resolve file --------------------------------------------
    file_path = _resolve_file_path(cfg, row)
    if file_path is None:
        return UploadResult(
            clip_id, UploadOutcome.error_no_output,
            reason=f"output_path missing or zero size: {row['output_path']!r}",
        )

    # ---- Step 4: Resolve publish_at --------------------------------------
    publish_at_utc: Optional[datetime] = None
    if explicit_publish_at is not None:
        publish_at_utc = explicit_publish_at
        # Real-mode persists explicit_publish_at to clips.publish_at_utc BEFORE
        # the API call so a crash mid-run leaves the right slot recorded.
        if not dry_run:
            with repo.tx():
                repo.conn.execute(
                    "UPDATE clips SET publish_at_utc=?, updated_at=datetime('now') WHERE clip_id=?",
                    (publish_at_mod.format_publish_at_iso_z(explicit_publish_at), clip_id),
                )
    elif row["publish_at_utc"]:
        publish_at_utc = _parse_iso_z(row["publish_at_utc"])
    if publish_at_utc is None:
        return UploadResult(
            clip_id, UploadOutcome.error_no_publish_at,
            reason="publish_at_utc not set on row and --publish-at not supplied",
        )

    # ---- Step 5: Pad future-too-near -------------------------------------
    padded, was_padded = publish_at_mod.pad_publish_at(
        publish_at_utc, now_utc, lead_minutes=20,
    )
    padded_iso = publish_at_mod.format_publish_at_iso_z(padded)

    # ---- Step 5.5: Fetch script_row for AI-gen clips ---------------------
    content_kind = row["content_kind"] if row["content_kind"] else "sourced"
    script_row: Optional[Any] = None
    if content_kind == "ai_generated":
        script_row = repo.get_script(row["script_id"])

    # ---- Step 6: Pre-upload policy re-check -------------------------------
    transcripts_dir = cfg.abs_path(cfg.paths.transcripts_dir)
    recheck_result = _resolve_recheck_inputs(
        clip_row=row,
        script_row=script_row,
        transcripts_dir=transcripts_dir,
    )
    if recheck_result is None:
        return UploadResult(
            clip_id, UploadOutcome.error_no_transcript,
            reason="transcript missing or unreadable",
        )
    clip_text, recheck_title = recheck_result

    policy_kwargs: dict = {}
    if ollama_host:
        policy_kwargs["nsfw_fn"] = functools.partial(
            nsfw_mod.classify_nsfw, model=cfg.ollama_model, host=ollama_host,
        )
        policy_kwargs["hook_fn"] = functools.partial(
            hook_mod.rate_hook_sanity, model=cfg.ollama_model, host=ollama_host,
        )
        policy_kwargs["topic_fn"] = functools.partial(
            topic_mod.classify_topic, model=cfg.ollama_model, host=ollama_host,
        )

    verdict: PolicyVerdict = evaluate_clip_policy(
        cfg, clip_text, recheck_title, **policy_kwargs,
    )
    if verdict.infrastructure_failed:
        logger.warning(
            f"uploader policy re-check infrastructure fail for {clip_id}: "
            f"{verdict.infrastructure_reason}"
        )
        return UploadResult(
            clip_id, UploadOutcome.infrastructure_failed,
            reason=verdict.infrastructure_reason,
        )
    if not verdict.passed:
        # Phase 4.5 contract: flip to rejected_policy ONLY if youtube_video_id
        # is null (already checked in preflight) AND not in dry-run mode.
        if not dry_run:
            repo.set_clip_status(
                clip_id, "rejected_policy",
                reason=verdict.reason_string,
            )
        logger.info(f"upload_one_clip rejected by re-check {clip_id}: {verdict.reason_string}")
        return UploadResult(
            clip_id, UploadOutcome.rejected_policy_recheck,
            failed_check=verdict.failed_check,
            failed_value=verdict.failed_value,
            reason=verdict.reason_string,
        )

    # ---- Step 7-8: Get joined row + build body ---------------------------
    joined_row = repo.get_clip_with_video(clip_id)
    if joined_row is None:
        # Should be impossible; defensive.
        return UploadResult(
            clip_id, UploadOutcome.skipped_wrong_status,
            reason="clip exists but joined videos row missing",
        )
    body = insert_body_mod.build_insert_body(
        clip_row=joined_row,
        video_row=joined_row,    # joined row carries v_* aliases
        padded_publish_at_utc=padded,
        script_row=script_row,
        cfg=cfg,
    )

    # ---- Step 8: Dry-run branch ------------------------------------------
    if dry_run:
        dry_run_dir = cfg.abs_path(cfg.paths.dry_run_dir)
        target = dry_run_dir / f"{clip_id}.json"
        _atomic_write_json(target, body)
        logger.info(
            f"[DRY-RUN] insert body for {clip_id} written to {target} "
            f"(padded={was_padded}, publishAt={padded_iso})"
        )
        return UploadResult(
            clip_id, UploadOutcome.dry_run,
            padded_publish_at=padded_iso, was_padded=was_padded,
            reason=f"wrote {target.name}",
        )

    # ---- Step 9: Resumable upload ----------------------------------------
    units = int(getattr(cfg, "videos_insert_unit_cost"))
    try:
        youtube_video_id = do_resumable_upload(
            youtube, ledger, body, str(file_path), units=units,
        )
    except QuotaExceeded as exc:
        logger.warning(f"upload_one_clip quota exceeded for {clip_id}: {exc}")
        return UploadResult(clip_id, UploadOutcome.quota_exceeded, reason=str(exc))
    except HttpError as exc:
        msg = str(exc)[:200].replace("\n", " ")
        logger.warning(f"upload_one_clip HttpError for {clip_id}: {msg}")
        return UploadResult(clip_id, UploadOutcome.api_rejected, reason=msg)
    except (socket.timeout, ConnectionError) as exc:
        logger.warning(f"upload_one_clip network failure for {clip_id}: {exc}")
        return UploadResult(clip_id, UploadOutcome.api_unreachable, reason=str(exc))

    # ---- Step 10: Persist success — orphan fence + ID-first two-step -----
    orphans_dir = cfg.abs_path(cfg.paths.orphans_dir)

    # 10-pre: write marker BEFORE any DB write. If this raises, abort.
    try:
        orphan_marker.write_marker(
            orphans_dir,
            clip_id=clip_id,
            youtube_video_id=youtube_video_id,
            padded_publish_at_utc=padded_iso,
            quota_units_used=units,
        )
    except OSError as exc:
        # Catastrophic: API succeeded but we cannot fence. Surface loudly.
        msg = (
            f"post_upload_marker_failed clip_id={clip_id} "
            f"youtube_video_id={youtube_video_id} err={exc}"
        )
        logger.error(msg)
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="post_upload_marker_failed", message=msg,
        )
        return UploadResult(
            clip_id, UploadOutcome.error_persist_failed,
            youtube_video_id=youtube_video_id,
            padded_publish_at=padded_iso, was_padded=was_padded,
            reason=f"marker write failed: {exc}",
        )

    # 10a: narrow tx writing youtube_video_id only.
    try:
        with repo.tx():
            repo.set_clip_youtube_id(clip_id, youtube_video_id)
    except sqlite3.Error as exc:
        msg = (
            f"post_upload_id_persist_failed clip_id={clip_id} "
            f"youtube_video_id={youtube_video_id} err={exc}"
        )
        logger.error(msg)
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="post_upload_id_persist_failed", message=msg,
        )
        return UploadResult(
            clip_id, UploadOutcome.error_persist_failed,
            youtube_video_id=youtube_video_id,
            padded_publish_at=padded_iso, was_padded=was_padded,
            reason=f"step 10a failed: {exc}",
        )

    # 10b: status flip + uploads row in one tx.
    try:
        with repo.tx():
            repo.set_clip_status(
                clip_id, "uploaded",
                publish_at_utc=padded_iso,
            )
            repo.upsert_upload(
                clip_id=clip_id,
                youtube_video_id=youtube_video_id,
                publish_at_utc=padded_iso,
                quota_units_used=units,
            )
    except sqlite3.Error as exc:
        msg = (
            f"post_upload_status_persist_failed clip_id={clip_id} "
            f"youtube_video_id={youtube_video_id} err={exc}"
        )
        logger.error(msg)
        append_alert(
            cfg.abs_path(cfg.paths.logs_dir),
            kind="post_upload_status_persist_failed", message=msg,
        )
        return UploadResult(
            clip_id, UploadOutcome.error_persist_failed,
            youtube_video_id=youtube_video_id,
            padded_publish_at=padded_iso, was_padded=was_padded,
            reason=f"step 10b failed: {exc}",
        )

    # 10-post: best-effort marker cleanup.
    orphan_marker.unlink_marker(orphans_dir, clip_id)

    logger.info(
        f"uploaded {clip_id} -> {youtube_video_id} (publishAt={padded_iso}, padded={was_padded})"
    )
    return UploadResult(
        clip_id, UploadOutcome.uploaded,
        youtube_video_id=youtube_video_id,
        padded_publish_at=padded_iso, was_padded=was_padded,
    )


def run_all(
    *,
    repo: Repository,
    cfg: Config,
    ledger: QuotaLedger,
    youtube: Any,
    dry_run: bool = False,
    ollama_host: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> list[UploadResult]:
    """Bulk upload over clips_for_upload(). Aborts (returning []) if the
    orphan-reconcile gate refuses; the CLI exits with code 4 in that case.
    """
    ok, alerts = reconcile_orphans(repo=repo, cfg=cfg)
    if not ok:
        for a in alerts:
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="orphan_reconcile_required", message=a,
            )
        return []

    rows = repo.clips_for_upload()
    if not rows:
        logger.info("uploader: no candidates")
        return []

    batch = _BatchAlerts()
    results: list[UploadResult] = []
    for row in rows:
        result = upload_one_clip(
            repo=repo, cfg=cfg, ledger=ledger, youtube=youtube,
            clip_id=row["clip_id"],
            dry_run=dry_run, ollama_host=ollama_host, now_utc=now_utc,
        )
        results.append(result)

        if result.outcome == UploadOutcome.error_no_transcript:
            batch.no_transcript.append(result.clip_id)
        elif result.outcome == UploadOutcome.error_no_output:
            batch.no_output.append(result.clip_id)
        elif result.outcome == UploadOutcome.infrastructure_failed:
            batch.infra_failures.append(f"{result.clip_id}: {result.reason}")
        elif result.outcome == UploadOutcome.api_rejected:
            batch.api_rejected.append(f"{result.clip_id}: {result.reason}")
        elif result.outcome == UploadOutcome.api_unreachable:
            batch.api_unreachable.append(f"{result.clip_id}: {result.reason}")
        elif result.outcome == UploadOutcome.quota_exceeded:
            batch.quota_exceeded.append(result.clip_id)
        elif result.outcome == UploadOutcome.error_persist_failed:
            batch.persist_failed.append(f"{result.clip_id}: {result.reason}")
        if result.was_padded:
            batch.publish_at_padded.append(result.clip_id)

        # Hard-stop the batch if quota tripped — every later clip will trip too.
        if result.outcome == UploadOutcome.quota_exceeded:
            logger.warning("uploader: quota tripped; aborting batch")
            break

    if not dry_run:
        alert = functools.partial(append_alert, cfg.abs_path(cfg.paths.logs_dir))
        if batch.no_transcript:
            alert(kind="upload_no_transcript",
                  message=f"{len(batch.no_transcript)} clips lacked transcript: {batch.no_transcript[:5]}")
        if batch.no_output:
            alert(kind="upload_no_output",
                  message=f"{len(batch.no_output)} clips lacked rendered file: {batch.no_output[:5]}")
        if batch.infra_failures:
            alert(kind="upload_policy_infra_fail",
                  message=f"{len(batch.infra_failures)} clips left at quality_pass after Ollama re-check failure; first: {batch.infra_failures[0]}")
        if batch.api_rejected:
            alert(kind="upload_api_rejected",
                  message=f"{len(batch.api_rejected)} clips rejected by YouTube; first: {batch.api_rejected[0]}")
        if batch.api_unreachable:
            alert(kind="upload_api_unreachable",
                  message=f"{len(batch.api_unreachable)} clips failed to reach YouTube; first: {batch.api_unreachable[0]}")
        if batch.quota_exceeded:
            alert(kind="upload_quota_exceeded",
                  message=f"{len(batch.quota_exceeded)} clips skipped after quota cap reached: {batch.quota_exceeded[:5]}")
        if batch.publish_at_padded:
            alert(kind="publish_at_padded",
                  message=f"{len(batch.publish_at_padded)} clips had publishAt padded to now+20m: {batch.publish_at_padded[:5]}")
        if batch.persist_failed:
            alert(kind="upload_persist_failed",
                  message=f"{len(batch.persist_failed)} clips uploaded but DB persist failed; first: {batch.persist_failed[0]}")

    summary = {o.value: 0 for o in UploadOutcome}
    for r in results:
        summary[r.outcome.value] += 1
    summary_str = ", ".join(f"{k}={v}" for k, v in summary.items() if v)
    logger.info(f"uploader summary: {summary_str} (total={len(results)})")
    return results


def _parse_iso_z(s: str) -> Optional[datetime]:
    """Parse 'YYYY-MM-DDTHH:MM:SSZ' or '...+00:00' → tz-aware UTC datetime."""
    if not s:
        return None
    try:
        # datetime.fromisoformat in 3.11+ handles 'Z' as UTC.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None

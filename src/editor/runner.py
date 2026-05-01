"""Editor orchestration (Phase 4): selected -> rendered.

Per-clip flow:
  preflight status -> resolve raw mp4 + transcript -> compute slug + tmp paths
  -> reserve gameplay (short tx) -> write ASS file -> build ffmpeg argv
  -> subprocess.run -> on success: os.replace + commit (clip status + gameplay
  cursor in one tx). On failure: leave clip at 'selected', alert at run end.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger

from src.config_loader import Config
from src.editor import ffmpeg_runner, gameplay
from src.editor.slug import title_slug
from src.observability import append_alert
from src.state import Repository
from src.subtitles.ass_writer import write_ass_file


class EditorOutcome(str, Enum):
    rendered = "rendered"
    skipped_wrong_status = "skipped_wrong_status"
    skipped_already_rendered = "skipped_already_rendered"
    skipped_locked = "skipped_locked"           # rendered but already scheduled/uploaded
    rejected_render = "rejected_render"
    error_ffmpeg = "error_ffmpeg"
    error_no_transcript = "error_no_transcript"
    error_no_gameplay = "error_no_gameplay"


@dataclass
class EditorResult:
    clip_id: str
    outcome: EditorOutcome
    output_path: Optional[str] = None
    title_slug: Optional[str] = None
    duration_s: float = 0.0
    reason: Optional[str] = None


@dataclass
class _BatchAlerts:
    ffmpeg_errors: list[str] = field(default_factory=list)
    no_transcript: list[str] = field(default_factory=list)
    no_gameplay: list[str] = field(default_factory=list)


def _preflight(row: sqlite3.Row, force: bool) -> Optional[EditorOutcome]:
    """Status preflight. Returns a skip outcome if the clip should bypass.

    --force gating per plan: only re-render if status='rendered' AND not yet
    advanced into Phase 5/6 (publish_at_utc is null AND youtube_video_id is null).
    """
    status = row["status"]
    if status not in ("selected", "rendered"):
        return EditorOutcome.skipped_wrong_status
    if status == "rendered":
        if not force:
            return EditorOutcome.skipped_already_rendered
        # --force is gated against scheduled / uploaded clips.
        if row["publish_at_utc"] is not None or row["youtube_video_id"] is not None:
            return EditorOutcome.skipped_locked
    return None


def _load_transcript_words(transcripts_dir: Path, video_id: str) -> Optional[list[dict]]:
    """Read cached transcript JSON and flatten segments[].words[] into one list."""
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


def _unscheduled_output_path(pending_dir: Path, clip_id: str, slug: str) -> Path:
    return pending_dir / f"__unscheduled__{clip_id}__{slug}.mp4"


def render_one_clip(
    *,
    repo: Repository,
    cfg: Config,
    clip_id: str,
    force: bool = False,
    dry_run: bool = False,
) -> EditorResult:
    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id=?", (clip_id,)).fetchone()
    if row is None:
        logger.warning(f"clip_id {clip_id} not in DB")
        return EditorResult(clip_id, EditorOutcome.skipped_wrong_status, reason="not in DB")

    skip = _preflight(row, force)
    if skip is not None:
        return EditorResult(
            clip_id, skip,
            output_path=row["output_path"], title_slug=row["title_slug"],
        )

    video_id = row["video_id"]
    start_s = float(row["start_s"])
    end_s = float(row["end_s"])
    duration_s = end_s - start_s
    suggested_title = row["suggested_title"]

    raw_dir = cfg.abs_path(cfg.paths.raw_dir)
    transcripts_dir = cfg.abs_path(cfg.paths.transcripts_dir)
    pending_dir = cfg.abs_path(cfg.paths.pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)

    source_mp4 = raw_dir / f"{video_id}.mp4"
    if not source_mp4.exists() or source_mp4.stat().st_size == 0:
        logger.warning(f"source mp4 missing for {clip_id}: {source_mp4}")
        if not dry_run:
            repo.set_clip_status(clip_id, "rejected_render", reason="source_missing")
        return EditorResult(
            clip_id, EditorOutcome.rejected_render,
            duration_s=duration_s, reason="source_missing",
        )

    words = _load_transcript_words(transcripts_dir, video_id)
    if words is None:
        logger.warning(f"transcript missing for {clip_id} (video {video_id})")
        return EditorResult(
            clip_id, EditorOutcome.error_no_transcript,
            duration_s=duration_s, reason="transcript missing",
        )

    slug = title_slug(suggested_title, clip_id)
    final_output = _unscheduled_output_path(pending_dir, clip_id, slug)
    tmp_output = final_output.with_suffix(".tmp.mp4")

    # Reserve gameplay outside the render tx. Read-only — no writes yet.
    reservation = gameplay.reserve_next_segment(
        repo,
        cfg.project_root,
        cfg.gameplay_pool,
        clip_duration_s=duration_s,
    )
    if reservation is None:
        return EditorResult(
            clip_id, EditorOutcome.error_no_gameplay,
            duration_s=duration_s, reason="no gameplay segment available",
        )

    # Write ASS file to a temp dir (lifetime: this function).
    with tempfile.TemporaryDirectory(prefix=f"editor_{clip_id}_") as ass_tmpdir:
        ass_path = Path(ass_tmpdir) / f"{clip_id}.ass"
        write_ass_file(ass_path, words, start_s, end_s)

        argv = ffmpeg_runner.build_ffmpeg_argv(
            ffmpeg_bin=shutil.which("ffmpeg") or "ffmpeg",
            source_path=source_mp4,
            source_start_s=start_s,
            duration_s=duration_s,
            gameplay_path=reservation.file_path,
            gameplay_offset_s=reservation.offset_s,
            ass_path=ass_path,
            output_tmp_path=tmp_output,
            nvenc_preset=cfg.nvenc_preset,
            nvenc_cq=cfg.nvenc_cq,
            loudness_target_lufs=cfg.loudness_target_lufs,
        )

        if dry_run:
            print()
            print(f"[DRY-RUN] argv for {clip_id}:")
            for a in argv:
                print(f"  {a}")
            print(f"[DRY-RUN] target: {final_output}")
            return EditorResult(
                clip_id, EditorOutcome.rendered,
                output_path=str(final_output), title_slug=slug,
                duration_s=duration_s, reason="dry-run; no file written",
            )

        result = ffmpeg_runner.run_ffmpeg(argv, tmp_output)

    # ASS tempdir cleaned up here. Continue with success/failure handling.
    if result.returncode != 0 or result.output_size_bytes == 0:
        if tmp_output.exists():
            try:
                tmp_output.unlink()
            except OSError:
                pass
        err_msg = (result.stderr or "")[-300:].replace("\n", " ")
        logger.warning(f"ffmpeg failed for {clip_id}: rc={result.returncode} size={result.output_size_bytes} stderr={err_msg!r}")
        return EditorResult(
            clip_id, EditorOutcome.error_ffmpeg,
            duration_s=duration_s,
            reason=f"rc={result.returncode}; {err_msg[:120]}",
        )

    # Promote tmp -> final + commit DB state in one tx.
    os.replace(tmp_output, final_output)
    with repo.tx():
        gameplay.commit_advance(repo, reservation)
        repo.set_clip_status(
            clip_id, "rendered",
            output_path=str(final_output),
            title_slug=slug,
        )

    logger.info(
        f"rendered {clip_id} -> {final_output.name} "
        f"({result.output_size_bytes / 1024 / 1024:.1f} MB, dur={duration_s:.1f}s)"
    )
    return EditorResult(
        clip_id, EditorOutcome.rendered,
        output_path=str(final_output), title_slug=slug,
        duration_s=duration_s,
    )


def run_all(
    repo: Repository,
    cfg: Config,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[EditorResult]:
    if force:
        rows = repo.conn.execute(
            "SELECT clip_id FROM clips WHERE status IN ('selected','rendered') ORDER BY clip_id"
        ).fetchall()
    else:
        rows = repo.conn.execute(
            "SELECT clip_id FROM clips WHERE status='selected' ORDER BY clip_id"
        ).fetchall()

    if not rows:
        logger.info("editor: no candidates")
        return []

    alerts = _BatchAlerts()
    results: list[EditorResult] = []

    for row in rows:
        result = render_one_clip(
            repo=repo, cfg=cfg, clip_id=row["clip_id"],
            force=force, dry_run=dry_run,
        )
        results.append(result)
        if result.outcome == EditorOutcome.error_ffmpeg:
            alerts.ffmpeg_errors.append(f"{result.clip_id}: {result.reason}")
        elif result.outcome == EditorOutcome.error_no_transcript:
            alerts.no_transcript.append(result.clip_id)
        elif result.outcome == EditorOutcome.error_no_gameplay:
            alerts.no_gameplay.append(result.clip_id)

    if not dry_run:
        if alerts.ffmpeg_errors:
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="editor_ffmpeg_errors",
                message=f"{len(alerts.ffmpeg_errors)} clips failed ffmpeg; first: {alerts.ffmpeg_errors[0]}",
            )
        if alerts.no_transcript:
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="editor_no_transcript",
                message=f"{len(alerts.no_transcript)} clips lacked a transcript: {alerts.no_transcript[:5]}",
            )
        if alerts.no_gameplay:
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="editor_no_gameplay",
                message=f"{len(alerts.no_gameplay)} clips had no gameplay segment available",
            )

    rendered = sum(1 for r in results if r.outcome == EditorOutcome.rendered)
    logger.info(
        f"editor summary: rendered={rendered} "
        f"ffmpeg_err={len(alerts.ffmpeg_errors)} "
        f"no_transcript={len(alerts.no_transcript)} "
        f"no_gameplay={len(alerts.no_gameplay)} "
        f"total={len(results)}"
    )
    return results

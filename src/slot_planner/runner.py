"""Phase 6 slot_planner orchestration: quality_pass (publish_at_utc NULL)
-> quality_pass (publish_at_utc filled, file renamed in output/pending/).

Per-clip flow (slot_one_clip):
  1. Status preflight:
     - approved   -> skipped_locked (user vouched for this artifact)
     - uploaded / yt_id set  -> skipped_locked
     - quality_pass + publish_at_utc set, no --force -> skipped_already_slotted
     - any other status -> skipped_wrong_status
  2. Compute new slot-named filename from the assignment.
  3. DB write FIRST (publish_at_utc + publish_slot_local + output_path) in
     one repo.tx().
  4. os.replace(old_path, new_path) AFTER the tx commits.

Run startup (run_all + single-clip CLI both call this):
  reconcile_slot_renames(...) — scans output/pending/ for `__unscheduled__*.mp4`
  files whose DB row has publish_at_utc set; completes the rename to the
  DB-recorded target. Heals "DB committed, rename crashed" partial writes.
"""

from __future__ import annotations

import functools
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from loguru import logger

from src.config_loader import Config
from src.editor.slug import title_slug
from src.observability import append_alert
from src.slot_planner.allocator import SlotAssignment, allocate_slots
from src.state import Repository
from src.uploader.publish_at import format_publish_at_iso_z


# Filename: __unscheduled__{clip_id}__{slug}.mp4
# clip_id format from src/state/schema.sql: {video_id}_{int(start_s)}_{int(end_s)}
# video_id can contain '_' so we anchor on the literal '__' separators around it.
_UNSCHEDULED_RE = re.compile(r"^__unscheduled__(?P<clip_id>.+?)__(?P<slug>.+)\.mp4$")


class SlotOutcome(str, Enum):
    slotted = "slotted"
    dry_run = "dry_run"
    skipped_already_slotted = "skipped_already_slotted"
    skipped_locked = "skipped_locked"
    skipped_wrong_status = "skipped_wrong_status"
    error_no_output = "error_no_output"
    error_rename_failed = "error_rename_failed"
    error_both_paths_exist = "error_both_paths_exist"


@dataclass
class SlotResult:
    clip_id: str
    outcome: SlotOutcome
    publish_at_utc: Optional[str] = None
    publish_slot_local: Optional[str] = None
    output_path: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class _BatchAlerts:
    overflow: List[str] = field(default_factory=list)
    rename_failed: List[str] = field(default_factory=list)
    both_paths_exist: List[str] = field(default_factory=list)
    no_output: List[str] = field(default_factory=list)


def _extract_slug_from_unscheduled(filename: str, clip_id: str) -> Optional[str]:
    """Extract the slug portion from `__unscheduled__{clip_id}__{slug}.mp4`.

    Returns None if the filename doesn't match the pattern.
    """
    m = _UNSCHEDULED_RE.match(filename)
    if m is None:
        return None
    if m.group("clip_id") != clip_id:
        return None
    return m.group("slug")


def _build_new_filename(
    *, slot: SlotAssignment, slug: str
) -> str:
    """Compose the slot-named filename from the assignment + slug."""
    return f"{slot.filename_date}__slot_{slot.filename_hhmm}__{slug}.mp4"


def _resolve_slug(row: sqlite3.Row) -> str:
    """Best-effort slug recovery from the existing output_path; falls back to
    re-deriving from suggested_title + clip_id if the convention is broken."""
    output_path_str = row["output_path"] or ""
    if output_path_str:
        basename = Path(output_path_str).name
        slug = _extract_slug_from_unscheduled(basename, row["clip_id"])
        if slug is not None:
            return slug
        # Stripped of unscheduled prefix? (Already slot-named — re-slotting case.)
        # Reconstruct by stripping any leading "{date}__slot_{HHMM}__" prefix.
        slot_prefix_re = re.compile(r"^\d{4}-\d{2}-\d{2}__slot_\d{4}__")
        m = slot_prefix_re.match(basename)
        if m:
            return basename[m.end():].rsplit(".", 1)[0]
        # Last-resort: use the basename minus extension.
        if basename.endswith(".mp4"):
            return basename[:-4]
    # Total fallback — re-derive from clip metadata.
    return title_slug(row["suggested_title"] or "", row["clip_id"])


def reconcile_slot_renames(repo: Repository, cfg: Config) -> List[str]:
    """Heal "DB committed, rename crashed" partial writes.

    Scans output/pending/ for files matching __unscheduled__{clip_id}__*.mp4.
    For each match:
      - If the clip's DB row has publish_at_utc set AND output_path points to
        a different filename, the rename never finished — complete it.
      - If the target path also exists, append a slot_rename_both_exist alert
        and skip (operator must inspect).

    Returns the list of clip_ids that were healed.
    """
    pending_dir = cfg.abs_path(cfg.paths.pending_dir)
    if not pending_dir.exists():
        return []
    alert = functools.partial(append_alert, cfg.abs_path(cfg.paths.logs_dir))

    fixed: List[str] = []
    for unscheduled_path in pending_dir.glob("__unscheduled__*.mp4"):
        m = _UNSCHEDULED_RE.match(unscheduled_path.name)
        if m is None:
            continue
        clip_id = m.group("clip_id")
        row = repo.conn.execute(
            "SELECT * FROM clips WHERE clip_id=?", (clip_id,),
        ).fetchone()
        if row is None:
            continue
        if row["publish_at_utc"] is None:
            continue   # genuinely waiting for allocation — leave alone
        target_str = row["output_path"]
        if not target_str:
            continue
        target = Path(target_str)
        if target == unscheduled_path:
            # Pathological: DB says the file is at the unscheduled path. Skip.
            continue
        if target.exists():
            msg = (
                f"{clip_id}: both __unscheduled__ and {target.name} exist "
                f"in {pending_dir}; manual inspection required"
            )
            alert(kind="slot_rename_both_exist", message=msg)
            logger.warning(msg)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(unscheduled_path), str(target))
            fixed.append(clip_id)
            logger.info(f"reconcile_slot_renames: {clip_id} -> {target.name}")
        except OSError as exc:
            msg = f"{clip_id}: rename {unscheduled_path.name} -> {target.name} failed: {exc}"
            alert(kind="slot_rename_failed", message=msg)
            logger.error(msg)
    return fixed


def slot_one_clip(
    *,
    repo: Repository,
    cfg: Config,
    clip_id: str,
    slot: SlotAssignment,
    force: bool = False,
    dry_run: bool = False,
) -> SlotResult:
    """Apply a single slot assignment to a clip. See module docstring."""
    row = repo.conn.execute(
        "SELECT * FROM clips WHERE clip_id=?", (clip_id,),
    ).fetchone()
    if row is None:
        return SlotResult(clip_id, SlotOutcome.skipped_wrong_status,
                          reason="not in DB")

    # Step 1: Status preflight.
    status = row["status"]
    if row["youtube_video_id"]:
        return SlotResult(clip_id, SlotOutcome.skipped_locked,
                          reason="already uploaded")
    if status == "approved":
        return SlotResult(clip_id, SlotOutcome.skipped_locked,
                          reason="approved by user; --force does not override")
    if status != "quality_pass":
        return SlotResult(clip_id, SlotOutcome.skipped_wrong_status,
                          reason=f"status={status}")
    if row["publish_at_utc"] is not None and not force:
        return SlotResult(clip_id, SlotOutcome.skipped_already_slotted,
                          publish_at_utc=row["publish_at_utc"],
                          publish_slot_local=row["publish_slot_local"],
                          output_path=row["output_path"])

    # Step 2: Compute new filename.
    slug = _resolve_slug(row)
    new_filename = _build_new_filename(slot=slot, slug=slug)
    pending_dir = cfg.abs_path(cfg.paths.pending_dir)
    new_path = pending_dir / new_filename
    old_path_str = row["output_path"] or ""
    old_path = Path(old_path_str) if old_path_str else None

    publish_at_iso = format_publish_at_iso_z(slot.slot_utc_dt)
    publish_slot_local = slot.slot_local_str

    if dry_run:
        logger.info(
            f"[DRY-RUN] slot {clip_id} -> publish_at_utc={publish_at_iso} "
            f"publish_slot_local={publish_slot_local} new_path={new_path}"
        )
        return SlotResult(
            clip_id, SlotOutcome.dry_run,
            publish_at_utc=publish_at_iso,
            publish_slot_local=publish_slot_local,
            output_path=str(new_path),
        )

    # Pathological-state guard: if both old (different) and new exist, refuse.
    if (old_path is not None and old_path != new_path
            and old_path.exists() and new_path.exists()):
        msg = (
            f"{clip_id}: both {old_path.name} and {new_filename} exist; "
            f"manual inspection required"
        )
        return SlotResult(clip_id, SlotOutcome.error_both_paths_exist,
                          reason=msg)

    # Step 3: DB write FIRST.
    with repo.tx():
        repo.set_clip_status(
            clip_id, "quality_pass",
            publish_at_utc=publish_at_iso,
            publish_slot_local=publish_slot_local,
            output_path=str(new_path),
        )

    # Step 4: os.replace AFTER the tx commits.
    if old_path is None or not old_path.exists():
        # File already at new_path? (idempotent recovery)
        if new_path.exists():
            return SlotResult(
                clip_id, SlotOutcome.slotted,
                publish_at_utc=publish_at_iso,
                publish_slot_local=publish_slot_local,
                output_path=str(new_path),
                reason="recovery: file already at target",
            )
        return SlotResult(
            clip_id, SlotOutcome.error_no_output,
            publish_at_utc=publish_at_iso,
            publish_slot_local=publish_slot_local,
            output_path=str(new_path),
            reason=f"old_path missing: {old_path_str!r}",
        )

    if old_path == new_path:
        # No-op (rare: --force re-slotted to the same exact slot).
        return SlotResult(
            clip_id, SlotOutcome.slotted,
            publish_at_utc=publish_at_iso,
            publish_slot_local=publish_slot_local,
            output_path=str(new_path),
            reason="no-op: same target path",
        )

    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(old_path), str(new_path))
    except OSError as exc:
        # DB has the new path but the file is still at the old path. Next
        # slot_planner run's reconcile_slot_renames will heal this.
        logger.error(f"slot_one_clip rename failed for {clip_id}: {exc}")
        return SlotResult(
            clip_id, SlotOutcome.error_rename_failed,
            publish_at_utc=publish_at_iso,
            publish_slot_local=publish_slot_local,
            output_path=str(new_path),
            reason=f"rename failed: {exc}",
        )

    logger.info(
        f"slotted {clip_id} publish_at_utc={publish_at_iso} "
        f"publish_slot_local={publish_slot_local} -> {new_path.name}"
    )
    return SlotResult(
        clip_id, SlotOutcome.slotted,
        publish_at_utc=publish_at_iso,
        publish_slot_local=publish_slot_local,
        output_path=str(new_path),
    )


def run_all(
    repo: Repository,
    cfg: Config,
    *,
    force: bool = False,
    dry_run: bool = False,
    now_local: Optional[datetime] = None,
) -> List[SlotResult]:
    """Bulk slot assignment over clips_for_slot_planner().

    `now_local`: injection point for tests. Defaults to datetime.now in
    cfg.timezone.
    """
    # Reconcile any "DB committed, rename crashed" survivors first.
    if not dry_run:
        reconcile_slot_renames(repo, cfg)

    if force:
        # --force re-slots quality_pass clips that already have publish_at_utc
        # but haven't been uploaded. Approved clips are excluded by SQL guard.
        rows = repo.conn.execute(
            "SELECT * FROM clips "
            "WHERE status='quality_pass' "
            "AND youtube_video_id IS NULL "
            "ORDER BY created_at ASC, clip_id ASC"
        ).fetchall()
    else:
        rows = repo.clips_for_slot_planner()

    if not rows:
        logger.info("slot_planner: no candidates")
        return []

    if now_local is None:
        now_local = datetime.now(ZoneInfo(cfg.timezone))

    clip_ids = [r["clip_id"] for r in rows]
    assignments, overflow = allocate_slots(
        clip_ids=clip_ids,
        now_local=now_local,
        upload_slots=list(cfg.upload_slots),
        days_per_run=int(cfg.days_per_run),
        clips_per_day=int(cfg.clips_per_day),
        timezone_name=cfg.timezone,
        allowed_weekdays=cfg.upload_weekdays,
    )

    by_clip_id = {a.clip_id: a for a in assignments}
    results: List[SlotResult] = []
    batch = _BatchAlerts()
    for clip_id in clip_ids:
        slot = by_clip_id.get(clip_id)
        if slot is None:
            # Overflow — clip has no slot this run.
            continue
        result = slot_one_clip(
            repo=repo, cfg=cfg, clip_id=clip_id, slot=slot,
            force=force, dry_run=dry_run,
        )
        results.append(result)
        if result.outcome == SlotOutcome.error_rename_failed:
            batch.rename_failed.append(result.clip_id)
        elif result.outcome == SlotOutcome.error_both_paths_exist:
            batch.both_paths_exist.append(result.clip_id)
        elif result.outcome == SlotOutcome.error_no_output:
            batch.no_output.append(result.clip_id)

    if overflow:
        batch.overflow.extend(overflow)

    if not dry_run:
        alert = functools.partial(append_alert, cfg.abs_path(cfg.paths.logs_dir))
        if batch.overflow:
            alert(
                kind="slot_overflow",
                message=(
                    f"{len(batch.overflow)} clip(s) had no slot this run; "
                    f"first: {batch.overflow[:5]}"
                ),
            )
        if batch.rename_failed:
            alert(
                kind="slot_rename_failed_batch",
                message=(
                    f"{len(batch.rename_failed)} clip(s) had DB committed but "
                    f"rename failed; reconcile_slot_renames will heal next run; "
                    f"first: {batch.rename_failed[:5]}"
                ),
            )
        if batch.both_paths_exist:
            alert(
                kind="slot_rename_both_exist",
                message=(
                    f"{len(batch.both_paths_exist)} clip(s) had both old + new paths "
                    f"present; manual inspection required: {batch.both_paths_exist[:5]}"
                ),
            )
        if batch.no_output:
            alert(
                kind="slot_no_output",
                message=(
                    f"{len(batch.no_output)} clip(s) lacked source file; "
                    f"first: {batch.no_output[:5]}"
                ),
            )

    summary = {o.value: 0 for o in SlotOutcome}
    for r in results:
        summary[r.outcome.value] += 1
    summary_str = ", ".join(f"{k}={v}" for k, v in summary.items() if v)
    logger.info(
        f"slot_planner summary: {summary_str} (total={len(results)}, overflow={len(overflow)})"
    )
    return results

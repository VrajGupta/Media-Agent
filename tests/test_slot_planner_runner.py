"""slot_planner runner tests: per-clip flow, idempotency, recovery branches."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.slot_planner.allocator import allocate_slots
from src.slot_planner.runner import (
    SlotOutcome,
    reconcile_slot_renames,
    run_all,
    slot_one_clip,
)
from src.state import Repository, connect, initialize_schema

from tests.conftest import StubConfig


SGT = ZoneInfo("Asia/Singapore")
SUNDAY_0200_SGT = datetime(2026, 5, 3, 2, 0, tzinfo=SGT)


def _seed_video(repo: Repository, video_id: str = "v1", keyword: str = "movies") -> None:
    repo.conn.execute(
        "INSERT INTO videos (video_id, title, channel, duration_seconds, views, "
        "published_at, keyword, virality_score, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (video_id, "title", "ch", 600, 1000, "2026-04-01T00:00:00Z", keyword, 1.0, "downloaded"),
    )


def _seed_clip(
    repo: Repository,
    *,
    clip_id: str = "v1_30_60",
    video_id: str = "v1",
    status: str = "quality_pass",
    publish_at_utc: str | None = None,
    youtube_video_id: str | None = None,
    output_path: str | None = None,
    suggested_title: str = "great hook",
) -> None:
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, publish_at_utc, output_path, youtube_video_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (clip_id, video_id, 30.0, 60.0, "hook", suggested_title,
         "transcript_only", status, publish_at_utc, output_path, youtube_video_id),
    )


def _make_unscheduled_file(pending_dir: Path, clip_id: str, slug: str = "great_hook_abcd") -> Path:
    p = pending_dir / f"__unscheduled__{clip_id}__{slug}.mp4"
    p.write_bytes(b"x")
    return p


def _new_repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _one_assignment(clip_id: str):
    a, _ = allocate_slots(
        clip_ids=[clip_id],
        now_local=SUNDAY_0200_SGT,
        upload_slots=["09:00"],
        days_per_run=1,
        clips_per_day=4,
        timezone_name="Asia/Singapore",
    )
    return a[0]


# ---- preflight matrix ----------------------------------------------------


def test_skipped_locked_for_uploaded_clip(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, status="quality_pass", youtube_video_id="ytX")
    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a)
    assert r.outcome == SlotOutcome.skipped_locked


def test_skipped_locked_for_approved_clip(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, status="approved")
    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a)
    assert r.outcome == SlotOutcome.skipped_locked


def test_force_does_not_override_approved(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, status="approved")
    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a, force=True)
    assert r.outcome == SlotOutcome.skipped_locked


def test_skipped_wrong_status_for_rendered(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, status="rendered")
    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a)
    assert r.outcome == SlotOutcome.skipped_wrong_status


def test_skipped_already_slotted_without_force(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, status="quality_pass",
               publish_at_utc="2026-05-03T01:00:00Z",
               output_path=str(tmp_path / "output" / "pending" / "anything.mp4"))
    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a)
    assert r.outcome == SlotOutcome.skipped_already_slotted


# ---- happy path / DB-first persistence ----------------------------------


def test_slotted_writes_db_first_then_renames(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    _seed_clip(repo, status="quality_pass")
    old_path = _make_unscheduled_file(pending, "v1_30_60")
    repo.conn.execute(
        "UPDATE clips SET output_path=? WHERE clip_id=?",
        (str(old_path), "v1_30_60"),
    )

    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a)
    assert r.outcome == SlotOutcome.slotted
    assert r.publish_at_utc == "2026-05-03T01:00:00Z"
    assert r.publish_slot_local == "2026-05-03 09:00"
    assert r.output_path is not None
    new_path = Path(r.output_path)
    assert new_path.exists(), "rename should have moved file to slot-named path"
    assert not old_path.exists(), "old unscheduled file should no longer exist"
    assert new_path.name.startswith("2026-05-03__slot_0900__")
    # DB row was written FIRST. Verify it's in the DB.
    row = repo.conn.execute(
        "SELECT publish_at_utc, publish_slot_local, output_path, status FROM clips "
        "WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["publish_at_utc"] == "2026-05-03T01:00:00Z"
    assert row["publish_slot_local"] == "2026-05-03 09:00"
    assert row["output_path"] == str(new_path)
    assert row["status"] == "quality_pass"   # status unchanged


def test_dry_run_no_rename_no_db_write(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    _seed_clip(repo, status="quality_pass")
    old_path = _make_unscheduled_file(pending, "v1_30_60")
    repo.conn.execute(
        "UPDATE clips SET output_path=? WHERE clip_id=?",
        (str(old_path), "v1_30_60"),
    )

    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a, dry_run=True)
    assert r.outcome == SlotOutcome.dry_run
    assert old_path.exists(), "dry-run should not rename"
    row = repo.conn.execute(
        "SELECT publish_at_utc FROM clips WHERE clip_id=?", ("v1_30_60",)
    ).fetchone()
    assert row["publish_at_utc"] is None, "dry-run should not write DB"


def test_force_re_slots_quality_pass_with_pat(tmp_path):
    """--force on a quality_pass clip with publish_at_utc set re-slots it."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    # Pretend the clip is currently slotted to a Monday slot.
    old_slot_path = pending / "2026-05-04__slot_0900__great_hook_abcd.mp4"
    old_slot_path.write_bytes(b"x")
    _seed_clip(repo, status="quality_pass",
               publish_at_utc="2026-05-04T01:00:00Z",
               output_path=str(old_slot_path))

    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a, force=True)
    assert r.outcome == SlotOutcome.slotted
    assert r.publish_at_utc == "2026-05-03T01:00:00Z"   # new slot
    new_path = Path(r.output_path)
    assert new_path.exists()
    assert not old_slot_path.exists()


# ---- crash-recovery / reconcile ----------------------------------------


def test_rename_failure_leaves_db_committed(tmp_path, monkeypatch):
    """Simulate os.replace raising OSError mid-slot-write."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    _seed_clip(repo, status="quality_pass")
    old_path = _make_unscheduled_file(pending, "v1_30_60")
    repo.conn.execute(
        "UPDATE clips SET output_path=? WHERE clip_id=?",
        (str(old_path), "v1_30_60"),
    )

    def _boom(*args, **kwargs):
        raise OSError("disk on fire")
    monkeypatch.setattr("src.slot_planner.runner.os.replace", _boom)

    a = _one_assignment("v1_30_60")
    r = slot_one_clip(repo=repo, cfg=cfg, clip_id="v1_30_60", slot=a)
    assert r.outcome == SlotOutcome.error_rename_failed
    # DB has the new path even though the file is still at the old path.
    row = repo.conn.execute(
        "SELECT publish_at_utc, output_path FROM clips WHERE clip_id=?",
        ("v1_30_60",),
    ).fetchone()
    assert row["publish_at_utc"] == "2026-05-03T01:00:00Z"
    expected_target = pending / "2026-05-03__slot_0900__great_hook_abcd.mp4"
    assert row["output_path"] == str(expected_target)
    # File still at old location.
    assert old_path.exists()
    assert not expected_target.exists()


def test_reconcile_heals_db_committed_rename_crashed(tmp_path):
    """Run reconcile_slot_renames after a simulated crash; file gets moved."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    old_path = _make_unscheduled_file(pending, "v1_30_60")
    intended_target = pending / "2026-05-03__slot_0900__great_hook_abcd.mp4"
    _seed_clip(repo, status="quality_pass",
               publish_at_utc="2026-05-03T01:00:00Z",
               output_path=str(intended_target))

    fixed = reconcile_slot_renames(repo, cfg)
    assert fixed == ["v1_30_60"]
    assert intended_target.exists()
    assert not old_path.exists()


def test_reconcile_idempotent_on_healthy_state(tmp_path):
    """No __unscheduled__ files in pending → reconcile is a no-op."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, status="quality_pass")
    fixed = reconcile_slot_renames(repo, cfg)
    assert fixed == []


def test_reconcile_skips_unscheduled_with_no_slot_yet(tmp_path):
    """An __unscheduled__ file whose clip has publish_at_utc=NULL is left alone."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    _seed_clip(repo, status="quality_pass")   # publish_at_utc NULL
    old_path = _make_unscheduled_file(pending, "v1_30_60")
    fixed = reconcile_slot_renames(repo, cfg)
    assert fixed == []
    assert old_path.exists(), "should not have moved a not-yet-slotted file"


def test_reconcile_alerts_when_both_paths_exist(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    old_path = _make_unscheduled_file(pending, "v1_30_60")
    target = pending / "2026-05-03__slot_0900__great_hook_abcd.mp4"
    target.write_bytes(b"y")
    _seed_clip(repo, status="quality_pass",
               publish_at_utc="2026-05-03T01:00:00Z",
               output_path=str(target))
    fixed = reconcile_slot_renames(repo, cfg)
    assert fixed == []
    assert old_path.exists()
    assert target.exists()
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "slot_rename_both_exist" in alerts_md


# ---- run_all -------------------------------------------------------------


def test_run_all_empty_returns_empty(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    results = run_all(repo, cfg, now_local=SUNDAY_0200_SGT)
    assert results == []


def test_run_all_overflow_appends_alert(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path,
                     clips_per_day=1, days_per_run=1,
                     upload_slots=["09:00"])
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    # 3 clips, capacity = 1*1 = 1 → 2 should overflow.
    for i in range(3):
        clip_id = f"v1_{i}_99"
        _seed_clip(repo, clip_id=clip_id, status="quality_pass")
        path = _make_unscheduled_file(pending, clip_id, slug=f"slug_{i}")
        repo.conn.execute(
            "UPDATE clips SET output_path=? WHERE clip_id=?",
            (str(path), clip_id),
        )

    results = run_all(repo, cfg, now_local=SUNDAY_0200_SGT)
    # Only 1 clip got slotted.
    slotted = [r for r in results if r.outcome == SlotOutcome.slotted]
    assert len(slotted) == 1
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "slot_overflow" in alerts_md
    assert "2 clip(s)" in alerts_md


def test_run_all_force_includes_already_slotted_clips(tmp_path):
    """--force re-slots quality_pass clips with publish_at_utc set."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path,
                     clips_per_day=1, days_per_run=1,
                     upload_slots=["09:00"])
    pending = tmp_path / "output" / "pending"
    _seed_video(repo)
    old_target = pending / "2026-05-04__slot_0900__great_hook_abcd.mp4"
    old_target.write_bytes(b"x")
    _seed_clip(repo, status="quality_pass",
               publish_at_utc="2026-05-04T01:00:00Z",
               output_path=str(old_target))

    results = run_all(repo, cfg, force=True, now_local=SUNDAY_0200_SGT)
    assert len(results) == 1
    assert results[0].outcome == SlotOutcome.slotted
    # The old slot path got renamed to the new one.
    assert not old_target.exists()

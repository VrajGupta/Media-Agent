"""daily_upload run_today: recovered_slot + orphan gate + quota stop tests.

Mocks Phase 5's upload_one_clip + reconcile_orphans so the test doesn't need
a real OAuth client. Verifies the Phase 6 layering on top of Phase 5 behaves
exactly as the plan specifies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.daily_upload import run_today
from src.state import Repository, connect, initialize_schema
from src.uploader.runner import UploadOutcome, UploadResult

from tests.conftest import StubConfig


def _new_repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _seed_video(repo: Repository) -> None:
    repo.conn.execute(
        "INSERT INTO videos (video_id, title, channel, duration_seconds, views, "
        "published_at, keyword, virality_score, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("v1", "t", "c", 600, 1, "2026-04-01T00:00:00Z", "movies", 1.0, "downloaded"),
    )


def _seed_clip(
    repo: Repository,
    *,
    clip_id: str,
    status: str = "approved",
    publish_at_utc: str = "2026-05-03T01:00:00Z",
    output_path: str | None = None,
) -> None:
    repo.conn.execute(
        "INSERT INTO clips (clip_id, video_id, start_s, end_s, hook, suggested_title, "
        "selection_method, status, publish_at_utc, output_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (clip_id, "v1", 30.0, 60.0, "hook", "title", "transcript_only",
         status, publish_at_utc, output_path),
    )


def test_orphan_inconsistent_aborts_with_exit_4(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    _seed_clip(repo, clip_id="x")

    def _fake_reconcile_orphans(*, repo, cfg):
        return (False, ["orphan_reconcile_required: 1 inconsistent marker"])

    with patch("src.uploader.runner.reconcile_orphans", _fake_reconcile_orphans):
        results, code = run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )
    assert code == 4
    assert results == []
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "orphan_reconcile_required" in alerts_md


def test_recovered_slot_alert_for_past_due_clip(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    # Past-due clip: publish_at_utc was 2026-04-01 (well before now_utc).
    _seed_clip(repo, clip_id="past_due", publish_at_utc="2026-04-01T00:00:00Z")

    def _fake_reconcile_orphans(*, repo, cfg):
        return (True, [])

    def _fake_upload_one_clip(**kwargs):
        return UploadResult(
            clip_id=kwargs["clip_id"],
            outcome=UploadOutcome.uploaded,
            youtube_video_id="ytX",
            padded_publish_at="2026-05-03T04:20:00Z",
            was_padded=True,   # padded because intended was past
        )

    now_utc = datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc)
    with patch("src.uploader.runner.reconcile_orphans", _fake_reconcile_orphans), \
         patch("src.uploader.runner.upload_one_clip", _fake_upload_one_clip):
        results, code = run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            now_utc=now_utc,
        )
    assert code == 0
    assert len(results) == 1
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "recovered_slot" in alerts_md
    assert "past_due" in alerts_md


def test_padded_but_not_past_does_not_emit_recovered_slot(tmp_path):
    """Future-too-near padding (5 min from now) ≠ recovered_slot."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    # publish_at_utc is 5 min from now — was_padded=True but intended not past.
    _seed_clip(repo, clip_id="near_future", publish_at_utc="2026-05-03T04:05:00Z")

    def _fake_reconcile_orphans(*, repo, cfg):
        return (True, [])

    def _fake_upload_one_clip(**kwargs):
        return UploadResult(
            clip_id=kwargs["clip_id"],
            outcome=UploadOutcome.uploaded,
            youtube_video_id="ytX",
            padded_publish_at="2026-05-03T04:20:00Z",
            was_padded=True,
        )

    now_utc = datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc)
    with patch("src.uploader.runner.reconcile_orphans", _fake_reconcile_orphans), \
         patch("src.uploader.runner.upload_one_clip", _fake_upload_one_clip):
        results, code = run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            now_utc=now_utc,
        )
    assert code == 0
    alerts_md = (Path(cfg.paths.logs_dir) / "alerts.md").read_text()
    assert "recovered_slot" not in alerts_md
    assert "publish_at_padded" in alerts_md


def test_quota_exceeded_breaks_batch(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path)
    _seed_video(repo)
    # Three clips today; the second one trips quota.
    _seed_clip(repo, clip_id="c1", publish_at_utc="2026-05-03T01:00:00Z")
    _seed_clip(repo, clip_id="c2", publish_at_utc="2026-05-03T02:00:00Z")
    _seed_clip(repo, clip_id="c3", publish_at_utc="2026-05-03T03:00:00Z")

    call_log: list[str] = []

    def _fake_reconcile_orphans(*, repo, cfg):
        return (True, [])

    def _fake_upload_one_clip(**kwargs):
        clip_id = kwargs["clip_id"]
        call_log.append(clip_id)
        if clip_id == "c2":
            return UploadResult(clip_id=clip_id, outcome=UploadOutcome.quota_exceeded,
                                reason="9001 / 9000")
        return UploadResult(clip_id=clip_id, outcome=UploadOutcome.uploaded,
                            youtube_video_id="ytX")

    with patch("src.uploader.runner.reconcile_orphans", _fake_reconcile_orphans), \
         patch("src.uploader.runner.upload_one_clip", _fake_upload_one_clip):
        results, code = run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )
    assert code == 0
    # c3 must NOT have been called.
    assert call_log == ["c1", "c2"]
    outcomes = [r.outcome for r in results]
    assert UploadOutcome.quota_exceeded in outcomes


def test_human_review_blocks_quality_pass(tmp_path):
    """human_review=True: a quality_pass clip is NOT uploaded even if its
    publish_at_utc is within today's window."""
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path, human_review=True)
    _seed_video(repo)
    _seed_clip(repo, clip_id="qp", status="quality_pass",
               publish_at_utc="2026-05-03T01:00:00Z")

    upload_calls: list[str] = []

    def _fake_reconcile_orphans(*, repo, cfg):
        return (True, [])

    def _fake_upload_one_clip(**kwargs):
        upload_calls.append(kwargs["clip_id"])
        return UploadResult(clip_id=kwargs["clip_id"],
                            outcome=UploadOutcome.uploaded, youtube_video_id="ytX")

    with patch("src.uploader.runner.reconcile_orphans", _fake_reconcile_orphans), \
         patch("src.uploader.runner.upload_one_clip", _fake_upload_one_clip):
        results, code = run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )
    assert code == 0
    assert results == []
    assert upload_calls == []


def test_human_review_false_uploads_quality_pass_directly(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path, human_review=False)
    _seed_video(repo)
    _seed_clip(repo, clip_id="qp", status="quality_pass",
               publish_at_utc="2026-05-03T01:00:00Z")

    upload_calls: list[str] = []

    def _fake_reconcile_orphans(*, repo, cfg):
        return (True, [])

    def _fake_upload_one_clip(**kwargs):
        upload_calls.append(kwargs["clip_id"])
        return UploadResult(clip_id=kwargs["clip_id"],
                            outcome=UploadOutcome.uploaded, youtube_video_id="ytX")

    with patch("src.uploader.runner.reconcile_orphans", _fake_reconcile_orphans), \
         patch("src.uploader.runner.upload_one_clip", _fake_upload_one_clip):
        results, code = run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )
    assert code == 0
    assert upload_calls == ["qp"]


def test_dry_run_does_not_persist(tmp_path):
    repo = _new_repo(tmp_path)
    cfg = StubConfig(tmp_path, human_review=True)
    _seed_video(repo)
    pending_file = Path(cfg.paths.pending_dir) / "x.mp4"
    pending_file.write_bytes(b"x")
    _seed_clip(repo, clip_id="qp", status="quality_pass",
               publish_at_utc="2026-05-03T01:00:00Z",
               output_path=str(pending_file))
    # User dragged the file to approved/.
    (Path(cfg.paths.approved_dir) / "x.mp4").write_bytes(b"x")

    def _fake_reconcile_orphans(*, repo, cfg):
        return (True, [])

    upload_calls: list[str] = []

    def _fake_upload_one_clip(**kwargs):
        upload_calls.append(kwargs["clip_id"])
        return UploadResult(clip_id=kwargs["clip_id"],
                            outcome=UploadOutcome.dry_run,
                            reason="wrote x.json")

    with patch("src.uploader.runner.reconcile_orphans", _fake_reconcile_orphans), \
         patch("src.uploader.runner.upload_one_clip", _fake_upload_one_clip):
        results, code = run_today(
            repo=repo, cfg=cfg, ledger=object(), youtube=object(),
            dry_run=True,
            now_utc=datetime(2026, 5, 3, 4, 0, tzinfo=timezone.utc),
        )
    assert code == 0
    # reconcile_approvals(dry_run=True) does NOT flip status; clips_for_upload_due
    # with statuses=('approved',) returns 0 rows.
    assert upload_calls == []
    row = repo.conn.execute(
        "SELECT status FROM clips WHERE clip_id=?", ("qp",)
    ).fetchone()
    assert row["status"] == "quality_pass"

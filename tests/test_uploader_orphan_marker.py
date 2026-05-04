"""Phase 5 — orphan-marker fence: write/read/scan/unlink/consistency check."""

from __future__ import annotations

import json
from pathlib import Path

from src.state import Repository, connect, initialize_schema
from src.uploader import orphan_marker


def _seed_clip_video(repo, *, clip_id="C1", video_id="V1", status="quality_pass",
                     youtube_video_id=None):
    repo.discovery_upsert_video(
        video_id=video_id, title="T", channel="C", duration_seconds=600,
        views=1, likes=0, comments=0,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.0,
    )
    repo.upsert_selector_clip(
        clip_id=clip_id, video_id=video_id, start_s=0.0, end_s=30.0,
        hook="hook", suggested_title="title", selection_method="transcript_only",
    )
    extra = {}
    if youtube_video_id is not None:
        extra["youtube_video_id"] = youtube_video_id
    repo.set_clip_status(clip_id, status, **extra)


def test_write_then_read_marker_roundtrip(tmp_path):
    orphans = tmp_path / "orphans"
    path = orphan_marker.write_marker(
        orphans,
        clip_id="C1",
        youtube_video_id="YT1",
        padded_publish_at_utc="2026-05-04T13:00:00Z",
        quota_units_used=1600,
    )
    assert path.exists()
    marker = orphan_marker.read_marker(path)
    assert marker is not None
    assert marker.clip_id == "C1"
    assert marker.youtube_video_id == "YT1"
    assert marker.padded_publish_at_utc == "2026-05-04T13:00:00Z"
    assert marker.quota_units_used == 1600
    assert marker.uploaded_at_utc.endswith("Z")


def test_write_marker_atomic_no_partial_file_on_normal_path(tmp_path):
    orphans = tmp_path / "orphans"
    orphan_marker.write_marker(
        orphans,
        clip_id="C1",
        youtube_video_id="YT1",
        padded_publish_at_utc="2026-05-04T13:00:00Z",
        quota_units_used=1600,
    )
    # No leftover .tmp files from the NamedTemporaryFile dance.
    leftovers = [p for p in orphans.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_scan_orphans_skips_malformed_and_tmp_files(tmp_path):
    orphans = tmp_path / "orphans"
    orphans.mkdir()
    # Valid marker.
    (orphans / "good.json").write_text(json.dumps({
        "clip_id": "good", "youtube_video_id": "YTG",
        "padded_publish_at_utc": "2026-05-04T13:00:00Z",
        "quota_units_used": 1600,
        "uploaded_at_utc": "2026-05-04T12:00:00Z",
    }), encoding="utf-8")
    # Malformed JSON.
    (orphans / "bad.json").write_text("not json", encoding="utf-8")
    # Missing field.
    (orphans / "incomplete.json").write_text(json.dumps({"clip_id": "x"}), encoding="utf-8")
    # In-flight tmp file.
    (orphans / ".inflight_tmp_.tmp").write_text("doesnt matter", encoding="utf-8")
    # Non-json file.
    (orphans / "readme.txt").write_text("nope", encoding="utf-8")

    markers = orphan_marker.scan_orphans(orphans)
    assert len(markers) == 1
    assert markers[0].clip_id == "good"


def test_unlink_marker_returns_true_on_missing_file(tmp_path):
    orphans = tmp_path / "orphans"
    orphans.mkdir()
    # Missing file: missing_ok=True so unlink succeeds.
    assert orphan_marker.unlink_marker(orphans, "nonexistent") is True


def test_db_consistent_when_db_reflects_upload(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    repo = Repository(conn)
    _seed_clip_video(repo, clip_id="C1", youtube_video_id="YT1", status="uploaded")
    # An uploads row must also exist for consistency.
    repo.upsert_upload(
        clip_id="C1", youtube_video_id="YT1",
        publish_at_utc="2026-05-04T13:00:00Z", quota_units_used=1600,
    )

    marker = orphan_marker.OrphanMarker(
        clip_id="C1", youtube_video_id="YT1",
        padded_publish_at_utc="2026-05-04T13:00:00Z",
        quota_units_used=1600,
        uploaded_at_utc="2026-05-04T12:00:00Z",
    )
    assert orphan_marker.db_is_consistent_with_marker(conn, marker) is True


def test_db_inconsistent_when_status_or_id_or_uploads_row_missing(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    repo = Repository(conn)

    marker = orphan_marker.OrphanMarker(
        clip_id="C1", youtube_video_id="YT1",
        padded_publish_at_utc="2026-05-04T13:00:00Z",
        quota_units_used=1600,
        uploaded_at_utc="2026-05-04T12:00:00Z",
    )

    # Case 1: clip not in DB at all.
    assert orphan_marker.db_is_consistent_with_marker(conn, marker) is False

    # Case 2: clip exists with status=quality_pass + no youtube_video_id.
    _seed_clip_video(repo, clip_id="C1", status="quality_pass")
    assert orphan_marker.db_is_consistent_with_marker(conn, marker) is False

    # Case 3: status='uploaded' + matching youtube_video_id but no uploads row.
    repo.set_clip_status("C1", "uploaded", youtube_video_id="YT1")
    assert orphan_marker.db_is_consistent_with_marker(conn, marker) is False

    # Case 4: youtube_video_id mismatch.
    repo.upsert_upload(
        clip_id="C1", youtube_video_id="DIFFERENT_ID",
        publish_at_utc="2026-05-04T13:00:00Z", quota_units_used=1600,
    )
    repo.conn.execute("UPDATE clips SET youtube_video_id='DIFFERENT_ID' WHERE clip_id='C1'")
    assert orphan_marker.db_is_consistent_with_marker(conn, marker) is False

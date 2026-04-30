"""Tests for repo.upsert_selector_clip — Phase 3's selector-scoped upsert.

The contract: Phase 3 owns only the selector columns. On conflict we must
update those columns and NEVER touch publish_at_utc, publish_slot_local,
output_path, youtube_video_id, or title_slug — those are filled by later
phases and a `--force` re-rank after rendering must not erase them.
"""

from __future__ import annotations

from pathlib import Path

from src.state import Repository, connect, initialize_schema


def _seed_video(repo: Repository, vid: str = "v1") -> None:
    repo.discovery_upsert_video(
        video_id=vid, title="T", channel="C",
        duration_seconds=600, views=100, likes=1, comments=1,
        published_at="2026-04-01T00:00:00Z",
        keyword="k", virality_score=1.5,
    )
    repo.set_video_status(vid, "transcribed")


def _make_repo(tmp_path: Path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def test_initial_insert_creates_selected_row(tmp_path):
    repo = _make_repo(tmp_path)
    _seed_video(repo)
    repo.upsert_selector_clip(
        clip_id="v1_30_60",
        video_id="v1",
        start_s=30.0,
        end_s=60.0,
        hook="hello",
        suggested_title="Hello World",
        selection_method="heatmap_aided",
    )
    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "selected"
    assert row["start_s"] == 30.0
    assert row["end_s"] == 60.0
    assert row["hook"] == "hello"
    assert row["suggested_title"] == "Hello World"
    assert row["selection_method"] == "heatmap_aided"
    # Phase 3 leaves these NULL.
    assert row["publish_at_utc"] is None
    assert row["publish_slot_local"] is None
    assert row["output_path"] is None
    assert row["youtube_video_id"] is None
    assert row["title_slug"] is None


def test_rerank_preserves_downstream_columns(tmp_path):
    """Critical invariant: --force re-rank must not erase phases 4-6 metadata."""
    repo = _make_repo(tmp_path)
    _seed_video(repo)
    repo.upsert_selector_clip(
        clip_id="v1_30_60",
        video_id="v1",
        start_s=30.0,
        end_s=60.0,
        hook="first hook",
        suggested_title="First Title",
        selection_method="transcript_only",
    )

    # Simulate downstream phases populating their columns.
    repo.conn.execute(
        """
        UPDATE clips SET
            publish_at_utc='2026-05-15T09:00:00Z',
            publish_slot_local='2026-05-15 17:00',
            output_path='output/pending/2026-05-15__1700__first_title.mp4',
            youtube_video_id='ytid_abc',
            title_slug='first_title',
            status='rendered'
        WHERE clip_id='v1_30_60'
        """
    )

    # --force re-rank: same clip_id, different hook/title/method.
    repo.upsert_selector_clip(
        clip_id="v1_30_60",
        video_id="v1",
        start_s=30.0,
        end_s=60.0,
        hook="second hook",
        suggested_title="Second Title",
        selection_method="heatmap_aided",
    )

    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id='v1_30_60'").fetchone()
    # Selector columns updated.
    assert row["hook"] == "second hook"
    assert row["suggested_title"] == "Second Title"
    assert row["selection_method"] == "heatmap_aided"
    # Status flipped back to 'selected' — selector owns this transition.
    assert row["status"] == "selected"
    # Downstream columns preserved verbatim.
    assert row["publish_at_utc"] == "2026-05-15T09:00:00Z"
    assert row["publish_slot_local"] == "2026-05-15 17:00"
    assert row["output_path"] == "output/pending/2026-05-15__1700__first_title.mp4"
    assert row["youtube_video_id"] == "ytid_abc"
    assert row["title_slug"] == "first_title"


def test_rerank_clears_rejection_reason(tmp_path):
    """A previously rejected clip can be re-selected; rejection_reason clears."""
    repo = _make_repo(tmp_path)
    _seed_video(repo)
    repo.upsert_selector_clip(
        clip_id="v1_30_60",
        video_id="v1",
        start_s=30.0,
        end_s=60.0,
        hook="h",
        suggested_title="T",
        selection_method="transcript_only",
    )
    repo.set_clip_status("v1_30_60", "rejected_policy", reason="banlist hit: foo")

    repo.upsert_selector_clip(
        clip_id="v1_30_60",
        video_id="v1",
        start_s=30.0,
        end_s=60.0,
        hook="h2",
        suggested_title="T2",
        selection_method="heatmap_aided",
    )

    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id='v1_30_60'").fetchone()
    assert row["status"] == "selected"
    assert row["rejection_reason"] is None


def test_distinct_clip_ids_coexist(tmp_path):
    """Two windows from the same video are independent rows."""
    repo = _make_repo(tmp_path)
    _seed_video(repo)
    repo.upsert_selector_clip(
        clip_id="v1_30_60", video_id="v1", start_s=30.0, end_s=60.0,
        hook="a", suggested_title="A", selection_method="heatmap_aided",
    )
    repo.upsert_selector_clip(
        clip_id="v1_120_175", video_id="v1", start_s=120.0, end_s=175.0,
        hook="b", suggested_title="B", selection_method="transcript_only",
    )
    rows = repo.conn.execute(
        "SELECT clip_id FROM clips WHERE video_id='v1' ORDER BY start_s"
    ).fetchall()
    assert [r["clip_id"] for r in rows] == ["v1_30_60", "v1_120_175"]

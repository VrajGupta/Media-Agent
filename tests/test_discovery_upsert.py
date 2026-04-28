"""Status-preserving upsert: a forced rerun must NOT regress a downloaded video."""

from src.state import Repository, connect, initialize_schema


def _fresh_repo(tmp_path) -> Repository:
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _row(repo, video_id):
    return repo.conn.execute(
        "SELECT * FROM videos WHERE video_id=?", (video_id,)
    ).fetchone()


def test_insert_new_row_marks_discovered(tmp_path):
    repo = _fresh_repo(tmp_path)
    repo.discovery_upsert_video(
        video_id="vid1",
        title="T1",
        channel="C",
        duration_seconds=600,
        views=100,
        likes=10,
        comments=5,
        published_at="2026-04-01T00:00:00Z",
        keyword="k",
        virality_score=1.5,
    )
    row = _row(repo, "vid1")
    assert row["status"] == "discovered"
    assert row["views"] == 100
    assert row["title"] == "T1"


def test_rerun_does_not_regress_status(tmp_path):
    repo = _fresh_repo(tmp_path)
    repo.discovery_upsert_video(
        video_id="vid1", title="T1", channel="C", duration_seconds=600,
        views=100, likes=10, comments=5,
        published_at="2026-04-01T00:00:00Z", keyword="k", virality_score=1.5,
    )
    repo.set_video_status("vid1", "downloaded")
    assert _row(repo, "vid1")["status"] == "downloaded"

    # Re-run discovery with refreshed stats — status must remain 'downloaded',
    # and views/likes/etc. must update.
    repo.discovery_upsert_video(
        video_id="vid1", title="T1-updated", channel="C", duration_seconds=600,
        views=999, likes=200, comments=80,
        published_at="2026-04-01T00:00:00Z", keyword="k", virality_score=2.7,
    )
    row = _row(repo, "vid1")
    assert row["status"] == "downloaded"        # NOT regressed
    assert row["views"] == 999                   # stats refreshed
    assert row["likes"] == 200
    assert row["comments"] == 80
    assert row["virality_score"] == 2.7
    assert row["title"] == "T1-updated"
    assert row["rejection_reason"] is None       # untouched


def test_rerun_preserves_keyword_after_reclassification(tmp_path):
    """Even if a future caller passes a different keyword, the original sticks."""
    repo = _fresh_repo(tmp_path)
    repo.discovery_upsert_video(
        video_id="vid1", title="T", channel="C", duration_seconds=600,
        views=100, likes=10, comments=5,
        published_at="2026-04-01T00:00:00Z", keyword="joe rogan", virality_score=1.5,
    )
    repo.discovery_upsert_video(
        video_id="vid1", title="T", channel="C", duration_seconds=600,
        views=200, likes=20, comments=10,
        published_at="2026-04-01T00:00:00Z", keyword="stoicism", virality_score=1.7,
    )
    assert _row(repo, "vid1")["keyword"] == "joe rogan"


def test_cooldown_guard_after_attempt(tmp_path):
    repo = _fresh_repo(tmp_path)
    assert repo.is_in_cooldown("k", 6) is False
    repo.record_discovery_attempt("k", inspected_count=10, inserted_count=3)
    assert repo.is_in_cooldown("k", 6) is True
    assert repo.is_in_cooldown("other-keyword", 6) is False


def test_niche_baseline_default(tmp_path):
    repo = _fresh_repo(tmp_path)
    assert repo.niche_median_views("missing") == 1
    repo.upsert_niche_baseline("k", median_views=12345, sample_size=20)
    assert repo.niche_median_views("k") == 12345

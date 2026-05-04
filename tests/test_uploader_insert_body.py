"""Phase 5 — videos.insert resource body shape regression tests.

Each locked field gets its own assertion so a future refactor that flips one
fails loudly here rather than at upload time.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.uploader.insert_body import build_insert_body


class _FakeRow(dict):
    """dict subclass that also exposes .keys() like sqlite3.Row."""
    pass


def _row(hook="The line", title="Backup title", video_id="abc123",
         channel="MovieClipsChannel", keyword="best movie scenes"):
    # Carries both clip and v_*-aliased video columns, so the same row can
    # be passed as both clip_row and video_row (mirrors get_clip_with_video).
    r = _FakeRow()
    r["hook"] = hook
    r["suggested_title"] = title
    r["video_id"] = video_id
    r["channel"] = channel
    r["keyword"] = keyword
    r["v_video_id"] = video_id
    r["v_channel"] = channel
    r["v_keyword"] = keyword
    return r


def test_full_body_shape_snapshot():
    publish_at = datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc)
    body = build_insert_body(
        clip_row=_row(),
        video_row=_row(),
        padded_publish_at_utc=publish_at,
    )
    assert set(body.keys()) == {"snippet", "status"}
    assert set(body["snippet"].keys()) == {
        "title", "description", "tags",
        "categoryId", "defaultLanguage", "defaultAudioLanguage",
    }
    assert set(body["status"].keys()) == {
        "privacyStatus", "publishAt",
        "selfDeclaredMadeForKids", "madeForKids",
        "license", "embeddable",
    }


def test_status_locked_fields():
    publish_at = datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc)
    body = build_insert_body(
        clip_row=_row(),
        video_row=_row(),
        padded_publish_at_utc=publish_at,
    )
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert body["status"]["madeForKids"] is False


def test_publishat_uses_z_suffix_never_plus_zero():
    publish_at = datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc)
    body = build_insert_body(
        clip_row=_row(),
        video_row=_row(),
        padded_publish_at_utc=publish_at,
    )
    pub = body["status"]["publishAt"]
    assert pub.endswith("Z")
    assert "+00:00" not in pub


def test_categoryid_is_24_entertainment():
    publish_at = datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc)
    body = build_insert_body(
        clip_row=_row(),
        video_row=_row(),
        padded_publish_at_utc=publish_at,
    )
    assert body["snippet"]["categoryId"] == "24"


def test_default_languages_are_en():
    publish_at = datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc)
    body = build_insert_body(
        clip_row=_row(),
        video_row=_row(),
        padded_publish_at_utc=publish_at,
    )
    assert body["snippet"]["defaultLanguage"] == "en"
    assert body["snippet"]["defaultAudioLanguage"] == "en"


def test_title_includes_shorts_suffix():
    publish_at = datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc)
    body = build_insert_body(
        clip_row=_row(hook="iconic"),
        video_row=_row(hook="iconic"),
        padded_publish_at_utc=publish_at,
    )
    assert body["snippet"]["title"].endswith("#Shorts")
    # Hook text is in the description too.
    assert "iconic" in body["snippet"]["description"]

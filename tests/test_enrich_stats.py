"""videos.list responses sometimes hide likeCount/commentCount/viewCount."""

from src.discovery.enrich import _parse_item


def _item(stats: dict, *, duration: str = "PT5M") -> dict:
    return {
        "id": "abc123",
        "snippet": {
            "title": "T",
            "channelTitle": "C",
            "publishedAt": "2026-04-01T00:00:00Z",
        },
        "contentDetails": {"duration": duration},
        "statistics": stats,
    }


def test_all_present():
    meta = _parse_item(_item({"viewCount": "12345", "likeCount": "100", "commentCount": "50"}))
    assert meta is not None
    assert meta.views == 12345
    assert meta.likes == 100
    assert meta.comments == 50


def test_missing_likes_and_comments():
    meta = _parse_item(_item({"viewCount": "1000"}))
    assert meta is not None
    assert meta.likes == 0
    assert meta.comments == 0


def test_missing_views():
    meta = _parse_item(_item({"likeCount": "10"}))
    assert meta is not None
    assert meta.views == 0


def test_missing_snippet_returns_none():
    bad = {"id": "x", "contentDetails": {}, "statistics": {}}
    assert _parse_item(bad) is None


def test_zero_duration():
    meta = _parse_item(_item({"viewCount": "1"}, duration=""))
    assert meta is not None
    assert meta.duration_seconds == 0

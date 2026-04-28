"""YouTube videos.list enrichment, ledger-metered.

Batches IDs in groups of 50 (the videos.list API limit). Each call costs 1 unit
regardless of `part` count (YouTube charges flat for read methods).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.discovery.search import _call_with_ledger
from src.discovery.virality import parse_iso8601_duration
from src.quota_ledger import QuotaLedger

ENDPOINT = "videos.list"


@dataclass(frozen=True)
class VideoMeta:
    video_id: str
    title: str
    channel: str
    duration_seconds: int
    views: int
    likes: int
    comments: int
    published_at: str  # RFC 3339 UTC, as returned by YouTube


def _stat(stats: dict, key: str) -> int:
    """Read a count from videos.list `statistics`. Hidden counts -> 0."""
    raw = stats.get(key)
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _parse_item(item: dict) -> VideoMeta | None:
    snippet = item.get("snippet") or {}
    content = item.get("contentDetails") or {}
    stats = item.get("statistics") or {}
    video_id = item.get("id")
    title = snippet.get("title")
    channel = snippet.get("channelTitle")
    published_at = snippet.get("publishedAt")
    if not (video_id and title and channel and published_at):
        return None
    return VideoMeta(
        video_id=video_id,
        title=title,
        channel=channel,
        duration_seconds=parse_iso8601_duration(content.get("duration", "")),
        views=_stat(stats, "viewCount"),
        likes=_stat(stats, "likeCount"),
        comments=_stat(stats, "commentCount"),
        published_at=published_at,
    )


def enrich_videos(
    youtube,
    ledger: QuotaLedger,
    video_ids: list[str],
    *,
    videos_unit_cost: int,
) -> list[VideoMeta]:
    if not video_ids:
        return []

    by_id: dict[str, VideoMeta] = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        request = youtube.videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(batch),
        )
        response = _call_with_ledger(request, ledger, videos_unit_cost, ENDPOINT)
        for item in response.get("items", []):
            meta = _parse_item(item)
            if meta is not None:
                by_id[meta.video_id] = meta

    # Preserve input order; silently drop missing IDs (region-blocked/private/deleted).
    return [by_id[vid] for vid in video_ids if vid in by_id]

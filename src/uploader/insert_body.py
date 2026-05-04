"""Build the YouTube videos.insert body dict.

Pure function. Combines templater outputs + publish_at formatting into the
exact resource the API call serializes.

The body is locked at:
    snippet.categoryId = "24"               # Entertainment
    snippet.defaultLanguage = "en"
    snippet.defaultAudioLanguage = "en"
    status.privacyStatus = "private"
    status.publishAt = <ISO8601 with 'Z' suffix>
    status.selfDeclaredMadeForKids = False
    status.madeForKids = False
    status.license = "youtube"
    status.embeddable = True

Tests assert each of these so a future refactor that changes one
inadvertently fails loudly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from src.uploader.publish_at import format_publish_at_iso_z
from src.uploader.templater import build_description, build_tags, build_title


def build_insert_body(
    *,
    clip_row: Mapping[str, Any],
    video_row: Mapping[str, Any],
    padded_publish_at_utc: datetime,
) -> dict:
    """Construct the videos.insert resource body.

    `clip_row` and `video_row` are sqlite3.Row objects (or dict-like). We
    read clip.hook, clip.suggested_title, video.video_id, video.channel,
    video.keyword.
    """
    hook = clip_row["hook"] or ""
    suggested_title = clip_row["suggested_title"] or ""

    # The clip row from get_clip_with_video aliases video columns with v_ prefix
    # so they don't shadow clip columns. Fall back to the raw video_row keys
    # for callers that pass a separate row.
    def _v(key_v: str, key_plain: str) -> str:
        if key_v in video_row.keys() if hasattr(video_row, "keys") else False:
            val = video_row[key_v]
            if val is not None:
                return val
        try:
            return video_row[key_plain] or ""
        except (KeyError, IndexError):
            return ""

    video_id = _v("v_video_id", "video_id")
    channel = _v("v_channel", "channel")
    keyword = _v("v_keyword", "keyword")

    title = build_title(hook, suggested_title)
    description = build_description(
        hook=hook,
        suggested_title=suggested_title,
        video_id=video_id,
        channel=channel,
        keyword=keyword,
    )
    tags = build_tags(keyword)

    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "24",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": format_publish_at_iso_z(padded_publish_at_utc),
            "selfDeclaredMadeForKids": False,
            "madeForKids": False,
            "license": "youtube",
            "embeddable": True,
        },
    }

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
from src.uploader.templater import (
    build_description, build_description_ai,
    build_tags, build_tags_ai,
    build_title,
)


def build_insert_body(
    *,
    clip_row: Mapping[str, Any],
    video_row: Mapping[str, Any],
    padded_publish_at_utc: datetime,
    script_row: Mapping[str, Any] | None = None,
    cfg: Any = None,
) -> dict:
    """Construct the videos.insert resource body.

    For content_kind='ai_generated' clips, pass script_row (scripts table row)
    and cfg so the function can apply the AI description template and set
    status.containsSyntheticMedia when cfg.compliance.ai_disclosure is True.

    For content_kind='sourced' clips, script_row and cfg are not required;
    the sourced-clip path (Source URL + Original channel attribution) is used.
    """
    hook = clip_row["hook"] or ""
    suggested_title = clip_row["suggested_title"] or ""
    try:
        content_kind = clip_row["content_kind"] or "sourced"
    except (KeyError, IndexError):
        content_kind = "sourced"

    if content_kind == "ai_generated" and script_row is not None:
        category = script_row.get("category") if hasattr(script_row, "get") else script_row["category"]
        title = build_title(hook, suggested_title)
        description = build_description_ai(
            hook=hook,
            suggested_title=suggested_title,
            category=category,
        )
        tags = build_tags_ai(category=category, suggested_title=suggested_title)
    else:
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

    status: dict[str, Any] = {
        "privacyStatus": "private",
        "publishAt": format_publish_at_iso_z(padded_publish_at_utc),
        "selfDeclaredMadeForKids": False,
        "madeForKids": False,
        "license": "youtube",
        "embeddable": True,
    }
    if (content_kind == "ai_generated"
            and cfg is not None
            and getattr(getattr(cfg, "compliance", None), "ai_disclosure", False)):
        status["containsSyntheticMedia"] = True

    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "24",
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": status,
    }

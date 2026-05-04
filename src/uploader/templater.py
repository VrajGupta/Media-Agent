"""Title / description / tags templating for the YouTube videos.insert body.

Pure functions — no DB, no Ollama, no API. Inputs are clip-row + video-row +
config; outputs are the strings that feed `insert_body.build_insert_body`.

Title rule: `{hook} #Shorts`, ≤100 chars (YouTube limit). Truncates at the
last word boundary before 96 chars and re-appends ` #Shorts` so the hashtag
always survives. Falls back to suggested_title if hook is empty/whitespace.

Description rule: hook + source attribution + niche hashtag. Source is the
YouTube reuploader URL; original channel name is included for transparent
attribution (per CLAUDE.md risk-mitigation policy).

Tags rule: [<keyword>, "shorts", "viral"], lowercased + deduped.
Movie-clip post-pivot variant: ["shorts", "movie", "movieclip"] etc. — kept
configurable by accepting a list from cfg.upload_extra_tags when present.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence


# YouTube hard limits.
_TITLE_MAX = 100
_TAGS_TOTAL_MAX = 500          # combined character budget across all tags
_SHORTS_SUFFIX = " #Shorts"


def _slug_keyword(keyword: str) -> str:
    """Lowercase + collapse non-alphanumeric to nothing; for hashtag use."""
    return re.sub(r"[^a-z0-9]+", "", (keyword or "").lower())


def build_title(hook: str, suggested_title: str = "") -> str:
    """Build the upload title.

    Format: `{hook} #Shorts`. If the combined string exceeds 100 chars, the
    hook is truncated at the last word boundary that leaves room for ` #Shorts`
    (8 chars). If the hook is empty/whitespace, falls back to suggested_title.
    If both are empty, returns just `#Shorts`.
    """
    base = (hook or "").strip()
    if not base:
        base = (suggested_title or "").strip()
    if not base:
        return _SHORTS_SUFFIX.lstrip()  # bare "#Shorts"

    full = f"{base}{_SHORTS_SUFFIX}"
    if len(full) <= _TITLE_MAX:
        return full

    # Need to truncate base. Reserve room for the suffix.
    budget = _TITLE_MAX - len(_SHORTS_SUFFIX)
    truncated = base[:budget]
    # Trim back to the last word boundary so we don't slice mid-word.
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    truncated = truncated.rstrip()
    return f"{truncated}{_SHORTS_SUFFIX}"


def build_description(
    *,
    hook: str,
    suggested_title: str = "",
    video_id: str,
    channel: str,
    keyword: str,
) -> str:
    """Build the upload description with attribution + niche hashtag.

    Format:
        {hook}

        Source: https://youtube.com/watch?v={video_id}
        Original channel: {channel}

        #Shorts #{keyword_slug}
    """
    primary = (hook or "").strip() or (suggested_title or "").strip()
    parts = []
    if primary:
        parts.append(primary)
        parts.append("")
    parts.append(f"Source: https://youtube.com/watch?v={video_id}")
    if channel:
        parts.append(f"Original channel: {channel}")
    parts.append("")

    tags_line = "#Shorts"
    slug = _slug_keyword(keyword)
    if slug:
        tags_line = f"#Shorts #{slug}"
    parts.append(tags_line)
    return "\n".join(parts)


def build_tags(
    keyword: str,
    *,
    extra_tags: Sequence[str] | None = None,
) -> list[str]:
    """Build the tags list.

    Always includes the keyword (verbatim, lowercased) plus a small static
    set ['shorts', 'viral']. Adds extra_tags from config if supplied.
    Lowercased + deduped (preserving first-seen order). Truncated to fit
    the 500-char joined limit YouTube enforces.
    """
    seed: list[str] = []
    if keyword:
        seed.append(keyword.strip().lower())
    seed.extend(["shorts", "viral"])
    if extra_tags:
        seed.extend(t.strip().lower() for t in extra_tags if t and t.strip())

    seen: set[str] = set()
    deduped: list[str] = []
    for tag in seed:
        if tag and tag not in seen:
            seen.add(tag)
            deduped.append(tag)

    # Enforce the 500-char joined-length limit. YouTube counts
    # commas+quotes in some edge cases; our budget assumes worst case
    # comma-separated.
    budget = _TAGS_TOTAL_MAX
    fitted: list[str] = []
    used = 0
    for tag in deduped:
        # +1 for the implicit separator after the first tag.
        cost = len(tag) + (1 if fitted else 0)
        if used + cost > budget:
            break
        fitted.append(tag)
        used += cost
    return fitted

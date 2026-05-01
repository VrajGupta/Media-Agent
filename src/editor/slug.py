"""Filesystem-safe slug derived from a clip's suggested_title.

Output mp4s land at output/pending/__unscheduled__{clip_id}__{slug}.mp4
in Phase 4; Phase 6 (slot_planner) renames in place to the date+slot form.
The clip_id portion guarantees uniqueness; the slug is purely for human
readability when the user reviews output/pending/ in Explorer.
"""

from __future__ import annotations

import hashlib
import re

MAX_SLUG_LENGTH = 80


def _normalize(text: str) -> str:
    """lowercase, replace non-alphanumeric runs with _, trim leading/trailing _."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text


def _truncate_at_word_boundary(text: str, limit: int) -> str:
    """Keep <= limit chars; cut at the last `_` to avoid mid-word truncation."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_us = cut.rfind("_")
    # Prefer word boundary, but only if it leaves enough characters that the
    # slug remains useful (>= 50% of limit). Otherwise hard-truncate.
    if last_us >= limit // 2:
        return cut[:last_us]
    return cut


def title_slug(suggested_title: str, clip_id: str) -> str:
    """Returns a filesystem-safe slug.

    Always appends a 4-char hash of clip_id so two clips that produce the same
    normalized slug from different sources get distinct filenames. The hash
    suffix is stable for a given clip_id, so re-running the editor on the
    same clip emits the same filename.
    """
    base = _normalize(suggested_title or "untitled")
    if not base:
        base = "untitled"

    suffix = hashlib.sha1(clip_id.encode("utf-8")).hexdigest()[:4]
    suffix_with_sep = f"_{suffix}"
    base_limit = MAX_SLUG_LENGTH - len(suffix_with_sep)
    base = _truncate_at_word_boundary(base, base_limit)
    base = base.strip("_") or "untitled"
    return f"{base}{suffix_with_sep}"

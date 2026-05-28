"""Hacker News trending corroboration for topic selection (Issue 32 / ADR-0004)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import requests
from loguru import logger

_DEFAULT_TOP_STORIES = "https://hacker-news.firebaseio.com/v0/topstories.json"
_DEFAULT_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
_STOPWORDS = frozenset(
    "the a an is are was were be been being have has had do does did will would "
    "could should may might must at by for from in of on to up with about after "
    "and as but if into or so than that this too when where while just it its "
    "says said new over".split()
)


@dataclass(frozen=True)
class HnItem:
    title: str
    url: str


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def hn_corroboration(
    topic: dict,
    hn_items: list[HnItem],
    *,
    weight: float = 2.0,
    min_overlap: float = 0.25,
) -> float:
    """Pure overlap score between a Topic and HN front-page titles."""
    if not hn_items:
        return 0.0
    topic_text = f"{topic.get('title', '')} {topic.get('summary') or ''}"
    topic_tokens = _tokens(topic_text)
    if not topic_tokens:
        return 0.0
    best = 0.0
    for item in hn_items:
        hn_tokens = _tokens(item.title)
        if not hn_tokens:
            continue
        overlap = len(topic_tokens & hn_tokens) / len(topic_tokens | hn_tokens)
        best = max(best, overlap)
    if best < min_overlap:
        return 0.0
    return best * weight


def fetch_hn_front_page(
    cfg,
    *,
    _get: Callable[..., requests.Response] | None = None,
) -> list[HnItem]:
    """Fetch current HN front-page story titles. Failures return []."""
    get = _get or requests.get
    hn = getattr(cfg.topic_ingest, "hn", None)
    if hn is not None and not getattr(hn, "enabled", True):
        return []

    top_url = getattr(hn, "top_stories_url", _DEFAULT_TOP_STORIES) if hn else _DEFAULT_TOP_STORIES
    item_tpl = getattr(hn, "item_url_template", _DEFAULT_ITEM) if hn else _DEFAULT_ITEM
    max_stories = int(getattr(hn, "max_stories", 30) if hn else 30)

    try:
        resp = get(top_url, timeout=15)
        resp.raise_for_status()
        story_ids = resp.json()[:max_stories]
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("hn fetch top stories failed: {}", exc)
        return []

    items: list[HnItem] = []
    for story_id in story_ids:
        try:
            item_resp = get(item_tpl.format(id=story_id), timeout=15)
            item_resp.raise_for_status()
            data = item_resp.json()
        except (requests.RequestException, ValueError, TypeError):
            continue
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        url = str(data.get("url") or f"https://news.ycombinator.com/item?id={story_id}")
        items.append(HnItem(title=title.strip(), url=url))
    return items

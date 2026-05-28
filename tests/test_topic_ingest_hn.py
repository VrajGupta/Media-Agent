"""Issue 32 — HN trending corroboration (pure + mocked HTTP)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests

from src.topic_ingest.hn import HnItem, fetch_hn_front_page, hn_corroboration


def test_hn_corroboration_matching_topic_scores_higher():
    topic_match = {"title": "Anthropic releases Claude Opus 4.7", "summary": None}
    topic_other = {"title": "Random widget patch notes", "summary": None}
    hn_items = [
        HnItem(title="Anthropic releases Claude Opus 4.7 model", url="https://example.com/a"),
        HnItem(title="Unrelated gaming news", url="https://example.com/b"),
    ]
    match_score = hn_corroboration(topic_match, hn_items, weight=2.0)
    other_score = hn_corroboration(topic_other, hn_items, weight=2.0)
    assert match_score > other_score
    assert match_score > 0


def test_fetch_hn_front_page_parses_mocked_http():
    cfg = SimpleNamespace(
        topic_ingest=SimpleNamespace(
            hn=SimpleNamespace(
                enabled=True,
                top_stories_url="https://hn/top",
                item_url_template="https://hn/item/{id}",
                max_stories=2,
            )
        )
    )
    calls: list[str] = []

    def fake_get(url, timeout=None):
        calls.append(url)
        if url.endswith("/top"):
            body = json.dumps([1, 2])
        else:
            story_id = url.rsplit("/", 1)[-1]
            body = json.dumps({"title": f"Story {story_id}", "url": f"https://ex/{story_id}"})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: json.loads(body),
        )

    items = fetch_hn_front_page(cfg, _get=fake_get)
    assert len(items) == 2
    assert items[0].title == "Story 1"
    assert len(calls) == 3


def test_fetch_hn_front_page_failure_returns_empty():
    cfg = SimpleNamespace(
        topic_ingest=SimpleNamespace(
            hn=SimpleNamespace(
                enabled=True,
                top_stories_url="https://hn/top",
                item_url_template="https://hn/item/{id}",
                max_stories=5,
            )
        )
    )

    def boom(url, timeout=None):
        raise requests.ConnectionError("down")

    assert fetch_hn_front_page(cfg, _get=boom) == []

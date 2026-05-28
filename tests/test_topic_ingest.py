"""Ticket 02 — RSS topic ingest: fetch + dedup + persist.

Tests verify observable behaviour through the public interface:
  fetch_unscripted_topics(cfg, repo, *, _parse=None, _now=None) -> list[dict]

feedparser and the clock are injectable; no live network or real time needed.
"""

from __future__ import annotations

import calendar
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.state import Repository, connect, initialize_schema
from src.topic_ingest.runner import fetch_unscripted_topics


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
_FEED_URL = "http://fake.feed/rss"


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def _make_cfg(tmp_path, *, feeds=None, recency_hours=48, jaccard_threshold=0.6,
              seen_topics_window_days=30, stopwords=None, niche_gate_enabled=False,
              low_yield_threshold=1, recency_hours_extended=96):
    if stopwords is None:
        stopwords = ["the", "a", "an", "is", "are", "of", "in", "to", "and",
                     "it", "just", "new", "says", "said", "openai", "ships"]
    niche_gate = SimpleNamespace(
        enabled=niche_gate_enabled,
        low_yield_threshold=low_yield_threshold,
        recency_hours_extended=recency_hours_extended,
    )
    ti = SimpleNamespace(
        feeds=feeds if feeds is not None else [_FEED_URL],
        recency_hours=recency_hours,
        seen_topics_window_days=seen_topics_window_days,
        jaccard_threshold=jaccard_threshold,
        stopwords=stopwords,
        niche_gate=niche_gate if niche_gate_enabled else None,
    )
    return SimpleNamespace(
        topic_ingest=ti,
        ollama_model="qwen2.5:3b-instruct",
        paths=SimpleNamespace(logs_dir="logs"),
        abs_path=lambda rel: tmp_path / rel,
    )


def _ts(dt: datetime) -> time.struct_time:
    """Convert UTC datetime → time.struct_time (feedparser published_parsed format)."""
    return time.gmtime(calendar.timegm(dt.timetuple()))


def _entry(title, link, summary="", *, pub_dt=None, no_pub=False):
    """Build a feedparser-like entry namespace."""
    e = SimpleNamespace(title=title, link=link, summary=summary)
    if not no_pub:
        e.published_parsed = _ts(pub_dt if pub_dt is not None else _NOW - timedelta(hours=1))
    return e


def _feed(entries):
    return SimpleNamespace(entries=entries, bozo=False)


def _make_parse(feed_map: dict):
    """feed_map: {url: feedparser-result-namespace | list-of-entries}"""
    def _parse(url, **kwargs):
        val = feed_map.get(url, [])
        if isinstance(val, list):
            return _feed(val)
        return val
    return _parse


# ---------------------------------------------------------------------------
# Tracer bullet: single fresh item inserted and returned
# ---------------------------------------------------------------------------


def test_single_fresh_item_inserted_and_returned(repo, tmp_path):
    cfg = _make_cfg(tmp_path)
    fake_parse = _make_parse({_FEED_URL: [
        _entry("GPT-5 Released", "https://example.com/gpt5", "OpenAI ships GPT-5.")
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1
    assert result[0]["title"] == "GPT-5 Released"
    rows = repo.conn.execute("SELECT * FROM topics").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "unscripted"
    assert rows[0]["url"] == "https://example.com/gpt5"


# ---------------------------------------------------------------------------
# Recency filter
# ---------------------------------------------------------------------------


def test_item_older_than_window_excluded(repo, tmp_path):
    cfg = _make_cfg(tmp_path)
    too_old = _NOW - timedelta(hours=50)
    fake_parse = _make_parse({_FEED_URL: [
        _entry("Old News", "https://example.com/old", pub_dt=too_old)
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert result == []
    assert repo.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 0


def test_item_exactly_48h_old_excluded(repo, tmp_path):
    cfg = _make_cfg(tmp_path, recency_hours=48)
    exactly_at_boundary = _NOW - timedelta(hours=48)
    fake_parse = _make_parse({_FEED_URL: [
        _entry("Boundary News", "https://example.com/b", pub_dt=exactly_at_boundary)
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert result == []


def test_item_just_inside_window_included(repo, tmp_path):
    cfg = _make_cfg(tmp_path, recency_hours=48)
    just_inside = _NOW - timedelta(hours=47, minutes=59)
    fake_parse = _make_parse({_FEED_URL: [
        _entry("Fresh News", "https://example.com/fresh", pub_dt=just_inside)
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# URL hash dedup
# ---------------------------------------------------------------------------


def test_same_url_in_two_feeds_only_inserted_once(repo, tmp_path):
    url2 = "http://fake.feed2/rss"
    cfg = _make_cfg(tmp_path, feeds=[_FEED_URL, url2])
    same_url = "https://example.com/gpt5"
    fake_parse = _make_parse({
        _FEED_URL: [_entry("GPT-5 Released", same_url)],
        url2:      [_entry("GPT-5 Released", same_url)],
    })
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_second_run_inserts_zero_new_topics(repo, tmp_path):
    cfg = _make_cfg(tmp_path)
    fake_parse = _make_parse({_FEED_URL: [
        _entry("GPT-5 Released", "https://example.com/gpt5")
    ]})
    fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert repo.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Jaccard title-similarity dedup
# ---------------------------------------------------------------------------


def test_paraphrased_title_above_threshold_caught_as_dup(repo, tmp_path):
    cfg = _make_cfg(tmp_path, jaccard_threshold=0.5,
                   stopwords=["just", "a", "the", "is", "are", "openai", "ships"])
    fake_parse = _make_parse({_FEED_URL: [
        _entry("GPT-5 released today", "https://example.com/1"),
        _entry("GPT-5 released now",   "https://example.com/2"),
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1


def test_different_title_below_threshold_passes_through(repo, tmp_path):
    cfg = _make_cfg(tmp_path, jaccard_threshold=0.6,
                   stopwords=["just", "a", "the", "is", "are"])
    fake_parse = _make_parse({_FEED_URL: [
        _entry("GPT-5 released", "https://example.com/1"),
        _entry("Llama 4 benchmark beats rivals", "https://example.com/2"),
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 2


def test_jaccard_exact_threshold_is_dup(repo, tmp_path):
    """Jaccard ≥ threshold is a dup (inclusive boundary)."""
    cfg = _make_cfg(tmp_path, jaccard_threshold=0.5,
                   stopwords=["the", "a"])
    # word sets: {"gpt", "five"} vs {"gpt", "five"} → Jaccard = 1.0 ≥ 0.5
    fake_parse = _make_parse({_FEED_URL: [
        _entry("GPT five launch", "https://example.com/1"),
        _entry("GPT five launch", "https://example.com/2"),
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Stopword strip
# ---------------------------------------------------------------------------


def test_stopword_strip_is_case_insensitive(repo, tmp_path):
    """'The GPT-5 Release' and 'gpt-5 release' should be same word set after strip."""
    stopwords = ["the", "a", "an"]
    cfg = _make_cfg(tmp_path, jaccard_threshold=0.99, stopwords=stopwords)
    fake_parse = _make_parse({_FEED_URL: [
        _entry("The GPT-5 Release", "https://example.com/1"),
        _entry("gpt-5 release",     "https://example.com/2"),
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Empty feed handling
# ---------------------------------------------------------------------------


def test_empty_single_feed_continues_with_others(repo, tmp_path):
    url2 = "http://fake.feed2/rss"
    cfg = _make_cfg(tmp_path, feeds=[_FEED_URL, url2])
    fake_parse = _make_parse({
        _FEED_URL: [],   # empty
        url2: [_entry("Llama 4 released", "https://example.com/l4")],
    })
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1
    assert result[0]["title"] == "Llama 4 released"


def test_all_feeds_empty_writes_alert_and_returns_empty(repo, tmp_path):
    cfg = _make_cfg(tmp_path, feeds=[_FEED_URL])
    fake_parse = _make_parse({_FEED_URL: []})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert result == []
    alert_path = tmp_path / "logs" / "alerts.md"
    assert alert_path.exists()
    content = alert_path.read_text(encoding="utf-8")
    assert "topic_ingest_empty" in content


# ---------------------------------------------------------------------------
# Multi-feed aggregation
# ---------------------------------------------------------------------------


def test_distinct_items_from_two_feeds_all_inserted(repo, tmp_path):
    url2 = "http://fake.feed2/rss"
    cfg = _make_cfg(tmp_path, feeds=[_FEED_URL, url2])
    fake_parse = _make_parse({
        _FEED_URL: [_entry("GPT-5 Released", "https://example.com/g")],
        url2:      [_entry("Llama 4 Scores", "https://example.com/l")],
    })
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 2
    assert repo.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# Missing pubDate fallback
# ---------------------------------------------------------------------------


def test_missing_pubdate_falls_back_to_fetched_at(repo, tmp_path):
    cfg = _make_cfg(tmp_path)
    fake_parse = _make_parse({_FEED_URL: [
        _entry("No Date Story", "https://example.com/nd", no_pub=True)
    ]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1
    row = repo.conn.execute("SELECT published_at FROM topics").fetchone()
    assert row["published_at"] is None


# ---------------------------------------------------------------------------
# Malformed entry skipped gracefully
# ---------------------------------------------------------------------------


def test_malformed_entry_without_link_skipped(repo, tmp_path):
    cfg = _make_cfg(tmp_path)
    bad = SimpleNamespace(title="No link here")   # no .link attribute
    good = _entry("Good Story", "https://example.com/good")
    fake_parse = _make_parse({_FEED_URL: [bad, good]})
    result = fetch_unscripted_topics(cfg, repo, _parse=fake_parse, _now=lambda: _NOW)
    assert len(result) == 1
    assert result[0]["title"] == "Good Story"


# ---------------------------------------------------------------------------
# dry_run: returns results without writing to DB
# ---------------------------------------------------------------------------


def test_dry_run_returns_topics_without_db_writes(repo, tmp_path):
    cfg = _make_cfg(tmp_path)
    fake_parse = _make_parse({_FEED_URL: [
        _entry("GPT-5 Released", "https://example.com/gpt5")
    ]})
    result = fetch_unscripted_topics(
        cfg, repo, _parse=fake_parse, _now=lambda: _NOW, dry_run=True
    )
    assert len(result) == 1
    assert result[0]["title"] == "GPT-5 Released"
    assert repo.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 0
    assert repo.conn.execute("SELECT COUNT(*) FROM seen_topics").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Issue 31 — niche gate at ingest
# ---------------------------------------------------------------------------


def test_off_niche_topic_never_persisted(repo, tmp_path):
    cfg = _make_cfg(tmp_path, niche_gate_enabled=True)

    def _classify(title, summary, *, model):
        from src.topic_ingest.niche_gate import NicheVerdict
        if "OnlyFans" in title:
            return NicheVerdict("off_niche", "culture entertainment", False)
        return NicheVerdict("on_niche", "ai launch", False)

    fake_parse = _make_parse({_FEED_URL: [
        _entry(
            "Apple TV OnlyFans shows",
            "https://example.com/bad",
            "culture story",
        ),
        _entry("GPT-5 Released", "https://example.com/good", "OpenAI ships GPT-5."),
    ]})
    result = fetch_unscripted_topics(
        cfg, repo, _parse=fake_parse, _now=lambda: _NOW, _classify_niche=_classify
    )
    assert len(result) == 1
    assert result[0]["title"] == "GPT-5 Released"
    assert repo.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 1


def test_low_yield_widens_recency_window(repo, tmp_path):
    cfg = _make_cfg(
        tmp_path,
        niche_gate_enabled=True,
        recency_hours=48,
        recency_hours_extended=96,
        low_yield_threshold=1,
    )
    inside_48h = _NOW - timedelta(hours=47)
    inside_96h = _NOW - timedelta(hours=72)

    def _classify(title, summary, *, model):
        from src.topic_ingest.niche_gate import NicheVerdict
        return NicheVerdict("on_niche", "ok", False)

    fake_parse = _make_parse({_FEED_URL: [
        _entry("Older AI launch", "https://example.com/old", pub_dt=inside_96h),
    ]})
    result = fetch_unscripted_topics(
        cfg, repo, _parse=fake_parse, _now=lambda: _NOW, _classify_niche=_classify
    )
    assert len(result) == 1
    assert result[0]["title"] == "Older AI launch"

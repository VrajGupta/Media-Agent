"""RSS topic ingest — Pivot.6 Ticket 02.

Public seam: fetch_unscripted_topics(cfg, repo) -> list[dict]

Everything else (feedparser invocation, dedup, persists) lives behind this
interface. The orchestrator (gen_run.py) calls this and nothing else.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from loguru import logger

from src.observability.alerts import append_alert
from src.topic_ingest.niche_gate import NicheVerdict, classify_niche


# ---------------------------------------------------------------------------
# Title normalisation helpers
# ---------------------------------------------------------------------------


def _normalize(title: str, stopwords: set[str]) -> str:
    """Lowercase, strip punctuation, remove stopwords. Returns space-joined string."""
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    words = [w for w in title.split() if w not in stopwords]
    return " ".join(words)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_title_dup(word_set: set[str], seen_sets: list[set[str]], threshold: float) -> bool:
    return any(_jaccard(word_set, s) >= threshold for s in seen_sets)


def _niche_gate_enabled(cfg) -> bool:
    ng = getattr(cfg.topic_ingest, "niche_gate", None)
    return bool(ng and getattr(ng, "enabled", False))


def _apply_niche_gate(
    title: str,
    summary: str | None,
    cfg,
    *,
    _classify: Callable[..., NicheVerdict] | None = None,
) -> bool:
    """Return True if the topic should be persisted (on-niche)."""
    classify = _classify or classify_niche
    model = getattr(cfg, "ollama_model", "qwen2.5:3b-instruct")
    verdict = classify(title, summary, model=model)
    if verdict.is_on_niche:
        return True
    logger.debug("niche_gate: off_niche — {} — {}", verdict.reason, title)
    return False


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def fetch_unscripted_topics(
    cfg,
    repo,
    *,
    _parse: Callable[..., Any] | None = None,
    _now: Callable[[], datetime] | None = None,
    _classify_niche: Callable[..., NicheVerdict] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Fetch RSS feeds, dedup, persist fresh topics. Returns list of inserted topics.

    _parse: injectable feedparser.parse (default: real feedparser)
    _now:   injectable clock (default: datetime.now(UTC))
    _classify_niche: injectable niche gate (default: classify_niche)
    dry_run: if True, compute results but skip all DB and file writes
    """
    if _parse is None:
        import feedparser as _fp
        _parse = _fp.parse
    if _now is None:
        _now = lambda: datetime.now(timezone.utc)

    ti = cfg.topic_ingest
    now = _now()
    stopwords = set(w.lower() for w in ti.stopwords)
    niche_enabled = _niche_gate_enabled(cfg)
    ng = getattr(ti, "niche_gate", None)
    low_yield_threshold = int(getattr(ng, "low_yield_threshold", 1)) if ng else 1
    extended_hours = int(getattr(ng, "recency_hours_extended", 96)) if ng else 96

    seen_rows = repo.seen_topics_in_window(ti.seen_topics_window_days)
    seen_hashes: set[str] = {r["url_hash"] for r in seen_rows}
    seen_norm_sets: list[set[str]] = [
        set(r["title_normalized"].split()) for r in seen_rows if r["title_normalized"]
    ]

    fetched_at_str = now.isoformat().replace("+00:00", "Z")
    all_feeds_empty = True

    def _collect(recency_hours: int) -> list[dict]:
        nonlocal all_feeds_empty
        cutoff = now - timedelta(hours=recency_hours)
        batch: list[dict] = []

        for feed_url in ti.feeds:
            try:
                parsed = _parse(feed_url)
            except Exception as exc:
                logger.warning("feed {} parse error: {}", feed_url, exc)
                continue

            entries = getattr(parsed, "entries", None) or []
            if not entries:
                logger.info("feed {} returned 0 entries, skipping", feed_url)
                continue

            all_feeds_empty = False

            for entry in entries:
                link = getattr(entry, "link", None)
                title = getattr(entry, "title", None)
                if not link or not title:
                    logger.debug("skipping malformed entry in {}", feed_url)
                    continue

                pub_parsed = getattr(entry, "published_parsed", None)
                if pub_parsed:
                    pub_dt = datetime.fromtimestamp(
                        calendar.timegm(pub_parsed), tz=timezone.utc
                    )
                    published_at = pub_dt.isoformat().replace("+00:00", "Z")
                    recency_dt = pub_dt
                else:
                    published_at = None
                    recency_dt = now

                if recency_dt <= cutoff:
                    continue

                url_hash = hashlib.sha256(link.encode()).hexdigest()
                if url_hash in seen_hashes:
                    continue

                normalized = _normalize(title, stopwords)
                word_set = set(normalized.split())
                if _is_title_dup(word_set, seen_norm_sets, ti.jaccard_threshold):
                    continue

                summary = getattr(entry, "summary", None) or None

                if niche_enabled and not _apply_niche_gate(
                    title,
                    summary,
                    cfg,
                    _classify=_classify_niche,
                ):
                    continue

                if not dry_run:
                    topic_id = repo.insert_topic(
                        url=link,
                        title=title,
                        summary=summary,
                        source_feed=feed_url,
                        fetched_at=fetched_at_str,
                        published_at=published_at,
                    )
                    repo.insert_seen_topic(
                        url_hash=url_hash,
                        title_normalized=normalized,
                        first_seen_at=fetched_at_str,
                    )
                else:
                    topic_id = None

                seen_hashes.add(url_hash)
                seen_norm_sets.append(word_set)

                batch.append({
                    "id": topic_id,
                    "title": title,
                    "url": link,
                    "source_feed": feed_url,
                    "published_at": published_at,
                })

        return batch

    inserted = _collect(ti.recency_hours)
    if niche_enabled and len(inserted) < low_yield_threshold and ti.recency_hours < extended_hours:
        inserted.extend(_collect(extended_hours))

    if all_feeds_empty and not dry_run:
        logs_dir = cfg.abs_path(cfg.paths.logs_dir)
        append_alert(
            logs_dir,
            kind="topic_ingest_empty",
            message="all configured RSS feeds returned 0 entries",
        )

    return inserted

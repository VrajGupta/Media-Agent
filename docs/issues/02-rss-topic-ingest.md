# Ticket 02 — RSS topic ingest (fetch + dedup + persist)

**Type:** AFK
**Slice in plan.md:** Slice 7
**User stories covered:** 3, 4, 10, 17, 18, 20

## Parent

PRD: `docs/prds/automated-topic-to-script-pipeline.md`

## What to build

A deep module at `src/topic_ingest/` that fetches the configured RSS feed list, filters to items from the last 48 hours, dedups them against the last 30 days of seen topics, and persists fresh items to the `topics` table. The dedup logic combines exact URL-hash match (SHA-256 of `<link>`) with Jaccard word-set overlap of normalized titles (≥ 0.6 threshold, configurable). Title normalization is lowercase + punctuation strip + stopword removal.

Public seam: a single function `fetch_unscripted_topics(cfg, repo) -> list[Topic]`. Everything else — `feedparser` invocation, the dedup ledger writes, the per-feed error handling — lives behind that interface. The orchestrator (Slice 8, future) will call this function and nothing else.

Empty-feed handling: skip + INFO log + continue with remaining feeds. All-feeds-empty: write `topic_ingest_empty` alert to `logs/alerts.md`, return empty list. Topic `published_at` from RSS `<pubDate>` if present; falls back to `fetched_at` if missing.

A CLI entrypoint (`python -m src.topic_ingest`) runs the full ingest end-to-end against the configured feeds. Supports `--dry-run` (no DB writes, just reports what would be inserted).

## Acceptance criteria

- [ ] Public function `fetch_unscripted_topics(cfg, repo)` exists in `src/topic_ingest/runner.py`.
- [ ] Recency filter: items with `published_at` (or `fetched_at` fallback) older than `cfg.topic_ingest.recency_hours` (default 48) are excluded. Test verifies the window boundary.
- [ ] URL hash dedup: identical URLs across feeds → only the first is inserted; the second writes nothing (PK conflict on `seen_topics.url_hash`).
- [ ] Title-similarity dedup: paraphrased reposts (e.g., "GPT-5 just released" vs "OpenAI ships GPT-5") with Jaccard ≥ 0.6 after stopword strip are caught. Verified with at least 3 test cases (boundary, well-above, well-below).
- [ ] Stopword strip: case-insensitive, punctuation-tolerant; stopword list from `cfg.topic_ingest.stopwords`. Test with mixed-case, punctuated titles.
- [ ] Empty single feed: logs INFO, doesn't raise, continues with remaining feeds.
- [ ] All feeds empty: writes one row to `logs/alerts.md` kind=`topic_ingest_empty`, returns `[]`.
- [ ] Idempotency: running ingest twice within the dedup window inserts zero rows on the second pass.
- [ ] CLI: `python -m src.topic_ingest` runs end-to-end against `cfg.topic_ingest.feeds` and prints a summary. `--dry-run` flag prevents DB writes.
- [ ] `feedparser` and the HTTP layer are mocked in tests (no live network calls). Prior art: `tests/ai_gen/test_openrouter_kling.py`.
- [ ] Config validates: `Config.topic_ingest` is a nested Pydantic sub-model (per the P4 pattern) with typed fields `feeds: list[str]`, `recency_hours: int = 48`, `seen_topics_window_days: int = 30`, `jaccard_threshold: float = 0.6`, `stopwords: list[str]`.
- [ ] At least 10 unit tests covering: recency boundary, URL hash dedup, Jaccard threshold boundary, stopword strip case-insensitivity, empty single feed, all-feeds-empty alert, idempotent rerun, multi-feed aggregation correctness, missing `<pubDate>` fallback, malformed feed item skipped gracefully.

## Blocked by

- Ticket 01 (schema migration must land first; this ticket writes to `topics` and `seen_topics` tables that 01 creates).

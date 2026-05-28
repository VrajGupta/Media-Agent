# Ticket 30 — Curated AI-focused feed list

**Status:** ready-for-agent
**Type:** AFK
**Slice:** AI-niche refit / 1
**User Stories:** 11, 12, 13 (PRD `ai-niche-trending-selection-and-photo-framing.md`)

## Parent

PRD: `docs/prds/ai-niche-trending-selection-and-photo-framing.md`
Decision record: `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`

## What to build

Replace the mixed consumer/research feed list with an AI-focused one so the input carries less culture/think-piece noise at the source, and document it.

End-to-end behavior:

1. **Curated `topic_ingest.feeds`** in `config.yaml`:
   - **Add:** Anthropic blog feed, Google AI blog feed.
   - **Swap:** The Verge main feed → The Verge AI subfeed; Ars Technica main/technology-lab → the Ars AI subfeed.
   - **Keep:** OpenAI, Google DeepMind, Hugging Face.
   - **Drop:** VentureBeat (think-piece/enterprise-analysis noise).
2. **Update `docs/rss_feeds.md`** — the feed table and rationale column to match the curated list.
3. Feeds remain **config-only**: adding/removing a feed must require no code change (no behavior regression in `topic_ingest.runner`).

No DB schema change. No billed API calls.

## Acceptance criteria

- [ ] `config.yaml` `topic_ingest.feeds` is the curated list (Anthropic + Google AI added; Verge/Ars swapped to AI subfeeds; VentureBeat removed; OpenAI/DeepMind/HF kept).
- [ ] An ingest run against the new feeds pulls recent AI items into `topics`; no Verge-culture items appear.
- [ ] Each new feed URL resolves to a valid RSS/Atom endpoint (English, stable).
- [ ] `docs/rss_feeds.md` reflects the curated list with rationale per feed.
- [ ] `topic_ingest.runner` reads feeds from config unchanged (no hardcoding); existing ingest tests stay green.
- [ ] Full suite green.

## Blocked by

None - can start immediately.

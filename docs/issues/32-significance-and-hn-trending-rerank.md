# Ticket 32 — Significance + Hacker News trending rerank

**Status:** ready-for-agent
**Type:** AFK
**Slice:** AI-niche refit / 3
**User Stories:** 5, 8, 9, 10 (PRD `ai-niche-trending-selection-and-photo-framing.md`)

## Parent

PRD: `docs/prds/ai-niche-trending-selection-and-photo-framing.md`
Decision record: `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`

## What to build

Replace the novelty/tension topic scoring (which rewarded "weird and edgy" — the exact axis that picked the OnlyFans story at 6.9) with a **Significance** judgment plus a free **Hacker News** trending corroboration, so "big launch from a major player, trending now" ranks first.

End-to-end behavior:

1. **Significance scorer.** Rewrite the `score_topics` scorer prompt + weighting in `scripter/runner.py`. Drop `0.4·novelty + 0.3·specificity + 0.3·tension`. The model emits a **Significance** judgment (how major the launch × how authoritative the player); the weighting becomes `significance × source_authority_weight + hn_corroboration_boost`. `source_authority_weight` is a config map keyed by `source_feed` (primary lab/vendor blogs weighted above aggregators).
2. **HN corroboration seams** (keyless, free):
   - `fetch_hn_front_page(cfg) -> list[HnItem]` — public HN top-stories/front-page endpoint; on failure returns empty and logs a warning (selection then proceeds on Significance alone).
   - **Pure** `hn_corroboration(topic, hn_items) -> float` — scores subject/title/entity overlap between a **Topic** and current front-page stories; feeds `hn_corroboration_boost`.
3. **Wiring.** `score_topics` consumes the HN signal during ranking; the scored/floor/`update_topic_score` plumbing (`run_stage_a`) is otherwise unchanged. Reuse the existing Ollama model; no new paid dependency or key.

No DB schema change (reuses `topic_score_json` / `weighted_score`).

## Acceptance criteria

- [ ] `score_topics` ranks by `significance × source_authority + hn_boost`; the novelty/specificity/tension formula is gone.
- [ ] A major-lab launch outranks an incremental/minor item; an HN-corroborated topic ranks above an identical non-corroborated one; primary-source feeds outweigh aggregators via the `source_authority` map.
- [ ] HN fetch failure does not error the run — selection proceeds on Significance alone (graceful degrade, warning logged).
- [ ] New config keys load: `scripter` `source_authority` map + `hn_boost`; `topic_ingest.hn` enable/endpoint/weight.
- [ ] No new paid dependency or API key (HN is keyless; Ollama reused).
- [ ] **Tests Required:** (a) significance weighting — pure: lab launch > minor item, HN-corroborated boosted, source authority applied; (b) `hn_corroboration` — pure: matching topic scores higher than non-matching; (c) `fetch_hn_front_page` — mocked HTTP parses the front page, and a fetch failure returns empty. Follow the HTTP-mocked `test_openrouter_kling.py` + existing scripter scoring test style.
- [ ] **Mock Injections:** HN HTTP mocked; Ollama mocked; no network in unit tests.
- [ ] Full suite green.

## Blocked by

None - can start immediately. (Independent of Tickets 30/31; touches the scoring layer only.)

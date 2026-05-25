# Ticket 03 — Scripter Stage A: topic scoring + categorization + top-4 diversity pick

**Type:** AFK
**Slice in plan.md:** Slice 6 (Stage A of three)
**User stories covered:** 5, 6, 7, 15, 16, 19

## Parent

PRD: `docs/prds/automated-topic-to-script-pipeline.md`

## What to build

The first stage of `src/scripter/` — pulls `unscripted` topics from the DB, has Ollama score each one and tag each with a category, then picks the top 4 with a one-unique-category-per-pick diversity gate. Output: 4 rows in `topics` table transitioned to `status='scored'` with `topic_score_json` populated.

Two Ollama callsites, both injectable for testability (per P3 pattern in `tests/test_policy_evaluator_injection.py`):

1. **Topic scorer** — Ollama JSON-mode returns `{novelty: int 1-10, specificity: int 1-10, tension: int 1-10, reason: str}`. Local code computes `weighted_score = 0.4*novelty + 0.3*specificity + 0.3*tension`. Out-of-range sub-scores trigger one retry; persistent garbage drops the topic with INFO log.

2. **Category tagger** — Ollama JSON-mode returns `{category: str}` constrained to one value from `cfg.scripter.categories`. Off-list categories trigger one retry; persistent off-list drops the topic.

Selection algorithm: sort all scored topics by `weighted_score` DESC, then greedy-pick — take #1 unconditionally; for each subsequent pick, require a category not yet used in this batch. Stop at 4 picks or pool exhaustion. If the diversity gate blocks pool exhaustion below 4 picks, apply failure-mode (b) from the PRD: degrade to "no two same product/entity" instead of "unique category"; if still <4, render whatever's available (could be 3, 2, 1). If 0 picks, halt + write alert.

A CLI entrypoint (`python -m src.scripter --stage a`) runs this stage standalone for testing.

## Acceptance criteria

- [ ] Public functions in `src/scripter/runner.py`: `score_topics(topics, scorer_fn) -> list[ScoredTopic]`, `tag_categories(topics, tagger_fn, allowed) -> list[CategorizedTopic]`, `select_topics(scored, n=4) -> list[Topic]`. Each takes injectable Ollama callables.
- [ ] Topic scorer: returns valid sub-scores; out-of-range sub-scores (e.g., 11, -1) trigger one retry then drop. Test with mock returning each failure mode.
- [ ] Category tagger: only `cfg.scripter.categories` values accepted; off-list triggers retry then drop.
- [ ] Diversity-aware selection: when 4+ topics with 4+ distinct categories exist, picks 4 with unique categories. When only 3 distinct categories available, applies the failure-mode degrade (drop diversity strictness) and reports 3 or fewer picks. When 0 categories available (pool empty), halt + alert kind=`topic_diversity_starved`.
- [ ] All Ollama calls persist `topic_score_json` (full sub-scores + reason) and the picked category onto the `topics` row. Audit trail verifiable via SQL.
- [ ] Selected topics transition to `status='scored'`. Non-selected scored topics also persist their scores (audit) but stay at `status='unscripted'` for next-week reuse if still fresh.
- [ ] Config: `Config.scripter` has nested fields `topic_score_weights: {novelty: 0.4, specificity: 0.3, tension: 0.3}`, `categories: list[str]` defaulting to `["ai_models","ai_features","hardware","software","policy","business","science_research","startup_funding"]`, `candidate_pool_size: int = 4`.
- [ ] CLI: `python -m src.scripter --stage a` runs end-to-end. `--dry-run` reads but doesn't write.
- [ ] Ollama is fully mocked in tests (no GPU/network needed). Prior art: `tests/test_policy_evaluator_injection.py`.
- [ ] At least 12 unit tests covering: valid-score scoring path, out-of-range retry then drop, off-list category retry then drop, diversity gate with 4 distinct categories, diversity gate with 3 categories (degrade), diversity gate with 0 categories (halt+alert), audit JSON persistence, ranking determinism, weighted-score formula, selection idempotency across reruns, status transition to `scored`, malformed-JSON Ollama response handling.

## Blocked by

- Ticket 01 (schema must exist).
- Ticket 02 (needs `topics` table populated with real `unscripted` rows to score).

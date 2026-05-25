# Ticket 04 — Scripter Stage B: script generation with shape gates + policy gate + retry

**Type:** AFK
**Slice in plan.md:** Slice 6 (Stage B of three)
**User stories covered:** 2, 8, 15, 19, 21

## Parent

PRD: `docs/prds/automated-topic-to-script-pipeline.md`

## What to build

The middle stage of `src/scripter/` — takes the 4 `scored` topics from Stage A, calls Ollama JSON-mode to generate a complete script for each, validates schema + shape gates + policy gate, and persists valid scripts to the `scripts` table. Handles retry-on-failure with a budget, and greedy-backfills from the wider scored-topic ranking when a topic's retries are exhausted.

Public function: `generate_scripts(picked_topics, all_scored_topics, generator_fn, policy_fn, cfg) -> list[Script]`. Both Ollama callables injected; no `ollama_host` parameter threading (P3 pattern).

For each picked topic, the generation loop:

1. Call `generator_fn(topic, cfg.scripter.style_suffix)` → expect JSON shaped like:
   ```json
   {
     "title": "...",
     "narration": "...",
     "shots": [{"index":0,"prompt":"...","duration_s":4}, ... 4 total],
     "style_notes": "..."
   }
   ```
2. Pydantic-validate the schema.
3. Run shape gates:
   - `narration` word count ∈ `[cfg.scripter.narration_word_count_min, max]` (default `[30, 50]`)
   - Hook in first `cfg.scripter.hook_word_count` words (default 5)
   - No banned tokens (`cfg.scripter.banned_tokens`, default includes `<<placeholder>>`, "I think", "as an AI")
4. Run `policy_fn(narration, title)` (the existing policy gate).
5. On any failure: retry with stricter prompt up to `cfg.scripter.retry_on_failure` (default 3). On exhausted retries: drop this topic, take the next-best from `all_scored_topics` (filtered for category diversity per Stage A's gate). If backfill pool is exhausted, return fewer than 4 scripts.

All scripts (passing or failing) persist their generation attempts for audit. Successful scripts land at `status='scripted'`. Policy-rejected scripts land at `status='rejected_policy'` with `rejection_reason` populated.

A CLI entrypoint (`python -m src.scripter --stage b`) runs this stage on the existing `scored` topics.

## Acceptance criteria

- [ ] Public function `generate_scripts(picked, all_scored, generator_fn, policy_fn, cfg)` in `src/scripter/runner.py`.
- [ ] Pydantic schema validation: malformed JSON → retry. Missing required fields → retry. Wrong shot count (≠4) → retry.
- [ ] Shape gates run after schema validation: narration < 30 words → retry; > 50 words → retry; banned token in narration or title → retry; hook position fails (heuristic: first clause length > 5 words) → retry.
- [ ] Policy gate: existing `policy_fn` invoked with `(narration, title)`. Rejection → script row written with `status='rejected_policy'`, `rejection_reason` populated, retry NOT triggered (per existing policy_gate contract: retry only on infra failure, not content rejection).
- [ ] Infra failure on Ollama (unreachable, malformed beyond JSON-parseable): retry up to `retry_on_failure` times with backoff. Exhausted retries → drop topic, take next-best from `all_scored_topics` filtered by category diversity.
- [ ] Greedy backfill: when topic #2 fails after retries, next-best in ranking (with a not-yet-used category) is promoted. Test verifies the backfill respects diversity.
- [ ] Backfill pool exhausted: return fewer than 4 scripts; don't loop forever; write `scripter_backfill_exhausted` alert if returned count < 2.
- [ ] All successful scripts persist to `scripts` table with: `script_id` (uuid), `topic_id` FK, `title`, `narration`, `shots_json` (JSON-serialized), `style_suffix`, `ollama_model`, `created_at`, `category` (copied from topic), `status='scripted'`. `topic_score_json` is on the linked topic row.
- [ ] Style suffix (from `cfg.scripter.style_suffix`, default the clean editorial string from grilling) is appended to every shot prompt before storage. Stored verbatim on the script row.
- [ ] Stub `clips` row created with `content_kind='ai_generated'`, `script_id` FK, `video_id=NULL`. Used downstream by ai_gen.
- [ ] Config: `Config.scripter` gains `style_suffix: str`, `narration_word_count_min: int = 30`, `narration_word_count_max: int = 50`, `hook_word_count: int = 5`, `banned_tokens: list[str]`, `retry_on_failure: int = 3`.
- [ ] CLI: `python -m src.scripter --stage b`. `--dry-run` flag.
- [ ] At least 14 unit tests covering: happy-path generation, pydantic validation failure → retry, narration too short → retry, narration too long → retry, banned token in narration → retry, hook position fail → retry, policy gate rejection writes rejected row no retry, retry budget exhaustion drops topic, backfill picks next-best with category diversity, backfill pool exhausted returns <4, infra Ollama failure retried then halted, stub clips row created, script_id is unique UUID, audit fields persisted.

## Blocked by

- Ticket 01 (schema), Ticket 03 (needs `scored` topics).

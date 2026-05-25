# PRD — Automated Topic-to-Script Pipeline

> **Scope:** Pivot.6 Slices 3 + 6 + 7. Builds the upstream half of the corrected Tech/AI news pipeline — everything from "RSS feed has new tech news" to "two scored scripts are sitting in the DB ready to be sent to Kling for $4 of generation." **Spends zero OpenRouter money.** When you top up OpenRouter and want to run Slice 2 (Kling spike), the prompts will come from this pipeline's output, not from hand-typed test data.
>
> **Status of upstream context:** All decisions in this PRD came out of a `/grill-with-docs` session on 2026-05-18. See `plan.md` for the full Pivot.6 slice tracker.

## Problem Statement

I want to publish 2 well-made Tech/AI news Shorts per week to YouTube on a fully automated cadence (no script-reading, no topic-curation). My only manual touchpoint is reviewing finished video clips in `output/pending/` before they upload.

Today, the upstream half of the pipeline doesn't exist:
- The state store has no concept of "topic" or "script" — `topics`, `seen_topics`, `scripts`, `generation_jobs` tables are not in the schema.
- There's no module that pulls fresh tech/AI news from RSS feeds, dedups across feeds, and queues candidate topics.
- There's no module that turns a topic into a structured script with hook/narration/shot prompts.
- There's nothing scoring topics or scripts, so the system can't pick the best 2-of-4 to spend Kling money on.

Without all of this, even after I top up OpenRouter I can't run the Kling spike (Slice 2) against realistic prompts — I'd be hand-typing test data that doesn't reflect what the production system will actually generate. That makes the aesthetic sign-off worth less and risks me locking in a style suffix that breaks when fed real generated prompts.

I also have a hard budget constraint of ~$5/week on OpenRouter Kling, which forces a max of ~2 clips/week. The system has to ruthlessly select the best 2 scripts out of every batch — and do it automatically, since reading scripts isn't something I want to do every week.

## Solution

A three-stage automated pipeline that produces a weekly queue of two render-ready scripts:

1. **RSS ingest** (Slice 7) — Pulls last-48h items from a mix of consumer + research tech/AI feeds. Dedups by URL hash + word-set title similarity (Jaccard ≥ 0.6) against the last 30 days. Lands fresh items in a `topics` table.

2. **Schema bridge** (Slice 3) — Adds `topics`, `seen_topics`, `scripts`, `generation_jobs` tables; `content_kind` + `script_id` columns on `clips`; `provider` column on `quota_usage`. Idempotent migration. Existing 457 tests stay green.

3. **Scripter** (Slice 6) — Two-stage Ollama-driven selection plus generation:
   - Stage A (topic selection): score every fresh topic 1–10 on novelty/specificity/tension; tag each with a category from a fixed list; pick top 4 with one-category-per-pick diversity.
   - Stage B (script generation): for each of the 4 picked topics, generate a pydantic-validated `{title, narration ≈40 words, shots[4], style_notes}` JSON via Ollama JSON-mode. Run shape gates (word count, hook position, banned tokens) and the existing policy gate. Retry on failure.
   - Stage C (script selection): score the 4 finished scripts 1–10 on hook-execution/pacing/payoff. Pick top 2. Anything below 6/10 doesn't ship — render best 1, halt+alert on the other slot.

Together, these produce 2 winning scripts each weekly run. The render/upload half (Slices 4, 5, 8, 9, 10) is downstream of this PRD and remains blocked until I top up OpenRouter.

## User Stories

1. As a creator on a tight $5/week budget, I want the system to algorithmically pick the best 2 scripts out of a batch of 4, so that I never spend Kling money on a mediocre script.

2. As a creator who doesn't want to read drafts, I want quality enforcement to happen via automated scoring gates, so that the human-review touchpoint is only at the finished-video level.

3. As a tech-news channel, I want fresh topics pulled from RSS feeds every weekly run, so that the content reflects what's happening in tech/AI right now, not what some static config file said months ago.

4. As a small channel, I want stories to be deduped across feeds, so that the same OpenAI announcement covered by The Verge and TechCrunch doesn't get scripted twice.

5. As a channel building an editorial voice, I want topic scoring against three clear dimensions (novelty / specificity / tension) instead of a vague single number, so that the rubric is debuggable and I can see why a topic was picked.

6. As a creator who wants varied content, I want the system to refuse to ship two scripts in the same category in one week, so that the channel doesn't feel like "this week was all GPT updates."

7. As a developer iterating on the rubric, I want every Ollama scoring call to persist its sub-scores and reasoning into the DB, so that I can audit "why did the system score this topic 7/10?" weeks later.

8. As a creator who can't afford ugly clips, I want hook-position and word-count gates to catch broken scripts before they cost any Kling money, so that schema-valid-but-narratively-broken scripts don't slip through.

9. As a creator running on an unreliable home network, I want explicit failure modes — alert and halt on Ollama unreachable, alert and degrade on diversity-starved batches, halt + alert when all 4 scripts score below the floor — so that I know exactly when to intervene.

10. As a creator who wants to validate the pipeline before spending real money, I want a free dry run of the whole upstream half (RSS → scripts in DB) that produces real artifacts I can inspect via SQL, so that I trust the system before topping up OpenRouter.

11. As a developer touching shared state, I want the migration to be idempotent and non-destructive, so that I can re-run it on the live DB without losing the 457 existing tests' worth of historical data.

12. As a developer maintaining the existing daily upload flow, I want a regression test confirming the legacy `quality_pass` clip body is still built correctly post-migration, so that the new `content_kind` column doesn't break legacy uploads.

13. As a creator with a fixed weekly cadence, I want top-2 selection to happen via a second Ollama pass scoring on hook-execution / pacing / payoff (different rubric than topic scoring), so that a great script of a meh topic can beat a flat script of a great topic.

14. As a creator who doesn't want my channel to go dark on slow news weeks, I want the failure matrix to ship at least 1 clip when possible and only halt when no good option exists.

15. As a developer running TDD, I want each Ollama call (topic score, category tag, script score) to be injectable behind a callable seam, so that I can mock it cleanly in tests without spinning up a real Ollama instance.

16. As a future maintainer reading the codebase, I want the topic categorization tag list to live in config, not hard-coded, so that the niche can pivot again without a code change.

17. As a developer testing dedup, I want the Jaccard threshold (0.6) and the stopword list to live in config, so that I can tune them based on observed false-positive/false-negative rates without redeploys.

18. As a developer building topic_ingest, I want the public interface to be a single function — `fetch_unscripted_topics(cfg, repo) -> list[Topic]` — so that the orchestrator (`gen_run.py`, Slice 8) consumes it without knowing about feed parsing internals.

19. As a developer building the scripter, I want the public interface to be `score_topics() + select_topics() + generate_scripts() + score_scripts() + select_scripts()` as separately-callable functions, so that the orchestrator can compose them and so that each step is testable in isolation.

20. As a creator, I want the topic recency window (48h) and the seen-topics window (30 days) to live in config, so that I can experiment with broader windows if my feed mix is too sparse.

21. As a developer, I want all retry behaviour (Ollama malformed JSON, schema validation fails, policy gate rejection) to be bounded with explicit retry budgets, so that a flaky Ollama doesn't infinite-loop the weekly run.

22. As a developer, I want the schema migration to live in a script under `scripts/` (not buried in module init), so that I can run it explicitly with `python -m scripts.<migration> --dry-run` before committing.

## Implementation Decisions

### Modules

Two new deep modules + shallow extensions to existing infrastructure:

- **`src/topic_ingest/`** — Deep module. Public seam: `fetch_unscripted_topics(cfg, repo) -> list[Topic]`. Hides feed parsing (`feedparser`), recency filtering (last 48 h), and dedup (URL hash + Jaccard ≥ 0.6 word-set overlap with stopword strip) behind one interface. Empty-feed handling: log + skip + continue.

- **`src/scripter/`** — Deep module exposing five separately-composable functions: `score_topics`, `select_topics`, `generate_scripts`, `score_scripts`, `select_scripts`. Hides Ollama prompt templating, JSON-mode invocation, pydantic validation, shape gates, policy gate integration, and retry logic. Each function takes injectable Ollama callables for clean mocking.

- **`src/state/repository.py`** — Shallow extension. New DAL helpers: `insert_topic`, `seen_topics_in_window`, `mark_topic_scripted`, `mark_topic_expired`, `insert_script`, `update_script_status`, `clips_for_generation_run`, `get_clip_with_script`. Follows the existing DAL pattern.

- **`src/state/schema.sql`** — Schema bridge: new tables (`topics`, `seen_topics`, `scripts`, `generation_jobs`), new columns (`clips.content_kind`, `clips.script_id`, `quota_usage.provider`), `clips.video_id` relaxed to nullable. Comment-only update for status enum extensions.

- **`scripts/migrate_pivot_6_3.py`** — Standalone idempotent migration script with `--dry-run` flag. Applies the schema changes; safe to re-run.

### Topic scoring rubric (Slice 6 Stage A)

Ollama `qwen2.5:3b-instruct` JSON-mode. Prompt instructs the model to return:

```
{
  "novelty": <int 1-10>,
  "specificity": <int 1-10>,
  "tension": <int 1-10>,
  "weighted_score": <float — computed locally, not by model>,
  "reason": "<one sentence>"
}
```

Local code computes `weighted_score = 0.4 * novelty + 0.3 * specificity + 0.3 * tension`. The model is asked to provide the three component scores plus a one-sentence reason; the weighted score is deterministic post-processing.

Three rubric dimensions:
- **Novelty** — "Is this a thing people haven't heard before, or routine?" Penalizes incremental updates.
- **Specificity** — "Is there a concrete fact/number/event, or vague speculation?" Penalizes "AI will change everything."
- **Tension** — "Is there a stake, conflict, or surprise?" Rewards "X beat Y at Z."

### Category tagging (Slice 6 diversity gate)

Separate Ollama call per topic. Returns single category string from a config-driven list. Initial set (lives in config):

`ai_models, ai_features, hardware, software, policy, business, science_research, startup_funding`

Diversity constraint: within the 4-pick batch, each picked topic must have a unique category. If fewer than 4 distinct categories are present among scored topics, degrade per the failure matrix.

### Top-4 topic selection

Sort scored topics by `weighted_score` descending. Greedily pick top-scored, then for each subsequent pick reject any topic with a category already used in this batch. Continue until 4 picked or pool exhausted.

### Script generation (Slice 6 Stage B)

For each picked topic, Ollama JSON-mode produces:

```
{
  "title": "<≤100 char string>",
  "narration": "<single string, ~40 words>",
  "shots": [
    {"index": 0, "prompt": "<string>", "duration_s": 4},
    {"index": 1, "prompt": "<string>", "duration_s": 4},
    {"index": 2, "prompt": "<string>", "duration_s": 4},
    {"index": 3, "prompt": "<string>", "duration_s": 4}
  ],
  "style_notes": "<optional string>"
}
```

Pydantic validates the schema. Shape gates check:
- Narration word count ∈ [30, 50]
- Hook within first 5 words (heuristic: first complete clause)
- No banned tokens (`<<placeholder>>`, "I think", "as an AI", "<<...>>` patterns)

Policy gate (existing infrastructure) runs on `narration` + `title`.

On failure (schema invalid, shape gate fail, or policy reject), retry with a stricter prompt up to `scripter.retry_on_failure` times (config, default 3). On exhausted retries: drop that topic, pick next-best from the topic ranking (greedy backfill).

### Script scoring rubric (Slice 6 Stage C)

Different rubric than topic scoring because the question is different:
- **Topic scoring:** "Is this story video-worthy?"
- **Script scoring:** "Did the writer actually nail a Shorts video for this story?"

Ollama JSON-mode returns:

```
{
  "hook_execution": <1-10>,
  "pacing": <1-10>,
  "payoff": <1-10>,
  "weighted_score": <float — computed locally>,
  "reason": "<one sentence>"
}
```

Weighted: `0.4 * hook_execution + 0.3 * pacing + 0.3 * payoff`. Stored on `scripts.quality_score` for audit + later threshold tuning.

### Top-2 script selection

Sort 4 scored scripts by `quality_score` descending. Pick top 2 if both ≥ 6.0. If only top 1 ≥ 6.0, render that one and halt+alert on the second slot. If none ≥ 6.0, halt+alert on both slots.

### Failure matrix

| Failure | Behaviour |
|---|---|
| RSS yields 0 unscripted topics | Halt run + write alert (`logs/alerts.md` kind=`topic_ingest_empty`) |
| Diversity constraint allows <4 picks | Degrade — drop diversity from "unique category" to "no two same product/entity," try again. If still <4 picks, render whatever you have (3, 2, or 1). If 0, halt + alert. |
| All retries exhausted on a topic's script generation | Drop topic, greedy-backfill from next-best in topic ranking |
| Ollama unreachable | Halt run + write alert (kind=`ollama_unreachable`) |
| All 4 written scripts score <6.0 | Render top 1 if it exists, halt+alert on the other slot. If even top 1 <6.0, halt+alert on both. |

### Schema specifics

```sql
CREATE TABLE topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  source_feed TEXT NOT NULL,
  fetched_at TEXT NOT NULL,       -- ISO Z
  published_at TEXT,              -- ISO Z, from RSS pubDate
  status TEXT NOT NULL DEFAULT 'unscripted'  -- 'unscripted' | 'scored' | 'scripted' | 'expired'
);

CREATE TABLE seen_topics (
  url_hash TEXT PRIMARY KEY,      -- SHA-256 hex of URL
  title_normalized TEXT NOT NULL, -- lowercased, stripped, stopwords removed
  first_seen_at TEXT NOT NULL     -- ISO Z
);

CREATE TABLE scripts (
  script_id TEXT PRIMARY KEY,
  topic_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  narration TEXT NOT NULL,
  shots_json TEXT NOT NULL,       -- JSON array
  style_suffix TEXT NOT NULL,
  ollama_model TEXT NOT NULL,
  topic_score_json TEXT,          -- novelty/specificity/tension subscores + weighted + reason
  category TEXT,
  quality_score_json TEXT,        -- hook/pacing/payoff subscores + weighted + reason
  quality_score REAL,             -- denormalised weighted score for sorting
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'  -- 'pending' | 'scripted' | 'rejected_policy' | 'selected_for_render' | 'failed'
);

CREATE TABLE generation_jobs (
  job_id TEXT PRIMARY KEY,
  script_id TEXT NOT NULL,
  shot_index INTEGER NOT NULL,
  provider TEXT NOT NULL,         -- 'openrouter_kling' etc.
  prompt TEXT NOT NULL,
  duration_s INTEGER NOT NULL,
  status TEXT NOT NULL,           -- 'pending' | 'submitted' | 'succeeded' | 'failed'
  external_id TEXT,
  output_path TEXT,
  cost_cents INTEGER,
  submitted_at TEXT,
  completed_at TEXT,
  error TEXT
);

ALTER TABLE clips ADD COLUMN content_kind TEXT NOT NULL DEFAULT 'sourced';
ALTER TABLE clips ADD COLUMN script_id TEXT;
-- clips.video_id relaxed to nullable: implemented via table rebuild
--   (SQLite can't ALTER COLUMN). Migration script handles this idempotently.

ALTER TABLE quota_usage ADD COLUMN provider TEXT NOT NULL DEFAULT 'youtube';
```

Foreign keys: enable per-connection via `PRAGMA foreign_keys=ON`. Indexes added for hot paths: `topics.fetched_at`, `topics.status`, `seen_topics.url_hash` (PK auto), `scripts.status`, `scripts.topic_id`, `generation_jobs.script_id`.

### Ollama call injection

All three Ollama callsites (topic-score, category-tag, script-score) take callables injected via constructor / function parameter, following the P3 pattern from the Architecture Deepening work. Default callables wrap real Ollama; tests inject mock callables. No `ollama_host` parameter threaded through call chains.

### Config additions

New nested sub-models on `Config` (following P4 pattern):

- `topic_ingest` — `feeds: list[str]`, `recency_hours: int = 48`, `seen_topics_window_days: int = 30`, `jaccard_threshold: float = 0.6`, `stopwords: list[str]`
- `scripter` — `topic_score_weights: {novelty, specificity, tension}`, `script_score_weights: {hook_execution, pacing, payoff}`, `categories: list[str]`, `quality_floor: float = 6.0`, `narration_word_count_min: 30`, `narration_word_count_max: 50`, `hook_word_count: 5`, `banned_tokens: list[str]`, `retry_on_failure: int = 3`, `weekly_clip_target: int = 2`, `candidate_pool_size: int = 4`

## Testing Decisions

A good test for these modules verifies **external observable behaviour through public interfaces** — never implementation details. Concretely:

- A topic_ingest test verifies "given these feeds, this dedup ledger, and this current time, these specific Topic rows land in the repo" — NOT "feedparser.parse() is called twice."
- A scripter test verifies "given this Topic, this stubbed Ollama callable, and this policy gate result, this Script row lands with these scores" — NOT "the prompt string contains the substring 'hook'."
- A schema migration test verifies "starting from the prior schema, running the migration produces a DB with these tables, columns, and constraints, and the existing rows are unchanged" — NOT "the migration script calls X function in Y order."

### Modules to be tested (per user confirmation during grilling)

**`topic_ingest`** — high test coverage. HTTP mocked, in-memory repo, deterministic clock. Key behaviours:
- 48 h window correctly filters items by published_at
- URL hash dedup catches identical URLs across runs
- Jaccard ≥ 0.6 word-set dedup catches paraphrased reposts after stopword strip
- Stopword strip is case-insensitive and punctuation-tolerant
- Empty feed yields zero topics + INFO log, doesn't raise
- All-feeds-empty case writes alert and returns []
- Multiple feeds aggregated correctly (no missed items, no double-counted items)
- Topic.published_at falls back to fetched_at when RSS pubDate is missing
- Re-running ingest within the dedup window is a no-op (seen_topics PK prevents reinsert)

**`scripter`** — high test coverage. Mock Ollama callable (so no GPU/network in tests), in-memory repo. Key behaviours:
- Topic scoring returns valid sub-scores in 1-10 range; weighted score computed locally; out-of-range model output handled (clamped or rejected with retry)
- Category tagging returns one value from the config list; "off-list" model output triggers retry; persistent off-list output halts that topic
- Diversity gate: 4 picks with distinct categories when available
- Diversity gate degrade: 3-distinct + retry, then 2-distinct, then fail per failure matrix
- Shape gates: word count out of [30,50] triggers retry; missing hook in first 5 words triggers retry; banned tokens trigger retry
- Policy gate rejection bumps scripts.status='rejected_policy', drops topic, picks next
- Retry budget: at most `retry_on_failure` retries per topic; on exhaustion, topic dropped + next-best backfilled
- Script scoring returns valid sub-scores; weighted score persisted; below-floor (6.0) scripts NOT selected for render
- All-below-floor case: render top 1 + halt-alert on the other slot
- Both-below-floor case: halt-alert on both slots
- Ollama-unreachable: halt + alert, no partial state
- Audit trail: `topic_score_json` and `quality_score_json` populated with sub-scores + reason for every scored row

**Schema migration** — focused tests. Real SQLite with a copy of the live DB. Key behaviours:
- Migration applied to fresh DB: produces correct schema
- Migration applied to live DB (with Phase 0-7 historical rows): no data loss, no schema breakage, existing 457 tests still green
- Migration applied twice: second run is a no-op (idempotency)
- `daily_upload.py --dry-run` regression: on a legacy `quality_pass` clip, body output is byte-identical to pre-migration (no `content_kind`-driven branching for `'sourced'` rows)
- Foreign key enforcement: works when `PRAGMA foreign_keys=ON`; INSERT into `scripts` with invalid `topic_id` fails

### Prior art

- `tests/ai_gen/test_openrouter_kling.py` (23 tests, already shipped) — exemplar for HTTP-mocked external-service module testing.
- `tests/test_repository_p1.py` (16 tests) — exemplar for DAL extension testing.
- `tests/test_policy_evaluator_injection.py` (7 tests) — exemplar for injectable-callable seam testing; this is the pattern Ollama mocks should follow.
- `tests/test_config_p4.py` (43 tests) — exemplar for new nested Pydantic config sub-model validation.

## Out of Scope

Explicitly NOT in this PRD (deferred to other slices):

- **OpenRouter Kling spike (Slice 2)** — requires user to top up OpenRouter; this PRD produces the prompts that spike will consume but does not run the spike.
- **Narration / TTS module (Slice 5)** — Edge TTS + Whisper forced-align; no audio touched here.
- **Subtitles writer rewrite (Slice 5)** — karaoke → line-at-a-time ASS.
- **Assembler / ffmpeg pipeline (Slice 4)** — no video assembly.
- **`gen_run.py` orchestrator (Slice 8)** — this PRD produces the building blocks; the weekly-cadence orchestrator wires them together with run lock + alerts.
- **AI disclosure compliance refit (Slice 9)** — uploader templater changes for `content_kind='ai_generated'`.
- **First live AI-generated upload (Slice 10)** — depends on Slices 4, 5, 8, 9 plus money on OpenRouter.
- **Style suffix iteration on real Kling output** — locked to the grilled clean editorial suffix until Slice 2 produces evidence.
- **Tuning the quality floor (6.0)** — locked for now; will be revisited after 4 weeks of shipped clips with YouTube performance data.
- **Cleaning up retired tables** (`videos`, `niche_baselines`, `discovery_attempts`) — inert; future housekeeping pivot.

## Further Notes

- This PRD is the unblocking precondition for Slice 2 (Kling spike). Once it's shipped, you can top up OpenRouter, generate one weekly batch of scripts, and feed the top-2 winning scripts' shot prompts into the Kling spike — producing a realistic aesthetic sign-off rather than a synthetic one.
- The pipeline is intentionally over-instrumented: every Ollama scoring call persists sub-scores + reason. Looks expensive at first, but the audit trail is what lets the rubric be tuned later without re-running grilling sessions.
- Three Ollama calls per topic per week (score + tag + script-score, post-generation), one Ollama call per topic for generation itself. For a 30-topic-pool, 4-script-batch weekly run: ~94 Ollama calls/week. All free, all local. The model stays loaded between calls.
- The failure matrix prefers shipping 1 great clip over shipping 2 mediocre clips. Channels go dark on slow weeks rather than diluting the editorial bar — this is a deliberate decision from grilling.

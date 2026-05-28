# Phase: architecture
**Project:** Media-Agent (Pivot.6 → Pivot.7)
**Status:** in-progress
**Last updated:** 2026-05-26

## Objective

Design the database schema, configuration model, DAL layer, and module boundaries for the Pivot.6 AI-generated pipeline. All structural decisions (tables, columns, Pydantic models, repository interfaces) are locked here.

## Key Decisions

- **SQLite state store** — single `data/state.db` file. No external DB. All pipeline state flows through repository helpers.
- **Schema strategy:** Additive-only Pivot.6 migration (`scripts/migrate_pivot_6_3.py`, idempotent with `--dry-run`). Never drop columns; only add new tables and new columns with DEFAULT.
- **Four new Pivot.6 tables:** `topics`, `seen_topics`, `scripts`, `generation_jobs`.
- **`clips.content_kind`** — `TEXT DEFAULT 'sourced'`. Values: `'sourced'` (legacy) | `'ai_generated'` (Pivot.6). Drives templater branch, disclosure flag.
- **`clips.video_id` relaxed to nullable** — AI-gen clips have no source video.
- **`clips.script_id TEXT`** — nullable FK to `scripts.script_id`.
- **`quota_usage.provider TEXT DEFAULT 'youtube'`** — `youtube` | `openrouter`. Enables per-provider spend tracking.
- **Pydantic Config god-object** — single `Config` aggregating sub-models: `TopicIngestConfig`, `AiGenConfig`, `ScripterConfig`, `NarrationConfig`, `SubtitlesConfig`, `ComplianceConfig`, `Retention`, `Paths`. YAML → validated object at startup.
- **Repository pattern (DAL)** — all SQL behind 50+ typed helpers in `state/repository.py`. No raw SQL outside `repository.py`. `tx()` context manager for multi-step writes.
- **Dependency injection for callables** — `run_stage_b(cfg, repo, topics, *, generator_fn)` pattern. Test doubles injected; no monkeypatching of module globals.
- **Provider ABC** — `ai_gen/base.py` defines `Provider` interface. `OpenRouterKlingClient` is production; `KlingClient` is fallback (API blocked on direct auth). Swappable without changing orchestrator.
- **Module deprecation pattern** — `discovery/`, `downloader/`, `lang_detect/`, `selector/` retained as dead code for regression safety. Not called by any Pivot.6 path. Tests still run.
- **[Pivot.7, ADR-0002] Canonical shot normalization in the assembler** — every **Shot** is conformed to one canonical format (**1080×1920, 30fps, yuv420p, SAR 1:1**, resolution from `cfg.output_resolution`) inside the filtergraph before it is **Stitched**. Kling std actually emits 720×1280@24 (CLAUDE.md's "native 1080×1920" was wrong); Ken Burns is 1080×1920@30. Without normalization, `xfade` (and the concat demuxer) fail on the mismatch (`err -22` / rc 4294967274). Normalization lives in a pure deep module (`src/assembler/normalize.py`); the crossfade-off path uses the concat *filter* (not the demuxer) on normalized inputs; all Clips canonicalize (pure-AI too).
- **[2026-05-27, ADR-0004] AI-centric niche + ingest relevance gate + significance/HN selection.** Niche narrowed to AI-centric + flagship launches; a hard LLM on/off-niche gate runs in `topic_ingest` *before* the `topics` insert (reject-before-persist); topic ranking moves from `novelty/specificity/tension` to **Significance × source-authority + Hacker-News trending corroboration** (keyless, graceful degrade). No schema change (rejection pre-persist; reuses `topic_score_json`/`weighted_score`). New deep seams: `classify_niche` (Ollama, mocked), `fetch_hn_front_page` + pure `hn_corroboration`. Decomposed into Issues 30–34.

## Accomplishments

- [2026-05-18] schema.sql extended with 4 new tables + nullable video_id + new columns.
- [2026-05-18] `scripts/migrate_pivot_6_3.py` written — idempotent migration (Ticket 01, 27 tests green).
- [2026-05-18] `src/state/repository.py` extended with 8 new DAL helpers for Pivot.6 tables.
- [2026-05-18] `src/config_loader/loader.py` extended with `TopicIngestConfig`, `AiGenConfig`, `ScripterConfig`, `NarrationConfig`, `SubtitlesConfig`, `ComplianceConfig` sub-models.
- [2026-05-20] `src/scripter/ollama_fns.py` — 4 callable factories wired to DI slots in runner.py.
- [2026-05-22] `src/gen_run.py` — orchestrator module with per-stage lambda pipeline and unified error handling.
- [2026-05-26] Issue 22 implemented (`bca0095`): `src/assembler/normalize.py` + normalized filtergraph in `build.py`. ADR-0002 now live in code.
- [2026-05-27] ADR-0004 authored (planning only, not yet in code): AI-centric niche, ingest relevance gate, significance/HN topic selection. Issues 30–34 published `ready-for-agent`.

## Artifacts

| Artifact | Path | Notes |
|---|---|---|
| Schema DDL | `src/state/schema.sql` | All tables incl. 4 Pivot.6 tables |
| Migration script | `scripts/migrate_pivot_6_3.py` | Idempotent. Run with `--dry-run` first |
| Repository DAL | `src/state/repository.py` | 50+ helpers; all SQL lives here |
| Config models | `src/config_loader/loader.py` | Pydantic, YAML-validated at startup |
| Provider ABC | `src/ai_gen/base.py` | Interface for video generators |
| Schema tests | `tests/test_repository_pivot6.py` | 27 tests |
| ADR-0002 | `docs/adr/0002-canonical-shot-normalization-in-assembler.md` | Assembler normalization decision |
| Grill record | `CONTEXT/Grilling/2026-05-26-hybrid-assembly-xfade.md` | Evidence + locked decisions |
| Normalize module | `src/assembler/normalize.py` | ADR-0002 implementation |
| Fix PRD | `docs/prds/p7-fix-hybrid-assembly-normalization.md` | Issues 22–25 |

## Sessions

- Ticket 01 (schema migration + DAL) — 2026-05-18
- Config model refactor — 2026-05-18 / 2026-05-19
- [p7-hybrid-assembly-fix-plan](.sessions/2026-05-26__p7-hybrid-assembly-fix-plan/handoff.md) — 2026-05-26: ADR-0002 + Issues 22–25 planning
- [issue-22-shot-normalization-tdd](../.sessions/2026-05-26__issue-22-shot-normalization-tdd/handoff.md) — 2026-05-26: implementation commit `bca0095`

## Open Items

- ~~Migration not applied to live DB~~ — applied 2026-05-24 (see Pivot.6 INDEX).
- `generation_jobs` table does not yet have a `retry_count` column — considered but deferred.
- ~~ADR-0002 normalization not implemented~~ — **done** (`bca0095`). Live hybrid spike verification still pending.

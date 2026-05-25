# Phase: architecture
**Project:** Media-Agent (Pivot.6)
**Status:** complete
**Last updated:** 2026-05-24

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

## Accomplishments

- [2026-05-18] schema.sql extended with 4 new tables + nullable video_id + new columns.
- [2026-05-18] `scripts/migrate_pivot_6_3.py` written — idempotent migration (Ticket 01, 27 tests green).
- [2026-05-18] `src/state/repository.py` extended with 8 new DAL helpers for Pivot.6 tables.
- [2026-05-18] `src/config_loader/loader.py` extended with `TopicIngestConfig`, `AiGenConfig`, `ScripterConfig`, `NarrationConfig`, `SubtitlesConfig`, `ComplianceConfig` sub-models.
- [2026-05-20] `src/scripter/ollama_fns.py` — 4 callable factories wired to DI slots in runner.py.
- [2026-05-22] `src/gen_run.py` — orchestrator module with per-stage lambda pipeline and unified error handling.

## Artifacts

| Artifact | Path | Notes |
|---|---|---|
| Schema DDL | `src/state/schema.sql` | All tables incl. 4 Pivot.6 tables |
| Migration script | `scripts/migrate_pivot_6_3.py` | Idempotent. Run with `--dry-run` first |
| Repository DAL | `src/state/repository.py` | 50+ helpers; all SQL lives here |
| Config models | `src/config_loader/loader.py` | Pydantic, YAML-validated at startup |
| Provider ABC | `src/ai_gen/base.py` | Interface for video generators |
| Schema tests | `tests/test_repository_pivot6.py` | 27 tests |

## Sessions

- Ticket 01 (schema migration + DAL) — 2026-05-18
- Config model refactor — 2026-05-18 / 2026-05-19

## Open Items

- Migration has been committed but NOT applied to live `data/state.db` yet. Must run before Slice 10 unblock. Back up `data/state.db` first — this is the blocking DB migration.
- `generation_jobs` table does not yet have a `retry_count` column — considered but deferred.

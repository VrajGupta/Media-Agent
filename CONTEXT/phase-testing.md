# Phase: testing
**Project:** Media-Agent (Pivot.6)
**Status:** in-progress
**Last updated:** 2026-05-27

## Objective

Maintain a comprehensive test suite that covers all pipeline modules. Tests must catch regressions across the sourced-clip legacy path and the Pivot.6 AI-gen path without hitting real APIs, real Ollama, or real SQLite writes in unit tests.

## Key Decisions

- **pytest** — sole test runner. No unittest.
- **Dependency injection over monkeypatching** — all Ollama/Kling/YouTube callables are injected. Test doubles passed directly; no `mock.patch` on module-level imports where avoidable.
- **StubConfig in conftest.py** — shared fixture for all unit tests. Pivot.6-specific fields not on `StubConfig` are added in local `_GenStubConfig` per test file (e.g., `test_gen_run.py`).
- **No real I/O in unit tests** — no real HTTP, no real Ollama, no real ffmpeg, no real SQLite writes (in-memory DB or tmp paths only).
- **457+ total tests** — all green except 7 pre-existing config failures (topic_pool removed in Pivot.6; ai_gen missing from config.yaml). These are known; do not fix silently.
- **Deprecated module tests retained** — `test_selector_*.py`, `test_downloader_*.py` etc. still run. They guard against accidental breakage of the legacy sourced-clip path even though those modules are no longer called by Pivot.6.
- **Ticket 01 tests** (`test_repository_pivot6.py`) — 27 tests cover all new DAL helpers for Pivot.6 tables.
- **Ollama callable tests** — `make_topic_scorer`, `make_topic_tagger`, `make_script_generator`, `make_script_scorer` tested with mocked HTTP responses (not real Ollama).
- **Quality screen loudness test** — 3-tier: pass ±0.5 LUFS / warn ±0.5..±1.5 / reject >±1.5. Tested with synthetic audio fixtures.
- **Uploader templater tests** — two branches: `content_kind='sourced'` and `content_kind='ai_generated'`. Both paths must be covered.
- **Policy gate tests** — `evaluate_clip_policy()` is pure; injected callables allow full coverage without Ollama.

## Accomplishments

- [2026-05-18] 27 Ticket 01 tests — schema migration + DAL helpers.
- [2026-05-18] 16 Ticket 02 tests — RSS ingest + dedup.
- [2026-05-18] 13 Ticket 03 tests — topic scoring Stage A.
- [2026-05-19] 13 Ticket 04 tests — script generation Stage B.
- [2026-05-19] 11 Ticket 05 tests — script scoring Stage C.
- [2026-05-22] 10 Slice 8 tests (`test_gen_run.py`) — orchestrator pipeline.
- [2026-05-22] Slice 9 tests — uploader templater AI-gen branch.
- [2026-05-09] Phase 7 hardening — run_lock, retention, alerts, runs_writer tests added.
- [2026-05-09] Phase 4.5 — policy_gate (4 checks + pure evaluator) + quality_screen (6 gates) tests.
- [2026-05-27] Issue 33 — 8 Ken Burns argv/pure-helper tests (`tests/assembler/test_ken_burns.py`).
- [2026-05-27] Issue 31 — 5 niche-gate unit + 2 ingest integration tests.

## Artifacts

| Artifact | Path | Notes |
|---|---|---|
| Test root | `tests/` | 457+ tests total |
| Shared fixtures | `tests/conftest.py` | `StubConfig`, shared DB fixtures |
| Schema/DAL tests | `tests/test_repository_pivot6.py` | 27 tests for Pivot.6 DAL |
| RSS ingest tests | `tests/test_topic_ingest.py` | 16 tests |
| Scripter Stage A | `tests/test_scripter_stage_a.py` | 13 tests |
| Scripter Stage B | `tests/test_scripter_stage_b.py` | 13 tests |
| Scripter Stage C | `tests/test_scripter_stage_c.py` | 11 tests |
| Orchestrator tests | `tests/test_gen_run.py` | 10 tests (Slice 8) |
| Uploader tests | `tests/test_uploader_*.py` | templater, insert_body, resumable, orphan_marker, runner |
| Policy gate tests | `tests/test_policy_*.py` | banlist, profanity, NSFW, hook_sanity, evaluator |
| Assembler tests | `tests/assembler/test_build.py`, `test_normalize.py`, `test_assemble_mixed_res.py` | argv + lavfi ffmpeg integration |

## Sessions

- Ticket 01–05 TDD sessions (2026-05-18/2026-05-19)
- Slice 8 + 9 test additions (2026-05-22)
- [issue-22-shot-normalization-tdd](../.sessions/2026-05-26__issue-22-shot-normalization-tdd/handoff.md) — 2026-05-26

## Open Items

- 7 pre-existing config failures (topic_pool, ai_gen) — known, tracked, not fixed yet.
- [2026-05-26] Issue 26 TDD: `test_shot_plan.py`, `test_bootstrap_copyright.py`, licensed probe test. Issue 22 integration tests remain uncommitted pending live spike.
- No integration tests that hit real Ollama or real OpenRouter. End-to-end verified only manually.
- [2026-05-24] Issue 11 tests (`test_render_from_script_reuse`, `test_insert_ai_gen_clip`) — 8 tests.
- [2026-05-24] Issue 14 tests (`test_upload_weekdays`, allocator weekday cases, runner wire-through) — 11 tests.
- [2026-05-24] Aligner CUDA→CPU fallback test in `tests/narration/test_aligner.py`.
- No load / perf tests for `ThreadPool` concurrency in `ai_gen/runner.py`.

# TDD cycles — AI-niche refit Issues 30–34

Session: `.sessions/2026-05-27__issue-33-ken-burns-tdd/`

## Issue 33 — Ken Burns (prior session)

Tracer: `test_ken_burns_zoompan_does_not_force_full_frame_on_foreground` → gradient bg + fitted zoompan. **8 tests green.**

## Issue 31 — Niche gate (prior session)

Tracer: `test_onlyfans_apple_tv_story_is_off_niche` → `niche_gate.py` + runner wiring. **7 tests green.**

## Issue 30 — Curated feeds

1. **RED→GREEN:** `test_config_yaml_has_curated_ai_feeds` + noise exclusion + feedparser parse. Config + `docs/rss_feeds.md`.

## Issue 32 — Significance + HN

| Cycle | Test | GREEN |
|---|---|---|
| 1 | `test_hn_corroboration_matching_topic_scores_higher` | `hn_corroboration` pure fn |
| 2 | `test_fetch_hn_front_page_parses_mocked_http` | `fetch_hn_front_page` |
| 3 | `test_fetch_hn_front_page_failure_returns_empty` | graceful degrade |
| 4 | `test_score_topics_uses_significance_not_novelty_axes` | `score_topics` rewrite |
| 5 | major launch / authority / HN boost tests | weighting formula |
| 6 | `test_scripter_stage_a.py` updated | orchestrator wiring |

## Issue 34 — Cleanup + docs

- `test_spike_82_rejected_and_not_in_pending` (live DB verify)
- `CLAUDE.md`, `plan.md` niche reconciled to ADR-0004

**Full refit suite:** `pytest tests/test_curated_feeds.py tests/test_topic_ingest_hn.py tests/test_scripter_significance.py tests/test_scripter_stage_a.py tests/test_topic_ingest*.py tests/assembler/test_ken_burns.py tests/test_spike_82_cleanup.py` → **55 passed**

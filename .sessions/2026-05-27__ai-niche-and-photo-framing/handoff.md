# Handoff — ai-niche-and-photo-framing
**Date:** 2026-05-27
**Project:** Media-Agent
**Working directory:** C:\Users\cryptix\Desktop\Work\Media-Agent-main

## What was accomplished this session

Diagnosed and planned the fix for two operator-rejected defects on the pending clip `spike-82`. No implementation code was written — this was a planning session (grill → ADR → PRD → issues).

- **Root-caused the "OnlyFans video".** Pending clip `spike-82` traces to **Topic #82** (a Verge culture story, *"Apple TV's hottest new shows explore different sides of OnlyFans"*). It passed because: `policy_gate/topic_filter.py` only filters religion/war; the topic scorer (`scripter/runner.py:18`) ranks on `0.4·novelty + 0.3·specificity + 0.3·tension` (it scored 6.9 — "weird" is what the formula rewards); and The Verge/VentureBeat feeds carry culture noise. Anthropic (the operator's own Opus 4.7 example) is absent from the feeds.
- **Root-caused the stretched photo.** `assembler/ken_burns.py:34-35` scales the photo aspect-correct, then pipes it into `zoompan` with `s=1080x1920`; zoompan ignores aspect ratio and re-stretches it (~3× vertical squash on a 16:9 image).
- **Grilled the design** (`/grill-with-docs`) and locked 5 decisions → see `docs/adr/0004`.
- **Sharpened the glossary** in `CONTEXT/CONTEXT.md`: redefined **Topic** (on-niche/off-niche), added **Significance** and **Trending corroboration**.
- **Wrote ADR-0004**, the **PRD**, and **5 ready-for-agent issues (30–34)**.

## Current state

- **Nothing is implemented yet.** All work product is docs/plans. Codebase behavior is unchanged.
- `output/pending/2026-05-28__slot_0900__it_s_in_the_air_apple_tv_1391.mp4` (`clip_id='spike-82'`, status `quality_pass`, publish_at `2026-05-28T01:00:00Z`) is **still present**. It cannot auto-publish (human-review is on; `daily_upload` pulls from `output/approved/`), but its removal is Ticket 34.
- Config feeds are still the old mixed list (incl. Verge main + VentureBeat, no Anthropic).
- Prior Pivot.7 work (Issues 22/26/27, commit `28b15fc`) is in place and untouched.

## Immediate next action

Grab **Ticket 31 — On-niche relevance gate at ingest** (`docs/issues/31-on-niche-relevance-gate-at-ingest.md`) or **Ticket 33 — Ken Burns photo-framing fix** (`docs/issues/33-ken-burns-photo-framing-fix.md`). Both are AFK, independent, no blockers, and each kills one of the two operator complaints. Suggest `/tdd` — both have mockable/pure seams and explicit "Tests Required" criteria. Ticket 33 is the lowest-risk quick win (render-only).

## Open decisions / blockers

- **None blocking.** All design decisions are locked in ADR-0004. Tickets 30/31/32/33 have no blockers; Ticket 34 is blocked by 31+32 (docs should describe shipped behavior).
- **Known trade-off to watch (not a blocker):** the narrowed niche + hard ingest gate yields fewer candidate topics. Mitigation is in Ticket 31 (widen recency 48h→96h on low yield, never relax the gate). Watch topic volume after the first curated run.

## Artifacts created this session

| Artifact | Path | Notes |
|---|---|---|
| ADR-0004 | `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md` | The 5 locked decisions + alternatives |
| PRD | `docs/prds/ai-niche-trending-selection-and-photo-framing.md` | Problem/solution/23 stories/modules/tests |
| Issue 30 | `docs/issues/30-curated-ai-focused-feeds.md` | Curated feeds (AFK, no blockers) |
| Issue 31 | `docs/issues/31-on-niche-relevance-gate-at-ingest.md` | Niche gate at ingest (AFK, no blockers) |
| Issue 32 | `docs/issues/32-significance-and-hn-trending-rerank.md` | Significance + HN rerank (AFK, no blockers) |
| Issue 33 | `docs/issues/33-ken-burns-photo-framing-fix.md` | Stretch fix + gradient bg (AFK, no blockers) |
| Issue 34 | `docs/issues/34-cleanup-spike82-and-doc-reconciliation.md` | Reject spike-82 + doc reconcile (blocked by 31,32) |
| Glossary updates | `CONTEXT/CONTEXT.md` | **Topic** sharpened; **Significance**, **Trending corroboration** added |

## Skills used this session

| Skill | File | Purpose |
|---|---|---|
| `/grill-with-docs` | `C:\Users\cryptix\.claude\skills\grill-with-docs\SKILL.md` | Locked niche scope, trending signal, feeds, photo framing, relevance gate; wrote ADR-0004 + CONTEXT.md |
| `/to-prd` | `C:\Users\cryptix\.claude\skills\to-prd\SKILL.md` | Wrote the PRD |
| `/to-issues` | `C:\Users\cryptix\.claude\skills\to-issues\SKILL.md` | Decomposed into Issues 30–34 |
| `/handoff` | `C:\Users\cryptix\.claude\skills\handoff\SKILL.md` | This document |

## Suggested skills for next session

- `/tdd` → `C:\Users\cryptix\.claude\skills\tdd\SKILL.md` — implement Tickets 30–34 test-first (all have mockable LLM/HTTP or pure seams)
- `/handoff` → `C:\Users\cryptix\.claude\skills\handoff\SKILL.md` — at session end

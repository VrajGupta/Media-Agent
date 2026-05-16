# Plan Archive — Historical Phases 0–7 (Archived 2026-05-16)

> This file archives the original `plan.md` as of Pivot.5. All phases described here are **COMPLETE** (Phases 0–7 live-verified, Pivots.0–5 shipped). The active plan is `.claude/plans/you-re-picking-up-the-expressive-abelson.md` (Pivot.6).

---

# Project Plan — YouTube Shorts Repost Automation

## Goal
Fully automated agent that searches YouTube by keyword, picks the most viral moments from long-form videos, reformats them into "brainrot-style" vertical Shorts (split-screen background gameplay + burned word-by-word subtitles), and uploads 2–6 clips/day to YouTube on an evenly-spaced schedule.

## Constraints & Decisions (locked)
- **Source:** third-party long-form videos, transformatively reformatted.
- **Selection signal:** virality/engagement (YouTube `mostReplayed` heatmap + transcript-driven LLM scoring).
- **Output platform:** YouTube Shorts only (TikTok/IG out of scope for v1).
- **Cadence:** configurable, default 4/day × 7 days = 28 clips/week, evenly spaced.
- **Stack:** Python 3.11+, runs on user's Windows PC.
- **Mode:** fully autonomous, no human approval step.
- **Operational mode (Path B — hybrid):**
  - **Weekly heavy run** (1× per week, ~1 hour, Windows Task Scheduler): discover → download → select → render. Produces N finished mp4s in `output/pending/` with assigned `publish_at` timestamps spread across the next 7 days.
  - **Daily upload run** (1× per day, ~5 min, Windows Task Scheduler): pops the day's clips from the queue and uploads each with `status.privacyStatus=private` + `status.publishAt=<assigned slot>`. Stays under the 10k-unit/day quota (4 uploads ≈ 6,400 units).
  - Quota-increase audit form is a **future task**; if/when approved, the daily uploader collapses into the weekly run.

## Hardware & Inputs (locked)
- **PC:** Windows, i9-11900H, 32 GB DDR4, 1 TB SSD, **RTX 3070 laptop GPU (8 GB VRAM)** — enough for Whisper `large-v3` int8 on CUDA and ffmpeg NVENC h264 encoding.
- **Keywords (v1):** Joe Rogan, stoicism, NBA highlights — all three rotated.
- **Background gameplay pool:** Subway Surfers, Minecraft parkour, GTA — one ~10 min file each.
- **Gameplay rotation rule:** consume sequentially across episodes — clip 1 uses Subway 0:00–0:30, clip 2 uses Minecraft 0:00–0:30, clip 3 uses GTA 0:00–0:30, clip 4 uses Subway 0:30–1:00, … wrap when all three pools are exhausted. Cursor persisted in state DB per gameplay file.

---

## Phase 0 — Environment & Credentials (Day 1) — COMPLETE
## Phase 1 — Discovery Agent (Day 2) — COMPLETE
## Phase 2 — Downloader (Day 2–3) — COMPLETE
## Phase 2.5 — Language Detection — COMPLETE
## Phase 3 / Pivot.0–2 — Clip Selection + Caption-First Transcripts — COMPLETE
## Phase 4 / Pivot.3 — Full-Screen Blurred-Bg Renderer + Karaoke Subs — COMPLETE
## Phase 4.5 — Policy Gate + Quality Screen — COMPLETE
## Phase 5 — Uploader — COMPLETE (live-verified)
## Phase 6 — Orchestrator (weekly_run + daily_upload + slot_planner) — COMPLETE
## Phase 7 — Hardening (run_lock, tenacity, real retention, runs.md) — COMPLETE (457 tests, 2026-05-09)
## Pivot.4 — Banlist tune — COMPLETE (15% rejection rate, within gate)
## Pivot.5 — Live movie-clip end-to-end — COMPLETE (2026-05-12, 10 clips slotted, 5 uploaded to test channel)

> Full detail for each phase/pivot is preserved in `progress.md`.

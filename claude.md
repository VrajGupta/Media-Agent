# Project Context — Media Agent

## What this project is
A fire-and-forget Python agent that automates an **AI-generated "weird/unsettling facts" YouTube Shorts channel** (Zack D. Films–style). A weekly run drives:
1. **Script generation** — local Ollama (`qwen2.5:3b-instruct`) emits a `{title, narration, shots[]}` JSON script from a topic-seed pool (weird biology, deep sea, weird history, unsettling animal facts, rare natural phenomena — **not phobias**).
2. **Video generation** — Kling AI text-to-video (provider-abstracted; Pika 2.0 / MiniMax-Hailuo are drop-in swaps) renders 4–6 stitched 5–10 s shots in native 1080×1920.
3. **Narration** — Edge TTS (`en-US-GuyNeural`, free) produces the voiceover; Whisper forced-align provides word timings.
4. **Assembly** — ffmpeg concat → mux narration → music-bed duck/mix → ASS line-at-a-time subtitle burn → NVENC encode → 2-pass LUFS normalize.
5. **Upload** — same backbone as before: slot-planner spreads `publish_at_utc` over 7 days; daily Task Scheduler run uploads via YouTube Data API v3 with `publishAt` + AI-disclosure flag.

**Cadence:** 2–6 clips/day to a single channel on a fixed cadence.

**Content pivot history:** v1 was "podcast/highlight + Subway gameplay split-screen" (Phases 0–4). Pivot.0–5 (2026-05-04 → 2026-05-12) swapped to "movie clips" (single full-screen + blurred-bg + karaoke subs). **Pivot.6 (2026-05-16, current)** drops sourced video entirely in favour of AI-generated content — the copyright-strike risk on first-party studio content was too high, and AI generation differentiates the channel. The canonical Pivot.6 plan is `.claude/plans/you-re-picking-up-the-expressive-abelson.md`.

## Scope (Pivot.6)
- **Source:** AI-generated visuals + AI-synthesized narration. No third-party video ingestion.
- **Output platform:** YouTube Shorts only. TikTok and Instagram are explicitly out of scope.
- **AI disclosure:** every upload carries the "altered/synthetic content" attestation (YouTube creator policy, March 2024+). Description footer notes "Made with AI."
- **Mode:** fully autonomous in steady state. `human_review=true` is locked on for the first 2 weeks (filesystem-based; user drags approved clips from `output/pending/` → `output/approved/`).
- **Operational model (Path B — hybrid, unchanged from v1):**
  - **Weekly heavy run** — `gen_run.py` (replaces `weekly_run.py`) triggered by Windows Task Scheduler once a week. Scripts → generates → narrates → assembles → screens → slots → retains, assigning each clip a `publish_at` timestamp spread across the next 7 days.
  - **Daily upload run** — `daily_upload.py` triggered by Windows Task Scheduler once a day, ~5 min. Uploads that day's clips to YouTube with `privacyStatus=private` + `publishAt=<slot>` + altered-content flag, letting YouTube auto-publish at the slot.
  - This split exists because YouTube's default API quota allows only ~6 inserts/day. Quota-increase audit is a future task; once approved, the daily run collapses into the weekly run.
- **Development & runtime:** the user's Windows laptop (single machine). Code is developed and run on the same PC; no separate dev/runtime environments.

## Stack
Python 3.11+ · ffmpeg+NVENC · **Kling AI** (paid; provider-abstracted) · **Edge TTS** (free) · faster-whisper (CUDA, forced-alignment role only post-Pivot.6) · YouTube Data API v3 · Ollama (`qwen2.5:3b-instruct`, local — now script writer, not clip ranker) · Windows Task Scheduler · SQLite. See `skills.md` for the full rationale. **Cost: Kling API only (target ≤ $150/mo at 28 clips/week); everything else is free.**

## Architecture in one diagram (Pivot.6)
```
[Windows Task Scheduler — weekly]
   └─ gen_run.py:
        topic seed pool → scripter (Ollama → {title, narration, shots[], style} JSON, persisted to scripts)
                → policy_gate (banlist / profanity / NSFW / hook-sanity / topic_filter on narration + title)
                → ai_gen (Kling text-to-video × 4–6 shots, async max_concurrent=2, persisted to generation_jobs)
                → narration (Edge TTS → mp3; Whisper forced-align → per-word timings)
                → assembler (ffmpeg concat → mux narration → music duck/mix → ASS line-centered burn → NVENC 1080×1920 → 2-pass −14 LUFS)
                  → output/pending/__unscheduled__{clip_id}__{slug}.mp4
                → quality_screen (duration + loudness + pHash dedup; density+confidence skipped for TTS-clean audio)
                → slot_planner (TZ-aware, publish_at_utc) → renames to {date}__slot_{HHMM}__{slug}.mp4
                → retention (cleanup + VACUUM; new TTLs for ai_gen_shots + narration)
[user, ad-hoc]  drag from output/pending/ → output/approved/  (only while human_review=true)

[Windows Task Scheduler — daily]
   └─ daily_upload.py:
        clips with publish_at_utc ∈ today and content_kind='ai_generated'
                → policy_gate (re-check on script.narration)
                → uploader (videos.insert + publishAt + altered_content flag, orphan-marker fence, --dry-run aware) → YouTube
                                  ↑
                          state.db (SQLite — clips.content_kind branches uploader templating)
                                  ↑
                  observability (loguru → logs/agent.log + logs/alerts.md) ← every stage
```

## Operational invariants preserved across pivots
- New modules introduced over time: `lang_detect/`, `policy_gate/`, `quality_screen/`, `quota_ledger/`, `retention/`, `observability/`, `slot_planner/` (Phase 4.5–7), **then Pivot.6 added** `scripter/`, `ai_gen/`, `narration/`, `assembler/` (replacing `editor/`) and **retired** `discovery/`, `downloader/`, `lang_detect/`, `selector/`.
- TZ semantics: canonical `timezone` from config, `zoneinfo` for DST, `publish_at_utc` stored UTC, missed-slot recovery batches stale → next future slot, future-too-near pad of 20 min.
- Quota ledger meters every billed call across providers (`youtube` for `videos.insert`, `kling` for per-shot cost cents). Weekly run aborts before exceeding the configured ceilings.
- Retention TTLs (Pivot.6): `ai_gen_shots/` 7 d post-render, `narration/` 14 d, `scripts` rows 90 d, `dup_hashes` / `quota_usage` 90 d, queue 7 d post-upload, monthly VACUUM. `raw_video` / `transcripts` TTLs retired (no longer produced).
- Observability: filesystem-based — `loguru` → `logs/agent.log`, append-only `logs/alerts.md` for run failure / quota near-cap / upload reject / missed-slot recovery / weekly finished / kling spend near cap.
- `--dry-run` mode on uploader and `gen_run.py`; `bootstrap --check` verifies KLING_API_KEY + edge-tts + Ollama + ffmpeg+NVENC + Whisper.
- Run lock (`data/.weekly_run.lock`) + tenacity retry on transient HTTP at every billed boundary (Phase 7).
Each stage is independent and idempotent, communicating via the SQLite state store. See `agents.md` for module-by-module detail.

## Where things live
- `.claude/plans/you-re-picking-up-the-expressive-abelson.md` — **canonical Pivot.6 plan** (authoritative).
- `plan.md` — superseded by the plan above; see `plan.archive.md` for historical phases.
- `agents.md` — module responsibilities and data flow (updated for Pivot.6).
- `skills.md` — libraries/APIs and the reasoning behind each (updated for Pivot.6).
- `progress.md` — running checklist; **update after every completed task.**
- `src/` — code. Active Pivot.6 modules: `scripter/`, `ai_gen/`, `narration/`, `assembler/`, `policy_gate/`, `quality_screen/`, `slot_planner/`, `uploader/`, `retention/`, `observability/`, `quota_ledger/`, `state/`, `config_loader/`, `bootstrap.py`, `gen_run.py`, `daily_upload.py`.
- `config.yaml` — runtime config (committed). `.env` — secrets (`KLING_API_KEY` + YouTube OAuth env; gitignored). `data/client_secret.json` + `data/oauth_token.json` — YouTube OAuth (gitignored).

## Locked decisions (Pivot.6)
- **Content kind:** `ai_generated`. No source-video ingestion. `clips.content_kind='ai_generated'` gates uploader templating.
- **Vertical layout:** native 9:16 from Kling — no blurred-bg filtergraph needed. Shots are already 1080×1920.
- **Subtitles:** centered line-at-a-time ASS burn. Position `\pos(540, 1500)`. Word timings from Whisper forced-align on TTS mp3.
- **Narration:** Edge TTS `en-US-GuyNeural`, rate `-8%`, pitch `-2Hz`. Whisper `large-v3` int8_float16 on CUDA for alignment.
- **Generator:** Kling AI, 5 s/shot, 4–6 shots/clip → ~30 s clip. Style suffix: "3D animated, Pixar-shaded surface, surreal cinematic lighting, vertical 9:16, photoreal textures with stylized characters, dark moody atmosphere".
- **Script writer:** Ollama `qwen2.5:3b-instruct` JSON-mode. Topic pool: weird_biology, deep_sea, weird_history, unsettling_animal_facts, rare_natural_phenomena. **Not phobias.**
- **Default cadence:** 4 clips/day × 7 days = 28 clips/week. Configurable via `clips_per_day` and `days_per_run`.
- **`human_review = true` for first 2 weeks.** Mechanism is filesystem-based:
  - Assembled clips → `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4`
  - User reviews in Explorer, drags approved files → `output/approved/`
  - Daily uploader pulls from `output/approved/` while review is on; from `output/pending/` directly after week 2.
- **Canonical timezone:** `Asia/Singapore`.
- **No Discord, no webhooks.** Failures and recoveries append to `logs/alerts.md`.
- **AI disclosure:** `compliance.ai_disclosure=true` in config. Upload description footer: "Made with AI. For entertainment / educational use." YouTube `altered_content` flag set on `videos.insert` where the v3 API exposes it; manual Studio attestation as fallback if the API field is not yet exposed.

## Hardware (locked)
- Windows PC: i9-11900H, 32 GB DDR4, 1 TB SSD, RTX 3070 laptop GPU (8 GB VRAM).
- Whisper: `large-v3` int8_float16 on CUDA (forced-alignment role, post-Pivot.6). Render: `h264_nvenc`.

## Content generation (Pivot.6)
- **Topic seeds:** rotated round-robin from `scripter.topic_pool` in config.
- **Kling shots:** submitted concurrently (max 2 in-flight). Cost tracked per shot in `quota_usage(provider='kling', units=cost_cents)`. Daily spend ceiling enforced (`ai_gen.daily_spend_cents_ceiling`).
- **Provider abstraction:** `src/ai_gen/base.py` defines a `Provider` ABC. Swap to Pika 2.0 or MiniMax by adding a concrete impl — no downstream pipeline changes.

## Working agreement
- Plan files are authoritative; touch them when scope changes. The canonical plan is `.claude/plans/you-re-picking-up-the-expressive-abelson.md`.
- Build sub-pivot by sub-pivot per that plan. Don't skip sub-pivots.
- Update `progress.md` immediately when a task completes — don't batch.
- No code written until the user confirms the plan.

## Risk acknowledgement (Pivot.6)
AI-generated content eliminates the movie-clip copyright-strike risk. Residual risks:
- **Kling API cost overrun.** Mitigated by `per_clip_cost_cents_max` and `daily_spend_cents_ceiling` enforced in `quota_ledger`. Agent aborts if projection exceeds ceiling.
- **Generator aesthetic drift.** The Pivot.6.1 spike validates 10 sample shots before committing. Provider abstraction allows a half-day swap if output quality is insufficient.
- **Edge TTS throttling.** Microsoft rate-limits the free endpoint unannounced. Tenacity retry + `pyttsx3` offline fallback as degraded mode.
- **YouTube AI-disclosure API gaps.** YouTube's `altered_content` UI toggle (required March 2024+) may not be fully exposed in the v3 insert API. Research at Pivot.6.5; manual Studio attestation as fallback.

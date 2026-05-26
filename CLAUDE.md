# Project Context — Media Agent

## What this project is
A fire-and-forget Python agent that automates an **AI-generated Tech/AI news YouTube Shorts channel** (MKBHD-style topic angle, Zack D. Films delivery format). Weekly run drives:
1. **Topic ingest** — pull last-48h items from mixed consumer + research tech/AI RSS feeds; dedup by URL + title-similarity; queue fresh topics in DB.
2. **Script generation** — local Ollama (`qwen2.5:3b-instruct`) emits a `{title, narration, shots[], style_notes}` JSON script from a queued topic. ~40-word narration, hook in first 5 words, 4 shots, ends on a teaser.
3. **Video generation** — OpenRouter Kling 3.0 std (`kwaivgi/kling-v3.0-std`) text-to-video (provider-abstracted; Seedance / Pika / MiniMax-Hailuo are drop-in swaps) renders 4 stitched ~4 s shots at **720×1280**; the assembler **Shot-normalizes** to 1080×1920.
4. **Narration** — Edge TTS (`en-US-GuyNeural`, rate `+10%`, pitch `0Hz`, free) produces the voiceover with natural conversational pacing; Whisper forced-align provides word timings.
5. **Assembly** — ffmpeg concat → mux narration → music-bed duck/mix → ASS line-at-a-time subtitle burn → NVENC encode → 2-pass LUFS normalize.
6. **Upload** — same backbone as before: slot-planner spreads `publish_at_utc` over 7 days; daily Task Scheduler run uploads via YouTube Data API v3 with `publishAt` + AI-disclosure flag.

**Cadence (current budget):** ~1 clip/day, $5/week budget = 2–3 clips/week practical. Scales to 4 clips/day if budget increases.

**Content pivot history:** v1 was "podcast/highlight + Subway gameplay split-screen" (Phases 0–4). Pivot.0–5 (2026-05-04 → 2026-05-12) swapped to "movie clips" (single full-screen + blurred-bg + karaoke subs). **Pivot.6 (2026-05-16, current)** drops sourced video entirely in favour of AI-generated content. Niche corrected on 2026-05-17 from "weird/unsettling facts" to "Tech/AI news" after strategy interview. The active plan is in `plan.md` — full slice breakdown inlined there.

## Scope (Pivot.6)
- **Source:** AI-generated visuals + AI-synthesized narration + RSS-fed tech/AI news topics. No third-party video ingestion.
- **Output platform:** YouTube Shorts only. TikTok and Instagram are explicitly out of scope.
- **AI disclosure:** every upload carries the "altered/synthetic content" attestation (YouTube creator policy, March 2024+). Description footer notes "Made with AI."
- **Mode:** fully autonomous in steady state. `human_review=true` is locked on for the first 2 weeks (filesystem-based; user drags approved clips from `output/pending/` → `output/approved/`).
- **Operational model (Path B — hybrid, unchanged from v1):**
  - **Weekly heavy run** — `gen_run.py` (replaces `weekly_run.py`) triggered by Windows Task Scheduler once a week. Topics → scripts → generates → narrates → assembles → screens → slots → retains, assigning each clip a `publish_at` timestamp spread across the next 7 days.
  - **Daily upload run** — `daily_upload.py` triggered by Windows Task Scheduler once a day, ~5 min. Uploads that day's clips to YouTube with `privacyStatus=private` + `publishAt=<slot>` + `containsSyntheticMedia` disclosure flag, letting YouTube auto-publish at the slot.
  - This split exists because YouTube's default API quota allows only ~6 inserts/day. Quota-increase audit is a future task; once approved, the daily run collapses into the weekly run.
- **Development & runtime:** the user's Windows laptop (single machine). Code is developed and run on the same PC; no separate dev/runtime environments.

## Stack
Python 3.11+ · ffmpeg+NVENC · **OpenRouter Kling 3.0 std** (paid; provider-abstracted via `OPENROUTER_API_KEY`) · **Edge TTS** (free) · faster-whisper (CUDA, forced-alignment role only post-Pivot.6) · YouTube Data API v3 · Ollama (`qwen2.5:3b-instruct`, local — script writer) · RSS via `feedparser` (Pivot.6 — topic source) · Windows Task Scheduler · SQLite. See `skills.md` for the full rationale. **Cost: OpenRouter Kling only (~$5/week budget → 2–3 clips/week); everything else is free.**

## Architecture in one diagram (Pivot.6)
```
[Windows Task Scheduler — weekly]
   └─ gen_run.py:
        RSS feeds → topic_ingest (last 48h, dedup by URL + title-similarity, persisted to topics)
                → scripter (Ollama → {title, narration ≈40 words, shots[4], style_notes} JSON, persisted to scripts)
                → policy_gate (banlist / profanity / NSFW / hook-sanity / topic_filter on narration + title)
                → ai_gen (OpenRouter Kling 3.0 std × 4 shots, ThreadPool max_workers=2, persisted to generation_jobs)
                → narration (Edge TTS at +10% rate / 0Hz pitch → mp3; Whisper forced-align → per-word timings)
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
                → uploader (videos.insert + publishAt + containsSyntheticMedia flag, orphan-marker fence, --dry-run aware) → YouTube
                                  ↑
                          state.db (SQLite — clips.content_kind branches uploader templating)
                                  ↑
                  observability (loguru → logs/agent.log + logs/alerts.md) ← every stage
```

## Operational invariants preserved across pivots
- New modules introduced over time: `lang_detect/`, `policy_gate/`, `quality_screen/`, `quota_ledger/`, `retention/`, `observability/`, `slot_planner/` (Phase 4.5–7), **then Pivot.6 added** `topic_ingest/`, `scripter/`, `ai_gen/`, `narration/`, `assembler/` (replacing `editor/`) and **retired** `discovery/`, `downloader/`, `lang_detect/`, `selector/`.
- TZ semantics: canonical `timezone` from config, `zoneinfo` for DST, `publish_at_utc` stored UTC, missed-slot recovery batches stale → next future slot, future-too-near pad of 20 min.
- Quota ledger meters every billed call across providers (`youtube` for `videos.insert`, `openrouter` for per-shot Kling cost cents). Weekly run aborts before exceeding the configured ceilings.
- Retention TTLs (Pivot.6): `ai_gen_shots/` 7 d post-render, `narration/` 14 d, `scripts` rows 90 d, `topics` rows 30 d, `dup_hashes` / `quota_usage` 90 d, queue 7 d post-upload, monthly VACUUM. `raw_video` / `transcripts` TTLs retired (no longer produced).
- Observability: filesystem-based — `loguru` → `logs/agent.log`, append-only `logs/alerts.md` for run failure / quota near-cap / upload reject / missed-slot recovery / weekly finished / OpenRouter spend near cap.
- `--dry-run` mode on uploader and `gen_run.py`; `bootstrap --check` verifies `OPENROUTER_API_KEY` + edge-tts + Ollama + ffmpeg+NVENC + Whisper.
- Run lock (`data/.weekly_run.lock`) + tenacity retry on transient HTTP at every billed boundary (Phase 7).
Each stage is independent and idempotent, communicating via the SQLite state store. See `agents.md` for module-by-module detail.

## Where things live
- `plan.md` — **active Pivot.6 plan with full slice breakdown** (authoritative).
- `plan.archive.md` — pre-Pivot.6 history (Phases 0–7 + Pivots.0–5, all complete).
- `agents.md` — module responsibilities and data flow (updated for Pivot.6 Tech/AI niche).
- `skills.md` — libraries/APIs and the reasoning behind each (updated for Pivot.6 Tech/AI niche).
- `progress.md` — running checklist; **update after every completed task.**
- `src/` — code. Active Pivot.6 modules: `topic_ingest/`, `scripter/`, `ai_gen/`, `narration/`, `assembler/`, `policy_gate/`, `quality_screen/`, `slot_planner/`, `uploader/`, `retention/`, `observability/`, `quota_ledger/`, `state/`, `config_loader/`, `bootstrap.py`, `gen_run.py`, `daily_upload.py`.
- `config.yaml` — runtime config (committed). `.env` — secrets (`OPENROUTER_API_KEY` + YouTube OAuth env; gitignored). `data/client_secret.json` + `data/oauth_token.json` — YouTube OAuth (gitignored).

## Locked decisions (Pivot.6)
- **Niche:** Tech/AI news (MKBHD-style topic angle, Zack D. Films delivery format). Topics sourced from live RSS feeds — no static `topic_pool`. **Not:** weird/unsettling facts, not phobias, not generic explainers.
- **Content kind:** `ai_generated`. No source-video ingestion. `clips.content_kind='ai_generated'` gates uploader templating.
- **Vertical layout:** native 9:16. Kling std emits **720×1280 @ 24fps**; Ken Burns **Real-image shots** render at **1080×1920 @ 30fps**. The assembler applies **Shot normalization** (ADR-0002) to conform every **Shot** to `output_resolution` + `output_fps` before **Stitching** — no blurred-bg filtergraph needed.
- **Subtitles:** centered line-at-a-time ASS burn. Position `\pos(540, 1500)`. Word timings from Whisper forced-align on TTS mp3. ≤28 chars/line, 100 ms fade-in.
- **Narration:** Edge TTS `en-US-GuyNeural`, rate `+10%`, pitch `0Hz`. Natural conversational pacing — not slow/calm, not crammed. Whisper `large-v3` int8_float16 on CUDA for alignment.
- **Generator:** OpenRouter Kling 3.0 std (`kwaivgi/kling-v3.0-std`) via `src/ai_gen/openrouter_kling.py`. Std tier emits **720×1280 @ 24fps** (~4 s/shot, 4 shots/clip → ~16 s clip). Style suffix: `"clean editorial product photography, soft studio lighting, neutral backgrounds, minimalist composition, sharp focus, vertical 9:16, premium tech magazine look"`.
- **Script writer:** Ollama `qwen2.5:3b-instruct` JSON-mode. Consumes a topic (title + summary) from `topics` table → produces `{title, narration ≈40 words, shots[4], style_notes}`. Rubric: hook in first 5 words, 1–2 punchy stats, ends on a teaser.
- **Topic source:** Live RSS pull from mixed consumer + research tech/AI feeds, last 48 h window. Dedup by URL hash + normalized-title similarity (Levenshtein / word-set overlap). Feed URLs configured by user at Slice 7.
- **Default cadence (current budget):** ~1 clip/day, $5/week budget = 2–3 clips/week. Configurable via `clips_per_day` and `days_per_run`.
- **`human_review = true` for first 2 weeks.** Mechanism is filesystem-based:
  - Assembled clips → `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4`
  - User reviews in Explorer, drags approved files → `output/approved/`
  - Daily uploader pulls from `output/approved/` while review is on; from `output/pending/` directly after week 2.
- **Hybrid real-image sourcing (Pivot.7, ADR-0003):** autonomous path uses **Licensed sources** only (`logo`, `wikimedia`, `openverse`; `web_fallback_enabled: false`). Licensed miss → **Real-image shot** degrades to **AI-video shot** before Kling billing. Web fallback remains for manual spike/dev only.
- **Canonical timezone:** `Asia/Singapore`.
- **No Discord, no webhooks.** Failures and recoveries append to `logs/alerts.md`.
- **AI disclosure:** `compliance.ai_disclosure=true` in config. Upload description footer: "Made with AI. For entertainment / educational use." YouTube `status.containsSyntheticMedia=true` set on `videos.insert` for all `content_kind='ai_generated'` clips (field confirmed live in v3 since 2024-10-30).

## Hardware (locked)
- Windows PC: i9-11900H, 32 GB DDR4, 1 TB SSD, RTX 3070 laptop GPU (8 GB VRAM).
- Whisper: `large-v3` int8_float16 on CUDA (forced-alignment role, post-Pivot.6). Render: `h264_nvenc`.

## Content generation (Pivot.6)
- **Topic flow:** RSS feeds → `topic_ingest` (dedup) → `topics` table → `scripter` consumes one topic round-robin → script generated → script_id linked to clip stub.
- **Kling shots:** submitted concurrently via `ThreadPoolExecutor(max_workers=2)`. Cost tracked per shot in `quota_usage(provider='openrouter', units=cost_cents)`. Daily spend ceiling enforced (`ai_gen.daily_spend_cents_ceiling`).
- **Provider abstraction:** `src/ai_gen/base.py` defines a `Provider` ABC. Swap to Pika 2.0, MiniMax, or Seedance by adding a concrete impl — no downstream pipeline changes.

## Working agreement
- `plan.md` is authoritative for the Pivot.6 slice breakdown; touch it when scope changes.
- Build slice by slice per that plan. Don't skip slices.
- Update `progress.md` immediately when a task completes — don't batch.
- No code written until the user confirms the plan.

## Risk acknowledgement (Pivot.6)
AI-generated content eliminates the movie-clip copyright-strike risk. Residual risks:
- **OpenRouter Kling cost overrun.** Mitigated by `per_clip_cost_cents_max` and `daily_spend_cents_ceiling` enforced in `quota_ledger`. Agent aborts if projection exceeds ceiling.
- **Generator aesthetic drift.** Slice 2 spike validates 10 sample shots before committing. Provider abstraction allows a half-day swap to Seedance / Pika / MiniMax if output quality is insufficient.
- **Edge TTS throttling.** Microsoft rate-limits the free endpoint unannounced. Tenacity retry + `pyttsx3` offline fallback as degraded mode.
- **YouTube AI-disclosure API gaps.** Resolved in Slice 9: `status.containsSyntheticMedia` (boolean) is confirmed live in v3 since 2024-10-30. Set on all `content_kind='ai_generated'` uploads. Spot-check Studio UI for first ~5 uploads to verify.
- **RSS feed quality.** Bad feed selections → boring or off-niche topics. Mitigated by user-curated feed list (delivered at Slice 7) and the policy_gate's topic_filter check.

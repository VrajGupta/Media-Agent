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

## Phase 0 — Environment & Credentials (Day 1)
- Set up Python venv, install dependencies, verify ffmpeg on PATH.
- Create Google Cloud project; enable YouTube Data API v3.
- Create OAuth 2.0 Desktop client; complete first OAuth flow; cache refresh token.
- Get Anthropic API key (for clip selection LLM).
- Acquire 1–3 royalty-free background gameplay clips (10+ min each, 1080×1920).
- Install Ollama on the PC; `ollama pull qwen2.5:3b-instruct`.
- Project skeleton: `src/`, `data/`, `data/gameplay/`, `data/transcripts/`, `output/pending/`, `output/approved/`, `output/rejected/`, `output/dry_run/`, `logs/`, `scripts/`, `config.yaml`, `.env`.

## Phase 1 — Discovery Agent (Day 2)
- `search_youtube(keyword, max_results)` via Data API v3 `search.list`.
- Filter at API level: duration > 5 min (rules out existing Shorts), `relevanceLanguage=en`, recency window.
- *Note: `search.list` cannot guarantee English **audio**. True language check happens post-download via Whisper in Phase 3.*
- Pull `videos.list` for each result → views, likes, comments, duration, channel.
- Concrete virality formula (locked):
  ```
  recency_factor   = views / max(age_hours, 24)
  engagement_rate  = (likes + 4*comments) / max(views, 1)
  niche_normalized = views / max(rolling_30d_median_views_for_niche, 1)
  virality_score   = log10(recency_factor + 1)
                   * (0.5 + min(engagement_rate * 50, 1.5))
                   * log10(niche_normalized + 1)
  ```
  Threshold to enter selection: `virality_score ≥ 1.0`.
- Every billed call records to `quota_usage` via `quota_ledger`. Discovery aborts if today's projected total > 8,000 units.
- Persist candidates to SQLite (`videos` table) with a `status` column.
- **Acceptance:** ≥30 candidates per keyword; quota ledger ≤ 1,800 units/run.

## Phase 2 — Downloader (Day 2–3)
- `yt-dlp` wrapper: download best 1080p mp4 + auto-subs (if available).
- Cache by video ID in `data/raw/`.
- Skip re-downloads; mark status=`downloaded`.

## Phase 3 — Clip Selection (Day 3–5)
- **Language detection first:** transcribe first 60 s; if Whisper detected language ≠ `en` w/ confidence ≥ 0.7, mark `rejected_language` and skip.
- Pull `mostReplayed` heatmap via undocumented endpoint. **Fallback validation:** track `heatmap_hit_rate` per run; if < 70%, run continues but tags clips `selection_method='transcript_only'` and emits Discord warning. First 2 weeks: manual spot-check of 5 transcript-only vs 5 heatmap-aided clips per week to validate quality gap ≤ 1.0/5.
- Transcribe full video with `faster-whisper` `large-v3` int8_float16 on CUDA. Cache transcripts under `data/transcripts/`.
- Slice transcript into 30–60 s windows aligned with sentence boundaries.
- Send window candidates + heatmap peaks (when present) to local Ollama (`qwen2.5:3b-instruct`, JSON-mode) with a fixed rubric prefix (kv-cache reused) → returns top N `(start, end, hook, suggested_title)`.
- Persist clips to `clips` table.
- **Acceptance:** first 10 clips manually rated, ≥7 "watchable hook"; transcript-only path ≥6/10.

## Phase 4 — Vertical Reformat & Subtitles (Day 5–7)
- Cut source clip with ffmpeg (`-ss`/`-to`, copy-codec when possible, re-encode otherwise).
- Build 1080×1920 canvas:
  - Top half (0–960): source clip, **center-cropped** to 1080×960 (subject tracking deferred to Phase 8).
  - Bottom half (960–1920): background gameplay, sequentially seeked from the rotation pool (see gameplay rotation rule).
- Re-encode with `h264_nvenc` (RTX 3070) for ~5× faster renders than libx264.
- **Acceptance:** valid 1080×1920 H.264, ≤60 s, audio at -14 ±0.5 LUFS, subtitle drift ≤50 ms.

## Phase 4.5 — Policy Gate + Quality Screen (Day 7)
- `policy_gate` (runs after select, again before upload):
  - Banlist substring match on transcript + suggested title (config-driven).
  - Profanity scoring (`better-profanity` baseline; LLM fallback if cost allows).
  - NSFW text classifier on transcript (zero-shot via Ollama).
  - Hook-vs-content sanity check: Ollama rates whether `suggested_title` accurately summarizes the clip; reject if score < 3/5.
- `quality_screen`:
  - `speech_density ≥ 1.5` words/sec.
  - mean Whisper word-confidence ≥ 0.6.
  - Perceptual hash (pHash on 5 evenly-spaced frames) + audio fingerprint compared against `dup_hashes` (last 90 days). Reject if either matches.
  - Final clip duration ∈ [25, 65] s.
- All rejections write `clips.rejection_reason`. Rejected clips are not rendered or uploaded.
- **Acceptance:** all banned-topic test inputs caught; legitimate test set passes; zero false-positive duplicate matches on 20 hand-picked distinct clips.
- Burn karaoke-style word-by-word subtitles via ASS subtitle file generated from Whisper word timestamps.
- Loudness normalize audio to -14 LUFS (YouTube target).
- Output filename: `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4` (date in canonical TZ Asia/Singapore; slug from suggested title, ≤80 chars). Self-describing for manual review.

## Phase 5 — Uploader (Day 7–8)
- `youtube.videos.insert` with resumable upload.
- `status.privacyStatus=private` + `status.publishAt=<ISO UTC>` so YouTube auto-publishes at the scheduled slot.
- **`--dry-run` mode:** writes the would-be insert body to `output/dry_run/{clip_id}.json`, makes no API call. Used for offline lint and CI-style smoke tests.
- Title from LLM hook; description templated; tags from keyword + niche; `categoryId=24`; `madeForKids=false`; `selfDeclaredMadeForKids=false`; `#Shorts` in title/description.
- **Future-too-near rule:** if `publish_at` < `now + 20 min`, pad to `now + 20 min` to avoid YouTube rejection.
- Mark clip `uploaded`, store returned `videoId` and confirmed `publish_at`.
- Quota ledger pre-flight: abort if next call would push today's usage > 9,000 units.
- **Acceptance:** `--dry-run` produces a valid insert body offline; one real upload to test channel publishes at exactly the requested `publishAt` in canonical TZ.

## Phase 6 — Orchestrator (Day 8–9)
- **No long-running daemon.** Entrypoints, all invoked by Windows Task Scheduler or manually:
  - `python -m src.weekly_run` — full pipeline: discover → download → lang_detect → select → policy_gate → render → quality_screen → slot_planner.
  - `python -m src.daily_upload` — selects clips whose `publish_at_utc` falls within today's local-TZ window, re-runs `policy_gate`, uploads with the clip's `publishAt`.
  - `python -m src.bootstrap --check` — env health check (ffmpeg/NVENC/CUDA/Whisper/YT auth/Anthropic auth).
  - `python -m src.bootstrap` — single-clip end-to-end smoke test.
- **Time semantics:** canonical timezone is config (`timezone: Asia/Singapore`). `publish_at_utc` stored UTC; converted via `zoneinfo`. Slot planner spreads N×D clips across `upload_slots: ["09:00","13:00","17:00","21:00"]` over `days_per_run`.
- **Missed-slot recovery:** if `daily_upload` finds clips with `publish_at_utc` already in the past (PC was off), it pads them to `now + 20 min` rather than asking YouTube to publish in the past. Logged as `recovered_slot` and Discord-alerted.
- All single-process, SQLite as state. Graceful resume on partial failure.
- **Acceptance:** weekly_run produces 28 ready clips; daily_upload publishes 4/day for 7 days with no missed slots when PC online; missed-slot recovery exercised.

## Phase 7 — Hardening (Day 9–10)
- Structured logging (`loguru`) → `logs/agent.log`, daily rotation, 30-day retention.
- Retry with backoff (`tenacity`) on API/network errors; quarantine on repeated failure.
- **Alerts file** (`logs/alerts.md`): weekly run finished, run failure, quota > 80% used, upload rejected, missed-slot recovery. Markdown table; user reads on demand.
- **Retention/cleanup module** at end of `weekly_run`:
  - `data/raw/*.mp4` → delete 14 days post-download or after all derived clips uploaded, whichever later.
  - `data/transcripts/*.json` → 90-day TTL.
  - `output/pending/*.mp4` → delete 7 days after `uploaded` confirmed.
  - `dup_hashes` rows older than 90 days pruned.
  - SQLite `VACUUM` monthly.
- Per-run summary appended to `logs/runs.md`.
- Config-driven (`config.yaml`): keywords, `clips_per_day`, `days_per_run`, `upload_slots`, `timezone`, `human_review`, `banlist`, `discord_webhook`, model sizes, paths.
- **Windows Task Scheduler** entries committed as `.xml` exports under `scripts/`:
  - `weekly_run.xml` — Sundays 02:00 local TZ.
  - `daily_upload.xml` — daily 09:00 local TZ.
- Document quota-increase audit form steps in `README.md`.
- **Acceptance:** logs rotate; Discord alerts fire on synthetic triggers; cleanup deletes correct files; double-running `weekly_run` is a no-op.

## Phase 8 — Stretch (post-v1)
- Thumbnail auto-generation.
- A/B title testing.
- TikTok / Reels via Playwright once YouTube is stable.
- Web dashboard for queue inspection.

## Risks
- **Copyright strikes / channel termination.** Mitigations: short clips, transformative format, attribution in description, niche selection. Accept residual risk.
- **mostReplayed unavailable for many videos.** Fallback: pure transcript+LLM scoring.
- **YouTube quota.** 6 uploads/day is the hard ceiling on default quota; request increase if needed.
- **Whisper speed on CPU-only PC.** Drop to `small.en` + 8-bit; pre-batch overnight.

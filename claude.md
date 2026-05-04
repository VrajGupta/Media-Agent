# Project Context — Media Agent

## What this project is
A fire-and-forget Python agent that automates a "movie clip Shorts" YouTube channel. It searches YouTube by keyword for movie-clip reuploader videos, finds the most viral 30–60s moments, reformats them as 1080×1920 Shorts (full-screen original frame on a blurred background extension + word-by-word burned subtitles), and uploads 2–6/day to a single YouTube channel on a fixed cadence.

**Content pivot 2026-05-04:** the channel was previously a "podcast/highlight + Subway gameplay split-screen" format. The pivot to movie clips drops the split-screen entirely, drops the gameplay rotation system, adds a YouTube-CC-first transcript path, and acknowledges meaningfully higher copyright-strike risk. See `progress.md` Pivot.0–Pivot.5 for the rewrite checklist and the plan archive in `.claude/plans/` for the full pivot rationale.

## Scope (v1)
- **Source:** third-party long-form videos, transformatively reformatted.
- **Output platform:** YouTube Shorts only. TikTok and Instagram are explicitly out of scope.
- **Mode:** fully autonomous in steady state. `human_review=true` is locked on for the first 2 weeks (filesystem-based; user drags approved clips from `output/pending/` → `output/approved/`).
- **Operational model (Path B — hybrid):**
  - **Weekly heavy run** — `weekly_run.py` triggered by Windows Task Scheduler once a week, ~1h. Discovers, downloads, selects, renders, and assigns each clip a `publish_at` timestamp spread across the next 7 days.
  - **Daily upload run** — `daily_upload.py` triggered by Windows Task Scheduler once a day, ~5 min. Uploads that day's clips to YouTube with `privacyStatus=private` + `publishAt=<slot>`, letting YouTube auto-publish at the slot.
  - This split exists because YouTube's default API quota allows only ~6 inserts/day. Quota-increase audit is a future task; once approved, the daily run collapses into the weekly run.
- **Development & runtime:** the user's Windows laptop (single machine). Code is developed and run on the same PC; no separate dev/runtime environments. Earlier docs referenced a Mac development host — that's stale; ignore it.

## Stack
Python 3.11+ · ffmpeg+NVENC · yt-dlp · faster-whisper (CUDA) · YouTube Data API v3 · Ollama (`qwen2.5:3b-instruct`, local) · Windows Task Scheduler · SQLite. See `skills.md` for the full rationale. **Cost: $0/month.**

## Architecture in one diagram (v1.2 — post-content-pivot)
```
[Windows Task Scheduler — weekly]
   └─ weekly_run.py:
        keywords → discovery (quota_ledger) → downloader (mp4 + json3 caption sidecars)
                → lang_detect → captions (yt-dlp CC parse → cached JSON v2)
                → selector (caption-first reuse OR Whisper fallback + heatmap-or-fallback + Ollama qwen2.5:3b)
                → policy_gate (banlist / profanity / NSFW / hook-sanity / topic_filter)
                → editor (ffmpeg + NVENC + split + gblur + overlay + ASS karaoke)
                  → output/pending/__unscheduled__{clip_id}__{slug}.mp4
                → quality_screen (speech density, sub-conf, pHash + audio dedup, loudness)
                → slot_planner (TZ-aware, publish_at_utc) → renames to {date}__slot_{HHMM}__{slug}.mp4
                → retention (cleanup + VACUUM)
[user, ad-hoc]  drag from output/pending/ → output/approved/  (only while human_review=true)

[Windows Task Scheduler — daily]
   └─ daily_upload.py:
        files in output/approved/ (or output/pending/ if human_review=false) with publish_at_utc ∈ today
                → policy_gate (re-check)
                → uploader (videos.insert + publishAt, orphan-marker fence, --dry-run aware) → YouTube
                                  ↑
                          state.db (SQLite)
                                  ↑
                  observability (loguru → logs/agent.log + logs/alerts.md) ← every stage
```

## v1.1 changes (folded from external critique)
- New modules: `lang_detect/`, `policy_gate/`, `quality_screen/`, `quota_ledger/`, `retention/`, `observability/`, `slot_planner/`.
- Concrete virality formula (see `agents.md` discovery section / `executive_plan.md` §5.1).
- `mostReplayed` fallback validation rule (warn at <70% hit rate; spot-check quality gap).
- TZ semantics: canonical `timezone` from config, `zoneinfo` for DST, `publish_at_utc` stored UTC, missed-slot recovery batches stale → next future slot, future-too-near pad of 20 min.
- Quota ledger meters every billed call; weekly run aborts before exceeding 9,000 units/day.
- Per-phase acceptance criteria added to `plan.md`.
- Retention TTLs: raw 14 d, transcripts 90 d, queue 7 d post-upload, dup_hashes/quota_usage 90 d, monthly VACUUM.
- Observability: filesystem-based — `loguru` → `logs/agent.log`, append-only `logs/alerts.md` for run failure / quota near-cap / upload reject / missed-slot recovery / weekly finished.
- `--dry-run` mode on uploader; `bootstrap --check` for env health.
- Crop = **center crop** in v1; subject tracking deferred to Phase 8.
Each stage is independent and idempotent, communicating via the SQLite state store. See `agents.md` for module-by-module detail.

## Where things live
- `plan.md` — phased build plan, day-by-day.
- `agents.md` — module responsibilities and data flow.
- `skills.md` — libraries/APIs and the reasoning behind each.
- `progress.md` — running checklist; **update after every completed task.**
- `src/` — code (Phase 0 modules in place: `config_loader/`, `state/`, `quota_ledger/`, `observability/`, `bootstrap.py`).
- `config.yaml` — runtime config (committed). `.env` — secrets (gitignored). `data/client_secret.json` + `data/oauth_token.json` — YouTube OAuth (gitignored).

## Decisions already locked
- Engagement signal = YouTube `mostReplayed` heatmap + transcript-driven LLM ranking (local Ollama `qwen2.5:3b-instruct`, JSON-mode, fixed rubric prefix).
- Vertical layout (post-pivot) = full-screen movie clip on a blurred-background extension. Foreground 1080×608 (preserves the 16:9 frame, no edge crop), background = the same source scaled-to-cover + gaussian-blur (sigma=20). No split-screen; no gameplay.
- Subtitles = karaoke-style word-by-word, burned via ASS + libass. Position: `\pos(540, 1500)` (~78% down) so they sit clear of the centered 16:9 foreground band.
- Transcripts (post-pivot) = YouTube CC track preferred when available (manual word-level via JSON3 → skip Whisper); auto/line-interp captions fall back to Whisper. Schema_version=2 with `timing_source` and per-word `confidence_source`.
- Default cadence: 4 clips/day × 7 days = 28 clips/week. Configurable via `clips_per_day` and `days_per_run`.
- 4/day stays well under the 10k-unit/day quota (4 × 1,600 = 6,400 units, 1,000-unit headroom).
- `gameplay_cursor` and `gameplay_pointer` tables retained in `schema.sql` for backward compat but DEPRECATED post-pivot — no code reads or writes them.

## Hardware (locked)
- Windows PC: i9-11900H, 32 GB DDR4, 1 TB SSD, RTX 3070 laptop GPU (8 GB VRAM).
- Whisper: `large-v3` int8_float16 on CUDA. Render: `h264_nvenc`.

## Content inputs (locked)
- **Keywords (post-pivot):** "best movie scenes", "iconic movie moments", "movie clips 4k" — rotated. Old keywords (Joe Rogan / stoicism / NBA highlights) are archived; the existing 156 downloaded videos are inert (different keyword) and will age out via Phase 7 retention.
- **Background:** none — full-screen pivot, source video covers the entire frame on a blurred extension of itself. No gameplay pool, no rotation.
- **Caption sources:** yt-dlp manual captions (preferred) → yt-dlp auto-captions → Whisper fallback. See agents.md §3 for the decision rule.

## Locked decisions (post-redesign)
- **Stack is fully free.** Anthropic API removed. Local LLM via **Ollama** (`qwen2.5:3b-instruct`, q4_K_M ≈ 2 GB VRAM) handles ranking, NSFW classification, and hook-sanity checks. Runs alongside Whisper on the 8 GB RTX 3070.
- **`human_review = true` for first 2 weeks.** Mechanism is filesystem-based, not Discord:
  - Rendered clips → `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4`
  - User reviews in Explorer, drags approved files → `output/approved/`
  - Daily uploader pulls from `output/approved/` while review is on; from `output/pending/` directly after week 2.
- **Canonical timezone:** `Asia/Singapore`.
- **No Discord, no webhooks.** Failures and recoveries append to `logs/alerts.md`. User reads the file when convenient.
- **No Anthropic key. No paid services. Total cost: $0.**

## Working agreement
- Plan files are authoritative; touch them when scope changes.
- Build phase by phase per `plan.md`. Don't skip phases.
- Update `progress.md` immediately when a task completes — don't batch.
- No code written until the user confirms the plan.

## Risk acknowledgement
This channel format carries **elevated** copyright-strike risk after the movie-clip pivot. Major studios (Disney/WB/Universal) operate aggressive Content ID + manual takedown teams; transformative-format defense (short clip + reframe + burned subtitles) is **weak** against first-party studio content. The user has acknowledged this via `cfg.copyright_acknowledgement="movie_clips_v1"`. Mitigations:
- Short clips (≤60 s, enforced).
- Transformative format: full-screen + blurred-bg extension + burned subtitles + reframing to 9:16 (preserves the original 16:9 inside the 9:16 frame).
- Heavy source attribution in upload description (`Source: <url>` + `Original channel: <name>`).
- **Recommended ops mitigation:** run the first 2–3 weeks against a separate test channel before pointing OAuth at production.
- Prefer older / cult / international films when curating keyword variants.

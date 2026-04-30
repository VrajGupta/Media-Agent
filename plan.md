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
- Acquire 1–3 royalty-free background gameplay clips (10+ min each, 1080×1920).
- Install Ollama on the PC; `ollama pull qwen2.5:3b-instruct` (replaces the v1.0 Anthropic dependency — stack is fully free).
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
> Phase 2.5 already covers language detection. Phase 3 starts at `status='lang_ok'` and ends at `status='selected'` on `clips`. Policy gate / quality screen are Phase 4.5; render is Phase 4.

### Status flow
`lang_ok` → `transcribed` → `selected`

`transcribed` is intentional: full-video Whisper at `large-v3 int8_float16` is expensive (~1–3 min per video × 148 = 2.5–7 h). If ranking or heatmap fails mid-batch, we resume from cache without re-paying Whisper.

### Module layout (mirrors `lang_detect/`)
```
src/selector/
  __init__.py        re-exports
  __main__.py        CLI: --video-id, --force, --retranscribe, --dry-run, --config
  runner.py          orchestrator: run_all, select_one_video; reuses _preload_nvidia_dlls()
  transcriber.py     full-video Whisper + JSON cache
  heatmap.py         Innertube mostReplayed fetcher (NOT routed through quota_ledger)
  windows.py         sentence-aligned 30–60 s window slicing (non-overlapping)
  ranker.py          Ollama qwen2.5:3b-instruct JSON-mode HTTP client
```

### Idempotency (3 layers)
1. **Status preflight** — `selected` skips entirely (unless `--force`); `transcribed` skips Whisper, runs heatmap+rank only.
2. **Transcript cache** — `data/transcripts/{video_id}.json` is read if `model+compute_type` match `cfg.whisper_*`. On mismatch (e.g. user swapped `large-v3` → `medium.en`), silently re-transcribe. Cache write is atomic: write to `{video_id}.json.tmp`, `os.replace()` to final. Whisper failure → no temp file is promoted, status stays `lang_ok`.
3. **Selector-scoped clip upsert** — deterministic `clip_id = f"{video_id}_{int(start_s)}_{int(end_s)}"`. Phase 3 owns only `start_s, end_s, hook, suggested_title, selection_method, status, rejection_reason`. Use a new `repo.upsert_selector_clip(...)` helper that touches **only** those columns on conflict — must NOT clobber `publish_at_utc`, `publish_slot_local`, `output_path`, `youtube_video_id`, `title_slug` once Phases 4–6 have populated them.

### Per-video transactionality
Per video, in order:
1. Run Whisper → write transcript via `tmp + os.replace`.
2. `repo.set_video_status(video_id, 'transcribed')` (own transaction).
3. Heatmap fetch (no DB write).
4. Rank via Ollama → validate candidate IDs.
5. Inside `repo.tx()`: `upsert_selector_clip` for each chosen window, then `set_video_status(video_id, 'selected')`.
A crash between any two steps leaves the video in a recoverable status the next run picks up.

### Heatmap fetcher (`heatmap.py`)
- Endpoint: `POST https://www.youtube.com/youtubei/v1/player` with body `{"context":{"client":{"clientName":"WEB","clientVersion":"2.20240101.00.00"}},"videoId":"<id>"}`. Hard-coded as a module constant. 5 s timeout, one retry on connection error / 5xx, fail-open on persistent failure. No fixed sleep between calls — rely on timeout/retry to detect throttling.
- Parses `playerOverlays.playerOverlayRenderer.decoratedPlayerBarRenderer.decoratedPlayerBarRenderer.playerBar.multiMarkersPlayerBarRenderer.markersMap[*].value.heatmap.heatmapRenderer.heatMarkers[*].heatMarkerRenderer` (intensityScoreNormalized + timeRangeStartMillis + markerDurationMillis). Fail-open: 4xx / 5xx / missing path → return `None`, log at INFO, count as a miss.
- **NOT** routed through `QuotaLedger` — this is the public Innertube endpoint, not Data API v3.
- Per-run aggregate: `heatmap_hit_rate = videos_with_heatmap / videos_attempted`. If `< 0.70`, append a warning row to `logs/alerts.md` at run end (one rolled-up row, not per-video).
- A clip whose window overlaps any top-5 heat marker → `selection_method='heatmap_aided'`. Else `'transcript_only'`.

### Transcript cache schema (`transcriber.py`)
`data/transcripts/{video_id}.json`:
```json
{
  "schema_version": 1,
  "video_id": "abc123",
  "model": "large-v3",
  "compute_type": "int8_float16",
  "duration_seconds": 1234.5,
  "language": "en",
  "language_probability": 0.99,
  "segments": [
    {"start": 0.0, "end": 5.2, "text": "...",
     "words": [{"start": 0.1, "end": 0.5, "word": "Hello", "probability": 0.98}, ...]}
  ]
}
```
Word-level timestamps captured here so Phase 4's ASS subtitle generator reads from the cache instead of re-running Whisper. Storage: ~0.5–2 MB × 148 ≈ 100–300 MB. 90-day TTL handled by Phase 7 retention.

### Window slicing (`windows.py`)
Two candidate sources, merged + deduped before ranking:
1. **Non-overlapping baseline** — walk Whisper segments left-to-right, accumulate until cumulative duration ∈ [`clip_min_seconds`, `clip_max_seconds`], emit, reset.
2. **Heatmap-centered candidates** — for each top-5 heat marker, build a window centered on the marker's midpoint, then expand outward to the nearest sentence/segment boundaries until duration ∈ [30, 60]. Skip if no boundary set produces a valid duration. Captures setup/payoff arcs the baseline can split.

Each window: `{candidate_id, start_s, end_s, text, words, heatmap_peak: bool, source: "baseline" | "heatmap_centered"}`. `candidate_id = "c{0..N}"` per video — handed to the LLM so it can never invent start/end.

Dedup: merge windows whose `(start_s, end_s)` are within 1 s of each other; prefer `source="heatmap_centered"` on collision.

### Ranker (`ranker.py`)
- Endpoint: `POST http://localhost:11434/api/chat` with `format: "json"`, `keep_alive: "10m"` so the model stays resident across 148 calls.
- Fixed system prompt = the rubric (hook strength, payoff, self-contained, controversy/curiosity, no slow intro). Ollama's prefix kv-cache reuses it across calls.
- One call per video, all candidate windows in the user message. **Each window labeled by `candidate_id`**; the model returns those IDs back, never raw timestamps. We map IDs back to canonical `(start_s, end_s)` locally.
- Returned schema:
  ```json
  {"clips": [
    {"candidate_id": "c3", "hook": "...", "suggested_title": "...", "score": 8.5}
  ]}
  ```
  N items = `cfg.clips_per_video`.
- Validation: if any `candidate_id` is missing, duplicated, or unknown → retry once with stricter user prompt; persistent → leave at `transcribed`, append alert.
- Failures:
  - Malformed JSON → retry once; persistent → leave at `transcribed`, append alert.
  - Ollama unreachable → leave at `transcribed`, append alert, continue with next video.

### `--force` vs `--retranscribe`
- `--force` — re-rank from cached transcript (fast; the loop you actually use when iterating on the LLM rubric).
- `--retranscribe` — also re-pay Whisper. Used when swapping models.

### Reviewer spot-check log
At end of `weekly_run`, `selector.runner` auto-emits a template appended to `logs/heatmap_qa.md`: a markdown table with that week's clip IDs split into 5 transcript-only + 5 heatmap-aided rows, blank `rating_1_to_5` column. User fills in by watching each clip. After 2 weeks, compute mean-gap; if ≤ 1.0/5, fallback validated.

### CLI semantics (mirrors lang_detect)
```
python -m src.selector                                  # all rows where status in (lang_ok, transcribed)
python -m src.selector --video-id <id>
python -m src.selector --force                          # re-rank from cache (also re-checks selected rows)
python -m src.selector --retranscribe                   # re-pay Whisper too
python -m src.selector --dry-run                        # full pipeline, no DB writes / no transcript file write
python -m src.selector --config alt.yaml
```

### Acceptance
- First 10 clips manually rated: ≥ 7 "watchable hook" (heatmap-aided path); ≥ 6/10 on transcript-only.
- `pytest tests/` ≥ 85 passing (~15 new).
- Re-run on a `selected` video without `--force` exits in < 2 s with no Whisper load.

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
  - `python -m src.bootstrap --check` — env health check (ffmpeg/NVENC/CUDA/Whisper/YT OAuth/Ollama reachable + model pulled).
  - `python -m src.bootstrap` — single-clip end-to-end smoke test.
- **Time semantics:** canonical timezone is config (`timezone: Asia/Singapore`). `publish_at_utc` stored UTC; converted via `zoneinfo`. Slot planner spreads N×D clips across `upload_slots: ["09:00","13:00","17:00","21:00"]` over `days_per_run`.
- **Missed-slot recovery:** if `daily_upload` finds clips with `publish_at_utc` already in the past (PC was off), it pads them to `now + 20 min` rather than asking YouTube to publish in the past. Logged as `recovered_slot` and a row appended to `logs/alerts.md`.
- All single-process, SQLite as state. Graceful resume on partial failure.
- **Acceptance:** weekly_run produces 28 ready clips; daily_upload publishes 4/day for 7 days with no missed slots when PC online; missed-slot recovery exercised.

## Phase 7 — Hardening (Day 9–10)
- Structured logging (`loguru`) → `logs/agent.log`, daily rotation, 30-day retention.
- Retry with backoff (`tenacity`) on API/network errors; quarantine on repeated failure.
- **Alerts file** (`logs/alerts.md`): weekly run finished, run failure, quota > 80% used, upload rejected, missed-slot recovery. Markdown table; user reads on demand. (No Discord webhook — filesystem-based alerting only.)
- **Retention/cleanup module** at end of `weekly_run`:
  - `data/raw/*.mp4` → delete 14 days post-download or after all derived clips uploaded, whichever later.
  - `data/transcripts/*.json` → 90-day TTL.
  - `output/pending/*.mp4` → delete 7 days after `uploaded` confirmed.
  - `dup_hashes` rows older than 90 days pruned.
  - SQLite `VACUUM` monthly.
- Per-run summary appended to `logs/runs.md`.
- Config-driven (`config.yaml`): keywords, `clips_per_day`, `days_per_run`, `upload_slots`, `timezone`, `human_review`, `banlist`, model sizes, paths.
- **Windows Task Scheduler** entries committed as `.xml` exports under `scripts/`:
  - `weekly_run.xml` — Sundays 02:00 local TZ.
  - `daily_upload.xml` — daily 09:00 local TZ.
- Document quota-increase audit form steps in `README.md`.
- **Acceptance:** logs rotate; `logs/alerts.md` rows appear on synthetic triggers (run failure, quota > 80%, upload reject, missed-slot recovery); cleanup deletes correct files; double-running `weekly_run` is a no-op.

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

# Agents / Modules

Each module is a single-purpose Python package under `src/`. They communicate through the SQLite state store, not direct calls — so any stage can be re-run independently.

## 1. `discovery/` — Discovery Agent
**Job:** Find candidate long-form videos for a given keyword.
**Inputs:** keyword list from `config.yaml`.
**Outputs:** rows in `videos` table (`video_id`, `title`, `channel`, `duration`, `views`, `published_at`, `virality_score`, `status='discovered'`).
**Key calls:** `youtube.search.list` (with `relevanceLanguage=en`), `youtube.videos.list`. Both metered via `quota_ledger`.
**Filter:** duration ≥ 5 min. *True English-audio filter happens post-download in `lang_detect/`; `search.list` only filters by metadata language.*
**Virality formula (locked):**
```
recency_factor   = views / max(age_hours, 24)
engagement_rate  = (likes + 4*comments) / max(views, 1)
niche_normalized = views / max(rolling_30d_median_for_niche, 1)
virality_score   = log10(recency_factor + 1)
                 * (0.5 + min(engagement_rate * 50, 1.5))
                 * log10(niche_normalized + 1)
```
Threshold to enter selection: `virality_score ≥ 1.0`.

## 2. `downloader/` — Downloader
**Job:** Pull the source mp4 + auto-captions for any `discovered` video.
**Inputs:** `videos` rows where status=`discovered`.
**Outputs:** file at `data/raw/{video_id}.mp4`; status → `downloaded`.
**Tool:** `yt-dlp` (Python API). Format selector: `bv*[height<=1080]+ba/b[height<=1080]`.
**Notes:** Idempotent. Disk-budget aware (deletes raw file once all clips are rendered).

## 2.5. `lang_detect/` — Language Filter (NEW)
**Job:** Reject non-English videos before expensive selection.
**Logic:** transcribe first 60 s with Whisper; if detected language ≠ `en` with confidence ≥ 0.7, mark video `rejected_language` and stop.

## 3. `selector/` — Clip Selector
**Job:** Pick the 1–3 most viral 30–60s windows in each downloaded video.
**Inputs:** `data/raw/{video_id}.mp4`, transcript, optional `mostReplayed` heatmap.
**Outputs:** rows in `clips` table (`clip_id`, `video_id`, `start_s`, `end_s`, `hook`, `suggested_title`, `selection_method` (`heatmap_aided` | `transcript_only`), `publish_at_utc` (filled later by slot planner), `status='selected'`).
**Sub-steps:**
- `transcriber.py` — faster-whisper → word-level JSON, cached to `data/transcripts/`.
- `heatmap.py` — fetch `mostReplayed` markers; **fallback validation**: if per-run `heatmap_hit_rate < 70%`, append a warning row to `logs/alerts.md`. First 2 weeks: manual spot-check 5+5 transcript-only vs heatmap-aided clips/week to bound quality gap ≤ 1.0/5.
- `ranker.py` — local Ollama (`qwen2.5:3b-instruct`) w/ JSON-mode output and a fixed rubric prefix (kv-cache reused across calls): hook strength, payoff, self-contained, controversy/curiosity, no slow intro.

## 3.5. `policy_gate/` — Policy & Safety Gate (NEW)
**Job:** Block clips that would risk strikes, ToS violations, or misleading metadata. Runs **twice**: post-select (before render) and pre-upload (in `daily_upload.py`).
**Checks:**
- Banlist substring match on transcript + suggested title (config-driven list).
- Profanity scoring (`better-profanity` baseline).
- NSFW text classifier on transcript (zero-shot via Ollama).
- Hook-vs-content sanity check: Ollama rates whether `suggested_title` accurately summarizes the clip; reject if score < 3/5.
**Failure:** writes `clips.rejection_reason`, status → `rejected_policy`. Not rendered, not uploaded.
**Config knob:** `human_review: true` (default for first 2 weeks) → rendered clips land in `output/pending/`; user must manually move to `output/approved/` before `daily_upload` will publish them. `human_review: false` → uploader treats `output/pending/` as the publish queue directly.

## 4. `editor/` — Vertical Reformat & Subtitle Burner
**Job:** Render the final 1080×1920 Short.
**Inputs:** clip row + raw video + word-timed transcript + the next gameplay segment from the rotation pool.
**Outputs:** `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4` (slug = lowercased alphanumeric+underscore from suggested title, ≤80 chars); status → `rendered`. Filename is self-describing so the user can review without opening the DB.
**Crop:** **center crop** to 1080×960 in v1 (subject-tracking deferred to Phase 8).
**Pipeline (single ffmpeg invocation where possible):**
1. Extract clip segment.
2. Build top pane: scale + crop source to 1080×960.
3. Build bottom pane: seek into the next gameplay segment per rotation rule, scale/crop to 1080×960.
2a. Top pane: center-crop to 1080×960.
4. Vstack → 1080×1920 @ 30fps.
5. Mix source audio (full) + gameplay audio (muted).
6. Burn ASS subtitle file with word-by-word highlight (one or two words on screen, big bold white + black stroke, centered ~70% down).
7. Loudness normalize via `loudnorm` filter.
8. Encode with `h264_nvenc` (NVIDIA RTX 3070) — `-preset p5 -cq 23`.

## 4.5. `quality_screen/` — Content Quality Screen (NEW)
**Job:** Block low-quality or duplicate output before it enters the upload queue.
**Checks (all must pass):**
- `speech_density ≥ 1.5` words/sec.
- mean Whisper word-confidence ≥ 0.6 across the clip window.
- Perceptual hash (pHash on 5 evenly-spaced frames) + audio fingerprint compared against `dup_hashes` (last 90 days). Reject on match.
- Final clip duration ∈ [25, 65] s.
**Failure:** status → `rejected_quality`, `rejection_reason` populated.

## 5. `subtitles/` — Subtitle Generator
**Job:** Convert Whisper word timestamps into a karaoke-style `.ass` file.
**Style:** Impact/Anton font, ~120pt, white fill, 8px black border, yellow highlight on the active word.

## 6. `uploader/` — YouTube Uploader
**Job:** Publish a `rendered` clip to YouTube as a Short with a future `publishAt`.
**Inputs:** When `human_review=true`: file in `output/approved/`. When `false`: file in `output/pending/`. Plus clip metadata + `publish_at_utc` timestamp.
**Outputs:** uploaded video (private, scheduled); status → `uploaded`; `youtube_video_id` + confirmed `publish_at` stored.
**Insert body:** `status.privacyStatus=private`, `status.publishAt=<ISO UTC>`, `selfDeclaredMadeForKids=false`.
**Auth:** OAuth refresh token cached at `data/oauth_token.json`.
**Title rule:** `{hook} #Shorts` (≤100 chars). Description: hook + source attribution line + niche hashtags.
**Quota guard:** queries `quota_ledger`; refuses upload if next call would push today's units > 9,000.
**Future-too-near rule:** if `publish_at_utc < now + 20 min`, pad to `now + 20 min` (YouTube rejects past or near-future timestamps).
**Dry-run mode (`--dry-run`):** writes the would-be insert body to `output/dry_run/{clip_id}.json`, makes no API call.

## 6.5. `quota_ledger/` — Per-Endpoint Quota Tracker (NEW)
**Job:** Prevent silent quota overruns.
**Schema:** `quota_usage(date, endpoint, units)` indexed on `date`.
**API:** `record(endpoint, units)`; `today_total()`; `would_exceed(units, ceiling=9000)` pre-flight check called before every billed API call.
**Resets:** rows older than 90 days pruned by `retention/`.

## 7. `orchestrator/` — Run Entrypoints
**No daemon.** Triggered by Windows Task Scheduler.

### `weekly_run.py`
1. Discovery → download → selector → editor over `keywords` until `clips_per_day × days_per_run` rendered clips exist in `output/pending/`.
2. `slot_planner.py` assigns each clip a `publish_at` evenly spaced across the next `days_per_run` days at configured times-of-day.
3. Idempotent: if it crashes mid-run, the next invocation picks up from state.

### `daily_upload.py`
1. Reads all clips with `publish_at` within `[today 00:00, today 23:59]` and `status='rendered'`.
2. For each, calls uploader with the clip's `publish_at`. Stops if the quota guard trips.
3. Marks `uploaded`. Logs a one-line per-clip summary.

### `bootstrap.py`
End-to-end smoke run: one keyword, one clip, one upload to a private test channel. For verifying setup before the first real weekly run.

## 8. `state/` — State Store
SQLite at `data/state.db`. Tables: `videos`, `clips`, `uploads`, `runs`, `gameplay_cursor`. Thin repository module — no ORM needed for this scale.

### Gameplay rotation
`gameplay_cursor` table: `(file_name PK, last_offset_s, last_used_at)`. Pool order: Subway → Minecraft → GTA, round-robin per clip. Each clip consumes `clip_duration` seconds starting at the file's `last_offset_s`. When `last_offset_s + clip_duration > file_duration`, wrap to 0. A separate `pool_pointer` row tracks which file is next in the round-robin so episode N+1 always advances to the next file.

## 9. `config/` — Config & Secrets
- `config.yaml` — keywords, `clips_per_day`, `days_per_run`, `upload_slots`, `timezone`, `human_review`, `banlist`, model sizes, paths, gameplay pool.
- `.env` — optional overrides (e.g. `OLLAMA_HOST`). YouTube OAuth lives in `data/client_secret.json` + `data/oauth_token.json` (both gitignored).

## 10. `retention/` — Cleanup (NEW)
**Job:** Free disk and prune state at the end of `weekly_run`.
**Rules:**
- `data/raw/*.mp4` → delete 14 days post-download or after all derived clips uploaded, whichever later.
- `data/transcripts/*.json` → 90-day TTL.
- `output/pending/*.mp4`, `output/approved/*.mp4` → delete 7 days after `uploaded` confirmed.
- `output/rejected/*.mp4` (user-side reject pile) → delete after 30 days.
- `dup_hashes` rows older than 90 days pruned.
- `quota_usage` rows older than 90 days pruned.
- SQLite `VACUUM` once per month.

## 11. `observability/` — Logging & Alerts (NEW)
**Job:** Make autonomous failures visible without push notifications.
**Stack:** `loguru` → `logs/agent.log` (daily rotation, 30-day retention).
**Alerts file:** `logs/alerts.md` — single markdown table; one row appended on each of: weekly run finished, run failure, quota > 80% used, upload rejected by YouTube, missed-slot recovery. User scans this file once a day.
**Per-run summary:** appended to `logs/runs.md` (date, keyword, candidates, rendered, dropped-by-reason, uploaded, quota_used).
**Filesystem-as-signal:** counts of files in `output/pending/` vs `output/approved/` are themselves a queue-depth signal the user can see in Explorer.

## Data Flow (v1.1)
```
keywords → [discovery] (quota_ledger metered) → videos table
                              ↓
                        [downloader] → data/raw/*.mp4
                              ↓
                       [lang_detect] (rejects non-en)
                              ↓
                         [selector] (heatmap-or-fallback + Haiku ranker) → clips table (+ transcripts)
                              ↓
                       [policy_gate] (banlist, profanity, NSFW, hook-sanity)
                              ↓
                          [editor] (ffmpeg + NVENC + ASS karaoke) → output/pending/*.mp4
                              ↓
                     [quality_screen] (speech density, sub-conf, pHash + audio dedup)
                              ↓
                      [slot_planner] (TZ-aware) → clips.publish_at_utc filled
                              ↓
                       [retention] (cleanup + VACUUM)
                              ↓
   (Windows Task Scheduler — daily) → [daily_upload] →
                       [policy_gate] (re-check) → [uploader] (quota_ledger metered, --dry-run aware) → YouTube (scheduled)
                              ↑
              [observability] (loguru → logs/agent.log + logs/alerts.md) ← every stage
```

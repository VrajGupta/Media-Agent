# Agents / Modules

Each module is a single-purpose Python package under `src/`. They communicate through the SQLite state store, not direct calls — so any stage can be re-run independently.

> **Pivot.6 status legend:**
> - ✅ Keep (unchanged or minor config-only update)
> - 🔧 Keep with changes (input contract / schema / templating update required)
> - 🆕 New module (Pivot.6)
> - ❌ Retired (Pivot.6 — code + tests deleted)

---

## ❌ `discovery/` — Discovery Agent (RETIRED Pivot.6)
Was: find candidate long-form YouTube videos by keyword, virality-score them, persist to `videos` table.
Retired because: no source-video ingestion in Pivot.6. Code + ~31 tests deleted.

## ❌ `downloader/` — Downloader (RETIRED Pivot.6)
Was: pull mp4 + caption sidecars via yt-dlp.
Retired because: no source-video ingestion in Pivot.6. Code + ~9 tests deleted.

## ❌ `lang_detect/` — Language Filter (RETIRED Pivot.6)
Was: reject non-English videos via Whisper on the first 60 s.
Retired because: no source video to classify. Code + ~14 tests deleted.

## ❌ `selector/` — Clip Selector (RETIRED Pivot.6)
Was: pick 1–3 viral 30–60 s windows per downloaded video (Whisper + heatmap + Ollama ranker).
Retired because: no source video to slice. Code + ~55 tests deleted.

---

## 🆕 `topic_ingest/` — RSS Topic Ingest (NEW Pivot.6)
**Job:** Fetch fresh tech/AI news topics from configured RSS feeds, dedup against previously-scripted stories, populate `topics` table.
**Inputs:** `config.topic_ingest.feeds` (list of RSS URLs), `config.topic_ingest.recency_hours` (48 h default), `config.topic_ingest.title_similarity_threshold`.
**Outputs:** `topics` table rows (`id`, `url`, `title`, `summary`, `source_feed`, `fetched_at`, `status='unscripted'`); `seen_topics` ledger rows for dedup (`url_hash`, `title_normalized`, `first_seen_at`).
**Dedup logic:** SHA-256 of `<link>` (exact) + normalized-title similarity (Levenshtein or word-set overlap; configurable threshold). Catches reposts across Verge / TechCrunch / Ars where the same story has different URLs.
**Library:** `feedparser` for RSS/Atom parsing.
**Failure modes:** unreachable feed → log + skip + continue with remaining feeds (not fatal). Empty result set → alert in `logs/alerts.md` (kind=`rss_empty`).
**Public interface (deep module seam):** `fetch_unscripted_topics(cfg, repo) -> list[Topic]`.

## 🆕 `scripter/` — Script Generator (NEW Pivot.6)
**Job:** Produce a complete `{title, narration, shots[], style_notes}` JSON script from one queued topic.
**Inputs:** unscripted topic row from `topics` table (title + summary), Ollama `qwen2.5:3b-instruct` JSON-mode.
**Outputs:** `scripts` table row (`script_id`, `topic_id` FK, `title`, `narration`, `shots_json`, `style_suffix`, `status='scripted'`); stub `clips` row (`content_kind='ai_generated'`, `script_id`, `video_id=NULL`).
**Rubric (locked, Tech/AI niche):** hook in first 5 words, ~40 words narration, 4 shots × ~4 s each, 1–2 punchy stats, ends on a teaser. Schema validated with pydantic; single retry on validation fail.
**Failure:** `scripts.status='rejected_policy'` if policy_gate rejects; retry up to `scripter.retry_on_policy_reject`.

## 🆕 `ai_gen/` — AI Video Generator Client (NEW Pivot.6)
**Job:** Submit shot prompts to an AI video generator, poll for completion, download mp4s.
**Design:** `base.Provider` ABC (`submit`, `poll`, `download`, `last_cost_cents`). **Production impl: `openrouter_kling.OpenRouterKlingClient`** (Kling 3.0 std `kwaivgi/kling-v3.0-std` via OpenRouter REST API, Bearer auth via `OPENROUTER_API_KEY`). `kling.KlingClient` (direct Kling JWT auth) retained as fallback. `pika.PikaClient` / `minimax.MiniMaxClient` / `seedance.SeedanceClient` are ready drop-in slots.
**Inputs:** `scripts` row + `generation_jobs` table (persisted per shot for idempotency).
**Outputs:** `data/ai_gen/{script_id}/shot_{i}.mp4`; `generation_jobs.status='succeeded'`; cost recorded in `quota_usage(provider='openrouter')`.
**Concurrency:** `threading.Semaphore` with `max_concurrent_jobs=2` (config-driven).
**Cost guard:** `per_clip_cost_cents_max` enforces per-clip abort; `daily_spend_cents_ceiling` in quota_ledger enforces daily hard stop.
**Style suffix (locked, Tech/AI niche):** appended to every shot prompt — `"clean editorial product photography, soft studio lighting, neutral backgrounds, minimalist composition, sharp focus, vertical 9:16, premium tech magazine look"`.

## 🆕 `narration/` — TTS Narration (NEW Pivot.6)
**Job:** Convert `script.narration` text → mp3 + per-word timings.
**Engine:** `edge-tts` (free, Microsoft neural voices). Voice: `en-US-GuyNeural`, rate `+10%`, pitch `0Hz` — natural conversational pacing (engaged-friend cadence; not calm/slow, not crammed).
**Word timings:** Whisper `large-v3` int8_float16 on CUDA run on the TTS mp3 → forced-align word timestamps. TTS audio is always clean → very fast/accurate transcription.
**Outputs:** `data/narration/{script_id}.mp3` + word-timings dict (used by subtitle writer).
**Degraded mode:** `pyttsx3` offline fallback if Edge TTS is throttled.

---

## 🔧 `assembler/` — Clip Assembler (replaces `editor/`, Pivot.6)
**Job:** Render the final 1080×1920 Short from generated shots + narration.
**Inputs:** list of `data/ai_gen/{script_id}/shot_{i}.mp4` + narration mp3 + subtitle ASS file + optional music track.
**Outputs:** `output/pending/__unscheduled__{clip_id}__{title_slug}.mp4`; `clips.status='rendered'`.
**Pipeline (single ffmpeg invocation):**
1. Concat 4–6 shot mp4s (hard cut, no crossfade — Kling already paces).
2. Mux narration mp3 as sole audio track (replace source audio).
3. Mix music bed at −22 dB with auto-duck under narration (reuses `editor/music.py` helpers).
4. Burn ASS subtitle file (line-at-a-time, from `subtitles/`).
5. NVENC encode: `h264_nvenc -preset p5 -cq 23 -movflags +faststart`, 2-pass loudness to −14 LUFS.
**Reused from `editor/`:** `music.py` (track picker + mix), `ffmpeg_runner.py` (NVENC helpers), `slug.py` (filename slug).
**Dropped from `editor/`:** blurred-bg split/gblur/overlay filtergraph (Kling outputs native 9:16 — no blurred bg needed). Karaoke subtitle path (replaced by line-at-a-time in `subtitles/`).

## 🔧 `subtitles/` — Subtitle Generator (Pivot.6: line-at-a-time)
**Job:** Convert per-word timings (from `narration/`) into a line-at-a-time centered `.ass` file.
**Style:** Anton font, 64pt, white fill, 8px black border. Position: `\pos(540, 1500)` (~78% down). Lines broken at ≤28 chars on natural word boundaries, 100 ms fade-in.
**Breaking change from Pivot.5:** karaoke word-by-word highlighting replaced by centered line-at-a-time. Old karaoke writer archived to `src/subtitles/_karaoke_legacy.py` for one pivot.

---

## 🔧 `policy_gate/` — Policy & Safety Gate (input contract updated Pivot.6)
**Job:** Block scripts/clips that would risk ToS violations or misleading metadata. Runs **twice**: post-script (before generation) and pre-upload (in `daily_upload.py`).
**Input change (Pivot.6):** `clip_text` = `script.narration` (not a Whisper transcript of source video). `recheck_title` = `script.title`.
**Checks (unchanged):** banlist substring match · profanity scoring (`better-profanity`) · NSFW zero-shot via Ollama · hook-vs-content sanity (Ollama: does title summarize narration?) · topic_filter (re-tuned for new topic pool).
**Failure:** `scripts.status='rejected_policy'` (pre-gen) or `clips.status='rejected_policy'` (pre-upload). `rejection_reason` populated.

## 🔧 `quality_screen/` — Content Quality Screen (gates updated Pivot.6)
**Job:** Block low-quality or duplicate output before it enters the upload queue.
**Checks active for `content_kind='ai_generated'`:**
- `duration.py` — final clip ∈ [25, 65] s.
- `loudness.py` — integrated loudness within ±1.5 LUFS of −14.
- `dedup.py` — pHash on 5 frames + (optionally) script-text hash to prevent narrative repetition. Stored in `dup_hashes`, matched over last 90 days.
**Checks SKIPPED for `content_kind='ai_generated'`:** `density.py` (speech density) and `confidence.py` (word confidence) — TTS output is always clean; these gates add no value and would false-positive on silence in generated video.

## 🔧 `uploader/` — YouTube Uploader (templating updated Pivot.6)
**Job:** Publish a `quality_pass` (or `approved`) clip to YouTube as a Short with a future `publishAt`.
**Unchanged:** orphan-marker fence, pre-upload re-check, quota guard, dry-run mode, `publish_at_utc` padding (20 min lead), resumable upload with tenacity.
**Changed for Pivot.6 (`content_kind='ai_generated'`):**
- `templater.py` — description drops `Source: url` + `Original channel: name`; replaces with `compliance.description_footer` ("Made with AI. For entertainment / educational use.") + topic hashtag. Tags from `upload_extra_tags` config key.
- `insert_body.py` — `altered_content` / `madeWithAi` flag set when `compliance.ai_disclosure=true`. (Exact v3 API field name to be confirmed at Slice 9 — manual Studio attestation if not yet exposed.)
- `runner.py` — `get_clip_with_video` join becomes LEFT JOIN; templater receives `content_kind` for routing.

## 🔧 `quota_ledger/` — Per-Endpoint Quota Tracker (provider dimension added Pivot.6)
**Job:** Prevent silent quota overruns across all billed APIs.
**Schema update:** `quota_usage` gains `provider TEXT NOT NULL DEFAULT 'youtube'`. Existing rows backfill to `'youtube'`.
**New provider:** `provider='openrouter'`, `units=cost_cents`. Daily ceiling enforced separately from YouTube units.
**API unchanged:** `record(endpoint, units, provider)`, `today_total(provider)`, `would_exceed(units, ceiling, provider)`.

## 🔧 `state/` — State Store (schema bridge Pivot.6)
**Schema additions:**
- `clips.content_kind TEXT NOT NULL DEFAULT 'sourced'` — `'sourced'` (legacy) | `'ai_generated'` (Pivot.6+).
- `clips.script_id TEXT` — FK → `scripts(script_id)`, nullable.
- `clips.video_id` — relaxed to nullable for `ai_generated` rows (was NOT NULL).
- `topics` table (new) — `id PK, url, title, summary, source_feed, fetched_at, status`. Status: `'unscripted' | 'scripted' | 'expired'`.
- `seen_topics` table (new) — `url_hash PK, title_normalized, first_seen_at`. Dedup ledger.
- `scripts` table (new) — `script_id PK, topic_id FK, title, narration, shots_json, style_suffix, ollama_model, created_at, status`.
- `generation_jobs` table (new) — `job_id PK, script_id, shot_index, provider, prompt, duration_s, status, external_id, output_path, cost_cents, submitted_at, completed_at, error`.
- `quota_usage.provider` column (new).
**Tables NOT dropped (Pivot.6):** `videos`, `dup_hashes`, `niche_baselines`, `discovery_attempts` — inert for new content but referenced by historic rows. Drop in a future cleanup pivot.
**New repository helpers:** `insert_topic`, `seen_topics_in_window`, `mark_topic_scripted`, `insert_script`, `insert_generation_job`, `update_job_status`, `clips_for_generation_run`, `get_clip_with_script`.

## ✅ `slot_planner/` — Slot Planner (unchanged)
**Job:** Assign `publish_at_utc` timestamps to rendered clips, spaced evenly across the next `days_per_run` days at configured slots. Rename files in place. Missed-slot recovery batches stale → next future slot. Future-too-near pad of 20 min.

## 🔧 `retention/` — Cleanup (TTLs updated Pivot.6)
**New TTLs:** `data/ai_gen/{script_id}/` — 7 d post-render. `data/narration/` — 14 d. `scripts` rows — 90 d. `topics` rows — 30 d post-`fetched_at`.
**Dropped TTLs:** `data/raw/*.mp4` (14 d) and `data/transcripts/*.json` (90 d) — no longer produced.
**Unchanged:** `output/pending|approved` 7 d post-upload, `dup_hashes` 90 d, `quota_usage` 90 d, monthly VACUUM.

## ✅ `observability/` — Logging & Alerts (unchanged)
**Stack:** `loguru` → `logs/agent.log` (daily rotation, 30-day retention). `logs/alerts.md` — one row appended on: weekly run finished, run failure, quota > 80% used (per provider), upload rejected, missed-slot recovery, OpenRouter spend near cap, `rss_empty`. `logs/runs.md` — per-run summary (kind, started_at, finished_at, success, summary).

## ✅ `config_loader/` — Config Loader (new keys added, otherwise unchanged)
New config sections: `topic_ingest.*`, `ai_gen.*`, `scripter.*`, `narration.*`, `subtitles.*`, `compliance.*`. Old discovery/lang_detect/selector/blurred_bg keys moved to `config.archive.yaml`.

## 🔧 `bootstrap.py` — Environment Health Check (updated Pivot.6)
**New checks:** `OPENROUTER_API_KEY` env var set, `edge-tts` importable, `feedparser` importable, ffmpeg concat smoke, Whisper load. **Dropped check:** `yt-dlp` availability, direct `KLING_API_KEY`.

## ✅ `daily_upload.py` — Daily Upload Entrypoint (unchanged)
Reads `clips_for_upload_due()`, runs policy re-check, calls uploader. Run lock + `runs.md` writer. `--dry-run` aware. Content-agnostic — templating branch is inside `uploader/`.

## 🆕 `gen_run.py` — Weekly Generation Entrypoint (NEW Pivot.6, replaces `weekly_run.py`)
**Job:** Full weekly orchestration: `topic_ingest → scripter → policy_gate → ai_gen → narration → assembler → quality_screen → slot_planner → retention`. Run lock (`data/.weekly_run.lock`) + `runs.md` writer. `--dry-run` and `--clips N` flags.

---

## Data Flow (Pivot.6)
```
RSS feeds → [topic_ingest] (feedparser; 48h window; URL + title-similarity dedup → topics + seen_topics tables)
                        ↓
                  [scripter] (Ollama qwen2.5:3b on topic.title+summary → scripts table + clips stub, content_kind='ai_generated')
                        ↓
               [policy_gate] (banlist/profanity/NSFW/hook_sanity on narration+title)
                        ↓
                  [ai_gen] (OpenRouter Kling 3.0 × 4 shots × ~4s, threading.Semaphore, generation_jobs table) → data/ai_gen/{script_id}/shot_{i}.mp4
                        ↓
                [narration] (Edge TTS +10%/0Hz → mp3; Whisper forced-align → word timings) → data/narration/{script_id}.mp3
                        ↓
               [assembler] (concat shots → mux narration → music-bed duck → ASS line-burn → NVENC 1080×1920 → −14 LUFS)
                        ↓ output/pending/__unscheduled__{clip_id}__{slug}.mp4
          [quality_screen] (duration, loudness, pHash dedup)
                        ↓
             [slot_planner] → clips.publish_at_utc + filename rename
                        ↓
               [retention] (cleanup + VACUUM)
                        ↓
(Windows Task Scheduler — daily) → [daily_upload] →
                  [policy_gate] (re-check) → [uploader] (quota_ledger metered, orphan-marker fence, --dry-run aware) → YouTube (scheduled)
                        ↑
         [observability] (loguru → logs/agent.log + logs/alerts.md) ← every stage
```

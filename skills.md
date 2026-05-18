# Tools, Libraries & APIs

> **Pivot.6 (current — Tech/AI news):** yt-dlp and mostReplayed are no longer used. Ollama's role has shifted from clip-ranker to script-writer. New additions: OpenRouter Kling 3.0 std (video generator), edge-tts (TTS narration), `feedparser` (RSS topic ingest), Whisper now used for forced-alignment of TTS output rather than source-video transcription.

## Language & Runtime
- **Python 3.11+** — best ecosystem fit for all project dependencies. Single-language project.
- **ffmpeg** (system binary, Gyan 8.1-full_build) — concat, mux, loudnorm, ASS burn, NVENC encode. Must be on PATH.

## AI Video Generation (NEW — Pivot.6)
- **OpenRouter Kling 3.0 std** (`kwaivgi/kling-v3.0-std`, accessed via OpenRouter REST API, `OPENROUTER_API_KEY`) — text-to-video generator. Native 9:16 output at 1080×1920. ~4 s shot duration, 4 shots stitched per clip. Bearer auth (no JWT signing). Implementation: `src/ai_gen/openrouter_kling.py` (`OpenRouterKlingClient(Provider)`, 23 unit tests).
- **Provider seam:** `src/ai_gen/base.Provider` ABC. Pika 2.0, MiniMax-Hailuo, and Seedance are drop-in replacements with ~½-day effort. Direct Kling API adapter (`src/ai_gen/kling.py`) retained as a fallback, not the production path (was blocked on error 1003 "Authorization not active").
- **Why OpenRouter over direct Kling:** API activation is immediate, billing aggregates across providers in one place, single env var simplifies key rotation. Switching providers requires no downstream pipeline changes.
- **Cost model:** per-second pricing; **$5/week budget → 2–3 clips/week at ~$2/clip**. Scales to ~$80/mo at 4 clips/day. Enforced by `per_clip_cost_cents_max` + `daily_spend_cents_ceiling` in `quota_ledger`.

## TTS Narration (NEW — Pivot.6)
- **`edge-tts`** (PyPI, free) — Microsoft Azure neural TTS via the unofficial public endpoint. No API key required. Voice `en-US-GuyNeural`. Rate `+10%`, pitch `0Hz` — natural conversational pacing (not slow/calm, not crammed; engaged-friend cadence).
- Why free over ElevenLabs: user requirement is zero additional paid services. Edge TTS quality is acceptable for this format.
- **Degraded-mode fallback:** `pyttsx3` (offline, SAPI5 voices) if Edge TTS throttles. Quality is lower but non-blocking.

## RSS Topic Ingest (NEW — Pivot.6)
- **`feedparser`** (PyPI) — RSS/Atom feed parsing. Pulls last-48h items from mixed consumer + research tech/AI feeds. Source-of-truth for topic selection; replaces the static `topic_pool` config.
- **Dedup:** URL hash (SHA-256 of `<link>`) + normalized-title similarity (Levenshtein or word-set overlap, configurable threshold). Catches reposts where the same story has different URLs across Verge / TechCrunch / etc.
- **Feed list:** user-curated, configured at Slice 7. Recommended feeds documented in `docs/rss_feeds.md`.

## Video Acquisition (LEGACY — not used in Pivot.6)
- **`yt-dlp`** (Python API) — was used for YouTube source-video downloads and caption sidecar retrieval (Phases 1–7, Pivots.0–5). Retained in `requirements.txt` but no code path calls it in Pivot.6. Will be removed when the `discovery/` and `downloader/` modules are fully deleted.

## Upload
- **YouTube Data API v3** via **`google-api-python-client`** — used for `videos.insert` (resumable upload) with `publishAt` + `altered_content` flag. `search.list` and `videos.list` no longer called (discovery retired in Pivot.6).
- **`google-auth-oauthlib`** — handles OAuth desktop flow; refresh-token cached at `data/oauth_token.json`.
- **`requests`** — HTTP client for Ollama API calls and (previously) `mostReplayed` heatmap endpoint.

## Transcription / Forced Alignment (ROLE CHANGED — Pivot.6)
- **`faster-whisper`** — now used exclusively for **forced alignment**: run on the Edge TTS mp3 output to extract per-word timings for the subtitle writer. No longer used on source video (no source video). Model: `large-v3` `int8_float16` on CUDA. Fits the RTX 3070 with headroom.
- Requires CUDA 12.x + cuDNN 9 on the PC (already installed).

## Script Writing / Policy / Hook-Sanity (LLM — ROLE CHANGED — Pivot.6)
- **Ollama** running locally on the PC, model **`qwen2.5:3b-instruct`** (q4_K_M ≈ 2 GB VRAM). Fits the RTX 3070 alongside Whisper. JSON-mode output.
- **Old role (Pivots.0–5):** clip ranking, NSFW transcript classifier, hook-vs-content sanity check.
- **New role (Pivot.6):** script writer — given a topic seed, produces `{title, narration, shots[], style_notes}` JSON. NSFW classifier and hook-sanity check still run, now on the generated narration + title.
- Quality note: 3B-class instruct models are sufficient for rubric-style script generation. Swap to `qwen2.5:7b-instruct` (≈ 5 GB VRAM) by changing one config line if quality is inadequate.

## Editing & Rendering
- **`ffmpeg-python`** (or raw subprocess) — composes the vstack + crop + subtitle-burn + loudnorm filtergraph in a single pass for speed.
- **NVENC (`h264_nvenc`)** — hardware-accelerated H.264 encoding on the RTX 3070; chosen over libx264 for ~5× faster renders, which matters when a single pipeline run produces multiple clips.
- **ASS subtitles** (libass via ffmpeg) — only practical way to get karaoke-style word highlighting burned into video.
- **`Pillow`** — generate ASS-incompatible overlays (e.g., title cards) if needed.

## Scheduling
- **Windows Task Scheduler** — host-level cron. Triggers `weekly_run` (weekly) and `daily_upload` (daily). No long-running Python daemon needed.
- **YouTube native scheduling** — `status.publishAt` on the insert call lets YouTube auto-publish at a future timestamp. We use this so the daily uploader can hand off all that day's clips at once and YouTube spaces out the actual publish times.

## State & Config
- **SQLite** via stdlib `sqlite3` — file-based, zero-ops, perfect for single-process pipeline state.
- **`pydantic`** + **`pyyaml`** — typed config loading from `config.yaml`.
- **`python-dotenv`** — load secrets from `.env`.

## Logging & Reliability
- **`loguru`** — structured logs with rotation, far less ceremony than stdlib logging.
- **`tenacity`** — retry decorators with exponential backoff for API/network calls.
- **`requests`** — used for Ollama HTTP calls and `mostReplayed` heatmap fetch.

## Human-in-the-Loop & Review
- **File-system as queue.** No Discord, no webhooks. Rendered clips drop into `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4`. The user reviews in Explorer; approved clips are moved to `output/approved/`; the daily uploader reads from `output/approved/` while `human_review=true`. After 2 weeks (or when the user flips the toggle), pipeline writes directly to `output/pending/` and uploader treats `output/pending/` as the publish queue.
- **Alerts log:** failures and recoveries append a line to `logs/alerts.md` (markdown table). User glances at this file once a day. No push notification mechanism in v1.

## Content Safety (v1.1)
- **`better-profanity`** — fast lexical profanity score; baseline gate before LLM checks.
- **Ollama (re-used)** — zero-shot NSFW transcript classifier and "hook accurately summarizes content?" sanity check. Same model as the ranker, just different prompts.
- *Configurable banlist* (substring match on transcript + suggested title) lives in `config.yaml`, not in code, so it can be tuned without redeploys.

## Dedup (v1.1)
- **`imagehash`** — perceptual hash (pHash) on 5 evenly-spaced frames per rendered clip. Stored in `dup_hashes` and matched by Hamming distance across the last 90 days.
- **`chromaprint` / `acoustid-tools`** — audio fingerprint stored alongside pHash for cross-modal dedup. Catches re-uploads where visuals differ but audio is the same clip.

## Time
- **`zoneinfo`** (stdlib) — canonical timezone handling with DST correctness. `publish_at_utc` stored in DB; converted to/from canonical TZ at the boundary.

## Dev Tooling
- **`uv`** or **`pip` + `requirements.txt`** — `uv` is faster but `pip` is fine.
- **`ruff`** — lint + format in one binary.

## What we are *not* using and why
- **MoviePy** — too slow; abstracts away the ffmpeg filtergraph we need fine control over.
- **OpenCV** — not needed; ffmpeg handles all cropping/scaling.
- **APScheduler / Celery / Redis / Postgres** — overkill; Windows Task Scheduler + native YouTube `publishAt` cover the scheduling needs.
- **Learned dedup model (CLIP / video embeddings)** — `imagehash` pHash is sufficient at this scale. A learned model adds GPU dependency + training pipeline for ~zero accuracy gain at 90-day, single-channel scope.
- **Email-on-critical alerting / Discord webhooks** — `logs/alerts.md` is sufficient for v1 (single-user, on-demand reading).
- **TikTok / Instagram SDKs** — out of scope per user.
- **Cloud transcription (AssemblyAI, Deepgram)** — local Whisper is free and accurate enough for forced-alignment on clean TTS audio.
- **ElevenLabs / OpenAI TTS** — Edge TTS is free; paid TTS adds a second paid dependency. Revisit if voice quality is inadequate.
- **Runway Gen-3 / Sora** — Runway is expensive and cinematic-skewed (weak for 3D-animated); Sora is not publicly accessible via API.

## Cost Model (Pivot.6)
- Edge TTS / Whisper / Ollama / ffmpeg / YouTube API / RSS fetching: all **free**
- **OpenRouter Kling 3.0 std:** ~$2/clip at 4 shots × ~4 s. **$5/week budget → 2–3 clips/week** (current cadence). Scales to ~$80/month at 4 clips/day if budget grows.
- **Total: ~$5/week to ~$80/month** depending on cadence. Only paid dependency.

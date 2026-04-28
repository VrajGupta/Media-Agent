# Tools, Libraries & APIs

## Language & Runtime
- **Python 3.11+** — best ecosystem fit for yt-dlp, ffmpeg wrappers, Whisper, and Google API client. Single-language project keeps the 1–2 week build realistic.
- **ffmpeg** (system binary) — every editing operation. Must be on PATH.

## Video Acquisition
- **`yt-dlp`** (Python API) — gold standard for YouTube downloads, handles auto-subs, format selection, throttling. Active maintenance vs deprecated `youtube-dl`.

## Discovery & Upload
- **YouTube Data API v3** via **`google-api-python-client`** — official, documented, supported. Used for `search.list`, `videos.list`, `videos.insert`.
- **`google-auth-oauthlib`** — handles OAuth desktop flow; refresh-token caching means we authenticate once.
- **`requests`** — for the unofficial `mostReplayed` endpoint (`youtubei/v1/player`) when needed.

## Transcription
- **`faster-whisper`** — 4× faster than reference Whisper, supports 8-bit/CTranslate2, runs on CPU acceptably and CUDA fast. Word-level timestamps are first-class. Local = zero API cost.
- Model choice: `large-v3` `int8_float16` on CUDA — fits in 8 GB VRAM with headroom on the RTX 3070.
- Requires CUDA 12.x + cuDNN 9 on the PC; install via `pip install faster-whisper` and the matching NVIDIA runtime libs.

## Clip Selection / Policy / Hook-Sanity (LLM)
- **Ollama** running locally on the PC, model **`qwen2.5:3b-instruct`** (q4_K_M ≈ 2 GB VRAM). Fits the RTX 3070 alongside Whisper. JSON-mode output for structured rubric responses.
- Used for: clip ranking, NSFW transcript classifier, and "does this title accurately summarize the clip?" sanity check.
- Why local: user requirement is a fully free stack. Ollama runs as a background service on Windows, exposes `http://localhost:11434`, handles model loading/unloading, kv-cache prefix reuse covers the prompt-cached-rubric pattern.
- Quality note: 3B-class instruct models are fine for rubric-style scoring and binary classification on short transcripts. If quality is insufficient after first 2-week review, swap to `qwen2.5:7b-instruct` (q4_K_M ≈ 5 GB VRAM) by changing one config line.

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
- **MoviePy** — too slow, abstracts away the ffmpeg filtergraph we need fine control over.
- **OpenCV** — not needed; ffmpeg handles all the cropping/scaling.
- **APScheduler / Celery / Redis / Postgres** — overkill given Windows Task Scheduler + native YouTube `publishAt` cover the scheduling needs.
- **Learned dedup model (CLIP / video embeddings)** — `imagehash` + audio fingerprint is sufficient at this scale (28 clips/week, 90-day window ≈ 360 entries). A learned model would add a GPU dependency and training pipeline for ~zero accuracy gain at 90-day, single-channel scope.
- **Email-on-critical alerting / Discord webhooks** — `logs/alerts.md` is sufficient for v1 (single-user, on-demand reading); push-notification setup is friction without proportional value while the user is actively monitoring the channel.
- **TikTok / Instagram SDKs** — out of scope for v1 per user.
- **Cloud transcription (AssemblyAI, Deepgram)** — local Whisper is good enough and free.

## Cost Model
- yt-dlp / Whisper / Ollama / ffmpeg / YouTube API: all free
- **Total: $0/month.** Stack is fully free per user requirement.

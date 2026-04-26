# Progress Checklist (v1.1)

Update immediately when a task is finished. `[x]` = done, `[~]` = in progress, `[ ]` = not started. Each phase has an **acceptance gate** at the end — do not advance until it passes.

## Phase 0 — Environment & Credentials
- [x] Confirm PC specs — i9-11900H / 32 GB / 1 TB SSD / RTX 3070 laptop GPU
- [x] Decide initial keyword list — Joe Rogan, stoicism, NBA highlights
- [x] Decide gameplay sources — Subway Surfers, Minecraft, GTA (~10 min each)
- [x] Acquire the three gameplay files and place in `data/gameplay/{subway,minecraft,gta}.mp4`
- [x] Confirm Python 3.11+ installed on the PC (3.12.10 venv)
- [x] Install CUDA 12.x + cuDNN 9 runtime on the PC (faster-whisper requirement) — installed via pip wheels (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12==9.*`) inside venv
- [x] Create Python venv on dev machine
- [x] Install ffmpeg with NVENC support and confirm on PATH (Gyan 8.1-full_build, h264_nvenc/hevc_nvenc/av1_nvenc)
- [x] Create Google Cloud project (`media-agent`)
- [x] Enable YouTube Data API v3
- [x] Create OAuth 2.0 Desktop client credentials
- [x] Run first OAuth flow, cache refresh token (`scripts/oauth_first_run.py` → `data/oauth_token.json`)
- [x] Install Ollama on the PC (0.21.2)
- [x] `ollama pull qwen2.5:3b-instruct` (1.9 GB)
- [x] Install chromaprint `fpcalc.exe` 1.6.0 (C:\chromaprint, on PATH) — needed by `pyacoustid`
- [x] Canonical `timezone` = `Asia/Singapore`
- [x] `human_review` = `true` (locked for first 2 weeks)
- [x] No Discord; alerts written to `logs/alerts.md`
- [x] No Anthropic; ranker / NSFW / hook-sanity all run on local Ollama
- [x] Build project skeleton (`src/`, `data/`, `data/gameplay/`, `data/transcripts/`, `output/pending/`, `output/approved/`, `output/rejected/`, `output/dry_run/`, `logs/`, `scripts/`, `config.yaml`, `.env.example`)
- [x] Write `requirements.txt`
- [x] `config.yaml` with all v1.2 tunables
- [x] `src/config_loader/` — pydantic-validated config
- [x] `src/state/schema.sql` + `repository.py` — SQLite DAL
- [x] `src/quota_ledger/` — per-endpoint quota guard
- [x] `src/observability/` — loguru setup + `logs/alerts.md` writer
- [x] `src/bootstrap.py --check` and `--init-db` — env health check
- [x] README.md — setup, layout, human-review workflow, scheduling
- [x] Syntax-check all Phase 0 modules with `py_compile`
- [x] **Acceptance:** `python -m src.bootstrap --check` returns green: ffmpeg + NVENC + CUDA + Whisper load + YT OAuth + Ollama reachable + qwen2.5:3b pulled all OK.

## Phase 1 — Discovery Agent + Quota Ledger
- [ ] SQLite schema (`videos`, `clips`, `uploads`, `runs`, `gameplay_cursor`, `quota_usage`, `dup_hashes`)
- [ ] `state/repository.py` thin DAL
- [ ] `quota_ledger/ledger.py` — `record(endpoint, units)`, `today_total()`, `would_exceed(units, ceiling=9000)`
- [ ] `discovery/search.py` — `search.list` wrapper, `relevanceLanguage=en`, ledger-metered
- [ ] `discovery/enrich.py` — `videos.list` enrichment, ledger-metered
- [ ] Virality scoring function (concrete formula from `executive_plan.md` §5.1)
- [ ] Rolling-30d niche-median views table + recompute step
- [ ] CLI: `python -m src.discovery --keyword "..."`
- [ ] **Acceptance:** ≥30 candidates per keyword; quota ledger shows ≤1,800 units used; rerunning is a no-op (idempotent).

## Phase 2 — Downloader
- [ ] `downloader/ytdlp.py` wrapper
- [ ] Idempotent download with disk-budget check
- [ ] Status transitions in state DB
- [ ] CLI: `python -m src.downloader`
- [ ] **Acceptance:** rerun does zero re-downloads; disk-budget eviction triggers at config threshold.

## Phase 2.5 — Language Detection (NEW)
- [ ] `lang_detect/detect.py` — Whisper on first 60 s, reject `≠ en` w/ confidence ≥ 0.7
- [ ] Status `rejected_language` written to `videos.rejection_reason`
- [ ] CLI: `python -m src.lang_detect`
- [ ] **Acceptance:** correctly rejects 5 hand-picked non-en videos; correctly passes 5 hand-picked en videos.

## Phase 3 — Clip Selection
- [ ] `selector/transcriber.py` (faster-whisper large-v3 int8_float16, CUDA)
- [ ] Transcript caching to `data/transcripts/`
- [ ] `selector/heatmap.py` — `mostReplayed` fetch + per-run hit-rate tracking
- [ ] Heatmap fallback validation: warn at hit-rate <70%; tag `selection_method` on each clip
- [ ] Reviewer spot-check log (`logs/heatmap_qa.md`) for first 2 weeks (5 transcript-only vs 5 heatmap-aided per week)
- [ ] `selector/ranker.py` — Ollama (`qwen2.5:3b-instruct`), JSON-mode, fixed rubric prefix
- [ ] Window slicing (sentence-aligned 30–60 s)
- [ ] CLI: `python -m src.selector`
- [ ] **Acceptance:** first 10 clips manually rated, ≥7 "watchable hook"; transcript-only path ≥6/10.

## Phase 4 — Editor / Reformat
- [ ] `subtitles/ass_writer.py` — word-by-word ASS generator
- [ ] Karaoke styling tuned (font, size, stroke, position)
- [ ] `editor/render.py` — single-pass ffmpeg filtergraph (cut + center-crop top + gameplay vstack + ASS burn + loudnorm + h264_nvenc)
- [ ] Gameplay rotation: round-robin file picker + cursor advance/wrap in `gameplay_cursor`
- [ ] Output to `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4`
- [ ] CLI: `python -m src.editor`
- [ ] **Acceptance:** valid 1080×1920 H.264, ≤60 s, audio at -14 ±0.5 LUFS, subtitle drift ≤50 ms; visual QA on 3 clips.

## Phase 4.5 — Policy Gate + Quality Screen (NEW)
- [ ] `policy_gate/banlist.py` — substring match on transcript + suggested title
- [ ] `policy_gate/profanity.py` — `better-profanity` baseline scoring
- [ ] `policy_gate/nsfw.py` — Ollama zero-shot transcript classifier
- [ ] `policy_gate/hook_sanity.py` — Ollama "does title accurately summarize clip?" rater (reject < 3/5)
- [ ] `quality_screen/density.py` — speech_density ≥ 1.5 words/sec
- [ ] `quality_screen/confidence.py` — mean Whisper word-conf ≥ 0.6
- [ ] `quality_screen/dedup.py` — `imagehash` pHash on 5 frames + audio fingerprint via `chromaprint`/`acoustid-tools`; compare to `dup_hashes` last-90-day window
- [ ] `quality_screen/duration.py` — final clip ∈ [25, 65] s
- [ ] `policy_gate` runs twice (post-select + pre-upload)
- [ ] `human_review` config knob — when `true`, rendered clips land in `output/pending/`; user moves to `output/approved/` to publish. When `false`, uploader treats `output/pending/` as the publish queue.
- [ ] CLI: `python -m src.policy_gate --clip-id <id>` and `python -m src.quality_screen --clip-id <id>`
- [ ] **Acceptance:** banned-topic test inputs all caught; legitimate test set passes; zero false-positive duplicate matches on 20 hand-picked distinct clips.

## Phase 5 — Uploader
- [ ] OAuth refresh-token loader
- [ ] `uploader/youtube.py` resumable insert with `status.privacyStatus=private` + `status.publishAt`
- [ ] `--dry-run` mode writes insert body to `output/dry_run/{clip_id}.json`, no API call
- [ ] Future-too-near rule: pad `publish_at_utc` < `now + 20 min` → `now + 20 min`
- [ ] Quota ledger pre-flight (abort if next call > 9,000 units today)
- [ ] Title/description/tag templating (`#Shorts`, `categoryId=24`, `selfDeclaredMadeForKids=false`)
- [ ] CLI: `python -m src.uploader --clip-id <id> [--dry-run]`
- [ ] **Acceptance:** `--dry-run` produces a valid insert body offline; one real upload to test channel publishes at exactly the requested `publishAt` in canonical TZ.

## Phase 6 — Orchestrator (no daemon)
- [ ] `slot_planner.py` — assigns `publish_at_utc` evenly across `days_per_run` × `upload_slots`; TZ-aware via `zoneinfo`
- [ ] `weekly_run.py` — discovery → download → lang_detect → select → policy_gate → render → quality_screen → slot_plan → retention
- [ ] `daily_upload.py` — pulls today's clips, re-runs policy_gate, uploads with `publishAt`, respects quota guard
- [ ] Missed-slot recovery: stale `publish_at_utc` padded to `now + 20 min`, logged as `recovered_slot`, Discord-alerted
- [ ] `bootstrap.py` — single-clip end-to-end smoke test
- [ ] `bootstrap.py --check` — env health check
- [ ] Windows Task Scheduler XML exports under `scripts/` (`weekly_run.xml`, `daily_upload.xml`)
- [ ] First full weekly run on the PC; verify queue depth = `clips_per_day × days_per_run`
- [ ] First week of daily uploads; verify scheduled publish times honored
- [ ] Missed-slot recovery exercised by deliberately skipping a day
- [ ] **Acceptance:** weekly_run produces `clips_per_day × days_per_run` ready clips; daily_upload publishes correctly; missed-slot path verified.

## Phase 7 — Hardening
- [ ] `loguru` config + log rotation (daily, 30-day retention)
- [ ] `tenacity` retry with backoff on all API calls
- [ ] `observability/alerts.py` — append-only writer for `logs/alerts.md`
- [ ] Alert rows wired to: weekly run finished, run failure, quota > 80%, upload rejected, missed-slot recovery
- [ ] Per-run summary writer (`logs/runs.md`)
- [ ] `retention/cleanup.py`:
  - [ ] `data/raw/*.mp4` → 14-day TTL post-download or post-upload-of-derived
  - [ ] `data/transcripts/*.json` → 90-day TTL
  - [ ] `output/pending/*.mp4` and `output/approved/*.mp4` → delete 7 days post-`uploaded`
  - [ ] `output/rejected/*.mp4` → delete after 30 days
  - [ ] `dup_hashes` rows → 90-day TTL
  - [ ] `quota_usage` rows → 90-day TTL
  - [ ] Monthly SQLite `VACUUM`
- [ ] All paths/tunables read from `config.yaml` (`clips_per_day`, `days_per_run`, `upload_slots`, `timezone`, `human_review`, `banlist`, `ollama_model`, `whisper_model`)
- [ ] README with PC setup + Task Scheduler import steps
- [ ] Document quota-increase audit form steps in README (deferred action item)
- [ ] **Acceptance:** logs rotate; Discord alerts fire on synthetic triggers; cleanup deletes correct files; double-running `weekly_run` is a no-op.

## Phase 8 — Stretch (deferred)
- [ ] Subject tracking (face/saliency-aware crop) replacing center-crop
- [ ] Thumbnail auto-generation
- [ ] A/B title testing
- [ ] TikTok / Reels integration
- [ ] Web dashboard
- [ ] File YouTube quota-increase audit form

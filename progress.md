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
- [x] SQLite schema (`videos`, `clips`, `uploads`, `runs`, `gameplay_cursor`, `quota_usage`, `dup_hashes`) — landed in Phase 0; Phase 1 added `discovery_attempts` for outcome-independent idempotency.
- [x] `state/repository.py` thin DAL — Phase 1 appended `discovery_upsert_video` (status-preserving), `historical_views_for_keyword`, `niche_median_views`, `upsert_niche_baseline`, `record_discovery_attempt`, `is_in_cooldown`.
- [x] `quota_ledger/ledger.py` — Phase 0 module wired into discovery via conservative recording rule (`HttpError` → record; `ConnectionError`/`socket.timeout` → no record).
- [x] `discovery/search.py` — paginated `search.list` wrapper, `relevanceLanguage=en`, `videoDuration=any`, ledger-metered.
- [x] `discovery/enrich.py` — `videos.list` batch enrichment (50 IDs/batch), parses ISO 8601 duration, handles hidden likeCount/commentCount/viewCount, ledger-metered.
- [x] Virality scoring function — `discovery/virality.py`, exact formula from `executive_plan.md` §5.1, defensively clamps zero/negative inputs.
- [x] Rolling-30d niche-median views — `niche_baselines` table populated via `compute_niche_median(fresh batch + last-30d historical)`; cold-start safe.
- [x] CLI: `python -m src.discovery [--keyword K] [--force] [--dry-run] [--config alt.yaml]`.
- [x] `src/integrations/youtube.py` — shared OAuth client (used by uploader in Phase 5).
- [x] `tests/` — 31 pytest tests covering virality formula, ISO 8601 duration, missing-stats handling, status-preserving upsert, cooldown guard, conservative quota recording (record on HTTP response, skip on ConnectionError, no record on preflight failure).
- [x] **Acceptance (live, 2026-04-28):** Joe Rogan=35, stoicism=41, NBA highlights=80 candidates (gate ≥30); per-run quota max 504 units (gate ≤1,800); cooldown rerun produced 3 skip lines and 0 new quota rows; force-rerun preserved a row marked 'downloaded' (Jvv1g3QMLL0) while refreshing its stats.

### Phase 1 live verification (run when ready)
1. `python -m src.discovery --dry-run --keyword "Joe Rogan"` — sanity-check pool quality before committing rows.
2. `python -m src.discovery --keyword "Joe Rogan"`, then `--keyword "stoicism"`, then `--keyword "NBA highlights"`.
3. `sqlite3 data/state.db "SELECT keyword, COUNT(*) FROM videos GROUP BY keyword;"` → expect ≥30 per keyword.
4. `sqlite3 data/state.db "SELECT date, endpoint, SUM(units) FROM quota_usage GROUP BY date, endpoint;"` → expect total ≤1,800 (predicted ~600).
5. Re-run `python -m src.discovery` immediately → expect 3 cooldown-skip lines, zero new `quota_usage` rows.
6. `UPDATE videos SET status='downloaded' WHERE video_id=<one>;` then `python -m src.discovery --force --keyword "Joe Rogan"` → confirm that row's `status` is still `downloaded` and `views`/`updated_at` got refreshed.

## Phase 2 — Downloader
- [x] `downloader/ytdlp_runner.py` — probe (no-download metadata read) + `download_one` with strict 720p–1080p band, sidecar cleanup helper.
- [x] Idempotent download — three-layer guard: probe rejects no-720p sources without bandwidth burn; existing-file + status-discovered auto-repairs to `downloaded`; second run is a clean no-op.
- [x] Status transitions: `discovered → downloaded | rejected_format | rejected_download`. Schema comment updated; `status` column is free-form TEXT (no migration needed).
- [x] `disk_budget.py` — soft cap (50 GB), hard cap (100 GB), free-disk safety floor (5 GB). Eviction loop deletes oldest fully-uploaded raw mp4s; refuses to delete videos with zero clips or non-uploaded clips. **Phase 2 caveat:** eviction has zero eligible victims until Phase 5 starts uploading clips — the hard cap protects the disk meanwhile.
- [x] Post-download hard-cap re-check unlinks oversized writes and marks `rejected_download`.
- [x] CLI: `python -m src.downloader [--video-id <id>] [--config alt.yaml]` with predictable semantics for missing/already-rejected/already-downloaded/file-missing rows.
- [x] `tests/` — 9 new tests (disk_budget x8, format selector x2, idempotency x3, status transitions x4, eviction safety x3, hard-cap post-download x1, soft-cap no-victims x1, sidecar cleanup x3, repo evictable matrix). 56 total tests green.
- [x] **Acceptance (live, 2026-04-29):** full sweep produced 156 downloaded / 1 rejected_download / 2 rejected_format (159 candidates total, all resolved); 54.7 GB used (under 100 GB hard cap); idempotent rerun was a clean no-op; eviction smoke test deleted exactly 1 fake-uploaded video and freed 647 MB.

### Phase 2 live verification (run when ready)
1. `python -m src.bootstrap --init-db` (idempotent — schema-comment-only update).
2. `pytest tests/` — expect 56 passing.
3. **First single-video download:** `python -m src.downloader --video-id <one Joe Rogan id>` — confirm `data/raw/<id>.mp4` is 100–500 MB and the row's status is `downloaded`.
4. **Idempotent rerun:** same command immediately. Expect `skip: already downloaded`, no new file write.
5. **Crash-gap repair:** `UPDATE videos SET status='discovered' WHERE video_id='<that id>';` then re-run the same command. Expect `repaired orphan`, status flips back to `downloaded`, no re-fetch.
6. **Full sweep:** `python -m src.downloader`. Expect ~145–155 sequential downloads over 15–30 minutes. Status counts: `downloaded ≈ 145–155`, `rejected_format ≈ 0–6`, `rejected_download ≈ 0–5`.
7. **Eviction smoke test (synthetic):** insert a fake `clips` row marked `uploaded` for one downloaded video, then re-run the downloader; expect the eviction loop log to free that file.

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
- [ ] Missed-slot recovery: stale `publish_at_utc` padded to `now + 20 min`, logged as `recovered_slot`, row appended to `logs/alerts.md`
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
- [ ] **Acceptance:** logs rotate; `logs/alerts.md` rows appear on synthetic triggers (run failure, quota > 80%, upload reject, missed-slot recovery); cleanup deletes correct files; double-running `weekly_run` is a no-op.

## Phase 8 — Stretch (deferred)
- [ ] Subject tracking (face/saliency-aware crop) replacing center-crop
- [ ] Thumbnail auto-generation
- [ ] A/B title testing
- [ ] TikTok / Reels integration
- [ ] Web dashboard
- [ ] File YouTube quota-increase audit form

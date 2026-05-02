# Progress Checklist (v1.1)

Update immediately when a task is finished. `[x]` = done, `[~]` = in progress, `[ ]` = not started. Each phase has an **acceptance gate** at the end — do not advance until it passes.

> **Dev environment:** code is developed AND run on the user's Windows laptop (i9-11900H + RTX 3070, single machine). Earlier docs implied a Mac dev host with code transfer to the PC — that's stale; the project moved to Windows-only development. Live verification commands run directly here, no sync step.

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
- [x] `lang_detect/runner.py` — Whisper on first encoder window, reject `≠ en` w/ confidence ≥ 0.7. Module name follows discovery/runner.py + downloader/runner.py convention; we don't iterate the segments generator, so Whisper performs language detection on the initial encoder window without full transcription.
- [x] Status `rejected_language` written to `videos.rejection_reason` (e.g. `lang=es, conf=0.92`); pass writes status `lang_ok` (new value, schema-comment-only update — status column is free-form TEXT).
- [x] CLI: `python -m src.lang_detect [--video-id <id>] [--force] [--dry-run] [--config alt.yaml]`. Single-video path preflights row status before constructing the Whisper model so a rerun on `lang_ok` exits without paying the model load. Batch path raises `LangDetectModelLoadError` on model-load failure; CLI logs + appends one rolled-up alert + exits 1. Per-video inference errors leave the row at `downloaded` for next-run retry; rolled-up alert at run end.
- [x] `tests/` — 14 new pytest tests (verdict matrix, threshold boundary, status preflight + force, missing file, inference error, dry-run, zero-candidate no-load, model-load failure). Whisper is monkeypatched at `src.lang_detect.runner.WhisperModel` — no GPU/CUDA touched in tests. 70 total tests green.
- [x] `src/state/repository.py` — added `videos_with_statuses(statuses)` helper (parameterized `IN (?, ?, ...)`, returns `[]` on empty input) for the `--force` batch path.
- [x] `config.yaml` + `Config` — added `lang_detect_threshold: 0.7` and `lang_detect_target_lang: "en"` with typed defaults.
- [x] **Acceptance (live, 2026-04-30):** 154 downloaded videos swept; 148 → `lang_ok`, 6 → `rejected_language`. All 6 rejections correctly classified by Whisper: my (Burmese, conf=0.99), ta (Tamil, conf=0.99), tl (Tagalog, conf=1.00), pt (Portuguese, conf=1.00), hi (Hindi, conf=0.99 — title was English but audio was Hindi, exact false-positive Phase 2.5 was built to catch), ur (Urdu, conf=0.80). Single-video reruns confirm idempotent skip path: 1.17 s wall-clock with no Whisper load (well under 2 s gate). DLL preload fix landed in [src/lang_detect/runner.py](src/lang_detect/runner.py) for `cublas64_12.dll` / `cudnn64_9.dll` (`os.add_dll_directory` + `ctypes.WinDLL` preload — required because ctranslate2's compiled extension does not honor `add_dll_directory` alone).

### Phase 2.5 live verification (run when ready)
1. `pytest tests/` — expect 70 passing.
2. `python -m src.lang_detect --video-id <one Joe Rogan id known English>` → `lang_ok`; agent.log shows `detected=en, conf=0.9x`.
3. `python -m src.lang_detect --video-id <one known non-English candidate>` → `rejected_language`; `rejection_reason` contains `lang=…, conf=…`.
4. Re-run #2 immediately → exits with `skip: skipped_already_lang_ok`, **no Whisper load** (verify wall-clock < 2 s).
5. Full sweep: `python -m src.lang_detect`. Expect most of the 156 downloaded rows → `lang_ok`, a handful → `rejected_language`. Wall-clock ~10 min on RTX 3070.
6. `sqlite3 data/state.db "SELECT status, COUNT(*) FROM videos GROUP BY status;"` → `lang_ok + rejected_language ≈ 156`.
7. **Acceptance gate:** manually pick 5 known-English and 5 known-non-English videos, force-run lang_detect on each, verify all 10 verdicts are correct.

## Phase 3 — Clip Selection
> Phase 2.5 covered language detection. Phase 3 starts at `status='lang_ok'`, ends at `status='selected'`. Status flow: `lang_ok → transcribed → selected`. Stops short of policy_gate (Phase 4.5) and editor (Phase 4).

### Module skeleton
- [x] `src/selector/__init__.py` re-exports.
- [x] `src/selector/__main__.py` — CLI: `--video-id`, `--force` (re-rank from cache), `--retranscribe` (also re-pay Whisper), `--dry-run`, `--config`.
- [x] `src/selector/runner.py` — `_preload_nvidia_dlls()` at top (mirrors [src/lang_detect/runner.py:22-56](src/lang_detect/runner.py#L22-L56)); `select_one_video`, `run_all`, `SelectorResult`, `SelectorOutcome` enum.

### Transcriber (`selector/transcriber.py`)
- [x] Full-video Whisper via `faster-whisper` `large-v3` `int8_float16` on CUDA. Iterate the segments generator.
- [x] Word-level timestamps enabled (`word_timestamps=True`) so Phase 4 ASS subtitles can read straight from cache.
- [x] Cache JSON written to `data/transcripts/{video_id}.json` with `{schema_version: 1, video_id, model, compute_type, duration_seconds, language, language_probability, segments[ {start,end,text,words[ {start,end,word,probability} ]} ]}`.
- [x] **Atomic write**: serialize to `data/transcripts/{video_id}.json.tmp`, then `os.replace()` to final. Inference failure means no temp file is promoted; status stays `lang_ok` for next-run retry.
- [x] Cache invalidation: silently re-transcribe + overwrite when cached `model` or `compute_type` ≠ `cfg.whisper_*`.
- [x] Fail-soft on inference error: leave row at `lang_ok`, no transcript file written, error rolled up into the run-end alert.

### Heatmap (`selector/heatmap.py`)
- [x] `POST https://www.youtube.com/youtubei/v1/next` (the watch-page renderer; `/player` returns a stripped-down payload without heatmap data — discovered during live verification 2026-04-30 and patched). Hard-coded module-level constant: `clientName=WEB`, `clientVersion=2.20241201.00.00`, `hl=en`, `gl=US`, plus `playbackContext.contentPlaybackContext.currentUrl=/watch?v=<id>`.
- [x] 5 s timeout. One retry on `requests.ConnectionError` or 5xx response. No fixed sleep between calls.
- [x] Parser walks `frameworkUpdates.entityBatchUpdate.mutations[].payload.macroMarkersListEntity.markersList.markers[]` → list of `(start_s, duration_s, intensity)`. Each marker is `{startMillis: str, durationMillis: str, intensityScoreNormalized: float}`. Multi-mutation payloads are walked in full; only mutations carrying `macroMarkersListEntity` contribute markers.
- [x] **NOT** routed through `QuotaLedger` — Innertube is unbilled.
- [x] Fail-open: 4xx / 5xx / network error / missing JSON path → return `None`, log INFO, count as miss in run-level `heatmap_hit_rate`.
- [x] Per-run aggregate: if `heatmap_hit_rate < 0.70`, append a single rolled-up warning row to `logs/alerts.md` at run end (kind=`heatmap_low_hit_rate`).
- [x] Per-clip: `selection_method='heatmap_aided'` iff window `[start_s, end_s]` overlaps any top-5 heat marker; else `'transcript_only'`.

### Window slicing (`selector/windows.py`)
- [x] **Baseline non-overlapping walk**: accumulate consecutive Whisper segments until cumulative duration ∈ [`clip_min_seconds`, `clip_max_seconds`]; emit; reset.
- [x] **Heatmap-centered candidates**: for each top-5 heat marker, build a window centered on the marker midpoint, expand outward to nearest sentence/segment boundaries until duration ∈ [30, 60]. Skip if no boundary set yields a valid duration.
- [x] Merge + dedup: windows whose `(start_s, end_s)` are within 1 s collapse; prefer `source="heatmap_centered"` on collision.
- [x] Each window: `{candidate_id, start_s, end_s, text, words, heatmap_peak: bool, source: "baseline" | "heatmap_centered"}`. `candidate_id = "c{0..N}"` per video — only this is exposed to the LLM.
- [x] Edge cases: video shorter than `clip_min_seconds` total → zero windows, video skipped.

### Ranker (`selector/ranker.py`)
- [x] `POST http://localhost:11434/api/chat`, `format: "json"`, `keep_alive: "10m"`.
- [x] Fixed system prompt = scoring rubric (hook strength, payoff, self-contained, controversy/curiosity, no slow intro). Identical bytes per call so Ollama prefix kv-cache reuses it.
- [x] One call per video; user message contains all candidate windows labeled by `candidate_id`.
- [x] Schema returned: `{"clips":[{"candidate_id","hook","suggested_title","score"}, ...]}` with N = `cfg.clips_per_video`. **LLM returns IDs, never raw timestamps**; selector maps IDs back to canonical `(start_s, end_s)` locally.
- [x] Validation: every returned `candidate_id` must exist in this video's window list and be unique. Unknown / duplicated / missing → retry once with stricter user prompt; persistent → leave at `transcribed`, alert at run end.
- [x] Malformed JSON → retry once; persistent → leave at `transcribed`, alert at run end.
- [x] Ollama unreachable → leave at `transcribed`, alert at run end, proceed with next video.
- [x] `OLLAMA_HOST` env override respected (mirrors [src/bootstrap.py:153](src/bootstrap.py#L153)).

### Persistence
- [x] `clip_id = f"{video_id}_{int(start_s)}_{int(end_s)}"`.
- [x] **New helper `repo.upsert_selector_clip(...)`** — touches only selector-owned columns: `start_s, end_s, hook, suggested_title, selection_method, status, rejection_reason, updated_at`. Does NOT clobber `publish_at_utc`, `publish_slot_local`, `output_path`, `youtube_video_id`, `title_slug` once Phases 4–6 have populated them. Verified by `tests/test_selector_upsert.py::test_rerank_preserves_downstream_columns` and `tests/test_selector_runner.py::test_force_preserves_downstream_columns`.
- [x] Per-video transactionality:
  1. Whisper → atomic transcript write.
  2. `set_video_status(video_id, 'transcribed')` (own transaction).
  3. Heatmap fetch (no DB write).
  4. Rank + validate candidate IDs.
  5. Inside `repo.tx()`: `upsert_selector_clip` for each chosen window, then `set_video_status(video_id, 'selected')`.
  A crash between steps leaves the video at `lang_ok` or `transcribed`; next run resumes there.
- [x] Phase 3 leaves `publish_at_utc`, `publish_slot_local`, `output_path`, `youtube_video_id`, `title_slug` NULL.

### Reviewer spot-check
- [x] At end of `run_all`, append a fresh template to `logs/heatmap_qa.md`: markdown header (created if missing) + up to 5 transcript-only + up to 5 heatmap-aided rows from this run, columns `clip_id | selection_method | hook | rating_1_to_5 | notes`. Skipped if no clips selected.

### Tests (55 new → 129 total)
Split across:
- [x] `tests/test_selector_upsert.py` (4 tests) — selector-scoped upsert preserves downstream columns.
- [x] `tests/test_selector_transcriber.py` (10 tests) — cache hit/miss matrix, atomic write, mid-stream Whisper failure leaves no temp file.
- [x] `tests/test_selector_windows.py` (11 tests) — baseline + heatmap-centered + dedup + candidate IDs.
- [x] `tests/test_selector_heatmap.py` (9 tests) — `/next` endpoint, parser walks `frameworkUpdates...macroMarkersListEntity.markersList.markers[]`, multi-mutation handling, fail-open, retry on connection error / 5xx.
- [x] `tests/test_selector_ranker.py` (8 tests) — candidate_id validation, retry, malformed JSON, network failures.
- [x] `tests/test_selector_runner.py` (17 tests) — full orchestration: status preflight, --force / --retranscribe semantics, atomic-transcript invariant, downstream-column preservation under --force, heatmap hit/miss + run-level alert, ranker error → status='transcribed' + alert, dry-run, empty candidate set tripwire, model load failure.

### Acceptance
- [x] `pytest tests/` — 129 passing (74 prior + 55 Phase 3).
- [x] Re-run on a `selected` row without `--force` exits via `skipped_already_selected` with no Whisper model load (verified by `test_already_selected_no_force_skips` with `TripwireWhisperModel`).
- [ ] **Live, post-merge:** First 10 clips manually rated, ≥ 7 "watchable hook"; transcript-only path ≥ 6/10.
- [ ] **Live, post-merge:** `heatmap_hit_rate ≥ 70 %` on the 148-video sweep; otherwise the rolled-up alert row appears in `logs/alerts.md`.

### Phase 3 live verification (run when ready)
1. `pytest tests/` — expect 128 passing.
2. `python -m src.selector --video-id <one Joe Rogan id>` → 1 transcript JSON written, 2 clip rows inserted, `videos.status='selected'`. Wall-clock ~2–5 min.
3. Re-run #2 immediately → `skip: skipped_already_selected`, no Whisper load, < 2 s.
4. `python -m src.selector --video-id <same id> --force` → re-ranks from cached transcript, no Whisper load, < 30 s. Clip rows replaced.
5. `python -m src.selector --video-id <same id> --retranscribe` → re-pays Whisper, transcript file rewritten.
6. Heatmap-miss simulation: temporarily set hosts entry blocking `youtube.com`, run a single video → `selection_method='transcript_only'`, no exception. Restore hosts.
7. Full sweep: `python -m src.selector`. Expect 148 transcripts written, ~296 clip rows (148 × 2). Wall-clock ~3–5 h.
8. `sqlite3 data/state.db "SELECT selection_method, COUNT(*) FROM clips GROUP BY selection_method;"` — expect ≥ 70% `heatmap_aided`; if not, verify the rolled-up alert row in `logs/alerts.md`.
9. **Acceptance gate**: pick 10 random clips, open source mp4 at `(start_s, end_s)`, rate "watchable hook" 1–5. Need ≥ 7 with rating ≥ 3.

## Phase 4 — Editor / Reformat
> Status flow: `selected → rendered`. New status value `rejected_render` for irrecoverable source/probe failures. Output file lives at `output/pending/__unscheduled__{clip_id}__{title_slug}.mp4`; Phase 6 (slot_planner) will rename in place once `publish_at_utc` is assigned.

### Module skeleton
- [x] `src/subtitles/__init__.py` + `src/subtitles/ass_writer.py` — Whisper words → ASS karaoke (clip-relative timing, drift correction, non-overlapping 1–2 word chunks).
- [x] `src/editor/__init__.py` + `src/editor/__main__.py` — CLI: `--clip-id`, `--force` (gated against scheduled/uploaded), `--retranscribe` not applicable, `--dry-run`, `--config`.
- [x] `src/editor/runner.py` — `render_one_clip`, `run_all`, `EditorOutcome` enum.
- [x] `src/editor/ffmpeg_runner.py` — argv builder + filtergraph builder + Windows-aware ASS filter-path escape.
- [x] `src/editor/gameplay.py` — `reserve_next_segment` / `commit_advance` (read-then-write split so ffmpeg never holds a transaction).
- [x] `src/editor/slug.py` — title → filesystem slug with deterministic 4-char hash suffix from `clip_id`.

### Subtitles (`subtitles/ass_writer.py`)
- [x] Non-overlapping 1–2 word chunks (no sliding pair). Line *n* `End` == Line *n+1* `Start` exactly.
- [x] Clip-relative timing: subtract `clip.start_s` from every word; clip boundaries to `[0, end-start]`.
- [x] `\k` centisecond rounding with carry-the-remainder drift correction (≤50 ms over 60 s).
- [x] Fast-speech fallback (>4 wps) drops to 1-word chunks.
- [x] ASS dialogue escape: `\ { }` only. Apostrophe NOT escaped (handled by ffmpeg filter-path escape, separate concern).
- [x] Style: Impact 120 pt, white fill, 8 px black border, yellow active-word highlight via `\1c&H0000FFFF&` override, `Alignment 5` + `\pos(540, 1340)` for center-anchored placement ~70% down a 1920-tall canvas.

### ffmpeg invocation (`editor/ffmpeg_runner.py`)
- [x] Filtergraph: identical scale-fill + center-crop chain on both panes (`scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960`). No preliminary aspect-strip crop.
- [x] `vstack=inputs=2,fps=30` for the 1080×1920 stack.
- [x] `ass=<escaped_path>` filter (the dedicated libass filter, not `subtitles=`).
- [x] One-pass `loudnorm=I=-14:LRA=11:TP=-1.0,aresample=48000` on source audio only (gameplay muted).
- [x] `-c:v h264_nvenc -preset p5 -cq 23 -c:a aac -b:a 128k -movflags +faststart`.
- [x] `-ss` / `-t` are command args BEFORE each `-i`, never inside the filtergraph.
- [x] argv built as `list[str]`, passed to `subprocess.run(shell=False)`. Never a shell string.
- [x] `escape_ass_filter_path`: doubles `\`, escapes `:` `,` `'`, wraps in single quotes (Windows-aware).
- [x] `ffprobe_duration_seconds(path)` mirrors the pattern from [src/downloader/ytdlp_runner.py](src/downloader/ytdlp_runner.py)`._ffprobe_height`.

### Gameplay rotation (`editor/gameplay.py`)
- [x] Read-then-write split: `reserve_next_segment` is read-only and returns the chosen `(file, offset)` without writing. `commit_advance` runs only after render success and is wrapped by the caller in `repo.tx()` together with `set_clip_status('rendered', ...)` — atomic.
- [x] Round-robin via `gameplay_pointer.next_index`; cursor advance via `gameplay_cursor.last_offset_s`.
- [x] Cursor wraps to 0 when `last_offset_s + clip_duration + 1 s safety > file_duration_s`.
- [x] `file_duration_s` probed via ffprobe once per file, cached in `gameplay_cursor` on first commit.
- [x] Render failure leaves pointer + cursor untouched (no double-consumption).

### Filename strategy
- [x] `output/pending/__unscheduled__{clip_id}__{title_slug}.mp4` — explicit signal that Phase 6 hasn't scheduled this clip yet.
- [x] Phase 4 stores the unscheduled path in `clips.output_path`. Phase 6 will rename in place to `{YYYY-MM-DD}__slot_{HHMM}__{title_slug}.mp4` and update `output_path` in the same transaction.
- [x] `slug.py`: lowercase, replace non-alphanum runs with `_`, truncate at word boundary to 80 chars minus a 4-char `sha1(clip_id)[:4]` suffix. Suffix guarantees no collision between clips that share a normalized title; suffix is stable across reruns.

### Idempotency (3 layers)
- [x] Status preflight: `rendered` skips (unless `--force`); `selected` proceeds.
- [x] `--force` is gated: only re-renders if `status='rendered'` AND `publish_at_utc IS NULL` AND `youtube_video_id IS NULL`. Scheduled or uploaded clips return `skipped_locked`.
- [x] Atomic file write: render to `<output>.tmp.mp4`, `os.replace()` only on ffmpeg exit code 0 + size > 0. ffmpeg failure / 0-byte output unlinks tmp, leaves clip at `selected`.

### Persistence
- [x] `set_clip_status(clip_id, 'rendered', output_path=..., title_slug=...)` reuses the existing `**extra` mechanism (no new DAL method needed). Inside the post-render transaction together with `gameplay.commit_advance`.
- [x] Three new repository helpers: `read_gameplay_pointer`, `read_gameplay_cursor`, `advance_gameplay_state` (multi-statement, transaction-bare; caller wraps in `repo.tx()`).
- [x] Schema comment update: `clips.status` enum extended with `rejected_render`.

### Tests (47 new → 182 total)
- [x] `tests/test_editor_slug.py` (7) — short title, special chars, truncation at word boundary, distinct hash suffixes for distinct clip_ids, stable suffix on rerun, empty/garbage-only fallback to `untitled`.
- [x] `tests/test_subtitles_ass.py` (10) — single word, non-overlapping chunks (line.End == next.Start exactly), fast-speech fallback to 1-word, drift ≤50 ms over 60 s synthetic, words clipped to clip window, escape `\ { }` but NOT apostrophe, empty words → header only, Alignment 5 in style.
- [x] `tests/test_editor_ffmpeg.py` (9) — Windows path escape, posix path escape, comma+apostrophe escape, filtergraph contents, regression on `crop=in_w:in_h*9/16` (must NOT appear), top/bot chains identical, argv is list, `-ss` before each `-i` and never inside filtergraph, NVENC settings present.
- [x] `tests/test_editor_gameplay.py` (8) — round-robin 0→1→2→0, cursor advance, wrap at near-end, ffprobe called once per file, render failure does not advance, empty pool → None, missing file → None, unprobeable file → None.
- [x] `tests/test_editor_runner.py` (13) — render success flips status + advances gameplay, status preflight matrix, `--force` re-renders unscheduled, `--force` blocked for scheduled / uploaded, source missing → `rejected_render`, missing transcript → `error_no_transcript` and unchanged status, ffmpeg failure leaves `selected` and gameplay unadvanced, 0-byte output treated as failure, dry-run no subprocess + no DB writes + argv printed, `run_all` filters out non-`selected`, `run_all` empty returns empty.

### Acceptance
- [x] `pytest tests/` — 182 passing (135 prior + 47 Phase 4).
- [x] **Live single-clip render** on `WHibDIQHeaY_31_65` (33.6 s clip): produced a 1080×1920 H.264 39.5 MB mp4 in 23.7 s wall-clock with NVENC. ffprobe verified `codec_name=h264, width=1080, height=1920, r_frame_rate=30/1`, duration 33.60 s (within 0.1 s of `end_s - start_s = 33.58 s`).
- [x] **Idempotent skip**: re-running `--clip-id WHibDIQHeaY_31_65` exits in 1.1 s with `skipped_already_rendered`, no ffmpeg invocation.
- [x] **Dry-run**: prints filtergraph + argv, with the libass `ass=` argument correctly escaped for the Windows ASS path (`'C\:\\Users\\cryptix\\AppData\\Local\\Temp\\...\\WHibDIQHeaY_31_65.ass'`). No subprocess, no file written, no DB write.
- [ ] **Live, post-merge:** Audio integrated loudness within ±0.5 of -14 LUFS (verify via `ffmpeg -af loudnorm=print_format=json` after a few real renders).
- [ ] **Live, post-merge:** Visual QA on 3 random rendered clips: top half source video centered, bottom half gameplay, subtitles word-by-word with no overlap and ≤50 ms drift.
- [ ] **Live, post-merge:** Full editor sweep across all `selected` clips after the Phase 3 sweep finishes.

## Phase 4.5 — Policy Gate + Quality Screen
> Status flow: `selected → policy_pass | rejected_policy` (post-select gate); `rendered → quality_pass | rejected_quality` (post-render screen, rejected files moved to `output/rejected/`). Two new clip status values, comment-only schema update. The editor's input filter flipped from `status='selected'` to `status='policy_pass'` so rejected_policy clips physically can't reach Phase 4.

### Shared helpers
- [x] `src/transcripts/clip_text.py` — `words_in_clip_window` (intersection-with-clipping; matches [src/subtitles/ass_writer.py:87-99](src/subtitles/ass_writer.py#L87) exactly) + `clip_text_from_words`. Both policy_gate and quality_screen consume this. 3 tests.
- [x] `tests/conftest.py::StubConfig` extended with `banlist`, `hook_sanity_min_score`, `profanity_max_score`, `min_speech_density`, `min_word_confidence`, `dedup_lookback_days`, `phash_min_hamming`, `ollama_model`, and `paths.rejected_dir`.
- [x] `src/state/repository.py` — `clips_for_policy_gate`, `clips_for_quality_screen`, `recent_dup_hashes(days)` returns `(clip_id, phash, audio_fp)`, `insert_dup_hash_rows(rows)` uses `INSERT OR IGNORE`.
- [x] `src/state/schema.sql` — comment-only update on `clips.status` line adds `policy_pass`, `quality_pass`.

### Pure evaluator vs. stateful runner (policy_gate)
- [x] `src/policy_gate/evaluator.py::evaluate_clip_policy(cfg, clip_text, suggested_title, *, ollama_host=None) -> PolicyVerdict` — pure, no DB / no file I/O. Short-circuits on first content failure. Used directly by Phase 5's pre-upload re-check (forward-compatible API).
- [x] `src/policy_gate/runner.py::gate_one_clip` — stateful; loads transcript, builds clip-window text, calls evaluator, applies `selected → policy_pass | rejected_policy` transition.

### Per-check modules
- [x] `src/policy_gate/banlist.py` — case-insensitive word-boundary substring match (multi-word phrases via `\s+` join). Cheap; runs first.
- [x] `src/policy_gate/profanity.py` — `better_profanity` percentage-of-flagged-words score. Compared to `cfg.profanity_max_score`.
- [x] `src/policy_gate/nsfw.py` — Ollama JSON-mode classifier; rejects on `label='nsfw' AND score >= 0.5`. Mirror of [src/selector/ranker.py](src/selector/ranker.py) HTTP/retry/keep-alive pattern. **Fail-soft on infrastructure failures** (network down, malformed JSON, **and unknown labels** after retry) — returns `label='infrastructure_failed'`.
- [x] `src/policy_gate/hook_sanity.py` — Ollama 1-5 rater; rejects on `score < cfg.hook_sanity_min_score` (default 3). Same fail-soft rules.
- [x] `src/quality_screen/density.py` — `len(words_in_clip_window) / clip_duration` ≥ `cfg.min_speech_density` (1.5 wps). Defensively returns 0.0 for nonpositive duration.
- [x] `src/quality_screen/confidence.py` — mean of `word.probability` across the same window; missing field defaults to 0.0 (= reject signal).
- [x] `src/quality_screen/duration.py` — wraps `editor.ffmpeg_runner.ffprobe_duration_seconds`; rejects outside [25, 65] s. Probe failure (None) is the foundational fail-soft — runner aborts the screen.
- [x] `src/quality_screen/loudness.py` — `ffmpeg -af loudnorm=print_format=json -f null -`; parses trailing JSON block from stderr (`_JSON_BLOCK_RE`). **Three-tier classification**: `pass` (±0.5 LUFS) / `warn` (±0.5..±1.5, alert appended) / `reject` (>±1.5). Subprocess error or parse failure = fail-soft pass-with-alert.
- [x] `src/quality_screen/dedup.py` — `imagehash.phash` on 5 frames at **10/30/50/70/90%** of duration (avoids endpoint black frames). Audio fingerprint via `pyacoustid.fingerprint_file`. **v1 reject signal is pHash-only** — Hamming distance < `cfg.phash_min_hamming` (8) to any stored phash. Audio fingerprints are stored to `dup_hashes.audio_fp` for a Phase 7 follow-up but don't gate rejection (chromaprint prefix-match is brittle across re-encodes). `compute_signals` deduplicates identical frame phashes before the `INSERT OR IGNORE` write — belt-and-suspenders against the `(clip_id, phash)` PK collision.

### Quality screen rejected-file relocation
- [x] On `rejected_quality`, `os.replace(pending_path → rejected_path)` first, then `repo.tx()` flips status + updates `output_path`. Best-effort consistency: SQLite tx cannot roll back the filesystem move. Three failure-mode branches tested independently (move OK + DB OK / move OK + DB fail / move fail + DB OK + result.reason gains `;move_failed`). `rejected_render` (Phase 4) does NOT relocate; only `rejected_quality`.

### CLIs (mirror selector/editor)
- [x] `python -m src.policy_gate [--clip-id] [--force] [--dry-run] [--config]` — exit codes `0=ok / 1=db missing / 2=clip not found`.
- [x] `python -m src.quality_screen [--clip-id] [--force] [--dry-run] [--config]` — same exit codes.

### Editor wiring change (Phase 4 update)
- [x] [src/editor/runner.py:1-10](src/editor/runner.py) docstring: `selected -> rendered` becomes `policy_pass -> rendered`; failure paths leave clip at `policy_pass`.
- [x] [src/editor/runner.py:67-75](src/editor/runner.py#L67) preflight tuple: `("selected", "rendered")` → `("policy_pass", "rendered")`.
- [x] [src/editor/runner.py:241-247](src/editor/runner.py#L241) run_all queries: `WHERE status='selected'` → `WHERE status='policy_pass'`; `WHERE status IN ('selected','rendered')` → `WHERE status IN ('policy_pass','rendered')`.
- [x] [src/editor/__main__.py](src/editor/__main__.py) docstring: examples reference `status='policy_pass'`; documented prerequisite that `policy_gate` runs first.
- [x] [tests/test_editor_runner.py](tests/test_editor_runner.py) — `_setup` now advances seeded clip from `selected` to `policy_pass` post-upsert. 4 status-assertion lines flipped (`"selected" → "policy_pass"` for unchanged-state cases). 3 tests renamed (`...selected_or_rendered_skipped` → `...policy_pass_or_rendered_skipped`, `..._leaves_status_at_selected` → `..._leaves_status_at_policy_pass`, `..._renders_only_selected` → `..._renders_only_policy_pass`). Phase 4.5 regression test added: `test_selected_status_now_skipped_after_phase_4_5`.

### Pre-upload rejection contract (declared for Phase 5; not implemented yet)
- [x] `evaluate_clip_policy` API stable; Phase 5's uploader will call it directly without refactoring policy_gate.
- [ ] **Phase 5 invariants** (flagged, not yet enforced — Phase 5 will): pre-upload re-check may flip `quality_pass → rejected_policy` only if `youtube_video_id IS NULL`; scheduled-but-rejected rows are acceptable; `daily_upload`'s selection MUST key on status to prevent re-queue.

### Tests (82 new → 264 total)
- [x] `tests/test_clip_text.py` (3) — words within window, intersection-with-clipping at boundaries, empty inputs.
- [x] `tests/test_policy_banlist.py` (5) — case-insensitive word-boundary, multi-word phrase with whitespace tolerance, unicode, empty banlist, **clip-window scoping regression** (term outside the passed clip text does not match).
- [x] `tests/test_policy_profanity.py` (4) — clean / profane / proportional-to-word-count / empty-text edge cases.
- [x] `tests/test_policy_nsfw.py` (6) — safe-pass, nsfw-high-rejects, nsfw-low-doesnotreject, malformed-JSON-retry-recovers, network-failure-fail-soft, **unknown-label-fail-soft** (contract violation = infra failure, not content rejection).
- [x] `tests/test_policy_hook_sanity.py` (6) — score above/below threshold, retry on malformed, network failure, score-out-of-range fail-soft, empty-input short-circuit.
- [x] `tests/test_policy_evaluator.py` (3) — banlist short-circuits before Ollama (asserts NSFW/hook callers never invoked), all-pass runs all four checks, NSFW infrastructure_failed bubbles up to `verdict.infrastructure_failed=True`.
- [x] `tests/test_policy_runner.py` (13) — preflight matrix (selected/policy_pass/rejected_policy/rendered/uploaded), `--force` re-gates policy_pass clips, transition to policy_pass with cleared rejection_reason, transition to rejected_policy with `<check>:<value>`, infrastructure_failed leaves clip at `selected`, missing transcript → error_no_transcript, dry-run no DB writes, run_all filters to selected only, batch alert appended for repeated Ollama failures.
- [x] `tests/test_quality_density.py` (3) — above/below threshold, empty/zero-duration edge cases.
- [x] `tests/test_quality_confidence.py` (3) — above-threshold, missing `probability` field defaults to 0.0, empty word list rejects.
- [x] `tests/test_quality_duration.py` (4) — in-range / under-25 / over-65 / probe-failure-returns-None.
- [x] `tests/test_quality_loudness.py` (6) — three-tier classification, JSON parsed from stderr, subprocess error fail-soft, malformed JSON fail-soft, warn-band boundary, reject-band beyond ±1.5.
- [x] `tests/test_quality_dedup.py` (8) — frame timestamps avoid endpoints (10/30/50/70/90%), no-stored-rows passes, identical phash matches with distance 0, close phash under threshold matches, distance-above-threshold passes, invalid hex skipped, min-distance picked when multiple matches, `compute_signals` dedupes identical frame phashes.
- [x] `tests/test_quality_relocation.py` (3) — three failure-mode branches: move OK + DB OK (file in `rejected/`, status flipped), move-fails + DB still flips (file stays in `pending/`, reason gains `;move_failed`), dry-run (no move + no DB write).
- [x] `tests/test_quality_runner.py` (13) — preflight matrix, scheduled/uploaded clips locked, foundational probe-failure aborts (asserts loudness/dedup never invoked), missing output, all-pass inserts dup_hashes atomically, dry-run no insert, multi-fail concatenates reasons (`duration:18.2;density:1.1`), loudness warn band passes with alert, loudness reject band fails, run_all filters to rendered+unscheduled, run_all emits loudness_warn alert.
- [x] `tests/test_editor_runner.py` (1 new + 3 renamed + 4 fixture flips) — Phase 4.5 regression test confirms `status='selected'` is now `skipped_wrong_status` for the editor.

### Acceptance
- [x] `pytest tests/` — **264 passing** (182 prior + 82 Phase 4.5).
- [x] All four policy checks short-circuit correctly (banlist runs first; later checks don't run when an earlier one fails).
- [x] Infrastructure failures (Ollama unreachable, malformed output, unknown labels) leave clips at their pre-gate status — never reject content because of a flaky model.
- [x] Foundational duration probe abort: a clip with broken metadata returns `error_probe` and no other checks run, no dedup frames extracted.
- [x] dup_hashes PK collision regression: 5 identical frame phashes collapse to 1 row via `set()`-dedupe + `INSERT OR IGNORE`.
- [x] Rejected-file relocation: best-effort, all three failure branches tested independently. No "true atomicity" claim across filesystem + DB.
- [x] Editor's input filter physically excludes `selected` and `rejected_policy` clips (regression test).
- [ ] **Live, post-merge:** policy_gate sweep across the 296 Phase 3 clips; sample 5 `rejected_policy` rows and confirm rejection reason matches the clip-window transcript (NOT whole-video).
- [ ] **Live, post-merge:** quality_screen sweep across the resulting `rendered` clips; ≥90% pass; failures reproducible on re-run.
- [ ] **Live, post-merge:** hand-picked dedup gate — 20 distinct clips → 0 false-positive matches; 5 known near-duplicate pairs → 5/5 caught.
- [ ] **Live, post-merge:** loudness gate distribution on 10 clips; if >2/10 land in warn band (±0.5..±1.5), escalate to two-pass loudnorm as a Phase 4 follow-up.
- [ ] **Live, post-merge:** Idempotent skip — re-run on a `policy_pass` or `quality_pass` clip exits in <2 s with no Ollama / ffmpeg / ffprobe spawn.

### Phase 4.5 live verification (run when ready)
1. `pytest tests/` — expect 264 passing.
2. **Single-clip policy gate:** `python -m src.policy_gate --clip-id <one Phase 3 clip>`. Expect `policy_pass` (or `rejected_policy` with `<check>:<value>` reason). Inspect `clips.rejection_reason`.
3. **Idempotent skip:** re-run #2 immediately. Expect `skipped_already_gated`, no Ollama call, <2 s wall-clock.
4. **Single-clip quality screen** on a rendered clip: `python -m src.quality_screen --clip-id <id>`. Expect `quality_pass` and 1-5 rows in `dup_hashes` for that clip_id. Re-run → `skipped_already_screened`.
5. **Multi-fail probe:** force a duration-out-of-spec clip into `rendered` status, run quality_screen → expect `rejected_quality` with `duration:<n>` in reason and the file relocated to `output/rejected/`.
6. **Full sweeps:**
   - `python -m src.policy_gate` — expect ~296 inputs split into `policy_pass` and `rejected_policy`.
   - `python -m src.editor` — confirms it now picks up policy_pass clips (the input filter changed).
   - `python -m src.quality_screen` — expect ~95% pass on first sweep.
7. **Sanity SQL:** `sqlite3 data/state.db "SELECT status, COUNT(*) FROM clips GROUP BY status;"` should show `policy_pass + rejected_policy ≈ 296` after the gate sweep.
8. **Acceptance gates:** sample 20 distinct clips through quality_screen → 0 dedup false-positives; sample 5 known near-duplicate pairs → 5/5 caught.

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

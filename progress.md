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

## Phase 4.6 — Content Pivot (movie clips, full-screen) — IN PROGRESS

> Triggered 2026-05-04: pivot from "podcast/highlight + Subway gameplay split-screen" to "full-screen movie-clip Shorts with caption-first transcripts." See `.claude/plans/you-are-continuing-work-groovy-kitten.md` for the full pivot rationale and the Phase 5 plan archive.

### Pivot.0 — Config + memory updates (no Whisper / ffmpeg work)
- [x] `config.yaml` — keywords flipped to movie-clip starter set; removed `gameplay_pool` / `top_pane_height` / `bottom_pane_height`; added `render_strategy: blurred_bg`, `blurred_bg_sigma: 20`, `source_pane_aspect: "16:9"`, `caption_min_confidence: 0.7`, `caption_prefer_manual: true`, `copyright_acknowledgement: "movie_clips_v1"`.
- [x] `src/config_loader/loader.py` — typed fields with pydantic Literal + range validation: `render_strategy`, `blurred_bg_sigma ∈ [0, 100]`, `source_pane_aspect`, `caption_min_confidence ∈ [0.0, 1.0]`, `caption_prefer_manual`, `Optional[copyright_acknowledgement]`. Removed `top_pane_height` / `bottom_pane_height` / `gameplay_pool`.
- [x] `tests/test_config_loader.py` — 4 new tests (valid blurred_bg loads, invalid render_strategy rejected, out-of-range caption_min_confidence rejected, missing copyright_acknowledgement loads as None). All 4 passing.
- [x] `CLAUDE.md` — pivot context: project description, v1.2 architecture diagram with captions+blurred-bg, content-inputs section (new keywords, no gameplay), elevated risk acknowledgement.
- [x] `agents.md` — §3 selector with caption-first sub-step + `timing_source` decision rule, §4 editor full-screen blurred-bg pipeline + audio probe, §6 uploader marked paused with movie-clip metadata notes, data-flow diagram updated.
- [x] `plan.md` — Phase 4.6 inserted; Phase 4 description rewritten for blurred-bg; Phase 5 marked PAUSED.
- [x] `progress.md` — this section.
- [x] `pytest tests/` — 279 passing post-Pivot.0 (275 prior + 4 new config tests).
- [ ] **Acceptance:** all four memory files reviewed; no live behavior changes yet.

### Pivot.1 — `src/captions/` (CC fetcher) — NOT STARTED
- [ ] `src/captions/fetcher.py` — yt-dlp `--write-sub --write-auto-sub --sub-langs en --sub-format json3` invocation; sidecar reuse from Phase 2 `data/raw/{video_id}.<lang>.<ext>`.
- [ ] `src/captions/parsers/{json3,vtt,srt}.py` — JSON3 word-level (gold path), VTT/SRT line-level + linear interp.
- [ ] `src/captions/schema.py` — schema_version=2 with `timing_source` + per-word `confidence_source`.
- [ ] `src/captions/runner.py` + `__main__.py` — `python -m src.captions [--video-id] [--force] [--dry-run]` CLI.
- [ ] `src/downloader/ytdlp_runner.py` — request `--sub-format json3` for sidecars (two-line update).
- [ ] `src/quality_screen/confidence.py` — `confidence_source` switch (asr → use probability; manual_attestation → bypass; interp → fail).
- [ ] `src/state/schema.sql` — comment `captions_fetched` on `videos.status` enum; bump transcript schema docs to v2.
- [ ] Tests: `tests/test_captions_json3.py` (7), `test_captions_vtt.py` (4), `test_captions_srt.py` (3), `test_captions_runner.py` (7), `test_quality_confidence.py` (3 new). 24 total.
- [ ] **Acceptance:** ~24 new tests passing; live single-video fetch on a manual-caption video produces schema_v2 cache; idempotent re-run <2 s.

### Pivot.2 — Selector transcriber update — NOT STARTED
- [ ] `src/selector/transcriber.py::load_cache` — `timing_source` switch: whisper-match reuses; manual_word_level reuses (skips Whisper); auto_word_level + high conf reuses; line-interp triggers Whisper.
- [ ] Schema_version=1 backward compat: legacy Whisper transcripts treated as `timing_source='whisper', confidence_source='asr'`.
- [ ] Tests: 3 new in `test_selector_transcriber.py` — manual_word_level reused without Whisper, auto_line_interp overwritten by Whisper, cache absent triggers Whisper.

### Pivot.3 — Editor rewrite (drop gameplay) + music + dialogue reverb — IMPLEMENTED + LIVE-VERIFIED

> 2026-05-07: Editor rewritten for full-screen blurred-bg layout. Music + dialogue reverb folded in as new audio features. Live-verified end-to-end: rendered + uploaded `DiqbQKlGXpQ_313_346` (Michael Jackson clip, "The Largest Concert Tour Ever") to test channel as `yH1yaBZv7lg`.

#### Editor rewrite
- [x] `src/editor/ffmpeg_runner.py` — new filtergraph: `[0:v]split=2` + `gblur=sigma=20` cover-fit background + `scale=1080:608` foreground (preserves full 16:9 frame) + `overlay=(W-w)/2:(H-h)/2,fps=30` + `ass=...` burn.
- [x] `src/editor/ffmpeg_runner.has_audio_stream(path)` — pre-render audio probe via `ffprobe -select_streams a -show_entries stream=codec_type`. Empty → `rejected_render: no_audio_stream`.
- [x] `src/editor/runner.py` — drops gameplay reservation/commit dance; collapses post-render tx to `set_clip_status` only.
- [x] `src/subtitles/ass_writer.py` — `\pos(540, 1500)` (~78% down) so subtitles sit clear of the centered 1080×608 foreground band.
- [x] DELETED `src/editor/gameplay.py` + `tests/test_editor_gameplay.py`.
- [x] DELETED `read_gameplay_pointer`, `read_gameplay_cursor`, `advance_gameplay_state` from `src/state/repository.py`. The `gameplay_cursor` / `gameplay_pointer` tables remain in `schema.sql` for backward compat but no code reads/writes them.
- [x] `data/gameplay/{gta,minecraft,subway}.mp4` deleted from main repo (~1.5 GB freed).

#### Music + dialogue reverb (NEW, integrated with Pivot.3)
- [x] `src/editor/music.py` — pure helpers: `list_music_tracks(cfg)` (alphabetical, supports `.mp3/.m4a/.wav/.flac/.ogg/.aac`), `pick_track_for_clip(clip_id, tracks)` (deterministic SHA1 modulo — same clip always picks the same track across reruns), `resolve_music_for_clip(cfg, clip_id)` (None when `music_enabled=false` or pool empty).
- [x] `src/editor/ffmpeg_runner.build_filtergraph` — when `music_enabled=true`:
  ```
  [0:a] aecho=0.8:0.88:60:0.4, loudnorm=I=-14:LRA=11:TP=-1.0, aresample=48000 [a_voice]
  [1:a] aloop=loop=-1:size=2147483647, atrim=0:<duration>, asetpts=PTS-STARTPTS,
        volume=-15dB, aresample=48000 [a_music]
  [a_voice][a_music] amix=inputs=2:duration=first:normalize=0 [a]
  ```
  When `music_enabled=false`, dialogue-only chain ending at `[a]` directly.
- [x] `data/music/` directory created with `.gitignore` (audio files untracked, dir + README committed).
- [x] `data/music/README.md` documents royalty-free sources (YouTube Audio Library, Pixabay, FreePD, Bensound).
- [x] Config additions: `music_enabled: true`, `music_volume_db: -15`, `dialogue_reverb_enabled: true`, `dialogue_reverb_aecho: "0.8:0.88:60:0.4"`, `paths.music_dir: "data/music"`.
- [x] Phase 6 status: gameplay_pool field removed from `cfg`; `bootstrap.py` `check_gameplay_pool` replaced with `check_copyright_acknowledgement` (soft-warning, not a hard fail).

#### Tests — 17 net new (414 total: 397 prior + 17 net Pivot.3)
- [x] `tests/test_editor_ffmpeg.py` (16) — REWRITTEN: split + gblur=sigma=20 + scale=1080:608 + overlay center + no vstack + dialogue chain has aecho when enabled / no aecho when disabled + music chain uses aloop/atrim/volume/amix + no music input when disabled + blur sigma configurable + argv has 1 input no-music / 2 inputs with-music + filename in correct argv slot + maps `[v_out]` and `[a]`.
- [x] `tests/test_editor_runner.py` (15) — REWRITTEN for Pivot.3: success no longer needs gameplay state + new `error_no_audio_stream` outcome via mocked `has_audio_stream` + run_all writes `editor_no_audio_stream` alert + music_track recorded in result + music disabled returns None + empty pool returns None + preflight matrix unchanged + force gating preserved.
- [x] `tests/test_editor_music.py` (10) — NEW: list filters by extension, all advertised extensions supported, missing dir / empty dir → empty, deterministic picks, distributes across pool, empty pool returns None, resolve_music_for_clip respects `music_enabled`, returns track when enabled, returns None when pool empty.
- [x] `tests/test_subtitles_ass.py` (+2) — anchor is at (540, 1500); rendered output contains `\pos(540,1500)` and not `\pos(540,1340)`.
- [x] DELETED `tests/test_editor_gameplay.py` (8 tests removed).
- [x] `tests/conftest.py::StubConfig` — added `music_enabled`, `music_volume_db`, `dialogue_reverb_enabled`, `dialogue_reverb_aecho`, `blurred_bg_sigma`, `paths.music_dir`. Removed `gameplay_pool`.

#### Live verification (2026-05-07, on the user's PC)
- [x] **Discovery** — `python -m src.discovery --keyword "famous movie clips"` produced 27 movie-clip candidates (504 quota units).
- [x] **Downloader** — `cApYKxhFcm0` (Devil Wears Prada 2 trailer, weak hooks) and `DiqbQKlGXpQ` (MICHAEL Jackson biopic clips). 55 MB + 69 MB.
- [x] **lang_detect** — both videos `lang_ok` at `conf>=0.77`.
- [x] **Selector** — Whisper + Ollama ranker. Devil Wears Prada gave 2 clips with placeholder titles (LLM rubric leaked). MICHAEL gave 2 clips with strong hooks: "The Largest Concert Tour Ever - Michael Jackson's Vision" and "Magic - Michael Jackson's Dream".
- [x] **policy_gate** — `DiqbQKlGXpQ_313_346` PASS. (Earlier Devil Wears Prada clip rejected by hook_sanity for content/title mismatch — system working as designed.)
- [x] **Editor (Pivot.3 first live render)** — produced `__unscheduled__DiqbQKlGXpQ_313_346__the_largest_concert_tour_ever_michael_jackson_s_vision_7730.mp4` (17.2 MB, 33.7 s). Music: `Aylex - This Is Phonk (freetouse.com).mp3` (deterministic per clip_id). Filtergraph confirmed: blurred-bg + 1080×608 foreground + `\pos(540,1500)` subtitles + dialogue reverb + music underneath at -15 dB.
- [x] **quality_screen** — `quality_pass`, loudness within ±0.5 LUFS of -14.
- [x] **slot_planner** — slotted to `2026-05-07T13:00:00Z` (= 21:00 SGT today). DB-first persistence + file rename worked.
- [x] **Approval flow** — file dragged to `output/approved/`. `daily_upload` `reconcile_approvals` flipped status `quality_pass → approved`, then real upload. **YouTube videoId = `yH1yaBZv7lg`**, quota_units_used=1600, no padding (slot was 2.5h in the future). https://youtu.be/yH1yaBZv7lg
- [x] **Acceptance:** Pivot.3 + music + reverb verified end-to-end against the test channel. Visual QA pending (user reviews the published video).

### Pivot.4 — Phase 4.5 banlist tune — NOT STARTED
- [ ] Audit live `cfg.banlist` for movie-content false positives.
- [ ] Sample 20 movie clips through `policy_gate --dry-run`; reject rate ≤ 30%.
- [ ] Tune `profanity_max_score` if rejection rate > 30%.

### Pivot.5 — Live keyword sweep + acceptance — NOT STARTED
- [ ] Pivot.5 step 1–12 from the plan archive: bootstrap → discovery → downloader → lang_detect → captions → selector → policy_gate → editor → quality_screen → caption-reuse-rate measurement.
- [ ] **Acceptance:** ≥5 movie-clip Shorts in `output/pending/` with new format; caption-reuse-rate ≥ 30% (recorded in this file); audio-rejection path exercised.

## Phase 5 — Uploader — COMPLETE (live-verified end-to-end)

> Status flow: `quality_pass | approved → uploaded`; `quality_pass → rejected_policy` (pre-upload re-check fail). Built ahead of Pivot.1–5 per user direction; uploader code is content-agnostic so it'll work on the existing podcast-format rendered clip (`WHibDIQHeaY_31_65`) for the live acceptance test, then on movie-clip output once the pivot lands.

### Module skeleton
- [x] `src/uploader/__init__.py` re-exports `upload_one_clip`, `run_all`, `reconcile_orphans`, `UploadOutcome`, `UploadResult`.
- [x] `src/uploader/__main__.py` — CLI: `--clip-id`, `--dry-run`, `--publish-at`, `--config`. Lazy OAuth (`build_youtube_client` only constructed in real-upload mode). Exit codes: 0=ok, 1=db missing, 2=clip not found, 3=invalid --publish-at, 4=orphan_reconcile_required.
- [x] `src/uploader/runner.py` — `upload_one_clip`, `run_all`, `reconcile_orphans`. `UploadOutcome` enum.
- [x] `src/uploader/publish_at.py` — pure `pad_publish_at(publish_at_utc, now, lead_minutes=20)` and `format_publish_at_iso_z(dt)`. Strict `<` comparison; naive datetimes raise.
- [x] `src/uploader/templater.py` — pure `build_title` (≤100 chars, word-boundary truncate keeping `#Shorts`), `build_description` (hook + source URL + channel + niche hashtag), `build_tags` (deduped, ≤500-char joined budget).
- [x] `src/uploader/insert_body.py` — pure `build_insert_body(clip_row, video_row, padded_publish_at_utc)`. `categoryId=24`, `privacyStatus=private`, `publishAt` Z-suffix only, `selfDeclaredMadeForKids=False`, `defaultLanguage=en`.
- [x] `src/uploader/resumable.py` — `do_resumable_upload(youtube, ledger, body, file_path, *, units)` with `request.next_chunk()` loop (NOT `.execute()` — undefined for resumable=True). Single quota call site; conservative ledger: HttpError records, ConnectionError/timeout don't.
- [x] `src/uploader/orphan_marker.py` — `write_marker`, `read_marker`, `unlink_marker`, `scan_orphans`, `db_is_consistent_with_marker`. Atomic tmp+os.replace writes; tmp files starting with `.` skipped by scan.

### Persistence — orphan-marker fence + ID-first two-step
- [x] **Step 10-pre:** `write_marker(...)` BEFORE any DB write after API success. If marker write fails, alert + return error_persist_failed; runner aborts.
- [x] **Step 10a:** narrow `repo.tx()` writing `youtube_video_id` only via `repo.set_clip_youtube_id(...)`. If this raises, marker survives → next run's reconcile_orphans aborts with exit 4. **No double upload possible.**
- [x] **Step 10b:** wider `repo.tx()` setting status='uploaded' + publish_at_utc + upserting `uploads` row via `repo.upsert_upload(...)`. Failure here is also covered by the marker.
- [x] **Step 10-post:** best-effort `unlink_marker(...)`. Failure logged but not fatal — next run's scan finds DB-consistent marker and silently cleans up.

### Runner-startup orphan reconcile gate
- [x] `reconcile_orphans(repo, cfg)` scans `output/orphans/`. For each marker:
  - DB consistent (status='uploaded' AND yt_id matches AND uploads row exists) → silent unlink, continue.
  - DB inconsistent → return `(False, alerts)`. `run_all` and the CLI both abort; CLI exits 4.
- [x] Reconcile runs BEFORE clip processing — poisoned state never lets a partial re-upload happen.

### Pre-upload policy re-check
- [x] Reuses `policy_gate.evaluator.evaluate_clip_policy(cfg, clip_text, recheck_title, ollama_host=...)`.
- [x] `recheck_title = clip.hook or clip.suggested_title` — matches `templater.build_title`'s input so re-check evaluates the actual upload title.
- [x] Infra-fail (Ollama unreachable / malformed output) → leave at `quality_pass`, alert. Never reject content because of a flaky model.
- [x] Content-fail with `youtube_video_id IS NULL` → flip `quality_pass → rejected_policy` with reason. **Skipped in dry-run** (no DB write).
- [x] Ordering: re-check runs BEFORE the dry-run JSON emission, so a failing dry-run reports `rejected_policy_recheck` and writes NO file.

### Dry-run isolation
- [x] No API call (`youtube.videos().insert(...).next_chunk` never invoked).
- [x] No DB writes.
- [x] No OAuth refresh — CLI doesn't construct `build_youtube_client` in dry-run mode.
- [x] `--publish-at` value is used in-memory to build the body but is NOT persisted to clips.publish_at_utc.
- [x] Atomic JSON write to `output/dry_run/{clip_id}.json` via tmp + os.replace.

### Quota ledger — single source of truth
- [x] `do_resumable_upload` is the only site that calls `ledger.check_or_raise` and `ledger.record` for `videos.insert`.
- [x] Conservative recording: HttpError records; ConnectionError/socket.timeout don't. Matches Phase 1 contract.
- [x] Runner catches `QuotaExceeded` → `quota_exceeded` outcome, alert, batch hard-stops.

### Repository helpers added
- [x] `repo.set_clip_youtube_id(clip_id, youtube_video_id)` — narrow critical-section update.
- [x] `repo.upsert_upload(...)` — explicit `INSERT ... ON CONFLICT(clip_id) DO UPDATE` (preserves `uploaded_at` on retry; not `INSERT OR REPLACE`).
- [x] `repo.clips_for_upload()` — quality_pass/approved with non-null publish_at_utc and null youtube_video_id, ordered by publish_at_utc ASC.
- [x] `repo.get_clip_with_video(clip_id)` — joined videos+clips for templater (v_video_id / v_channel / v_keyword aliases).

### Config + paths
- [x] `config.yaml` — added `paths.orphans_dir: "output/orphans"`.
- [x] `src/config_loader/loader.py` — added `Paths.orphans_dir` field with default for backward compat.
- [x] `.gitignore` — added `output/orphans/*.json`.

### Tests — 48 new (327 total: 279 prior + 48 Phase 5)
- [x] `tests/test_uploader_publish_at.py` (7) — pad needed/not-needed/boundary, naive raises, idempotent repeat, format_iso_z Z-suffix, naive raises.
- [x] `tests/test_uploader_templater.py` (7) — short hook, exactly 100 chars, truncate at word boundary keeping #Shorts, empty-hook fallback, description includes source+channel, tags lowercase+deduped+keyword-first, joined-tags ≤500 chars.
- [x] `tests/test_uploader_insert_body.py` (6) — body shape snapshot, status locked fields, publishAt Z-only never +00:00, categoryId=24, defaultLanguage=en, hook in description.
- [x] `tests/test_uploader_resumable.py` (5) — quota preflight raises before MediaFileUpload constructed, HttpError records ledger and reraises, ConnectionError no record, socket.timeout no record, success returns response.id and records.
- [x] `tests/test_uploader_orphan_marker.py` (6) — write+read roundtrip, atomic no-leftover-tmp, scan skips malformed/.tmp/non-json, unlink missing returns True, db_consistent_when_db_reflects_upload, db_inconsistent matrix (no clip / quality_pass / no uploads row / yt_id mismatch).
- [x] `tests/test_uploader_runner.py` (17) — already_uploaded skip (no API call), yt_id_set_on_quality_pass also skips, wrong_status skip, approved-dir basename fallback succeeds, missing output/publish_at/transcript errors, policy recheck rejection flips status (no API), recheck title input matches build_title, infra-fail soft, success writes marker+10a+10b+unlinks, **10a failure preserves marker → next run's reconcile aborts** (regression on next-run safety), future-too-near pad persists padded value, dry-run no DB / no API / no orphan, dry-run policy rejection emits no JSON (ordering regression), run_all filters to clips_for_upload only, orphan reconcile inconsistent aborts run_all + alert.

### Acceptance
- [x] `pytest tests/` — **327 passing** (279 prior + 48 Phase 5).
- [x] All idempotency invariants:
  - re-running a clip with `youtube_video_id` set → `skipped_already_uploaded`, no API call (regression test).
  - `--dry-run` is fully offline: no API, no DB, no OAuth refresh, atomic JSON write.
  - Quota ledger conservative: HttpError records, network errors don't (regression test).
  - Pre-upload re-check fails-soft on Ollama infra failure.
  - **10a failure with marker fence intact** → next run aborts with `orphan_reconcile_required` (end-to-end regression test).
- [x] **Live (2026-05-06):** Real upload to test channel publishes at requested `publishAt`. Bridge clip `WHibDIQHeaY_31_65` → YouTube videoId `B0Ic4OK38mE`. `youtube_video_id` populated, `uploads` row inserted, `clips.status='uploaded'`, `quota_usage` row for `videos.insert` with units=1600, orphan markers dir empty.
- [x] **Live (2026-05-07):** Pivot.3 movie clip uploaded to test channel — `DiqbQKlGXpQ_313_346` → YouTube videoId `yH1yaBZv7lg`, publishAt=2026-05-07T13:00:00Z, no padding (slot 2.5h in future). Music+reverb format verified end-to-end.
- [x] **Live:** OAuth refresh exercise — old token from Phase 5 setup had expired; `scripts/oauth_first_run.py` rerun produced fresh `data/oauth_token.json`. Phase 5's `RefreshError` propagation was clean (no orphan markers, status preserved).

### Out of scope for Phase 5 (deferred per plan)
- `slot_planner` and bulk `publish_at_utc` assignment — Phase 6.
- Filename rename `__unscheduled__... → {date}__slot_{HHMM}__...` — Phase 6.
- `daily_upload.py` orchestration (today-window filter, Task Scheduler) — Phase 6.
- `tenacity` retry/backoff on transient HTTP errors — Phase 7.
- Quota-increase audit form — operations task.
- Thumbnail upload via `videos.update` — Phase 8.
- Per-percent resumable progress reporting — chunksize=-1 means single-shot; deferred until file sizes warrant it.

## Phase 6 — Orchestrator (no daemon) — COMPLETE (live-verified end-to-end)

> Status flow: `quality_pass` (publish_at_utc NULL) → slot_planner → `quality_pass` (publish_at_utc filled, file renamed) → user drags pending → approved → daily_upload's reconcile_approvals flips status → `approved` → upload_one_clip → `uploaded`. slot_planner does NOT change `clips.status`. The human-review gate is enforced at the SQL boundary via `clips_for_upload_due(statuses=...)` (`('approved',)` when human_review=True; both when False).

### Module skeleton
- [x] `src/slot_planner/__init__.py` re-exports `allocate_slots`, `SlotAssignment`, `slot_one_clip`, `run_all`, `reconcile_slot_renames`, `SlotOutcome`, `SlotResult`.
- [x] `src/slot_planner/__main__.py` — CLI: `--clip-id`, `--force`, `--dry-run`, `--config`. Exit codes: 0=ok, 1=db missing, 2=clip-id not found.
- [x] `src/slot_planner/allocator.py` — pure: `allocate_slots(clip_ids, now_local, upload_slots, days_per_run, clips_per_day, timezone_name, min_lead_minutes=20)`. Cap = `clips_per_day * days_per_run` (semantically correct expression vs. `len(upload_slots) * days_per_run`). Returns `(assignments, overflow)`. zoneinfo for DST correctness even though the canonical runtime path (Asia/Singapore) has no DST.
- [x] `src/slot_planner/runner.py` — `slot_one_clip`, `run_all`, `reconcile_slot_renames`, `SlotOutcome`, `SlotResult`.
- [x] `src/daily_upload.py` — orchestrator: `reconcile_approvals` + today-window filter + recovered_slot detection. Calls Phase 5's `upload_one_clip` directly; does not modify `src/uploader/runner.py`.
- [x] `src/weekly_run.py` — orchestrator: per-stage lambda pipeline (each stage's verified real signature), opens/closes `runs` row, JSON summary, `weekly_run_finished` / `weekly_run_failed` alerts.
- [x] `src/retention/` — Phase 6 skeleton (enumeration only; `dry_run=False` raises `NotImplementedError`). Phase 7 will flip the kill switch.
- [x] `src/bootstrap.py` — extended with `--smoke --keyword <X>` subcommand. Drives the full pipeline against the test channel for one keyword.
- [x] `scripts/weekly_run.xml` + `scripts/daily_upload.xml` — Windows Task Scheduler templates for Sundays 02:00 SGT and daily 09:00 SGT.

### slot_planner — DB-first persistence + reconcile sweep
- [x] **Allocator (pure)**: builds slot grid, filters past-by-`min_lead_minutes`, caps at `clips_per_day * days_per_run`. Cross-TZ DST tests for `America/New_York` spring-forward + `Europe/Berlin` fall-back exercise zoneinfo correctness.
- [x] **Per-clip flow** (`slot_one_clip`):
  1. Status preflight: `approved` → `skipped_locked`; `youtube_video_id` set → `skipped_locked`; non-`quality_pass` → `skipped_wrong_status`; `quality_pass + publish_at_utc + no --force` → `skipped_already_slotted`.
  2. `--force` gate: blocks `approved` and uploaded clips even with `--force` (per Phase 6 plan — user has vouched for that exact artifact).
  3. Compute new filename `{YYYY-MM-DD}__slot_{HHMM}__{title_slug}.mp4` from the assignment + slug recovered from current `output_path` basename (with regex extraction or fallback to `editor.slug.title_slug`).
  4. **DB write FIRST** in one `repo.tx()` (publish_at_utc + publish_slot_local + output_path); status stays `quality_pass`.
  5. `os.replace(old_path, new_path)` AFTER tx commits. On `OSError` returns `error_rename_failed` with DB already pointing at new path; the next slot_planner run's `reconcile_slot_renames` heals it.
  6. Idempotent recovery branches: file already at new path → `slotted` no-op; old path missing + new path missing → `error_no_output`; both paths exist → `error_both_paths_exist` with `slot_rename_both_exist` alert.
- [x] **`reconcile_slot_renames` (startup sweep)**: scans `output/pending/` for `__unscheduled__{clip_id}__*.mp4`, looks up each clip in DB; if `publish_at_utc IS NOT NULL` and `output_path` points elsewhere, performs `os.replace` to complete the rename. Emits `slot_rename_both_exist` alert on collision; `slot_rename_failed` alert on OSError. Idempotent (no-op when filesystem and DB agree).

### daily_upload — approval reconciliation + today-window + recovered_slot
- [x] **`reconcile_approvals(repo, cfg, *, dry_run=False)`**: scans `output/approved/` for files dragged in by the user; flips matching `quality_pass` clip's status to `'approved'` and rewrites `output_path` in one tx. Match key: Python `Path(...).name` lookup against an in-memory map of eligible clips' basenames (avoids SQL `LIKE` wildcard pitfalls if a slug ever contains `%` or `_`). `dry_run=True` logs would-be flips without writing — matches Phase 5's strict no-DB-writes-in-dry-run contract.
- [x] **Today-window filter**: end-of-today computed in `cfg.timezone` via zoneinfo, converted to UTC ISO Z. Window is `<= end_of_today_local` so past-due clips (PC was off, Task Scheduler skipped a day) are recovered alongside today's slots; tomorrow's clips are excluded.
- [x] **Status whitelist** based on `cfg.human_review`: `('approved',)` when True, `('quality_pass', 'approved')` when False. Enforced at the SQL boundary in `repo.clips_for_upload_due(end_of_window_utc_iso_z, *, statuses=...)` — the human-review gate is impossible to bypass.
- [x] **`recovered_slot` detection**: classified distinctly from generic `publish_at_padded`. Fires only when `was_padded=True` AND the row's intended `publish_at_utc` was strictly in the past at upload time. Plain "5 minutes from now needed padding to 20 minutes" emits the existing `publish_at_padded` alert, not `recovered_slot`.
- [x] Reuses Phase 5's runner-startup orphan reconcile gate (`reconcile_orphans`) as the very first step. Inconsistent marker → exit 4. Quota-exceeded breaks the batch identically to Phase 5.

### weekly_run — per-stage adapter pipeline
- [x] **Real signatures honored** (verified against existing modules 2026-05-05): discovery needs `(cfg, repo, ledger, youtube, *, force, dry_run)`; downloader is `(cfg, repo)` with NO dry_run flag; lang_detect/selector/policy_gate/editor/quality_screen/slot_planner all `(repo, cfg, *, dry_run=...)` with `policy_gate` also taking `ollama_host`; retention always `dry_run=True` (Phase 6 skeleton).
- [x] Pipeline is a list of `(stage_name, lambda)` pairs so one consistent failure-handling loop wraps them all. Lambda indirection lets each stage's heterogeneous signature live inline.
- [x] **`runs` row** opened at start with `kind='weekly'` (REUSE `repo.start_run`); closed at finish with `success=1` and `summary_json=json.dumps(summary)` (REUSE `repo.finish_run` — takes a JSON **string**, orchestrator wraps `json.dumps` itself). Failure path closes with `success=0` + the error in the summary, then re-raises.
- [x] **Honest `--dry-run` policy** (per CLI help text):
  - discovery: `dry_run=True` (still spends quota; existing behavior — no DB writes).
  - downloader: SKIPPED entirely via `[] if args.dry_run else downloader.run_all(...)`.
  - lang_detect / selector / policy_gate / editor / quality_screen / slot_planner: `dry_run=True` propagated.
  - retention: always `dry_run=True` in Phase 6.
- [x] Alerts: `weekly_run_finished` on success, `weekly_run_failed` (`{ExceptionType}: {first 200 chars}`) on failure.

### bootstrap --smoke
- [x] `python -m src.bootstrap --smoke --keyword "<keyword>"` drives the full pipeline against the test channel.
- [x] Sequence: `discovery.run_for_keyword` → `downloader.run_all` → `lang_detect.run_all` → `selector.run_all` → `policy_gate.run_all` → `editor.run_all` → `quality_screen.run_all` → pick first `quality_pass` clip with NULL `publish_at_utc` → `upload_one_clip(explicit_publish_at=now+30min)`. **Bypasses slot_planner** — smoke is a one-shot, not bulk slotting.
- [x] First failure halts; raises so the CLI exits 1. `--smoke` without `--keyword` exits 2. `--check` and `--init-db` paths untouched.

### Repository helpers added / reused
- [x] **NEW** `repo.clips_for_slot_planner()` — `quality_pass` AND `publish_at_utc IS NULL` AND `youtube_video_id IS NULL`, ordered by `created_at ASC, clip_id ASC`. Excludes `approved` (slot_planner does not re-slot approved clips).
- [x] **NEW** `repo.clips_for_upload_due(end_of_window_utc_iso_z, *, statuses=("quality_pass", "approved"))` — like `clips_for_upload()` but with an additional `publish_at_utc <= ?` predicate and a parameterized status whitelist. Empty statuses tuple returns `[]` defensively.
- [x] **REUSE** `repo.start_run(kind)` / `repo.finish_run(run_id, success, summary_json)` — already exist; `summary_json` is a string, weekly_run wraps `json.dumps` itself.
- [x] **REUSE** `repo.set_clip_status(clip_id, status, **extra)` — slot_planner writes `set_clip_status(clip_id, 'quality_pass', publish_at_utc=..., publish_slot_local=..., output_path=...)`; status field is a no-op, extras flow through.

### Config + paths
- [x] No new fields. Existing `cfg.timezone`, `cfg.upload_slots`, `cfg.clips_per_day`, `cfg.days_per_run`, `cfg.human_review` drive Phase 6.
- [x] `requirements.txt` — added `tzdata` (required on Windows for `zoneinfo` to resolve IANA names like `Asia/Singapore`).

### Cross-process safety note (deferred to Phase 7)
- [x] DB-first persistence has a brief window between the `repo.tx()` commit and the `os.replace`: DB says the file is at the new path, but it's at the unscheduled path. If `daily_upload` runs in this gap (Task Scheduler overlap, manual concurrent invocation), it sees a "ready to upload" clip whose `output_path` doesn't exist and fails with `error_no_output`. The clip is recoverable on the next slot_planner run via `reconcile_slot_renames`, but the daily_upload window for it is missed.
- [x] Phase 6 mitigation: non-overlapping Task Scheduler triggers (Sun 02:00 SGT vs daily 09:00 SGT) + README warning.
- [ ] Phase 7: real `flock`-style run lock (e.g. `data/.weekly_run.lock` via `msvcrt.locking` on Windows).

### Tests — 70 new (397 total: 327 prior + 70 Phase 6)
- [x] `tests/test_slot_planner_allocator.py` (13) — empty input, exactly N, more than N (overflow), past-slot filter, `min_lead_minutes` window, `clips_per_day < len(upload_slots)` cap, deterministic order across reruns, weekly_run-on-Sunday-02:00 produces today-09:00 SGT first slot, naive `now_local` raises, filename helpers (`filename_date` / `filename_hhmm`), `America/New_York` spring-forward, `Europe/Berlin` fall-back uses fold=0.
- [x] `tests/test_slot_planner_runner.py` (16) — preflight matrix (`uploaded`/`approved`/`rendered`/`quality_pass`-with-and-without-pat), `--force` blocks `approved`, DB-first persistence (tx commits before rename), rename-crash leaves DB committed and file at old path, reconcile heals the partial-write next run, reconcile idempotent on healthy state, reconcile skips clips with publish_at_utc=NULL, both-paths-exist alert, dry-run no rename + no DB write, `--force` re-slots quality_pass+pat clips, run_all empty/overflow/force.
- [x] `tests/test_daily_upload_approval.py` (7) — flips quality_pass → approved on basename match, no-flip when file absent, idempotent on already-approved, slug-with-underscores does not break matching (regression on rejected SQL-LIKE approach), ignores non-mp4 files, ignores clips with publish_at_utc=NULL, `dry_run=True` logs but does not write.
- [x] `tests/test_daily_upload_window.py` (8) — window end in SGT is 23:59 local converted to UTC, day-boundary crossings handled, `clips_for_upload_due` filters by window, status whitelist `('approved',)` excludes quality_pass, status whitelist `('quality_pass', 'approved')` includes both, excludes uploaded clips, includes past-due clips for missed-slot recovery, empty statuses tuple returns `[]`.
- [x] `tests/test_daily_upload_recovery.py` (7) — orphan_inconsistent → exit 4 + alert, recovered_slot alert for past-due clip, padded-but-not-past does NOT emit recovered_slot (regression), quota_exceeded breaks batch, `human_review=True` blocks `quality_pass` (the headline correctness fix), `human_review=False` uploads `quality_pass` directly, dry-run does not persist.
- [x] `tests/test_weekly_run.py` (6) — happy path calls each stage with verified signature, `--dry-run` skips downloader entirely, finished alert written on success, `runs` row stored with `summary_json` as a JSON **string** (regression on the actual existing helper), stage failure halts and records error + alert, `finish_run` called with a string (not a dict).
- [x] `tests/test_retention_skeleton.py` (8) — raw candidates require age >= retention.raw_video AND all derived clips uploaded, age below threshold excludes, transcript candidates use mtime, dup_hashes count by created_at threshold, quota_usage count by date threshold, run_all dry-run aggregates, real-mode raises NotImplementedError (Phase 7 reservation).
- [x] `tests/test_bootstrap_smoke.py` (5) — `--smoke` requires `--keyword` (exit 2), happy-path runs each stage and exits 0, stage failure exits 1, `--check` path unchanged, `--init-db` path unchanged.

### Acceptance
- [x] `pytest tests/` — **397 passing** (327 prior + 70 Phase 6).
- [x] All idempotency invariants:
  - Slot-write is DB-first; rename failures are healed by next-run reconcile.
  - `--force` blocks both uploaded clips AND approved clips (regression test).
  - Approval reconciliation matches by Python basename, not SQL LIKE.
  - Approval reconciliation is forward-only (no demote-back-to-quality_pass path).
  - `dry_run=True` writes nothing in either reconcile_approvals OR upload_one_clip (Phase 5 isolation parity).
  - Recovered_slot alert only fires for past-due intended slots; future-too-near padding still emits the generic publish_at_padded alert.
- [x] **Live (2026-05-06):** `slot_planner --dry-run` on live DB listed `WHibDIQHeaY_31_65` with first available slot today 21:00 SGT. `slot_planner --clip-id` (real) DB-first persistence then file rename to `2026-05-06__slot_2100__*.mp4`. Status preserved at `quality_pass`.
- [x] **Live (2026-05-06):** **Human-review gate verification** — file in `output/pending/` (not approved), `daily_upload` returned 0 candidates, no API call.
- [x] **Live (2026-05-06):** Drag pending → approved. `daily_upload --dry-run` logged the would-be flip, did not write DB. Real `daily_upload` flipped status `quality_pass → approved`, uploaded clip to test channel as `B0Ic4OK38mE`. publishAt was past (slot=21:00, run=21:32) → padded to now+20m, **`recovered_slot` alert appended** (NOT generic `publish_at_padded`) — Phase 6 missed-slot classification correct.
- [x] **Live (2026-05-07):** End-to-end with NEW Pivot.3 format: discovery → downloader → lang_detect → selector → policy_gate → editor (full-screen + reverb + phonk music) → quality_screen → slot_planner → reconcile_approvals → upload. Result: `yH1yaBZv7lg` on test channel. `recovered_slot` not triggered (slot 2.5h in future).
- [ ] **Live (deferred):** Crash-recovery exercise — synthetic mv of slot-named file back to `__unscheduled__` while DB has new path; verify `reconcile_slot_renames` heals on next run. Covered by 16 unit tests; live exercise deferred to next housekeeping pass.
- [ ] **Live (deferred):** `python -m src.weekly_run --dry-run` walks the full pipeline. (User interrupted this step during the 2026-05-07 verification to pivot to Pivot.3 + music; weekly_run logic is covered by 6 unit tests and ran the same per-stage callables that worked individually above.)
- [ ] **Live (deferred):** Task Scheduler import — `schtasks /Create /XML scripts/weekly_run.xml`. Templates committed; user runs after fully reviewing schedule.
- [ ] **Live (deferred):** `python -m src.bootstrap --smoke --keyword "<X>"` — Pivot.3 verified the same per-stage path manually; smoke deferred until next QA pass.

### Out of scope for Phase 6 (deferred)
- Real retention deletion (Phase 7 — flips `dry_run=False` after live disk validation).
- `logs/runs.md` per-run summary writer (Phase 7; Phase 6 writes only to `runs` table).
- `tenacity` retry/backoff on transient HTTP errors (Phase 7).
- `flock`-style run lock to make the slot-planner DB-committed/rename-crashed gap impossible (Phase 7).
- `logs/alerts.md` UTF-8 encoding fix (separate PR — Phase 6 alert kinds stay ASCII).
- Pivot.1–5 (caption-first transcripts + full-screen blurred-bg renderer + banlist tune + live keyword sweep) — Phase 6 contracts are content-agnostic.
- Quota-increase audit form (operations task; documented in README).
- Subject tracking / face-aware crop (Phase 8).
- Web dashboard for queue inspection (Phase 8).

## Phase 7 — Hardening — COMPLETE (live-verified end-to-end on 2026-05-09)

> Status flow unchanged from Phase 6. Phase 7 is operational hardening — no
> new pipeline stages, no new billed API calls. The four locked contracts
> (idempotency, conservative quota recording, dry-run isolation, human-review
> gate) all preserved and explicitly re-regression-tested.

### Module skeleton
- [x] `src/observability/runs_writer.py` — NEW. `append_run_row(logs_dir, kind, started_at, finished_at, success, summary)` writes to `logs/runs.md`. Best-effort, serialized cross-process by the run lock; concurrency contract documented in module docstring.
- [x] `src/observability/run_lock.py` — NEW. `acquire_run_lock(lock_path)` context manager via `msvcrt.locking` (Windows). Raises `RunLockHeld` on contention. Imports `msvcrt` inside the function so the module loads cleanly on any platform; raises a clear `RuntimeError` on non-Windows.
- [x] `src/observability/alerts.py` — UPDATE. `datetime.utcnow()` → `datetime.now(timezone.utc)`; `encoding="utf-8"` on both `write_text` and `open("a")`.
- [x] `src/observability/__init__.py` — re-exports `append_run_row`, `acquire_run_lock`, `RunLockHeld`.
- [x] `src/retention/cleanup.py` — UPDATE. Real-mode deletion replaces the Phase 6 `NotImplementedError`. `RetentionResult` extended with `deleted_*`, `pruned_*`, `vacuumed`, `already_gone`, `delete_errors`. `_safe_unlink` resolves every path under the project root before unlink.
- [x] `src/retention/__main__.py` — UPDATE. CLI default flipped from dry-run to real mode (matches project convention).
- [x] `src/uploader/resumable.py` — UPDATE. `tenacity.retry` wraps a private `_drive_request_to_completion` driver, NOT the outer `do_resumable_upload`. `check_or_raise` exactly-once; ledger.record at most once per logical attempt.
- [x] `src/discovery/search.py` — UPDATE. Same retry pattern around a private `_execute_with_retry` helper inside `_call_with_ledger`.
- [x] `src/selector/ranker.py` — UPDATE. `<<.*>>` placeholder regex rejection in `_validate_clips`; system prompt strengthened with an explicit no-placeholder line.
- [x] `src/weekly_run.py` — UPDATE. Run lock acquisition in `main()` before any DB access; `runs.md` row appended on both success and failure (before re-raise); retention now honors `--dry-run` propagation (was hard-coded `dry_run=True` in Phase 6).
- [x] `src/daily_upload.py` — UPDATE. Run lock + `runs.md` row at end of `run_today` (and on early-return paths: orphan abort, no-candidates).
- [x] `scripts/drop_gameplay_tables.py` — NEW. One-shot migration; idempotent.
- [x] `src/state/schema.sql` — UPDATE. Removed `gameplay_cursor` + `gameplay_pointer` CREATE blocks + the seed `INSERT OR IGNORE` row; replaced with a comment pointing at the migration script.
- [x] `config.yaml` — UPDATE. `hook_sanity_min_score` comment now flags it as INFORMATIONAL ONLY (binary gate post-Phase-4.5).
- [x] `README.md` — UPDATE. Added the YouTube quota-increase audit-form section; replaced stale gameplay setup steps with `data/music/`; replaced the run-lock-deferred warning with the actual lock contract.

### Loguru rotation
- [x] Already wired in [src/observability/logging_setup.py:12-21](src/observability/logging_setup.py) (`rotation="00:00"`, `retention="30 days"`, `compression="zip"`). Phase 7 added the synthetic-trigger test only; production code unchanged.

### Tenacity retry/backoff
- [x] Policy at both sites: `stop_after_attempt(3)` + `wait_exponential(min=2, max=30)` + `retry_if_exception_type((socket.timeout, ConnectionError))`. `HttpError` intentionally NOT in the retry list (fails fast through existing handlers).
- [x] Preserves the locked Phase 1 contract: `HttpError` records via `QuotaLedger`, `ConnectionError`/`socket.timeout` does NOT — even after 3 retries.
- [x] Tests use `monkeypatch.setattr(<fn>.retry, "wait", tenacity.wait_none())` to skip the 2s..30s sleep; covers the 5 invariant cases (1 success record, transient-recover record-once, 3-fail no-record, HttpError fail-fast no-retry, check_or_raise exactly-once across retries).

### Retention cleanup — kill switch flipped
- [x] `run_all(dry_run=False)` now performs real deletion. `dry_run=True` writes nothing (Phase 5 isolation parity).
- [x] Path safety: `_safe_unlink` resolves paths and refuses anything outside `cfg.abs_path(".")`. Out-of-root attempts emit a `retention_path_outside_root` alert.
- [x] FileNotFoundError counted as `already_gone`, NOT a delete error (benign race).
- [x] PermissionError / OSError go into `delete_errors` and emit a `retention_delete_errors` alert; sweep continues across remaining files.
- [x] `dup_hashes` and `quota_usage` pruned via the same threshold math as the count helpers (no drift between count and delete).
- [x] VACUUM gate: `data/.last_vacuum` sentinel file. Run only when `cfg.retention.vacuum_every_days` has elapsed (or sentinel missing).
- [x] VACUUM runs on a freshly-opened standalone `sqlite3.connect`; on `OperationalError("database is locked")`, emits `vacuum_skipped` alert and leaves the sentinel mtime untouched so the next sweep retries.
- [x] [src/weekly_run.py:88](src/weekly_run.py) now passes `dry_run=dry_run` to retention (was hard-coded `True`).

### Per-run summary writer
- [x] `logs/runs.md` table: `kind | started_at | finished_at | success | summary`. UTF-8 encoding. Pipes escaped, newlines collapsed.
- [x] `weekly_run.run_weekly` appends in BOTH happy-path and `except` path (before re-raise). Summary built from existing `summary["stages"]` dict.
- [x] `daily_upload.run_today` appends from THREE return points: orphan-abort (success=false), no-candidates (success=true), normal completion (success=true with outcome counts).

### Run lock — `data/.weekly_run.lock`
- [x] Single shared lock file; weekly_run + daily_upload + manual invocations all block on it.
- [x] Hard-fail: contention → `RunLockHeld` → main() returns 2 + appends `lock_held` alert to `logs/alerts.md`. No DB access (entrypoint tests assert `connect` was never called).
- [x] Phase 6 cross-process safety note in progress.md L567 retired — the gap is closed.

### Selector placeholder leak guard
- [x] Live regression observed on `cApYKxhFcm0` (Devil Wears Prada, Pivot.3 verification): qwen2.5:3b returned `<<=70 char title>>` literal as `suggested_title`. Phase 7 rejects via `re.search(r"<<.*?>>", title)` in `_validate_clips`.
- [x] System prompt strengthened: "Do NOT include angle brackets, square brackets, or example placeholders like '<<...>>' in any field — write a real title."
- [x] Stricter retry prompt now mentions the validation reason verbatim ("placeholder leaked into suggested_title for ...") so the model has a clear correction signal.

### gameplay_* table drop
- [x] DDL removed from `src/state/schema.sql`: `gameplay_cursor` CREATE TABLE, `gameplay_pointer` CREATE TABLE, and the `INSERT OR IGNORE INTO gameplay_pointer (id, next_index) VALUES (1, 0)` seed row. Replaced by a comment.
- [x] `scripts/drop_gameplay_tables.py` — one-shot migration. `--dry-run` reports row counts; real run drops both tables. Idempotent (safe to re-run).
- [x] User invokes manually post-merge: `python -m scripts.drop_gameplay_tables --config config.yaml --dry-run` → review → re-run without `--dry-run`.

### hook_sanity_min_score config comment
- [x] [config.yaml:50](config.yaml) comment updated to flag the field as INFORMATIONAL ONLY (binary accept/reject gate in `src/policy_gate/hook_sanity.py` since Phase 4.5; the value is no longer read by the runtime).

### Alerts UTF-8 + datetime.utcnow fix
- [x] `datetime.utcnow()` → `datetime.now(timezone.utc).strftime(...)` (deprecated in 3.12).
- [x] Both `write_text` and `open("a")` now pass `encoding="utf-8"`. Non-ASCII messages round-trip cleanly.

### README quota-audit section
- [x] Replaced terse "Future quota-increase audit" stub with a 4-step Cloud Console walkthrough (URL path, audit-form requirement, 2–4 week approval window, `youtube_quota_ceiling_units` config knob).
- [x] Stale `data/gameplay/{subway,minecraft,gta}.mp4` setup step replaced with `data/music/` royalty-free track guidance (matches Pivot.3 reality).
- [x] Stale "A `flock`-style run lock is deferred to Phase 7" warning replaced with the actual Phase 7 lock contract.

### Repository helpers — none added
- [x] No new `repo.*` methods. Phase 7 doesn't add new billed API calls or new state-store queries.

### Tests — 43 net new (457 total passing, up from 414 prior)
- [x] `tests/test_alerts_writer.py` (3 new) — UTF-8 round-trip, UTC timestamp, pipe/newline escape.
- [x] `tests/test_logging_rotation.py` (3 new) — handler created, write reaches `agent.log`, rotation/retention/compression configured on the FileSink.
- [x] `tests/test_selector_ranker.py` (+2) — `<<.*>>` rejection + retry uses stricter prompt after placeholder leak.
- [x] `tests/test_runs_writer.py` (5 new) — header creation, append after rows, pipe escape, newline strip, in-process two-thread best-effort (against pre-existing file).
- [x] `tests/test_run_lock.py` (4 new) — release on normal exit, RunLockHeld on contended fd, release on exception inside block, sentinel file created if missing. Skipped on non-Windows.
- [x] `tests/test_weekly_run.py` (+3) — `lock_held → exit 2 + no DB access`, `runs.md appended on success`, `runs.md appended on failure before reraise`. Existing `test_happy_path_calls_each_stage` updated for retention `dry_run=False` propagation.
- [x] `tests/test_daily_upload_recovery.py` (+3) — `lock_held → exit 2 + no orphan reconcile`, `runs.md appended after run`, `runs.md appended on orphan abort`, `human_review gate at SQL boundary` (Phase 7 explicit re-regression).
- [x] `tests/test_uploader_resumable.py` (+3) — transient-recover record-once, HttpError fail-fast no-retry, `check_or_raise` exactly-once across retries. Existing ConnectionError + socket.timeout tests updated to assert `next_chunk.call_count == 3`.
- [x] `tests/test_quota_recording.py` (+3) — same retry-invariant matrix for `_call_with_ledger`.
- [x] `tests/test_retention.py` (renamed from `test_retention_skeleton.py`; +9) — replaced the Phase 6 NotImplementedError test; added: deletes old raw with uploaded clips, preserves in-progress raw (the guard), prunes dup_hashes / quota_usage with exact threshold match, FileNotFoundError counted as already_gone (not error), PermissionError → delete_errors + alert + sweep continues, refuses path outside project root + alert, dry_run writes nothing (regression), VACUUM sentinel gate due-when-missing / not-due-when-recent, VACUUM busy → no sentinel touch + `vacuum_skipped` alert.
- [x] `tests/test_drop_gameplay_tables.py` (3 new) — dry-run reports counts without drop, real run drops tables, idempotent on already-dropped DB.

### Acceptance
- [x] `pytest tests/` — **457 passing** (414 prior + 43 net new Phase 7).
- [x] All locked contracts re-regression-verified:
  - Idempotency: lock-held → hard fail (no queue, no DB writes).
  - Conservative quota recording: HttpError records once, ConnectionError after 3 retries records zero times. `check_or_raise` exactly-once.
  - Dry-run isolation: retention `dry_run=True` writes nothing.
  - Human-review gate: `cfg.human_review=True` excludes `quality_pass` clips at the `repo.clips_for_upload_due` SQL boundary (explicit Phase 7 re-regression test).
- [x] Loguru handler verified (rotation + retention + compression all configured on the FileSink).
- [x] Selector rejects `<<.*>>` placeholder titles; retry prompt mentions the rejection reason verbatim.
- [x] `gameplay_*` migration script idempotent; schema.sql DDL removed.

### Live verification (executed 2026-05-09 on the user's PC)
1. [x] **Run lock smoke** — background helper held `data/.weekly_run.lock` via `acquire_run_lock` in a separate process; foreground `python -m src.weekly_run --dry-run` exited code 2 in <1s with the warning `weekly_run: lock_held; another instance is running`. `logs/alerts.md` row appended: `2026-05-09 05:04:48 | lock_held | weekly_run skipped: another instance holds data/.weekly_run.lock`. Connect was never invoked (the lock-held branch returns before `connect(db_path)`).
2. [x] **Retention dry-run** — `python -m src.retention --dry-run` reported zero candidates across all categories (raw=0, transcripts=0, pending=0, approved=0, rejected=0, dup_hashes=0, quota_usage=0). Only `vacuum_due=True` (sentinel missing on first invocation). Live `B0Ic4OK38mE`'s raw video is ~3 days old → well under the 14-day TTL.
3. [x] **Retention real-mode** — `python -m src.retention` ran VACUUM cleanly on the live `state.db`; `data/.last_vacuum` sentinel created (32-byte ISO timestamp). Re-running immediately reported `due=False ran=False` confirming the sentinel gate works (also reproduced by the backgrounded second invocation that finished mid-flight: `vacuum_due=False` from a separate process).
4. [x] **runs.md writer** — `python -m src.daily_upload --dry-run` (cheaper than weekly_run, no quota cost) created `logs/runs.md` with the canonical header + one row: `| daily | 2026-05-09 05:16:38 | 2026-05-09 05:16:38 | true | no_candidates |`.
5. [x] **Tenacity retry sanity** (wall-clock test, no Windows Firewall needed) — exercised both `_execute_with_retry` (search.py) and `_drive_request_to_completion` (resumable.py) with a `MagicMock` raising `ConnectionError`. Real `time.sleep`, no test override of `wait`. Both completed in 4.0s with `call_count == 3` — matches `wait_exponential(min=2, max=30)` semantics (~2s + ~2s between attempts).
6. [x] **Alerts UTF-8 round-trip** — wrote a synthetic `phase7_utf8_test` row containing Japanese (日本語), Korean (한국어), and emoji (✅) to `logs/alerts.md`; re-read with `encoding='utf-8'` confirmed all three preserved byte-exact.
7. [x] **Drop-gameplay-tables migration** — `python -m scripts.drop_gameplay_tables --dry-run` reported `gameplay_cursor: 1 row, gameplay_pointer: 1 row` (stale Phase 4 data). Real run dropped both. Post-migration `sqlite_master` lists exactly: clips, discovery_attempts, dup_hashes, niche_baselines, quota_usage, runs, sqlite_sequence, uploads, videos. Schema matches `schema.sql` after Phase 7 DDL removal.
8. [x] **Manual cleanup** — user deleted `B0Ic4OK38mE` (Joe Rogan + Minecraft bridge clip, pre-pivot format) from the test YouTube channel via YouTube Studio. Test channel now contains only `yH1yaBZv7lg` (Pivot.3 movie clip).

### Out of scope for Phase 7 (deferred)
- OAuth refresh probe in `bootstrap --check`. Calibration findings note this as optional. Defer until a token expires silently.
- Two-pass loudnorm in editor (Phase 4 follow-up). Only matters if `quality_screen` rejects too many clips on the ±0.5 LUFS gate.
- Pivot.1 (`src/captions/`), Pivot.2 (selector caption-first reuse), Pivot.4 (banlist tune), Pivot.5 (live keyword sweep). Independent of Phase 7 hardening.
- POSIX `fcntl.flock` fallback in `run_lock.py`. Single-machine Windows deployment.
- Quota-increase audit-form filing itself — README documents the steps; the user files when ready.

## Phase 8 — Stretch (deferred)
- [ ] Subject tracking (face/saliency-aware crop) replacing center-crop
- [ ] Thumbnail auto-generation
- [ ] A/B title testing
- [ ] TikTok / Reels integration
- [ ] Web dashboard
- [ ] File YouTube quota-increase audit form

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
- Endpoint: `POST https://www.youtube.com/youtubei/v1/next` (the `/player` endpoint returns a stripped-down payload without heatmap data — verified live and patched 2026-04-30). Body includes `clientName=WEB`, `clientVersion=2.20241201.00.00`, `hl=en`, `gl=US`, plus `playbackContext.contentPlaybackContext.currentUrl=/watch?v=<id>` (which the server expects to populate the watch-page entity batch). Hard-coded module constant. 5 s timeout, one retry on connection error / 5xx, fail-open on persistent failure. No fixed sleep between calls — rely on timeout/retry to detect throttling.
- Parses `frameworkUpdates.entityBatchUpdate.mutations[*].payload.macroMarkersListEntity.markersList.markers[*]` → `{startMillis: str, durationMillis: str, intensityScoreNormalized: float}`. Multiple mutations are walked; only those carrying `macroMarkersListEntity` contribute markers. Fail-open: 4xx / 5xx / missing path → return `None`, log at INFO, count as a miss.
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
> Phase 3 ends at `clips.status='selected'` with `(start_s, end_s, hook, suggested_title, selection_method)` populated and a cached transcript at `data/transcripts/{video_id}.json`. Phase 4 turns each selected clip into a 1080×1920 H.264 mp4 in `output/pending/`: split-screen with the source video on top (center-cropped) and a looping background gameplay clip on the bottom, karaoke-style word-by-word ASS subtitles burned in, audio loudnorm'd to -14 LUFS, encoded with `h264_nvenc` on the RTX 3070 — single ffmpeg pass per clip.

### Status flow
`selected → rendered`

New status value: `rejected_render` for irrecoverable source/probe failures (source mp4 missing or unreadable). `clips.status` column is free-form TEXT (schema-comment-only update, no migration).

Phase 4 fills only `title_slug`, `output_path`, `status` on success. Leaves `publish_at_utc`, `publish_slot_local`, `youtube_video_id` NULL — those belong to Phases 5/6.

### Module layout (mirrors `selector/`)
```
src/subtitles/
  __init__.py        re-exports
  ass_writer.py      Whisper words → .ass karaoke (clip-relative timing)
src/editor/
  __init__.py        re-exports
  __main__.py        CLI: --clip-id, --force, --dry-run, --config
  runner.py          orchestrator: render_one_clip, run_all
  ffmpeg_runner.py   filtergraph builder + subprocess.run wrapper
  gameplay.py        round-robin file picker + cursor read/advance
  slug.py            suggested_title → filesystem-safe slug (≤80 chars)
```
`subtitles/` is its own package per `agents.md` §5. Raw subprocess (no `ffmpeg-python`) per the existing pattern in `src/downloader/ytdlp_runner.py`'s `_ffprobe_height` (`subprocess.check_output`, list-of-args, never a shell string).

### Subtitle generation (`subtitles/ass_writer.py`)

#### Chunking — non-overlapping karaoke chunks
One Dialogue line per **non-overlapping chunk of 1–2 words**. Each line's `End` time is exactly the next line's `Start` time so libass renders one chunk at a time with no overlap. The active word inside each chunk is highlighted via `\k` karaoke tags so the highlight sweeps across the chunk while it's on screen. Chunk size = 2 words by default; falls back to 1 word for very fast speech (>4 wps sustained) or for a final orphan word.

#### Clip-relative timing
Whisper word timestamps in the cached JSON are full-video seconds. The ASS file must be clip-relative: subtract `clip.start_s` from every word's start/end so the file timeline begins at 0. Only words intersecting `[clip.start_s, clip.end_s]` are included; words straddling the boundary are clipped to the boundary.

#### `\k` centisecond rounding with drift correction
`\k` durations are integer centiseconds. Naive rounding accumulates error. Use carry-the-remainder: track `accumulated_real_cs - accumulated_emitted_cs`; when the residual exceeds 1 cs, add it to the next word. Acceptance: cumulative drift ≤ 50 ms over a 60 s clip (verifiable in tests with synthetic word streams).

#### Style
Per `agents.md` §5: Impact font ~120 pt, white fill, 8 px black border, yellow active-word highlight via `\1c&H0000FFFF&` override, `Alignment 5` + `\pos(540, 1340)` for center-anchored placement ~70% down a 1920-tall canvas.

#### Special-character escaping
ASS dialogue text escape (separate concern from ffmpeg filter-path escape):
- `\` → `\\`
- `{` → `\{`
- `}` → `\}`
- newlines normalized to a single space
- apostrophes are NOT escaped — that's an ffmpeg filter-path concern, not a libass dialogue concern.

### ffmpeg invocation (`editor/ffmpeg_runner.py`)

#### Filtergraph (single pass)
```
[0:v] scale=1080:960:force_original_aspect_ratio=increase,
       crop=1080:960
       → [top]

[1:v] scale=1080:960:force_original_aspect_ratio=increase,
       crop=1080:960
       → [bot]

[top][bot] vstack=inputs=2,fps=30 → [v]

[v] ass='<escaped_path>' → [vsub]

[0:a] loudnorm=I=-14:LRA=11:TP=-1.0,aresample=48000 → [a]
```
`force_original_aspect_ratio=increase` + `crop` guarantees both pane dimensions are met or exceeded (no under-fill on non-16:9 inputs). Identical chain on both panes — no preliminary aspect-strip crop.

#### Seeking via command args, not in the filtergraph
`-ss` and `-t` go on the input declarations BEFORE each `-i`, never inside `crop`/`scale`. Built as `list[str]` and passed to `subprocess.run(shell=False)`. Never concatenated into a shell string.

```
ffmpeg -y
  -ss <clip.start_s>     -t <duration> -i "<raw_mp4_path>"
  -ss <gameplay_offset>  -t <duration> -i "<gameplay_path>"
  -filter_complex "<filtergraph>"
  -map "[vsub]" -map "[a]"
  -c:v h264_nvenc -preset p5 -cq 23
  -c:a aac -b:a 128k -movflags +faststart
  "<output_path.tmp.mp4>"
```

#### Subtitle filter syntax
Use `ass=<escaped_path>` (the dedicated libass filter), NOT `subtitles=`. Windows path escaping for the libass filter argument:
- `\` → `\\`
- `:` (drive letter) → `\:`
- `,` → `\,`
- `'` → `\\\''`
- whole argument wrapped in single quotes inside the filter string

`escape_ass_filter_path` is its own function with its own unit test (Windows-style absolute path round-tripping; output starts with `'C\:\\Users\\...`).

#### Loudnorm strategy
One-pass `loudnorm=I=-14:LRA=11:TP=-1.0,aresample=48000` per `config.yaml`. Acceptance target -14 ±0.5 LUFS is best-effort with one-pass. Phase 4 does NOT verify after render; Phase 4.5 (quality_screen) is the right place to add an `ffmpeg -af loudnorm=print_format=json` post-check.

#### NVENC settings
`-preset p5 -cq 23` per `config.yaml`. Hardware encoder verified by `src/bootstrap.py check_ffmpeg`.

### Gameplay rotation (`editor/gameplay.py`)

`gameplay_cursor` and `gameplay_pointer` already exist in `schema.sql`.

#### Read-then-write split — never hold a transaction during ffmpeg
Rendering is the slow part (~5–15 s with NVENC). Long write transactions block every other repository operation. Per clip:
1. **Reserve (read-only)**: `SELECT next_index FROM gameplay_pointer`; pick file from `cfg.gameplay_pool`; `SELECT last_offset_s, file_duration_s FROM gameplay_cursor WHERE file_name=?`; compute `(file, offset)`. No DB writes yet.
2. **Render (no transaction)**: invoke ffmpeg with the captured `(file, offset)`. Atomic write to `<output_path>.tmp.mp4`, then `os.replace()`.
3. **Commit (one short tx)**: only on render success — advance `gameplay_pointer.next_index`, advance `gameplay_cursor.last_offset_s` by `clip_duration` (wrap to 0 if `last_offset_s + clip_duration + 1 s safety > file_duration_s`), set `gameplay_cursor.last_used_at`, then `repo.set_clip_status(clip_id, 'rendered', output_path=..., title_slug=...)`. All inside one `repo.tx()`.

If render fails, the cursor was never advanced, so the next clip retries with the same `(file, offset)`. No double-consumption, no orphaned advancement.

#### `file_duration_s` caching
Probed once per file via `ffprobe -v error -show_entries format=duration -of csv=p=0 <path>` and cached in `gameplay_cursor.file_duration_s` on first commit. Pattern matches the existing `_ffprobe_height` in `src/downloader/ytdlp_runner.py`.

#### Concurrency
Phase 4 runs single-threaded inside `weekly_run`, so the simpler short-transaction approach is sufficient. If parallel rendering is added later, introduce a `rendering` status as a soft lock or use SQLite's `BEGIN IMMEDIATE` for the reservation step.

### Filename strategy
Phase 4 renders to:
```
output/pending/__unscheduled__{clip_id}__{title_slug}.mp4
```
The `__unscheduled__` prefix is the explicit signal that the file is awaiting `slot_planner`. Phase 6 renames once, in place, to:
```
output/pending/{YYYY-MM-DD}__slot_{HHMM}__{title_slug}.mp4
```
Phase 4 stores the unscheduled path in `clips.output_path` immediately. Phase 6 updates `output_path` to the renamed path in the same transaction as the rename.

`title_slug` derivation (`editor/slug.py`): lowercase, replace runs of non-`[a-z0-9]` with `_`, collapse repeats, trim leading/trailing `_`, truncate at a word boundary to ≤80 chars minus a 4-char `sha1(clip_id)[:4]` suffix. Suffix guarantees no collision between clips that share a normalized title; suffix is stable across reruns.

### Idempotency (3 layers)
1. **Status preflight** — clip at `status='rendered'` skips entirely (unless `--force`); `selected` proceeds.
2. **`--force` is gated** — only re-renders if `status='rendered'` AND `publish_at_utc IS NULL` AND `youtube_video_id IS NULL`. Scheduled or uploaded clips return `skipped_locked` so a stray `--force` cannot stomp downstream Phase 5/6 state.
3. **Atomic file write** — render to `<output>.tmp.mp4`, `os.replace()` only on ffmpeg exit code 0 + size > 0. ffmpeg failure / 0-byte output unlinks tmp, leaves clip at `selected`. Status flips to `rejected_render` only for irrecoverable problems (source mp4 missing or ffprobe reports unreadable).

### Per-clip flow
1. Read clip row + `video_id` + raw mp4 path + transcript JSON.
2. Validate: source mp4 exists; transcript JSON exists.
   - Missing source → `rejected_render`, skip.
   - Missing transcript → `error_no_transcript` (rolled-up alert), skip; next run re-transcribes.
3. Compute `title_slug` + unscheduled `output_path`.
4. Reserve gameplay (read-only).
5. Generate clip-relative ASS file in temp location.
6. Build ffmpeg argv list (raw mp4, gameplay file, ass path, output tmp).
7. `subprocess.run(argv, shell=False, check=False, capture_output=True)`.
8. On exit code 0 + tmp file > 0 bytes: `os.replace(tmp, final)`; inside `repo.tx()`: advance gameplay state and `set_clip_status('rendered', output_path=..., title_slug=...)`.
9. On failure: unlink tmp, leave clip at `selected`, append to run-end alert rollup.

### CLI semantics (mirrors lang_detect / selector)
```
python -m src.editor                             # all clips at status='selected'
python -m src.editor --clip-id <id>              # single clip
python -m src.editor --force                     # re-render unscheduled rendered clips (gated)
python -m src.editor --dry-run                   # build filtergraph + ASS, print argv, no ffmpeg / DB writes
python -m src.editor --config alt.yaml
```
Exit codes: 0 = ok, 1 = config/db missing, 2 = clip-id not found.

### Repository helpers added
- `read_gameplay_pointer() → int` — returns `next_index`, defaults to 0.
- `read_gameplay_cursor(file_name) → (last_offset_s, file_duration_s)` — returns `(0.0, None)` if no row.
- `advance_gameplay_state(*, file_name, new_offset_s, file_duration_s, new_pointer_index)` — multi-statement, transaction-bare; caller wraps in `repo.tx()`.
- `set_clip_status(...)` already accepts `**extra` — Phase 4 calls `set_clip_status(clip_id, 'rendered', output_path=..., title_slug=...)` with no new helper needed.

### Tests (47 new → 182 total)
- `tests/test_subtitles_ass.py` (10) — single word, non-overlapping chunks (`line.End == next.Start` exactly), fast-speech fallback to 1-word, drift ≤50 ms over 60 s synthetic, words clipped to clip window, escape `\ { }` but NOT apostrophe, empty words → header only, `Alignment 5` in style.
- `tests/test_editor_slug.py` (7) — short title, special chars, truncation at word boundary, distinct hash suffixes for distinct `clip_id`s, stable suffix on rerun, empty/garbage-only fallback to `untitled`.
- `tests/test_editor_ffmpeg.py` (9) — Windows path escape, posix path escape, comma+apostrophe escape, filtergraph contents, regression on `crop=in_w:in_h*9/16` (must NOT appear), top/bot chains identical, argv is list, `-ss` before each `-i` and never inside filtergraph, NVENC settings present.
- `tests/test_editor_gameplay.py` (8) — round-robin 0→1→2→0, cursor advance, wrap at near-end, ffprobe called once per file, render failure does not advance, empty pool / missing file / unprobeable file → None.
- `tests/test_editor_runner.py` (13) — render success flips status + advances gameplay, status preflight matrix, `--force` re-renders unscheduled / blocked for scheduled / uploaded, source missing → `rejected_render`, missing transcript → `error_no_transcript`, ffmpeg failure leaves `selected` and gameplay unadvanced, 0-byte output treated as failure, dry-run no subprocess + no DB writes + argv printed, `run_all` filters out non-`selected`.

### Acceptance
- `pytest tests/` — 182 passing (135 prior + 47 Phase 4).
- Live single-clip render produces a 1080×1920 H.264 mp4; `ffprobe` verifies `codec_name=h264, width=1080, height=1920, r_frame_rate=30/1`, duration within 0.1 s of `(end_s - start_s)`.
- Idempotent skip: re-running `--clip-id <id>` exits in <2 s with `skipped_already_rendered`, no ffmpeg invocation.
- Dry-run prints filtergraph + argv with libass `ass=` argument correctly escaped; no subprocess / file / DB writes.
- Audio integrated loudness within ±0.5 of -14 LUFS (verify via `ffmpeg -af loudnorm=print_format=json` after a few real renders).
- Visual QA on 3 random rendered clips: top half source video centered, bottom half gameplay, subtitles word-by-word with no overlap and ≤50 ms drift.

### Out of scope for Phase 4 (deferred)
- Two-pass loudnorm — only if Phase 4.5 quality_screen rejects too many on the ±0.5 LUFS gate.
- Subject tracking / face crop — `agents.md` §4 explicitly defers to Phase 8.
- Parallel rendering — single-threaded for v1.
- Slot-aware filename emission — Phase 6 owns the rename.
- Policy gate (banlist / profanity / NSFW / hook-sanity) — Phase 4.5. Phase 4 will render `selected` clips directly until Phase 4.5 lands, after which the orchestrator must guarantee `rejected_policy` clips never reach Phase 4.

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
  - Post-render loudness check: `ffmpeg -af loudnorm=print_format=json -f null -` parses `input_i`; reject if outside -14 ±0.5 LUFS.
- All rejections write `clips.rejection_reason`. Rejected clips are not rendered or uploaded.
- **Acceptance:** all banned-topic test inputs caught; legitimate test set passes; zero false-positive duplicate matches on 20 hand-picked distinct clips.

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

# Issue 11 — Hand-stitch script for Slice 10 (assemble Corti clip)

**Status:** ready-for-agent
**Type:** AFK (requires GPU-equipped local environment for narration + assembler — only runnable on the user's machine in practice)

## Parent

`docs/prds/slice-10-first-live-ai-gen-upload.md` (Slice 10: First live AI-generated upload)

## What to build

> **Amended 2026-05-24 (/grill-with-docs):** approach changed from a separate one-off script to a `--reuse-shots/--order` flag on the existing `scripts/render_from_script.py`; shot order changed from `[1,0,2,3]` (whiteboard thumbnail) to `[3,2,1,0]` (shot 3 — clinician + medical scan — leads). Rationale below.

Extend the existing Slice 4/5 tracer `scripts/render_from_script.py` with a `--reuse-shots <dir> --order <i,j,k,l>` mode that **skips Stage-1 generation** and feeds already-rendered shot MP4s, in the given order, through the unchanged narration → Whisper-align → subtitle → assembler stages, producing one assembled MP4 in `output/pending/`. Then insert a corresponding `clips` row at `status='quality_pass'` (a separate small DB step — `render_from_script.py` itself does not write to the DB). After the MP4 exists and the row is inserted, the standard HITL workflow (drag pending → approved, run `daily_upload.py`) takes over.

Why a flag instead of a throwaway script: the grill found `render_from_script.py` already wires every stage we need and only its Stage-1 *generation* is in the way. A `--reuse-shots/--order` flag is a ~20-line addition that reuses that wiring, costs no new Kling money, and — unlike re-running generation — does **not** re-fire the shot-0 prompt that named a real living person. The flag is also reusable for any future "ship from existing shots" need, so it is not dead weight.

End-to-end behaviour:

1. **Read the candidate script row** for `script_id='7cb41305-b39b-4cc2-855b-067e03549d25'` from `data/state.db`. This is the Corti's-Symphony candidate locked in the Slice 10 grilling session — narration is source-traceable to its VentureBeat article (the alternate `d0da493f` candidate has a fabricated stat and was rejected).
2. **Sanitize the narration** by calling `clean_mojibake(scripts_row['narration'])` from `src/scripter/sanitize.py` (delivered in Issue 10). This converts `Corti�s` → `Corti's` so Edge TTS pronounces correctly and Whisper subtitles render cleanly.
3. **Point `--reuse-shots` at the 4 existing Kling shots** at `data/ai_gen_shots/spike_2026-05-21/` (files `7cb41305_shot_{0,1,2,3}.mp4`). Do not re-render — these are the paid shots already on disk. The flag must skip Stage-1 generation entirely (no OpenRouter call).
4. **Pass `--order 3,2,1,0`** so **shot 3 (clinician + medical scan) leads** and becomes the first-frame auto-thumbnail. Frame review (2026-05-24): three of the four shots are synthetic people; only shot 0 came from a prompt naming a real living person (Andreas Cleve). Shot 3 is the cleanest, on-topic, compliant cover (a generic clinician + a medical scan, no garbled text); the whiteboard frame (shot 1) has garbled AI text and is the worst-looking cover; the synthetic-"CEO" shot 0 is buried last. Narration names no one, so audio is safe and disclosure (`containsSyntheticMedia=true`) covers the generic synthetic people. Order past the lead frame is a reversible detail. (The upstream scripter-prompt fix — "do not name real living people in shot prompts" — is separate steady-state work, not this issue.)
5. **Run the narration stage** on the sanitized narration text: Edge TTS at `en-US-GuyNeural`, rate `+10%`, pitch `0Hz` → mp3. Whisper forced-align on the mp3 → per-word timings.
6. **Run the assembler stage** on the reordered shot list + narration mp3 + word timings: ffmpeg concat shots → mux narration → music duck/mix from `data/music/` (which is already YT-Audio-Library-only per Slice 10 grilling) → ASS line-at-a-time subtitle burn → NVENC encode → 2-pass −14 LUFS normalize. Output MP4 to `output/pending/__unscheduled__7cb41305__corti-symphony.mp4` (the `__unscheduled__` prefix is the existing convention for clips that have no `publish_at_utc` yet).
7. **Insert a `clips` row** (a separate small step — `render_from_script.py` produces only the MP4 and does not touch the DB; a few lines of SQL or a tiny insert script). Fields: `clip_id` (UUID), `content_kind='ai_generated'`, `script_id='7cb41305-b39b-4cc2-855b-067e03549d25'`, `video_id=NULL` (legacy column, nullable post-migration), `status='quality_pass'`, `output_path` matching the MP4 basename exactly, `publish_at_utc=NULL`, and the existing required NOT-NULL columns (start_s, end_s, hook, suggested_title, selection_method) populated with values derivable from `scripts_row` or sensible defaults documented in the script's source.
8. **Exit cleanly.** No further action — the standard HITL workflow takes over from `output/pending/`.

Both steps must be safely re-runnable: re-running `render_from_script.py --reuse-shots` overwrites the MP4; the `clips`-row insert must upsert on `script_id='7cb41305...'` (update `output_path`/`updated_at` rather than insert a duplicate). The user has a backup at `data/state.db.pre-slice-10.bak` from the migration, so a misstep is recoverable but should not be a routine outcome.

## Acceptance criteria

- [ ] `scripts/render_from_script.py` accepts `--reuse-shots <dir> --order <i,j,k,l>`, skips Stage-1 generation, and runs to completion (no OpenRouter call).
- [ ] A `clips` row is inserted (separate step) against the live `data/state.db` without error.
- [ ] An MP4 is written to `output/pending/__unscheduled__7cb41305__corti-symphony.mp4` with duration ≈16 s, resolution 1080×1920, audio loudness ≈ −14 LUFS integrated.
- [ ] The MP4's first frame is **shot 3** (clinician + medical scan), not the synthetic-"CEO" scene (shot 0).
- [ ] Burned-in subtitles render `Corti's` correctly (no `?` or `�` glyphs).
- [ ] A `clips` row exists with `content_kind='ai_generated'`, `script_id='7cb41305-b39b-4cc2-855b-067e03549d25'`, `status='quality_pass'`, and `output_path` matching the MP4 basename.
- [ ] No new Kling API calls were made (Activity log on OpenRouter shows no new charges for `kwaivgi/kling-v3.0-std`).
- [ ] The `--reuse-shots/--order` flag is documented in the `render_from_script.py` `--help` / docstring (it is a reusable addition, not a throwaway).

## Blocked by

- Issue 10 (`clean_mojibake` utility) — this script imports `clean_mojibake` from `src/scripter/sanitize.py` to sanitize the narration before TTS.

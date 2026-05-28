# Project Plan — Media Agent

> **Pivot.6 (Tech/AI news) is the active plan.** This file inlines the full slice breakdown.
> Historical phases (0–7) and earlier pivots (0–5) are archived in `plan.archive.md`.

---

## Direction summary

**Niche:** AI-centric tech news Shorts (ADR-0004). On-niche = model/research releases, AI shipping in products, or major flagship hardware/OS launches. Culture, drama, and minor/incremental tech are excluded at ingest. MKBHD-style topic angle, Zack D. Films delivery format. ~16 s clip, ~40-word narration, 4 stitched shots, hook in first 5 words, ends on a teaser.

**PRD / ADR:** `docs/prds/ai-niche-trending-selection-and-photo-framing.md` · `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`

**Generator:** OpenRouter Kling 3.0 std (`kwaivgi/kling-v3.0-std`) via existing `src/ai_gen/openrouter_kling.py`. Bearer auth via `OPENROUTER_API_KEY`. Provider-abstracted behind `ai_gen.base.Provider` ABC.

**Narration:** Edge TTS `en-US-GuyNeural`, rate `+10%`, pitch `0Hz`. Natural conversational pacing. Whisper `large-v3` int8_float16 on CUDA for forced-alignment on TTS mp3.

**Visual style suffix (locked):**
`"clean editorial product photography, soft studio lighting, neutral backgrounds, minimalist composition, sharp focus, vertical 9:16, premium tech magazine look"`

**Topic source:** Curated AI-focused RSS feeds (`docs/rss_feeds.md`) with 48 h recency (96 h on low yield). On-niche LLM gate at ingest + Significance/HN ranking at scripter Stage A. Dedup by URL + title-similarity.

**Budget:** $5/week → 2–3 clips/week (scale up when growth validates the format).

**AI disclosure:** locked on (`compliance.ai_disclosure=true`). Description footer + `status.containsSyntheticMedia=true` on `videos.insert` for all `ai_generated` clips.

**Human review:** locked on for first 2 weeks. Filesystem-based — user drags `output/pending/*.mp4` → `output/approved/`.

---

## Active slices

Each slice is a vertical tracer bullet — a thin end-to-end path through every layer. Slices are independently verifiable. Per-slice progress lives in `progress.md`; this file is the readable narrative.

### Slice 1 — Niche + direction lock (docs only) · HITL · no blockers

Cold-read of `CLAUDE.md` + `plan.md` should tell a fresh agent exactly what to build and why. Inline the corrected Pivot.6 direction (tech/AI niche, OpenRouter Kling 3.0, clean editorial style, `+10%/0Hz` narration, RSS topic source) into all five doc files. Retire broken `.claude/plans/...` references everywhere.

**Acceptance:** No references to "weird/unsettling facts." No references to direct-Kling-API (`KLING_API_KEY`). No broken file links. Stale topic_pool config language replaced with RSS direction. New 10-slice structure visible in `progress.md`.

### Slice 2 — OpenRouter Kling 3.0 live spike · HITL · blocked by 1

Use existing `src/ai_gen/openrouter_kling.py` directly: 10 hand-typed prompts → 10 MP4 shots. Confirm cost per shot, aesthetic match to the locked style suffix, native 9:16 1080×1920 output. No DB writes, no scripter, no RSS — just the provider call.

**Acceptance:** 10 MP4 shots produced. Per-shot cost recorded. User signs off on aesthetic. Cost ≤ budget projection for one clip.

### Slice 3 — Schema migration · AFK · blocked by 1

Add new tables and columns to the SQLite store:
- `topics` (id, url, title, summary, source_feed, fetched_at, status)
- `seen_topics` (url_hash, title_normalized, first_seen_at) — dedup ledger
- `scripts` (script_id, topic_id FK, title, narration, shots_json, style_suffix, ollama_model, created_at, status)
- `generation_jobs` (job_id, script_id FK, shot_index, provider, prompt, duration_s, status, external_id, output_path, cost_cents, submitted_at, completed_at, error)
- `clips.content_kind TEXT NOT NULL DEFAULT 'sourced'` — `'sourced'` (legacy) | `'ai_generated'` (Pivot.6+)
- `clips.script_id TEXT` (nullable FK)
- Relax `clips.video_id` to nullable
- `quota_usage.provider TEXT NOT NULL DEFAULT 'youtube'`

Idempotent migration script. New repo helpers: `insert_topic`, `seen_topics_in_window`, `mark_topic_scripted`, `insert_script`, `insert_generation_job`, `update_job_status`, `clips_for_generation_run`, `get_clip_with_script`.

**Acceptance:** Migration applies cleanly to existing `data/state.db`. All 457 existing tests still green. New DAL helper tests pass. `daily_upload.py --dry-run` on a legacy `quality_pass` clip still produces correct body (regression).

### Slice 4 — Hand-script tracer bullet · AFK · blocked by 2, 3

Wire `ai_gen` → `narration` → `assembler` into a single script `scripts/render_from_script.py` that takes a hand-written `{title, narration, shots[]}` JSON and produces one watchable MP4 in `output/pending/`. **No subtitles yet, no scripter, no RSS.** The tracer bullet that proves the new visual style + narration tuning + assembler refactor are correct.

Reuses the worktree spike pattern as a starting point. New narration tuning (`+10%/0Hz`). New provider (OpenRouter Kling 3.0). Assembler refactored from `editor/`: concat shots → mux narration → music duck → NVENC 1080×1920 → 2-pass −14 LUFS.

**Acceptance:** Hand-written test script produces one MP4 in `output/pending/` with clean editorial visuals from Kling, natural-paced narration from Edge TTS, no subtitles yet. User confirms aesthetic + audio.

### Slice 5 — Subtitles · AFK · blocked by 4

Whisper forced-align on the TTS mp3 → per-word timings → line-at-a-time ASS file (≤28 chars/line, broken on word boundaries, `\pos(540, 1500)`, 100 ms fade-in) → ffmpeg burn-in. Replace old karaoke writer; archive to `_karaoke_legacy.py`.

**Acceptance:** Same hand-script tracer clip now has readable, in-sync subtitles. User confirms timing + positioning.

### Slice 6 — Scripter (topic → script) · AFK · blocked by 3

`src/scripter/runner.py` consumes a topic (title + summary) → calls Ollama `qwen2.5:3b-instruct` JSON-mode → produces a pydantic-validated `{title, narration ≈40 words, shots[4], style_notes}`. Hook in first 5 words, 1–2 punchy stats, ends with teaser. Persists to `scripts` table. Policy gate runs on `narration` + `title`.

**Acceptance:** 5 hand-picked tech topics → 5 valid scripts. Eyeball pass on quality. Policy gate rejection rate ≤ 30%. Schema-validation failures recover via stricter retry.

### Slice 7 — RSS topic ingest · AFK · blocked by 3

`src/topic_ingest/` fetches mixed consumer + research RSS feeds (last 48 h) → dedups by URL hash AND normalized-title similarity (Levenshtein or word-set overlap, configurable threshold) → writes fresh topics to the `topics` table. Recommended-feeds setup doc delivered to user.

**Acceptance:** Given 3+ real RSS feed URLs, recent tech/AI items appear in `topics` table. Running the ingest twice within 48 h produces no duplicates. A reposted story (same title, different URL) is caught. Recommended-feeds doc handed off to user.

### Slice 8 — `gen_run.py` orchestrator · AFK · blocked by 4, 5, 6, 7

Wire it all: `topic_ingest` → `scripter` → `ai_gen` → `narration` → `assembler` → `policy_gate` → `quality_screen` → `slot_planner`. Run lock (`data/.weekly_run.lock`), alerts, `runs.md` writer. `--dry-run` and `--clips N` flags. Replaces the legacy `weekly_run.py`.

**Acceptance:** `python -m src.gen_run --dry-run --clips 1` walks the full pipeline with no DB writes. Real `--clips 3` produces 3 clips in `output/pending/` from real RSS-fed topics. Run lock contention exits cleanly.

### Slice 9 — Compliance refit (AI disclosure) · AFK · blocked by 3

Uploader templater branches on `content_kind='ai_generated'`: drops source/channel attribution, adds "Made with AI. For entertainment / educational use." footer + topic hashtag from upload tags. Research `altered_content` / `madeWithAi` v3 API field; set it where exposed; document manual Studio attestation fallback.

**Acceptance:** Dry-run uploader output JSON shows correct AI-gen description, no source/channel field, AI disclosure flag set (or fallback documented).

### Slice 10 — First live AI-generated upload · HITL · blocked by 8, 9

User drags one Slice 8 output from `output/pending/` to `output/approved/`. Runs `daily_upload.py`. Verifies the published Short carries AI disclosure visible in YouTube Studio.

**Acceptance:** 1 AI-generated Short live on the test channel. AI disclosure visible. No Content ID flag. Cost recorded in `quota_ledger` within ±5% of OpenRouter dashboard.

---

### Slice 11 — Steady-state publish cadence (Tue/Thu) · AFK · blocked by 8

User wants steady-state publishing on **Tuesdays and Thursdays only**. The current `slot_planner` allocates over consecutive days with no weekday filter, so this isn't expressible today. Add an `upload_weekdays` allowlist to config and a one-line weekday skip in the allocator grid loop; default to all 7 days for backward compatibility. Tune clips-per-publishing-day to the budget (~1/day → 2/week). Not on the Slice 10 critical path — the first live clip is decoupled to a near-term slot for mechanics validation.

**Acceptance:** With `upload_weekdays: [tue, thu]`, a weekly `slot_planner` run assigns `publish_at_utc` only to Tuesdays and Thursdays at the configured `upload_slots` times.

---

## Pivot.7 — Hybrid real-image + AI-transition Shorts (active)

> Locked in a design dialogue on 2026-05-25. Full spec: `docs/prds/pivot-7-hybrid-real-image-shorts.md`. Decomposed into Issues 15–21 (`docs/issues/`).

**Why:** the all-Kling Pivot.6 output reads as AI slop, renders recognizable entities (RTX 5090, OpenAI logo) as fakes, and the Edge voice sounds robotic.

**The change:** each clip becomes a **hybrid** — `real_image` shots (real sourced photos of recognizable entities, via hybrid licensed→web sourcing + Ken Burns motion) mixed with `ai_video` shots (Kling, kept only as connective/atmosphere transitions). The Scripter tags each of 4 shots. Narration moves to local **Kokoro** (Edge fallback). ~2 Kling shots/clip → **~half the Kling cost**. AI disclosure stays on.

- **P7.1 / Issue 15 — Tagged shot schema** · AFK · no blockers. Scripter emits `real_image`/`ai_video` shots; pure `normalize_shots`; back-compat for legacy string shots.
- **P7.2 / Issue 16 — Kokoro narration engine** · Interactive · no blockers. Kokoro-82M local behind `synthesize(...)`, Edge fallback, `bootstrap --check` for `espeak-ng`.
- **P7.3 / Issue 17 — `image_fetch` hybrid sourcing** · AFK · no blockers. `Source` ABC + Wikimedia/Openverse/logo/web(ddgs); cache + license audit; validation.
- **P7.4 / Issue 18 — Ken Burns builder** · AFK · blocked by 17. Still → `shot_XX.mp4` (blurred-bg 9:16 fill + zoompan), pure argv builder.
- **P7.5 / Issue 19 — Hybrid assembler** · AFK · blocked by 15, 17, 18. Kind-aware routing in `_generate_clip` + optional `xfade` crossfades; cost counts ai_video only.
- **P7.6 / Issue 20 — End-to-end hybrid spike** · Interactive · blocked by 15–19. One real topic → mixed clip → eyeball + cost reconciliation + HITL sign-off.
- **P7.7 / Issue 21 — Config/retention/compliance/docs cleanup** · AFK · blocked by 20. Re-tighten cost ceilings; image-cache TTL; confirm disclosure; update docs.

**Acceptance (Pivot.7):** one hybrid Short with real entity images + AI transitions (no synthetic person), natural Kokoro voice, per-clip Kling cost ≈ half the 4-shot baseline, AI disclosure intact, docs updated to the hybrid model.

---

## Out of scope for Pivot.6

- TikTok / Instagram cross-posting (still YouTube-only)
- Web dashboard
- Subject tracking / face-aware crop
- Thumbnail auto-generation
- Quota-increase audit form (still future operations task)
- Cleanup of retired-module tables (`videos`, `niche_baselines`, `discovery_attempts`) — inert, will drop in a future housekeeping pivot

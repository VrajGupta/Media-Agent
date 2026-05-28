# Phase: development
**Project:** Media-Agent (Pivot.6)
**Status:** in-progress
**Last updated:** 2026-05-28

## Objective

Implement all 10 slices of the Pivot.6 AI-generated pipeline: RSS ingest → topic scoring → script generation → video generation → narration → assembly → upload. Slices 1–9 are complete; Slice 10 (first live upload) is double-blocked pending two manual unblock steps.

## Key Decisions

- **Pipeline order for free phase:** Slices 3→7→6 first. Produce real Ollama scripts and validate quality before spending on Kling.
- **Slice 10 candidate script locked:** `7cb41305-b39b-4cc2-855b-067e03549d25` ("Corti's Symphony Beats OpenAI in Medical Speech Recognition", 31 words, VentureBeat). Replaced `d0da493f` (Android Apps script) after QC found hallucinated "tripling" stat.
- **Block A (Slice 10):** Migration `scripts/migrate_pivot_6_3.py` committed but never applied to live `data/state.db`. Run with `--dry-run` first, then live. Back up DB first.
- **Block B (Slice 10):** No assembled MP4 in `output/pending/`. 8 paid shots from 2026-05-21 spike (`data/ai_gen_shots/spike_2026-05-21/`) need to be run through assembler manually.
- **Shot order swap:** Shot 0 ↔ shot 1 swapped in assembler so thumbnail is whiteboard-style frame, not synthetic-CEO frame. Compliance safety.
- **`--dry-run` mandatory pre-flight:** Review full `videos.insert` JSON before any live upload send.
- **Ollama local-first:** All text AI (scoring, script generation) runs locally. Zero cost. OpenRouter only for Kling video generation.
- **qwen2.5:3b workarounds (known defects):**
  - Mojibake on smart-quotes (`Corti's` → `Corti�s`). Workaround: `src/scripter/sanitize.py` strips U+FFFD before TTS.
  - Hallucinated stats in tech-news scripts. Workaround: human-review every script before Slice 10 ships.
  - Weak hooks scored below `quality_floor: 6.0` are auto-rejected.
  - Must NOT name real living people in shot prompts (compliance — Kling generates synthetic person under real name).
- **`publishAt` shape:** `private` + scheduled → auto-flip to public. Avoids needing live API re-call.
- **gen_run.py run lock:** `data/.gen_run.lock` (msvcrt advisory). Prevents concurrent weekly runs.

## Accomplishments

- [2026-05-18] **Slice 1 (Niche lock):** CLAUDE.md + agents.md + docs updated. HITL complete.
- [2026-05-21] **Slice 2 (Kling spike):** 8 shots generated at `data/ai_gen_shots/spike_2026-05-21/`. H2/H3/H4/H5 PASS. Auth fix pushed (`fcf2385` — Bearer auth for OpenRouter URLs). Slices 4/5/8/9 unblocked.
- [2026-05-18] **Slice 3 (Schema migration):** Ticket 01 complete. 27 tests green. `scripts/migrate_pivot_6_3.py` idempotent.
- [2026-05-19] **Slice 4 (Tracer bullet):** `scripts/generate_clip.py` — hand-script → Kling shots → assembler → MP4. End-to-end without subtitles.
- [2026-05-19] **Slice 5 (Subtitles):** `src/subtitles/line_ass.py` — line-at-a-time ASS burn. ≤28 chars/line, `\pos(540,1500)`, 100ms fade.
- [2026-05-18] **Slice 6 (Scripter):** Tickets 03/04/05 complete. `run_stage_a/b/c` with Ollama qwen2.5:3b. 37 tests green.
- [2026-05-18] **Slice 7 (RSS ingest):** Ticket 02 complete. `fetch_unscripted_topics()` with feedparser + Jaccard dedup. 16 tests green.
- [2026-05-22] **Slice 8 (gen_run orchestrator):** `src/gen_run.py` — full pipeline CLI with run lock, DB run row, per-stage lambda pipeline. Commit `82ce0d1`. 10 tests green.
- [2026-05-22] **Slice 9 (AI disclosure compliance):** `src/uploader/templater.py` + `src/uploader/insert_body.py` AI-gen branch. `status.containsSyntheticMedia=true` on all `ai_generated` uploads. Commit `f871df8`. Tests green.
- [2026-05-23] **Slice 10 (First live upload):** Operational plan locked. BLOCKED — two manual unblock steps required before execution.

- [2026-05-28] Dry-run verify: `gen_run --dry-run --clips 1` exit 0; live MP4 review pending operator.
- [2026-05-27] **Issues 30–34 (ADR-0004):** curated feeds, niche gate, significance+HN, Ken Burns fix, doc reconciliation. 55 tests green.
- [2026-05-27] **Issue 31 (Niche gate at ingest):** `classify_niche` reject-before-persist; 48h→96h low-yield widen.

## Artifacts

| Artifact | Path | Notes |
|---|---|---|
| Orchestrator | `src/gen_run.py` | Pivot.6 weekly run — topic→script→gen→assemble |
| Daily uploader | `src/daily_upload.py` | Human-review gate + recovery + orphan fence |
| RSS ingest | `src/topic_ingest/runner.py` | feedparser + Jaccard dedup |
| Scripter | `src/scripter/runner.py` | Stage A/B/C — topic scoring → script generation → quality scoring |
| Ollama callables | `src/scripter/ollama_fns.py` | 4 callable factories (DI-injected) |
| Sanitizer | `src/scripter/sanitize.py` | qwen2.5:3b U+FFFD mojibake fix |
| AI gen client | `src/ai_gen/openrouter_kling.py` | OpenRouter Kling 3.0 production provider |
| Narration | `src/narration/synth.py` | Edge TTS en-US-GuyNeural |
| Aligner | `src/narration/aligner.py` | Whisper forced-align word timings |
| Assembler | `src/assembler/build.py` + `normalize.py` | Shot normalize → Stitch (xfade/concat filter) → NVENC/libx264 1080×1920 |
| Subtitles | `src/subtitles/line_ass.py` | Line-at-a-time ASS writer |
| Shot gen CLI | `scripts/generate_clip.py` | Ad-hoc clip generation |
| Spike shots | `data/ai_gen_shots/spike_2026-05-21/` | 8 shots — ready for assembler |

## Sessions

- Slice 1 + 3 (niche lock + schema) — 2026-05-18
- Slice 2 spike (Kling test) — 2026-05-21, auth fix commit `fcf2385`
- Slice 4/5 (tracer + subtitles) — 2026-05-19/2026-05-20
- Slice 6/7 (scripter + RSS) — 2026-05-18/2026-05-20, Tickets 02-05
- Slice 8 (gen_run) — 2026-05-22, commit `82ce0d1`
- Slice 9 (compliance refit) — 2026-05-22, commit `f871df8`
- Slice 10 operational plan — 2026-05-23
- [issue-22-shot-normalization-tdd](.sessions/2026-05-26__issue-22-shot-normalization-tdd/handoff.md) — 2026-05-26, commit `bca0095`

## Open Items

- [2026-05-24] Slice 10 uploaded (`9lpL8kuLX08`); T+1h Studio gate + T+48h stability (Issue 13) remain.
- [2026-05-24] Issue 11 + Issue 14 code shipped; `gen_run.py` unattended weekly run not live-verified.
- [2026-05-26] **Pivot.7 hybrid spike:** assembly fix shipped; live `scripts/spike_hybrid.py` run + HITL sign-off (Issue 20) pending.
- Next grill after Slice 10 `[x]`: scripter quality (deferred from 2026-05-23 handoff).

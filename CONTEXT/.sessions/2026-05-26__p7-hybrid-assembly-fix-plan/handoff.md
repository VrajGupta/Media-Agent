# Handoff — p7-hybrid-assembly-fix-plan
**Date:** 2026-05-26
**Project:** media-agent (Pivot.7)
**Working directory:** C:\Users\cryptix\Desktop\Work\Media-Agent-main

## What was accomplished this session

Diagnosed the Pivot.7 hybrid-spike assembly failure, then ran
`/grill-with-docs` → `/to-prd` → `/to-issues` to turn the diagnosis into a
ready-to-implement plan. **No production code written** (planning session).

- **Root cause confirmed, not guessed.** `ffprobe` shows Kling 3.0 std emits
  **720×1280 @ 24fps** (not the "1080×1920" CLAUDE.md claims); Ken Burns renders
  **1080×1920 @ 30fps**. The assembler feeds these mismatched shots straight into
  `xfade` with no normalization. Reproduced locally (zero API cost): the mixed-res
  xfade fails with `error -22 (Invalid argument)` — and **−22 unsigned 32-bit =
  4294967274**, the exact rc the spike reported. A `scale→pad→setsar→fps→format→settb`
  prefix per input makes the same command succeed (`rc=0`).
- The failure is **not** crossfade-specific: the concat-demuxer fallback fails on
  mixed resolution too, so `crossfade_enabled:false` would not have fixed it.
- Locked the fix decisions and recorded them: see grill record + ADR below.
- Sharpened the glossary with **Stitch** and **Shot normalization** (`CONTEXT/CONTEXT.md`).
- Published PRD `docs/prds/p7-fix-hybrid-assembly-normalization.md` and issues
  **22–25** (`docs/issues/`), all `ready-for-agent`.

## Current state

- **Pivot.6 Slices 1–9 complete; Slice 10 uploaded** (`9lpL8kuLX08`, 720×1280) — gates
  still per prior handoff. Slice 11 cadence code shipped.
- **Pivot.7 (commit `0e533af`)** introduced hybrid real-image + AI-transition shots.
  The hybrid end-to-end spike (Issue 20, `scripts/spike_hybrid.py`) gets through
  scripting → Kling → Kokoro → Whisper-align (CPU fallback) → **fails at assembly**.
  This plan fixes that.
- **Working tree (uncommitted):** `src/narration/aligner.py` carries the CUDA→CPU
  Whisper fallback from the prior session. Not yet committed/pushed. Commit it
  alongside the Issue 24 encode fallback (same pattern).
- `config.yaml` has `assembler.crossfade_enabled: true`, `output_resolution:[1080,1920]`,
  `nvenc_preset:p5`, `nvenc_cq:23`. The assembler **ignores** `output_resolution` today —
  Issue 22 makes it consume it. No `output_fps` key yet (Issue 22 adds it).
- Banked Kling shots for repro/tests: `data/ai_gen_shots/spike_2026-05-21/7cb41305_shot_{0..3}.mp4`
  (720×1280 @ 24fps).

## Immediate next action

**Implement Issue 22** (`docs/issues/22-canonical-shot-normalization.md`): create the
pure `src/assembler/normalize.py` deep module, route every shot through it in
`src/assembler/build.py` (xfade chain + crossfade-off concat-filter), add `video_codec`
+ `resolution`/`fps` params, add `output_fps` config, wire `gen_run._generate_clip`, and
land the ffmpeg-guarded mixed-res integration test (synthesize 720+1080 fixtures via
`lavfi`, assert `rc=0` + 1080×1920 output). This is the defect fix. `/tdd` fits — the
acceptance integration test is the natural RED.

## Open decisions / blockers

- **No open design decisions** — all locked in ADR-0002 + the grill record. User
  delegated granularity ("do what you think is recommended"); issue breakdown was
  published without a blocking approval round — adjust 22–25 if the granularity feels off.
- **No git remote configured in this working copy** (per prior handoffs) — push remains
  blocked until `git init`/remote is set. Verify before attempting to push.
- Issue 24's libx264 fallback must fire **only** on encoder-attributable failures; a
  filtergraph error (like this very defect) must still fail fast — don't mask it.

## Artifacts created this session

| Artifact | Path | Notes |
|---|---|---|
| Grill record | `CONTEXT/Grilling/2026-05-26-hybrid-assembly-xfade.md` | Verified evidence + 6 locked decisions |
| ADR | `docs/adr/0002-canonical-shot-normalization-in-assembler.md` | Decision of record |
| Glossary terms | `CONTEXT/CONTEXT.md` | **Stitch**, **Shot normalization** added |
| PRD | `docs/prds/p7-fix-hybrid-assembly-normalization.md` | `ready-for-agent`, 22 user stories |
| Issue 22 | `docs/issues/22-canonical-shot-normalization.md` | The fix (AFK, no blockers) |
| Issue 23 | `docs/issues/23-render-from-script-canonicalize.md` | Pure-AI 1080p (AFK, blocked by 22) |
| Issue 24 | `docs/issues/24-assembly-stderr-and-cpu-fallback.md` | stderr + CPU fallback (AFK, blocked by 22) |
| Issue 25 | `docs/issues/25-correct-kling-resolution-docs.md` | Doc fix (AFK, no blockers) |

## Skills used this session

| Skill | File | Purpose |
|---|---|---|
| /grill-with-docs | `C:\Users\cryptix\.claude\skills\grill-with-docs\SKILL.md` | Diagnosed + locked fix decisions; glossary + ADR-0002 + grill record |
| /to-prd | `C:\Users\cryptix\.claude\skills\to-prd\SKILL.md` | PRD `p7-fix-hybrid-assembly-normalization` |
| /to-issues | `C:\Users\cryptix\.claude\skills\to-issues\SKILL.md` | Issues 22–25 |
| /handoff | `C:\Users\cryptix\.claude\skills\handoff\SKILL.md` | This document |

## Suggested skills for next session

Next session is coding the fix:
- `/tdd` → `C:\Users\cryptix\.claude\skills\tdd\SKILL.md` — Issue 22's mixed-res
  integration test + the normalize.py unit tests are clean RED→GREEN targets.
- `/handoff` → `C:\Users\cryptix\.claude\skills\handoff\SKILL.md` — at session end.

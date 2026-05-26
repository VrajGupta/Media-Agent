# ADR-0002 — Canonical shot normalization in the assembler

**Status:** Accepted
**Date:** 2026-05-26
**Context:** Surfaced during the Pivot.7 hybrid-assembly grilling session
(`CONTEXT/Grilling/2026-05-26-hybrid-assembly-xfade.md`).

## Context

Pivot.7 introduced **hybrid Clips** that mix two **Shot kinds**:

- **Real-image shots** — Ken Burns motion over a sourced still. Rendered locally at
  **1080×1920 @ 30fps, yuv420p, SAR 1:1** (`src/assembler/ken_burns.py`).
- **AI-video shots** — downloaded from Kling 3.0 std, which actually emits
  **720×1280 @ 24fps** (verified by `ffprobe`; CLAUDE.md's "native 1080×1920"
  claim was wrong).

The assembler's filtergraph (`src/assembler/build.py`) fed each shot straight into
`xfade` (crossfade on) or the **concat demuxer** (crossfade off) with no per-input
conditioning. `xfade` requires both inputs to share resolution, pixel format, frame
rate, and timebase; the concat demuxer requires identical stream parameters. A hybrid
Clip violates both. The hybrid spike failed at assembly with
`ffmpeg failed (rc=4294967274)`.

Reproduced locally: xfade of a 1080×1920 clip against a real 720×1280 Kling shot
errors with `First input link main parameters (size 1080x1920) do not match … (size
720x1280) … error code: -22 (Invalid argument)`. **`-22` unsigned 32-bit =
4294967274** — the exact reported rc. A `scale→pad→setsar→fps→format→settb` prefix on
each input made the same command succeed.

The config already declares the intended canonical size (`output_resolution:
[1080,1920]`); the assembler simply never applied it to its inputs.

## Decision

**Every shot is normalized to a single canonical format inside the assembler
filtergraph before it is stitched.** Canonical format:
**1080×1920, 30fps, yuv420p, SAR 1:1** (resolution from `cfg.output_resolution`).

Concretely:

1. Each input `[i:v]` is prefixed with
   `scale=W:H:force_original_aspect_ratio=decrease, pad=W:H:(ow-iw)/2:(oh-ih)/2,
   setsar=1, fps=30, format=yuv420p, settb=AVTB` before any xfade/concat node.
2. The **crossfade-off** multi-input path moves from the **concat demuxer** to the
   **concat filter**, so it normalizes identically. (Disabling crossfade is therefore
   a valid fallback, but it was never the fix — concat-demuxer fails on mixed
   resolution the same way.)
3. Normalization is applied uniformly to **all** Clips, pure-AI included — one path,
   one output resolution (true 1080×1920), no second code path.

## Consequences

**Positive:**
- Hybrid Clips assemble. Pure-AI Clips upgrade from 720×1280 to true 1080×1920.
- The provider abstraction holds: a future generator at any resolution/fps just
  gets normalized — no downstream change.
- crossfade on/off are both valid; crossfade is decoupled from correctness.

**Negative:**
- Kling 720→1080 is interpolated upscale — no real detail gained, slightly softer
  than native 1080 real-image shots within the same Clip.
- 24→30fps on AI-video shots duplicates frames (no motion interpolation).
- Every shot is re-encoded in the assembler pass even when already canonical
  (negligible at 2–3 clips/week).

**Mitigations:**
- A higher-resolution Kling tier is available later as a pure cost decision; the
  normalization step makes that swap invisible to the rest of the pipeline.

## Alternatives considered

1. **Pre-normalize each shot to a temp MP4 in a separate ffmpeg pass, then
   concat/xfade uniform files.** Rejected: extra passes, temp-file lifecycle, double
   encode for no quality gain over in-graph normalization.
2. **Disable crossfade (`crossfade_enabled: false`).** Rejected: doesn't fix hybrid
   — the concat demuxer fails on mixed resolution too. Misdiagnoses the messenger
   (xfade) as the cause.
3. **Downscale everything to 720×1280** to match Kling. Rejected: discards genuine
   detail from high-res real-image stills; ships sub-1080p Shorts.
4. **Request 1080 from Kling.** Rejected here: std tier is 720×1280; higher tiers are
   a separate cost decision, not a fix for this defect.

## References

- `CONTEXT/Grilling/2026-05-26-hybrid-assembly-xfade.md` — full evidence + decisions.
- `CONTEXT/CONTEXT.md` — **Stitch**, **Shot normalization** glossary terms.
- `src/assembler/build.py`, `src/assembler/ken_burns.py`, `src/gen_run.py`.

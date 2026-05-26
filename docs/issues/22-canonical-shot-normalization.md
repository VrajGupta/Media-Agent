# Issue 22 — Canonical shot normalization → hybrid Clip stitches

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/p7-fix-hybrid-assembly-normalization.md` — Pivot.7 Fix: Canonical shot
normalization in the assembler. Decisions of record:
`docs/adr/0002-canonical-shot-normalization-in-assembler.md`.

## What to build

The core defect fix. A hybrid **Clip** mixes **AI-video shots** (Kling std,
720×1280 @ 24fps) and **Real-image shots** (Ken Burns, 1080×1920 @ 30fps). The
assembler feeds these into `xfade` with no **Shot normalization**, so assembly fails
with `error -22 (Invalid argument)` (rc `4294967274`). Introduce per-input **Shot
normalization** so every **Shot** is conformed to the canonical format — **1080×1920,
30fps, yuv420p, SAR 1:1** — inside the filtergraph before it is **Stitched**.

End-to-end behavior:

1. A new pure module owns "what canonical means": given an input index + target
   width/height/fps, it returns the filter chain
   `scale=w:h:force_original_aspect_ratio=decrease, pad=w:h:(ow-iw)/2:(oh-ih)/2,
   setsar=1, fps=fps, format=yuv420p, settb=AVTB`, labeled to a normalized output pad.
   This chain is the one verified to make the failing xfade succeed.
2. The **xfade** chain consumes the normalized labels rather than raw `[i:v]`.
3. The crossfade-**off** multi-input path uses the **concat filter** on normalized
   inputs (`concat=n=N:v=1:a=0`) instead of the strict **concat demuxer** — so
   disabling crossfade is a real fallback that also survives mixed **Shot kinds**.
   The multi-input branch always passes one `-i` per shot; the concat-demuxer path is
   retained only for the single-input / legacy `shot_paths=None` case.
4. The argv builder takes the target resolution + fps (canonical values), plus a
   `video_codec` parameter (default `h264_nvenc`) so a later slice can request a CPU
   encode. fps becomes a single declared config value (`output_fps`, default 30)
   rather than the literal `30` hardcoded today.
5. The hybrid orchestrator passes `cfg.output_resolution` + `cfg.output_fps` into the
   builder, so the hybrid spike assembles a watchable 1080×1920 **Clip**.

Per ADR-0002, normalization applies to all Clips, so pure-AI Clips assembled by the
hybrid orchestrator also output 1080×1920 (the standalone `render_from_script` script
is wired separately in Issue 23).

## Acceptance criteria

- [ ] A new pure function returns the canonical per-input filter chain for a given
      index/width/height/fps, ending in a normalized output label; covered by a unit
      test asserting the exact string (`scale`, centered `pad`, `setsar=1`, `fps`,
      `format=yuv420p`, `settb`).
- [ ] The xfade chain references the normalized labels, never raw `[i:v]` into xfade;
      asserted for 2, 3, and 4 shots; xfade offsets unchanged from today.
- [ ] Crossfade-off multi-input builds a normalized **concat filter**
      (`concat=n=N:v=1:a=0`) and emits one `-i` per shot with no `-f concat`; audio
      filter input indices remain correct.
- [ ] `build_assembler_argv` accepts `resolution` + `fps` + `video_codec`; emits
      `-c:v {video_codec}`; the single-input legacy filtergraph path is byte-identical
      to today (regression guard).
- [ ] `output_fps` config field added (default 30) and threaded from `gen_run` into
      the builder alongside `output_resolution`.
- [ ] **Acceptance integration test (ffmpeg-guarded):** synthesize a 720×1280@24 and a
      1080×1920@30 fixture via `lavfi` (no API), build the real argv with
      `video_codec="libx264"`, run ffmpeg, assert `rc==0` and `ffprobe` reports a
      1080×1920 output. Reproduces the original failure mode and proves it fixed.
- [ ] Running `scripts/spike_hybrid.py` on a topic assembles a 1080×1920 hybrid
      **Clip** into `output/pending/` (operator-facing check).
- [ ] Unit tests follow the argv/filtergraph-string assertion style in
      `tests/assembler/test_build.py`; all green via the project's standard runner.

## Blocked by

None — can start immediately. Root cause confirmed and fix verified locally (see PRD).

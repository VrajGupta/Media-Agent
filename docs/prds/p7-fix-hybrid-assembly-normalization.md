# Pivot.7 Fix — Canonical shot normalization in the assembler

**Status:** ready-for-agent
**Project:** Media-Agent Pivot.7
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-05-26
**Source session:** /grill-with-docs → /to-prd
**Defect surfaced by:** Issue 20 (hybrid end-to-end spike, `scripts/spike_hybrid.py`)
**Blocks:** First hybrid ship; any further Pivot.7 forward work
**Blocked by:** Nothing — root cause confirmed, fix verified locally
**Decisions of record:** `docs/adr/0002-canonical-shot-normalization-in-assembler.md`, `CONTEXT/Grilling/2026-05-26-hybrid-assembly-xfade.md`

---

## Problem Statement

As the channel owner I ran the Pivot.7 hybrid spike end-to-end. Scripting, Kling
generation, Kokoro narration, and Whisper alignment all succeeded — then the final
ffmpeg assembly step crashed with `ffmpeg failed (rc=4294967274)` and produced no
**Clip**. I cannot ship a hybrid Short until the **Stitch** step works.

The proximate failure is in the crossfade (`xfade`) filtergraph, but the real cause
is deeper: a hybrid **Clip** mixes two **Shot kinds** at two different formats.
**AI-video shots** come from Kling 3.0 std at **720×1280 @ 24fps**; **Real-image
shots** are Ken-Burns-rendered at **1080×1920 @ 30fps**. The assembler feeds these
heterogeneous **Shots** straight into `xfade` with no **Shot normalization**, and
`xfade` requires both inputs to share resolution, frame rate, pixel format, and
timebase. The same mismatch breaks the concat-demuxer fallback, so simply turning
crossfade off does **not** fix it.

This also exposed two latent problems: (1) CLAUDE.md's locked decisions claim Kling
emits "native 1080×1920", which is false (std is 720×1280); and (2) when ffmpeg
fails, only the return code is surfaced — the stderr that would have diagnosed this
in seconds was discarded, forcing a manual reproduction to confirm the cause.

### Confirmed evidence

- `ffprobe` on a banked Kling shot: `h264, 720x1280, yuv420p, 24fps`.
- `ken_burns.py` renders `1080×1920, 30fps, yuv420p, SAR 1:1`.
- Local reproduction (zero API cost) — `xfade` of a 1080×1920 clip against the real
  720×1280 Kling shot: `First input link main parameters (size 1080x1920) do not
  match the corresponding second input link xfade parameters (size 720x1280) … error
  code: -22 (Invalid argument)`. **`-22` unsigned 32-bit = 4294967296 − 22 =
  4294967274**, the exact reported rc.
- Same command with a `scale→pad→setsar→fps→format→settb` prefix on each input:
  `rc=0`, valid output. Fix verified.

## Solution

Introduce **Shot normalization** in the assembler: every **Shot** is conformed to one
canonical format — **1080×1920, 30fps, yuv420p, SAR 1:1** (resolution from the
existing `cfg.output_resolution`) — inside the filtergraph, before it is **Stitched**.
This is applied to **all Clips**, pure-AI included, so there is one **Stitch** path and
one output resolution. Per ADR-0002.

Concretely, from the user's perspective:

1. The hybrid spike (and `gen_run`) assembles a watchable hybrid **Clip** at true
   1080×1920 with the crossfade intact.
2. Pure-AI **Clips** also output true 1080×1920 (upgraded from the 720×1280 that
   Slice 10 shipped), with no second code path.
3. Turning `crossfade_enabled` off is a genuine fallback that also works (it now
   normalizes via the concat filter instead of the strict concat demuxer).
4. When any ffmpeg step fails, the stderr tail is written to the logs, so the next
   failure is diagnosable without a manual reproduction.
5. If the NVENC encoder is unavailable at runtime (this machine's CUDA stack is
   demonstrably fragile — the aligner already fell back to CPU this session), the
   assembler retries the encode on CPU (`libx264`) instead of failing the run.
6. The docs stop claiming Kling output is 1080×1920.

## User Stories

1. As the channel owner, I want the hybrid spike to finish assembly and write a
   watchable **Clip** to `output/pending/`, so that I can validate Pivot.7 visuals,
   voice, and cost end-to-end.
2. As the channel owner, I want a hybrid **Clip** that mixes a **Real-image shot** and
   an **AI-video shot** to **Stitch** without error, so that the hybrid format is
   actually shippable.
3. As the channel owner, I want every finished **Clip** to be true 1080×1920, so that
   my Shorts meet the platform's preferred resolution rather than an upscaled 720p.
4. As the channel owner, I want the **AI-video shots'** 720×1280 frames upscaled to fit
   the canonical 1080×1920 frame, so that they sit in the same **Clip** as 1080
   **Real-image shots** without letterboxing or a size-mismatch crash.
5. As the channel owner, I want **Real-image shots** kept at their native 1080×1920
   rather than downscaled to Kling's 720, so that genuinely high-resolution stills
   keep their detail.
6. As the channel owner, I want the crossfade between **Shots** preserved after the
   fix, so that the **Clip** keeps its intended polish.
7. As the channel owner, I want turning `crossfade_enabled` off to also produce a
   valid hybrid **Clip**, so that I have a working fallback if a crossfade ever
   misbehaves.
8. As the channel owner, I want pure-AI **Clips** (four Kling **Shots**, no
   **Real-image shot**) to keep assembling correctly after the change, so that the
   Slice 10 path is not regressed.
9. As the channel owner, I want clips of mixed **Shot** counts and orders to assemble,
   so that the 2×real + 2×AI hybrid ratio is not the only layout that works.
10. As the channel owner, when an ffmpeg step fails, I want the stderr tail recorded in
    the logs/alerts, so that I (or an agent) can diagnose the next failure in seconds
    instead of reproducing it by hand.
11. As the channel owner, if the GPU encoder (NVENC) is unavailable at runtime, I want
    the assembler to fall back to a CPU encode, so that a flaky CUDA stack degrades the
    run instead of failing it — mirroring the aligner's existing CPU fallback.
12. As the channel owner, I want the CPU-encode fallback to only trigger on an
    encoder-level failure, so that a genuine filtergraph error still fails loudly
    instead of being masked by a pointless retry.
13. As the channel owner, I want the canonical resolution to come from
    `cfg.output_resolution` (already `[1080,1920]`), so that one config value controls
    both the Ken Burns render and the final **Stitch**.
14. As the channel owner, I want the canonical frame rate to be a single declared value
    rather than a number hardcoded in three places, so that changing cadence is a
    one-line config edit.
15. As a developer, I want the per-input normalization expressed as one pure,
    independently testable function, so that "what canonical means" lives in exactly
    one place and is asserted directly.
16. As a developer, I want the **xfade** chain to consume the normalized input labels
    rather than raw `[i:v]`, so that the offsets are computed on uniform-framerate
    streams.
17. As a developer, I want the crossfade-off multi-input path to use the concat
    *filter* on normalized inputs instead of the concat *demuxer*, so that it no longer
    requires byte-identical input parameters and survives mixed **Shot kinds**.
18. As a developer, I want a regression test that actually **Stitches** a 720×1280
    fixture and a 1080×1920 fixture and asserts `rc=0` plus a 1080×1920 output, so that
    this exact defect can never silently return.
19. As a developer, I want the single-input (legacy) filtergraph path to remain
    behaviorally unchanged, so that the change is additive and low-risk.
20. As a developer reading CLAUDE.md and agents.md, I want them to state Kling std emits
    720×1280 and the assembler normalizes to 1080×1920, so that nobody re-derives the
    false "native 1080×1920" assumption that hid this bug.
21. As a developer extending the pipeline to another generator (Pika, MiniMax,
    Seedance) at any resolution, I want normalization to absorb that difference, so that
    swapping providers needs no assembler change.
22. As the channel owner, I want a one-line config kill comparable to today's
    `crossfade_enabled` to remain, so that the fix doesn't remove existing knobs.

## Implementation Decisions

All decisions are locked in `docs/adr/0002` and the grill record. Summary:

1. **Canonical format = 1080×1920, 30fps, yuv420p, SAR 1:1.** Resolution from
   `cfg.output_resolution`. Frame rate becomes a single declared value (new
   `output_fps`, default `30`) rather than the literal `30` currently hardcoded in
   `build.py` and defaulted in `ken_burns.py`.
2. **Per-input normalization is a new deep module.** A pure function returns the filter
   chain for one input:
   `scale={w}:{h}:force_original_aspect_ratio=decrease, pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,
   setsar=1, fps={fps}, format=yuv420p, settb=AVTB`, labeled to a normalized output pad.
   It knows nothing about xfade, concat, audio, or codecs — only "make one input
   canonical." This is the testable seam.
3. **xfade chain consumes normalized labels.** `_build_crossfade_video_chain` chains the
   normalized `[vn{i}]` pads, not raw `[i:v]`. The final `[v_comp]fps=30` tail is
   redundant after per-input fps but harmless; it may stay or be folded into the ASS
   burn step.
4. **Crossfade-off multi-input path switches to the concat filter.** When `shot_paths`
   has >1 entry and crossfade is disabled, build `[vn0][vn1]…concat=n=N:v=1:a=0[v_comp]`
   on normalized inputs instead of using `-f concat -i list.txt`. The concat *demuxer*
   path is retained only for the single-input / no-`shot_paths` legacy case.
5. **All Clips normalize.** Both `gen_run._generate_clip` and
   `scripts/render_from_script.py` pass `resolution` + `fps` and feed `shot_paths`
   through the normalized filtergraph, so pure-AI Clips also output 1080×1920. The
   `render_from_script` concat-demuxer path is replaced by the normalized filter path.
6. **ffmpeg stderr is persisted on failure.** The `run_ffmpeg` result already carries
   stderr; on a non-zero rc or zero-byte output, `gen_run` (and the spike runner) write
   the stderr tail to `logs/` and emit an alert, instead of raising with only the rc.
7. **CPU-encode fallback.** `build_assembler_argv` accepts a `video_codec` parameter
   (default `h264_nvenc`). On an encode-attributable failure, the caller retries once
   with `video_codec="libx264"` (and drops `-preset/-cq` for the appropriate libx264
   equivalents `-preset/-crf`). The fallback fires only when stderr indicates an encoder
   problem — a filtergraph error (like this defect) still fails fast. Mirrors the
   aligner CUDA→CPU fallback pattern.
8. **Docs corrected in-scope.** CLAUDE.md "Locked decisions" (vertical layout / Kling
   native res) and agents.md assembler section are updated to: Kling std emits
   720×1280; the assembler normalizes every **Shot** to canonical 1080×1920.

### Modules built or modified

| # | Module | Kind | Interface |
|---|--------|------|-----------|
| 1 | `src/assembler/normalize.py::normalize_input_chain` | **New, pure (deep)** | `(index: int, *, width: int, height: int, fps: int, out_label: str \| None = None) -> str`. Returns the per-input filter chain string ending in `[vn{index}]`. No ffmpeg, no I/O. |
| 2 | `src/assembler/build.py::_build_crossfade_video_chain` | Modified, pure | Chains normalized `[vn{i}]` labels (from #1) into xfade instead of raw `[i:v]`. Takes `width/height/fps`. |
| 3 | `src/assembler/build.py::_build_filtergraph` | Modified, pure | Adds a normalized **concat-filter** branch for crossfade-off multi-input; threads `width/height/fps`. |
| 4 | `src/assembler/build.py::build_assembler_argv` | Modified, pure | New kwargs `resolution: tuple[int,int]`, `fps: int = 30`, `video_codec: str = "h264_nvenc"`. Emits `-c:v {video_codec}` with codec-appropriate quality flags. Multi-input branch always uses `-i` per shot (no concat demuxer). |
| 5 | `src/gen_run.py::_generate_clip` | Modified | Passes `resolution=tuple(cfg.output_resolution)`, `fps=cfg.output_fps`; on assembly failure persists `result.stderr` tail + emits alert; retries once with `video_codec="libx264"` on encoder-attributable failure. |
| 6 | `scripts/render_from_script.py` | Modified | Same normalization wiring (resolution/fps/shot_paths through the filter path); drops the concat-demuxer call. |
| 7 | `src/config_loader/loader.py` (+ `config.yaml`) | Modified | Add `output_fps: int = 30` (top-level, next to `output_resolution`). |
| 8 | `CLAUDE.md`, `agents.md` | Docs | Correct the Kling-resolution claim; document the normalization step. |

### Canonical filter chain (decision-bearing snippet)

From the verified local reproduction — the exact per-input chain that made the failing
xfade succeed. `{w}/{h}` from `cfg.output_resolution`, `{fps}` from `cfg.output_fps`:

```
[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,
       pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,
       setsar=1,fps={fps},format=yuv420p,settb=AVTB[vn{i}]
```

`force_original_aspect_ratio=decrease` + centered `pad` keeps every **Shot** aspect-
correct and pillar/letter-boxed into the canonical frame rather than stretched — both
720×1280 and 1080×1920 sources are already 9:16, so in practice this is a clean
upscale with no bars, but the pad guards any future non-9:16 source.

## Testing Decisions

### What makes a good test here

Existing assembler tests (`tests/assembler/test_build.py`) assert against the **built
argv / filtergraph string** of pure functions — never by invoking ffmpeg. The new unit
tests follow that discipline: assert the produced filter string and argv, not internal
state. One integration test is the exception — it must actually run ffmpeg to prove the
defect is fixed, and is guarded on `shutil.which("ffmpeg")`.

### Modules under test

| Module | Test file | Asserts |
|--------|-----------|---------|
| `normalize_input_chain` (#1) | `tests/assembler/test_normalize.py` (new) | Exact filter string for given index/width/height/fps; output label `[vn{i}]`; contains `scale`, centered `pad`, `setsar=1`, `fps={fps}`, `format=yuv420p`, `settb`. |
| `_build_crossfade_video_chain` (#2) | extend `tests/assembler/test_build.py` | Each input is normalized (chain references `[vn{i}]`, never raw `[i:v]` into xfade); xfade offsets unchanged; N=2,3,4 shot counts. |
| `_build_filtergraph` crossfade-off (#3) | extend `tests/assembler/test_build.py` | Multi-input + crossfade off → normalized **concat filter** present (`concat=n=N:v=1:a=0`), and **no** reliance on a concat-demuxer list; audio chain indices still correct. |
| `build_assembler_argv` (#4) | extend `tests/assembler/test_build.py` | Multi-input path emits one `-i` per shot and no `-f concat`; `-c:v` reflects `video_codec`; `libx264` variant emits libx264 quality flags; single-input legacy path byte-identical to today. |
| End-to-end **Stitch** (#1–#4) | `tests/assembler/test_assemble_mixed_res.py` (new, ffmpeg-guarded) | Synthesize a 720×1280@24 fixture + a 1080×1920@30 fixture via `lavfi` (no API), build the real argv (`video_codec="libx264"` to avoid NVENC in CI), run it, assert `rc==0` and `ffprobe` output is 1080×1920. **Formal acceptance test for this fix.** |
| `gen_run` failure handling (#5) | extend `tests/test_hybrid_gen_run.py` | On a simulated non-zero rc, stderr tail is logged/alerted; an encoder-attributable failure triggers exactly one libx264 retry; a filtergraph error does **not** retry. |

### Prior art

- `tests/assembler/test_build.py` — argv/filtergraph string assertions on pure builders.
- `tests/test_hybrid_gen_run.py` — patched-stage orchestration tests for `_generate_clip`.
- `src/narration/aligner.py` — the CUDA→CPU fallback shape the encode fallback mirrors;
  its tests (added this session) are the model for the encoder-fallback tests.

## Out of Scope

- **Requesting a higher resolution from Kling.** Std tier is 720×1280; a higher tier is
  a cost decision, not part of this defect fix.
- **Changing crossfade duration or transition style.**
- **xfade offset drift from nominal-vs-actual durations.** Kling shots are ~4.04s while
  the code assumes 4.0s; at a 0.25s crossfade the drift is sub-frame. Noted, deferred.
- **Re-rendering / backfilling the already-shipped Slice 10 Clip** (`9lpL8kuLX08`, 720p).
  It stays as published.
- **Motion-interpolated 24→30fps** (e.g. `minterpolate`). Frame duplication via `fps`
  is sufficient and cheap; interpolation is a quality experiment for later.
- **A general ffmpeg-retry framework.** The CPU fallback is scoped to the assembler
  encode only.

## Further Notes

- The doc correction is in-scope because the false "native 1080×1920" claim is what hid
  this defect; the docs should match reality in the same change as the fix. Worktree
  copies under `.claude/worktrees/` are excluded (snapshots, not live docs).
- The aligner CPU fallback already landed this session (`src/narration/aligner.py`,
  uncommitted in the working tree) — the encode fallback is the same pattern applied to
  the assembler, and both should be committed together.
- After this fix, re-run `scripts/spike_hybrid.py` on a fresh topic to confirm a hybrid
  **Clip** lands in `output/pending/` at 1080×1920; that is the operator-facing
  acceptance check, parallel to the automated #6 integration test.
- This fix unblocks Pivot.7's first hybrid ship; it does not itself ship anything.

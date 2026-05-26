# Grill record — Pivot.7 hybrid assembly failure (xfade / resolution mismatch)

**Date:** 2026-05-26
**Trigger:** Hybrid spike (`scripts/spike_hybrid.py`) failed at the final ffmpeg
assembly step with `ffmpeg failed (rc=4294967274)` after scripting, Kling, Kokoro,
and Whisper alignment (CPU fallback) all succeeded.
**Mode:** `/grill-with-docs` — user delegated decisions ("do what you think is recommended").

## Verified evidence (not inference)

1. **Kling std real output is 720×1280 @ 24fps**, not 1080×1920.
   `ffprobe` on `data/ai_gen_shots/spike_2026-05-21/7cb41305_shot_0.mp4`:
   `h264, 720x1280, yuv420p, r_frame_rate=24/1, time_base=1/12288, dur=4.04s`.
   This **contradicts CLAUDE.md's locked decision** ("renders … in native 1080×1920",
   "Shots are already 1080×1920"). The doc is wrong — corrected below.

2. **Ken Burns real-image shots are 1080×1920 @ 30fps** (`src/assembler/ken_burns.py`
   hardcodes `resolution=(1080,1920)`, `fps=30`, `-pix_fmt yuv420p`; fed
   `cfg.output_resolution = [1080,1920]`).

3. **A hybrid Clip therefore mixes two resolutions and two framerates.** The xfade
   chain in `src/assembler/build.py` (`_build_crossfade_video_chain`) feeds raw
   `[i:v]` inputs straight into `xfade` with **no per-input normalization**; `fps=30`
   is applied only *after* the whole chain.

4. **Reproduced the exact failure locally (zero API cost).** xfade of a 1080×1920
   clip against the real 720×1280 Kling shot:
   ```
   First input link main parameters (size 1080x1920) do not match the
   corresponding second input link xfade parameters (size 720x1280)
   Failed to configure output pad on Parsed_xfade_0
   Task finished with error code: -22 (Invalid argument)
   ```
   **`-22` as unsigned 32-bit = 4294967296 − 22 = 4294967274** — byte-for-byte the
   rc the spike reported. Root cause confirmed.

5. **Fix verified locally.** Prefixing each input with
   `scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p,settb=AVTB`
   before xfade → `rc=0`, valid output. Confirmed working.

## Decisions locked

| # | Decision | Rationale |
|---|---|---|
| D1 | **Canonical shot format = 1080×1920 @ 30fps, yuv420p, SAR 1:1.** | Matches the existing `output_resolution: [1080,1920]` config + hardcoded fps=30. Real-image stills are genuinely high-res; upscaling Kling 720→1080 loses nothing real, downscaling real images to 720 would throw away detail. Output stays true 1080p Shorts. |
| D2 | **Normalize per-input inside the assembler filtergraph**, not via a pre-pass or by disabling crossfade. The assembler must finally *consume* `cfg.output_resolution` (today it ignores it). | One ffmpeg pass, no temp files. xfade and concat-filter both require uniform inputs; the filtergraph is the only place that can enforce it. |
| D3 | **The crossfade-OFF path must normalize too.** Switch the multi-input non-crossfade branch from the **concat demuxer** (`-f concat`, requires identical params) to the **concat filter** with the same per-input normalization. | The user's suggested `crossfade_enabled:false` isolation test would *not* have fixed the hybrid clip — concat-demuxer fails on mixed resolution identically. crossfade is not the root cause. |
| D4 | **Canonicalize ALL clips to 1080×1920, pure-AI included.** | Slice 10's shipped clip (`9lpL8kuLX08`) was 720×1280 (4 same-res Kling shots concat'd, no scale). Going forward one normalization path serves both pure-AI and hybrid; avoids a second code path and a second resolution. |
| D5 | **Persist ffmpeg stderr on assembly failure** (gen_run currently raises with rc only; spike runner prints rc only — stderr was lost, which is why this took a repro to confirm). Add a regression test asserting each shot input is normalized in the built argv. | Diagnosis confidence: never debug an ffmpeg rc blind again. |
| D6 | **Add a libx264 CPU fallback for the final assembler encode**, mirroring the aligner's CPU fallback (`src/narration/aligner.py`). | The machine's CUDA/NVENC stack is demonstrably fragile (cublas64_12.dll missing → aligner CPU fallback this same session). The encode is not perf-critical at 2–3 clips/week. Defensive, low-cost. Gated behind confirming via D5 stderr that NVENC is/ isn't implicated. |

## Doc corrections required (tracked in PRD/issues)

- **CLAUDE.md** "Locked decisions": "native 1080×1920" / "Shots are already 1080×1920"
  is false for Kling std (720×1280). Reword to: Kling std emits 720×1280; the
  assembler upscales/normalizes every shot to the canonical 1080×1920.
- **agents.md** assembler section: document the normalization step.

## Out of scope (explicitly)

- Requesting a higher resolution from Kling (std tier is 720×1280; a higher tier
  is a cost decision, not this bug fix).
- Changing crossfade duration / transition style.
- xfade offset drift from nominal-vs-actual shot durations (Kling is 4.04s, code
  assumes 4.0s) — noted, sub-frame at 0.25s crossfade, deferred.

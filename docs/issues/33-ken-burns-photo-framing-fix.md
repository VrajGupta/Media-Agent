# Ticket 33 — Ken Burns photo-framing fix (stretch → dominant-color gradient)

**Status:** ready-for-agent
**Type:** AFK
**Slice:** AI-niche refit / 4
**User Stories:** 14, 15, 16, 17, 18 (PRD `ai-niche-trending-selection-and-photo-framing.md`)

## Parent

PRD: `docs/prds/ai-niche-trending-selection-and-photo-framing.md`

## What to build

Fix the stretched-photo bug in `assembler/ken_burns.py` and give real-image shots a clean, premium look (MKBHD-style): the photo at its true aspect ratio with a slow zoom, over a background derived from the photo's own dominant color.

The bug: the foreground is scaled aspect-correct (`force_original_aspect_ratio=decrease`) and then piped into `zoompan` with `s=1080x1920`; `zoompan` ignores aspect ratio and re-stretches the fitted photo to fill the frame (a 16:9 photo is squashed ~3× vertically).

End-to-end behavior:

1. **Remove the distortion.** The `zoompan` step must no longer force a fitted photo to `s=WxH`. The photo stays at its true aspect ratio, contained (never cropped/stretched), with a slow Ken Burns zoom preserved.
2. **Dominant-color gradient background** replaces the blurred-bg fill. Two new **pure** helpers:
   - `dominant_color(image_path) -> rgb` — sample the photo's dominant color (Pillow).
   - `clamp_dark_for_subtitles(rgb) -> rgb` — force the color into a **dark, desaturated band** so white centered subtitles at `\pos(540,1500)` always have contrast, regardless of the source image.
   The gradient (built from the clamped color) fills behind the contained photo.
3. **Output parity.** `build_ken_burns_argv(...)` stays a **pure argv builder** (no ffmpeg invoked inside) and emits a `shot_XX.mp4` of the same resolution/fps/duration/codec as today, so the downstream concat path stays kind-agnostic. Retire the `blurred_bg_sigma` key; add gradient/dark-clamp config keys.

No DB schema change. No billed API calls (local ffmpeg).

## Acceptance criteria

- [ ] A wide (16:9) input photo is rendered at its true aspect ratio — no vertical/horizontal stretch (the zoompan `s=WxH` distortion is gone).
- [ ] The slow Ken Burns zoom is preserved; the photo is contained, never cropped.
- [ ] Background is a gradient built from the photo's dominant color, clamped to a dark/desaturated band; white subtitles retain contrast even for a bright-dominant-color input.
- [ ] `build_ken_burns_argv` remains pure (returns argv, invokes nothing); output geometry/fps/duration/NVENC settings unchanged from today.
- [ ] New gradient config keys load and validate; `blurred_bg_sigma` retired without breaking config load.
- [ ] **Tests Required** (≥ 5, no ffmpeg run): `dominant_color` returns a plausible RGB for a synthetic image; `clamp_dark_for_subtitles` always returns a color in the dark/desaturated band (incl. a bright input); argv has no aspect-distorting `zoompan s=WxH` on a fitted photo; gradient layer present; resolution/fps/duration correct. Follow `tests/test_editor_ffmpeg.py` / assembler argv-test style.
- [ ] **Mock Injections:** no ffmpeg execution in unit tests (argv + pure-helper assertions only).
- [ ] Full suite green.

## Blocked by

None - can start immediately. (Render-only; independent of the topic-selection tickets.)

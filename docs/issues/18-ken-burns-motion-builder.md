# Ticket 18 — Ken Burns image→shot mp4 builder

**Status:** ready-for-agent
**Type:** AFK
**Slice:** Pivot.7 / P7.4
**User Stories:** 14, 15, 25 (PRD `pivot-7-hybrid-real-image-shorts.md`)

## Parent

PRD: `docs/prds/pivot-7-hybrid-real-image-shorts.md`

## What to build

Turn a still image into a motion `shot_XX.mp4` that is shape-compatible with a Kling shot, so the assembler's concat step treats real-image and AI shots identically.

End-to-end behavior:

1. **Pure argv builder (public seam).** `build_ken_burns_argv(image_path, dest, *, duration_s, resolution, zoom_rate, blurred_bg_sigma, fps) -> list[str]` — returns ffmpeg argv; **no ffmpeg invoked inside** (same discipline as `assembler.build.build_assembler_argv`).
2. **Filtergraph.** Reuse the proven Pivot.3 blurred-bg idiom from the legacy `editor/`:
   - `split` the still → a `gblur` cover-fit background copy + a contained (aspect-preserved, never cropped) foreground copy centered via `overlay` → output at `resolution` (default 1080×1920), `fps` locked.
   - Apply a slow `zoompan` push for motion over `duration_s` (so logos/wide product shots don't crop and don't sit static next to AI shots).
3. **Output parity.** Emitted `shot_XX.mp4` matches Kling shot geometry/fps/codec so the downstream concat/crossfade is kind-agnostic. Encode via the existing NVENC settings (`nvenc_preset`, `nvenc_cq`).
4. **Invocation.** A thin runner (or a helper consumed by Ticket 19) writes the still to a `shot_XX.mp4` via `editor.ffmpeg_runner.run_ffmpeg`, atomic-write style (`.tmp.mp4` → `os.replace` on success).
5. **Config.** New render keys: `ken_burns_zoom_rate`, reuse `blurred_bg_sigma`. (Render `output_resolution`, `nvenc_*` already exist.)

No DB schema change. No billed API calls (local ffmpeg).

## Acceptance criteria

- [ ] `build_ken_burns_argv` is pure (returns argv; invokes nothing) and produces argv containing the blurred-bg split/gblur/overlay chain, a `zoompan` push, the configured `resolution`, locked `fps`, and NVENC settings.
- [ ] Foreground image is aspect-preserved (contained, not cropped) — logos are not clipped.
- [ ] Output `shot_XX.mp4` geometry/fps match a Kling shot (so concat is uniform).
- [ ] Atomic write: failed/0-byte ffmpeg run leaves no promoted output.
- [ ] New render config keys load and validate; defaults sensible.
- [ ] **Tests Required** (≥ 5, argv-shape, no ffmpeg run): blurred-bg chain present; zoompan present; resolution/fps correct; NVENC settings present; output path correct. Follow `tests/test_editor_ffmpeg.py` / assembler argv-test style.
- [ ] **Mock Injections:** no ffmpeg execution in unit tests (argv assertions only). A single real render is part of Ticket 20's spike, not this ticket.
- [ ] Full suite green.

## Blocked by

Ticket 17 (`image_fetch` — needs `ImageAsset.path` and `Paths.images_dir`).

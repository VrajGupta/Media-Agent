# Issue 23 — Pure-AI Clips canonicalize to 1080×1920 (`render_from_script`)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/p7-fix-hybrid-assembly-normalization.md` — Pivot.7 Fix: Canonical shot
normalization in the assembler. Decisions of record: `docs/adr/0002`.

## What to build

The standalone `scripts/render_from_script.py` tracer (used for the Slice 10
hand-stitch and pure-AI renders) currently assembles via the **concat demuxer** and
inherits Kling's 720×1280, so it ships sub-1080p **Clips**. Wire it through the same
**Shot normalization** path introduced in Issue 22 so that pure-AI **Clips** also
output the canonical 1080×1920.

End-to-end behavior: the script passes `cfg.output_resolution` + `cfg.output_fps`
(or the equivalent constants it already uses) and feeds its shot paths through the
normalized filtergraph path instead of the concat-demuxer call. A pure-AI render of
four 720×1280 Kling **Shots** produces a true 1080×1920 **Clip**.

## Acceptance criteria

- [ ] `render_from_script.py` builds the assembler argv via the normalized
      multi-input filter path (Issue 22), not the concat demuxer.
- [ ] A render from the four banked Kling shots
      (`data/ai_gen_shots/spike_2026-05-21`, order `3,2,1,0`) produces a 1080×1920
      output (`ffprobe`-verified), with subtitles and narration intact.
- [ ] `--dry-run` still prints the planned steps without invoking ffmpeg or APIs.
- [ ] Crossfade on/off both produce a valid pure-AI **Clip**.

## Blocked by

- Issue 22 (provides the normalized filter path + `resolution`/`fps` builder params).

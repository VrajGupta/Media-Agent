# Issue 24 — Diagnosable + resilient assembly: persist stderr, CPU-encode fallback

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/p7-fix-hybrid-assembly-normalization.md` — Pivot.7 Fix: Canonical shot
normalization in the assembler. Decisions of record: `docs/adr/0002`.

## What to build

Two resilience/observability improvements that this defect exposed:

1. **Persist ffmpeg stderr on failure.** Today `gen_run._generate_clip` (and
   `scripts/spike_hybrid.py`) raise/print only the return code on assembly failure —
   the stderr that diagnoses the problem in seconds is discarded (which is why
   diagnosing this defect required a manual reproduction). On a non-zero rc or
   zero-byte output, write the stderr tail to `logs/` and emit an alert via the
   existing observability path.

2. **CPU-encode fallback.** The machine's CUDA/NVENC stack is demonstrably fragile
   (the aligner already falls back to CPU this session — `src/narration/aligner.py`).
   When the assembler encode fails for an **encoder-attributable** reason, retry the
   assembly once with `video_codec="libx264"` (Issue 22's parameter), using libx264's
   quality flags (`-preset`/`-crf`) in place of the NVENC `-preset`/`-cq`. A
   **filtergraph** error (like this defect) must still fail fast — the fallback only
   triggers on encoder-level failures, detected from the stderr.

## Acceptance criteria

- [ ] On assembly failure, the ffmpeg stderr tail is written to `logs/` and an alert is
      appended (kind consistent with existing alert kinds), instead of surfacing only
      the rc.
- [ ] An encoder-attributable failure triggers exactly one retry with
      `video_codec="libx264"`; success on retry yields a valid **Clip**.
- [ ] A filtergraph error (non-encoder) does **not** trigger the libx264 retry — it
      fails fast with the stderr recorded.
- [ ] The libx264 retry path emits libx264-appropriate quality flags, not NVENC flags.
- [ ] Tests extend `tests/test_hybrid_gen_run.py` (patched-stage style): simulate a
      non-zero rc and assert stderr is logged; assert one retry on an encoder failure
      and zero retries on a filtergraph failure. Mirrors the aligner CPU-fallback tests
      added this session.

## Blocked by

- Issue 22 (provides the `video_codec` builder parameter the fallback toggles).

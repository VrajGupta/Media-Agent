# Ticket 16 — Kokoro local narration engine (+ Edge fallback)

**Status:** ready-for-agent
**Type:** Interactive
**Slice:** Pivot.7 / P7.2
**User Stories:** 4, 18, 19, 20, 25 (PRD `pivot-7-hybrid-real-image-shorts.md`)

## Parent

PRD: `docs/prds/pivot-7-hybrid-real-image-shorts.md`

## What to build

Swap the robotic Edge TTS voice for **Kokoro-82M** running locally on the RTX 3070, behind the existing `synthesize(...)` contract, with Edge TTS retained as an automatic fallback. Marked **Interactive** because it requires a one-time `espeak-ng` install and an operator listen-test.

End-to-end behavior:

1. **Engine behind the existing seam.** Keep `synthesize(text, dest, *, voice, rate, pitch) -> Path` as the public entry. Add a `KokoroEngine` (Kokoro-82M on CUDA; voice selectable, e.g. `am_michael`, `bm_george`) and an engine selector that dispatches on `narration.engine ∈ {kokoro, edge}`. Output an mp3 (or wav → mp3) at `dest`, same as today, so the aligner/subtitles/assembler are untouched.
2. **Automatic fallback.** On any Kokoro failure (import error, model load, runtime, missing `espeak-ng`), log a degraded-mode warning and fall back to the existing Edge TTS path. A run must never hard-fail solely because Kokoro is unavailable.
3. **Config.** `NarrationConfig` gains `engine: Literal["kokoro","edge"] = "kokoro"` and `kokoro_voice: str`. Retain `voice`/`rate`/`pitch` for the Edge fallback.
4. **Bootstrap check.** `bootstrap --check` verifies Kokoro is importable and `espeak-ng` is present; reports a clear remediation message if not.
5. **gen_run wiring.** `gen_run._generate_clip` passes `narration.engine`/`kokoro_voice` through to `synthesize`. Whisper forced-alignment (`narration.aligner.align`) is unchanged — Kokoro audio is clean speech.

No DB schema change. No billed API calls (fully local).

## Acceptance criteria

- [ ] `synthesize(...)` signature/return unchanged for callers; engine chosen via `narration.engine`.
- [ ] `engine=kokoro` produces an mp3 at `dest` from Kokoro; `engine=edge` uses the existing Edge path.
- [ ] Kokoro failure (mocked) falls back to Edge and logs a degraded-mode warning; the call still returns a valid `dest`.
- [ ] `NarrationConfig.engine` validates to `kokoro`/`edge`; an invalid value raises at config load; defaults to `kokoro`.
- [ ] `bootstrap --check` reports Kokoro + `espeak-ng` presence with an actionable message on failure.
- [ ] Whisper forced-alignment still produces word timings on Kokoro output (verified at the listen-test, not asserted in unit tests).
- [ ] **Tests Required** (≥ 5): engine selector routes to Kokoro for `engine=kokoro`; routes to Edge for `engine=edge`; Kokoro failure falls back to Edge + warning logged; config validation accepts kokoro/edge and rejects garbage; config defaults to kokoro.
- [ ] **Mock Injections:** Kokoro and Edge synthesis backends are mocked in unit tests (no model download, no network, no GPU). Real synthesis is an operator listen-test only.
- [ ] **Operator step:** install `espeak-ng`, run a real synthesis on one script, listen-confirm it sounds natural and aligns.
- [ ] Full suite green.

## Blocked by

None — independent of the image path; can run in parallel with Ticket 15. Required by Ticket 20 (end-to-end spike).

# Ticket 20 — End-to-end hybrid spike (one real topic) + HITL review

**Status:** ready-for-agent
**Type:** Interactive
**Slice:** Pivot.7 / P7.6
**User Stories:** 1, 2, 3, 4, 5, 24 (PRD `pivot-7-hybrid-real-image-shorts.md`)

## Parent

PRD: `docs/prds/pivot-7-hybrid-real-image-shorts.md`

## What to build

A throwaway operator script that runs the full hybrid pipeline on **one real RSS topic** so the creator can eyeball the mixed visual quality, listen to the Kokoro voice, and reconcile the halved Kling cost — before steady-state.

End-to-end behavior:

1. **One-shot CLI** (`scripts/spike_hybrid.py`, throwaway — deleted/archived once steady-state ships): pick one real topic → real Scripter (tagged shots) → route shots (ai_video → Kling, real_image → fetch + Ken Burns) → Kokoro narration → Whisper align → subtitle burn → hybrid assemble (crossfades on) → write to `output/pending/`.
2. **Cost reconciliation.** Record the `ai_video` shot costs to `quota_usage(provider='openrouter')` via the existing DAL; print the per-clip total and compare to the OpenRouter dashboard (expect ≈ half the Pivot.6 $1.34 baseline).
3. **Provenance report.** Print, for each `real_image` shot, the chosen `source`/`license`/`source_url` from the `image_fetch` sidecars, so the operator can sanity-check the images are the *right* entities (the correct GPU, the real logo).
4. **HITL gate.** Operator reviews the MP4 in `output/pending/` and signs off (or rejects) on: real images correct + on-topic, AI shots read as transitions (no synthetic person), Kokoro voice natural, crossfades smooth.

No unit tests (throwaway operator script — manual run + eyeball + cost reconciliation is the validation, consistent with `scripts/spike_kling.py`).

## Acceptance criteria

- [ ] One hybrid MP4 produced in `output/pending/` from one real RSS topic.
- [ ] Visible mix: real sourced images for the recognizable entities + Kling shots as transitions; **no synthetic person talking**.
- [ ] Kokoro narration present and operator-confirmed natural.
- [ ] Crossfades smooth (or operator flips `assembler.crossfade_enabled=false` and re-runs to compare).
- [ ] Per-clip Kling cost recorded and ≈ half the Pivot.6 4-shot baseline; reconciled against the OpenRouter dashboard within ±10%.
- [ ] Provenance report shows each real image's source/license/url; operator confirms entities are correct.
- [ ] **No tests** for the throwaway script.
- [ ] **HITL sign-off** recorded in `progress.md`.

## Blocked by

Tickets 15, 16, 17, 18, 19 (the full hybrid pipeline).

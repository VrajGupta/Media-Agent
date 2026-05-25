# Ticket 21 — Pivot.7 config/retention/compliance/docs cleanup

**Status:** ready-for-agent
**Type:** AFK
**Slice:** Pivot.7 / P7.7
**User Stories:** 21, 22, 26, 27 (PRD `pivot-7-hybrid-real-image-shorts.md`)

## Parent

PRD: `docs/prds/pivot-7-hybrid-real-image-shorts.md`

## What to build

Finalize Pivot.7: re-tighten cost ceilings around the new ~2-Kling-shot baseline, confirm compliance is unchanged, set the image-cache retention TTL, and update the docs so a fresh agent builds against the hybrid model — not the stale "4 Kling shots" assumption.

End-to-end behavior:

1. **Cost ceilings.** Lower `ai_gen.per_clip_cost_cents_max` to reflect ~2 Kling shots/clip (≈ $0.67 real → set with sensible headroom). Re-confirm `daily_spend_cents_ceiling` against the new cadence. Numbers grounded by Ticket 20's measured per-clip cost.
2. **Compliance (restate + verify).** Confirm `compliance.ai_disclosure=true` stays on and AI-gen uploads still set `containsSyntheticMedia=true` + the "Made with AI." footer (half the clip is AI; Ken Burns motion is synthesized). No uploader code change expected — verify via the existing dry-run.
3. **Retention.** Wire the `data/images/` cache TTL into `retention.run_all` (cleanup + the existing VACUUM cadence).
4. **Docs.** Update `CLAUDE.md`, `agents.md`, `skills.md`, and `CONTEXT/` to describe the hybrid model:
   - Visual path = real images (hybrid sourcing + Ken Burns) + Kling transitions; no longer "4 Kling shots".
   - Narration = Kokoro (Edge fallback), replacing the GuyNeural line.
   - Extend the no-living-individuals rule: `real_image` entities must be products/logos/objects.
   - New modules: `image_fetch/`, Ken Burns builder; `ai_gen` reduced to the transition role.
   - `CONTEXT/CONTEXT.md` glossary: add **Shot kind** values `real_image`/`ai_video`; note Ken Burns and hybrid clip.

No DB schema change. No new billed calls.

## Acceptance criteria

- [ ] `per_clip_cost_cents_max` lowered to the new baseline with documented headroom; `daily_spend_cents_ceiling` re-confirmed.
- [ ] Dry-run uploader for an AI-gen clip still shows `containsSyntheticMedia=true` + "Made with AI." footer (compliance unchanged).
- [ ] `data/images/` governed by a retention TTL in `retention.run_all`.
- [ ] `CLAUDE.md`, `agents.md`, `skills.md`, `CONTEXT/` updated to the hybrid model; no remaining "4 Kling shots" / "en-US-GuyNeural-as-primary" language.
- [ ] `CONTEXT/CONTEXT.md` glossary documents `real_image`/`ai_video` shot kinds and the extended living-person rule.
- [ ] **Tests Required:** config validation for the new ceilings/keys; a retention test for the image-cache TTL (follow existing retention/config test style). Doc edits need no tests.
- [ ] **Mock Injections:** retention test uses a temp dir + injected clock (no real wall-clock waits), matching existing retention tests.
- [ ] Full suite green.

## Blocked by

Ticket 20 (cost ceilings grounded by the spike's measured per-clip cost; docs reflect the validated hybrid pipeline).

# Issue 35 — Resolve fetches-and-caches (retire the search-only probe) + cost cap 250¢

**Status:** ready-for-agent
**Type:** AFK
**User Stories:** 1, 2, 3, 4, 5, 6, 15, 16, 17, 29 (PRD `first-live-hybrid-gen-run.md`)

## Parent

PRD: `docs/prds/first-live-hybrid-gen-run.md`
ADR: `docs/adr/0003-licensed-only-image-sourcing-for-autonomous-ships.md` (Refinement
2026-05-30)

## What to build

Make the degrade-vs-keep decision for a **Real-image shot** run on a *fetched and
validated* asset, not a search-only probe — so a licensed "hit" can never bill Kling and
then abort at render.

End-to-end behavior:

1. The licensed-source resolver downloads, validates, and caches each Real-image still
   **up front**, over **Licensed sources only** (never web). A hit returns a validated
   asset (now cached); a miss returns nothing and the shot degrades to an **AI-video
   shot** — all *before* any Kling job is submitted.
2. The shot-plan resolution seam changes from a boolean probe to an asset-or-nothing
   resolver. A kept Real-image shot carries its resolved asset forward so the render step
   reuses the cached still and performs **no second fetch**.
3. `gen_run` resolves the shot plan **once** (today it resolves twice — in the per-script
   loop and again inside clip generation) and threads the resolved plan (with cached
   assets) into clip generation. The pre-billing cost projection uses the exact billable
   AI-video count from that single resolve.
4. The search-only probe is retired.
5. Config: `ai_gen.per_clip_cost_cents_max` `270 → 250` (with a comment noting the
   $20/month ÷ 8 videos = $2.50/video basis, and that at ~67¢/shot this rejects a 4-shot
   fully-degraded clip — so every clip must resolve ≥1 licensed image). Leave
   `daily_spend_cents_ceiling: 500`.

Follows the ADR-0003 Refinement: a Licensed source "satisfies" an entity only when it
yields a validated, downloadable still.

## Acceptance criteria

- [ ] The shot-plan resolver takes an injected resolver returning an asset-or-nothing
      (not a boolean), and remains pure (no network/ffmpeg/Kling) under unit test.
- [ ] All-hit → shot list unchanged, each Real-image shot carries its resolved asset,
      billable count = number of AI-video shots.
- [ ] One licensed miss → that shot degrades to AI-video; billable count increments.
- [ ] Resolution (fetch+validate+cache) completes for every Real-image shot **before**
      any Kling job is submitted (asserted via call order in a test).
- [ ] The render step reuses the cached asset — no second fetch occurs for a resolved
      Real-image shot.
- [ ] The resolver consults Licensed sources only; web is never consulted on this path.
- [ ] `gen_run` resolves the shot plan once per script (the duplicate resolve is removed).
- [ ] `per_clip_cost_cents_max` is 250; config loads and validates; a clip projected to
      4 AI-video shots (~268¢) is rejected before billing.
- [ ] Unit tests added per the PRD's testing decisions; full suite green.

## Blocked by

None — can start immediately.

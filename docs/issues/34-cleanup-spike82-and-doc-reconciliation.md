# Ticket 34 — Cleanup (reject `spike-82`) + niche doc reconciliation

**Status:** ready-for-agent
**Type:** AFK
**Slice:** AI-niche refit / 5
**User Stories:** 19, 20 (PRD `ai-niche-trending-selection-and-photo-framing.md`)

## Parent

PRD: `docs/prds/ai-niche-trending-selection-and-photo-framing.md`
Decision record: `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`

## What to build

Remove the bad clip and bring the top-level docs in line with the narrowed niche, so a fresh agent doesn't rebuild against the stale broad "Tech/AI news" framing.

End-to-end behavior:

1. ~~**Reject `spike-82`.**~~ **DONE 2026-05-27** (manual, ahead of this ticket): `clip_id='spike-82'` set to `status='rejected_policy'` (reason references Topic #82 + ADR-0004) and its file moved `output/pending/` → `output/rejected/`. `rejected_policy` is selected by neither the upload due-query nor approval-reconcile, so it can never publish. Just verify this still holds.
2. **Reconcile `CLAUDE.md`.** Update the "Locked decisions → Niche" line from broad "Tech/AI news" to the sharpened niche (AI-centric + flagship hardware/OS launches; culture/drama/minor-tech excluded), citing ADR-0004.
3. **Reconcile `plan.md`.** Update the direction summary / niche language likewise; reference the new PRD + ADR-0004.
4. Confirm `CONTEXT.md` (**Topic**, **Significance**, **Trending corroboration**) and `docs/rss_feeds.md` already match (they were updated during the design session / Ticket 30) — fix any residual drift.

No DB schema change.

## Acceptance criteria

- [x] `spike-82` is marked rejected in the DB and its file is no longer in `output/pending/` (no path by which it can be uploaded). **(done 2026-05-27 — verify only)**
- [ ] `CLAUDE.md` niche line reflects "AI-centric + flagship launches," referencing ADR-0004; no stale "weird/unsettling" or broad-niche language remains in the locked-decisions niche entry.
- [ ] `plan.md` direction summary matches the narrowed niche and links the PRD + ADR-0004.
- [ ] `CONTEXT.md` and `docs/rss_feeds.md` are consistent with the shipped behavior (no contradictions).
- [ ] No broken doc links introduced.

## Blocked by

- Ticket 31 (on-niche relevance gate) and Ticket 32 (significance + HN rerank) — so the docs describe shipped behavior, not an intent.

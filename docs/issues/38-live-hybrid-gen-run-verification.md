# Issue 38 — Live hybrid gen_run verification + HITL sign-off

**Status:** ready-for-agent
**Type:** HITL (operator-run acceptance gate)
**User Stories:** 18, 19, 20, 21, 22, 23, 24, 25, 26, 27 (PRD `first-live-hybrid-gen-run.md`)
**Supersedes:** Issue 20 (throwaway `spike_hybrid.py` end-to-end spike)

## Parent

PRD: `docs/prds/first-live-hybrid-gen-run.md`
ADR: `docs/adr/0001-two-gate-signoff-for-live-uploads.md` (evidence model)

## What to build

This is a **verification gate**, not new code (beyond marking the superseded spike). With
the three fixes in (Issues 35–37), prove that a real `gen_run` produces one **Hybrid
clip** end-to-end on this machine.

End-to-end behavior to verify:

1. **Dry-run rehearsal:** `gen_run --dry-run --clips 1` walks the full hybrid pipeline
   (RSS ingest → niche gate → scripter → licensed-source resolve → narration policy →
   Kling + Ken Burns → narration → align → assemble → quality → slot) with **no** DB
   writes and **no** spend.
2. **Real unattended run:** `gen_run --clips 1` produces ≥1 Hybrid clip in
   `output/pending/` at 1080×1920, within the 250¢ per-clip cap and the 500¢ daily
   ceiling, holding `data/.gen_run.lock` and appending a `runs.md` row.
3. **Quality eyeball (mechanics bar):** visible mix of real sourced images for
   recognizable entities + Kling shots as transitions, **no synthetic-person frame**;
   narration natural; subtitles in sync.
4. **Cost + provenance:** per-clip Kling cost recorded to
   `quota_usage(provider='openrouter')` and reconciled within the cap; a provenance line
   (source/license/url) available for each Real-image shot.
5. **Slotting:** the clip's `publish_at_utc` lands on a Tuesday or Thursday at a
   configured slot.
6. **Housekeeping:** mark the throwaway `spike_hybrid.py` superseded (it proves less than
   `gen_run` and is no longer the proof path).

Record the evidence in `progress.md` (ffprobe dims, `quota_usage` rows, `runs.md` row, the
Tue/Thu `clips` row, provenance), per ADR-0001's gate model. Stop at the
`output/pending/` HITL review — the live ship (Issue 29) is out of scope.

## Acceptance criteria

- [ ] `gen_run --dry-run --clips 1` completes the full hybrid pipeline with zero DB writes
      and zero OpenRouter spend.
- [ ] A real `gen_run --clips 1` produces ≥1 Hybrid clip in `output/pending/` at 1080×1920
      (ffprobe-confirmed).
- [ ] The clip shows a real-image + AI-video mix with no synthetic-person frame.
- [ ] Per-clip Kling cost is within 250¢; the run stays under the 500¢ daily ceiling; cost
      recorded to `quota_usage(provider='openrouter')`.
- [ ] No licensed miss wasted Kling spend (degrade happened before billing).
- [ ] Provenance (source/license/url) available for each Real-image shot.
- [ ] The run holds `data/.gen_run.lock` and appends a `runs.md` row.
- [ ] The clip's `publish_at_utc` falls on a Tuesday or Thursday at a configured slot.
- [ ] `spike_hybrid.py` marked superseded.
- [ ] Evidence recorded in `progress.md`; HITL sign-off noted.

## Blocked by

- Issue 35 (resolve fetches-and-caches + cost cap)
- Issue 36 (niche gate infra split)
- Issue 37 (pre-billing narration policy check)

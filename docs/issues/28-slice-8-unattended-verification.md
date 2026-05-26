# Issue 28 — Slice 8 unattended end-to-end verification

**Status:** ready-for-agent
**Type:** HITL (operator-run acceptance gate)

## Parent

`docs/prds/finish-line-autonomous-hybrid.md` — Finish Line: Autonomous Hybrid Pipeline.

## What to build

This is a **verification gate**, not new code. `gen_run.py` exists (Slice 8, `82ce0d1`)
but the unattended weekly run has never been exercised end-to-end on live RSS with the
working hybrid path. Prove the weekly run works as a system.

End-to-end behavior to verify:

1. **Dry-run rehearsal:** `gen_run --dry-run --clips 1` walks the full hybrid pipeline
   (RSS ingest → scripter → licensed-source resolve → Kling + Ken Burns → Kokoro →
   align → assemble → policy → quality → slot) with **no** DB writes and **no** spend.
2. **Real unattended run:** a real `gen_run` (no `--dry-run`) from a live RSS topic
   produces ≥1 **Hybrid clip** in `output/pending/` at 1080×1920, within
   `per_clip_cost_cents_max` and `daily_spend_cents_ceiling`, holding the run lock and
   appending a `runs.md` row.
3. **Slotting:** the produced clip is assigned a `publish_at_utc` on a Tuesday or
   Thursday at a configured slot time.

Record the evidence (ffprobe dims, `quota_usage` rows, `runs.md` row, `clips` row with
Tue/Thu `publish_at_utc`) in `progress.md`, per ADR-0001's gate model.

## Acceptance criteria

- [ ] `gen_run --dry-run --clips 1` completes the full hybrid pipeline with zero DB
      writes and zero OpenRouter spend.
- [ ] A real unattended `gen_run` produces ≥1 hybrid clip in `output/pending/` at
      1080×1920 (ffprobe-confirmed).
- [ ] Per-clip Kling cost is within `per_clip_cost_cents_max`; the run stays under
      `daily_spend_cents_ceiling`; cost recorded to `quota_usage(provider='openrouter')`.
- [ ] The run holds `data/.gen_run.lock` and appends a `runs.md` row (success summary).
- [ ] The clip's `publish_at_utc` falls on a Tuesday or Thursday at a configured slot.
- [ ] Licensed-only sourcing (Issue 26) is in effect — no web-sourced image in the
      produced clip; any licensed miss degraded to ai_video.
- [ ] Evidence recorded in `progress.md`.

## Blocked by

- Issue 26 (licensed-only sourcing) — must be in effect for the unattended run.
- Issue 20 (live hybrid spike sign-off) — the manual single-clip proof precedes
  trusting the unattended run.

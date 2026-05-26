# Issue 29 — First hybrid ship (two-gate) + cadence verify

**Status:** ready-for-agent
**Type:** HITL (operator-run, two-gate sign-off)

## Parent

`docs/prds/finish-line-autonomous-hybrid.md` — Finish Line: Autonomous Hybrid Pipeline.
Governed by `docs/adr/0001-two-gate-signoff-for-live-uploads.md` (the first hybrid ship
is treated as a first live ship because **Real-image shots** are a new external-content
surface).

## What to build

Ship the first **Hybrid clip** to the test channel and verify it through the two-gate
sign-off — and confirm the Tue/Thu cadence landed it on the right day (Slice 11
live-verify). Verification gate, not new code — the Slice 9 uploader already sets
`containsSyntheticMedia=true` + the "Made with AI." footer for `ai_generated` clips, and
hybrid clips are `ai_generated`.

End-to-end behavior:

1. The hybrid clip from Issue 28 is approved (drag `output/pending/` → `output/approved/`
   while `human_review=true`).
2. `daily_upload` picks it up on its slot day and uploads it with disclosure intact.
3. **Ship gate (T+1h)** and **stability gate (T+48h)** per ADR-0001 (the gate template
   is the same one used for Slice 10 in Issues 12/13).
4. **Cadence confirm:** the upload occurred on the Tuesday or Thursday slot the
   allocator assigned — Slice 11 live-verified outside its unit tests.

## Acceptance criteria

**Ship gate (T+1h):**
- [ ] `videos.insert` succeeded; `youtube_video_id` populated.
- [ ] Disclosure: Studio "Altered content" toggle ON + "Made with AI." footer present.
- [ ] Clip went public at its scheduled Tue/Thu slot.
- [ ] No Content ID claim (strict — any claim fails the gate; watch real-image shots
      especially).
- [ ] Per-clip Kling cost reconciled within ±10% of the OpenRouter dashboard.

**Stability gate (T+48h):**
- [ ] `logs/alerts.md` clean for 48 h (no delayed CID, policy, or community-guidelines
      action).
- [ ] Clip still public (not auto-removed).
- [ ] Impressions > 0.

**Cadence:**
- [ ] The publish day was a Tuesday or Thursday at a configured slot time (Slice 11
      live-verified).

## Blocked by

- Issue 28 (Slice 8 unattended end-to-end verification) — produces the hybrid clip and
  its Tue/Thu slot.

# ADR-0001 — Two-gate sign-off for first-live ships

**Status:** Accepted
**Date:** 2026-05-23
**Context:** Surfaced during the Slice 10 grilling session.

## Context

Slice 10 is the first live AI-generated YouTube Short shipped from this pipeline. The plan's acceptance bar is:

> 1 AI-generated Short live on test channel. AI disclosure visible. No Content ID flag. Cost recorded within ±5% of OpenRouter dashboard.

Several of these signals propagate on different timescales:

| Signal | Latency from upload |
|---|---|
| `videos.insert` success + `youtube_video_id` | seconds |
| Studio "Altered content" toggle visible | seconds |
| Description footer visible | seconds |
| Cost in `generation_jobs.cost_cents` | already recorded pre-upload |
| OpenRouter dashboard settled cost | ~minutes |
| Auto-flip to public at scheduled slot | up to 24 h (depends on slot) |
| Initial Content ID scan | minutes |
| Delayed Content ID propagation | up to 48 h |
| Community-guidelines actions | up to 48 h |
| YouTube auto-removal (rare) | up to 48 h |
| Analytics impressions data | 24–48 h |

If we adopt a single sign-off gate at T+48h to cover all signals, Slice N+1 work is blocked for two days after every live ship. If we adopt a single gate at T+0/T+1h, we miss the slower signals and may scale clip volume on top of a Content ID problem that hasn't surfaced yet.

## Decision

Adopt a two-gate sign-off pattern for any "first live ship of a new content type":

### Gate 1 — Ship gate (`[~]` in progress.md), T+1h

Verifies the immediate ship path:
- Upload succeeded, `youtube_video_id` populated
- Disclosure: Studio toggle ON + description footer present
- Video flipped public at scheduled slot (or re-check at slot+10m if slot is >1h out)
- No immediate CID claim (strict: any claim = fail)
- Cost reconciliation within ±5% of provider dashboard

**Slice N+1 may proceed once this gate passes.**

### Gate 2 — Stability gate (`[x]` in progress.md), T+48h

Runs concurrently with Slice N+1 work. Does not block forward progress.
- `logs/alerts.md` clean for 48 h
- Video still public (no YouTube auto-removal)
- Impressions > 0

## Consequences

**Positive:**
- Unblock cadence isn't gated by propagation latency.
- Two distinct failure-class buckets: structural (gate 1) vs propagation/policy (gate 2). Easier to triage.
- Strict CID bar at gate 1 catches music-bed issues before clip volume scales.

**Negative:**
- Requires two-phase progress.md updates (`[~]` then `[x]`). Bookkeeping overhead.
- If a delayed CID surfaces at T+24h while Slice N+1 is in flight, rollback decisions span two slices.

**Mitigations:**
- The `[~]` symbol is unambiguous: not-yet-stable-but-ship-verified.
- Stability-gate failures append to `alerts.md` and emit a `recovered_slot` / `cid_delayed` alert kind, surfacing them on the next run.

## Scope

This ADR applies to:
- Slice 10 (first AI-gen Short).
- Any future "first live ship of a new content kind" (e.g. first 3-clip batch, first non-English narration, first thumbnail-auto-gen ship).

It does NOT apply to steady-state daily ships once a content kind is established — those use the standard pass/fail bar from `daily_upload.py` (success of `videos.insert`).

## Alternatives considered

1. **Single gate at T+48h.** Rejected: blocks Slice N+1 for 2 days every time.
2. **Single gate at T+0/T+1h.** Rejected: misses delayed CID, no stability data, risk of scaling on top of a latent problem.
3. **Three gates (T+1h, T+24h, T+48h).** Rejected: bookkeeping cost not justified — the T+24h vs T+48h split adds no decision-relevant information; either the video is fine or it isn't, and a 24h sample is rarely enough to distinguish.

## References

- `CONTEXT.md` — operational protocols section restates these gates as a runbook.
- `progress.md` Slice 10 section — first concrete application.
- Slice 10 grilling session, 2026-05-23.

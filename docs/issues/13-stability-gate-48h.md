# Issue 13 — T+48h stability gate

**Status:** ready-for-agent
**Type:** HITL (passive monitoring; user checks YouTube Studio analytics and the alerts log)

## Parent

`docs/prds/slice-10-first-live-ai-gen-upload.md` (Slice 10: First live AI-generated upload)

## What to build

The T+48h stability-gate verification defined in `docs/adr/0001-two-gate-signoff-for-live-uploads.md`. Passing this issue marks Slice 10 as `[x]` (complete) in `progress.md`. It runs concurrently with Slice 11+ work — does not block forward progress, but is the formal ceremony that calls Slice 10 done.

This is purely operational and passive. There is no code to write. The work is checking three signals 48 hours after Issue 12's live upload returned success.

End-to-end behaviour:

1. **48 hours after the upload returned `UploadOutcome.success`**, read `logs/alerts.md`. The file should be clean across the full 48-hour window — no `recovered_slot`, `cid_delayed`, `publish_at_padded`, `upload_quota_exceeded`, `policy_strike`, or any other alert kind tied to this video's `clip_id` or `youtube_video_id`. (Alerts unrelated to this video — for example, alerts from other unrelated daily runs — are fine and do not block.)
2. **Check the video still exists publicly.** YouTube can auto-remove content for delayed Content ID propagation, community-guidelines actions, or compliance flags. Open the watch URL or check Studio → Content. The video must still be `privacyStatus=public` and viewable.
3. **Check impressions > 0** in Studio → Analytics for this video. Impressions > 0 confirms YouTube's recommendation algorithm is at least serving the video somewhere — this is the minimum signal that the upload is "real" in the YouTube ecosystem, not just a private URL nobody can find. Actual view counts are not part of the bar; Slice 10's goal is the path being correct, not the content performing well.

If all three checks pass, mark the Slice 10 row in `progress.md` from `[~]` (ship-verified) to `[x]` (complete). Slice 10 is done.

If any check fails:

- **Alerts present:** read each alert, triage. If the alert is informational (e.g. `recovered_slot` for an unrelated past-due slot) it does not block this issue. If the alert is tied to this video (delayed CID, policy strike, auto-removal), open a follow-up bug issue and decide whether to leave Slice 10 at `[~]` partially-complete or roll back to `[ ]`.
- **Video missing/private:** check Studio for the removal reason. Document in a postmortem. Decide whether the cause is fixable (re-upload after a fix) or fundamental (rethink the music bed, prompt rules, or whole approach). Do not close this issue.
- **Zero impressions:** YouTube usually serves at least a handful of impressions to any uploaded Short within 48h. Zero impressions can mean shadow-ban, an early Content ID block that resolved but suppressed reach, or a deeply low-signal upload. Investigate, document in `alerts.md`, and decide whether to mark Slice 10 `[~]` permanently (ship worked but reach is broken — Slice 11+ work needs to address reach) or attempt a re-upload.

## Acceptance criteria

- [ ] T+48h has elapsed since Issue 12's `UploadOutcome.success`.
- [ ] `logs/alerts.md` is clean (or all entries triaged as informational and not tied to this video).
- [ ] Video still publicly viewable (not removed, not flipped to private/unlisted).
- [ ] Impressions > 0 in Studio Analytics for this video.
- [ ] Slice 10 row in `progress.md` marked `[x]` (complete).

## Blocked by

- Issue 12 (dry-run review + live ship + T+1h ship gate) — Issue 13 timer starts when Issue 12's live upload returns success.

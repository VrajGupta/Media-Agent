# Issue 12 — Dry-run review + live ship + T+1h ship gate

**Status:** ready-for-agent
**Type:** HITL (requires user to drag files, click in YouTube Studio, and read the OpenRouter dashboard)

## Parent

`docs/prds/slice-10-first-live-ai-gen-upload.md` (Slice 10: First live AI-generated upload)

> **Amended 2026-05-24 (/grill-with-docs):** cost-reconciliation target corrected 252¢ → **315¢** (shot 0 was billed twice; query must filter `status='succeeded'`). The first-ship slot is intentionally **near-term and same-day** (≈ now + 45 min), decoupled from the new Tue/Thu steady-state cadence (Slice 11) so the public auto-flip is verifiable inside the T+1h window. Mark Slice 10 `[~]` on pass; the "unblocks Slice 11+" wording below means future slices generally, not specifically the Tue/Thu cadence slice.

## What to build

The actual live ship of the first AI-generated YouTube Short, plus the T+1h ship-gate verification defined in `docs/adr/0001-two-gate-signoff-for-live-uploads.md`. Passing this issue marks Slice 10 as `[~]` (ship-verified) in `progress.md` and unblocks Slice 11+ work.

This is operational — there is no code to write. The work is sequencing several existing tooling steps, reviewing the dry-run upload JSON for correctness, and then performing the strict verification protocol within an hour of the upload returning success.

End-to-end behaviour:

1. **Pre-flight checklist.** Confirm `output/orphans/` is empty (or all markers reconciled), `data/oauth_token.json` exists and is < 50 days old, no other Python process holds `data/.weekly_run.lock`, `quota_ledger` has ≥1600 units of headroom, and the MP4 in `output/pending/` from Issue 11 has a basename matching `output_path` in its `clips` row.
2. **Dry-run review.** Run `python -m src.daily_upload --dry-run` against the assembled clip. Read the generated `videos.insert` JSON (written to `data/dry_run/{clip_id}.json` by existing dry-run plumbing). Confirm:
   - `status.containsSyntheticMedia == true`
   - `status.privacyStatus == 'private'`
   - `status.publishAt` is set to a future UTC ISO-Z timestamp in `Asia/Singapore` slot
   - `status.madeForKids == false`
   - The description contains the literal string `Made with AI. For entertainment / educational use.`
   - The description contains no `Source: youtube.com/watch?v=` or `Original channel:` lines (legacy sourced-clip fields, must be absent for AI-gen)
   - The description contains a `#Shorts` hashtag and a category-derived hashtag
   - The tags list contains the category slug, `shorts`, and `viral`
   - `snippet.categoryId` matches a sensible category (likely `28` Science & Technology or `22` People & Blogs)
3. **Drag-to-approve.** Move (drag, copy+delete, or `Move-Item`) the MP4 from `output/pending/` to `output/approved/`. Confirm `reconcile_approvals` will match the basename when `daily_upload.py` runs (basename equality, not slug-LIKE).
4. **Live upload.** Run `python -m src.daily_upload` (no `--dry-run`). Expect: orphan reconcile passes (empty), approvals reconcile flips the clip to `status='approved'`, today-window query picks it up, `upload_one_clip` returns `UploadOutcome.success` with a `youtube_video_id` populated.
5. **T+1h ship-gate verification.** Within an hour of the upload returning success, perform the strict bar:
   - **Disclosure toggle in Studio.** Open YouTube Studio → Content → click the new video → Details tab → scroll to "Altered content" section → toggle must read "Yes, altered or synthetic". This confirms the API flag was accepted by YouTube and surfaced as the Studio setting.
   - **Description footer.** On the watch page (or in Studio preview), confirm the description includes the literal text `Made with AI. For entertainment / educational use.`
   - **Public flip.** If `publishAt` was scheduled within the next hour, confirm the video has flipped to `privacyStatus=public`. If the slot is further out, postpone this check to `slot + 10 minutes` and document the deferred check timestamp in `alerts.md`.
   - **Content ID.** Strict bar — any claim, including monetization-only claims that do not block playback, counts as a fail. Check Studio → Content → click video → Copyright tab.
   - **Cost reconciliation.** Compute `SELECT SUM(cost_cents) FROM generation_jobs WHERE script_id='7cb41305-b39b-4cc2-855b-067e03549d25' AND status='succeeded'` against `data/state.db` — expected value is **315¢** (5 succeeded renders × 63¢: shot 0 was rendered **twice** under two distinct `external_id`s — `ifAeq9TM…` and `u1G4K99n…` — a re-roll that OpenRouter really billed). Do **not** use the unfiltered `SUM(cost_cents)` (= 621¢; it includes `dry_run` rows at 34¢). Compute the OpenRouter dashboard total for 2026-05-21, filtered to `kwaivgi/kling-v3.0-std` calls matching the **five** `external_id`s in `generation_jobs`. The two numbers must agree within ±5% (**299–331¢**). Tolerance gradient: <5% pass, 5–20% soft fail (ship the clip, log to `alerts.md`, investigate before next clip), >20% hard fail (treat as ship-block, investigate `quota_ledger` writes).
6. **Mark `[~]` in `progress.md`** for the Slice 10 ship-gate row. This unblocks Slice 11+ work to proceed concurrently with the 48-hour stability window.

Failure-mode handling (apply at any step):

- `api_rejected` on the live upload: hard ship-block. Read `result.reason`. Do not retry blindly — this is almost certainly a Slice 9 templater bug. Open a follow-up bug issue, do not close this issue.
- `api_unreachable`: retry up to 2× with 60-second backoff. If still failing, postpone to next day.
- `upload_quota_exceeded`: postpone to next day (quota resets at midnight Pacific).
- `lock_held` (exit code 2): investigate which Python process holds `data/.weekly_run.lock`. Clean up if stale.
- `orphan_reconcile_required` (exit code 4): manually inspect `output/orphans/` markers; finalize or delete before retry.

## Acceptance criteria

- [ ] Pre-flight checklist verified (orphans empty, OAuth fresh, no lock, quota headroom, MP4 basename matches `clips.output_path`).
- [ ] `python -m src.daily_upload --dry-run` written-out JSON reviewed; all 8 dry-run bullet points in step 2 above confirmed.
- [ ] MP4 moved from `output/pending/` to `output/approved/`.
- [ ] `python -m src.daily_upload` returned `UploadOutcome.success` and the `clips.youtube_video_id` is populated.
- [ ] YouTube Studio "Altered content" toggle reads "Yes, altered or synthetic" for this video.
- [ ] Description footer "Made with AI. For entertainment / educational use." is visible on the watch page or in Studio preview.
- [ ] Video flipped to public at scheduled slot (or deferred check documented if slot >1h out).
- [ ] No Content ID claim of any kind on the video (strict bar).
- [ ] Cost reconciliation between `generation_jobs.cost_cents` (succeeded-only) and OpenRouter dashboard within ±5% (target **315¢**, tolerance 299–331¢).
- [ ] Slice 10 row in `progress.md` marked `[~]` (ship-verified). Slice 11+ unblocked.

## Blocked by

- Issue 11 (hand-stitch script) — the MP4 in `output/pending/` is the input to this issue.

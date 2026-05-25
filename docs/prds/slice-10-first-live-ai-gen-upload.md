# Slice 10 — First live AI-generated upload

**Status:** ready-for-agent
**Project:** Media-Agent Pivot.6
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-05-23
**Source session:** /grill-with-docs → /to-prd
**Blocks:** Slice 11+ (scripter quality tuning, scale to 3 clips/week)
**Blocked by:** Slice 3 (schema migration — **applied** to live DB, verified 2026-05-24), Slice 8 (gen_run orchestrator — complete), Slice 9 (AI disclosure refit — complete)

---

> **⚠ Amended 2026-05-24 (/grill-with-docs).** Several decisions in the body below are superseded; the authoritative versions live in the amended **Issue 11** and **Issue 12** and in `CONTEXT/Grilling/2026-05-24-slice-10-first-ship.md`:
> - **Hand-stitch approach:** a `--reuse-shots <dir> --order` flag on `scripts/render_from_script.py`, **not** a separate `scripts/hand_stitch_slice_10.py`.
> - **Lead/thumbnail frame:** **shot 3** (clinician + medical scan) leads, order `3,2,1,0` — **not** the "swap 0↔1 → whiteboard thumbnail" plan (the whiteboard frame has garbled AI text; 3 of 4 shots are synthetic people but only shot 0 came from a named-person prompt, so disclosure covers it).
> - **Cost target:** **315¢** (5 succeeded renders; shot 0 billed twice), reconcile against `status='succeeded'` rows — **not** 252¢ (the raw `SUM` is 621¢ incl. dry-run rows).
> - **Publish slot:** near-term **same-day** (≈ now + 45 min), **decoupled** from the new Tue/Thu steady-state cadence (see `docs/prds/slice-11-tue-thu-publish-cadence.md`).
> - **Ship bar:** mechanics-validation ship — "compliant + not embarrassing", not portfolio quality.

---

## Problem Statement

As the channel owner I have completed every upstream slice in Pivot.6 (topic ingest, scripter, ai_gen spike, narration, assembler, uploader, AI disclosure compliance refit), but I have never actually shipped an AI-generated Short to YouTube. The Slice 9 disclosure code path has been unit-tested in dry-run but never run against the real `videos.insert` endpoint. I do not know:

- Whether `status.containsSyntheticMedia=true` actually renders as a "Yes, altered or synthetic" toggle in YouTube Studio.
- Whether the upload payload will be accepted by YouTube's API as currently constructed.
- Whether my chosen music bed will trigger a Content ID claim.
- Whether the cost recorded internally in `generation_jobs.cost_cents` matches what OpenRouter actually billed for the spike shots.
- Whether the qwen2.5:3b-instruct scripter produces narrations of sufficient factual accuracy and tonal fit to ship publicly without embarrassing the channel.

Layered on top, this session's grilling surfaced two structural blockers and several content-level defects that prevent a clean ship even if I just "drag and run":

1. **Block A (schema):** The Slice 3 migration (`scripts/migrate_pivot_6_3.py`) was committed and tested but never applied to the live `data/state.db`. Columns `clips.content_kind`, `clips.script_id`, `quota_usage.provider` do not exist on the live DB, and `clips.video_id` is still `NOT NULL`. Without these, Slice 9's templater (which reads `row["content_kind"]`) cannot fire the AI-gen branch, and a `clips` row for an AI-gen clip cannot legally be inserted (the legacy `video_id` foreign key constraint fails).
2. **Block B (assembled MP4 missing):** The 2026-05-21 paid spike produced 8 shots (~$5.04 of paid Kling output) for two scripts, but the pipeline never carried those shots through narration + assembly. `output/pending/` is empty. There is no MP4 to drag.
3. **Content defect — qwen mojibake:** Narration text in `scripts` contains U+FFFD replacement characters where source articles had smart-quotes (`Corti's` → `Corti�s`). Edge TTS will mispronounce these and Whisper subtitles will render the `�` glyph literally.
4. **Content defect — qwen factual hallucination:** Spike script `d0da493f` (Android Apps) cites a fabricated "tripling" statistic not present in its source TechCrunch article. Shipping it would put a fake stat on the first AI-gen Short on the channel.
5. **Compliance risk — shot prompt names a real person:** Script `7cb41305` (the alternate candidate) has shot 0 = "Corti's CEO Andreas Cleve in a video call interview with VentureBeat." Kling will have rendered a synthetic person under a real person's name. The `containsSyntheticMedia=true` flag covers this legally, but if shot 0's first frame becomes YouTube's auto-thumbnail, the channel's first AI-gen Short opens with a fake-CEO face.

Without addressing all five, Slice 10 cannot meet its stated acceptance: "1 AI-generated Short live on test channel. AI disclosure visible. No Content ID flag. Cost recorded within ±5% of OpenRouter dashboard."

## Solution

Unblock both structural blockers, work around the content defects, ship one chosen candidate end-to-end, and verify the acceptance bar across a two-gate sign-off.

1. **Apply the Slice 3 migration** to the live `data/state.db`. Back up the DB first. The migration script is idempotent and `--dry-run`-capable; run dry-run first to confirm the planned ALTERs, then run live.
2. **Select the Corti candidate** (`7cb41305-b39b-4cc2-855b-067e03549d25`) over the Android Apps candidate. The Corti narration's stats are all traceable to the source VentureBeat article; the Android Apps script's "tripling" claim is hallucinated and disqualifying.
3. **Sanitize the mojibake** in the Corti narration before TTS via a new pure utility `clean_mojibake(text)` that replaces U+FFFD with `'`. Apply at narration-stage as an always-on filter so future scripts benefit too.
4. **Hand-stitch the Corti clip** via a one-off operational script `scripts/hand_stitch_slice_10.py`. Reuses the existing 4 Corti shots in `data/ai_gen_shots/spike_2026-05-21/` (no new Kling spend). Runs narration + assembler + subtitle burn against the sanitized narration. Swaps shot 0 ↔ shot 1 in assembler order so the whiteboard frame becomes YouTube's auto-thumbnail rather than the synthetic-CEO frame. Outputs to `output/pending/__unscheduled__7cb41305__corti-symphony.mp4` and inserts the corresponding `clips` row at `content_kind='ai_generated'`, `script_id='7cb41305...'`, `status='quality_pass'`.
5. **Configure the music bed.** User has already replaced phonk tracks with YouTube Audio Library tracks (CID-safe by Google guarantee). No code work needed.
6. **Dry-run the upload.** Run `python -m src.daily_upload --dry-run` against the assembled clip; review the full `videos.insert` JSON payload before sending real traffic. Confirm `containsSyntheticMedia=true`, `madeForKids=false`, AI-disclosure description footer, category seeded, no source/channel attribution.
7. **Ship live.** Drag the MP4 from `output/pending/` to `output/approved/`. Run `python -m src.daily_upload` (real). Apply the operational pre-flight checklist (output/orphans/ empty, OAuth fresh, no lock held, quota headroom).
8. **Verify against the two-gate sign-off ceremony defined in ADR-0001:**
   - **T+1h ship gate** — disclosure toggle on in Studio, footer visible, public at scheduled slot, no CID claim (strict bar), cost reconciled within ±5%. Mark `[~]` in `progress.md`. Slice 11+ unblocked.
   - **T+48h stability gate** — `logs/alerts.md` clean, video still public, impressions > 0. Mark `[x]`. Slice 10 complete.

The compliance fix to the scripter prompt ("must not name real living people in shot descriptions") and the upstream mojibake root-cause fix in `topic_ingest/` are deferred to Slice 11+. They are tracked in `CONTEXT.md` so the next agent picks them up.

## User Stories

1. As the channel owner, I want to apply the Slice 3 migration to my live database safely, so that the AI-gen disclosure code path can read `clips.content_kind` and fire the synthetic-media flag.
2. As the channel owner, I want the migration to back up my database before running, so that if anything goes wrong I can restore in seconds without losing existing rows.
3. As the channel owner, I want to dry-run the migration before applying it, so that I see exactly which ALTER TABLE statements will execute against my data.
4. As the channel owner, I want the migration to be idempotent, so that re-running it after a partial failure is safe and produces the same end state.
5. As the channel owner, I want one of the two paid spike scripts to ship as my first live AI-generated Short, so that I do not incur new Kling spend just to validate the upload path.
6. As the channel owner, I want to ship the Corti candidate rather than the Android Apps candidate, so that my first AI-gen Short does not cite a fabricated statistic.
7. As the channel owner, I want the candidate's narration sanitized of mojibake before TTS, so that Edge TTS doesn't mispronounce smart-quote characters and Whisper subtitles don't render `�` literally.
8. As the channel owner, I want the sanitize utility implemented as a pure, deeply-encapsulated function in `src/scripter/sanitize.py`, so that the workaround applies everywhere mojibake might leak through (assembler, narration, future scripter persistence) without duplicating `.replace()` calls.
9. As the channel owner, I want shot 0 and shot 1 swapped in the assembled clip, so that YouTube's auto-thumbnail is the whiteboard frame rather than a synthetic person rendered under a real person's name.
10. As the channel owner, I want the hand-stitch script to be a throwaway one-off in `scripts/`, so that it does not pollute the steady-state `gen_run.py` pipeline with operational scaffolding.
11. As the channel owner, I want the hand-stitch script to reuse the existing 4 Corti shots from the spike directory without re-generating, so that no new Kling spend is incurred for Slice 10.
12. As the channel owner, I want the hand-stitch script to insert the resulting `clips` row at `status='quality_pass'`, so that the standard `output/pending/` → `output/approved/` drag-to-approve HITL workflow applies unchanged.
13. As the channel owner, I want only YouTube Audio Library tracks in `data/music/` at upload time, so that the music bed cannot trigger a Content ID claim during the strict-bar T+1h verification.
14. As the channel owner, I want a dry-run of `daily_upload.py` against the assembled clip before any real send, so that I see the exact `videos.insert` JSON payload and can spot a templater bug before quota is spent.
15. As the channel owner, I want the dry-run JSON to confirm `status.containsSyntheticMedia=true` is present, so that the structural disclosure flag is wired through end-to-end.
16. As the channel owner, I want the dry-run JSON to confirm `madeForKids=false` is set explicitly, so that the upload is not audience-restricted by default.
17. As the channel owner, I want the dry-run JSON to confirm the "Made with AI. For entertainment / educational use." footer is in the description, so that the human-facing disclosure also fires.
18. As the channel owner, I want the dry-run JSON to confirm no "Source: youtube.com/watch?v=…" or "Original channel: …" lines appear in the description, so that AI-gen content is not misattributed to a non-existent source video.
19. As the channel owner, I want the pre-flight checklist (orphans empty, OAuth fresh, no lock held, quota headroom ≥1600 units, MP4 matches `clips.output_path`) verified before the live upload, so that the run cannot fail on avoidable preconditions.
20. As the channel owner, I want the live upload to use `privacyStatus='private'` plus a future `publishAt` slot, so that YouTube auto-flips the Short to public at the scheduled time and the production code path is what actually ships.
21. As the channel owner, I want to verify within an hour of upload that the Studio "Altered content" toggle reads "Yes, altered or synthetic", so that the disclosure path is confirmed working before I scale clip volume.
22. As the channel owner, I want to verify within an hour that there is no Content ID claim of any kind (strict bar — any claim is a fail), so that I can isolate music-bed problems early before they compound.
23. As the channel owner, I want to reconcile `SUM(generation_jobs.cost_cents) WHERE script_id='7cb41305...'` against the OpenRouter dashboard for 2026-05-21 within ±5% (target 252¢ ±13¢), so that I know my internal cost ledger is accurate and I can trust it for budget enforcement.
24. As the channel owner, I want cost drift between 5–20% to soft-fail (ship the clip, log to `alerts.md`, investigate before next clip), so that a small ledger discrepancy doesn't ship-block Slice 10 but I still see the signal.
25. As the channel owner, I want cost drift greater than 20% to hard-fail (ship-block), so that a structural ledger bug cannot quietly accrue across many clips.
26. As the channel owner, I want to mark Slice 10 `[~]` (ship-verified) in `progress.md` after the T+1h ship gate passes, so that Slice 11+ work can proceed without waiting 48 hours.
27. As the channel owner, I want to mark Slice 10 `[x]` (complete) in `progress.md` after the T+48h stability gate passes, so that delayed Content ID propagation, community-guidelines actions, and analytics signals are all covered before the slice is considered done.
28. As the channel owner, if `api_rejected` fires on the live upload, I want to treat it as a hard ship-block and investigate `result.reason` before retrying, so that I don't burn quota retrying a Slice-9 templater bug.
29. As the channel owner, if `api_unreachable`, `lock_held`, or `upload_quota_exceeded` fires, I want to treat each as recoverable within 24 hours, so that I'm not panicking over transient infrastructure issues.
30. As a developer reading `src/scripter/sanitize.py`, I want it to expose a single pure function `clean_mojibake(text: str) -> str` with no side effects and no dependencies, so that it is trivially testable and trivially reusable.
31. As a developer extending the pipeline later, I want the mojibake workaround clearly tagged as a "until upstream fix in `topic_ingest/`" workaround in CONTEXT.md, so that the root-cause fix is not forgotten in Slice 11+.
32. As a developer reviewing the two-gate sign-off, I want the rationale captured in `docs/adr/0001-two-gate-signoff-for-live-uploads.md`, so that the pattern is documented for every future "first live ship of a new content type" and is not re-litigated each time.
33. As a developer reading `CONTEXT.md`, I want a documented prohibition against scripter prompts naming real living people, so that the next agent fixes the upstream scripter prompt for Slice 11+ rather than just patching shot orders.
34. As a developer reading `CONTEXT.md`, I want a documented policy that `data/music/` may contain only YouTube Audio Library tracks, so that the Content ID risk is permanently mitigated at the policy layer.
35. As the channel owner, I want the Corti shots' descriptions never named in any user-facing surface (the narration itself does not name Andreas Cleve), so that even though the shot prompt was non-compliant, the published Short does not mention the real person by name.
36. As the channel owner, I want the assembled MP4's basename to match `clips.output_path` exactly so that `reconcile_approvals` in `daily_upload.py` can match it correctly when I drag it into `output/approved/`.
37. As the channel owner, I want all the Slice 10 unblock work itself (migration, hand-stitch, sanitize utility) to be reversible — I can drop the assembled clip, re-run the migration safely, re-stitch with different parameters — so that a single mistake during the unblock does not cost me $2.52 of paid Kling spend.

## Implementation Decisions

### New modules

- **`src/scripter/sanitize.py`** — pure utility. One exported function:
  - `clean_mojibake(text: str) -> str` — replaces U+FFFD (`�`) with U+0027 (`'`). No other transformation. No side effects. No I/O. No dependencies.
  - Deep module rationale: tiny interface, fixes a real defect, broadly reusable across stages (narration, assembler, future scripter persistence). Encodes a constraint that would otherwise be scattered as inline `.replace()` calls.
  - Called by: `scripts/hand_stitch_slice_10.py` (Slice 10 ship), eventually wired into the narration stage as an always-on pre-TTS filter (Slice 11+, out of scope here).

### New operational scripts

- **`scripts/hand_stitch_slice_10.py`** — one-off throwaway script. Not a module; not part of the steady-state pipeline. Wires:
  1. Read `scripts.narration` for `7cb41305-b39b-4cc2-855b-067e03549d25` from `data/state.db`.
  2. Apply `clean_mojibake()` to the narration text.
  3. Locate the 4 Corti shots in `data/ai_gen_shots/spike_2026-05-21/7cb41305_shot_{0,1,2,3}.mp4`.
  4. Define assembler shot order as `[1, 0, 2, 3]` (shot 1 first so its frame becomes the auto-thumbnail).
  5. Invoke the existing narration stage (Edge TTS at `+10%/0Hz`) on the sanitized text → mp3 + Whisper forced-align timings.
  6. Invoke the existing assembler stage on the shot list + narration + music bed → final MP4 with subtitles, music duck, NVENC encode, 2-pass −14 LUFS.
  7. Output the MP4 at `output/pending/__unscheduled__7cb41305__corti-symphony.mp4`.
  8. Insert a `clips` row: `content_kind='ai_generated'`, `script_id='7cb41305-b39b-4cc2-855b-067e03549d25'`, `video_id=NULL`, `status='quality_pass'`, `output_path` matching the file basename, `publish_at_utc=NULL` (set later by slot planner or manual override).
  9. Exit cleanly so the standard HITL workflow (drag pending → approved, run `daily_upload.py`) takes over.

### Existing modules to execute (no code change)

- **`scripts/migrate_pivot_6_3.py`** — already shipped under Ticket 01. Apply to live `data/state.db`. Workflow:
  1. Back up `data/state.db` → `data/state.db.pre-slice-10.bak`.
  2. Run `python scripts/migrate_pivot_6_3.py --dry-run` against the live DB; review planned ALTERs.
  3. Run `python scripts/migrate_pivot_6_3.py` for real.
  4. Verify with a one-shot SQL: `PRAGMA table_info(clips)` should now show `content_kind`, `script_id`; `PRAGMA table_info(quota_usage)` should show `provider`.

### Configuration

No `config.yaml` changes. `music_enabled` stays `true`. `compliance.ai_disclosure` stays `true`. `human_review` stays `true`.

### Two-gate sign-off

Captured in `docs/adr/0001-two-gate-signoff-for-live-uploads.md`. Operational checklist in `progress.md` Slice 10 section. Pass/fail bars in `CONTEXT.md`.

- **Ship gate (T+1h):** disclosure toggle ON in Studio, footer visible, public at slot, no CID claim, cost ±5%. Marks `[~]` — unblocks Slice 11+.
- **Stability gate (T+48h):** `alerts.md` clean, video still public, impressions > 0. Marks `[x]` — Slice 10 complete.

### Cost reconciliation

- Internal source: `SELECT SUM(cost_cents) FROM generation_jobs WHERE script_id='7cb41305-b39b-4cc2-855b-067e03549d25' AND status='succeeded'` — target 252 (4 shots × 63¢).
- External source: OpenRouter dashboard → Activity for 2026-05-21, filter by model `kwaivgi/kling-v3.0-std`, restrict to the four `external_id`s recorded in `generation_jobs`.
- Tolerance gradient: <5% pass / 5–20% soft fail (ship, log to `alerts.md`) / >20% hard fail (ship-block).

### Failure handling

- `api_rejected`: hard ship-block. Investigate `result.reason`. Most likely Slice 9 templater bug; do not retry blindly.
- `api_unreachable`: retry up to 2× with 60 s backoff.
- `upload_quota_exceeded`: postpone to next day (quota resets at midnight Pacific).
- `lock_held`: investigate process; clean up stale lock if found.
- `orphan_reconcile_required`: manual investigation of `output/orphans/` markers before retry.

## Testing Decisions

### What makes a good test here

Test external behavior, not implementation details. For Slice 10 specifically, the operational checks (Studio toggle, real CID scan, OpenRouter dashboard reconciliation) cannot be automated without a live YouTube API and a live OpenRouter session. Those are manual checks per the two-gate sign-off ceremony.

The only piece of new pure code is `clean_mojibake()`. That is testable in isolation.

### Modules to test

- **`src/scripter/sanitize.py`** — unit tests for `clean_mojibake`. Approximately 5 tests:
  1. Empty string in → empty string out.
  2. String with no mojibake → unchanged.
  3. Single mojibake instance → replaced with `'`.
  4. Multiple mojibake instances across a string → all replaced.
  5. Surrounding text (Unicode, ASCII, whitespace) is preserved exactly.

  Pattern matches existing pure-function tests in `tests/test_scripter_stage_a.py` (the topic-scoring/tagging suite). New file: `tests/test_scripter_sanitize.py`.

### Modules NOT tested

- **`scripts/hand_stitch_slice_10.py`** — throwaway operational scaffolding. Manual / smoke-test only. The wiring it does is just composition of already-tested modules (`narration/`, `assembler/`, `state/repository/`). An integration test would test the test harness, not Slice 10 behavior.
- **End-to-end Slice 10 ship** — the actual acceptance bar (Studio toggle visible, no CID claim, cost reconciled with OpenRouter dashboard) requires live YouTube + OpenRouter and is impossible to automate. Verified manually via the two-gate sign-off ceremony.

### Prior art

- `tests/test_scripter_stage_a.py` — pure-function unit tests for scripter scoring/tagging.
- `tests/test_repository_pivot6.py` — DAL helper tests; informs the (deferred) work of testing any new `insert_ai_clips` helper if one is added in Slice 11+.
- `tests/test_uploader_runner.py` — integration test fixtures for AI-gen `videos.insert` body; already passing per Slice 9 completion.

## Out of Scope

- **Scripter prompt fix** ("must not name real living people in shot prompts"). Tracked in `CONTEXT.md` as a Slice 11+ task. Slice 10 mitigates the issue for the Corti candidate via shot reordering only.
- **Upstream mojibake fix in `topic_ingest/`**. Tracked in `CONTEXT.md`. Slice 10 ships the workaround utility; root cause investigation is Slice 11+.
- **Scripter quality tuning** (weak hooks, factual hallucination). Tracked in `CONTEXT.md`. Possible Slice 11+ work: upgrade to qwen2.5:7b, add a verify-stage, or prompt-engineer fewshot examples.
- **Wiring `clean_mojibake` into the narration stage as an always-on filter.** Slice 10 only calls it from the hand-stitch script. Wiring it into the steady-state pipeline is Slice 11+.
- **Quota-increase audit for YouTube Data API.** Still future operations work.
- **TikTok / Instagram cross-posting.** Still out of scope for Pivot.6 entirely.
- **Automated end-to-end live-upload regression test.** Not feasible without dedicated test YouTube channel + mock OpenRouter; manual verification per two-gate sign-off ceremony is the contract for now.

## Further Notes

- **Why Corti and not Android Apps:** During the grilling session, both candidate narrations were read against their source articles. The Corti narration's stats (93% WER reduction, 1.4% vs 17.7%) are all literally in the source VentureBeat article. The Android Apps narration's "tripling app development speed" claim does not appear anywhere in the source TechCrunch summary — it is a qwen2.5:3b hallucination. Shipping a fact-checkable hallucination as the first AI-gen Short on the channel would damage trust faster than any other failure mode. Niche audience (B2B medical) is also lower-blast-radius than mass-market tech, which is the right risk profile for a first-ever live test.
- **Why shot 0 ↔ shot 1 swap, not a full thumbnail override:** A custom thumbnail requires extra `videos.thumbnails.set` API calls and an extra image asset. Swapping the shot order achieves the same outcome (whiteboard frame as first frame = auto-thumbnail) for zero additional code. The order swap is local to the hand-stitch script and does not affect the steady-state pipeline.
- **Why YouTube Audio Library and not Epidemic Sound / Artlist:** Cost. The Pivot.6 budget is $5/week, and Epidemic ($15/month) would consume the entire month's budget for music alone. YouTube Audio Library is CID-safe by Google's own guarantee, free, and contains adequate selection in the "Cinematic / Calm / Inspirational" mood categories that match the locked visual style suffix.
- **What "first live AI-generated Short" means for the channel:** This is not a smoke test against a hidden internal endpoint. It ships publicly (after the auto-flip-to-public at the scheduled slot) on the user's test YouTube channel. The two-gate sign-off ceremony exists precisely because the failure surface is public.
- **Estimated time-on-task for the unblock + ship:** Migration apply ~5 min. Hand-stitch run ~5–10 min (TTS + assembler + subtitles). Dry-run review ~5 min. Live upload ~1 min. T+1h verification ~10 min. Total active time ~30 min, plus the 48h passive stability window.
- **What happens if Slice 10 fails the ship gate:** Depending on which check failed:
  - Disclosure toggle OFF → Slice 9 bug. Investigate templater branch on `content_kind`.
  - Description footer missing → Slice 9 bug in `build_description_ai`.
  - Hard CID claim → music-bed problem. Swap track, re-render, re-upload as a fresh video (CID claims don't clear on edits).
  - Cost reconciliation hard-fail → ledger reading wrong provider. Investigate `quota_ledger.py` and `generation_jobs` writes.
- **What happens if Slice 10 fails the stability gate:** Document the failure in `alerts.md`, write a postmortem, and decide whether to mark Slice 10 partially complete (`[~]` left in place) or fully rolled back. The next slice can still proceed concurrently; the stability gate failure becomes Slice N+1's first investigation item.

# Finish Line — Autonomous Hybrid Pipeline

**Status:** ready-for-agent
**Project:** Media-Agent (Pivot.6 → Pivot.7)
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-05-26
**Source session:** /grill-with-docs → /to-prd
**Decisions of record:** `CONTEXT/Grilling/2026-05-26-finish-line-roadmap.md`, `docs/adr/0003-licensed-only-image-sourcing-for-autonomous-ships.md`, `docs/adr/0001-two-gate-signoff-for-live-uploads.md`
**Blocked by:** Issue 22 (hybrid assembly fix) — **done** (`bca0095`)

---

## Problem Statement

As the channel owner I have all the pieces of a **fire-and-forget** Tech/AI Shorts
agent — RSS ingest, scripter, hybrid shot generation, Kokoro narration, the now-fixed
assembler, the compliant uploader, and a Tue/Thu cadence allocator — but I have never
run the whole thing **unattended end-to-end**, and I have never shipped a **Hybrid
clip**. Individual stages are tested; the autonomous loop as a system is not proven.
Until it is, I am still hand-stitching clips one at a time, which is not the product I
set out to build.

Two specific gaps make this risky to just "turn on":

1. **The hybrid path has never produced a real clip on my machine.** The assembly fix
   (`bca0095`) is verified only against synthetic `lavfi` fixtures. I don't yet know
   that a real RSS topic → tagged shots → fetched images + Kling → Kokoro → assemble
   produces a watchable 1080×1920 Short at roughly half the 4-shot cost.
2. **Hybrid introduces a new external-content surface.** **Real-image shots** put
   third-party product/logo images on the channel. With `web_fallback_enabled: true`,
   an unattended run could auto-publish an unvetted, non-rights-cleared web image —
   an outward-facing, hard-to-reverse Content-ID/licensing risk that pure-AI never had.

## Solution

Drive the project to its **done** definition through an ordered set of gates, each
verifiable on its own:

> **Done** = the autonomous loop (weekly `gen_run` + daily `daily_upload`) runs
> unattended and ships **Hybrid clips** on the Tue/Thu cadence, with the first hybrid
> Short live-verified through the two-gate sign-off.

Ordered milestones (from the grill, ADR-0001, ADR-0003):

1. **Live hybrid spike + HITL sign-off** — prove the hybrid path end-to-end on one
   real topic before trusting automation.
2. **Licensed-only sourcing** (ADR-0003) — make the autonomous path incapable of
   publishing a web image: `web_fallback_enabled: false`, licensed sources only, and
   on a licensed miss **degrade the real_image shot to ai_video** before billing Kling.
   Refresh the stale `copyright_acknowledgement`.
3. **Slice 8 unattended end-to-end** — one real `gen_run` from live RSS produces ≥1
   hybrid clip in `output/pending/`, within cost ceiling, run-locked, `runs.md` logged,
   slotted onto a Tue/Thu `publish_at`.
4. **Slice 11 cadence live-verify** — confirm the unattended slotting lands only on
   Tue/Thu.
5. **First hybrid ship, two-gated** — treat it as a first live ship under ADR-0001
   (ship gate T+1h, stability gate T+48h), because real-image sourcing is a new
   content surface.
6. **Close Slice 10 gates** — the 2026-05-24 pure-AI ship's T+1h/T+48h boxes have
   elapsed; confirm and tick.
7. **Housekeeping** — reconcile the `CLAUDE.md`/`claude.md` case-duplicate, write the
   missing `docs/rss_feeds.md`, commit the 3 follow-up files, and file the CUDA cuBLAS
   PATH fix as a tracked (deferred) perf item.

## User Stories

1. As the channel owner, I want to run the hybrid spike on my machine and get a
   watchable 1080×1920 Short in `output/pending/`, so that I have proof the hybrid path
   works on real inputs, not just synthetic fixtures.
2. As the channel owner, I want the spike to ffprobe-confirm 1080×1920 output, so that
   the assembly fix is validated on real Kling + Ken Burns shots.
3. As the channel owner, I want the spike's per-clip Kling cost recorded to
   `quota_usage(provider='openrouter')` and reconciled within ±10% of the dashboard, so
   that I trust the hybrid cost is roughly half the 4-shot baseline.
4. As the channel owner, I want a provenance record (source/license/url) for each
   real-image shot in the spike, so that I can audit where every shipped image came from.
5. As the channel owner, I want to confirm the spike's real-image shots contain no
   synthetic person and read as the recognizable "money shot", so that the hybrid form
   matches its intent.
6. As the channel owner, I want to confirm the spike's AI-video shots read as
   transitions and the Kokoro voice sounds natural with in-sync subtitles, so that the
   clip is "compliant + not embarrassing" (mechanics-validation bar).
7. As the channel owner, I want the autonomous path to use **Licensed sources** only
   (logo/Wikimedia/Openverse), so that the agent can never auto-publish a
   non-rights-cleared web image.
8. As the channel owner, when every licensed source misses for a real-image entity, I
   want that shot to degrade to an ai_video shot rather than skip the whole clip, so
   that one image miss doesn't silently drop a topic from an unattended run.
9. As the channel owner, I want the degrade decision made **before** Kling jobs are
   billed, so that a degraded clip never wastes OpenRouter spend.
10. As the channel owner, I want web fallback to remain available for the manual spike
    and dev configs, so that I can still explore web imagery where a human reviews
    output before upload.
11. As the channel owner, I want `copyright_acknowledgement` updated from the stale
    `movie_clips_v1` to a hybrid value, so that the config and `bootstrap --check`
    describe the actual current risk.
12. As the channel owner, I want one real unattended `gen_run` (no `--dry-run`) to
    produce at least one hybrid clip from a live RSS topic, so that I know the weekly
    run works as a system.
13. As the channel owner, I want that unattended run to stay within
    `per_clip_cost_cents_max` and `daily_spend_cents_ceiling`, so that the agent cannot
    overspend my budget while I'm not watching.
14. As the channel owner, I want the unattended run to hold the run lock and append a
    `runs.md` row, so that concurrent runs are prevented and every run is auditable.
15. As the channel owner, I want `gen_run --dry-run --clips 1` to walk the full hybrid
    pipeline with no DB writes and no spend, so that I can rehearse a run safely.
16. As the channel owner, I want the produced clip slotted onto a Tuesday or Thursday
    `publish_at_utc`, so that the cadence I configured is actually applied unattended.
17. As the channel owner, I want to confirm an unattended slotting run assigns slots
    only on Tue/Thu at the configured times, so that Slice 11 is verified outside its
    unit tests.
18. As the channel owner, I want the daily uploader to pick up the hybrid clip on its
    slot day and upload it with `containsSyntheticMedia=true` + the "Made with AI."
    footer, so that the first hybrid ship is compliant.
19. As the channel owner, I want the first hybrid ship governed by the two-gate
    sign-off, so that I verify the immediate ship path at T+1h and stability at T+48h
    before scaling hybrid volume.
20. As the channel owner, I want the T+1h hybrid ship gate to check disclosure visible,
    went public at slot, no Content ID claim, and cost reconciled, so that a structural
    failure is caught before the next slice.
21. As the channel owner, I want the T+48h hybrid stability gate to confirm the clip
    stayed live and clean, so that a delayed Content-ID or policy action surfaces before
    I trust the loop.
22. As the channel owner, I want the Slice 10 (pure-AI) T+1h/T+48h gate boxes confirmed
    and ticked, so that the prior ship's record is closed rather than left dangling.
23. As a developer, I want a single canonical `CLAUDE.md` (not a `CLAUDE.md`/`claude.md`
    case-duplicate), so that doc edits can't silently land in the wrong copy on Windows.
24. As a developer, I want `docs/rss_feeds.md` documenting the curated feeds and why
    each was chosen, so that the Slice 7 deliverable exists and feed choices are
    explained.
25. As a developer, I want the 3 uncommitted follow-up files committed once the spike
    passes, so that the working tree is clean and `origin/main` reflects reality.
26. As a developer, I want the CUDA cuBLAS PATH fix captured as a tracked, deferred
    perf item with steps, so that GPU Whisper alignment can be restored later without
    blocking completion.
27. As the channel owner, I want the hybrid-model doc updates (CLAUDE.md / agents.md /
    skills.md) finished, so that the docs describe the shipped system (closes P7.7).
28. As a developer, I want each milestone independently verifiable, so that a failure in
    one gate doesn't force re-doing the others.

## Implementation Decisions

Locked in the grill record and ADR-0003 / ADR-0001. Summary:

1. **Hybrid is the default content path** — already true in code (scripter targets ~2
   real_image + ~2 ai_video). A **Clip** stays `Content kind = ai_generated`; hybrid is
   the **Shot kind** mix. No toggle, no schema change.
2. **Licensed-only autonomous sourcing (ADR-0003).** Production config:
   `web_fallback_enabled: false`, `sources: [logo, wikimedia, openverse]`. The manual
   spike / dev configs may re-enable `web`.
3. **Degrade-on-miss, pre-billing.** When the licensed sources all miss for a
   `real_image` entity, the shot is rewritten to an `ai_video` shot. The resolution
   happens **before** Kling jobs are submitted, so the billable AI-video count is known
   up front and no spend is wasted on a clip that would otherwise be skipped. This
   replaces the current "fetch failure → whole clip skipped" behavior for the licensed
   path. The decision-bearing shape (a shot-plan resolver that maps the normalized shot
   list + a fetch probe to a final shot list + billable count) keeps the routing
   testable without ffmpeg, Kling, or HTTP.
4. **`copyright_acknowledgement`** moves from `movie_clips_v1` to a hybrid value (e.g.
   `hybrid_real_image_v1`); `bootstrap --check` keeps warning if absent.
5. **First hybrid ship = first live ship under ADR-0001.** Two gates: ship gate (T+1h)
   and stability gate (T+48h). Justified by the new real-image content surface even
   though `Content kind` is unchanged.
6. **No schema migration, no new billed API calls, no new uploader fields.** The
   uploader already sets `containsSyntheticMedia` for `ai_generated` clips (Slice 9);
   hybrid clips inherit it unchanged.
7. **Canonical doc file is `CLAUDE.md`.** The lowercase `claude.md` is merged into it
   and removed; future edits target the uppercase name.
8. **Verification gates are ops/HITL, not code.** Milestones 1, 3, 4, 5, 6 are run-and-
   observe steps with explicit pass criteria, not modules. They produce evidence
   (ffprobe output, `quota_usage` rows, `runs.md` rows, Studio checks), recorded in
   `progress.md`.

### Modules built or modified

| # | Module | Kind | Interface |
|---|--------|------|-----------|
| 1 | `src/image_fetch` / `src/gen_run` shot-plan resolver | **New/modified (deep)** | Given the normalized shot list + a licensed-only fetch probe, returns the final shot list (real_image shots that missed rewritten to ai_video) and the billable ai_video count. Pure given an injected fetch fn; no ffmpeg/Kling/HTTP in the unit. |
| 2 | `config.yaml` (`image_fetch`, `copyright_acknowledgement`) | Modified | `web_fallback_enabled: false`; `sources: [logo, wikimedia, openverse]`; `copyright_acknowledgement: hybrid_real_image_v1`. |
| 3 | `src/bootstrap.py` | Verify only | Existing `copyright_acknowledgement`-absent warning now keys on the new value; no logic change expected. |
| 4 | `docs/rss_feeds.md` | New doc | Curated mixed consumer + research feeds with per-feed rationale + setup notes. |
| 5 | `CLAUDE.md` (+ remove `claude.md`), `agents.md`, `skills.md` | Docs | Reconcile case-duplicate; finish hybrid-model description (P7.7 `[~]`). |
| 6 | `progress.md` | Tracking | Record each milestone's evidence; flip Slice 10/11 + P7.6/P7.7 boxes; add the deferred cuBLAS perf item. |

## Testing Decisions

### What makes a good test here

The pipeline's pure functions are tested at their boundary with injected dependencies
(no network, no ffmpeg, no Kling) — e.g. `tests/test_hybrid_gen_run.py` patches the
stage callables, and `tests/assembler/test_build.py` asserts built argv. The one new
behavior (shot-plan degrade) follows that discipline: inject a fetch probe that reports
hit/miss and assert the resulting shot list + billable count — never invoke a real
source.

### Modules under test

| Module | Test | Asserts |
|--------|------|---------|
| Shot-plan resolver (#1) | new unit test (alongside `tests/test_hybrid_gen_run.py`) | All-licensed-hit → shot list unchanged, billable count = #ai_video; one licensed miss → that shot becomes ai_video, billable count +1; resolution happens before any Kling submission (assert order via the injected probe / fake client); web is never consulted when `web_fallback_enabled=false`. |
| Config (#2) | extend config-loader tests | `web_fallback_enabled=false` + licensed-only `sources` load and validate; `copyright_acknowledgement` new value loads. |
| `bootstrap --check` (#3) | extend bootstrap test if one exists | Warns when `copyright_acknowledgement` absent; passes with the hybrid value. |

### Prior art

- `tests/test_hybrid_gen_run.py` — patched-stage orchestration; the resolver test sits
  here.
- `tests/test_config_p4.py` — typed config field validation.
- `src/narration/aligner.py` + its CPU-fallback tests — the model for "degrade rather
  than fail" behavior and its tests.

### Verification gates (not unit tests — recorded evidence)

The live spike, the unattended `gen_run`, the cadence check, and the two-gate ship are
**operator-run acceptance gates**, each with explicit pass criteria in the user stories.
Their "test" is recorded evidence in `progress.md` (ffprobe dims, `quota_usage` /
`runs.md` rows, Studio screenshots/notes), per ADR-0001's gate model.

## Out of Scope

- **Phase 8 stretch:** thumbnail auto-gen, A/B title testing, TikTok/Reels, web
  dashboard, subject-tracking crop.
- **Quota-increase audit / collapsing `daily_upload` into `gen_run`.** The daily/weekly
  split stays.
- **Scripter content-quality grill** (hook strength, stat hallucination) — deferred
  from the 2026-05-23 handoff; not a completion blocker.
- **CUDA cuBLAS PATH fix itself** — captured as a tracked deferred item; CPU-fallback
  alignment works today.
- **Motion-interpolated 24→30fps; higher Kling resolution tier; backfilling the
  720×1280 Slice 10 clip.**
- **Web-fallback human-review gate** (the rejected ADR-0003 alternative) — not built.

## Further Notes

- ADR-0003's degrade-to-ai_video changes the current "fetch failure → clip skipped"
  behavior only for the licensed path; the dev/spike path with `web` enabled keeps the
  old behavior since a human reviews it.
- The first hybrid ship rides the existing Slice 9 uploader unchanged — hybrid clips
  are `content_kind='ai_generated'`, so `containsSyntheticMedia` and the footer are
  already applied. No uploader code work.
- During the locked 2-week `human_review` window every clip is reviewed regardless, so
  ADR-0003's constraint is belt-and-suspenders there and load-bearing once review is
  off.
- After all gates pass, the project meets its "done" definition; remaining items are
  the explicitly out-of-scope stretch list.

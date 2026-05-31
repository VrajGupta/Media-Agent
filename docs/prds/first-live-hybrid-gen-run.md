# First Live Hybrid gen_run

**Status:** ready-for-agent
**Project:** Media-Agent (Pivot.6 → Pivot.7)
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-05-30
**Source session:** /grill-with-docs → /to-prd
**Decisions of record:** `CONTEXT/Grilling/2026-05-30-hybrid-gen-run-finish-line.md`,
`docs/adr/0003-licensed-only-image-sourcing-for-autonomous-ships.md` (Refinement
2026-05-30), `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`,
`docs/adr/0001-two-gate-signoff-for-live-uploads.md`
**Supersedes:** Issue 20 (throwaway `spike_hybrid.py` end-to-end spike)

---

## Problem Statement

I have every piece of a fire-and-forget Tech/AI Shorts agent, and I have shipped a
pure-AI sample Short — but I have **never produced a Hybrid clip** (the default Pivot.7
form: ~2 **Real-image shots** + ~2 **AI-video shots**) from a real `gen_run`. Three
defects discovered in the 2026-05-28 live runs block it, and each one makes the agent
either spend money it shouldn't or silently produce nothing:

1. **A licensed-image "hit" can bill Kling and then abort.** The shot-plan resolver
   decides keep-vs-degrade with a *search-only probe* (true if a source returns any
   candidate), but the render step *downloads and validates*. They disagree, so a probe
   "hit" let Kling bill the AI-video shots and then the real fetch failed at render —
   ~$2 of spend wasted on `openai_logo` on 2026-05-28. This breaks ADR-0003's promise
   that a licensed miss costs no Kling spend.
2. **An Ollama hiccup silently empties the topic queue.** The on-niche relevance gate
   treats an infrastructure failure (Ollama timeout / invalid JSON) as a real `off_niche`
   verdict and drops the topic. The 2026-05-28 "rejected all Verge AI items" looks like
   editorial strictness but may be Ollama failing — I can't tell, because the two are
   indistinguishable in the logs.
3. **A policy-violating script renders in full before it's caught.** The `gen_run`
   policy stage is the legacy transcript-clip gate; it runs before any clip exists, in a
   pipeline with no transcripts, so it always logs "no candidates" and gates nothing.
   The real narration policy check happens only at upload — after ~$2 of Kling render.

Until these are fixed and a real `gen_run` produces one watchable Hybrid clip, I am
still hand-stitching, which is not the product I set out to build.

## Solution

Fix the three defects so a single real `gen_run --clips 1` produces **one Hybrid clip**
in `output/pending/`, then prove it end-to-end on my machine — stopping at the
filesystem HITL review (the live ship stays a separate, two-gated step).

The three fixes share one shape: **make every spend-affecting decision on the right
signal, at the right time.**

1. **Resolve fetches-and-caches.** Retire the search-only probe. The licensed-source
   resolver downloads, validates, and caches each Real-image still *up front*; a **hit**
   is a validated asset already in the cache, a **miss** degrades the shot to AI-video —
   all before any Kling job is submitted. Render reads the cached asset and never does a
   second, possibly-divergent fetch. (ADR-0003 Refinement.)
2. **Split infrastructure failure from off-niche.** When the niche gate's classifier
   fails on infrastructure (Ollama unreachable / invalid output), **keep** the topic and
   emit a distinct alert, instead of silently dropping it as off-niche. Do not retune the
   classifier prompt yet — first re-run with per-item verdict logging and see whether
   genuinely on-niche items are still rejected.
3. **Policy-check the narration before billing.** Replace the misfit legacy gate with a
   per-script `evaluate_clip_policy(narration, title)` run *before* ai_gen billing; a
   violation skips the script with zero Kling spend. The uploader's pre-upload re-check
   stays as defense-in-depth.

Then tighten the per-clip cost ceiling to the real budget share and run the pipeline.

## User Stories

1. As the channel owner, I want a licensed-image "hit" to mean a real, validated,
   downloadable still — not just a search result — so that a hit can never bill Kling and
   then abort at render.
2. As the channel owner, I want each Real-image still fetched, validated, and cached
   *before* any Kling job is submitted, so that a licensed miss degrades to AI-video with
   zero wasted spend.
3. As the channel owner, I want the render step to read the already-cached licensed
   asset, so that there is no second fetch that could disagree with the billing decision.
4. As the channel owner, when every licensed source misses for an entity, I want that
   shot degraded to an AI-video shot before billing, so that one image miss never aborts
   a clip after spend.
5. As the channel owner, I want the billable AI-video count known exactly at billing
   time, so that the cost projection that guards my budget is accurate.
6. As the channel owner, I want the resolver to consult licensed sources only (never web)
   on the autonomous path, so that ADR-0003's licensed-only guarantee still holds.
7. As the channel owner, I want an Ollama infrastructure failure in the niche gate to be
   distinguished from a real off-niche verdict, so that a transient outage is never read
   as "this topic is off-niche."
8. As the channel owner, when the niche classifier fails on infrastructure, I want the
   topic **kept** (fail-open) and a distinct alert emitted, so that an Ollama hiccup can
   never silently empty my topic queue.
9. As the channel owner, I want each niche verdict (and its reason) logged per item on a
   live ingest run, so that I can see whether a rejection was editorial or infrastructure
   before I touch the classifier prompt.
10. As the channel owner, I do **not** want the niche prompt retuned in this task, so
    that I change one variable at a time and can attribute any change in yield.
11. As the channel owner, I want a script's narration + title policy-checked *before*
    ai_gen billing, so that a banned/profane/NSFW/weak-hook script never costs a Kling
    render.
12. As the channel owner, I want a script that fails the pre-billing policy check skipped
    (not billed, not rendered), while other selected scripts still proceed, so that one
    bad script doesn't sink the run.
13. As the channel owner, I want the uploader's pre-upload policy re-check kept unchanged,
    so that policy is still enforced at the boundary as defense-in-depth.
14. As the channel owner, I want the misfit legacy transcript-clip gate removed from
    `gen_run`, so that the run no longer logs a misleading "no candidates" and no longer
    implies it gates content when it doesn't.
15. As the channel owner, I want `per_clip_cost_cents_max` set to 250¢, so that the
    per-clip ceiling matches my real budget ($20/month ÷ 8 videos = $2.50/video).
16. As the channel owner, I want a clip that would degrade to 4 AI-video shots (~268¢)
    rejected before billing, so that every shipped clip resolves at least one licensed
    image and is at least minimally hybrid.
17. As the channel owner, I want `daily_spend_cents_ceiling` left at 500¢, so that the
    per-day safety rail still accommodates two clips on a heavy day.
18. As the channel owner, I want `gen_run --dry-run --clips 1` to walk the full hybrid
    pipeline with no DB writes and no spend, so that I can rehearse the run safely.
19. As the channel owner, I want a real `gen_run --clips 1` to produce ≥1 Hybrid clip in
    `output/pending/` at 1080×1920 (ffprobe-confirmed), so that I have proof the hybrid
    path works on real inputs.
20. As the channel owner, I want the produced clip to show a visible mix of real sourced
    images for recognizable entities and Kling shots as transitions, with no
    synthetic-person frame, so that the hybrid form matches its intent.
21. As the channel owner, I want the per-clip Kling cost recorded to
    `quota_usage(provider='openrouter')` and within the 250¢ cap, so that I trust the
    spend stayed inside budget.
22. As the channel owner, I want a provenance line (source/license/url) printed or logged
    for each Real-image shot, so that I can audit where every shipped image came from.
23. As the channel owner, I want the run to hold `data/.gen_run.lock` and append a
    `runs.md` row, so that concurrent runs are prevented and the run is auditable.
24. As the channel owner, I want the produced clip slotted onto a Tuesday or Thursday
    `publish_at_utc` at a configured time, so that the cadence I configured is applied
    unattended.
25. As the channel owner, I want to review the clip in `output/pending/` and sign off in
    `progress.md`, so that the HITL gate is honored while `human_review` is on.
26. As the channel owner, I want the live-run evidence (ffprobe dims, `quota_usage` rows,
    `runs.md` row, the Tue/Thu `clips` row, provenance) recorded in `progress.md`, so
    that this gate is closed per ADR-0001's evidence model.
27. As a developer, I want the throwaway `spike_hybrid.py` (Issue 20) marked superseded,
    so that we don't maintain or re-run a script that proves less than `gen_run` itself.
28. As a developer, I want the resolver, the niche-gate infra split, and the pre-billing
    policy skip each unit-tested with injected fakes, so that these spend- and
    safety-bearing behaviors don't regress.
29. As a developer, I want each fix independently verifiable, so that a failure in one
    doesn't force redoing the others.

## Implementation Decisions

Locked in the grill record and ADR-0003 (Refinement 2026-05-30). Summary:

1. **`resolve_shot_plan` seam changes from probe to resolver.** The injected dependency
   changes from `licensed_probe: (entity, query) -> bool` to
   `licensed_resolver: (entity, query) -> ImageAsset | None`. A non-None asset keeps the
   shot as `real_image` and the resolved asset/path is carried forward so the render step
   reuses it; `None` degrades the shot to `ai_video` (existing degrade prompt). The
   function still returns `(final_shots, billable_ai_video_count)` and remains pure given
   the injected resolver — no network, ffmpeg, or Kling in the unit. This is the keystone
   **deep module**.
2. **`src/image_fetch` gains a non-raising licensed resolver.** A thin wrapper (e.g.
   `resolve_licensed_image(entity, query, cfg) -> Optional[ImageAsset]`) runs the
   download+validate+cache path over **licensed sources only** and returns `None` on
   `NoImageFoundError` (rather than raising). `probe_licensed_image` (search-only) is
   retired. `fetch_image` remains the cache-reading path used at render and returns the
   cached asset when present.
3. **`gen_run` resolves once and threads the plan through.** The current double call to
   `resolve_shot_plan` (in the per-script loop and again inside `_generate_clip`) is
   consolidated to a single resolve; the resolved shot list (with cached real-image
   assets) is passed into clip generation so render performs no second fetch. The
   pre-billing cost projection uses the exact billable count from the single resolve.
4. **`gen_run` policy stage is replaced, not patched.** The `policy_gate.run_all` call is
   removed. In its place, for each selected script, `evaluate_clip_policy(cfg,
   script.narration, script.title, ...)` runs **before** ai_gen billing; a failed verdict
   skips that script (logged, not billed); an infrastructure failure leaves the script
   unprocessed for this run (no spend) consistent with the existing fail-soft pattern. The
   uploader's pre-upload re-check (`uploader/runner.py`) is unchanged.
5. **Niche gate distinguishes infrastructure failure.** `_apply_niche_gate` (topic_ingest
   runner) keys on the verdict's `infrastructure_failed` flag: if set, **keep** the topic
   (return persist=True) and emit a distinct alert (e.g. `niche_gate_unavailable`); a real
   `off_niche` verdict still drops the topic with the existing debug log. The classifier
   prompt is **unchanged** in this task.
6. **Config.** `ai_gen.per_clip_cost_cents_max: 270 → 250` (with an updated comment noting
   the $2.50/video budget basis and the ≥1-licensed-image floor it implies).
   `daily_spend_cents_ceiling: 500` unchanged.
7. **No schema migration, no new billed API calls, no uploader changes.** Hybrid clips
   are `content_kind='ai_generated'`; `containsSyntheticMedia` + the "Made with AI."
   footer already apply (Slice 9).
8. **Verification is an operator-run acceptance gate, not code.** The dry-run, the live
   `gen_run`, ffprobe dims, cost reconciliation, provenance, and Tue/Thu slotting are
   run-and-observe steps with evidence recorded in `progress.md`, per ADR-0001.

## Testing Decisions

### What makes a good test here

Test external behavior at a module's boundary with injected dependencies — never the
network, ffmpeg, or Kling. A good test asserts *what the seam decides* (shot list,
billable count, keep/drop, skip/bill), not how it is wired internally. This matches the
existing discipline in `tests/test_hybrid_gen_run.py` (patched stage callables) and
`tests/assembler/test_build.py` (asserts built argv without running ffmpeg).

### Modules under test

| Module | Test asserts |
|--------|--------------|
| `resolve_shot_plan` (resolver seam) | Inject a fake resolver. All-hit → shot list unchanged, real-image shots carry their resolved asset, billable count = #ai_video. One miss → that shot becomes ai_video, billable count +1. Resolution happens before any Kling submission (assert order via the fake resolver / a fake Kling client that records call order). Web is never consulted (the resolver is licensed-only). |
| Niche-gate infra split (`_apply_niche_gate` + classify) | Inject a fake `classify`. `infrastructure_failed=True` → topic kept (persist=True) **and** alert emitted. Real `off_niche` → dropped. `on_niche` → kept. (Extends existing niche-gate tests.) |
| `gen_run` pre-billing policy skip | Inject a policy evaluator + a fake Kling client. Violating narration → script skipped, **no Kling client constructed/called**, other selected scripts still proceed. Passing narration → proceeds to billing. |
| Config loader | `per_clip_cost_cents_max=250` loads and validates; `daily_spend_cents_ceiling=500` unchanged. |

### Prior art

- `tests/test_hybrid_gen_run.py` — patched-stage orchestration; the resolver and
  policy-skip tests sit alongside it.
- existing niche-gate tests (Issue 31) — the infra-split test extends them.
- `tests/test_config_p4.py` — typed config field validation.
- `src/narration/aligner.py` CPU-fallback tests — the model for "distinguish
  infrastructure failure from a real negative result."

## Out of Scope

- **Issue 29 — the first hybrid live ship and its two-gate sign-off.** This PRD stops at
  the `output/pending/` HITL review. The ship is a separate, independently-gated step.
- **Retuning the niche classifier prompt.** Deferred until the per-item verdict evidence
  (story 9) shows genuinely on-niche items are still being rejected after the infra split.
- **Scripter content-quality grill** (hook strength, stat hallucination).
- **Phase 8 stretch:** thumbnails, A/B titles, TikTok/Reels, dashboard.
- **Quota-increase audit / collapsing `daily_upload` into `gen_run`.**
- **CUDA cuBLAS PATH fix** (CPU-fallback alignment works today).
- **Any uploader, schema, or disclosure change.**

## Further Notes

- The ADR-0003 Refinement (2026-05-30) is the architectural record for fix #1; this PRD
  implements it. A **Licensed source** now "satisfies" an entity only when it yields a
  validated, downloadable still.
- During the locked 2-week `human_review` window every clip is reviewed regardless, so
  the pre-billing policy check and the licensed-only resolver are belt-and-suspenders
  here and load-bearing once review is off.
- If the live run yields 0 on-niche topics even after the infra split, that is itself the
  evidence (story 9) that the deferred prompt-retune is warranted — captured as a
  follow-up, not fixed in this task.
- After this gate passes, the remaining path to "done" is Issue 29 (first hybrid ship,
  two-gated) and steady-state cadence confirmation.

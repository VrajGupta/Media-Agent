# Grill record — first live hybrid `gen_run` (finish-line path)

**Date:** 2026-05-30
**Trigger:** ADR-0004 AI-niche refit shipped (`4d6ab7b`); sample clip `qRdVYO1Tmfw`
uploaded but **ai_video-only, not hybrid**. The hybrid `gen_run` has never produced a
real clip end-to-end. User asked to grill the next finish-line task before a PRD.
**Mode:** `/grill-with-docs`. User delegated most calls ("do the recommended"); gave the
budget math explicitly for the cost-cap decision.

## North star (unchanged)

> The autonomous loop (weekly `gen_run` + daily `daily_upload`) ships **Hybrid clips**
> on the Tue/Thu cadence, with the first hybrid Short live-verified through the two-gate.

This task is the **next increment** toward that: make a real `gen_run` produce **one**
hybrid clip in `output/pending/`. The live ship (Issue 29) stays a separate gated step.

## Verified code facts (this grill)

- **Degrade-before-billing is wired but leaky.** `gen_run._generate_clip` calls
  `resolve_shot_plan(..., licensed_probe=probe_licensed_image)` (gen_run.py:254) to
  price the clip *before* Kling, but `probe_licensed_image` (fetcher.py:94) returns
  `True` on **any search candidate** — no download, no validation — while the render
  step `_render_real_image_shot` → `fetch_image` (fetcher.py:141) downloads + validates
  and raises `NoImageFoundError` on failure. Probe and fetch answer **different
  questions**, so a probe "hit" can bill Kling and then abort at render (~$2 wasted).
  This is what killed the 2026-05-28 resume on `openai_logo`.
- **Niche gate conflates infra-failure with off_niche.** `classify_niche`
  (niche_gate.py) returns `NicheVerdict(infrastructure_failed=True, verdict="off_niche")`
  on Ollama timeout / invalid JSON, and `_apply_niche_gate` (runner.py:62) checks only
  `is_on_niche` — so an Ollama hiccup silently **drops** the topic and looks identical
  to a real off-niche rejection. The 2026-05-28 "rejected all Verge AI items" may be
  infra-failure masquerading.
- **`policy_gate` in gen_run is a misfit no-op.** `policy_gate.run_all` (line 470) is the
  **legacy transcript-clip gate**: it queries the `clips` table (empty at that point —
  clips are inserted later at line 499) and needs Whisper transcripts (none in AI-gen).
  It always logs "no candidates." Real AI-gen narration policy runs correctly but only
  at **upload time** (uploader/runner.py:326 → `evaluate_clip_policy` on
  `script_row.narration`). So a policy-violating script is rendered in full (~$2) before
  rejection — no fail-fast.
- **Cost:** `per_clip_cost_cents_max: 270`, `daily_spend_cents_ceiling: 500`; code prices
  a billable ai_video shot at `*67` cents (gen_run.py:259).

Common theme across all three: **a decision made on the wrong signal or at the wrong
time relative to spend.**

## Decisions locked

| # | Decision | Rationale |
|---|---|---|
| G1 | **Scope = one hybrid clip in `output/pending/`.** Fix the three defects, then a real `gen_run --clips 1` produces ≥1 hybrid clip at 1080×1920, ≤ cost cap, slotted Tue/Thu; stop at HITL review. Issue 29 (live ship) stays separate. | Smallest provable increment; the ship crosses an irreversible outward-facing action and is independently gated. |
| G2 | **Defect 1 — resolve fetches-and-caches.** Retire the search-only probe; the licensed-source resolver downloads + validates + caches each real_image still up front, returning hit/miss on real success; render reads the cache (no second fetch). Probe and fetch become one operation. → **ADR-0003 Refinement (2026-05-30).** | The "price the degrade before billing" guarantee is only as good as the signal the resolver uses. A search probe lies; a fetched+validated asset doesn't. |
| G3 | **Defect 2 — split infra-failure from off_niche; fail-open + alert.** On `infrastructure_failed`, **keep** the topic and emit a distinct alert; do **not** retune the prompt yet — re-run ingest, log each item's verdict+reason, retune only if genuinely on-niche items are still rejected. | Don't tune the classifier blind. If Ollama is down every downstream stage fails anyway, so the value here is observability, not flooding the queue. Consistent with the codebase's degrade-don't-fail pattern (aligner CPU fallback, policy_gate leaves clips at `selected`). |
| G4 | **Defect 3 — narration policy check before billing.** Replace the misfit `run_all` call with a per-script `evaluate_clip_policy(narration, title)` run **before** ai_gen billing; fail-fast skip on violation. Keep the uploader re-check as defense-in-depth. Remove the "no candidates" no-op. | Same evaluator/text the uploader already trusts; moving it earlier stops ~$2 of Kling spend on a script that would be rejected at upload anyway. |
| G5 | **Cost cap `per_clip_cost_cents_max: 270 → 250`.** Budget = $5/wk × 4 = $20/mo ÷ 8 videos = **$2.50/video**. At ~67¢/shot the pre-billing projection rejects a 4-shot fully-degraded clip (268¢ > 250) but passes 3 shots (201¢) — so **every clip must resolve ≥1 licensed image to ship** (an "at least minimally hybrid" floor). `daily_spend_cents_ceiling: 500` unchanged (per-day safety rail). | User's budget math. The 270¢ cap permitted a fully-degraded clip costing the same as pure-AI, contradicting hybrid's "halve the cost" rationale. |
| G6 | **Prove via `gen_run` directly, not the throwaway spike.** `gen_run --dry-run --clips 1` (green, no spend) then a real `gen_run --clips 1`. All three fixes live in the gen_run path, so this exercises the real code; the throwaway `spike_hybrid.py` (Issue 20) is **superseded** — mark it so. This IS Issue 28's acceptance. | The spike doesn't exercise the niche gate or the gen_run policy/resolve wiring, so it proves less while costing a second ~$1.34 render. |

## Doc updates this session

- **ADR-0003** — appended *Refinement — 2026-05-30*: degrade decision must run on a
  fetched+validated asset, not a search probe; a Licensed source "satisfies" an entity
  only when it yields a validated, downloadable still.
- **CONTEXT.md** — intentionally unchanged. The three fixes are mechanism corrections,
  not new domain terms; the glossary stays implementation-free.

## Out of scope (unchanged)

Issue 29 live ship + two-gate; scripter content-quality grill; prompt retuning (pending
G3 evidence); Phase 8 stretch; quota-increase audit; CUDA cuBLAS PATH fix.

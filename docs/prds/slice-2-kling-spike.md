# PRD — Slice 2: OpenRouter Kling 3.0 Spike

> **Scope:** Pivot.6 Slice 2. The first paid Kling generation run. Spends ~$2.69 of this week's $5 budget to ground-truth per-shot pricing, validate the locked style suffix, confirm 4-shot stitchability, and bank 8 raw MP4 shots as raw footage for the first two production videos (consumed once Slices 4/5/8/9 ship).
>
> **Status of upstream context:** Decisions came out of a `/grill-with-docs` session on 2026-05-21 against the locked Pivot.6 plan. This PRD supersedes the original `plan.md` Slice 2 spec ("10 hand-typed prompts") with a staged spike on real Ollama-generated prompts.

## Problem Statement

The Pivot.6 pipeline produces scored, ranked tech/AI news scripts from RSS feeds — but it has never made a single Kling API call. Three risks block further build investment downstream:

1. **Cost model unverified.** The plan assumes Kling 3.0 std at $0.084/sec × 4s = $0.34/shot, no-audio, for a $1.34/video unit cost. This is a projection from OpenRouter's pricing page, never measured against an actual `usage.cost` response. If the real cost is double that (audio billed by default, or a different model variant resolves), the $20/month budget produces ~7 videos, not ~14.

2. **Aesthetic unverified.** The locked style suffix — `"clean editorial product photography, soft studio lighting, neutral backgrounds, minimalist composition, sharp focus, vertical 9:16, premium tech magazine look"` — came out of a grilling session. Nobody has seen Kling 3.0 std actually render it. If it produces cartoon-style or stock-photo output, the entire Pivot.6 visual direction is wrong — and that needs to be known before weeks of building Slices 4/5/8/9.

3. **Scripter prompts unverified against Kling.** The Ollama scripter generates 4 shot prompts per script. Those prompts have never been fed to Kling. If they contain phrases Kling's safety filter rejects, or if they're too abstract to render coherently, the scripter prompt-template needs work *before* the assembler is built.

The OpenRouter account holds $20.16 — a hard monthly budget topped up on the 1st of each month. This week's allocation is $5 (~2 videos at the projected unit cost). Spending all $5 calibrating means losing this week's content. Spending none means no de-risking of (1)-(3). The spike must live inside the existing weekly envelope.

## Solution

A staged Kling spike that:

1. **Uses two production-ready scripts already in the DB** from the 2026-05-20 run — Corti's Symphony Beats OpenAI in Medical Speech Recognition (quality=8.70) and AI Coding Speeds Up Android Apps (quality=8.60) — not hand-typed prompts. The spike thus doubles as an integration check of the upstream Ollama scripter's Kling-compatibility.

2. **Runs in three stages with halt-gates** so a catastrophic Stage 1 (~$0.34) stops the bleed before Stage 2 (~$1.01) or Stage 3 (~$1.34) ever fire.

3. **Pre-registers five hypotheses** (cost, latency, aesthetic, prompt-compatibility, coherence) so the post-spike question "did we learn anything?" has a deterministic answer.

4. **Hardcodes `audio: false`** in the OpenRouter Kling submit body before any spend, eliminating the 50% cost-overrun risk if Kling defaults to billing the with-audio rate ($0.126/sec).

5. **Tightens two config ceilings** (`per_clip_cost_cents_max`, `daily_spend_cents_ceiling`) so the existing quota guardrails actually bound a runaway loop. Current ceilings are 3-4× larger than real costs.

6. **Banks 8 successful MP4 shots on disk** as raw footage. When Slices 4/5/8/9 ship, those shots stitch into the first 2 production Shorts — so the $2.69 retroactively becomes week-1 production, not throwaway calibration.

## User Stories

1. As a creator on a $20/month OpenRouter budget, I want to ground-truth the actual per-shot cost via the response `usage.cost` field, so that monthly capacity planning (~14 vs ~7 videos) is based on measurement, not projection.

2. As a creator who has never seen Kling 3.0 std render the locked style suffix, I want a single $0.34 shot before any larger commit, so that an unworkable aesthetic kills the spike at 7% of the spike budget rather than 100%.

3. As a creator who knows Kling pricing differs by audio mode, I want the OpenRouter submit body to explicitly send the no-audio flag, so that I never accidentally pay the with-audio rate for output whose audio track I discard.

4. As a developer with two production-ready scripts in the DB, I want the spike to consume real Ollama-generated shot prompts rather than hand-typed ones, so that I learn whether my scripter prompt-template produces Kling-compatible output — not just whether Kling itself works.

5. As a creator who cares about end-product quality, I want the spike to verify that the 4 shots from a single script look stylistically coherent (same lighting, same world), so I know whether the assembler can stitch them without visible shot-to-shot drift.

6. As a developer iterating against pre-registered hypotheses, I want each shot's actual cost (cents), latency (submit-to-completed), output path, and any error persisted to a structured report, so the post-spike analysis is auditable and "was this useful?" has a numeric answer.

7. As a creator with a hard weekly budget cap, I want a halt-gate after Stage 1 (if cost > $0.50 OR aesthetic looks cartoon/stock) and a second halt-gate after Stage 2 (if the 4 shots don't look like the same world), so that a bad early signal stops further spend automatically.

8. As a creator with $2.31 of budget headroom planned, I want the spike to stop at Stage 3 (total $2.69) even if everything works, so I retain spike-overrun budget for unexpected reruns rather than chasing more samples.

9. As a developer touching the OpenRouter Kling client, I want the audio-off flag hardcoded (not parameterized), so the only mode we use is the only mode the code can produce — no risk of a downstream caller forgetting to pass it.

10. As a developer respecting the existing `quota_ledger` infrastructure, I want each shot's `usage.cost` recorded into `quota_usage(provider='openrouter')` via the existing DAL, so the spike participates in the same budget tracking the production pipeline will.

11. As a creator who wants the spike to retroactively become production, I want the 8 successful MP4 shots saved into the path scheme the future assembler expects (`data/ai_gen_shots/{...}/shot_{idx}.mp4`), so Slice 4 can consume them as-is without re-running Kling.

12. As a developer running the spike as a one-shot CLI command, I want operator prompts between stages ("Stage 1 done — view shot_0.mp4 — continue or halt?"), so that the halt-gates aren't fully automated on aesthetic judgments where my eye is the decider.

13. As a developer worried about runaway loops, I want `daily_spend_cents_ceiling` tightened from $10/day to $5/day, so a bug in the spike can at most blow one week's budget, not half the month's.

14. As a developer worried about per-shot cost spikes, I want `per_clip_cost_cents_max` tightened from $5 to $2, so the quota_ledger guardrail meaningfully fires before a single accidental clip consumes 1.5× the real cost.

15. As a developer maintaining a clean codebase, I want the spike runner script to be a throwaway artifact with no unit tests of its own, so it doesn't compromise the design of Slice 6's `run_ai_gen` orchestrator (which has its own test scaffolding waiting).

16. As a developer with a permanent change to the production OpenRouter client, I want a focused test on the audio-off flag being present in submit bodies, so a future refactor can't silently regress the cost model.

17. As a creator at a decision point after the spike, I want the final report to include a hypothesis pass/fail summary (3-of-5 = useful, ≤2 = wasted), so the next decision (proceed to Slices 4/5/8/9, or regroup) has explicit criteria.

18. As a creator whose budget refills only on the 1st of the month, I want the spike to execute within the current week's $5 allocation without dipping into next week's, so that a successful spike still leaves capacity to produce at least one shippable video this week if/when the assembler ships in time.

19. As a creator who has not yet built Slice 4 (assembler), I want the spike report to explicitly note that the 8 banked shots are NOT yet videos, so I don't conflate "spike succeeded" with "I have content to upload."

20. As a developer running on a Windows laptop with an 8 GB VRAM GPU, I want the spike to NOT trigger local GPU work (no Whisper, no NVENC), since all generation is server-side at OpenRouter — keeping local resource footprint to network I/O and a tiny SQLite write.

21. As a developer respecting existing parallelism decisions, I want Stage 2 (3 parallel shots) to use `ThreadPoolExecutor(max_workers=2)`, matching the CLAUDE.md-locked production parallelism — so the spike's latency measurements are predictive of weekly-run latency.

22. As a creator running the spike for the first time, I want a final markdown report at `logs/spike_report_2026-05-21.md` plus a single-line alert append to `logs/alerts.md` (kind=`spike_kling_complete`), so the outcome lives in the same observability sink as future production runs.

## Implementation Decisions

### Modules

Three touches: two production-permanent, one throwaway.

**Production-permanent: OpenRouter Kling client (`src/ai_gen/openrouter_kling.py`)**
- The `submit()` method's HTTP body (currently `{model, prompt, duration, aspect_ratio}`) gains a fifth key: the OpenRouter Kling no-audio flag.
- Exact flag name verified against OpenRouter's Kling docs immediately before the patch. If docs are ambiguous, fall back to empirical verification via Stage 1 — `usage.cost` of $0.34 (4 × $0.084) confirms no-audio mode; $0.50 (4 × $0.126) confirms audio-on default and forces a docs deep-dive before Stage 2.
- Hardcoded, not parameterized. This codebase's only mode is no-audio (Edge TTS owns narration). A parameter is over-engineering for a single-mode product, and "downstream caller forgot to set `audio=False`" is a class of bug the hardcoding makes impossible.

**Production-permanent: Config (`config.yaml`)**
- `ai_gen.per_clip_cost_cents_max: 500 → 200`. From $5 → $2 per clip; ~50% headroom over the $1.34 real per-clip cost. Replaces a near-useless 3.7× over-ceiling with a meaningful guardrail.
- `ai_gen.daily_spend_cents_ceiling: 1000 → 500`. From $10/day → $5/day; one week's budget is the panic-stop, not half the month.

**Throwaway: Spike runner (`scripts/spike_kling.py`)**
- Hand-runnable CLI. Deleted (or moved to `_archive/`) once Slice 4 lands a successful end-to-end render.
- Responsibilities:
  - Read Corti and AI Coding scripts from `data/state.db` (script_ids `7cb41305` and `d0da493f`). Fallback path: if either row is missing, replace with next-best `scripts` row by `quality_score DESC WHERE status='selected_for_render'`.
  - Stage 1: submit Corti shot 0 (duration_s=4, aspect_ratio="9:16"). Poll until terminal. Download MP4 to `data/ai_gen_shots/spike_2026-05-21/7cb41305_shot_0.mp4`. Record `usage.cost`, submit→completed elapsed, output path. Print summary + operator prompt.
  - Stage 2: submit Corti shots 1-3 via `ThreadPoolExecutor(max_workers=2)`. Same metrics, same operator prompt.
  - Stage 3: submit all 4 AI Coding shots (no further halt gate).
  - Per-shot: persist a `generation_jobs` row via existing DAL (`insert_generation_job`, `update_job_status`); record total spend as a `quota_usage(provider='openrouter')` row. If those helpers haven't shipped on the working-copy branch yet, degrade to a flat JSON metrics file alongside the MP4s.
  - Final: write `logs/spike_report_2026-05-21.md` with H1-H5 pass/fail table, append `logs/alerts.md` line (kind=`spike_kling_complete`).

### Halt gates

Two gates use the OR of an automated condition and an operator check:

| Gate | Auto-condition (immediate halt) | Operator condition (stdin prompt) |
|---|---|---|
| After Stage 1 | `usage.cost > $0.50` | Shot 0 looks cartoony / stock-photo / not editorial |
| After Stage 2 | (none — auto can't judge coherence) | Shots 0-3 don't look like the same scene/world |

Auto-halt writes the halt-report immediately and exits non-zero. Operator-halt blocks on stdin between stages with explicit prompt text quoting the gate condition.

### Pre-registered hypotheses

| ID | Hypothesis | Pass condition |
|---|---|---|
| H1 | Real cost matches projection | mean `usage.cost` across the 8 shots ≤ $0.34 |
| H2 | Latency fits weekly run budget | mean submit→completed < 90s, p95 < 150s |
| H3 | Locked style suffix produces editorial output | operator binary sign-off on a representative shot |
| H4 | Ollama scripter prompts are Kling-compatible | 0 of 8 shots failed for policy/banned-content reasons |
| H5 | 4-shot coherence is achievable | operator binary sign-off on the 4 shots of Corti script |

**Spike is "useful" iff ≥3 of 5 pass.** Below that, the next action is regroup on style suffix or prompt template — not proceed to Slices 4/5/8/9.

### Output paths

`data/ai_gen_shots/spike_2026-05-21/{script_id}_shot_{idx}.mp4`. This matches the production retention path scheme in CLAUDE.md (`ai_gen_shots/` 7d post-render TTL), so successful spike outputs are already in the right place for Slice 4's assembler to consume directly.

### Cost recording

Each shot's `usage.cost` (cents) is written to `generation_jobs.cost_cents`. Total spend is written to `quota_usage(provider='openrouter', units=<total_cents>)` via the existing DAL. The spike participates in the same budget-tracking infrastructure that will track production runs.

### Out-of-the-box budget context

Real per-shot cost (projected, no audio): $0.34. Per-video (4 shots): $1.34. Monthly capacity at $20: ~14 videos. Cadence cap: 8 videos/month (2/week). Spike total: $2.69. Spike-week budget remaining after a clean run: ~$2.31. None of these numbers are encoded in code — they live here as the documented framing.

## Testing Decisions

A good test in this codebase verifies external observable behavior through public interfaces — never internal call sequences or string contents of prompts. Concretely, an OpenRouter Kling client test verifies "given this prompt, the HTTP body sent to OpenRouter contains these keys with these values" — NOT "the `submit` method calls `_post_with_retry` first."

### Modules to be tested

**`src/ai_gen/openrouter_kling.py`** — ONE new test added to the existing `tests/ai_gen/test_openrouter_kling.py` suite (23 tests already shipped):
- Given a `submit()` call with any valid prompt/duration/aspect_ratio, the JSON body POSTed to `/api/v1/videos` contains the audio-off key with the audio-off value. Mock the HTTP session, capture the body via the mock, assert the key. Additive — no changes to existing tests.

**`scripts/spike_kling.py`** — NO tests. Throwaway operator script; deleted post-Slice-4. Manual operation + MP4 inspection + the final hypothesis report IS the test. Adding unit tests to throwaway code is the "design for hypothetical futures" pattern CLAUDE.md cautions against.

**`config.yaml`** — NO tests. Declarative config; existing `tests/test_config_p4.py` already validates these Pydantic fields, and the change is a numeric edit within validated ranges.

### Prior art

- `tests/ai_gen/test_openrouter_kling.py` — 23 tests, exemplar for HTTP-body-shape testing under a mocked `requests.Session`. The audio-off test follows the same pattern (mock session → call submit → inspect captured request body).

## Out of Scope

Explicitly NOT in this PRD:

- **Slice 4 (assembler wire-up)** — `ai_gen` → `narration` → `assembler` integration. The spike produces raw shots only.
- **Slice 5 (subtitles)** — Whisper forced-align + ASS burn-in.
- **Slice 8 (`gen_run.py` orchestrator)** — weekly-cadence pipeline runner.
- **Slice 9 (AI-disclosure upload templater)** — uploader changes for `content_kind='ai_generated'`.
- **Style-suffix iteration on real Kling output** — the locked clean-editorial suffix stands until the spike disproves it. If H3 fails, the follow-up is a new PRD, not in this scope.
- **Provider abstraction changes** — `src/ai_gen/base.py` is unchanged; the ABC is exercised only via the concrete `OpenRouterKlingClient`.
- **Retry-on-failure behavior** — Kling-side failures (status='failed') are recorded and reported but NOT retried in the spike. Retry policy is a Slice 6 concern.
- **Persistent `generation_jobs` schema bootstrapping** — if the upstream Ticket 01 migration hasn't been applied to the working-copy DB, the spike falls back to JSON metrics. The migration itself is the upstream PRD's responsibility.
- **Tuning the per-shot duration (4s)** — locked from CLAUDE.md and `plan.md`. Variable duration is a future Slice 6+ concern.
- **Adding model fallbacks (Pika, MiniMax, Seedance)** — the provider abstraction supports drop-in swaps but the spike only exercises `kwaivgi/kling-v3.0-std`.

## Further Notes

- This PRD is the unblocking precondition for Slices 4/5/8/9. Until the spike completes and ≥3-of-5 hypotheses pass, those slices remain blocked. No point building the assembler if the visual generator produces unworkable output; no point building the orchestrator if per-video cost is double the budget model.
- The spike intentionally consumes real Ollama-generated prompts rather than hand-typed ones. This trades the original Slice 2 plan's "Kling-in-isolation" clarity for upstream-pipeline integration coverage. The decision is reversible: if H4 fails (prompts blocked by Kling policy), the next iteration uses hand-typed prompts to isolate the failure to the prompt template vs Kling itself.
- The 50% cost-overrun risk from an audio-on default is genuine — OpenRouter documents Kling 3.0 std at $0.084/s (no audio) vs $0.126/s (with audio). The audio-off patch lands BEFORE Stage 1 spend, regardless of how the flag is verified (docs read or empirical check).
- After the spike, `scripts/spike_kling.py` is deleted (or moved to `_archive/`) once Slice 4's `scripts/render_from_script.py` produces a successful end-to-end render. The audio-off patch and config tweaks remain permanent.
- The two source scripts were chosen because they were the top 2 of the 2026-05-20 production run (both quality > 8.5, well above the 6.0 floor). Substituting alternative top-of-pool scripts is acceptable if their rows are unavailable; the spike's signal does not depend on these specific stories.
- This is the first time real OpenRouter money is spent on this project. A "no Kling spend before audio-off flag is in code" working agreement applies for the remainder of Pivot.6.

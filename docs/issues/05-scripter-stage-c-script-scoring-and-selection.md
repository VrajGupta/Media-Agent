# Ticket 05 — Scripter Stage C: script scoring + top-2 selection + quality-floor failure modes

**Type:** AFK
**Slice in plan.md:** Slice 6 (Stage C of three)
**User stories covered:** 1, 9, 13, 14, 15, 19

## Parent

PRD: `docs/prds/automated-topic-to-script-pipeline.md`

## What to build

The final stage of `src/scripter/` — takes the 4 (or fewer) `scripted` scripts from Stage B, re-scores each with Ollama on a script-quality rubric (different from the topic rubric), picks the top 2 above the quality floor, and applies the failure matrix when the floor isn't met. Output: top scripts transition to `status='selected_for_render'`; below-floor scripts halt+alert their slot.

Public function: `score_and_select_scripts(scripts, scorer_fn, cfg) -> list[Script]`. Ollama callable injected.

Script scoring rubric (different from topic scoring):

- **Hook execution** (40%) — Does the first sentence hit hard, or does it bury the lede?
- **Pacing** (30%) — Does each of the 4 shots deliver something new, or is shot 2 just rephrasing shot 1?
- **Payoff** (30%) — Does the ending land — surprise, callback, or teaser — or just stop?

Ollama JSON-mode returns `{hook_execution: int 1-10, pacing: int 1-10, payoff: int 1-10, reason: str}`. Local code computes `quality_score = 0.4*hook + 0.3*pacing + 0.3*payoff`. Persists `quality_score_json` (sub-scores + reason) and denormalized `quality_score` (float) onto the `scripts` row.

Selection + quality floor: sort by `quality_score` DESC. If top 2 both ≥ `cfg.scripter.quality_floor` (default 6.0) → both selected for render. If only top 1 ≥ floor → render that one, halt+alert on the other slot. If even top 1 < floor → halt+alert on both slots; no scripts selected for render that week.

A CLI entrypoint (`python -m src.scripter --stage c`) runs this stage on the existing `scripted` scripts.

## Acceptance criteria

- [ ] Public function `score_and_select_scripts(scripts, scorer_fn, cfg)` in `src/scripter/runner.py`.
- [ ] Scorer returns valid sub-scores in 1-10 range. Out-of-range → retry once, then drop that script (don't halt the whole batch).
- [ ] Weighted score formula: `0.4*hook + 0.3*pacing + 0.3*payoff`. Test verifies the exact math.
- [ ] `quality_score_json` persisted with full sub-scores + reason; `quality_score` (float) denormalized for sort.
- [ ] Top 2 both ≥ floor: both transition to `status='selected_for_render'`. The other (lower-scored) scripts stay at `status='scripted'`.
- [ ] Only top 1 ≥ floor: that one transitions to `selected_for_render`; alert kind=`script_quality_floor_one_slot` written with the floor + actual top scores.
- [ ] None ≥ floor: zero scripts selected for render; alert kind=`script_quality_floor_zero_slots` written; the week's `runs.md` row reflects 0 clips queued.
- [ ] Ties (e.g., two scripts at exactly 7.5) → deterministic tiebreak by `scripts.created_at ASC` then `script_id ASC`.
- [ ] When input is <4 scripts (Stage B returned fewer due to backfill exhaustion): still scores all available, applies same floor logic; possible outcomes are 0, 1, or 2 selected.
- [ ] Config: `Config.scripter` gains `script_score_weights: {hook_execution: 0.4, pacing: 0.3, payoff: 0.3}`, `quality_floor: float = 6.0`, `weekly_clip_target: int = 2`.
- [ ] CLI: `python -m src.scripter --stage c`. `--dry-run` reads + scores but doesn't transition status or write alerts.
- [ ] Ollama scorer fully mocked in tests.
- [ ] At least 10 unit tests covering: happy path (both top ≥ floor), only top 1 ≥ floor → alert + 1 selected, none ≥ floor → alerts on both slots + 0 selected, tiebreak determinism, out-of-range retry then drop one script, <4 input scripts (e.g., backfill returned 2), exact-floor boundary (6.0 selects, 5.99 rejects), audit JSON persistence, dry-run no-write, weighted-score formula.

## Blocked by

- Ticket 01 (schema), Ticket 04 (needs `scripted` scripts to score).

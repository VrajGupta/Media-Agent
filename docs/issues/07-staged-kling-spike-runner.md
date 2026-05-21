# Issue 07 — Staged Kling spike runner

## Parent

`docs/prds/slice-2-kling-spike.md` (Slice 2: OpenRouter Kling 3.0 spike)

## What to build

A throwaway hand-runnable CLI at `scripts/spike_kling.py` that executes the staged Kling spike against real Ollama-generated prompts from the 2026-05-20 production run. Throwaway means: no unit tests of its own (manual MP4 inspection + the final hypothesis report IS the test), deletable once Slice 4's `scripts/render_from_script.py` produces a successful end-to-end render.

End-to-end behavior:

1. **Stage 1** — Read Corti's Symphony script (id `7cb41305`) from `data/state.db`. Submit shot 0 to OpenRouter Kling 3.0 std with `duration_s=4`, `aspect_ratio="9:16"`. Poll until terminal. Download MP4 to `data/ai_gen_shots/spike_2026-05-21/7cb41305_shot_0.mp4`. Record `usage.cost`, submit→completed latency, output path. Print summary + halt-gate prompt. **Auto-halt** if `usage.cost > $0.50`. **Operator-halt** via stdin if shot 0 looks cartoony / stock-photo / not editorial.

2. **Stage 2** — Submit Corti shots 1, 2, 3 in parallel via `ThreadPoolExecutor(max_workers=2)`. Same metric capture per shot. After all complete, print summary + operator coherence-gate prompt ("Are the 4 shots stylistically consistent — same lighting, same world?"). **Operator-halt** via stdin if no.

3. **Stage 3** — Read AI Coding script (id `d0da493f`) from `data/state.db`. Submit all 4 shots in parallel via `ThreadPoolExecutor(max_workers=2)`. Same metric capture per shot. No further halt gate.

4. **Reporting** — After Stage 3 (or at any halt point), write `logs/spike_report_2026-05-21.md` with:
   - Per-shot table: shot id, cost, latency, output path, status
   - Hypothesis pass/fail table (H1–H5 per the parent PRD)
   - Top-line verdict: "useful (≥3 of 5 passed)" or "money-wasted (≤2 of 5 passed)"
   - Append one-line entry to `logs/alerts.md` with kind=`spike_kling_complete`

5. **Persistence** — Each shot writes a row to `generation_jobs` via existing DAL helpers (`insert_generation_job`, `update_job_status`). Total spend writes one row to `quota_usage(provider='openrouter', units=<total_cents>)`. **Fallback:** if those DAL helpers aren't on the working-copy branch yet, degrade to a flat JSON metrics file at `data/ai_gen_shots/spike_2026-05-21/metrics.json` alongside the MP4s.

6. **Fallback script selection** — If either Corti or AI Coding script row is missing or corrupt by run time, the spike substitutes the next-best script: `SELECT * FROM scripts WHERE status='selected_for_render' ORDER BY quality_score DESC` and use the first one not already chosen.

7. **`--dry-run` mode** — A `--dry-run` flag walks all 3 stages with a mock provider that returns canned successful responses without touching the network. No money spent. Used for pre-flight verification that the script's flow / DB reads / file writes work before any live API call.

## Acceptance criteria

- [ ] `scripts/spike_kling.py --dry-run` walks all 3 stages, makes zero HTTP requests, writes a complete (mocked-data) report at `logs/spike_report_2026-05-21.md`, exits zero
- [ ] Live mode (no flag) reads the two scripts from `data/state.db` and submits real Kling calls in the staged pattern
- [ ] Stage 1 halt-gate fires (process exits, halt-report written) if `usage.cost > $0.50` for the single Corti shot
- [ ] Stage 1 halt-gate fires if operator types `halt` at the stdin prompt
- [ ] Stage 2 uses `ThreadPoolExecutor(max_workers=2)` (matches CLAUDE.md-locked production parallelism)
- [ ] Stage 2 halt-gate fires if operator types `halt` at the coherence prompt
- [ ] All successful shots land at `data/ai_gen_shots/spike_2026-05-21/{script_id}_shot_{idx}.mp4` (matches the production retention path scheme in CLAUDE.md)
- [ ] Each successful shot persists a `generation_jobs` row OR (fallback) appears in `data/ai_gen_shots/spike_2026-05-21/metrics.json`
- [ ] Total spend persists as a `quota_usage(provider='openrouter')` row OR (fallback) appears in the metrics JSON
- [ ] Final report `logs/spike_report_2026-05-21.md` contains the per-shot table and the H1–H5 pass/fail table
- [ ] `logs/alerts.md` gains a one-line entry with kind=`spike_kling_complete` on terminal completion (success or halt)
- [ ] No unit tests added for `scripts/spike_kling.py` itself (throwaway scope per parent PRD)
- [ ] No changes to `src/` modules outside of any fallback necessitated by missing DAL helpers (which would themselves be flagged as a separate concern, not absorbed silently)

## Blocked by

Issue 06 — must merge first. The audio-off flag must be in `src/ai_gen/openrouter_kling.py` before Stage 1's live call, otherwise the spike risks a 50% cost overrun.

# Issue 37 — Pre-billing narration policy check; remove the misfit policy_gate.run_all

**Status:** ready-for-agent
**Type:** AFK
**User Stories:** 11, 12, 13, 14 (PRD `first-live-hybrid-gen-run.md`)

## Parent

PRD: `docs/prds/first-live-hybrid-gen-run.md`

## What to build

Stop a policy-violating script from being rendered in full (~$2 of Kling) before it is
caught. Today the `gen_run` policy stage is the **legacy transcript-clip gate**: it runs
before any clip exists, in a pipeline with no transcripts, so it always logs "no
candidates" and gates nothing. Real narration policy runs only at upload time.

End-to-end behavior:

1. Remove the misfit `policy_gate.run_all` call from `gen_run`.
2. For each selected script, run the existing policy evaluator on the script's
   **narration + title** *before* ai_gen billing. A failing verdict **skips** that script
   (logged, not billed, not rendered); other selected scripts still proceed.
3. An infrastructure failure (Ollama) leaves the script unprocessed for this run with no
   spend, consistent with the existing fail-soft pattern — it is not force-rejected.
4. The uploader's pre-upload policy re-check is left **unchanged** as defense-in-depth.

This reuses the same evaluator and the same text (narration + title) the uploader already
trusts — only the timing moves earlier.

## Acceptance criteria

- [ ] `policy_gate.run_all` is no longer called from `gen_run`; the "no candidates" log is
      gone.
- [ ] Each selected script's narration + title is policy-checked before ai_gen billing.
- [ ] A script that fails policy is skipped with no Kling client constructed/called;
      sibling selected scripts still proceed.
- [ ] An infrastructure failure leaves the script unprocessed with no spend (no
      force-reject).
- [ ] The uploader pre-upload re-check is unchanged.
- [ ] Unit test (alongside the existing hybrid gen_run tests): violating narration → script
      skipped, no Kling call; passing narration → proceeds to billing. Full suite green.

## Blocked by

- Issue 35 — both edit gen_run's per-script loop; land 35 first to avoid a conflict.

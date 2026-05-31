# Handoff — issues-35-37-tdd
**Date:** 2026-05-31
**Project:** Media-Agent (Pivot.6 → Pivot.7)
**Working directory:** C:\Users\cryptix\Desktop\Work\Media-Agent-main

## What was accomplished this session

- **Issue 35 shipped:** `resolve_licensed_image()` (fetch+validate+cache, licensed-only, non-raising); `resolve_shot_plan` resolver seam carries `image_asset`; `gen_run` single resolve + threaded plan; cap **250¢**; `probe_licensed_image` retired.
- **Issue 36 shipped:** niche gate infra fail-open + `niche_gate_unavailable` alert; off/on niche behavior unchanged.
- **Issue 37 shipped:** removed `policy_gate.run_all` from `gen_run`; pre-billing `evaluate_clip_policy(narration, title)` per script.
- **Issue 38 partial:** dry-run `gen_run --dry-run --clips 1` exit 0; `spike_hybrid.py` superseded; live run + HITL still operator-owned.
- **Tests:** 48 targeted tests green; `progress.md` updated.

## Current state

- Code on disk; ready to commit/push.
- **Issue 38 open:** operator must run live `python -m src.gen_run --clips 1`, ffprobe 1080×1920, reconcile OpenRouter cost ≤250¢, eyeball hybrid mix, record evidence in `progress.md`.
- Prior uploads unchanged: Slice 10 `9lpL8kuLX08`; sample `qRdVYO1Tmfw` scheduled 2026-06-02 09:00 SGT (ai_video-only, not hybrid).

## Immediate next action

Operator-run **Issue 38** live verification:

```powershell
python -m src.gen_run --clips 1
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 output/pending/<clip>.mp4
```

Pick a topic with good logo/Wikimedia coverage; drag to `output/approved/` only after HITL eyeball. Issue 29 ship remains out of scope.

## Open decisions / blockers

- Niche prompt retune still deferred (G3) until live-run verdict evidence.
- Live dry-run selected a script but policy infra-failed on empty hook input under dry-run scripter stubs — live run with real Ollama scripts should not hit this.

## Artifacts created this session

| Artifact | Path | Notes |
|---|---|---|
| Licensed resolver | `src/image_fetch/fetcher.py::resolve_licensed_image` | Replaces probe |
| Shot plan | `src/scripter/shot_plan.py` | `licensed_resolver` seam |
| gen_run wiring | `src/gen_run.py` | Single resolve + pre-billing policy |
| Niche gate | `src/topic_ingest/runner.py::_apply_niche_gate` | Infra fail-open |
| Config | `config.yaml` | `per_clip_cost_cents_max: 250` |
| Tests | `tests/test_hybrid_gen_run_policy.py` | New |
| TDD log | `.sessions/2026-05-31__issues-35-37-tdd/tdd/cycles.md` | |

## Skills used this session

| Skill | File | Purpose |
|---|---|---|
| `/tdd` | `C:\Users\cryptix\.claude\skills\tdd\SKILL.md` | RED→GREEN for Issues 35–37 |
| `/handoff` | `C:\Users\cryptix\.claude\skills\handoff\SKILL.md` | This document |

## Suggested skills for next session

- `/handoff` after Issue 38 live verify + evidence in `progress.md`

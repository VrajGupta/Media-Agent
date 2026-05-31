# TDD cycles — Issues 35–37

## Issue 35 (resolve fetches-and-caches)
1. **RED→GREEN:** `test_all_licensed_hits_carry_resolved_assets` → `shot_plan.py` resolver seam (`ImageAsset | None`).
2. **RED→GREEN:** `test_licensed_miss_degrades_real_image_to_ai_video` → degrade path unchanged.
3. **RED→GREEN:** `test_resolve_licensed_image_never_consults_web` → `resolve_licensed_image()` in `fetcher.py`; retired `probe_licensed_image`.
4. **RED→GREEN:** `test_render_reuses_cached_asset_without_second_fetch` → `_render_real_image_shot` reads `shot["image_asset"]`.
5. **RED→GREEN:** `test_four_ai_video_shots_rejected_before_billing` → single resolve in `run_generation` + cap 250.
6. **RED→GREEN:** `test_resolve_shot_plan_called_once_per_script` → `resolved_shots` threaded into `_generate_clip`.

## Issue 36 (niche gate infra split)
1. **RED→GREEN:** `test_infra_failure_keeps_topic_and_emits_alert` → `_apply_niche_gate` fail-open + alert.
2. **RED→GREEN:** `test_off_niche_still_dropped` / `test_on_niche_still_kept` → regression guards.

## Issue 37 (pre-billing policy)
1. **RED→GREEN:** `test_policy_violation_skips_script_without_kling` → removed `policy_gate.run_all`; per-script `evaluate_clip_policy`.
2. **RED→GREEN:** updated `tests/test_gen_run.py` orchestration mocks.

**48 targeted tests green** (2026-05-31).

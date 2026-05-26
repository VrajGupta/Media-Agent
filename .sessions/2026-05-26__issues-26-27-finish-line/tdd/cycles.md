# TDD cycles — Issue 26 licensed-only sourcing

1. **RED→GREEN:** `test_all_licensed_hits_leaves_shot_list_unchanged` → `resolve_shot_plan`
2. **RED→GREEN:** `test_licensed_miss_degrades_real_image_to_ai_video` → degrade prompt + billable count
3. **RED→GREEN:** `test_generate_clip_resolves_shots_before_kling_submission` → gen_run wiring
4. **RED→GREEN:** `test_probe_licensed_image_never_consults_web` → `probe_licensed_image`
5. **RED→GREEN:** config + bootstrap copyright tests

Issue 27 was non-TDD chores (docs, CLAUDE.md dedup, progress.md).

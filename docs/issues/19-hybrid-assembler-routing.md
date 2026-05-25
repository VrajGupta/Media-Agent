# Ticket 19 — Hybrid assembler: kind-aware shot routing + crossfades

**Status:** ready-for-agent
**Type:** AFK
**Slice:** Pivot.7 / P7.5
**User Stories:** 2, 3, 16, 17 (PRD `pivot-7-hybrid-real-image-shorts.md`)

## Parent

PRD: `docs/prds/pivot-7-hybrid-real-image-shorts.md`

## What to build

Wire the hybrid visual path end-to-end: route each shot by `kind` to its builder, concatenate the mix, and add optional crossfades so cuts flow.

End-to-end behavior:

1. **Kind-aware routing.** In `gen_run._generate_clip`, run `normalize_shots` (Ticket 15) on the script's shots, then for each shot:
   - `ai_video` → existing `ai_gen.generate_shots` (Kling) — only the `ai_video` shots are submitted, so Kling cost ≈ halves.
   - `real_image` → `image_fetch.fetch_image` (Ticket 17) → `build_ken_burns_argv` + `run_ffmpeg` (Ticket 18) → `shot_XX.mp4`.
   - Both kinds yield ordered `shot_XX.mp4` paths in shot order.
2. **Crossfade path (assembler).** `build_assembler_argv` gains an optional crossfade mode:
   - `assembler.crossfade_enabled=true` → join shots with `xfade` (duration `assembler.crossfade_duration_s`, default 0.25) via a `filter_complex` chain; total duration accounts for overlap.
   - `assembler.crossfade_enabled=false` → existing concat-demuxer hard-cut path, **byte-identical** to today (regression-protected).
   - The crossfade builder stays a pure argv function.
3. **Failure handling.** If `fetch_image` raises (no usable image) for a `real_image` shot, log + (config choice) either skip that clip or substitute a degraded handling — default: log the failure and skip the clip (consistent with `gen_run`'s per-clip try/except), so one bad entity doesn't abort the batch.
4. **Cost guard.** Per-clip cost projection now counts only `ai_video` shots against `per_clip_cost_cents_max` / `daily_spend_cents_ceiling`.
5. **Config.** `assembler.crossfade_enabled` (default true), `assembler.crossfade_duration_s` (default 0.25).

No DB schema change. Billed calls limited to the `ai_video` shots only.

## Acceptance criteria

- [ ] `_generate_clip` routes `ai_video` shots to Kling and `real_image` shots to fetch+Ken Burns, preserving shot order; only `ai_video` shots hit OpenRouter.
- [ ] `build_assembler_argv` crossfade-enabled path emits `xfade` with the configured duration; crossfade-disabled path is byte-identical to the current concat-demuxer argv (regression test).
- [ ] A `fetch_image` failure for one clip is logged and that clip is skipped without aborting the batch.
- [ ] Per-clip cost projection counts only `ai_video` shots against the cost ceilings.
- [ ] `assembler.crossfade_*` config keys load with the documented defaults.
- [ ] **Tests Required** (≥ 6): routing partitions shots by kind (Kling called only for ai_video — assert via mock); crossfade-enabled argv contains `xfade` with configured duration; crossfade-disabled argv == current concat-demuxer argv (regression); fetch_image failure → clip skipped, batch continues; cost projection counts ai_video only; mixed-order shots preserved.
- [ ] **Mock Injections:** mock `ai_gen.generate_shots`, `image_fetch.fetch_image`, and `run_ffmpeg` — no real Kling calls, no network, no ffmpeg execution. Follow existing `gen_run` test patterns.
- [ ] Full suite green.

## Blocked by

Tickets 15 (tagged shots), 17 (`image_fetch`), 18 (Ken Burns). Soft-needs Ticket 16 for a *complete* clip, but the routing/crossfade logic is independently testable.

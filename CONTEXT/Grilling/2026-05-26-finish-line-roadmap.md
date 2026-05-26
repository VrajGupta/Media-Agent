# Grill record — remaining roadmap to project completion

**Date:** 2026-05-26
**Trigger:** Hybrid-assembly bug fix is shipped (`bca0095`, Issues 22–25). User asked
to grill "what's left to finish the project" before a PRD.
**Mode:** `/grill-with-docs`. User delegated most decisions; explicitly chose the
image-licensing posture (D2) when asked.

## North star — what "done" means

The project's identity is a **fire-and-forget** agent. "Done" =

> The autonomous loop (weekly `gen_run` + daily `daily_upload`) runs unattended and
> ships **Hybrid clips** (Tech/AI Shorts) on the Tue/Thu cadence, with the first
> hybrid Short live-verified through the two-gate sign-off.

Everything past that (thumbnails, A/B titles, TikTok, quota-increase audit, dashboard,
scripter-quality grill) is post-completion stretch — explicitly **not** "done".

## Verified code facts

- **Hybrid is already the default path.** Scripter prompt (`src/scripter/ollama_fns.py:140`)
  targets "~2 real_image + ~2 ai_video, alternating." `gen_run._generate_clip` routes
  per-Shot-kind. A **Clip** is still `Content kind = ai_generated`; hybrid is the
  **Shot kind** mix.
- **Cost ceilings already tuned for hybrid:** `ai_gen.per_clip_cost_cents_max: 100`
  (~2 Kling shots), `daily_spend_cents_ceiling: 500`.
- **Image sourcing:** `image_fetch.sources: [logo, wikimedia, openverse, web]`,
  `web_fallback_enabled: true`. Living-person entities rejected.
- **Stale config:** `copyright_acknowledgement: "movie_clips_v1"` — a fossil from the
  retired movie-clip pivot; does not describe hybrid real-image risk.

## Decisions locked

| # | Decision | Rationale |
|---|---|---|
| D1 | **Hybrid is the default content path** (no toggle). A clip is `ai_generated`; the real_image/ai_video mix is per-Shot. | Already true in code; documented, not changed. |
| D2 | **Licensed-only image sourcing for the autonomous path** (`web_fallback_enabled: false`, `sources: [logo, wikimedia, openverse]`); on licensed miss, degrade the real_image shot to ai_video; web fallback stays for the manual spike/dev. → **ADR-0003**. Update `copyright_acknowledgement` to a hybrid value. | A fire-and-forget agent must not auto-publish unvetted web images (outward-facing, hard to reverse). User chose this option. |
| D3 | **Sequencing (hard gates):** (1) live hybrid spike + HITL sign-off → (2) Slice 8 unattended end-to-end verify → (3) cadence live-verify → (4) first hybrid ship two-gated. | Validate mechanics on one clip before trusting the unattended run, per ADR-0001's philosophy. |
| D4 | **The first hybrid ship is a "first live ship" under ADR-0001** (two-gate), even though `Content kind` is unchanged, because real_image sourcing is a new external-content (licensing/Content-ID) surface. | ADR-0001 scope extended in spirit: a materially new content *form*, not just a new `Content kind`. |
| D5 | **Slice 8 "done" =** one real unattended `gen_run` (no `--dry-run`) from live RSS produces ≥1 hybrid **Clip** in `output/pending/`, within cost ceiling, run-lock + `runs.md` row, slotted onto a Tue/Thu `publish_at`; `--dry-run --clips 1` walks the pipeline with no writes. | This is the existing Slice 8 acceptance, now exercisable because hybrid assembly works. |
| D6 | **Slice 10 gates: confirm-and-tick.** Shipped 2026-05-24; T+1h and T+48h windows have elapsed by 2026-05-26 — verify Studio toggle / still-public / no-CID / OpenRouter ±5% and mark `[x]`. HITL. | No new work; just close the open boxes. |
| D7 | **Housekeeping:** canonical doc file = `CLAUDE.md` (reconcile the `claude.md` case-duplicate, remove the lowercase copy); write the missing `docs/rss_feeds.md` (curated feeds + rationale); commit the 3 uncommitted follow-up files; **CUDA cuBLAS PATH** deferred as a tracked perf item (document steps, non-blocking). | Drift hazards + a stale Slice 7 deliverable; cuBLAS is perf-only (CPU fallback works). |

## Doc corrections required (tracked in PRD/issues)

- `config.yaml`: `web_fallback_enabled: false`, `sources: [logo, wikimedia, openverse]`,
  `copyright_acknowledgement: hybrid_real_image_v1` (per ADR-0003).
- Reconcile `CLAUDE.md` / `claude.md` to a single canonical `CLAUDE.md`.
- Finish hybrid-model updates in `CLAUDE.md` / `agents.md` / `skills.md` (P7.7 `[~]`).

## Out of scope for "done" (explicit)

- Phase 8 stretch (thumbnails, A/B titles, TikTok/Reels, dashboard).
- Quota-increase audit / collapsing `daily_upload` into `gen_run`.
- Scripter content-quality grill (deferred from 2026-05-23).
- Motion-interpolated 24→30fps; higher Kling resolution tier.
- Backfilling the already-shipped 720×1280 Slice 10 clip.

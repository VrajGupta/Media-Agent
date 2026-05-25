# Phase: planning
**Project:** Media-Agent (Pivot.6)
**Status:** complete
**Last updated:** 2026-05-24

## Objective

Lock the niche, content format, budget, weekly cadence, and tech stack direction for the Pivot.6 AI-generated YouTube Shorts pipeline. All strategic decisions were made in this phase; downstream phases implement them without debate.

## Key Decisions

- **Niche locked:** Tech/AI news Shorts only. No gameplay, no movie clips, no podcasts.
- **Content kind:** `ai_generated` — Kling 3.0 visuals + Edge TTS narration. No real footage.
- **Weekly output target:** 2 clips/week, $5 budget (OpenRouter Kling 3.0 std only).
- **Cadence:** 1 upload/day (slot-planned), weekly heavy run (`gen_run.py`) every Sunday.
- **Topic source:** RSS feeds — 7 feeds (Ars Technica, TechCrunch, The Verge, OpenAI, DeepMind, HuggingFace, VentureBeat). 48-hour recency window, Jaccard ≥ 0.6 dedup.
- **Script writer:** Ollama `qwen2.5:3b-instruct` (local, free). JSON-mode, 30–50 word narrations, 4 shots.
- **Video generator:** OpenRouter Kling 3.0 std (`kwaivgi/kling-v3.0-std`). $0.126/s billed at 5s minimum with audio.
- **Narration voice:** Edge TTS `en-US-GuyNeural`, +10% rate, 0Hz pitch.
- **Visual style suffix:** "clean editorial product photography, soft studio lighting, neutral backgrounds, minimalist composition, sharp focus, vertical 9:16, premium tech magazine look"
- **Human review:** `human_review: true` for first 2 weeks (filesystem gate — drag-to-approved).
- **Timezone:** Asia/Singapore.
- **AI disclosure:** Always-on. `status.containsSyntheticMedia=true` + description footer on every upload.
- **Music:** YouTube Audio Library only (CID safety). No other royalty-free sources.
- **Build order constraint:** Slices 3→7→6 first (free upstream pipeline) before Kling spend. Produce real scripts, validate quality, then top up OpenRouter.
- **Cost reality check (Slice 2 spike 2026-05-21):** Projected $0.34/shot; actual $0.63/shot. Kling bills 5s min with audio even when `enable_audio: False`. `per_clip_cost_cents_max: 350` (updated from 200).
- **Two-gate sign-off on first live upload (Slice 10):** T+1h ship gate + T+48h stability gate (ADR-0001).
- **Slice 10 ship bar = mechanics validation** (2026-05-24): test channel, "compliant + not embarrassing", not portfolio quality. Term defined in `CONTEXT/CONTEXT.md`.
- **Slice 10 lead frame = shot 3** (clinician + medical scan), order `3,2,1,0`. Supersedes "swap 0↔1 → whiteboard thumbnail": only shot 0 came from a named-person prompt; disclosure covers the generic synthetic clinicians; whiteboard frame has garbled AI text.
- **Slice 10 cost baseline = 315¢** (5 succeeded renders; shot 0 billed twice). Reconcile with `status='succeeded'`, not raw `SUM` (=621¢ incl. dry-runs).
- **Slice 10 stitch = `render_from_script.py --reuse-shots/--order`** (reuse paid shots, no regeneration) — reverses Issue 11's original "separate one-off script" approach.
- **First-ship slot decoupled** from steady-state cadence: same-day near-term slot (≈ now+45 min) so the T+1h gate can verify the public flip.
- **Steady-state cadence = Tuesdays & Thursdays** (Slice 11). Needs a new `upload_weekdays` allowlist + allocator weekday filter; `slot_planner` has no weekday support today. `clips_per_day` → 1 (2 clips/week, budget).

## Accomplishments

- [2026-05-18] Niche pivot decided in /grill-with-docs session. All architecture decisions locked.
- [2026-05-18] PRD written: `docs/prds/automated-topic-to-script-pipeline.md`.
- [2026-05-18] 10-slice Pivot.6 plan written: `plan.md`.
- [2026-05-18] CLAUDE.md updated to reflect Pivot.6 architecture and operational model.
- [2026-05-21] Slice 2 spike completed — cost model corrected, Slices 4/5/8/9 unblocked.
- [2026-05-23] Slice 10 operational plan locked in /grill-with-docs. Two-gate sign-off formalized as ADR-0001.
- [2026-05-23] Music policy finalized: YouTube Audio Library only (user replaced phonk tracks).
- [2026-05-23] Candidate script locked: `7cb41305` ("Corti's Symphony Beats OpenAI in Medical Speech Recognition", 31 words, VentureBeat-sourced).
- [2026-05-24] /grill-with-docs refined Slice 10 against verified DB/disk state; six decisions locked (see grill record). Created `CONTEXT/CONTEXT.md` glossary.
- [2026-05-24] /to-prd published Slice 11 cadence PRD; amended stale Slice 10 PRD + Issues 11/12.
- [2026-05-24] /to-issues published Issue 14 (weekday cadence allowlist, AFK, no blockers).

## Artifacts

| Artifact | Path | Notes |
|---|---|---|
| Pivot.6 PRD | `docs/prds/automated-topic-to-script-pipeline.md` | Source of truth for niche + pipeline contract |
| 10-slice plan | `plan.md` | Readable narrative; slice deps, HITL/AFK labels |
| Architecture overview | `CLAUDE.md` | System overview for agents — read first |
| Two-gate ADR | `docs/adr/0001-two-gate-signoff-for-live-uploads.md` | Slice 10 sign-off protocol |
| Historical plans | `plan.archive.md` | Phases 0–7, Pivots 0–5 archived here |
| Domain glossary | `CONTEXT/CONTEXT.md` | Topic/Script/Shot/Clip + ship-lifecycle terms |
| Slice 11 PRD | `docs/prds/slice-11-tue-thu-publish-cadence.md` | Tue/Thu cadence; `ready-for-agent` |
| Grill record (Slice 10 refine) | `CONTEXT/Grilling/2026-05-24-slice-10-first-ship.md` | Six locked decisions + verified state |

## Sessions

- Niche lock + PRD (2026-05-18)
- Slice 2 spike cost reconciliation (2026-05-21)
- Slice 10 operational plan grilling (2026-05-23)
- Slice 10 refine + Slice 11 cadence (2026-05-24) — `.sessions/2026-05-24__slice-10-refine-slice-11-cadence/handoff.md`

## Open Items

- Slice 10 not yet ship-verified (T+1h gate) or stability-verified (T+48h gate). The candidate clip still needs assembly (Issue 11) before the gate can run.
- Slice 11 (Tue/Thu cadence) PRD + Issue 14 written but not implemented — `slot_planner` weekday filter is the build.

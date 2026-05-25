# Session Handoff — 2026-05-25

## 1. Executive Summary & Goal

* **Current Mission:** Design **Pivot.7** — replace the all-Kling visual path with a **hybrid clip** (real sourced images for recognizable entities + Kling AI shots as transitions), and swap Edge TTS for local **Kokoro** narration. This session produced planning artifacts only — **no `src/` code was written.**
* **Status:** Pivot.6 is live (Slice 10 uploaded `9lpL8kuLX08`; Slice 11 Tue/Thu cadence code complete). **Pivot.7 is fully specced and ticketed, NOT STARTED.** PRD + Issues 15–21 published; `plan.md` + `progress.md` updated.

## 2. Recent Accomplishments (this session)

Planning artifacts (filesystem tracker):

* **PRD:** `docs/prds/pivot-7-hybrid-real-image-shorts.md` — problem, solution, 28 user stories, deep-module decomposition, testing decisions, scope. Labeled `ready-for-agent`.
* **Issues 15–21** (`docs/issues/`), dependency-ordered, free-win slices first:
  * `15-tagged-shot-schema.md` — Scripter tags each of 4 shots `real_image`(+entity) / `ai_video`(+prompt); pure `normalize_shots`; legacy back-compat. **No blockers.**
  * `16-kokoro-narration-engine.md` — Kokoro-82M local behind `synthesize(...)`, Edge fallback, `bootstrap --check` for `espeak-ng`. **No blockers.** (Interactive — needs `espeak-ng` install + listen-test.)
  * `17-image-fetch-hybrid-sourcing.md` — `src/image_fetch/` `Source` ABC + Wikimedia/Openverse/logo/web(`ddgs`); cache + license audit + validation. **No blockers.**
  * `18-ken-burns-motion-builder.md` — still → `shot_XX.mp4` (blurred-bg 9:16 + zoompan), pure argv. **Blocked by 17.**
  * `19-hybrid-assembler-routing.md` — kind-aware routing in `_generate_clip` + `xfade` crossfades; only ai_video billed. **Blocked by 15, 17, 18.**
  * `20-hybrid-end-to-end-spike.md` — one real topic → mixed clip → cost reconciliation + HITL sign-off. **Blocked by 15–19.** (Interactive/throwaway.)
  * `21-pivot7-config-retention-docs-cleanup.md` — lower cost ceilings, image-cache TTL, confirm disclosure, update docs. **Blocked by 20.**
* **`plan.md`** — added "Pivot.7" section (P7.1–P7.7) before the out-of-scope block.
* **`progress.md`** — appended Pivot.7 checklist (NOT STARTED).

### Locked design decisions (2026-05-25 `AskUserQuestion` dialogue)
* Image source = **hybrid** (licensed/free first → web fallback).
* Voice = **Kokoro-82M local** (Edge TTS fallback).
* **Kling kept for ~half the shots** (ai_video transitions only) → ~half the per-clip cost.
* **Scripter tags each shot** real_image/ai_video.
* Crossfades **ON** by default (~0.25s), config-toggleable.
* Web fallback **keyless `ddgs`** by default; SerpAPI optional via env.
* **AI disclosure unchanged** — stays on (clip is still part-AI).

## 3. Active Codebase State

* **Database (`data/state.db`):** Pivot.6 schema live — `topics`, `seen_topics`, `scripts`, `generation_jobs`; `clips.content_kind`, `clips.script_id`, nullable `clips.video_id`, `quota_usage.provider`. **Pivot.7 needs NO migration** — `shots_json` already stores arbitrary JSON; the only change is its internal shape (handled by `normalize_shots`).
* **External integrations:** Ollama `qwen2.5:3b-instruct` (local, scripter); OpenRouter Kling 3.0 std (`kwaivgi/kling-v3.0-std`, paid); Edge TTS (current voice); faster-whisper `large-v3` (forced-align); YouTube Data API v3. Pivot.7 adds: Kokoro-82M (local), `image_fetch` sources (Wikimedia/Openverse/`ddgs`).
* **Config (`config.yaml`):** `ai_gen.per_clip_cost_cents_max=350`, `daily_spend_cents_ceiling=500`; `upload_weekdays=[tue,thu]`, `clips_per_day=1`; `narration.voice=en-US-GuyNeural`. Pivot.7 will add `ImageFetchConfig`, `narration.engine`/`kokoro_voice`, `assembler.crossfade_*`, `paths.images_dir`, image-cache retention TTL — and lower the cost ceilings.
* **Known latent bug (fixed by Pivot.7 in passing):** `gen_run._generate_clip` assumes dict-shaped shots (`s['prompt']`) while the Pivot.6 scripter emits bare strings — resolved by `normalize_shots` (Issue 15).

## 4. Operational Health & Run Logs

* **Recent runs (`logs/runs.md`):** daily 2026-05-24 → `uploaded=1` (success). Prior dailies clean.
* **Alerts (`logs/alerts.md`):** last entry 2026-05-24 `publish_at_padded` (clip `1c1e8ae6…` padded to now+20m — benign). 2026-05-21 Kling spike → `USEFUL 8/8`. No failures/quota-cap/CID alerts pending.
* **Slice 10 open gates:** T+1h Studio checks (altered-content toggle UI, public flip at `publishAt`, no Content ID) + T+48h stability gate still pending — independent of Pivot.7.

## 5. Next Immediate Steps (Actionable Todo)

- [ ] **Implement Issue 15** (tagged shot schema) — free, no API; foundation. Start here.
- [ ] **Implement Issue 16** (Kokoro) in parallel — free; requires `espeak-ng` install + operator listen-test.
- [ ] **Implement Issue 17** (`image_fetch`) — free; HTTP-mocked tests.
- [ ] **Implement Issue 18** (Ken Burns) — after 17.
- [ ] **Implement Issue 19** (hybrid assembler + crossfades) — after 15/17/18.
- [ ] **Run Issue 20 spike** — one real topic, eyeball + cost reconciliation + HITL sign-off.
- [ ] **Implement Issue 21** — cost ceilings, retention, docs cleanup.
- [ ] Suggested driver: `/tdd` per ticket (matches the project's red-green workflow), or `/goal` to resume autonomous execution from Issue 15.

## 6. Risks, Blockers & Open Decisions

* **Copyright trade-off (accepted):** real web images partially walk back Pivot.6's "AI eliminates strike risk" win — mitigated by licensed-source-first + per-image license audit; editorial use defensible; images far lower-risk than the sourced *video* Pivot.6 abandoned.
* **`espeak-ng` install** is the one Kokoro friction point on Windows — caught by `bootstrap --check`.
* **Wrong-image risk** ("not the wrong GPU") — v1 relies on scripter `entity` specificity + licensed priority. A CLIP/vision re-rank is a deliberate **v2/out-of-scope** follow-up.
* **Reversible knobs:** crossfade on/off, web-fallback on/off, `narration.engine` — all config flags; tune at the spike without code changes.
* **Open (deferred):** per-shot image provenance in the DB (`generation_jobs` column) — filesystem sidecars for now; additive migration if DB-queryable provenance is later needed.
* **No git repo** in this working copy — pushes still blocked until `git init` + remote.

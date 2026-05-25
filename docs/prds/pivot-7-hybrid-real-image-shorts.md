# PRD — Pivot.7: Hybrid Real-Image + AI-Transition Shorts

> **Status:** ready-for-agent
> **Scope:** Pivot.7. Replaces the all-Kling visual path with a **hybrid clip**: real sourced images for recognizable entities + AI-generated Kling shots as connective/atmosphere transitions. Swaps Edge TTS for local **Kokoro** narration. Upstream context: locked via an `AskUserQuestion` design dialogue on 2026-05-25 (image source = hybrid; voice = Kokoro; Kling kept for ~half the shots; scripter tags each shot). Supersedes the Pivot.6 "4 Kling shots per clip" visual model.

## Problem Statement

The creator watched the Pivot.6 output and rejected it on three counts:

1. **The visuals are AI slop.** Every shot is Kling text-to-video, which produces generic AI imagery — and worse, sometimes a synthetic person "yapping/talking" on screen. For a Tech/AI news channel, viewers expect to see the *actual thing* being discussed.
2. **The recognizable entities are fake.** A video about the RTX 5090 shows an AI-hallucinated graphics card, not the real card. A video mentioning OpenAI shows generic AI imagery, not the OpenAI logo. The things the audience can recognize are exactly the things that must be real — an AI render of a 5090 reads as low-effort and wrong.
3. **The voice sounds robotic.** `en-US-GuyNeural` (Edge TTS) is serviceable but reads as obviously synthetic. The creator wants narration that at least sounds "a bit normal" — human, not text-to-speech.

The creator does NOT want to abandon AI generation entirely. AI shots are useful as connective tissue — abstract b-roll and motion that make cuts flow, so the clip isn't a flat static slideshow. The explicit ask: **"use half of the things as AI to make them transition well, and then the AI cost would drop as well — use a mix hybrid of both."**

So the problem is threefold: (a) real imagery for recognizable entities, (b) AI only for transitions/atmosphere, (c) a more natural voice — while *lowering* the per-clip Kling spend (currently ~$1.34/clip for 4 shots).

## Solution

A hybrid pipeline where each clip mixes two **Shot kinds**:

| Shot kind | Source | Role | Per-shot cost |
|---|---|---|---|
| `real_image` | Hybrid sourcing (licensed/free → web fallback) → Ken Burns motion | The recognizable "money shots": real RTX 5090, real OpenAI logo | $0 |
| `ai_video` | Kling 3.0 std (existing `ai_gen`) | Connective/atmosphere b-roll that makes cuts flow | paid |

The **Scripter** tags each of the 4 shots as `real_image` (carrying a concrete `entity` to source) or `ai_video` (carrying a cinematic Kling `prompt`), aiming for roughly 2 of each, alternating so AI shots sit between real ones and smooth the pacing.

A new **`image_fetch`** module sources real images via a hybrid strategy — licensed/free sources first (Wikimedia Commons, Openverse, a brand-logo source), then a web image search fallback — caching each result and recording its `source` + `license` + `source_url` for an audit trail. A **Ken Burns** builder turns each still into a motion `shot_XX.mp4` (blurred-background 9:16 fill + slow zoom/pan) that is byte-compatible with Kling output at the concat step.

Narration moves to **Kokoro-82M**, a local neural TTS running on the RTX 3070 — free, offline, and markedly more natural than Edge TTS, which is retained as a degraded-mode fallback.

Because only ~half the shots are now Kling, **per-clip Kling cost roughly halves** (~$0.67/clip vs ~$1.34), so the same $5/week budget either yields more clips or leaves headroom. AI disclosure stays ON — half of every clip is still AI-generated, so `containsSyntheticMedia=true` and the "Made with AI" footer are unchanged.

## User Stories

1. As the channel owner, I want recognizable entities (a named GPU, a company logo) rendered from **real sourced images**, so that viewers see the actual RTX 5090 / OpenAI logo, not an AI hallucination.
2. As the channel owner, I want AI-generated Kling shots used only for **abstract transitions and atmosphere**, so that the clip flows like edited video rather than a flat slideshow — while the recognizable content stays real.
3. As the channel owner, I want roughly **half the shots to be AI**, so that my per-clip Kling spend drops (~$0.67 vs ~$1.34) and my weekly budget stretches further.
4. As the channel owner, I want narration from a **local neural voice (Kokoro)** that sounds human, so that the videos don't read as obviously robotic text-to-speech.
5. As the channel owner, I never want a **synthetic person "talking"** on screen, so that the channel doesn't look like AI-avatar spam.
6. As a developer, I want the **Scripter to tag each shot** `real_image` (with an `entity`) or `ai_video` (with a `prompt`), so that the split adapts per topic instead of being hardcoded.
7. As a developer, I want a **pure shot-normalizer** that coerces legacy bare-string shots into `{kind: ai_video, prompt}`, so that existing `scripts` rows and tests keep working and the latent dict-vs-string mismatch in `_generate_clip` is fixed.
8. As the channel owner, I want image sourcing to **prefer licensed/free sources** (Wikimedia Commons, Openverse, brand-logo source) before falling back to web search, so that copyright/trademark exposure is minimized.
9. As the channel owner, I want each sourced image's **source, license, and source URL recorded**, so that there is an audit trail if a takedown or claim ever arises.
10. As the channel owner, I want the web-search fallback to be **keyless and free by default** (DuckDuckGo via `ddgs`), so that no paid API is required — with an optional SerpAPI upgrade if reliability demands it.
11. As a developer, I want fetched images **cached by entity hash**, so that a repeatedly-referenced entity (e.g. the OpenAI logo) is fetched once, not every run.
12. As a developer, I want every sourced image **validated** (decodable, correct content-type, minimum resolution), so that a 404 page or a 32×32 favicon never reaches the assembler.
13. As the channel owner, I want a `real_image` entity to **never be a living person** (only products, logos, objects), so that I avoid likeness/publicity-rights problems — narration may still name people (factual reporting is fine).
14. As a developer, I want each real image turned into a **Ken Burns motion clip** (slow zoom/pan) with a **blurred-background 9:16 fill**, so that stills don't crop badly (logos especially) and don't look static next to the AI shots.
15. As a developer, I want the Ken Burns step to emit a **`shot_XX.mp4` identical in shape to a Kling shot**, so that the assembler's concat step treats both kinds uniformly.
16. As the channel owner, I want short **crossfades between shots** (default ~0.25s), so that cuts between a real image and an AI shot feel intentional and smooth.
17. As a developer, I want crossfades to be **config-toggleable**, so that if they look worse than hard cuts I can disable them without a code change.
18. As a developer, I want a **Kokoro narration engine** behind the existing `synthesize(...)` contract, so that swapping the voice doesn't ripple into the aligner, subtitles, or assembler.
19. As a developer, I want **Edge TTS retained as an automatic fallback** when Kokoro fails or is unavailable, so that a bad Kokoro install never blocks a run.
20. As a developer, I want `bootstrap --check` to verify **Kokoro + its `espeak-ng` dependency** are present, so that the one install-friction point is caught before a run, not mid-pipeline.
21. As the channel owner, I want **AI disclosure to stay on** (`containsSyntheticMedia=true`, "Made with AI" footer), so that the channel stays compliant even though only half the clip is AI now.
22. As the channel owner, I want `per_clip_cost_cents_max` **lowered** to reflect ~2 Kling shots per clip, so that the cost guardrail meaningfully bounds a runaway run.
23. As a developer, I want the scripter to still produce exactly **4 shots** with the existing narration rubric (hook in first 5 words, ~40 words, ends on a teaser), so that the only script-level change is per-shot tagging.
24. As a developer, I want an **end-to-end hybrid spike** on one real RSS topic before steady-state, so that I can eyeball the mixed visual quality and reconcile the halved cost against the OpenRouter dashboard.
25. As a developer running on a Windows laptop with an RTX 3070, I want Kokoro and Ken Burns to fit the **8 GB VRAM** envelope alongside Whisper alignment, so that the machine doesn't OOM during a run.
26. As a developer, I want image-cache files governed by a **retention TTL**, so that `data/images/` doesn't grow unbounded.
27. As the channel owner, I want the docs (`CLAUDE.md`, `agents.md`, `skills.md`, `CONTEXT/`) updated to describe the **hybrid model**, so that a fresh agent doesn't rebuild against the stale "4 Kling shots" assumption.
28. As a developer, I want the new modules covered by **fast, hermetic tests** (mocked HTTP, mocked engines, argv-shape assertions), so that the suite stays green and offline like the rest of the project.

## Implementation Decisions

### Decision summary (locked in the 2026-05-25 design dialogue)

- **Image source = hybrid.** Licensed/free sources first; web search only as a fallback.
- **Voice = Kokoro-82M local**, Edge TTS as fallback.
- **Kling kept for ~half the shots** — the `ai_video` transition/atmosphere shots only.
- **Scripter tags each shot** `real_image` (+`entity`) or `ai_video` (+`prompt`).
- **Crossfades ON by default** (~0.25s), config-toggleable. Reversible — if hard cuts look better, flip the config.
- **Web fallback is keyless (`ddgs`) by default**; SerpAPI is an optional env-keyed upgrade, not required.
- **AI disclosure unchanged** — stays on; the clip is still part-AI.

### Modules

This is a deep-module decomposition: each new module hides its complexity behind a small interface that rarely changes, and is testable in isolation.

**Modified — Scripter (tagged shot schema).**
The Stage-B generator prompt is rewritten so the model emits **structured shots** instead of bare strings. Each shot is one of:
- `{ "kind": "real_image", "entity": "<concrete thing to source>", "search_query": "<optional refinement>", "duration_s": 4 }`
- `{ "kind": "ai_video", "prompt": "<cinematic Kling prompt>", "duration_s": 4 }`

Guidance baked into the prompt: 4 shots total, aim for ~2 `real_image` + ~2 `ai_video`, roughly alternating; `real_image` entities are products/logos/objects only (never a living person); `ai_video` shots are abstract/atmospheric/transitional. A new **pure** seam `normalize_shots(raw_shots) -> list[dict]` coerces and validates: a bare string becomes `{kind: "ai_video", prompt: <string>}` (legacy back-compat), a dict missing required keys raises, and unknown `kind` raises. `validate_script(script, cfg)` is extended to validate the new shape (still requires exactly 4 shots; narration word-count rule unchanged). `scripts.shots_json` continues to store the shots as JSON — now structured dicts; old rows decode and pass through `normalize_shots`.

**New — `image_fetch` (hybrid image sourcing).**
Mirrors the existing `ai_gen.base.Provider` ABC pattern. A `Source` ABC defines `search(entity, query) -> list[ImageCandidate]`. Concrete sources, tried in priority order:
1. `LogoSource` — brand/company logos (for logo-type entities).
2. `WikimediaSource` — Wikimedia Commons API (CC-licensed).
3. `OpenverseSource` — Openverse API (CC-licensed aggregator).
4. `WebSearchSource` — keyless DuckDuckGo image search via `ddgs` (fallback); optionally SerpAPI when `SERPAPI_KEY` is set.

Public seam: `fetch_image(entity, query, cfg, *, cache_dir) -> ImageAsset`, where `ImageAsset = {path, source, license, source_url, width, height}`. Behavior: check cache (`sha256(entity|query)`) → on miss, walk sources in priority order, take the first candidate that passes validation (content-type is an image, decodable via Pillow, ≥ configured min resolution) → download to cache → return the asset. The `source`/`license`/`source_url` are persisted to a sidecar JSON next to the cached image for the audit trail. All HTTP lives inside the `Source` classes so tests mock the network and assert priority/fallback/cache/validation/audit behavior without real requests.

**New — Ken Burns motion builder (`image_fetch.ken_burns` or `assembler.ken_burns`).**
Pure argv builder, same philosophy as `assembler.build.build_assembler_argv` (no ffmpeg invoked inside). Public seam: `build_ken_burns_argv(image_path, dest, *, duration_s, resolution, zoom_rate, blurred_bg_sigma, fps) -> list[str]`. Produces a `shot_XX.mp4` from a still: a blurred, cover-fit background copy of the image + the contained image centered on top (reusing the proven blurred-bg filtergraph idiom from the legacy `editor/` Pivot.3 work) + a slow `zoompan` push for motion. Output matches Kling shot geometry/fps so the downstream concat is kind-agnostic.

**New/Modified — Narration (Kokoro engine + fallback).**
The existing `synthesize(text, dest, *, voice, rate, pitch) -> Path` contract is preserved. A `KokoroEngine` is added (Kokoro-82M on CUDA, voice selectable, e.g. `am_michael` / `bm_george`), and an engine selector dispatches on `narration.engine ∈ {kokoro, edge}`. On Kokoro failure (import error, model load, runtime), it falls back to the Edge path and logs a degraded-mode warning. Whisper forced-alignment (`narration.aligner.align`) is unchanged — Kokoro audio is clean speech and aligns fine. `bootstrap --check` gains a Kokoro-importable + `espeak-ng`-present check.

**Modified — Assembler + `gen_run` (kind-aware routing + crossfade).**
`gen_run._generate_clip` becomes kind-aware: for each normalized shot, `ai_video` → existing `ai_gen.generate_shots` (Kling); `real_image` → `image_fetch.fetch_image` then `ken_burns` → a `shot_XX.mp4`. Both kinds yield ordered `shot_XX.mp4` paths fed to the existing concat path. `build_assembler_argv` gains an optional **crossfade** path: when `assembler.crossfade_enabled`, shots are joined with `xfade` (duration `assembler.crossfade_duration_s`, default 0.25) via a `filter_complex` chain instead of the concat demuxer; when disabled, the current concat-demuxer hard-cut path is used unchanged. The crossfade builder stays a pure argv function for testability.

**Modified — Config / schema / paths / retention / bootstrap.**
- New `ImageFetchConfig` sub-model: source priority list, min resolution, max candidates per source, cache dir, web-fallback toggle, optional SerpAPI key reference.
- `NarrationConfig` gains `engine: Literal["kokoro","edge"] = "kokoro"` and `kokoro_voice`. Existing `voice`/`rate`/`pitch` retained for the Edge fallback.
- `AiGenConfig`: shot-count expectations relaxed (a clip may contain 1–3 `ai_video` shots; the rest are `real_image`). `per_clip_cost_cents_max` lowered to reflect ~2 Kling shots.
- New `assembler`/render keys: `crossfade_enabled` (default true), `crossfade_duration_s` (default 0.25).
- `Paths` gains `images_dir` (default `data/images`).
- `Retention` gains an image-cache TTL.
- No SQLite schema migration is required: `shots_json` already stores arbitrary JSON; the only change is the JSON's internal shape, handled by `normalize_shots`. (If a per-shot audit of image provenance in the DB is later desired, a `generation_jobs.kind`/`image_source` column is a future additive migration — out of scope here.)

### Compliance contract (unchanged from Pivot.6, restated)

- `compliance.ai_disclosure` stays `true`. Every `content_kind='ai_generated'` clip still sets `status.containsSyntheticMedia=true` and the "Made with AI." footer. Rationale: half of each clip is Kling-generated, and the Ken Burns motion is itself synthesized — the clip is unambiguously part-AI.
- The CONTEXT.md **no-living-individuals** rule is extended: it already forbids naming a real person in an `ai_video` (Kling) prompt; Pivot.7 adds that a `real_image` `entity` must be a product/logo/object, never a living person — to avoid sourcing a real photo of an identifiable individual.

## Testing Decisions

A good test here verifies **external observable behavior through public seams**, never internal call order or prompt byte-contents — consistent with the existing suite (e.g. `tests/ai_gen/test_openrouter_kling.py` asserts the HTTP body shape, not that `submit` calls `_post_with_retry`). Network, the clock, and ML models are mocked so tests stay fast, local, and GPU-free.

### Modules to be tested

- **Scripter `normalize_shots` + `validate_script`** — pure functions. Cover: bare-string → `ai_video` coercion; valid tagged `real_image`/`ai_video` dicts pass; missing required key raises; unknown `kind` raises; wrong shot count rejected; narration word-count rule still enforced. Prior art: `tests/` scripter/runner tests.
- **`image_fetch` sources + `fetch_image`** — HTTP fully mocked. Cover: source priority order (licensed before web), fallback when a higher-priority source misses, cache hit avoids any HTTP, license/source/source_url recorded to sidecar, validation rejects non-image content-type / undersized / undecodable, web-fallback used only when licensed sources miss. Prior art: HTTP-mocked pattern from `tests/ai_gen/test_openrouter_kling.py` and the Ollama-mocked policy tests.
- **Ken Burns argv builder** — pure argv-shape assertions: blurred-bg + zoompan + correct resolution/fps/duration present; output path correct. Prior art: `tests/test_editor_ffmpeg.py`, assembler argv tests.
- **Narration engine selection + fallback** — engines mocked. Cover: `engine=kokoro` calls Kokoro; Kokoro failure falls back to Edge and logs degraded mode; `engine=edge` calls Edge directly. The real audio synthesis is an integration smoke, not a unit assertion.
- **Assembler crossfade argv** — pure argv-shape assertions: crossfade-enabled path emits `xfade` with the configured duration; crossfade-disabled path is byte-identical to the current concat-demuxer argv (regression).
- **Config** — Pydantic validation of the new sub-models/keys, following the existing config-loader tests (valid loads; invalid `narration.engine` rejected; defaults applied).

### Not tested

- The **end-to-end hybrid spike runner** — a throwaway operator script (like `scripts/spike_kling.py` before it). Manual run + eyeball + cost reconciliation is its validation. Adding unit tests to throwaway code is the over-engineering the project guidelines caution against.
- Real Kokoro audio quality and real web-image relevance — judged by the operator at the spike, not asserted in code.

## Out of Scope

- **Vision-based image verification** (CLIP/zero-shot "is this actually a 5090?") — v1 relies on the scripter's specific `entity` string + licensed-source priority. A vision re-rank is a strong v2 follow-up but is its own PRD.
- **Replacing Kling with another provider** — the `ai_video` half still uses the existing `OpenRouterKlingClient`. Pika/MiniMax/Seedance swaps remain the Provider-ABC drop-in path, untouched here.
- **A DB migration for per-shot image provenance** — provenance is recorded to filesystem sidecars in v1. A `generation_jobs` column is a future additive migration if DB-queryable provenance is needed.
- **SerpAPI as the default** — keyless `ddgs` is the default web fallback. SerpAPI is an optional env-keyed upgrade only.
- **TikTok/Instagram, web dashboard, thumbnail generation, subject-aware crop** — still out of scope (carried from Pivot.6).
- **Tuning shot duration or shot count away from 4** — locked; 4 shots, ~4s each.
- **Animated/video logos or motion-graphics templates** — real images are stills with Ken Burns motion only.

## Further Notes

- **Cost framing.** Pivot.6 = 4 Kling shots ≈ $1.34/clip. Pivot.7 ≈ 2 Kling shots ≈ $0.67/clip; image sourcing and Kokoro are $0. The $5/week budget therefore covers ~2× the clips, or the same cadence with comfortable headroom. `per_clip_cost_cents_max` and `daily_spend_cents_ceiling` should be re-tightened around the new ~$0.67 baseline at the cleanup slice.
- **The copyright trade-off is deliberate and acknowledged.** Pivot.6's headline win was "AI-generated content eliminates copyright-strike risk." Sourcing real images partially walks that back — but only for the image half, mitigated by licensed-source-first priority and a per-image license audit trail, and editorial/news commentary is a defensible use. Images also carry far lower strike risk than sourced *video* did (the original Pivot.6 driver). This was surfaced to and accepted by the owner during the design dialogue.
- **Reversible knobs.** Crossfade on/off, web-fallback on/off, and `narration.engine` are all config flags — the visual/audio direction can be re-tuned at the spike without code changes.
- **`espeak-ng` is the one install-friction point** for Kokoro on Windows; everything else is `pip`. Caught by `bootstrap --check`.
- **Latent bug fixed in passing:** `gen_run._generate_clip` already assumes dict-shaped shots (`s['prompt']`) while the Pivot.6 scripter emits bare strings — `normalize_shots` resolves this mismatch as a side effect of the schema change.
- This PRD decomposes into issues **15–21** (`docs/issues/`), dependency-ordered, free-win slices first (tagged schema + Kokoro), then the image path, then the hybrid assembler, then an end-to-end spike, then cleanup.

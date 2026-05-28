# PRD — AI-Centric Niche, Trending Topic Selection, and Photo Framing Fix

> **Status:** ready-for-agent
> **Scope:** Fix the two defects the operator hit on the pending clip `spike-82` — (1) an off-niche adult-content **Topic** (a Verge culture story about Apple TV's OnlyFans-themed shows) became a finished, slot-scheduled **Clip**; (2) the real photo in it was vertically stretched. Narrows the niche, gates relevance at ingest, reranks selection on **Significance** + Hacker News **Trending corroboration**, curates feeds, and fixes the Ken Burns framing. Locked in a `/grill-with-docs` design dialogue on 2026-05-27. Authoritative decision record: `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`. Glossary: `CONTEXT/CONTEXT.md` (**Topic**, **Significance**, **Trending corroboration**).

## Problem Statement

The operator opened the pending clip and rejected it on two counts:

1. **It was about the wrong thing.** The clip discussed OnlyFans-themed TV shows — adult-adjacent culture content, not Tech/AI news. Tracing it back: it came from **Topic** #82, a real Verge RSS item (*"'It's in the air': Apple TV's hottest new shows explore different sides of OnlyFans"*) that was ingested, scored **6.9** (novelty 9.0, tension 7.0), and turned into a **Clip**. The operator's words: *"talk about tech not these weird things like onlyfans... find actually trending content like opus 4.7 or new ai models or new features in ios update."*
2. **The photo was stretched.** The real image in the clip was visibly distorted (squashed/stretched to fill the frame) rather than framed cleanly. The operator wants it *"appealing like other shorts like MKBHD."*

Three design gaps produced defect (1), and one bug produced defect (2):

- **No relevance gate.** `policy_gate/topic_filter.py` only classifies religion / war and returns `"allowed"` for everything else — a culture story sails through.
- **The scorer rewards the wrong axis.** Topic ranking is `0.4·novelty + 0.3·specificity + 0.3·tension` (`src/scripter/runner.py`). "Edgy and weird" is literally what it optimizes; there is no on-niche signal and no measure of whether a story is genuinely *trending*.
- **Mixed feeds.** The Verge *main* feed and VentureBeat produce mostly culture/think-piece noise; Anthropic — the source for the operator's own "Opus 4.7" example — is absent.
- **Ken Burns stretch bug.** `assembler/ken_burns.py` scales the foreground photo aspect-correctly (`force_original_aspect_ratio=decrease`) and then pipes it into `zoompan` with `s=1080x1920` — and `zoompan` ignores aspect ratio, re-stretching the fitted photo to fill the frame (a wide 16:9 photo is squashed ~3× vertically).

## Solution

**Narrow the niche, gate it hard at ingest, rerank on significance + live trending, curate the feeds, and fix the photo framing.**

- **On-niche is sharpened and testable.** A **Topic** is on-niche only if its center of gravity is AI — a model/research release, or AI shipping inside a product (Apple Intelligence, Copilot) — **or** it is a major flagship hardware/OS launch (new iPhone, a major iOS version, a flagship GPU). Culture, entertainment, lawsuits/drama, and minor/incremental tech are off-niche. (ADR-0004; `CONTEXT.md` → **Topic**.)
- **Hard relevance gate at ingest.** An LLM on/off-niche binary verdict runs during `topic_ingest`, *before* the row is written to `topics`. Off-niche items are discarded (never persisted) so a "significant" culture story cannot leak through scoring; each rejection emits one `logs/agent.log` debug line for tuning.
- **Significance + Trending corroboration replace novelty/tension.** Survivors are ranked by **Significance** (magnitude of the launch × authority of the source) plus a free **Hacker News front-page** check (no API key); a **Topic** also trending on HN is boosted. The novelty/tension formula is removed.
- **Feeds curated to AI-focused sources.** Add Anthropic + Google AI blogs; swap The Verge / Ars main feeds for their AI subfeeds; keep OpenAI / DeepMind / Hugging Face; drop VentureBeat.
- **Photo framing fixed.** The Ken Burns builder stops distorting: the photo is rendered at its true aspect ratio with a slow zoom, over a **per-photo dominant-color gradient** background (replacing the blurred-bg fill). The derived color is **clamped to a dark, desaturated range** so white subtitles always have contrast.

AI disclosure, the `ai_generated` **Content kind**, the scripter output schema, the assembler concat path, and the upload/two-gate flow are all unchanged.

## User Stories

1. As the channel owner, I want adult/culture stories (OnlyFans-themed TV, celebrity drama) to **never become a Clip**, so that the channel stays on its Tech/AI niche.
2. As the channel owner, I want topics whose center of gravity is **AI** (new models, AI features in products) to be eligible, so that I cover the content I actually care about.
3. As the channel owner, I want **major flagship hardware/OS launches** (new iPhone, a major iOS version, a flagship GPU) eligible too, so that my "new iOS features" examples are covered.
4. As the channel owner, I want **minor/incremental tech and lawsuits/industry drama** excluded, so that the channel doesn't drift into low-signal filler.
5. As the channel owner, I want the agent to favor **actually trending** stories (e.g. an Opus 4.7 launch), so that the channel rides current attention instead of obscure items.
6. As a developer, I want an **on/off-niche LLM verdict at ingest** that drops off-niche topics *before* they hit the `topics` table, so that no downstream stage can resurrect a culture story.
7. As a developer, I want each off-niche rejection to emit **one debug log line with a reason**, so that I can audit false rejections without polluting the `topics` table.
8. As a developer, I want topic ranking driven by **Significance** (launch magnitude × source authority) instead of novelty/tension, so that "big launch from a major player" wins, not "weird and edgy."
9. As a developer, I want a **free Hacker News front-page corroboration** signal that boosts topics also trending on HN, so that "trending" is measured, not guessed — with no API key or cost.
10. As a developer, I want the HN fetch to **degrade gracefully** (HN down → selection proceeds on Significance alone), so that an external outage never blocks a run.
11. As the channel owner, I want **Anthropic and Google AI blogs added** to the feeds, so that primary-source model launches (my Opus 4.7 example) are ingested.
12. As the channel owner, I want **The Verge and Ars main feeds swapped for their AI subfeeds** and **VentureBeat dropped**, so that the input carries less culture/think-piece noise.
13. As a developer, I want the feed list to remain **config-only** (no code change to add/remove a feed), so that sourcing stays tunable.
14. As the channel owner, I want real photos rendered at their **true aspect ratio** (never stretched/squashed), so that products and logos look correct.
15. As the channel owner, I want a photo framed over a **clean background derived from its own dominant color** (a muted gradient), so that the look is cohesive and premium, like MKBHD-style shorts.
16. As the channel owner, I want a **slow Ken Burns zoom** retained on the photo, so that real-image shots aren't flatly static next to the AI-video shots.
17. As a developer, I want the derived background color **clamped to a dark, desaturated range**, so that white centered subtitles at `\pos(540,1500)` always have contrast regardless of the source image.
18. As a developer, I want the Ken Burns builder to remain a **pure argv function** emitting a `shot_XX.mp4` of the same geometry/fps as before, so that the downstream concat path stays kind-agnostic and the change is unit-testable.
19. As the operator, I want the bad pending clip (`spike-82`) **marked rejected** so it can never publish, so that the OnlyFans clip doesn't reach the channel.
20. As a developer, I want `CLAUDE.md` and `plan.md` **reconciled** to the narrowed niche, so that a fresh agent doesn't rebuild against the stale broad "Tech/AI news" framing.
21. As a developer, I want the niche gate, HN corroboration, and significance scoring to reuse the **existing local Ollama model and keyless HTTP**, so that no new paid dependency is added.
22. As a developer, when on-niche topics run low I want the **recency window to widen (48h → 96h)** rather than the gate relaxing, so that a quiet news week never causes off-niche filler.
23. As a developer, I want all new seams covered by **fast, hermetic tests** (mocked Ollama/HTTP, pure-function and argv-shape assertions), so that the suite stays green and offline.

## Implementation Decisions

### Decision summary (locked 2026-05-27, ADR-0004)

- **Niche = AI-centric + flagship launches.** Culture / drama / minor tech are off-niche.
- **Hard relevance gate at ingest**, reject-before-persist, with a debug log breadcrumb.
- **Significance × source authority + HN corroboration** replaces novelty/specificity/tension.
- **Feeds curated** (add Anthropic + Google AI; Verge/Ars → AI subfeeds; drop VentureBeat).
- **Photo framing:** true-aspect photo + slow zoom over a per-photo dominant-color gradient, dark-clamped for subtitle contrast. **Stretch bug fixed.**
- **No SQLite migration.** No schema change is required.

### Modules

This is a deep-module decomposition — each new seam hides its complexity behind a small interface and is testable in isolation (mocked LLM/HTTP or pure).

**New — Niche gate (`topic_ingest`).**
A seam `classify_niche(title, summary, cfg) -> NicheVerdict` backed by the local Ollama model, returning an on-niche/off-niche binary + a short reason. It runs inside `topic_ingest` *before* the candidate is written to `topics`: off-niche → discarded, with a single `logs/agent.log` debug line (`niche_gate: off_niche — <reason> — <title>`). Modeled on the existing `policy_gate/topic_filter.py` Ollama pattern (same retry/empty-input handling). The niche definition (the on-niche rule from `CONTEXT.md`) lives in the prompt. All LLM calls are mockable so tests assert on/off verdicts without a live model.

**New — Hacker News trending corroboration (`topic_ingest`).**
Two seams: `fetch_hn_front_page(cfg) -> list[HnItem]` (keyless HTTP against the public HN front-page/top-stories endpoint; failures return empty and log a warning) and a **pure** `hn_corroboration(topic, hn_items) -> float` that scores how strongly a topic's subject matches a current HN front-page story (title/entity overlap). HTTP lives entirely inside the fetch seam so tests mock it; the match is pure and tested directly.

**Modified — Significance scorer (`scripter/runner.py`).**
`score_topics` drops `0.4·novelty + 0.3·specificity + 0.3·tension`. The scorer prompt is rewritten to emit a **Significance** judgment (how major the launch, how authoritative the player); the weighting becomes `significance × source_authority_weight + hn_corroboration_boost`. `source_authority_weight` is a config map keyed by `source_feed` (primary lab/vendor blogs weighted above aggregators). The scored/ranked-selection plumbing (`run_stage_a`, the quality floor, `update_topic_score`) is otherwise unchanged. Pure weighting given the scorer's raw output, so it is unit-tested directly.

**Modified — Ken Burns builder (`assembler/ken_burns.py`).**
The foreground photo is scaled aspect-correct and the **`zoompan s=` distortion is removed** (zoompan no longer forces a fitted photo to `WxH`). The blurred-bg layer is replaced by a **per-photo dominant-color gradient**: two new pure helpers — `dominant_color(image_path) -> rgb` (sampled via Pillow) and `clamp_dark_for_subtitles(rgb) -> rgb` (force into a dark, desaturated band) — feed the gradient. Output stays a `shot_XX.mp4` of the same resolution/fps/duration as today, so the concat path is untouched. Remains a pure argv builder (no ffmpeg invoked inside) per the existing assembler idiom.

**Modified — Config.**
- `topic_ingest.feeds` replaced with the curated list (Anthropic, Google AI, OpenAI, DeepMind, Hugging Face, Verge-AI subfeed, Ars-AI subfeed; VentureBeat removed).
- New `topic_ingest.niche_gate` (enable toggle, Ollama model reference reusing the existing one).
- New `topic_ingest.hn` (enable toggle, endpoint, corroboration weight) and a `topic_ingest.recency_hours` low-yield widen (48 → 96) behavior.
- New `scripter` significance keys: `source_authority` map, `hn_boost` weight.
- New `assembler`/ken_burns keys for the gradient (dark-clamp bounds, gradient style); the blurred-bg sigma key is retired.
- The stale `docs/rss_feeds.md` table is updated to the curated list.

**Cleanup + docs (no schema change).**
- The pending clip `spike-82` is marked rejected (DB status + moved out of `output/pending/`) so it can never publish. (Human-review is on, so it cannot auto-publish today; this is belt-and-suspenders.)
- `CLAUDE.md` "Locked decisions → Niche" and `plan.md` direction summary are reconciled to "AI-centric + flagship launches," pointing at ADR-0004.

### No schema change

`topics`, `scripts`, and `generation_jobs` are untouched. The niche gate rejects pre-persist; significance reuses the existing `topic_score_json` / `weighted_score` columns; the photo fix is render-only.

## Testing Decisions

A good test verifies **external observable behavior through public seams** — never internal call order or prompt byte-contents — consistent with the existing suite (e.g. `tests/ai_gen/test_openrouter_kling.py` asserts the HTTP body shape; the Ollama-backed policy tests mock the model). Network, the clock, and the LLM are mocked so tests stay fast, local, and GPU-free.

### Modules to be tested (operator-selected: the three core fixes)

- **Niche gate + HN corroboration** (`topic_ingest`). Mocked Ollama: `"Apple TV OnlyFans shows" → off_niche` (regression on the exact failure), `"Claude Opus 4.7" → on_niche`, `"iOS 19 adds Apple Intelligence" → on_niche`, empty/garbage input handled. Mocked HTTP: HN fetch parses the front page; fetch failure returns empty and selection still proceeds. Pure `hn_corroboration`: a topic matching a front-page story scores higher than one that doesn't. Prior art: the Ollama-mocked policy tests and the HTTP-mocked `test_openrouter_kling.py`.
- **Significance scoring** (`scripter`). Pure weighting: a major-lab launch outranks an incremental item; an HN-corroborated topic is boosted above an identical non-corroborated one; `source_authority_weight` lifts primary-source feeds above aggregators; the old novelty/tension axes are gone. Prior art: existing scripter/runner scoring tests.
- **Ken Burns stretch fix** (`assembler`). Pure helpers: `dominant_color` returns a plausible RGB for a synthetic test image; `clamp_dark_for_subtitles` always returns a color within the dark/desaturated band (incl. a bright-input case). Argv-shape regression: a wide (16:9) input no longer yields a `zoompan s=WxH` that distorts it (assert the aspect-preserving structure), the gradient layer is present, and resolution/fps/duration are unchanged. Prior art: assembler/editor argv-shape tests.

### Not tested

- **Config validation** (operator excluded it) — follows the existing config-loader tests if added later.
- **Real LLM niche judgments and real HN relevance** — judged by the operator on the next live run, not asserted in code.
- **Subjective "does the gradient look good"** — an eyeball call at review, not a unit test.

## Out of Scope

- **External trending source as the *primary* ingest** (pulling topics directly from HN/Reddit). HN is corroboration only; making it the primary source is a larger `topic_ingest` rewrite, deferred (ADR-0004 alternative 3).
- **Vision-based image verification** ("is this really a 5090?") — carried over from the Pivot.7 PRD; still its own future PRD.
- **Changing the scripter output schema, the assembler concat path, narration, AI disclosure, or the upload / two-gate flow** — all unchanged.
- **A DB migration** — none required.
- **TikTok/Instagram, web dashboard, thumbnail generation, subject-aware crop** — still out of scope (carried from Pivot.6/7).
- **Tuning shot count/duration away from 4 × ~4s** — locked.
- **Full-bleed crop or blurred-bg framing alternatives** — the operator chose the dominant-color gradient; the others were considered and rejected in the grill.

## Further Notes

- **Why reject-at-ingest over score-only:** the OnlyFans story scored 6.9 on the old axes — a "significant" culture story can score high, so a score floor alone cannot guarantee exclusion. A hard binary gate makes the failure structurally impossible. (ADR-0004.)
- **Topic-volume trade-off (known):** narrowing the niche + a hard gate yields fewer candidate topics. The 48h→96h recency widen on low yield is the mitigation — never relax the gate to hit a clip count. Worth watching after the first curated run.
- **No new cost or dependency:** the niche gate and significance reuse the existing local Ollama model; HN is keyless and free. Nothing here changes the Kling/OpenRouter spend.
- **Reversible knobs:** `niche_gate` enable, `hn` enable/weight, `source_authority` map, and the gradient style are all config flags — selection and framing can be re-tuned without code changes.
- **This PRD decomposes into issues (`docs/issues/`)**, dependency-ordered: feeds + config first (free win), then the niche gate, HN corroboration, significance rerank, the Ken Burns fix, then cleanup + doc reconciliation.

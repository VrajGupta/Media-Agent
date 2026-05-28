# ADR-0004 — AI-centric niche, ingest relevance gate, and significance/HN topic selection

**Status:** Accepted
**Date:** 2026-05-27
**Context:** Surfaced while grilling a live failure — the pending clip `spike-82`
(topic #82, a Verge culture story about Apple TV's OnlyFans-themed shows) shipped
off-niche with a vertically stretched photo. Grill session
`.sessions/2026-05-27__ai-niche-and-photo-framing/handoff.md`.

## Context

Pivot.6 fixed the niche as "Tech/AI news" and sourced **Topics** from a mixed
consumer + research RSS list (`topic_ingest.feeds`). Two design gaps let an
adult-content culture story become a finished, slot-scheduled **Clip**:

1. **No relevance gate.** `policy_gate/topic_filter.py` classifies only
   religion / war and returns `"allowed"` for everything else. A culture/entertainment
   item on a tech feed passes untouched.
2. **The topic scorer rewards the wrong axis.** `src/scripter/runner.py` ranks
   **Topics** by `0.4·novelty + 0.3·specificity + 0.3·tension`. The OnlyFans story
   scored **novelty 9.0, tension 7.0 → 6.9 weighted** — "edgy and weird" is exactly
   what the formula optimizes for. There is no on-niche signal and no measure of
   whether a story is actually *trending*.

Compounding it, the source list mixes streams: The Verge's *main* feed and
VentureBeat produce mostly culture posts and think-pieces, and the list omits
Anthropic entirely (the source for the operator's own "Opus 4.7" example).

## Decision

**Narrow the niche, gate it hard at ingest, and select on significance + live
trending corroboration.**

1. **On-niche is sharpened and made testable.** A **Topic** is on-niche only if its
   center of gravity is AI — a model/research release, or AI shipping inside a product
   (Apple Intelligence, Copilot) — **or** it is a major flagship hardware/OS launch
   (new iPhone, a major iOS version, a flagship GPU). Culture, entertainment, lawsuits
   and industry drama, and minor/incremental tech are **off-niche**. (Glossary:
   `CONTEXT/CONTEXT.md` → **Topic**.)

2. **Hard relevance gate at ingest.** An LLM on-niche/off-niche binary verdict runs
   during `topic_ingest`, *before* the row is written to `topics`. Off-niche items are
   discarded and never persisted, so a "significant" culture story (the exact failure)
   cannot leak through scoring. Each rejection emits one `logs/agent.log` debug line
   with the reason, preserving a tuning breadcrumb without polluting the table.

3. **Significance replaces novelty/tension.** Survivors are ranked by **Significance**
   (magnitude of the launch × authority of the source) plus **Trending corroboration** —
   a free Hacker News front-page check (no API key); a **Topic** also trending on HN is
   boosted. The retired novelty/tension formula is removed. (Glossary: **Significance**,
   **Trending corroboration**.)

4. **Feeds curated to AI-focused sources.** Add Anthropic + Google AI blogs; swap
   The Verge / Ars main feeds for their AI-specific subfeeds; keep OpenAI / DeepMind /
   Hugging Face; drop VentureBeat. Less noise at the source — the ingest gate becomes a
   backstop, not the front line.

## Consequences

**Positive:**
- The unattended agent cannot script an off-niche **Topic**; the OnlyFans-class failure
  is structurally impossible, not merely improbable.
- Selection optimizes for "big launch from a major player, trending now" — directly the
  Opus 4.7 / new-model / iOS-feature content the operator asked for.
- "Trending" is grounded in measured signal (HN), not the LLM's unaided guess.

**Negative:**
- Fewer candidate **Topics** per run. The narrowed niche + hard gate can starve the
  pipeline in a quiet news week.
- One extra LLM call per ingested item (the on-niche verdict).

**Mitigations:**
- When on-niche **Topics** run low, widen the recency window (48h → 96h) rather than
  relaxing the gate — never reach for off-niche filler to hit a clip count.
- The gate verdict and significance score can reuse the existing local Ollama model;
  no new paid dependency.

## Alternatives considered

1. **Score-only, no hard gate** (high significance floor). Rejected: a culture/drama
   story can score "significant" and slip through — the precise failure observed.
2. **Hard gate at the selection stage** (ingest everything, mark off-niche in `topics`).
   Offers a full audit trail but keeps junk in the table and spends scoring work on it.
   Rejected in favor of reject-at-ingest for a clean store; the debug log line covers
   tuning.
3. **External trending source as the primary ingest** (pull from HN / Reddit directly,
   RSS secondary). Strongest trending guarantee but the largest rewrite of
   `topic_ingest`. Deferred; HN is used as corroboration, not the primary source.

## Scope

Changes topic sourcing, ingest, and selection only. Does not change the scripter's
output schema, the assembler, AI disclosure, the upload path, or the two-gate
sign-off (ADR-0001). Does not change the `ai_generated` **Content kind** — the niche
narrows *what* is covered, not *how* a **Clip** is made. The photo-framing /
Ken Burns stretch fix decided in the same session is a bug fix + aesthetic tweak and is
tracked in the PRD/issues, not here.

## References

- `CONTEXT/CONTEXT.md` — **Topic**, **Significance**, **Trending corroboration**.
- `docs/adr/0003` — licensed-only image sourcing (the other autonomous-path guardrail).
- `src/topic_ingest/`, `src/scripter/runner.py`, `src/policy_gate/topic_filter.py`,
  `config.yaml` (`topic_ingest.feeds`).

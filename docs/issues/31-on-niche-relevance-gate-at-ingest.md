# Ticket 31 — On-niche relevance gate at ingest

**Status:** ready-for-agent
**Type:** AFK
**Slice:** AI-niche refit / 2
**User Stories:** 1, 2, 3, 4, 6, 7, 22 (PRD `ai-niche-trending-selection-and-photo-framing.md`)

## Parent

PRD: `docs/prds/ai-niche-trending-selection-and-photo-framing.md`
Decision record: `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`

## What to build

A hard relevance gate that drops off-niche **Topics** *before* they are persisted, so no downstream stage can resurrect a culture/drama story (the OnlyFans failure).

End-to-end behavior:

1. **Niche-gate seam.** `classify_niche(title, summary, cfg) -> NicheVerdict` (on-niche/off-niche binary + short reason), backed by the local Ollama model — mirror the existing `policy_gate/topic_filter.py` pattern (same retry + empty-input handling). The **on-niche rule lives in the prompt**, taken verbatim from `CONTEXT.md` → **Topic**:
   - On-niche = center of gravity is AI (a model/research release, or AI shipping inside a product like Apple Intelligence/Copilot) **or** a major flagship hardware/OS launch (new iPhone, a major iOS version, a flagship GPU).
   - Off-niche = culture, entertainment, lawsuits/industry drama, minor/incremental tech.
2. **Reject before persist.** The gate runs inside `topic_ingest` ahead of the `topics` insert. Off-niche items are **discarded (never written)** and emit exactly one `logs/agent.log` debug line: `niche_gate: off_niche — <reason> — <title>`.
3. **Low-yield widen.** When on-niche topics fall below the run's need, widen the recency window (48h → 96h) rather than relaxing the gate — never admit off-niche filler to hit a clip count.
4. **Reuse, no new dependency.** Reuse the existing local Ollama model; no paid API, no new key.

No DB schema change (rejection happens pre-persist; the gate adds no column).

## Acceptance criteria

- [ ] `classify_niche` returns an on/off-niche verdict + reason via Ollama, with the `CONTEXT.md` rule in the prompt; transient HTTP errors retry; empty/garbage input is handled.
- [ ] Off-niche topics are never written to `topics`; on-niche topics are persisted as today.
- [ ] Each off-niche rejection emits exactly one debug log line with a reason.
- [ ] Low on-niche yield widens the recency window (48h → 96h); the gate threshold itself never relaxes.
- [ ] No new paid dependency or API key; reuses the configured Ollama model.
- [ ] **Tests Required** (mocked Ollama, no live model): `"Apple TV OnlyFans shows" → off_niche` (regression on the exact failure); `"Claude Opus 4.7 released" → on_niche`; `"iOS 19 adds Apple Intelligence" → on_niche`; `"startup raises $20M" / lawsuit / minor-tech → off_niche`; empty input handled. Follow the Ollama-mocked policy-gate test style.
- [ ] **Mock Injections:** Ollama mocked in unit tests; no live model call.
- [ ] Full suite green.

## Blocked by

None - can start immediately. (Pairs naturally with Ticket 30 but does not depend on its code.)

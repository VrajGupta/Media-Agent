# Issue 36 — Niche gate: split infrastructure failure from off_niche (fail-open + alert)

**Status:** ready-for-agent
**Type:** AFK
**User Stories:** 7, 8, 9, 10 (PRD `first-live-hybrid-gen-run.md`)

## Parent

PRD: `docs/prds/first-live-hybrid-gen-run.md`
ADR: `docs/adr/0004-ai-centric-niche-and-ingest-relevance-gate.md`

## What to build

Stop an Ollama hiccup from silently emptying the topic queue. The on-niche relevance gate
must distinguish an **infrastructure failure** (Ollama unreachable / invalid output) from
a real **off_niche** verdict.

End-to-end behavior:

1. When the niche classifier reports an infrastructure failure for a topic, the ingest
   gate **keeps** the topic (persists it, fail-open) instead of dropping it as off_niche,
   and emits a **distinct alert** (e.g. `niche_gate_unavailable`) so the operator sees the
   true cause.
2. A real `off_niche` verdict still drops the topic with the existing debug log line.
3. An `on_niche` verdict still keeps the topic.
4. The classifier **prompt is unchanged** in this issue (retuning is deferred to evidence
   from the live run — PRD story 10).

Rationale (grill record): if Ollama is down, every downstream Ollama stage fails anyway,
so the value here is observability and not silently producing zero topics — consistent
with the codebase's degrade-don't-fail pattern (aligner CPU fallback; policy_gate leaving
clips at `selected` on infra failure).

## Acceptance criteria

- [ ] A niche verdict carrying an infrastructure-failure flag results in the topic being
      kept (persisted), not dropped.
- [ ] A distinct alert is emitted on niche-gate infrastructure failure.
- [ ] A real `off_niche` verdict still drops the topic.
- [ ] An `on_niche` verdict still keeps the topic.
- [ ] The classifier prompt is unchanged.
- [ ] Unit tests (extending the existing niche-gate tests) assert: infra-fail → kept +
      alert; off_niche → dropped; on_niche → kept. Full suite green.

## Blocked by

None — can start immediately.

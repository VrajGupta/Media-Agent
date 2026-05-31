# ADR-0003 — Licensed-only image sourcing for autonomous ships

**Status:** Accepted
**Date:** 2026-05-26
**Context:** Surfaced while grilling the remaining roadmap to project completion
(`.sessions/2026-05-26__finish-line-roadmap/handoff.md`; grill record
`CONTEXT/Grilling/2026-05-26-finish-line-roadmap.md`).

## Context

Pivot.7 **Hybrid clips** introduce **Real-image shots** — Ken Burns motion over a
sourced still of a real product, logo, or object. `image_fetch` resolves a still
through an ordered source list: `logo → wikimedia → openverse → web`, with
`web_fallback_enabled: true`.

The first three are **Licensed sources** (rights-cleared: brand logo APIs, Wikimedia,
Openverse). The fourth — open web search (`ddgs` / optional SerpAPI) — returns
arbitrary images that are **not** rights-cleared. The project is a *fire-and-forget*
agent: the steady-state weekly run generates clips and the daily run auto-publishes
them to YouTube with no human in the loop (after the initial 2-week `human_review`
window). Auto-publishing a web-sourced product image is an **outward-facing,
hard-to-reverse** act: a Content-ID claim or a copyright/licensing strike lands on the
live channel before any human sees the image.

Pure-AI **Clips** never had this surface — Kling output is synthetic. Hybrid is the
first form that puts third-party visual material on the channel since the retired
"movie clips" pivot. The stale `copyright_acknowledgement: "movie_clips_v1"` config
value is a fossil of that earlier risk and does not describe this one.

## Decision

**The autonomous path uses Licensed sources only.** In production config,
`web_fallback_enabled: false` and `sources: [logo, wikimedia, openverse]`.

- If every **Licensed source** misses for a **Real-image shot**'s entity, the shot
  **degrades to an AI-video shot** rather than publishing a web image — the topic
  still ships, and disclosure already covers AI-video. (Degrade is chosen over
  whole-clip skip so an unattended run doesn't silently drop topics, and over
  hard-fail so no already-billed Kling spend is wasted; the exact mechanism is an
  implementation detail of the issue.)
- **Web fallback remains available for the manual spike / dev** (`web` may be enabled
  in a dev config or the throwaway `spike_hybrid.py`), where a human reviews output
  before any upload.
- `copyright_acknowledgement` is updated to a hybrid-era value (e.g.
  `hybrid_real_image_v1`); `bootstrap --check` continues to warn if it is absent.

This applies once `human_review` is off. During the locked 2-week `human_review`
window every clip is reviewed regardless, so the constraint is belt-and-suspenders
there and load-bearing afterward.

## Consequences

**Positive:**
- The unattended agent cannot publish an unvetted, non-rights-cleared image.
- Provenance (source/license/url sidecar) on every shipped **Real-image shot** is
  always a **Licensed source** — clean audit trail.
- AI disclosure + licensed-only sourcing is a defensible posture against Content-ID.

**Negative:**
- Topics whose entity has no logo/Wikimedia/Openverse image lose their "money shot"
  to AI b-roll, reducing real-image punch on those clips.
- Degrade-to-AI-video adds one more billed Kling shot on a miss (cost), unless the
  pipeline fetches real images before submitting Kling jobs.

**Mitigations:**
- The three **Licensed sources** cover the overwhelming majority of tech entities
  (companies, products, chips, logos). Misses are the long tail.
- Fetch real-image assets *before* billing Kling so a degrade is priced correctly.

## Alternatives considered

1. **Web fallback on, human-review gate.** Any web-sourced clip pinned to
   `output/pending` for manual approval. Rejected as the production default: it breaks
   the fire-and-forget promise — a human must clear clips indefinitely.
2. **Web fallback on, no gate.** Rely on provenance + AI disclosure, respond to
   takedowns reactively. Rejected: bets the live channel on every web image being
   claim-free; one strike can demonetize or remove the channel.

## Refinement — 2026-05-30 (degrade decision must run on a fetched asset, not a search probe)

**Context:** Grilling the first live hybrid `gen_run`
(`.sessions/2026-05-30__hybrid-gen-run-finish-line/handoff.md`). The as-built
resolver decided degrade-vs-keep with a *search-only probe*
(`probe_licensed_image`: true if a source returns **any candidate**, no download, no
validation) while the render step used a *different* function (`fetch_image`: download
+ resolution/content-type validation, raising `NoImageFoundError` on failure). The two
answer different questions, so a probe "hit" could keep a shot as **Real-image**, let
Kling bill the **AI-video shots**, and then abort at render when the candidate failed
to download/validate — wasting ~$2 of already-billed spend. This violated the "price
the degrade correctly *before* billing" mitigation above.

**Decision:** The "before billing" guarantee requires that the resolve step perform the
**same operation** the render step relies on. The licensed-source resolver
**fetches, validates, and caches** each **Real-image shot**'s still up front; a
**hit** means a validated, downloadable asset now sits in the cache, and a **miss**
degrades to **AI-video** — all *before* any Kling job is submitted. The render step
then reads the cached asset and never performs a second, possibly-divergent fetch.
Probe and fetch are unified into one cache-populating operation; the search-only probe
is retired.

**Consequence:** A **Licensed source** "satisfies" an entity only when it yields a
validated, downloadable still — not merely a search result. The billable AI-video count
is therefore exact at billing time, and a licensed miss can never cost wasted Kling
spend.

## Scope

Applies to the autonomous (auto-published) path only. The manual spike, dev configs,
and any human-reviewed run may enable `web`. Does not change pure-AI clips (no
real-image shots) and does not change AI disclosure.

## References

- `CONTEXT/CONTEXT.md` — **Licensed source**, **Hybrid clip**, **Real-image shot**.
- `docs/adr/0001` — two-gate sign-off; the first hybrid ship is treated as a first
  live ship under it (new external-content surface).
- `src/image_fetch/`, `config.yaml` (`image_fetch`, `copyright_acknowledgement`).

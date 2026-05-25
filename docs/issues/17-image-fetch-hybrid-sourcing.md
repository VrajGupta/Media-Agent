# Ticket 17 — `image_fetch` hybrid image sourcing module

**Status:** ready-for-agent
**Type:** AFK
**Slice:** Pivot.7 / P7.3
**User Stories:** 1, 8, 9, 10, 11, 12, 13, 26 (PRD `pivot-7-hybrid-real-image-shorts.md`)

## Parent

PRD: `docs/prds/pivot-7-hybrid-real-image-shorts.md`

## What to build

A new `src/image_fetch/` module that sources a **real image** for a given entity via a hybrid strategy: licensed/free sources first, web search as a fallback. Caches results and records provenance for audit.

End-to-end behavior:

1. **Source ABC.** Mirror `src/ai_gen/base.py`'s Provider pattern. `Source` ABC: `search(entity, query) -> list[ImageCandidate]` where a candidate carries at least `url`, `source`, `license`, `source_url`.
2. **Concrete sources, tried in priority order:**
   - `LogoSource` — brand/company logos (logo-type entities).
   - `WikimediaSource` — Wikimedia Commons API (CC-licensed).
   - `OpenverseSource` — Openverse API (CC-licensed aggregator).
   - `WebSearchSource` — keyless DuckDuckGo image search via `ddgs` (fallback). If `SERPAPI_KEY` is set, use SerpAPI instead for higher reliability.
3. **Orchestrator (public seam).** `fetch_image(entity, query, cfg, *, cache_dir) -> ImageAsset` where `ImageAsset = {path, source, license, source_url, width, height}`:
   - Cache key = `sha256(f"{entity}|{query}")`. Cache hit → return cached asset, **no HTTP**.
   - On miss → walk sources in priority order; for each candidate, **validate** (content-type is an image; decodable via Pillow; width/height ≥ `min_resolution`); take the first valid candidate; download to `cache_dir`.
   - Write a provenance sidecar JSON (`source`, `license`, `source_url`, dimensions) next to the cached image.
   - Web fallback is used **only** when all licensed/free sources miss (and only if `web_fallback_enabled`).
   - If nothing valid is found across all sources, raise a typed error so the caller can decide (Ticket 19 logs + skips/handles).
4. **Living-person guard.** Reject (or refuse to source) an entity flagged as a living person — `real_image` entities must be products/logos/objects (defense-in-depth with the scripter rule).
5. **Config.** New `ImageFetchConfig`: ordered `sources` priority list, `min_resolution`, `max_candidates_per_source`, `web_fallback_enabled`, optional SerpAPI key reference. `Paths.images_dir` default `data/images`. `Retention` gains an image-cache TTL.

No DB schema change. No paid API required by default (keyless `ddgs`).

## Acceptance criteria

- [ ] `Source` ABC + the four concrete sources implemented; each returns candidates with `url`/`source`/`license`/`source_url`.
- [ ] `fetch_image` returns an `ImageAsset` with a local `path` and recorded `source`/`license`/`source_url`/dimensions.
- [ ] **Priority order** honored: a licensed/free hit is preferred over web search.
- [ ] **Fallback**: when higher-priority sources miss, the next source is tried; web search used only after licensed sources miss and only if enabled.
- [ ] **Cache hit** returns without any HTTP call (asserted by a tripwire on the mocked session).
- [ ] **Validation** rejects non-image content-type, undecodable bytes, and sub-`min_resolution` images.
- [ ] Provenance sidecar JSON written for every cached image.
- [ ] Living-person entity is rejected.
- [ ] No usable image across all sources → raises a typed error (not a silent empty/None that reaches the assembler).
- [ ] `ImageFetchConfig` + `Paths.images_dir` + image-cache TTL load and validate.
- [ ] **Tests Required** (≥ 10, HTTP fully mocked): priority order; fallback to next source; web-only-after-licensed-miss; cache-hit-no-HTTP; reject non-image content-type; reject undersized; reject undecodable; provenance recorded; living-person rejected; no-result raises typed error.
- [ ] **Mock Injections:** all source HTTP mocked (no real Wikimedia/Openverse/ddgs/SerpAPI calls); Pillow decode exercised on tiny in-memory fixtures. Tests are offline and fast.
- [ ] Full suite green.

## Blocked by

None for the module itself. Consumed by Tickets 18 (Ken Burns) and 19 (assembler routing).

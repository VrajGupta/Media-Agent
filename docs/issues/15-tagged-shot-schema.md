# Ticket 15 — Tagged shot schema (Scripter: real_image vs ai_video)

**Status:** ready-for-agent
**Type:** AFK
**Slice:** Pivot.7 / P7.1
**User Stories:** 6, 7, 13, 23 (PRD `pivot-7-hybrid-real-image-shorts.md`)

## Parent

PRD: `docs/prds/pivot-7-hybrid-real-image-shorts.md`

## What to build

Make the Scripter tag each of the 4 shots as either `real_image` (a concrete entity to source as a real photo) or `ai_video` (a cinematic Kling prompt). This is the foundation every downstream Pivot.7 slice reads.

End-to-end behavior:

1. **Generator prompt (Stage B).** Rewrite `make_script_generator`'s prompt in `src/scripter/ollama_fns.py` so `shots` is a list of 4 tagged objects, not bare strings:
   - `{ "kind": "real_image", "entity": "<concrete product/logo/object>", "search_query": "<optional refinement>", "duration_s": 4 }`
   - `{ "kind": "ai_video", "prompt": "<10-20 word cinematic shot>", "duration_s": 4 }`
   - Prompt guidance: exactly 4 shots; aim for ~2 `real_image` + ~2 `ai_video`, alternating so AI shots sit between real ones; `real_image` entities are **products/logos/objects only — never a living person**; `ai_video` shots are abstract/atmospheric/transitional. Narration rubric unchanged (4 sentences, 30–50 words, hook in first 5 words, ends on a tease).
2. **Pure normalizer (new public seam).** `normalize_shots(raw_shots) -> list[dict]` in the scripter package (pure; no I/O):
   - A bare `str` → `{"kind": "ai_video", "prompt": <str>, "duration_s": 4}` (legacy back-compat).
   - A dict with `kind="real_image"` requires non-empty `entity`; `search_query` optional; defaults `duration_s=4`.
   - A dict with `kind="ai_video"` requires non-empty `prompt`; defaults `duration_s=4`.
   - Missing required key → raise `ValueError`; unknown `kind` → raise `ValueError`.
3. **Validation.** Extend `validate_script(script, cfg)` in `src/scripter/runner.py` to run `normalize_shots` on `script["shots"]` and reject if not exactly 4 shots or if normalization raises. Existing narration word-count and banned-token checks unchanged.
4. **Persistence.** `run_stage_b` continues to store `shots_json = json.dumps(<normalized shots>)`. Old `scripts` rows (list-of-strings) decode and pass through `normalize_shots` unchanged.
5. **Config.** Relax `AiGenConfig` shot-count expectations so a clip may carry 1–3 `ai_video` shots (the rest `real_image`). No new required keys.

No DB schema migration (`shots_json` already stores arbitrary JSON). No billed API calls (Ollama is local).

## Acceptance criteria

- [ ] `make_script_generator` prompt instructs the model to emit 4 tagged shot objects with the `real_image`/`ai_video` schema above; living-person entities explicitly disallowed for `real_image`.
- [ ] `normalize_shots` is a pure function: bare string → `ai_video`; valid tagged dicts pass; missing `entity` (real_image) or `prompt` (ai_video) raises `ValueError`; unknown `kind` raises `ValueError`; `duration_s` defaults to 4.
- [ ] `validate_script` rejects a script whose shots don't normalize or aren't exactly 4; narration word-count rule unchanged.
- [ ] Legacy list-of-strings `shots_json` round-trips through `normalize_shots` to all-`ai_video` shots (back-compat regression).
- [ ] `AiGenConfig` accepts clips with 1–3 `ai_video` shots without validation error.
- [ ] **Tests Required** (≥ 8): bare-string coercion; valid real_image dict; valid ai_video dict; missing-entity raises; missing-prompt raises; unknown-kind raises; wrong-shot-count rejected by `validate_script`; legacy-row back-compat. Follow the existing scripter test style.
- [ ] **Mock Injections:** the Ollama call is exercised via the injected `generator_fn` test double (no live Ollama); `normalize_shots`/`validate_script` need no mocks (pure).
- [ ] Full suite green via the project's standard test runner.

## Blocked by

None — can start immediately. Foundation for Tickets 18, 19, 20.

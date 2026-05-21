# Issue 06 — Pre-spike safety patches

## Parent

`docs/prds/slice-2-kling-spike.md` (Slice 2: OpenRouter Kling 3.0 spike)

## What to build

Two coordinated guardrails that must land before the first paid Kling call:

1. **Audio-off flag in OpenRouter Kling submit body.** OpenRouter bills Kling 3.0 std at $0.084/sec without audio vs $0.126/sec with audio (50% premium). Edge TTS owns narration in this pipeline, so the with-audio rate is pure waste. The `OpenRouterKlingClient.submit()` HTTP body must explicitly request no-audio output. The flag is hardcoded — not parameterized — because no-audio is the only mode this codebase ever uses, and a parameter creates a "forgot to pass it" failure mode.

2. **Tightened `ai_gen` budget ceilings.** Current `per_clip_cost_cents_max: 500` ($5/clip) is 3.7× larger than the real $1.34 per-clip cost — a near-useless guardrail. Current `daily_spend_cents_ceiling: 1000` ($10/day) would burn half the monthly budget in two days of a runaway loop. Both ceilings tighten to bound a bug at one week's budget instead of half a month's.

## Acceptance criteria

- [ ] `OpenRouterKlingClient.submit()` includes the OpenRouter Kling no-audio flag in every POST body to `/api/v1/videos` (flag name verified against OpenRouter Kling API docs at implementation time)
- [ ] One new test added to `tests/ai_gen/test_openrouter_kling.py` that mocks the HTTP session, calls `submit()` with any valid prompt, captures the POSTed JSON body, and asserts the no-audio key is present with the no-audio value
- [ ] All existing tests in `tests/ai_gen/test_openrouter_kling.py` (23 currently shipped) remain green — patch is additive, not invasive
- [ ] `config.yaml` updated: `ai_gen.per_clip_cost_cents_max: 500` → `200`
- [ ] `config.yaml` updated: `ai_gen.daily_spend_cents_ceiling: 1000` → `500`
- [ ] All existing `tests/test_config_p4.py` validation tests remain green (numeric values stay within validated Pydantic ranges)
- [ ] No new dependencies added to `pyproject.toml` / `requirements.txt`

## Blocked by

None — can start immediately.

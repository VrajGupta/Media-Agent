# Issue 26 — Licensed-only image sourcing for autonomous ships

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/finish-line-autonomous-hybrid.md` — Finish Line: Autonomous Hybrid
Pipeline. Decision of record: `docs/adr/0003-licensed-only-image-sourcing-for-autonomous-ships.md`.

## What to build

Make the autonomous (auto-published) path incapable of putting a non-rights-cleared
web image on the channel, per ADR-0003.

End-to-end behavior:

1. **Licensed sources only in production.** The autonomous path resolves a
   **Real-image shot** still from **Licensed sources** only — brand-logo APIs,
   Wikimedia, Openverse — with web search disabled (`web_fallback_enabled: false`,
   `sources: [logo, wikimedia, openverse]`). Web fallback remains usable in a dev
   config / the manual `spike_hybrid.py`, where a human reviews output before upload.
2. **Degrade-on-miss, before billing.** When every **Licensed source** misses for a
   real-image entity, that shot is rewritten to an `ai_video` shot **before** any Kling
   job is submitted — so an unattended run never drops the topic (the **Clip** still
   ships) and never wastes Kling spend on a clip that would otherwise be skipped. This
   replaces the current "fetch failure → whole clip skipped" behavior on the licensed
   path. The billable `ai_video` count is therefore known up front.
3. **Refresh the stale acknowledgement.** `copyright_acknowledgement` moves from
   `movie_clips_v1` to a hybrid value (e.g. `hybrid_real_image_v1`); `bootstrap --check`
   keeps warning when it is absent.

The resolution belongs in a small, testable seam: given the normalized shot list and a
licensed-only fetch probe, return the final shot list (missed real-image shots rewritten
to ai_video) and the billable ai_video count. Pure given an injected fetch fn — no
ffmpeg, Kling, or HTTP in the unit.

## Acceptance criteria

- [ ] Production `config.yaml`: `web_fallback_enabled: false`, `sources: [logo,
      wikimedia, openverse]`, `copyright_acknowledgement` set to the hybrid value.
- [ ] All-licensed-hit: shot list unchanged; billable ai_video count = number of
      ai_video shots in the script.
- [ ] One licensed miss: that real_image shot becomes an ai_video shot; billable count
      increments by one; the rewrite happens before any Kling submission (asserted via
      the injected probe / fake client ordering).
- [ ] With `web_fallback_enabled=false`, the web source is never consulted on the
      autonomous path (even on a licensed miss).
- [ ] `bootstrap --check` warns when `copyright_acknowledgement` is absent and passes
      with the hybrid value.
- [ ] Unit tests follow the injected-dependency style of
      `tests/test_hybrid_gen_run.py`; config validation follows `tests/test_config_p4.py`.
      Suite green.

## Blocked by

None — can start immediately (Issue 22 assembly fix is merged at `bca0095`).

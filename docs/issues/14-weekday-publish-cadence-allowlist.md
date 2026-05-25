# Issue 14 — Weekday publish-cadence allowlist (Tue/Thu)

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/slice-11-tue-thu-publish-cadence.md` (Slice 11: Steady-state publish cadence — Tuesdays & Thursdays)

## What to build

Give the slot planner a **weekday allowlist** so `publish_at_utc` is assigned only on configured weekdays (e.g. Tuesday and Thursday), at the existing `upload_slots` times-of-day. One thin vertical slice through every layer: config → pure allocator → runner wire-through → `config.yaml` → tests.

End-to-end behavior:

1. **Config field.** Add `upload_weekdays` to config. It accepts a list of weekday tokens — short names (`mon`..`sun`), full names (`monday`..`sunday`), or integers `0`..`6` — parsed **case-insensitively** into a normalized set of integer weekday indices using Python's `datetime.weekday()` convention (**Monday=0 … Sunday=6**). Parsing and validation live in the config layer (not the allocator). An unrecognized token is a load-time validation error. **Omitted or empty ⇒ all seven days** (backward compatible — existing/legacy configs behave exactly as before).

2. **Allocator weekday filter.** The pure `allocate_slots(...)` function gains an `allowed_weekdays` parameter (a set of integer weekday indices; `None` or the full set means no restriction). In its day-grid loop, skip any day whose `.weekday()` is not in the allowed set. Everything else the allocator already does is preserved unchanged: canonical timezone, DST-correct `zoneinfo` math, the `min_lead_minutes` past-slot filter, chronological ordering, overflow handling, and the `clips_per_day * days_per_run` capacity cap (the eligible-slot list is simply smaller after filtering). The function stays pure — no clock, DB, or filesystem; the caller injects `now_local`.

3. **Runner wire-through.** The slot-planner runner passes the parsed `upload_weekdays` set from config into `allocate_slots`. No other logic change. The daily uploader's existing today-window selection is untouched — Tue/Thu-slotted clips are naturally picked up on those days by the existing `publish_at_utc <= end_of_today_local` query.

4. **config.yaml.** Set `upload_weekdays: [tue, thu]`. Drop `clips_per_day` from 4 to **1** so realized cadence is 2 clips/week, matching the ~$5/week OpenRouter budget. Leave `upload_slots`, `days_per_run: 7`, and `timezone: Asia/Singapore` as-is. (`days_per_run ≥ 7` is required for a weekly run to always contain each target weekday — a config expectation, not enforced in code.)

No schema change. No new billed API calls. No Task Scheduler trigger changes (`daily_upload` still runs daily; it just finds Tue/Thu-slotted clips on those days).

## Acceptance criteria

- [ ] `upload_weekdays` config field accepts short names, full names, and integers, case-insensitively, parsing to the correct Monday=0 index set.
- [ ] Omitted or empty `upload_weekdays` resolves to all seven weekdays (backward compatible).
- [ ] An unrecognized weekday token raises a validation error at config-load time (not a silent zero-slot result).
- [ ] `allocate_slots(...)` accepts `allowed_weekdays` and assigns slots only on those weekdays; `None`/full-set is byte-identical to a run without the parameter (backward-compat regression test).
- [ ] With `upload_weekdays: [tue, thu]`, a 7-day window from a known `now_local` assigns slots only to the next Tuesday and Thursday at the configured `upload_slots` times — nothing on other days.
- [ ] The weekday filter composes correctly with `min_lead_minutes` (a target-weekday slot earlier than `now_local + lead` is dropped) and with the `clips_per_day` capacity cap.
- [ ] A window that excludes all target weekdays yields zero assignments and overflows all clips.
- [ ] Unit tests cover the allocator weekday cases and the config weekday parsing/validation, following the injected-`now_local` style in `tests/test_slot_planner_allocator.py` and the typed-field-validation style in the config-loader tests. All green via the project's standard test runner.
- [ ] `config.yaml` set to `upload_weekdays: [tue, thu]` and `clips_per_day: 1`.

## Blocked by

None — can start immediately. The allocator/config capability is independent of Slice 8 (`gen_run.py`); only full unattended automation waits on the orchestrator. (Note: earlier issues 10–13 use "Slice 11+" loosely to mean future steady-state work generally — this issue is the concrete Slice 11 cadence feature.)

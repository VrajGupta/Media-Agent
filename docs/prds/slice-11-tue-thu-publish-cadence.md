# Slice 11 — Steady-state publish cadence (Tuesdays & Thursdays)

**Status:** ready-for-agent
**Project:** Media-Agent Pivot.6
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-05-24
**Source session:** /grill-with-docs → /to-prd
**Blocks:** steady-state autonomous operation (the desired Tue/Thu publishing rhythm)
**Blocked by:** Slice 8 (`gen_run.py` orchestrator) for full automation — but the allocator change itself is independently shippable and testable today

---

## Problem Statement

As the channel owner, I want my Shorts to publish on a predictable weekly rhythm — **Tuesdays and Thursdays** — so the channel posts on a consistent schedule that matches my ~$5/week budget (2 clips/week). Today the slot planner spreads `publish_at_utc` across **every consecutive day** in its window: with `clips_per_day: 4` and four time-of-day slots, a weekly run would schedule up to 28 uploads across 7 straight days. There is no way to say "only Tuesday and Thursday." I cannot express my intended cadence, and I would blow my budget many times over.

## Solution

Give the slot planner a **weekday allowlist**. A new `upload_weekdays` config key (e.g. `[tue, thu]`) restricts slot assignment to those weekdays only, at the existing `upload_slots` times-of-day, while preserving everything else the allocator already does correctly: canonical timezone, DST-correct math via `zoneinfo`, the `min_lead_minutes` past-slot filter, chronological ordering, and overflow handling. When the key is omitted or empty, behavior is identical to today (all seven days) so the change is backward compatible. Alongside this, drop `clips_per_day` to **1** so the realized cadence is 2 clips/week, matching the budget.

The weekday filter lives in the existing **pure allocator** (`allocate_slots`), which takes plain parameters and has no I/O — so the new behavior is fully unit-testable without a clock, DB, or filesystem. Weekday-name parsing and validation live in the config layer, keeping the allocator working in plain integer weekday indices.

## User Stories

1. As the channel owner, I want to configure which weekdays my channel publishes on, so that I can run a Tuesday/Thursday cadence without editing code.
2. As the channel owner, I want the slot planner to assign publish slots **only** on my chosen weekdays, so that no clip is ever scheduled for a Monday, Wednesday, weekend, etc.
3. As the channel owner, I want the chosen weekdays to still use my configured times-of-day (`upload_slots`), so that a Tuesday clip still goes out at 09:00 SGT (or whichever slot times I set).
4. As the channel owner, I want the weekday filter to respect my canonical timezone (`Asia/Singapore`), so that "Tuesday" means Tuesday in my local time, not UTC.
5. As the channel owner, I want DST correctness preserved, so that if I ever switch the canonical timezone to a DST zone, "Tuesday 09:00 local" still resolves correctly across transitions.
6. As the channel owner, I want past slots (earlier than now + lead minutes) still filtered out on a fresh run, so that a Tuesday run never asks YouTube to publish in the past.
7. As the channel owner, I want a weekly run window (`days_per_run: 7`) to always contain my target weekdays, so that every weekly run finds at least one Tuesday and one Thursday to schedule into.
8. As the channel owner, I want clips beyond the available weekday slots to overflow (remain unscheduled) exactly as they do today, so that excess clips wait for the next window rather than getting crammed onto disallowed days.
9. As the channel owner, I want to set `clips_per_day: 1` so that I publish exactly one clip per publishing day (2/week), keeping me inside my $5/week OpenRouter budget.
10. As the channel owner, I want the cadence configurable per weekday-set (not hard-coded to Tue/Thu), so that I can later switch to e.g. Mon/Wed/Fri without another code change.
11. As the channel owner, I want omitting or leaving the weekday list empty to mean "all seven days," so that the change is backward compatible and existing configs behave exactly as before.
12. As the channel owner, I want an invalid weekday name in config (e.g. `tuseday`) to fail loudly at config-load time, so that a typo surfaces immediately rather than silently producing zero slots.
13. As the channel owner, I want to specify weekdays by short name (`tue`), full name (`tuesday`), or integer (`1`), case-insensitively, so that the config is forgiving of how I write it.
14. As a maintainer, I want the weekday filter implemented in the existing pure `allocate_slots` function, so that it is unit-testable in isolation with no clock, DB, or filesystem.
15. As a maintainer, I want weekday-name parsing kept out of the allocator (handled in the config layer), so that the allocator's interface stays in plain integer weekday indices and rarely changes.
16. As a maintainer, I want the daily uploader's existing today-window logic to keep working unchanged, so that on a Tuesday it naturally picks up the Tuesday-slotted clips and ignores Thursday's.
17. As a maintainer, I want a regression test proving that with no `upload_weekdays` set, the allocator produces byte-identical assignments to today, so that backward compatibility is guaranteed.
18. As a maintainer, I want explicit tests for the Tue/Thu case over a known week window, so that the feature's core promise is locked against regression.

## Implementation Decisions

**Modules built/modified:**

- **`slot_planner` allocator (deep module, modified).** `allocate_slots(...)` gains an `allowed_weekdays` parameter (a set/collection of integer weekday indices, Monday=0 … Sunday=6, matching `datetime.weekday()`). In the grid-building loop, a day is skipped when `day.weekday()` is not in the allowed set. `None` (or the all-seven set) means "no restriction" → identical to today's behavior. The function stays pure: no clock, no I/O, caller injects `now_local`. The capacity cap remains `clips_per_day * days_per_run`; the eligible-slot list is simply smaller after weekday filtering.
- **`config_loader` (modified).** New typed field `upload_weekdays`. Accepts a list of weekday tokens — short names (`mon`..`sun`), full names (`monday`..`sunday`), or integers `0`..`6` — parsed case-insensitively into a normalized set of integer indices. Omitted or empty → all seven (backward compatible). An unrecognized token raises a validation error at load time. Parsing/validation lives here, not in the allocator.
- **`slot_planner` runner (thin wire-through, modified).** Passes the parsed `cfg.upload_weekdays` set into `allocate_slots`. No other logic change.
- **`config.yaml` (modified).** Add `upload_weekdays: [tue, thu]`. Set `clips_per_day: 1` (down from 4) so realized cadence is 2 clips/week. Leave `upload_slots`, `days_per_run: 7`, and `timezone: Asia/Singapore` as-is.

**Contracts / semantics:**

- Weekday index convention is Python's `datetime.weekday()` (Monday=0). Documented at the config field and the allocator parameter.
- Omitted / empty `upload_weekdays` ≡ all seven weekdays (no behavior change for existing or legacy configs).
- `days_per_run` must be ≥ 7 for a weekly run to be guaranteed to contain each target weekday; this is a config expectation, not enforced in code (the allocator simply yields fewer slots if the window is too short).
- No schema change. No new billed API calls. The daily uploader's today-window selection is unchanged — Tue/Thu-slotted clips are picked up on those days by the existing `publish_at_utc <= end_of_today_local` query.

## Testing Decisions

**What makes a good test here:** assert the *external behavior* of the pure allocator — given `clip_ids`, an injected `now_local`, `upload_slots`, `days_per_run`, `clips_per_day`, `timezone_name`, and `allowed_weekdays`, the returned `(assignments, overflow)` is correct. Do not assert internal grid construction or private helpers. The allocator's purity (no clock/DB/FS) is exactly what makes this clean.

**Modules tested:** the `slot_planner` allocator and the `config_loader` weekday field.

**Prior art:** `tests/test_slot_planner_allocator.py` (13 existing tests, including `America/New_York` spring-forward and `Europe/Berlin` fall-back DST cases, the lead-time filter, and the `clips_per_day` cap) — new cases follow the same injected-`now_local` style. `tests/test_config_loader.py` / `tests/test_config_p4.py` are prior art for typed-field validation tests.

**New cases:**

- Allocator, Tue/Thu over a 7-day window from a known Sunday `now_local` → assignments land only on the next Tuesday and Thursday at the configured slot times; nothing on other days.
- Allocator, `allowed_weekdays=None` (and the full Mon–Sun set) → assignments byte-identical to a run without the parameter (backward-compat regression).
- Allocator, weekday filter interacts correctly with `min_lead_minutes` (a target-weekday slot earlier than `now_local + lead` is dropped).
- Allocator, `clips_per_day` cap still respected after weekday filtering.
- Allocator, window shorter than a week that excludes all target weekdays → zero assignments, all clips overflow.
- Config, weekday tokens parse case-insensitively from short names, full names, and integers into the correct index set.
- Config, omitted/empty `upload_weekdays` → all seven days.
- Config, an unrecognized weekday token raises a validation error at load.

## Out of Scope

- **The Slice 10 first-ship clip.** That mechanics-validation ship is deliberately decoupled and uses a near-term same-day slot, not this weekday cadence (see the amended Issue 11/12 and the 2026-05-24 grill record).
- **Per-week clip-count budgeting / dynamic cadence.** This slice fixes *which days*; it does not add spend-aware throttling beyond setting `clips_per_day: 1`.
- **Arbitrary schedules** (day-of-month, specific dates, cron expressions). Only a weekday allowlist.
- **Task Scheduler trigger changes.** `daily_upload` continues to run daily; it simply finds Tue/Thu-slotted clips on those days. No change to `scripts/*.xml`.
- **The upstream scripter "no real living people in shot prompts" fix** — separate steady-state work.

## Further Notes

- Naming: earlier issues (10–13) use "Slice 11+" loosely to mean "future steady-state work." This PRD is the concrete **Slice 11 = Tue/Thu cadence**. The mojibake root-cause fix and scripter-prompt hardening those issues defer remain separate future items, not part of this slice.
- The realized cadence depends on clip supply: the allocator only schedules clips that exist. With 2 publishing days/week and `clips_per_day: 1`, two available clips fill Tuesday and Thursday; a third overflows to the next window.
- Decision provenance: requested in the /grill-with-docs session on 2026-05-24; full context in `CONTEXT/Grilling/2026-05-24-slice-10-first-ship.md` and the Slice 11 checklist in `progress.md`.

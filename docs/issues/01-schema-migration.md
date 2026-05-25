# Ticket 01 — Schema migration: topics / seen_topics / scripts / generation_jobs

**Type:** AFK
**Slice in plan.md:** Slice 3
**User stories covered:** 11, 12, 22

## Parent

PRD: `docs/prds/automated-topic-to-script-pipeline.md`

## What to build

Extend the SQLite state store to support the Pivot.6 automated topic-to-script pipeline. Add four new tables (`topics`, `seen_topics`, `scripts`, `generation_jobs`), three column additions (`clips.content_kind`, `clips.script_id`, `quota_usage.provider`), and relax `clips.video_id` to nullable. Deliver an idempotent migration script that's safe to re-run, plus the DAL helper functions the downstream tickets will consume. Existing 457 tests must stay green, and the legacy `daily_upload.py --dry-run` body output must be byte-identical for `content_kind='sourced'` rows.

The exact DDL is in the PRD's "Schema specifics" section — including the table-rebuild dance needed to relax `clips.video_id` from NOT NULL to nullable (SQLite can't `ALTER COLUMN`). Foreign keys enabled per-connection via `PRAGMA foreign_keys=ON`. Indexes on hot paths: `topics.fetched_at`, `topics.status`, `scripts.status`, `scripts.topic_id`, `generation_jobs.script_id`.

## Acceptance criteria

- [ ] Fresh DB: migration applied → all 4 new tables exist with the correct columns, types, defaults, and indexes per the PRD DDL.
- [ ] Live DB: migration applied to a copy of `data/state.db` → no data loss, all pre-existing rows intact, `clips.content_kind='sourced'` populated by default on legacy rows.
- [ ] Migration is idempotent: running it twice produces no errors and no schema drift on second pass.
- [ ] `clips.video_id` is nullable post-migration (verified via `PRAGMA table_info(clips)`).
- [ ] `pytest tests/` — all 457 existing tests still green.
- [ ] Regression test: `daily_upload.py --dry-run` on a legacy `quality_pass` clip produces byte-identical body output to pre-migration baseline.
- [ ] FK enforcement: `INSERT INTO scripts` with an invalid `topic_id` fails when `PRAGMA foreign_keys=ON`.
- [ ] Migration script lives under `scripts/` and supports `--dry-run` (reports planned changes without applying them).
- [ ] DAL helpers added to `repository.py`: `insert_topic`, `seen_topics_in_window`, `mark_topic_scripted`, `mark_topic_expired`, `insert_script`, `update_script_status`, `clips_for_generation_run`, `get_clip_with_script`. Each covered by at least one unit test verifying the SQL query shape and return type.
- [ ] All new tests follow the prior-art pattern in `tests/test_repository_p1.py` (in-memory SQLite, no network).

## Blocked by

None — can start immediately.

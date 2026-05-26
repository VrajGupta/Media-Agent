# Issue 27 — Finish-line housekeeping

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/finish-line-autonomous-hybrid.md` — Finish Line: Autonomous Hybrid Pipeline.

## What to build

The doc/config/repo chores that should land before the project is called done. Each is
independent; bundled here because none warrants its own issue.

1. **Reconcile the `CLAUDE.md` / `claude.md` case-duplicate.** On Windows the two
   case-variant filenames collide; the hybrid doc fix landed in `claude.md` while
   `CLAUDE.md` shows modified. Merge to a single canonical **`CLAUDE.md`** (uppercase,
   matching the project-instructions reference) and remove the lowercase copy so future
   edits cannot silently diverge.
2. **Write `docs/rss_feeds.md`** (the Slice 7 deliverable that was never produced).
   Document the curated mixed consumer + research feeds currently inline in
   `config.yaml`, with a one-line rationale per feed and setup notes.
3. **Finish the hybrid-model doc pass** (closes P7.7 `[~]`): update `agents.md` and
   `skills.md` to describe the hybrid **Shot kind** mix, **Shot normalization**, and the
   ADR-0003 **Licensed source** posture, consistent with the `CONTEXT/CONTEXT.md`
   glossary.
4. **Commit the 3 uncommitted follow-up files** once the live spike (Issue 20) passes:
   `CLAUDE.md`, `scripts/spike_hybrid.py`, `tests/assembler/test_assemble_mixed_res.py`.
5. **Capture the CUDA cuBLAS PATH fix as a tracked, deferred perf item** in
   `progress.md` (Whisper currently falls back to CPU because `cublas64_12.dll` is not
   on PATH — works, just slow). Record the fix steps; do not implement.

## Acceptance criteria

- [ ] Exactly one canonical `CLAUDE.md` remains; the lowercase `claude.md` is gone and
      its content is merged in.
- [ ] `docs/rss_feeds.md` exists with the curated feed list + per-feed rationale.
- [ ] `agents.md` + `skills.md` describe the hybrid model (P7.7 doc box can be flipped).
- [ ] The 3 follow-up files are committed (after Issue 20 passes); working tree clean.
- [ ] `progress.md` carries a deferred cuBLAS PATH perf item with fix steps.

## Blocked by

None — items 1–3 and 5 can start immediately; item 4 waits on the Issue 20 spike pass.

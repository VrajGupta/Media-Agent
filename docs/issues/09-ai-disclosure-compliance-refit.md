# Issue 09 — AI disclosure compliance refit

## Parent

`docs/prds/slice-9-ai-disclosure.md` (Slice 9: Compliance refit — AI disclosure flag on upload)

## What to build

A content-kind-branched refit of the uploader so every `content_kind='ai_generated'` clip publishes with the YouTube Data API v3 `status.containsSyntheticMedia = true` flag plus an AI-branded description + tags. Sourced (legacy movie-clip) uploads must remain byte-for-byte identical to today's output — this is purely additive on the AI-gen branch.

The change is a single PR covering all six modules in the PRD's module sketch, the bundled documentation rename (`altered_content` / `madeWithAi` → `containsSyntheticMedia`) across CLAUDE.md / agents.md / skills.md / plan.md / progress.md, and the removal of the obsolete "manual Studio attestation as fallback" hedging from those docs. The hedge is obsolete because the API field has been live in v3 since 2024-10-30; no manual Studio path is needed.

End-to-end behavior:

1. **Templater (new pure functions).** `build_description_ai(*, hook, suggested_title, category) -> str` produces:
   ```
   {hook}

   Made with AI. For entertainment / educational use.

   #Shorts #{category_slug}
   ```
   where `category_slug = re.sub(r"[^a-z0-9]+", "", category.lower())` when category is present, falling back to the same slug rule on `suggested_title`. If both are empty, the description is just the bare `#Shorts` line (matching the sourced-clip's empty-hook fallback). A peer function `build_tags_ai(*, category, extra_tags=None) -> list[str]` produces `[category_slug, "shorts", "viral"]` with the same null-category fallback, lowercased + deduped + truncated to the 500-char joined budget.

2. **Body builder dispatch.** `build_insert_body` gains two new kwargs: `script_row` (optional `Mapping`) and `cfg` (Config). It dispatches on `clip_row["content_kind"]`. For `'ai_generated'` it calls the `_ai` templater pair using `script_row['category']`; for `'sourced'` (or anything else) it calls the existing helpers using `video_row['keyword']`. The `status` dict gains `containsSyntheticMedia: True` iff `clip_row['content_kind'] == 'ai_generated' AND cfg.compliance.ai_disclosure`; otherwise the key is omitted entirely.

   The exact gate logic (decision-bearing, do not paraphrase):
   ```python
   if (clip_row["content_kind"] == "ai_generated"
           and cfg.compliance.ai_disclosure):
       status["containsSyntheticMedia"] = True
   ```

3. **Repository DAL helper.** `repository.get_script(script_id: str) -> sqlite3.Row | None` — a single `SELECT * FROM scripts WHERE script_id=?`. Returns `None` if no row matches.

4. **Runner recheck-input helper.** Extract a new private helper from `upload_one_clip` that resolves the `(clip_text, recheck_title)` pair for both content kinds:
   - `content_kind='ai_generated'` → returns `(script_row['narration'], script_row['title'])`. No filesystem reads.
   - `content_kind='sourced'` → returns the existing transcript-words derivation, or a sentinel value when the transcript JSON is missing/unreadable.

5. **Runner wiring.** `upload_one_clip` fetches `script_row = repo.get_script(clip_row['script_id'])` when `content_kind='ai_generated'` (otherwise leaves it `None`). Threads `script_row` into the recheck helper (#4) and into `build_insert_body`. Threads `cfg` into `build_insert_body`. No other behaviour change; the orphan-marker fence, ID-first two-step persistence, and `do_resumable_upload` signature are all untouched.

6. **Doc rename pass.** Replace every occurrence of `altered_content`, `madeWithAi`, and `altered-content flag` in CLAUDE.md, agents.md, skills.md, plan.md, and progress.md with `containsSyntheticMedia`. Remove every "manual Studio attestation as fallback" hedge from those same files. The "research at Slice 9" / "Exact v3 API field name to be confirmed at Slice 9" lines also go — the research is complete. Worktree copies under `.claude/worktrees/` are excluded (they're snapshots, not live docs).

## Acceptance criteria

### Body builder + templater (pure-function correctness)

- [ ] `build_description_ai` outputs hook → blank line → `Made with AI. For entertainment / educational use.` → blank line → `#Shorts #{category_slug}` exactly, in that order
- [ ] `build_description_ai` falls back to `suggested_title` slug when `category` is null/empty
- [ ] `build_description_ai` returns the bare `#Shorts` line when hook, suggested_title, AND category are all empty
- [ ] `build_description_ai` output never contains the substring `Source:` or `Original channel:` under any input
- [ ] `build_tags_ai` always contains `["shorts", "viral"]` (lowercased)
- [ ] `build_tags_ai` prepends `category_slug` when category is present
- [ ] `build_tags_ai` honors the 500-char joined budget (existing `build_tags` behaviour)
- [ ] `build_tags_ai` deduplicates if `category_slug == "shorts"` or `"viral"`
- [ ] `build_insert_body` sets `status.containsSyntheticMedia = True` iff `content_kind='ai_generated'` AND `cfg.compliance.ai_disclosure=True`
- [ ] `build_insert_body` omits the `containsSyntheticMedia` key entirely when either gate condition is false
- [ ] `build_insert_body` for `content_kind='ai_generated'` uses the `_ai` templater functions
- [ ] `build_insert_body` for `content_kind='sourced'` uses the existing templater functions and produces byte-identical output to today's

### Runner + DAL plumbing

- [ ] `repository.get_script(script_id)` returns the matching `sqlite3.Row` for a known script_id
- [ ] `repository.get_script(script_id)` returns `None` for an unknown script_id
- [ ] `_resolve_recheck_inputs` returns `(script_row['narration'], script_row['title'])` for `content_kind='ai_generated'`
- [ ] `_resolve_recheck_inputs` returns the transcript-derived `(clip_text, hook OR suggested_title)` for `content_kind='sourced'`
- [ ] `_resolve_recheck_inputs` returns the missing-transcript sentinel when the JSON file is absent for a sourced clip
- [ ] `_resolve_recheck_inputs` does NOT touch the filesystem on the AI-gen path
- [ ] `upload_one_clip` calls `repo.get_script(clip_row['script_id'])` exactly when `content_kind='ai_generated'`
- [ ] `upload_one_clip(dry_run=True)` on an `ai_generated` clip writes a JSON file whose `status.containsSyntheticMedia` is `True`
- [ ] That dry-run JSON's description matches the locked layout (hook → footer → `#Shorts #{category_slug}`)
- [ ] That dry-run JSON's tags begin with the category slug
- [ ] `upload_one_clip(dry_run=True)` on a `sourced` clip produces a JSON file byte-identical to today's output (golden-fixture regression)
- [ ] `do_resumable_upload`'s signature and return type are unchanged

### Tests added

- [ ] `tests/test_uploader_templater_ai.py` — unit tests for `build_description_ai` and `build_tags_ai`
- [ ] `tests/test_uploader_insert_body_ai.py` — unit tests for the `build_insert_body` dispatch + gate
- [ ] `tests/test_uploader_runner_recheck.py` — unit tests for `_resolve_recheck_inputs`
- [ ] Existing `tests/test_uploader_runner.py` extended with an `ai_generated` fixture exercising `upload_one_clip(dry_run=True)` end-to-end

### Documentation rename pass

- [ ] CLAUDE.md, agents.md, skills.md, plan.md, progress.md: every occurrence of `altered_content`, `madeWithAi`, and `altered-content flag` is replaced with `containsSyntheticMedia`
- [ ] Every "manual Studio attestation as fallback" hedge is removed from those same files
- [ ] Every "research at Slice 9" / "to be confirmed at Slice 9" pointer is removed (the research is complete)
- [ ] `.claude/worktrees/**` is NOT modified (worktree snapshots are excluded)

### Non-regression / boundary guards

- [ ] No DDL changes; no schema migration; no new columns
- [ ] No new keys added to `config.yaml` or `ComplianceConfig`
- [ ] No new environment variables
- [ ] No CLI flag changes to `daily_upload.py` or `src/uploader/__main__.py`
- [ ] No new alert kinds in the uploader's `_BatchAlerts`
- [ ] No new YouTube quota calls (the slice does not add a verification `videos.list`)
- [ ] All pre-existing uploader tests pass without modification
- [ ] The 15 pre-existing CUDA / config-schema test failures noted in the Slice 8 handoff are NOT in this slice's scope (do not count them as regressions)

## Blocked by

None. Slice 8 (Issue 08 — `gen_run.py` orchestrator, commit `82ce0d1`) is complete; the schema columns this slice reads (`clips.content_kind`, `clips.script_id`, `scripts.category`, `scripts.narration`, `scripts.title`) were all delivered in Issue 01.

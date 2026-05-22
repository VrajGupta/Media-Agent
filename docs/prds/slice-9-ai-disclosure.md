# Slice 9 — Compliance refit (AI disclosure on upload)

**Status:** ready-for-agent
**Project:** Media-Agent Pivot.6
**Path:** `C:\Users\cryptix\Desktop\Work\Media-Agent-main`
**Authored:** 2026-05-22
**Source session:** /grill-with-docs → /to-prd
**Blocks:** Slice 10 (first live AI-generated upload)
**Blocked by:** Slice 3 (schema), Slice 8 (gen_run) — both complete

---

## Problem Statement

As the channel owner I am about to publish AI-generated Shorts (Kling visuals + Edge TTS narration) to YouTube. YouTube's creator policy (March 2024+) requires me to disclose realistic Altered or Synthetic (A/S) content at upload. If I publish without that disclosure, the channel is exposed to policy strikes, possible monetization loss, and viewer-trust erosion. The existing uploader was built for the previous "movie clips" pivot — it always writes a "Source: youtube.com/watch?v=…" + "Original channel: …" attribution block (irrelevant and misleading for AI-generated content) and it never sets any A/S disclosure flag on the `videos.insert` body. Without a fix, Slice 10 cannot ship a compliant first upload.

## Solution

Refit the uploader so every `content_kind='ai_generated'` clip publishes with:

1. The YouTube Data API v3 disclosure flag `status.containsSyntheticMedia = true` set on the `videos.insert` body (research-resolved: this field has been live in v3 since 2024-10-30, so the previously-documented "manual Studio attestation fallback" is no longer needed).
2. A redesigned description: hook → "Made with AI. For entertainment / educational use." → `#Shorts #{category_slug}`. The "Source / Original channel" attribution block is dropped for AI-gen.
3. A redesigned tags list seeded from `scripts.category` (e.g. `ai-models`, `policy`, `hardware`) instead of the now-empty `videos.keyword` column, preserving the static `shorts` / `viral` tags and the 500-char budget.
4. A pre-upload policy re-check that reads the source narration from `scripts.narration` (TTS source-of-truth) instead of trying to load a Whisper transcript that does not exist for AI-gen clips.

Sourced clips (the legacy `content_kind='sourced'` path) must continue to produce byte-identical bodies — the refit is a content-kind-branched addition, not a rewrite.

## User Stories

1. As the channel owner, I want every AI-generated clip uploaded with the official YouTube A/S disclosure flag, so that I am compliant with YouTube's March-2024 altered-content policy without manually attesting in Studio.
2. As the channel owner, I want the disclosure flag wired through the API rather than the Studio UI, so that the daily upload runs unattended without me babysitting each clip.
3. As the channel owner, I want the description footer "Made with AI. For entertainment / educational use." to appear on every AI-gen clip, so that viewers see transparent context even if they miss YouTube's small "Altered or synthetic content" label.
4. As the channel owner, I do **not** want the "Source: youtube.com/watch?v=…" line published on AI-gen clips, so that viewers are not misled into thinking the clip is a re-upload of someone else's video.
5. As the channel owner, I do **not** want the "Original channel: …" attribution line published on AI-gen clips for the same reason.
6. As the channel owner, I want a niche-affinity hashtag (e.g. `#aimodels`) on each AI-gen clip so that YouTube's discovery surface can group my clips topically over time.
7. As the channel owner, I want the hashtag derived from the curated `scripts.category` enum rather than per-clip titles, so that the hashtag is short, stable, and compounds discovery value across many clips in the same category.
8. As the channel owner, when a script lacks a category, I want the templater to fall back to slugging `suggested_title` and ship the clip anyway, so that one upstream gap does not block a publish slot.
9. As the channel owner, I want sourced (movie-clip) uploads to remain byte-for-byte identical to today's output, so that this slice cannot regress the legacy code path even by accident.
10. As the channel owner, I want a single config kill-switch (`compliance.ai_disclosure`) that can suppress the disclosure flag if I deliberately want to upload an internal test clip, so that I have an explicit override without editing code.
11. As the channel owner, I want the disclosure decision to require **both** `content_kind='ai_generated'` **and** `cfg.compliance.ai_disclosure=true`, so that the flag never fires on legacy sourced clips by accident and never fails to fire on AI clips when policy is on.
12. As the channel owner, I want the pre-upload policy re-check to still run on AI-gen clips, so that policy drift between render time and upload time is still caught (just like for sourced clips).
13. As the channel owner, I want the AI-gen re-check to read `scripts.narration` directly rather than try to load a Whisper transcript, so that the upload does not crash on the missing transcript file every AI-gen clip would otherwise lack.
14. As the channel owner, I want the dry-run uploader output for an AI-gen clip to write the full insert body JSON to `data/dry_run/{clip_id}.json` (same path as today), so that I can review the exact payload locally before any quota is spent.
15. As the channel owner, I want existing dry-run JSON files for sourced clips to continue producing the same shape, so that I can regression-compare old and new outputs side by side.
16. As the channel owner, I want all uploader documentation (CLAUDE.md, agents.md, skills.md, plan.md, progress.md) to refer to the real API field name `containsSyntheticMedia` rather than the outdated guesses `altered_content` / `madeWithAi`, so that future-me (or a future agent reading the docs) doesn't reintroduce the wrong field name.
17. As the channel owner, I want the "manual Studio attestation as fallback" hedge removed from every doc that carries it, so that the docs no longer imply work that is no longer needed.
18. As a developer reading the templater, I want a separate `build_description_ai` / `build_tags_ai` pair rather than overloaded if-branches inside the existing functions, so that the AI-gen and sourced paths can evolve independently and each function stays single-purpose.
19. As a developer reading the uploader runner, I want a single small helper that decides "give me the text + title to re-check" for any clip regardless of kind, so that the recheck branch is testable in isolation without spinning up a full clip.
20. As a developer extending the uploader to other AI providers in the future (Pika, MiniMax, Seedance), I want the disclosure flag to be tied to `content_kind` rather than to the specific generator, so that swapping providers does not require touching uploader code.
21. As a developer reviewing the diff, I want zero changes to `do_resumable_upload`'s return signature, so that the existing quota-ledger + orphan-marker plumbing remains untouched.
22. As a developer reviewing the diff, I want no schema migration in this slice, so that database state is unchanged and rollback is a code-only revert.
23. As the channel owner, I want the first 5 real AI-gen uploads (Slice 10) to be manually spot-checked in YouTube Studio to confirm the disclosure label is present on the published Short, so that I have human confirmation the field round-tripped before trusting the pipeline.
24. As the channel owner, I do **not** want the uploader to make an extra `videos.list` quota call after each upload just to verify the disclosure echoed back, so that I do not double my YouTube quota usage for a field that has been stable since 2024.
25. As the channel owner, I want the daily upload CLI to require no new flags for this slice, so that my Task Scheduler entry doesn't have to change.

## Implementation Decisions

### Locked decisions from the grilling session (2026-05-22)

1. **API field name:** `status.containsSyntheticMedia` (boolean). Added to the YouTube Data API v3 on 2024-10-30. No Studio fallback path required.
2. **Disclosure rule:** unconditionally `true` for any clip with `content_kind='ai_generated'`. Justified by the TTS narration alone being synthetic; not contingent on whether the Kling visuals look "realistic enough" under the policy.
3. **Gating:** `status.containsSyntheticMedia` is set when `clip.content_kind == 'ai_generated' AND cfg.compliance.ai_disclosure`. Both conditions required. The config flag remains as an emergency kill switch; default stays `True`.
4. **Description layout (AI-gen only):**
   ```
   {hook}

   Made with AI. For entertainment / educational use.

   #Shorts #{category_slug}
   ```
   Sourced clips keep today's layout (hook → Source URL → Original channel → hashtags).
5. **Tags layout (AI-gen only):** `[category_slug, "shorts", "viral"]`. Lowercased + deduped + truncated to fit the 500-char joined budget, same logic as today's `build_tags`.
6. **Hashtag source:** `scripts.category` (the scripter Stage A enum). Fallback to `suggested_title` slug if category is null/empty.
7. **DB plumbing:** add a thin DAL helper `repository.get_script(script_id)`. The uploader runner calls it when `content_kind='ai_generated'` and passes the row through as a kwarg to `build_insert_body`. Existing `repository.get_clip_with_video` is untouched — no widening of an already-load-bearing join.
8. **Templater shape:** two new pure functions live alongside the existing ones:
   - `build_description_ai(*, hook, suggested_title, category) -> str`
   - `build_tags_ai(*, category, extra_tags=None) -> list[str]`
   The dispatch happens in `build_insert_body`, which is taught to accept an optional `script_row` and the `cfg` object so it can read the gate.
9. **Response verification:** skipped. The user spot-checks Studio for the first ~5 uploads to confirm the field round-tripped, then trusts the API. `do_resumable_upload`'s signature is unchanged.
10. **Policy re-check on AI-gen:** when `content_kind='ai_generated'`, the recheck skips the transcript load entirely and feeds `scripts.narration` (as the clip text) + `scripts.title` (as the recheck title) into `evaluate_clip_policy`. Sourced clips keep today's transcript-words path.
11. **Doc cleanup is in-scope:** rename `altered_content` / `madeWithAi` → `containsSyntheticMedia` across CLAUDE.md, agents.md, skills.md, plan.md, progress.md. Drop every "manual Studio attestation as fallback" hedge in those same docs. agents.md line 104 and skills.md line 29 also get the description footer wording matched to the locked text.

### Modules built or modified

| # | Module | Kind | Interface |
|---|--------|------|-----------|
| 1 | `src/uploader/templater.py::build_description_ai` | New, pure | `(*, hook: str, suggested_title: str, category: str \| None) -> str` |
| 2 | `src/uploader/templater.py::build_tags_ai` | New, pure | `(*, category: str \| None, extra_tags: Sequence[str] \| None = None) -> list[str]` |
| 3 | `src/uploader/insert_body.py::build_insert_body` | Modified, pure | Adds `script_row: Mapping \| None` and `cfg: Config` kwargs. Dispatches title/description/tags + sets `status.containsSyntheticMedia` based on `clip_row['content_kind']` and `cfg.compliance.ai_disclosure`. |
| 4 | `src/state/repository.py::get_script` | New DAL | `(script_id: str) -> sqlite3.Row \| None`. Single SELECT against `scripts`. |
| 5 | `src/uploader/runner.py::_resolve_recheck_inputs` | New extracted helper | `(*, clip_row, script_row, transcripts_dir) -> _RecheckInputs \| _RecheckMissing`. Returns the `(clip_text, recheck_title)` pair for both content kinds, or a sentinel when the sourced-clip transcript is missing/unreadable. |
| 6 | `src/uploader/runner.py::upload_one_clip` | Modified | When `content_kind='ai_generated'`, fetches `script_row = repo.get_script(clip_row['script_id'])`. Threads `script_row` into both the recheck helper (#5) and `build_insert_body` (#3). Threads `cfg` into `build_insert_body`. No other behaviour change. |

### Gating logic (decision-bearing snippet, from the grilling)

This is the exact gate the body builder applies. Inlined here because the precise boolean shape is the slice's core compliance claim — paraphrasing would lose it:

```python
status = {
    "privacyStatus": "private",
    "publishAt": format_publish_at_iso_z(padded_publish_at_utc),
    "selfDeclaredMadeForKids": False,
    "madeForKids": False,
    "license": "youtube",
    "embeddable": True,
}
if (clip_row["content_kind"] == "ai_generated"
        and cfg.compliance.ai_disclosure):
    status["containsSyntheticMedia"] = True
```

For sourced clips, or when `cfg.compliance.ai_disclosure` is `False`, the key is omitted entirely (matches today's body shape).

### Description shape (decision-bearing snippet)

AI-gen description format. Order, blank-line separators, and slug derivation are load-bearing:

```
{hook}

Made with AI. For entertainment / educational use.

#Shorts #{category_slug}
```

`category_slug` is `re.sub(r"[^a-z0-9]+", "", category.lower())` when category is present; otherwise the same slug rule applied to `suggested_title`. If both are empty, just `#Shorts`.

### No schema changes

No DDL, no migration, no new columns. The slice rides entirely on:
- `clips.content_kind` (already added in Slice 3 / Ticket 01)
- `clips.script_id` (already added in Slice 3 / Ticket 01)
- `scripts.category` (already added in Slice 3 / Ticket 01)
- `scripts.narration` (already added in Slice 3 / Ticket 01)
- `scripts.title` (already added in Slice 3 / Ticket 01)

### No new config keys

`compliance.ai_disclosure` already exists in `ComplianceConfig` (`src/config_loader/loader.py:94`, default `True`) and is already covered by `test_config_p4.py`. No additions needed.

### Out-of-band side effects

None. The slice writes no new files at runtime (the dry-run JSON path is unchanged), introduces no new quota calls, and adds no environment variables.

## Testing Decisions

### What makes a good test in this codebase

Existing uploader tests (e.g. `tests/test_uploader_*`) cover behaviour at the function boundary: pure functions are tested with explicit kwargs and asserted-against literal expected output; `upload_one_clip` is tested through its public outcome enum + the dry-run JSON file it writes. No test reaches into private state or patches things that aren't injected. New tests will follow the same discipline — assert only what the function returns, contributes to the body dict, or writes to disk.

### Modules under test

| Module | Test file | Asserts |
|--------|-----------|---------|
| `build_description_ai` (#1) | `tests/test_uploader_templater_ai.py` (new) | Hook → footer → hashtag order; blank-line separators preserved; `category_slug` derived correctly; null-category falls back to `suggested_title` slug; both empty → bare `#Shorts`; no "Source:" / "Original channel:" substring under any input. |
| `build_tags_ai` (#2) | `tests/test_uploader_templater_ai.py` (new) | Always contains `["shorts", "viral"]`; category slug prepended when present; null-category falls back to `suggested_title` slug; 500-char budget honored; lowercased + deduped. |
| `build_insert_body` dispatch (#3) | `tests/test_uploader_insert_body_ai.py` (new) | For `content_kind='ai_generated'` + `cfg.compliance.ai_disclosure=True`: `status.containsSyntheticMedia == True`, description has "Made with AI." line, description omits "Source:" + "Original channel:", tags built from category. For `content_kind='ai_generated'` + `ai_disclosure=False`: `containsSyntheticMedia` key absent (gate off). For `content_kind='sourced'`: body byte-identical to today's output (regression guard via golden fixture). |
| `_resolve_recheck_inputs` (#5) | `tests/test_uploader_runner_recheck.py` (new) | AI-gen path returns `(scripts.narration, scripts.title)` and never touches the filesystem. Sourced path returns transcript-derived `(clip_text, hook OR suggested_title)`. Missing-transcript sentinel returned when the JSON file is absent for a sourced clip. |
| End-to-end dry-run with AI-gen fixture | extend `tests/test_uploader_runner.py` (or its dry-run sibling) | One new test: `upload_one_clip(dry_run=True)` on an `ai_generated` clip writes a JSON file whose `status.containsSyntheticMedia` is `True`, whose description matches the locked layout, and whose tags begin with the category slug. This is the formal acceptance test for the slice. |

### Prior art

- `tests/test_uploader_templater.py` (sourced-clip templater unit tests) — same shape, just for the AI variants.
- `tests/test_uploader_insert_body.py` (current body builder tests) — golden-dict assertions against `build_insert_body` output. The new AI-gen tests follow the same pattern.
- `tests/test_uploader_runner.py` (existing runner orchestration tests using injected `now_utc` + dry-run mode) — the new end-to-end dry-run test reuses that fixture style.

### Regression guard for sourced clips

The existing `build_insert_body` tests must continue to pass byte-for-byte after the signature widens (new kwargs are optional with backwards-compatible defaults: `script_row=None`, `cfg` passed but only read when the gate would fire). This is the single most important non-functional guarantee of the slice and is asserted via the unchanged existing test file.

### Tests intentionally not written

- `repository.get_script` (#4): a one-line SELECT. Covered indirectly by the end-to-end dry-run test. A dedicated unit test would be over-testing SQLite.
- `upload_one_clip` for AI-gen as a unit: the orchestration is exercised by the new dry-run integration test plus the unit tests of #1/#2/#3/#5. A separate unit test of `upload_one_clip` would mostly assert what the helpers already assert.

## Out of Scope

- **Quota-increase audit / collapsing daily_upload back into gen_run.** Separate future work; daily/weekly split stays as-is.
- **YouTube `videos.update` for already-uploaded clips that lack the flag.** No backfill of historical sourced uploads.
- **Response verification (read-back of `containsSyntheticMedia`).** Manual Studio spot-check on the first ~5 uploads instead. Revisit if a regression ever surfaces.
- **Provider-agnostic disclosure metadata.** The flag is tied to `content_kind`, not to which AI provider produced the visuals. Switching from Kling to Pika/MiniMax/Seedance does not require any change here.
- **Schema migrations.** No new columns, no new tables.
- **New config keys.** `compliance.ai_disclosure` already exists.
- **`daily_upload.py` CLI flags.** No additions.
- **Telemetry / alerts for disclosure decisions.** No new alert kind; the existing dry-run JSON + Studio spot-check are sufficient at 2–3 clips/week.
- **Removal of the `videos` table or `videos.keyword` column.** Sourced-clip code path stays intact in case the channel ever ingests a sourced clip again.

## Further Notes

- The doc-rename pass (`altered_content` / `madeWithAi` → `containsSyntheticMedia`) and the removal of the "manual Studio attestation as fallback" hedge are in-slice because the docs explicitly said "research at Slice 9" — that research is complete and the docs should match reality in the same commit as the code. Worktree copies under `.claude/worktrees/` are excluded from the rename (they're snapshots, not live docs).
- The acceptance criterion in `plan.md:97` ("Dry-run uploader output JSON shows correct AI-gen description, no source/channel field, AI disclosure flag set") is exercised end-to-end by the new dry-run runner test.
- Slice 10 (first live AI-gen upload) depends on this slice + Slice 8 (gen_run, complete). After Slice 9 merges, Slice 10 needs no further uploader code work — just a user-driven drag from `output/pending/` → `output/approved/` and a `python -m src.uploader` run.
- The `category_slug` rule reuses `re.sub(r"[^a-z0-9]+", "", lower)` from the existing `_slug_keyword` helper. The implementation can either reuse it directly or rename it for clarity; the choice is local.
- Pre-existing failing tests (CUDA-dependent `lang_detect` / `selector` tests, plus old config-schema mismatches) are not regressions and not in scope for this slice.

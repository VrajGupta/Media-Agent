# Issue 10 — clean_mojibake utility + tests

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/slice-10-first-live-ai-gen-upload.md` (Slice 10: First live AI-generated upload)

## What to build

A new pure utility module that fixes the U+FFFD ("`�`") replacement-character corruption surfaced in the qwen2.5:3b scripter output. The utility lives in `src/scripter/sanitize.py` and exports one function:

```
clean_mojibake(text: str) -> str
```

The function replaces every U+FFFD codepoint with U+0027 (`'`). No other transformation, no I/O, no side effects, no dependencies beyond the standard library. The replacement is correct because every observed instance of `�` in scripter output corresponds to a smart-quote (U+2019) in the source RSS article that got corrupted during the topic-ingest → scripter round-trip; replacing with a straight ASCII apostrophe is the cheapest restoration that yields correct TTS pronunciation and clean Whisper subtitles.

This is the workaround for a defect whose proper root-cause fix belongs in `topic_ingest/` (Slice 11+). The workaround is intentionally a small deep module so the same one-line call is the canonical fix wherever mojibake might leak — narration stage, assembler, hand-stitch scripts, and any future scripter persistence path.

The utility is consumed by Issue 11 (hand-stitch script). Wiring it into the steady-state narration stage is explicitly Slice 11+ work and not part of this issue.

## Acceptance criteria

- [ ] `src/scripter/sanitize.py` exists with one exported function `clean_mojibake(text: str) -> str`.
- [ ] Empty input returns an empty string.
- [ ] Input with no U+FFFD returns the input unchanged (byte-for-byte).
- [ ] A single U+FFFD is replaced with `'`.
- [ ] Multiple U+FFFD occurrences in one string are all replaced.
- [ ] Non-mojibake characters around the replacements (including other Unicode codepoints, whitespace, and ASCII) are preserved exactly.
- [ ] Unit tests in `tests/test_scripter_sanitize.py` cover all 5 acceptance behaviours above. Pattern matches the pure-function style of `tests/test_scripter_stage_a.py`.
- [ ] Tests green via the project's standard test runner.
- [ ] No other module is modified — this issue introduces the utility only; consumers come in later issues.

## Blocked by

None — can start immediately. (The Pivot.6 schema migration is already applied to the live `data/state.db`.)

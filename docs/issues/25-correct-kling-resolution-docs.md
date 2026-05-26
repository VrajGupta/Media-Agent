# Issue 25 — Correct the Kling-resolution docs

**Status:** ready-for-agent
**Type:** AFK

## Parent

`docs/prds/p7-fix-hybrid-assembly-normalization.md` — Pivot.7 Fix: Canonical shot
normalization in the assembler. Decisions of record: `docs/adr/0002`.

## What to build

CLAUDE.md's "Locked decisions" claim Kling output is "native 1080×1920" and "Shots
are already 1080×1920". This is false — Kling 3.0 std emits **720×1280 @ 24fps**
(`ffprobe`-verified), and that false assumption is what hid the hybrid-assembly defect.
Correct the docs so nobody re-derives it.

End-to-end behavior: update the affected prose in CLAUDE.md (vertical-layout /
generator locked-decision lines) and the agents.md assembler section to state: Kling
std emits 720×1280; the assembler normalizes every **Shot** to the canonical
1080×1920 before **Stitching** (per ADR-0002). Keep the wording consistent with the
`CONTEXT/CONTEXT.md` glossary terms **Stitch** and **Shot normalization**.

## Acceptance criteria

- [ ] CLAUDE.md no longer claims Kling output is "native 1080×1920" / "already
      1080×1920"; it states the 720×1280 source + assembler normalization to 1080×1920.
- [ ] agents.md assembler section documents the **Shot normalization** step and
      references ADR-0002.
- [ ] No change to worktree snapshots under `.claude/worktrees/`.
- [ ] Wording uses the glossary terms **Stitch** / **Shot normalization** consistently.

## Blocked by

None — can start immediately (independent of the code slices).

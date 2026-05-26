# Session index — media-agent

Each row is one session. Read the most recent first. The "Next action" column
is copied from each session's "Immediate next action" section — it tells you
where the work is at a glance.

| Date | Session folder | Summary | Next action |
|---|---|---|---|
| 2026-05-26 | [p7-hybrid-assembly-fix-plan](2026-05-26__p7-hybrid-assembly-fix-plan/handoff.md) | Diagnosed Pivot.7 hybrid assembly failure (xfade resolution mismatch, rc 4294967274 = err -22), reproduced + verified fix locally; grill → ADR-0002 + glossary (Stitch / Shot normalization) → PRD `p7-fix-hybrid-assembly-normalization` → Issues 22–25 | Implement Issue 22: `src/assembler/normalize.py` + build.py normalization + gen_run wiring + ffmpeg-guarded mixed-res integration test |
| 2026-05-24 | [slice-10-refine-slice-11-cadence](2026-05-24__slice-10-refine-slice-11-cadence/handoff.md) | Refined Slice 10 (shot 3 lead, 315¢, reuse-shots flag, same-day slot); new Slice 11 Tue/Thu cadence PRD + Issue 14; amended Issues 11/12 + Slice 10 PRD; glossary created | Implement Issue 11 (`--reuse-shots/--order` flag on render_from_script.py, order 3,2,1,0), assemble candidate `7cb41305`, insert `clips` row |
| 2026-05-23 | [slice-10-grill-tdd-issues-10-11](2026-05-23__slice-10-grill-tdd-issues-10-11/handoff.md) | Slice 10 grill locked, DB migrated, Issues 10–13 created, clean_mojibake + hand-stitch script shipped | Run `python scripts/hand_stitch_slice_10.py` then follow Issue 12 checklist |

# Grill session — Slice 10 first live ship (refinement)

**Date:** 2026-05-24
**Mode:** /grill-with-docs (Opus 4.7, high effort)
**Subject:** What's next = Slice 10, the first live AI-generated upload (candidate `7cb41305` "Corti's Symphony Beats OpenAI in Medical Speech Recognition") to the test channel.
**Builds on:** the 2026-05-23 grill that locked the two-gate sign-off (`docs/adr/0001`) and the operational pre-flight.

---

## State verified against disk + live DB (not the checkboxes)

- **Migration already applied.** `clips.content_kind`, `clips.script_id`, `quota_usage.provider`, and the `topics`/`scripts`/`generation_jobs` tables are all present in `data/state.db`. The plan's "apply `migrate_pivot_6_3.py`" pre-flight step was stale.
- **Clip not assembled; no `clips` row** for the candidate. The real pending work is the hand-stitch, not the migration.
- **Narration grounded, not hallucinated.** "1.4% vs OpenAI's 17.7% WER" is verbatim from the VentureBeat source; "93%" is a mild conflation of "up to 93% WER reduction vs leading generalist models." Mojibake is real (`Corti�s`, `OpenAI�s` → U+FFFD).
- **Three of four shots are synthetic people**, not just shot 0. But only **shot 0** came from a prompt naming a real person (the CEO); shots 2 & 3 are generic clinicians (compliant with disclosure). Narration names no one.
- **Cost ledger messy.** `generation_jobs` for the script: raw `SUM(cost_cents)` = 621¢ (includes `dry_run` rows at 34¢); `status='succeeded'` = 315¢ across **5** renders — shot 0 succeeded twice under distinct `external_id`s (`ifAeq9TM…`, `u1G4K99n…`), i.e. two real billed renders.
- **`render_from_script.py` always regenerates** shots from prompts (no reuse, no reorder); `slot_planner` allocates over **consecutive** days only (no weekday filter).

---

## Decisions (Q→A with rationale)

1. **Ship bar → Mechanics validation.** Prove upload→disclosure→Content ID→cost end-to-end on the test channel; content bar = "compliant + not embarrassing," not portfolio quality.
2. **Lead/cover frame → Shot 3** (clinician + medical scan). Cleanest, on-topic, compliant. Supersedes the prior "swap 0↔1 so the whiteboard is the cover" — the whiteboard frame has garbled AI text and is the worst-looking cover; the synthetic-"CEO" shot 0 is buried last.
3. **Cost baseline → 315¢** (all `status='succeeded'` renders; the shot-0 re-roll was really billed). Gate query must filter `status='succeeded'`; ±5% band = 299–331¢. The earlier 252¢ figure (4 in-clip shots) is superseded.
4. **Stitch path → add `render_from_script.py --reuse-shots <dir> --order`** (skip Stage-1 generation; feed existing MP4s to the unchanged narration→subtitle→assembler stages). No regeneration → no extra spend, no re-firing the named-CEO prompt.
5. **First-ship timing → decouple, validate today.** Ship the mechanics-validation clip with a near-term slot (~45–60 min out: >20 min so no padding, within the T+1h ship-gate window). Tue/Thu cadence is steady-state work, off this clip's critical path.
6. **Steady-state cadence → Tuesdays & Thursdays.** Requires a new `upload_weekdays` config knob + a weekday skip in the allocator grid loop — not expressible today. Captured as **Slice 11**.

---

## Doc changes made this session

- **`CONTEXT/CONTEXT.md`** — created the domain glossary (Topic, Script, Shot, Clip, Content kind, Synthetic-person frame; ship-lifecycle terms).
- **`progress.md`** — corrected Slice 10 pre-flight; added the 2026-05-24 refinement note, the tracker-vs-reality flag, and **Slice 11** (Tue/Thu cadence).
- **`plan.md`** — added the Slice 11 narrative.

No ADR opened: the "ship manually first" sequencing is reversible (fails the hard-to-reverse bar); ADR-0001 already covers the two-gate pattern.

---

## Open items carried forward (for the PRD / build)

- Implement `render_from_script.py --reuse-shots/--order` (+ narration sanitize, source from DB).
- Assemble the Corti clip (order `3,2,1,0`) → insert `clips` row with `publish_at_utc = now+~45m`.
- Confirm `data/music/` = YouTube Audio Library only → `daily_upload --dry-run` JSON review.
- Slice 11: `upload_weekdays` config + allocator weekday filter + clips-per-day budget tuning (recommend 1/day → 2/week).

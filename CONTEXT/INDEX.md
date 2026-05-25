> **For agents:** Read the relevant phase file(s) before starting work.
> The most recent session handoff is in [`.sessions/INDEX.md`](../.sessions/INDEX.md) (project root).
> Start with `CLAUDE.md` at the project root for the full system overview.

# CONTEXT Index — Media-Agent (Pivot.6)

Tech/AI news YouTube Shorts pipeline. Slices 1–9 complete. **Slice 10 uploaded** (`9lpL8kuLX08`); T+1h Studio checks + T+48h stability gate pending. Slice 11 Tue/Thu cadence code shipped (Issue 14).

## Domain terminology (sharpened)

- **Candidate script** — a row in `scripts` whose 4 shots have all succeeded in `generation_jobs` and whose narration has passed scripter-stage policy. Not yet a `clips` row.
- **Ship-verified** vs **complete** — see two-gate sign-off in review. A slice is *ship-verified* at T+1h (immediate uploader/disclosure path works) and *complete* at T+48h (no delayed CID, stability data clean).
- **AI-gen content** — anything where `clips.content_kind='ai_generated'`. Triggers the Slice 9 uploader branch (`containsSyntheticMedia=true`, AI-disclosure footer, no source/channel attribution).
- **Real-person reference** — naming or visually depicting an identifiable living individual. **Not allowed in scripter shot prompts.**

---

| Phase | File | Status | Last Updated | Summary |
|---|---|---|---|---|
| planning | [phase-planning.md](phase-planning.md) | complete | 2026-05-24 | Niche locked (Tech/AI), 10-slice plan, two-gate sign-off; Slice 10 refined (shot 3 lead, 315¢, reuse-shots, same-day slot) + Slice 11 Tue/Thu cadence added |
| architecture | [phase-architecture.md](phase-architecture.md) | complete | 2026-05-24 | SQLite schema (4 Pivot.6 tables), Pydantic Config sub-models, 50+ DAL helpers, Provider ABC |
| development | [phase-development.md](phase-development.md) | in-progress | 2026-05-24 | Slices 1–9 complete; Slice 10 uploaded (ship gate partial); Issue 11/14 code shipped |
| testing | [phase-testing.md](phase-testing.md) | in-progress | 2026-05-24 | 740+ tests; session added reuse-shots, weekday, aligner CPU fallback tests |
| deployment | [phase-deployment.md](phase-deployment.md) | in-progress | 2026-05-24 | Slice 10 live upload succeeded; OAuth re-authed 2026-05-24 |
| review | [phase-review.md](phase-review.md) | complete | 2026-05-24 | 4-check policy gate, 6-gate quality screen, AI disclosure compliance (Slice 9), pre-flight checklist |

---

## Quick-reference: Current blockers (as of 2026-05-24)

1. ~~DB migration~~ / ~~MP4 assembly~~ / ~~live upload~~ — **DONE** (`youtube_video_id=9lpL8kuLX08`).
2. **T+1h ship gate (HITL)** — Studio: altered-content toggle, public flip at `publishAt`, no CID. API check: footer ✓, `madeForKids=false` ✓; `containsSyntheticMedia` not returned by `videos.list` — verify in Studio UI.
3. **T+48h stability gate (Issue 13)** — starts after T+1h ship-verified; passive 48 h monitoring.
4. **No git repo** in this working copy — push blocked until `git init` + remote configured.

---

## Document update protocol

When a grilling session locks new constraints, update three places:

1. **`progress.md`** — operational plan / checklist for the affected slice.
2. **`CONTEXT/` phase files** — durable constraints, defects, protocols.
3. **`docs/adr/`** — architectural decisions (sparingly).

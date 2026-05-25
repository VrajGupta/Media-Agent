# Phase: review
**Project:** Media-Agent (Pivot.6)
**Status:** complete
**Last updated:** 2026-05-24

## Objective

Quality gate, content policy enforcement, and compliance review for all clips before upload. This phase covers the `policy_gate`, `quality_screen`, and uploader compliance modules — the safety layer that sits between the pipeline output and YouTube upload.

## Key Decisions

- **4-check policy gate** (`policy_gate/evaluator.py`): banlist (short-circuit) → profanity (`better_profanity`) → NSFW (Ollama classifier, fail-soft) → hook_sanity (Ollama 1-5 rater, min score 3). All checks injected as callables — pure, mockable.
- **6-gate quality screen** (`quality_screen/runner.py`): duration → density → confidence → loudness → dedup → relocation. Duration failure aborts remaining checks. Loudness is 3-tier: pass ±0.5 LUFS / warn ±0.5..±1.5 / reject >±1.5 LUFS.
- **Dedup:** pHash Hamming distance + audio fingerprint. pHash-only blocks at Hamming < 8. 90-day lookback.
- **Loudness target:** -14.0 LUFS. ffmpeg loudnorm 2-pass baked into assembler.
- **Policy gate re-check at upload time** — `upload_one_clip()` re-runs policy before `videos.insert`. Catches clips that passed gate days earlier but whose title/narration changed.
- **AI disclosure (Slice 9):** `status.containsSyntheticMedia = true` on every `ai_generated` upload. Description footer appended by `templater.py` AI-gen branch. Failure to set disclosure = hard abort.
- **Compliance constraint: no real people in Kling shot prompts.** Kling generates a synthetic face; if a real person's name is in the prompt, the result is a fake person under a real name — defamation risk.
- **CID bar:** Any Content ID claim = hard fail. Check `logs/alerts.md` at T+1h and T+48h gates.
- **Human review gate (quality layer):** When `human_review: true`, only `status=approved` clips are eligible for upload. User drags from `output/pending/` → `output/approved/` after reviewing quality.

---

## Detailed Compliance Constraints

### 1. No Living Individuals in Prompts
* **Why**: Kling 3.0 generates a synthetic person for any "Person X doing Y" prompt. Shipping a fake person under a real name is defamation-adjacent under YouTube's "altered content depicting real people" policy—even with `containsSyntheticMedia=true` set.
* **Application**: 
  * Scripter prompts (Slice 6) must enforce: *"Do not name specific living individuals (CEOs, researchers, public figures) in shot descriptions. Refer to people by role only (e.g. 'a CEO in a video call', not 'Andreas Cleve in a video call')."*
  * Narration text may name people (factual reporting is fine), but shot prompts must not.
  * Surfaced in 2026-05-23 grill on script `7cb41305` ("Corti's CEO Andreas Cleve in a video call interview..."). Swapping shot 0 ↔ shot 1 was used as a mitigation so the whiteboard frame becomes the thumbnail.

### 2. Music Bed Source Policy: YouTube Audio Library Only
* **Why**: Content ID risk is the single biggest avoidable failure mode for a new channel. YouTube Audio Library tracks are guaranteed CID-safe. Other "royalty-free" sources (Pixabay, freetouse.com) are often registered in CID by third parties, causing claims.
* **Application**:
  * `data/music/` must contain ONLY tracks downloaded directly from YouTube Studio -> Audio Library (filter: "Attribution Required = No").
  * Non-library tracks must be checked via private test upload first.
  * Genre fit: Editorial tech-news visuals require *Cinematic / Calm / Inspirational* mood. Aggressive phonk, hyperpop, or intense electronic genres are banned.

### 3. Always-On AI Disclosure
* **Why & Application**: `compliance.ai_disclosure=true` in `config.yaml` is locked on. Both the description footer and `status.containsSyntheticMedia=true` API flag must execute on every upload. Any failure is a hard ship-blocking bug.

---

## Known Scripter Defects

### 1. qwen2.5:3b Mojibake on Smart-Quotes
* **Symptom**: Narration contains `` (U+FFFD replacement character) where the source article had a smart-quote (U+2019). Example: `Corti's` becomes `Cortis`.
* **Impact**: Edge TTS mispronounces or silent-drops the character, and Whisper renders the literal `` glyph in burned-in subtitles.
* **Workaround**: Sanitize narration before TTS in the assembler/narration stage:
  ```python
  narration = scripts_row["narration"].replace("\uFFFD", "'")
  ```
* **Permanent Fix**: Track encoding detection in `topic_ingest/` (`feedparser` detection) or the Ollama prompt round-trip in Slice 11+.

### 2. qwen2.5:3b Factual Hallucinations on Tech News
* **Symptom**: Local 3B model may cite specific statistics not present in the source article (e.g., claiming Google's new Android CLI "triples app development speed" when the TechCrunch source made no speed claim).
* **Workaround**: Strict human-review of every script before assembly until Slice 11+. Cross-check narration stats against `topics.summary`.
* **Permanent Fix**: Swap to `qwen2.5:7b-instruct` or add a fact-checking verification stage in Slice 11+.

### 3. Weak Hooks
* **Symptom**: Scripter rarely hits the "hook in first 5 words" constraint perfectly, often using 7+ words of setup before hitting the hook.
* **Status**: Quality issue, not a hard defect. Worth few-shot prompt engineering in Slice 11+.

---

## Two-Gate Sign-Off for First-Live Ships

Applies to every first live ship of a new content type (e.g., Slice 10 first AI-gen Short, first 3-clip batch, etc.):

### Gate 1 — Ship gate (`[~]` in progress.md), T+1h
Checks immediate upload path success (blocks downstream slices if failed):
* `videos.insert` succeeded, `youtube_video_id` populated.
* AI disclosure toggle is ON in YouTube Studio + description footer is present.
* Video successfully flipped public at scheduled slot.
* No immediate Content ID claims (any claim is a fail).
* Cost reconciliation matches within ±5% of OpenRouter dashboard.

### Gate 2 — Stability gate (`[x]` in progress.md), T+48h
Runs concurrently in the background (non-blocking):
* `logs/alerts.md` remains clean of failures/reversals for 48 hours.
* Video remains public (no YouTube auto-removal or guidelines strikes).
* Analytics show impressions > 0 (verified algorithm serving).

---

## Cost Reconciliation Protocol

OpenRouter dashboard cost versus internal `generation_jobs.cost_cents` must agree within ±5% per clip.

| Drift | Treatment |
|---|---|
| < 5% | Pass. Normal rounding. |
| 5–20% | Soft fail. Log to `alerts.md`. Ship anyway. Investigate before next clip. |
| > 20% | Hard fail. Ledger isn't reading provider correctly. Ship-block. |

* **Granularity**: Per-clip for first-live; per-week-batch for steady-state.
* **Cadence**: At upload time + one verify at +1h (to allow dashboard to fully settle).

---

## Accomplishments

- [2026-05-09] **Phase 4.5 complete:** policy_gate (4 checks, pure evaluator) implemented and live-verified.
- [2026-05-09] **quality_screen (6 gates)** implemented and live-verified. Loudness 3-tier confirmed working.
- [2026-05-09] **dedup** (pHash + audio fingerprint) implemented. 90-day lookback window.
- [2026-05-22] **Slice 9 compliance refit complete (commit f871df8):** `status.containsSyntheticMedia=true` on all AI-gen uploads. PRD at `docs/prds/slice-9-ai-disclosure.md`. Tests green.
- [2026-05-22] **Uploader templater dual-branch:** `sourced` path (legacy) and `ai_generated` path (Pivot.6) both implemented and tested.
- [2026-05-23] **Slice 10 pre-flight checklist finalized** in CONTEXT.md: mandatory `--dry-run` → JSON review → live send sequence.
- [2026-05-23] **qwen2.5:3b known defects documented** (mojibake, hallucinated stats, weak hooks) — workarounds in place (`sanitize.py`, human-review every script).

## Artifacts

| Artifact | Path | Notes |
|---|---|---|
| Policy gate evaluator | `src/policy_gate/evaluator.py` | Pure; 4 checks; injectable callables |
| Policy gate runner | `src/policy_gate/runner.py` | `gate_one_clip()`, `run_all()` |
| Banlist | `src/policy_gate/banlist.py` | Case-insensitive substring match |
| NSFW check | `src/policy_gate/nsfw.py` | Ollama classifier; fail-soft on infra down |
| Hook sanity | `src/policy_gate/hook_sanity.py` | Ollama 1-5 rater; min 3 to pass |
| Quality screen | `src/quality_screen/runner.py` | 6-gate pipeline; loudness 3-tier |
| Loudness gate | `src/quality_screen/loudness.py` | ±0.5 pass / ±1.5 reject thresholds |
| Dedup gate | `src/quality_screen/dedup.py` | pHash Hamming + audio fingerprint |
| Compliance refit | `src/uploader/templater.py` | `build_description()` AI-gen branch |
| AI disclosure insert | `src/uploader/insert_body.py` | `status.containsSyntheticMedia` field |
| Slice 9 PRD | `docs/prds/slice-9-ai-disclosure.md` | AI disclosure requirement rationale |
| Compliance doc | `CONTEXT/` | Defects, pre-flight checklist, music policy |

## Sessions

- Phase 4.5 policy + quality gates (2026-05-09)
- Slice 9 compliance refit (2026-05-22, commit `f871df8`)
- Slice 10 operational plan + compliance review (2026-05-23)

## Open Items

- `sanitize.py` unit tests not yet written (known gap — covers mojibake fix).
- Hook sanity score threshold (`hook_sanity_min_score: 3`) may need tuning after Slice 10 real-data feedback.
- No automated CID check in pipeline — relies on human checking `logs/alerts.md` at T+1h and T+48h gates.
- Post-Slice-10: consider adding automated T+1h gate check (YouTube API `videos.list` → check `contentDetails.contentRating`).

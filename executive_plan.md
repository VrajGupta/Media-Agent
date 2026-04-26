# Executive Plan v1.2 — YouTube Shorts Repost Automation

> Self-contained brief. v1.2 finalizes the stack as **fully free** per user requirement: Anthropic API removed, replaced with local Ollama (qwen2.5:3b-instruct). Discord webhook removed; review and alerting are filesystem-based. Canonical TZ Asia/Singapore. `human_review` defaulted to `true` for first 2 weeks.

---

## 0a. Changelog from v1.1 → v1.2
- **Removed Anthropic API.** Local Ollama (`qwen2.5:3b-instruct`, q4_K_M ≈ 2 GB VRAM) handles ranking, NSFW classification, and hook-sanity. Stack cost is now **$0/month**.
- **Removed Discord webhook.** Alerts written to `logs/alerts.md` (markdown table). User reads on demand.
- **Filesystem-based human review.** Rendered clips → `output/pending/{YYYY-MM-DD}__{slot_HHMM}__{title_slug}.mp4`. User drags approved files → `output/approved/`. Daily uploader pulls from `output/approved/` while `human_review=true`, otherwise from `output/pending/` directly.
- **`human_review = true`** default (was `false`) for the first 2 weeks per user instruction.
- **Canonical timezone:** `Asia/Singapore`.

## 0b. Changelog from v1.0 → v1.1
- Elevated **policy/legal risk**: added a `policy_gate/` module that blocks clips by banned-topic, profanity, NSFW, and metadata-misleading checks before render and again before upload. `human_review` toggle in config (default `false` v1, recommended `true` for first 2 weeks).
- Hardened the **mostReplayed dependency**: defined explicit fallback validation — if heatmap is missing for >30% of pipeline videos in a run, the run flips to "transcript-only" mode and emits a warning; fallback quality is measured via reviewer-spotcheck on first 20 clips.
- Concrete **virality formula** with normalization across niches.
- Added **per-endpoint quota ledger** (`quota_ledger/`) — every API call increments a today-bucket counter; weekly_run aborts the discovery loop if today's projected usage > 8,000 units.
- Specified **time semantics**: canonical TZ = `Asia/Singapore` (configurable), DST handled via `zoneinfo`, missed-slot retry rules enumerated.
- Added **content-quality screens**: min speech density, subtitle confidence floor, perceptual-hash duplicate suppression across the last 90 days.
- Added **cleanup & retention** policy with explicit TTLs.
- Replaced "face/center-cropped" with **center crop + optional subject tracking** (subject tracking deferred to v1.1 stretch — it requires a face/saliency model not in v1 scope).
- Added **observability**: file-based alerts log on run failure, quota near-cap, and upload rejection.
- Added **acceptance criteria** for every phase (go / no-go gates).
- Added **dry-run mode** to uploader (`--dry-run` writes the would-be insert body to disk, makes no API call).
- Acknowledged that **`search.list` has no English-audio filter** — language detection happens post-download via Whisper.

---

## 1. Objective
Build a fully autonomous Python agent that operates a single YouTube channel which republishes other people's long-form content as engaging vertical Shorts ("brainrot" split-screen format with burned word-by-word subtitles). Target 1–2 weeks to v1.

## 2. Product Spec
| Aspect | Decision |
|---|---|
| Platforms | YouTube Shorts only (v1). |
| Source content | Third-party long-form YouTube videos, transformatively reformatted. |
| Clip length | 30–60 s, sentence-aligned. |
| Visual format | 1080×1920. Top half (1080×960): source video, **center-cropped** (subject-tracking deferred). Bottom half (1080×960): looping background gameplay. |
| Subtitles | ASS karaoke style, 1–2 words on-screen, white + black stroke, yellow active-word highlight. |
| Audio | Source full, gameplay muted, loudnorm to -14 LUFS. |
| Cadence | Default 4 clips/day × 7 days = 28/week. Configurable. |
| Approval | `human_review: true` default (locked for first 2 weeks). Mechanism: drag clip from `output/pending/` to `output/approved/` in Explorer. |
| Niche keywords (v1) | Joe Rogan, stoicism, NBA highlights — rotated. |

## 3. Operational Model — Path B (hybrid)

### Why
YouTube Data API v3 default quota: **10,000 units/day**; `videos.insert` = 1,600 units → ~6 inserts/day max. Single weekly batch cannot upload 28 clips. Quota-audit deferred. Therefore:

- **Weekly heavy run** (~1 h, Sunday 02:00 local, Windows Task Scheduler) — discovery → download → selector → policy gate (pre-render) → editor → slot planner.
- **Daily upload run** (~5 min, daily 09:00 local, Windows Task Scheduler) — policy gate (pre-upload) → uploader with `status.publishAt`.
- No long-running daemon. SQLite state. All stages idempotent.

### Quota math (per day; per endpoint)
| Endpoint | Cost | Calls/run | Units |
|---|---|---|---|
| `videos.insert` | 1,600 | 4 | 6,400 |
| `search.list` (weekly only) | 100 | ≤16 | 1,600 (weekly) |
| `videos.list` (weekly only) | 1 | ≤200 | 200 (weekly) |
| **Daily worst case** | | | **6,400** |
| **Sunday worst case** | | | **8,200** |

Hard ceiling enforced by `quota_ledger`: abort if next call would push today's total > 9,000.

### Time semantics
- Canonical timezone: `Asia/Singapore` (config: `timezone:`). All scheduling reasoned in this TZ; Python `zoneinfo` for DST correctness.
- `publish_at` stored UTC; converted on render/upload.
- **Missed slot policy:** if `daily_upload.py` runs at 09:00 and finds clips with `publish_at` in the past (PC was off, run failed), it batches all stale slots into the next future slot rather than asking YouTube to publish in the past (which YouTube rejects). Logged as `recovered_slot`.
- **Future-too-near rule:** YouTube rejects `publishAt < now + ~15 min`. Uploader pads any slot < `now + 20 min` to `now + 20 min`.

## 4. Architecture

```
[Win Task Scheduler — weekly Sunday 02:00]
  └─ weekly_run.py:
       discovery (quota_ledger) → downloader → lang_detect (Whisper)
         → selector (transcript + heatmap-or-fallback + Ollama qwen2.5:3b)
         → policy_gate (banned topics, NSFW text, misleading hooks)
         → editor (ffmpeg + NVENC + ASS karaoke)
         → quality_screen (speech density, sub confidence, dup-hash)
         → slot_planner (publish_at in canonical TZ)
         → output/pending/*.mp4 + clips.publish_at filled
       └─ logs/alerts.md row: "weekly run finished, queue=N, dropped=M"

[Win Task Scheduler — daily 09:00]
  └─ daily_upload.py:
       policy_gate (re-check, in case banlist changed)
         → uploader (videos.insert + publishAt, quota_ledger)
         → mark uploaded
       └─ logs/alerts.md row on quota near-cap, reject, or run failure
                                ↑
                     state.db (SQLite — single source of truth)
```

### Modules (delta from v1.0 in **bold**)
1. **discovery/** — `search.list` + `videos.list`, ranks by virality formula (§5.1). Filter duration ≥ 5 min. *English filter happens post-download (no API support).*
2. **downloader/** — `yt-dlp`, idempotent, caches `data/raw/{video_id}.mp4`.
3. **lang_detect/** *(new)* — first 60 s through Whisper; if detected language ≠ `en` with confidence ≥ 0.7, mark `rejected_language`.
4. **selector/** — Whisper large-v3 int8_float16 CUDA; heatmap fetcher with **fallback validation** (§5.2); Ollama (`qwen2.5:3b-instruct`) ranker, JSON-mode, fixed rubric prefix for kv-cache reuse.
5. **policy_gate/** *(new)* — runs twice (post-select and pre-upload). Checks: banlist substring match (configurable), profanity scoring (`better-profanity`), NSFW text classifier on transcript (Ollama zero-shot), hook-vs-content sanity check (Ollama, "does this hook accurately represent the clip?"). Failure → `rejected_policy`.
6. **editor/** — single-pass ffmpeg: cut → top center-crop → bottom gameplay seek → vstack → ASS burn → loudnorm → `h264_nvenc`.
7. **quality_screen/** *(new)* — speech_density = words / clip_seconds ≥ 1.5; mean Whisper word-conf ≥ 0.6; perceptual hash (pHash on 5 evenly-spaced frames + audio fingerprint) compared against last-90-days uploaded set. Failure → `rejected_quality`.
8. **subtitles/** — Whisper word stamps → ASS karaoke.
9. **slot_planner/** *(new)* — assigns `publish_at` evenly across `days_per_run` days at configured `upload_slots: ["09:00","13:00","17:00","21:00"]`. Stored UTC.
10. **uploader/** — `videos.insert` resumable, `status.privacyStatus=private`, `status.publishAt`. **`--dry-run` mode** dumps insert body to JSON file, no API call. Quota guard via ledger.
11. **quota_ledger/** *(new)* — `quota_usage(date, endpoint, units)` table. Pre-flight check before every billed call.
12. **retention/** *(new)* — runs at end of `weekly_run`. Deletes `data/raw/*.mp4` older than 14 days, `output/pending/*.mp4` after `uploaded` is confirmed for ≥7 days. Vacuums SQLite monthly.
13. **observability/** *(new)* — `loguru` to `logs/agent.log` + append-only `logs/alerts.md` for: run start/finish, run failure, quota > 80% used, upload rejected, missed-slot recovery.
14. **orchestrator/** — `weekly_run.py`, `daily_upload.py`, `bootstrap.py`, plus `dry_run.py` (full pipeline with uploader stubbed).
15. **state/** — SQLite. Tables: `videos`, `clips` (`publish_at_utc`, `rejection_reason`), `uploads`, `runs`, `gameplay_cursor`, `quota_usage`, `dup_hashes`.

## 5. Concrete Definitions

### 5.1 Virality formula
For each candidate video v with views V, age in hours A, likes L, comments C, channel-niche median views M_n:

```
recency_factor   = V / max(A, 24)
engagement_rate  = (L + 4*C) / max(V, 1)
niche_normalized = V / max(M_n, 1)              # so niches with smaller audiences aren't unfairly punished
virality_score   = log10(recency_factor + 1)
                 * (0.5 + min(engagement_rate * 50, 1.5))
                 * log10(niche_normalized + 1)
```
Threshold: `virality_score ≥ 1.0` to enter selection. M_n is rolling 30-day median, recomputed weekly.

### 5.2 mostReplayed fallback validation
- Per run, count videos with successful heatmap fetch.
- If `heatmap_hit_rate < 70%`, run continues but appends a warning row to `logs/alerts.md` and tags clips selected without heatmap as `selection_method='transcript_only'`.
- Reviewer (manual, first 2 weeks) spot-checks 5 transcript-only clips and 5 heatmap-aided clips per week and rates engagement-fit 1–5. If gap ≤ 0.5, fallback validated; if > 1.0, escalate to add a second LLM pass or weight transcript scoring more heavily.

### 5.3 Content-quality screens (all must pass)
- `speech_density ≥ 1.5 words/sec`
- `mean(word_conf) ≥ 0.6` over the clip window
- `pHash distance ≥ 8` from any clip uploaded in last 90 days
- audio fingerprint Hamming distance ≥ threshold from last-90-days set
- clip duration in [25, 65] s after final trim

## 6. Acceptance Criteria (per phase)

| Phase | Pass condition |
|---|---|
| 0 — Env | `python -m src.bootstrap --check` returns green: ffmpeg + NVENC + CUDA + Whisper load + YT OAuth + Ollama reachable + qwen2.5:3b pulled all OK. |
| 1 — Discovery | Run on each of the 3 keywords returns ≥ 30 candidates; virality scores within expected ranges; quota ledger shows ≤ 1,800 units used. |
| 2 — Downloader | Re-running on the same set is idempotent (zero re-downloads); disk-budget eviction triggers at config threshold. |
| 3 — Selector | First 10 clips reviewed manually: ≥ 7 rated "watchable hook" by user. Heatmap fallback path also produces ≥ 6/10. |
| 4 — Editor | Output is valid 1080×1920 H.264, ≤ 60 s, audio at -14 ±0.5 LUFS, subtitles aligned ≤ 50 ms drift. |
| 4.5 — Policy + Quality | Banned-topic test inputs all caught; legitimate clips all pass; duplicate-hash collision test produces zero false positives on 20 hand-picked distinct clips. |
| 5 — Uploader | `--dry-run` produces a valid insert body (offline lint); one real upload to private test channel publishes at exactly the requested `publishAt` in canonical TZ. |
| 6 — Orchestrator | Full weekly_run produces 28 ready clips; daily_upload publishes 4/day for 7 days with no missed slots when PC is online; missed-slot recovery exercised by deliberately skipping a day. |
| 7 — Hardening | Logs rotate; `logs/alerts.md` receives all expected alert rows; cleanup deletes the right files; running `weekly_run` twice in a row is a no-op. |

## 7. Stack & Rationale
*(see `skills.md` for full table)*. v1.2 stack: yt-dlp · faster-whisper (CUDA) · ffmpeg+NVENC · **Ollama qwen2.5:3b-instruct** (replaces Anthropic) · imagehash · chromaprint/acoustid-tools · better-profanity · loguru · tenacity · zoneinfo · sqlite3 · google-api-python-client.

## 8. Hardware (locked)
Windows 11 PC: i9-11900H · 32 GB DDR4 · 1 TB SSD · RTX 3070 laptop GPU (8 GB VRAM). Code developed on a Mac, transferred to the PC.

## 9. Cost Model
| Line item | Per clip | Per week (28) |
|---|---|---|
| yt-dlp / Whisper / ffmpeg / YT API | $0 | $0 |
| Ollama (local) | $0 | $0 |
| **Total** | **< $0.01** | **< $1/month** |

## 10. Phased Build (10 days)
- **Phase 0 (Day 1):** Env, ffmpeg+NVENC, CUDA/cuDNN, GCP project, OAuth, Ollama install + `qwen2.5:3b-instruct` pull, project skeleton, gameplay files staged. Acceptance §6.
- **Phase 1 (Day 2):** SQLite schema (incl. `quota_usage`, `dup_hashes`), discovery + virality formula, **quota_ledger**.
- **Phase 2 (Day 2–3):** yt-dlp downloader, idempotency, retention sketch.
- **Phase 3 (Day 3–5):** lang_detect, Whisper transcriber (CUDA), heatmap + fallback validation, Claude ranker.
- **Phase 4 (Day 5–7):** ASS karaoke generator, ffmpeg single-pass render, gameplay rotation.
- **Phase 4.5 (Day 7):** **policy_gate** + **quality_screen** + duplicate hashing.
- **Phase 5 (Day 7–8):** Uploader with `publishAt`, **dry-run mode**, quota ledger integration. First successful scheduled upload.
- **Phase 6 (Day 8–9):** slot_planner with TZ semantics, weekly_run, daily_upload (incl. missed-slot recovery), bootstrap, Task Scheduler XMLs.
- **Phase 7 (Day 9–10):** loguru, tenacity, `logs/alerts.md`, retention/cleanup, README, run summaries.
- **Phase 8 (deferred):** subject tracking (face/saliency crop), thumbnail gen, A/B titles, TikTok/IG, web dashboard, request quota increase.

## 11. Risks & Mitigations (v1.1)
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Copyright strikes / channel termination** | High | Channel loss | Treat the channel as expendable. Run on a dedicated Google account. Keep clips ≤ 60 s and visually transformed (split-screen + burned subs). Source attribution in description. **Recommend `human_review=true` for first 2 weeks.** Watch for first claim — if it lands, narrow the niche to safer keywords. |
| **Misleading title/hook → policy violation** | Medium | Strike or removal | `policy_gate` runs an Ollama "does this hook accurately summarize the clip?" check; failures rejected. |
| **mostReplayed missing** | Medium | Selection quality drop | Fallback validation (§5.2) measures the gap; escalate ranker if gap > 1.0/5. |
| **Quota over-spend on Sunday** | Medium | Run abort mid-pipeline | `quota_ledger` aborts before the offending call; partial state resumes next run. |
| **Missed publish slots (PC off)** | Medium | Schedule drift | Recovery rule batches stale slots into next future slot. |
| **Whisper VRAM pressure** | Low | OOM / slowdown | int8_float16 fits with headroom; fallback to `medium.en`. |
| **Auto-Shorts detection inconsistent** | Low | Shows as regular video | 9:16, ≤60 s, `#Shorts` in title + description. |
| **Duplicate uploads / self-similarity** | Medium | Channel looks low-effort | pHash + audio fingerprint dedup on 90-day window. |
| **OAuth refresh token revoked** | Low | Uploads fail | Detect, append to `logs/alerts.md`, manual re-auth one command. |
| **NSFW/banned topic slipping through** | Low | Strike | `policy_gate` banlist + profanity score + LLM hook check. |

## 12. Cleanup & Retention
- `data/raw/*.mp4` — delete 14 days after download or after all derived clips are `uploaded`, whichever later.
- `data/transcripts/*.json` — keep 90 days.
- `output/pending/*.mp4` — delete 7 days after `uploaded` confirmed.
- `logs/*.log` — `loguru` rotation, 30-day retention.
- `dup_hashes` table — prune entries > 90 days old.
- SQLite `VACUUM` monthly via the retention module.

## 13. Observability
- `loguru` → `logs/agent.log` (rotated daily, 30-day retention).
- `logs/alerts.md` (markdown table, append-only) for:
  - Weekly run finished (queue depth, dropped count).
  - Quota usage > 80% in any day.
  - Upload rejected by YouTube (with reason).
  - Run failure / unhandled exception.
  - Missed-slot recovery triggered.
- Filesystem signal: `output/pending/` and `output/approved/` file counts visible in Explorer.
- Per-run summary appended to `logs/runs.md` (markdown table: date, keyword, candidates, rendered, dropped, uploaded, quota_used).

## 14. Open Questions for Reviewers
1. Is `policy_gate` strong enough for autonomous operation, or is a human approval step required for v1?
2. Is the virality formula (§5.1) defensible across the 3 chosen niches, or should it be niche-specific from day one?
3. Is the missed-slot batching rule the right behavior, or should missed slots be silently dropped to avoid posting bursts?
4. Is `imagehash` + audio fingerprint sufficient dedup, or do we need a learned embedding model?
5. Is filesystem-only observability (`logs/alerts.md` + folder counts) sufficient given the user is fine reading on demand, or would the absence of push notifications cause delayed reaction to channel-strike events?
6. Is "channel as expendable" an acceptable copyright posture, or should v1 ship with `human_review=true` hard-coded and only flip after the first 50 clips?
7. Should `lang_detect` reject non-English content, or should we widen the channel scope to include other languages from day one?

## 15. Files in this repo
- `executive_plan.md` — this file (v1.1).
- `plan.md` — phase-by-phase build plan.
- `agents.md` — module responsibilities + data flow.
- `skills.md` — libraries and rationale.
- `claude.md` — context primer.
- `progress.md` — task checklist.

No source code yet. Pre-implementation review phase.

# Media Agent

Autonomous YouTube Shorts repost pipeline. See `executive_plan.md` for the full v1.2 brief.

Stack: Python 3.11+ · ffmpeg+NVENC · faster-whisper (CUDA) · Ollama (qwen2.5:3b-instruct) · YouTube Data API v3. **Cost: $0/month.**

## One-time PC setup

1. **Install Python 3.11+**, ffmpeg with NVENC support, and CUDA 12.x + cuDNN 9 runtime.
2. **Install Ollama** from <https://ollama.com/download>, then `ollama pull qwen2.5:3b-instruct`.
3. Create a Google Cloud project, enable YouTube Data API v3, create an **OAuth 2.0 Desktop client**, download the JSON, save as `data/client_secret.json`.
4. Drop a few royalty-free background tracks (phonk / lo-fi / etc.) into `data/music/` as `.mp3 / .m4a / .wav / .flac / .ogg`. The editor picks one deterministically per clip (sha1 of `clip_id` modulo).
5. ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env
   ```
6. ```
   python -m src.bootstrap --init-db
   python -m src.bootstrap --check
   ```
   All checks must be `OK` before continuing past Phase 0.

## Layout

| Path | Purpose |
| --- | --- |
| `config.yaml` | All tunables (cadence, keywords, models, retention, paths). |
| `data/state.db` | SQLite — single source of truth for pipeline state. |
| `data/raw/*.mp4` | Downloaded long-form sources (14-day TTL). |
| `data/transcripts/*.json` | Whisper / caption-cache output, cached. |
| `data/music/*.{mp3,m4a,wav,flac,ogg}` | User-supplied royalty-free background tracks (gitignored; pool is local). |
| `output/pending/` | Rendered clips awaiting review (when `human_review=true`) or upload (when `false`). |
| `output/approved/` | User-approved clips eligible for upload. |
| `output/rejected/` | User-rejected pile (30-day TTL). |
| `output/dry_run/*.json` | Uploader `--dry-run` output; no API call. |
| `logs/agent.log` | Rotated daily, 30-day retention. |
| `logs/alerts.md` | Markdown table of alerts (run failure, quota near-cap, etc.). |
| `logs/runs.md` | Per-run summary table. |

## Human review (first 2 weeks)

`config.yaml` has `human_review: true`. Workflow:

1. `weekly_run.py` renders 28 clips to `output/pending/{YYYY-MM-DD}__{HHMM}__{slug}.mp4`.
2. You review in Explorer. Drag approved clips to `output/approved/`. Drag rejects to `output/rejected/`.
3. `daily_upload.py` (Windows Task Scheduler, daily 09:00 SGT) reads `output/approved/` and uploads with `publishAt`.
4. After 2 weeks, flip `human_review: false`; uploader will then read `output/pending/` directly.

## Scheduling

Windows Task Scheduler runs (`scripts/weekly_run.xml`, `scripts/daily_upload.xml`):

- **Weekly:** Sunday 02:00 SGT — heavy GPU work.
- **Daily:** every day 09:00 SGT — uploads under quota cap (4 uploads × 1,600 = 6,400 units).

### Task Scheduler templates (LOCAL — edit before importing)

The XMLs in `scripts/` are templates for **this** machine's paths
(`C:\Users\cryptix\Documents\Media-Agent-main`). If you check the project
out elsewhere, edit `<Command>` and `<WorkingDirectory>` in both XML files
before `schtasks /Create` to match your venv and worktree paths.

Import on this machine:

```powershell
schtasks /Create /XML scripts\weekly_run.xml   /TN MediaAgentWeekly
schtasks /Create /XML scripts\daily_upload.xml /TN MediaAgentDailyUpload
```

Run-once for verification:

```powershell
schtasks /Run /TN MediaAgentWeekly
schtasks /Run /TN MediaAgentDailyUpload
```

Remove:

```powershell
schtasks /Delete /TN MediaAgentWeekly       /F
schtasks /Delete /TN MediaAgentDailyUpload  /F
```

**Concurrent-invocation safety (Phase 7).** `weekly_run`, `daily_upload`,
and any manual invocation of either share a single advisory file lock at
`data/.weekly_run.lock` (Windows `msvcrt.locking`). A second invocation
while the first is mid-run exits with code 2 and a `lock_held` row in
`logs/alerts.md` — never a queue, never an overlap.

## Requesting a YouTube quota increase

The default YouTube Data API v3 daily quota is 10,000 units, which caps
this project at ~6 uploads/day (1,600 units/insert + ~400 units of search
+ enrichment overhead per `weekly_run`). To upload more than ~6/day,
request a quota increase:

1. Cloud Console → APIs & Services → YouTube Data API v3 → Quotas.
2. Click the pencil icon on the **Queries per day** row → **Apply for
   higher quota**.
3. The form requires:
   - Channel URL.
   - Description of how the API will be used.
   - Privacy policy URL.
   - An audit form link (Google sends this after the initial request —
     it covers content moderation, takedowns, copyright, acceptable use).
4. Approval typically takes 2–4 weeks. Until approved, the
   `quota_ledger` keeps daily usage under 9,000 units (the `youtube_quota_ceiling_units`
   guard in `config.yaml`).

Once approved, `daily_upload`'s role collapses into `weekly_run` — no
longer needed to spread uploads across days to fit under the 10k cap.

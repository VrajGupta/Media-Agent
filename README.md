# Media Agent

Autonomous YouTube Shorts repost pipeline. See `executive_plan.md` for the full v1.2 brief.

Stack: Python 3.11+ · ffmpeg+NVENC · faster-whisper (CUDA) · Ollama (qwen2.5:3b-instruct) · YouTube Data API v3. **Cost: $0/month.**

## One-time PC setup

1. **Install Python 3.11+**, ffmpeg with NVENC support, and CUDA 12.x + cuDNN 9 runtime.
2. **Install Ollama** from <https://ollama.com/download>, then `ollama pull qwen2.5:3b-instruct`.
3. Create a Google Cloud project, enable YouTube Data API v3, create an **OAuth 2.0 Desktop client**, download the JSON, save as `data/client_secret.json`.
4. Acquire 3 background gameplay videos (~10 min each) and place them at `data/gameplay/{subway,minecraft,gta}.mp4`.
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
| `data/transcripts/*.json` | Whisper output, cached. |
| `data/gameplay/*.mp4` | User-supplied background pool. |
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

## Future quota-increase audit

YouTube Data API default quota is 10,000 units/day → ~6 inserts/day cap. If you submit the API Services audit and Google grants more, the daily upload run can collapse into the weekly one. Form lives in Cloud Console → APIs & Services → YouTube Data API v3 → Quotas → "Apply for higher quota."
# Media-Agent

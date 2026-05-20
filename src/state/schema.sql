-- Media Agent state schema. Single SQLite file at data/state.db.
-- Stages communicate exclusively through these tables; runs are idempotent.

CREATE TABLE IF NOT EXISTS videos (
    video_id           TEXT PRIMARY KEY,
    title              TEXT NOT NULL,
    channel            TEXT NOT NULL,
    duration_seconds   INTEGER NOT NULL,
    views              INTEGER NOT NULL,
    likes              INTEGER NOT NULL DEFAULT 0,
    comments           INTEGER NOT NULL DEFAULT 0,
    published_at       TEXT NOT NULL,                -- ISO 8601 UTC
    keyword            TEXT NOT NULL,
    virality_score     REAL NOT NULL,
    status             TEXT NOT NULL,                -- discovered|downloaded|lang_ok|transcribed|selected|rejected_language|rejected_format|rejected_download|done
                                                     -- Phase 3 transitions: lang_ok -> transcribed (after atomic transcript cache write)
                                                     --                  -> selected   (after clip rows inserted in repo.tx())
    rejection_reason   TEXT,
    discovered_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_keyword ON videos(keyword);

CREATE TABLE IF NOT EXISTS clips (
    clip_id            TEXT PRIMARY KEY,             -- {video_id}_{start_s}_{end_s}
    video_id           TEXT REFERENCES videos(video_id),  -- nullable: ai_generated clips have no source video
    start_s            REAL NOT NULL,
    end_s              REAL NOT NULL,
    hook               TEXT NOT NULL,
    suggested_title    TEXT NOT NULL,
    title_slug         TEXT,
    selection_method   TEXT NOT NULL,                -- heatmap_aided|transcript_only|ai_generated
    publish_at_utc     TEXT,                         -- ISO 8601 UTC; filled by slot_planner
    publish_slot_local TEXT,                         -- e.g. 2026-04-25 09:00 (canonical TZ)
    output_path        TEXT,                         -- path under output/pending or output/approved
    youtube_video_id   TEXT,
    content_kind       TEXT NOT NULL DEFAULT 'sourced',  -- sourced|ai_generated
    script_id          TEXT,                         -- FK to scripts.script_id (ai_generated clips only)
    status             TEXT NOT NULL,                -- selected|policy_pass|rejected_policy|rendered|rejected_render|quality_pass|rejected_quality|approved|uploaded
                                                     -- Phase 4 transitions: policy_pass -> rendered (file lives at output_path; title_slug filled)
                                                     --                  -> rejected_render (irrecoverable: source mp4 missing/unreadable)
                                                     -- Phase 4.5 transitions: selected -> policy_pass | rejected_policy (post-select gate; clip-window text)
                                                     --                    rendered -> quality_pass | rejected_quality (post-render screen; rejected file moved to output/rejected/)
                                                     -- Pivot.6 additions: ai_generated clips arrive at 'selected' via scripter
    rejection_reason   TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS idx_clips_video_id ON clips(video_id);
CREATE INDEX IF NOT EXISTS idx_clips_publish_at_utc ON clips(publish_at_utc);

CREATE TABLE IF NOT EXISTS uploads (
    clip_id            TEXT PRIMARY KEY REFERENCES clips(clip_id),
    youtube_video_id   TEXT NOT NULL,
    publish_at_utc     TEXT NOT NULL,
    uploaded_at        TEXT NOT NULL DEFAULT (datetime('now')),
    quota_units_used   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind               TEXT NOT NULL,                -- weekly|daily|bootstrap
    started_at         TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at        TEXT,
    success            INTEGER,                      -- 0/1
    summary_json       TEXT
);

-- Phase 7: gameplay_cursor + gameplay_pointer were retained as no-op tables
-- after Pivot.3 dropped split-screen / gameplay-rotation. Phase 7 removes the
-- DDL outright since no live runtime code touches them. Populated DBs from
-- prior phases are migrated by `python -m scripts.drop_gameplay_tables`.

CREATE TABLE IF NOT EXISTS quota_usage (
    date               TEXT NOT NULL,                -- YYYY-MM-DD in UTC
    endpoint           TEXT NOT NULL,                -- search.list|videos.list|videos.insert|openrouter
    units              INTEGER NOT NULL,
    provider           TEXT NOT NULL DEFAULT 'youtube',  -- youtube|openrouter
    recorded_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_quota_date ON quota_usage(date);

CREATE TABLE IF NOT EXISTS dup_hashes (
    clip_id            TEXT NOT NULL REFERENCES clips(clip_id),
    phash              TEXT NOT NULL,
    audio_fp           TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (clip_id, phash)
);
CREATE INDEX IF NOT EXISTS idx_dup_hashes_created_at ON dup_hashes(created_at);

CREATE TABLE IF NOT EXISTS niche_baselines (
    -- rolling 30-day median view count per keyword, recomputed weekly.
    keyword            TEXT PRIMARY KEY,
    median_views       INTEGER NOT NULL,
    sample_size        INTEGER NOT NULL,
    computed_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS discovery_attempts (
    -- one row per keyword; outcome-independent (zero-survivor runs still write).
    -- Cooldown comparison is performed in SQL via datetime('now', '-N hours').
    keyword            TEXT PRIMARY KEY,
    last_attempted_at  TEXT NOT NULL,                -- naive UTC string from datetime('now')
    last_inspected     INTEGER NOT NULL,
    last_inserted      INTEGER NOT NULL
);

-- ============================================================
-- Pivot.6: automated topic-to-script pipeline tables
-- ============================================================

CREATE TABLE IF NOT EXISTS topics (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    url                TEXT NOT NULL,
    title              TEXT NOT NULL,
    summary            TEXT,
    source_feed        TEXT NOT NULL,
    fetched_at         TEXT NOT NULL,               -- ISO Z
    published_at       TEXT,                        -- ISO Z; from RSS pubDate; falls back to fetched_at
    status             TEXT NOT NULL DEFAULT 'unscripted',  -- unscripted|scored|scripted|expired
    topic_score_json   TEXT,                        -- {novelty, specificity, tension, weighted_score, reason}
    weighted_score     REAL,                        -- denormalised for sorting
    category           TEXT                         -- one of scripter.categories
);
CREATE INDEX IF NOT EXISTS idx_topics_status     ON topics(status);
CREATE INDEX IF NOT EXISTS idx_topics_fetched_at ON topics(fetched_at);

CREATE TABLE IF NOT EXISTS seen_topics (
    url_hash           TEXT PRIMARY KEY,            -- SHA-256 hex of normalised URL
    title_normalized   TEXT NOT NULL,               -- lowercase + punct-stripped + stopword-removed
    first_seen_at      TEXT NOT NULL                -- ISO Z
);

CREATE TABLE IF NOT EXISTS scripts (
    script_id          TEXT PRIMARY KEY,
    topic_id           INTEGER NOT NULL REFERENCES topics(id),
    title              TEXT NOT NULL,
    narration          TEXT NOT NULL,
    shots_json         TEXT NOT NULL,               -- JSON array of {index, prompt, duration_s}
    style_suffix       TEXT NOT NULL,
    ollama_model       TEXT NOT NULL,
    topic_score_json   TEXT,                        -- copy from topics.topic_score_json at generation time
    category           TEXT,
    quality_score_json TEXT,                        -- {hook_execution, pacing, payoff, reason}
    quality_score      REAL,                        -- denormalised weighted score for sorting
    rejection_reason   TEXT,
    created_at         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending'  -- pending|scripted|rejected_policy|selected_for_render|failed
);
CREATE INDEX IF NOT EXISTS idx_scripts_status   ON scripts(status);
CREATE INDEX IF NOT EXISTS idx_scripts_topic_id ON scripts(topic_id);

CREATE TABLE IF NOT EXISTS generation_jobs (
    job_id             TEXT PRIMARY KEY,
    script_id          TEXT NOT NULL REFERENCES scripts(script_id),
    shot_index         INTEGER NOT NULL,
    provider           TEXT NOT NULL,               -- openrouter_kling etc.
    prompt             TEXT NOT NULL,
    duration_s         INTEGER NOT NULL,
    status             TEXT NOT NULL,               -- pending|submitted|succeeded|failed
    external_id        TEXT,
    output_path        TEXT,
    cost_cents         INTEGER,
    submitted_at       TEXT,
    completed_at       TEXT,
    error              TEXT
);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_script_id ON generation_jobs(script_id);

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
    status             TEXT NOT NULL,                -- discovered|downloaded|transcribed|selected|rejected_language|done
    rejection_reason   TEXT,
    discovered_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_keyword ON videos(keyword);

CREATE TABLE IF NOT EXISTS clips (
    clip_id            TEXT PRIMARY KEY,             -- {video_id}_{start_s}_{end_s}
    video_id           TEXT NOT NULL REFERENCES videos(video_id),
    start_s            REAL NOT NULL,
    end_s              REAL NOT NULL,
    hook               TEXT NOT NULL,
    suggested_title    TEXT NOT NULL,
    title_slug         TEXT,
    selection_method   TEXT NOT NULL,                -- heatmap_aided|transcript_only
    publish_at_utc     TEXT,                         -- ISO 8601 UTC; filled by slot_planner
    publish_slot_local TEXT,                         -- e.g. 2026-04-25 09:00 (canonical TZ)
    output_path        TEXT,                         -- path under output/pending or output/approved
    youtube_video_id   TEXT,
    status             TEXT NOT NULL,                -- selected|rejected_policy|rendered|rejected_quality|approved|uploaded
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

CREATE TABLE IF NOT EXISTS gameplay_cursor (
    file_name          TEXT PRIMARY KEY,
    last_offset_s      REAL NOT NULL DEFAULT 0,
    file_duration_s    REAL,
    last_used_at       TEXT
);

CREATE TABLE IF NOT EXISTS gameplay_pointer (
    -- single-row table: which file is next in the round-robin
    id                 INTEGER PRIMARY KEY CHECK (id = 1),
    next_index         INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO gameplay_pointer (id, next_index) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS quota_usage (
    date               TEXT NOT NULL,                -- YYYY-MM-DD in UTC
    endpoint           TEXT NOT NULL,                -- search.list|videos.list|videos.insert
    units              INTEGER NOT NULL,
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

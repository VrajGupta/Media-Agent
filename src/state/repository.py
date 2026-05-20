from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_FILE.read_text()
    conn.executescript(sql)


class Repository:
    """Thin DAL. Each stage uses the methods relevant to it; no ORM."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def tx(self) -> Iterator["Repository"]:
        """Transaction context. Yields repo itself — callers use repo methods inside."""
        try:
            self.conn.execute("BEGIN")
            yield self
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # ---- videos ----

    def upsert_video(self, **fields) -> None:
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        update_clause = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "video_id")
        self.conn.execute(
            f"INSERT INTO videos ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(video_id) DO UPDATE SET {update_clause}, updated_at=datetime('now')",
            fields,
        )

    def set_video_status(self, video_id: str, status: str, reason: str | None = None) -> None:
        self.conn.execute(
            "UPDATE videos SET status=?, rejection_reason=?, updated_at=datetime('now') WHERE video_id=?",
            (status, reason, video_id),
        )

    def videos_by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM videos WHERE status=?", (status,)).fetchall()

    def videos_with_statuses(self, statuses: list[str]) -> list[sqlite3.Row]:
        if not statuses:
            return []
        placeholders = ",".join("?" * len(statuses))
        return self.conn.execute(
            f"SELECT * FROM videos WHERE status IN ({placeholders})",
            tuple(statuses),
        ).fetchall()

    def get_video(self, video_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM videos WHERE video_id=?", (video_id,)
        ).fetchone()

    def videos_for_download(self) -> list[sqlite3.Row]:
        """Discovered candidates ordered for the downloader.

        Highest virality score first so the best material lands when budget is tight.
        Stable secondary order (`video_id ASC`) for deterministic reruns.
        """
        return self.conn.execute(
            "SELECT * FROM videos WHERE status='discovered' "
            "ORDER BY virality_score DESC, video_id ASC"
        ).fetchall()

    def evictable_video_ids(self) -> list[str]:
        """Video IDs whose every derived clip is uploaded; oldest first.

        Excludes videos with zero clips — we can't safely delete a source whose
        derivatives haven't been generated yet, even if status='downloaded'.
        """
        rows = self.conn.execute(
            """
            SELECT v.video_id FROM videos v
            WHERE EXISTS (SELECT 1 FROM clips c WHERE c.video_id = v.video_id)
              AND NOT EXISTS (
                  SELECT 1 FROM clips c
                  WHERE c.video_id = v.video_id AND c.status != 'uploaded'
              )
            ORDER BY v.updated_at ASC
            """
        ).fetchall()
        return [r["video_id"] for r in rows]

    def is_raw_evictable(self, video_id: str) -> bool:
        """Single-method safety check: ≥1 clip AND all clips uploaded.

        Critically returns False for videos with zero clips so a stray call site
        can't accidentally delete a source whose derivatives haven't been made.
        """
        row = self.conn.execute(
            """
            SELECT
                EXISTS(SELECT 1 FROM clips WHERE video_id=:vid) AS has_any,
                NOT EXISTS(
                    SELECT 1 FROM clips WHERE video_id=:vid AND status != 'uploaded'
                ) AS all_uploaded
            """,
            {"vid": video_id},
        ).fetchone()
        return bool(row["has_any"]) and bool(row["all_uploaded"])

    # ---- clips ----

    def insert_clip(self, **fields) -> None:
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(f":{k}" for k in fields)
        self.conn.execute(
            f"INSERT OR REPLACE INTO clips ({cols}) VALUES ({placeholders})", fields
        )

    def upsert_selector_clip(
        self,
        *,
        clip_id: str,
        video_id: str,
        start_s: float,
        end_s: float,
        hook: str,
        suggested_title: str,
        selection_method: str,
    ) -> None:
        """Selector-owned upsert. Touches only selector columns on conflict.

        Critically does NOT clobber publish_at_utc, publish_slot_local, output_path,
        youtube_video_id, or title_slug — those are populated by Phases 4 (editor),
        5 (uploader), and 6 (slot_planner). A `--force` re-rank on a clip whose
        downstream metadata is already filled must preserve that metadata so we
        don't accidentally erase a scheduled or rendered clip's pointer state.
        """
        self.conn.execute(
            """
            INSERT INTO clips (
                clip_id, video_id, start_s, end_s,
                hook, suggested_title, selection_method, status
            ) VALUES (
                :clip_id, :video_id, :start_s, :end_s,
                :hook, :suggested_title, :selection_method, 'selected'
            )
            ON CONFLICT(clip_id) DO UPDATE SET
                start_s          = excluded.start_s,
                end_s            = excluded.end_s,
                hook             = excluded.hook,
                suggested_title  = excluded.suggested_title,
                selection_method = excluded.selection_method,
                status           = 'selected',
                rejection_reason = NULL,
                updated_at       = datetime('now')
            """,
            {
                "clip_id": clip_id,
                "video_id": video_id,
                "start_s": float(start_s),
                "end_s": float(end_s),
                "hook": hook,
                "suggested_title": suggested_title,
                "selection_method": selection_method,
            },
        )

    def set_clip_status(
        self,
        clip_id: str,
        status: str,
        reason: str | None = None,
        **extra,
    ) -> None:
        sets = ["status=?", "rejection_reason=?", "updated_at=datetime('now')"]
        params: list = [status, reason]
        for k, v in extra.items():
            sets.append(f"{k}=?")
            params.append(v)
        params.append(clip_id)
        self.conn.execute(
            f"UPDATE clips SET {', '.join(sets)} WHERE clip_id=?",
            params,
        )

    def clips_by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM clips WHERE status=?", (status,)).fetchall()

    def clips_for_policy_gate(self) -> list[sqlite3.Row]:
        """Clips ready for the post-select policy gate (Phase 4.5).

        Ordered by clip_id for deterministic batch reruns.
        """
        return self.conn.execute(
            "SELECT * FROM clips WHERE status='selected' ORDER BY clip_id"
        ).fetchall()

    def clips_for_quality_screen(self) -> list[sqlite3.Row]:
        """Clips ready for the post-render quality screen (Phase 4.5).

        Excludes scheduled / uploaded clips so the screen is never run on a
        clip whose downstream pointer state would be invalidated by a flip
        to rejected_quality.
        """
        return self.conn.execute(
            "SELECT * FROM clips WHERE status='rendered' "
            "AND publish_at_utc IS NULL AND youtube_video_id IS NULL "
            "ORDER BY clip_id"
        ).fetchall()

    # ---- uploader (Phase 5) ----

    def clips_for_upload(self) -> list[sqlite3.Row]:
        """Clips ready for the uploader: quality_pass or approved, with a
        scheduled publish_at_utc and no youtube_video_id yet.

        Ordered by publish_at_utc ASC (then clip_id) so the daily upload run
        publishes oldest-slot-first. NULL publish_at_utc clips are excluded
        — they're waiting on slot_planner (Phase 6); the standalone CLI's
        `--clip-id --publish-at` path handles single-clip ad-hoc uploads.
        """
        return self.conn.execute(
            "SELECT * FROM clips "
            "WHERE status IN ('quality_pass', 'approved') "
            "AND publish_at_utc IS NOT NULL "
            "AND youtube_video_id IS NULL "
            "ORDER BY publish_at_utc ASC, clip_id ASC"
        ).fetchall()

    # ---- slot_planner / daily_upload (Phase 6) ----

    def clips_for_slot_planner(self) -> list[sqlite3.Row]:
        """Clips ready for slot allocation: quality_pass with NULL publish_at_utc
        and NULL youtube_video_id.

        Ordered by created_at ASC then clip_id ASC so allocation is
        reproducible across reruns of the same batch (critical for --dry-run
        parity vs. real-mode).

        Approved clips are EXCLUDED — once a clip is approved, the user has
        vouched for that exact artifact. Slot_planner does not re-slot
        approved clips even with --force (per Phase 6 plan).
        """
        return self.conn.execute(
            "SELECT * FROM clips "
            "WHERE status='quality_pass' "
            "AND publish_at_utc IS NULL "
            "AND youtube_video_id IS NULL "
            "ORDER BY created_at ASC, clip_id ASC"
        ).fetchall()

    def clips_for_upload_due(
        self,
        end_of_window_utc_iso_z: str,
        *,
        statuses: tuple[str, ...] = ("quality_pass", "approved"),
    ) -> list[sqlite3.Row]:
        """Clips_for_upload() with an additional `publish_at_utc <= ?` window
        bound and a parameterized status whitelist.

        Caller passes the whitelist based on cfg.human_review:
          - human_review=True  → statuses=("approved",)
          - human_review=False → statuses=("quality_pass", "approved")

        Window semantics: `<=` end-of-today (caller computes in cfg.timezone
        and converts to UTC). Past-due clips ARE included so missed-slot
        recovery works (PC was off / Task Scheduler skipped a day).
        """
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        return self.conn.execute(
            f"SELECT * FROM clips "
            f"WHERE status IN ({placeholders}) "
            f"AND publish_at_utc IS NOT NULL "
            f"AND publish_at_utc <= ? "
            f"AND youtube_video_id IS NULL "
            f"ORDER BY publish_at_utc ASC, clip_id ASC",
            (*statuses, end_of_window_utc_iso_z),
        ).fetchall()

    def get_clip_with_video(self, clip_id: str) -> sqlite3.Row | None:
        """Joined clips + videos row for the templater.

        Returns columns from both tables; aliases the videos columns with a
        v_ prefix (v_video_id, v_title, v_channel, v_keyword) so the caller
        can disambiguate from the clips columns. Returns None if the clip
        doesn't exist (defensive — every clip should have a video).
        """
        return self.conn.execute(
            """
            SELECT
                c.*,
                v.video_id  AS v_video_id,
                v.title     AS v_title,
                v.channel   AS v_channel,
                v.keyword   AS v_keyword
            FROM clips c
            JOIN videos v ON v.video_id = c.video_id
            WHERE c.clip_id = ?
            """,
            (clip_id,),
        ).fetchone()

    def set_clip_youtube_id(self, clip_id: str, youtube_video_id: str) -> None:
        """Narrow critical-section update: write the YouTube videoId onto the
        clip row WITHOUT touching status. Called by the uploader IMMEDIATELY
        after the API call succeeds (step 10a in the post-upload persistence
        sequence) so the next run cannot double-upload even if the
        subsequent status / uploads-row write fails.

        Caller wraps in repo.tx(). The narrowness of this update is intentional
        — every additional column written here widens the critical section
        between API success and durable DB state.
        """
        self.conn.execute(
            "UPDATE clips SET youtube_video_id=?, updated_at=datetime('now') WHERE clip_id=?",
            (youtube_video_id, clip_id),
        )

    def upsert_upload(
        self,
        clip_id: str,
        youtube_video_id: str,
        publish_at_utc: str,
        quota_units_used: int,
    ) -> None:
        """Insert (or update on conflict) an uploads row.

        Uses explicit ON CONFLICT(clip_id) DO UPDATE rather than
        INSERT OR REPLACE so uploaded_at (the default-on-INSERT timestamp)
        is preserved across retries — REPLACE would silently bump it. PK
        on uploads is clip_id.
        """
        self.conn.execute(
            """
            INSERT INTO uploads (clip_id, youtube_video_id, publish_at_utc, quota_units_used)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(clip_id) DO UPDATE SET
                youtube_video_id = excluded.youtube_video_id,
                publish_at_utc   = excluded.publish_at_utc,
                quota_units_used = excluded.quota_units_used
            """,
            (clip_id, youtube_video_id, publish_at_utc, int(quota_units_used)),
        )

    # ---- dup_hashes (Phase 4.5 quality_screen) ----

    def recent_dup_hashes(self, days: int) -> list[sqlite3.Row]:
        """Returns (clip_id, phash, audio_fp) rows from the last N days.

        Includes clip_id so rejection reasons can name the matching prior
        clip. The 90-day window matches cfg.dedup_lookback_days.
        """
        return self.conn.execute(
            "SELECT clip_id, phash, audio_fp FROM dup_hashes "
            "WHERE created_at >= datetime('now', ?)",
            (f"-{int(days)} days",),
        ).fetchall()

    def insert_dup_hash_rows(
        self,
        rows: list[tuple[str, str, str | None]],
    ) -> None:
        """Bulk-insert dup_hashes rows for a single clip.

        Caller must dedupe the phash list (the schema PK is (clip_id, phash))
        and wrap this call in repo.tx() together with set_clip_status. We use
        INSERT OR IGNORE as a belt-and-suspenders against the rare case where
        two of the five sampled frames produce the same phash.
        """
        if not rows:
            return
        self.conn.executemany(
            "INSERT OR IGNORE INTO dup_hashes (clip_id, phash, audio_fp) "
            "VALUES (?, ?, ?)",
            rows,
        )

    # ---- gameplay rotation: REMOVED in Pivot.3 ----
    # The split-screen + gameplay-rotation editor is gone. The gameplay_cursor
    # and gameplay_pointer tables remain in schema.sql for backward compat
    # with old DBs but no code reads or writes them. They can be dropped by
    # Phase 7 retention's VACUUM pass once we're confident the columns won't
    # be referenced again.

    # ---- discovery: status-preserving upsert ----

    def discovery_upsert_video(
        self,
        *,
        video_id: str,
        title: str,
        channel: str,
        duration_seconds: int,
        views: int,
        likes: int,
        comments: int,
        published_at: str,
        keyword: str,
        virality_score: float,
    ) -> None:
        """Insert a new candidate as 'discovered'; on conflict refresh stats only.

        Critically does NOT touch status, rejection_reason, keyword, or
        discovered_at on existing rows — so a rerun of discovery cannot regress
        a downloaded/uploaded video back to 'discovered'.
        """
        self.conn.execute(
            """
            INSERT INTO videos (
                video_id, title, channel, duration_seconds,
                views, likes, comments, published_at,
                keyword, virality_score, status
            ) VALUES (
                :video_id, :title, :channel, :duration_seconds,
                :views, :likes, :comments, :published_at,
                :keyword, :virality_score, 'discovered'
            )
            ON CONFLICT(video_id) DO UPDATE SET
                title            = excluded.title,
                channel          = excluded.channel,
                duration_seconds = excluded.duration_seconds,
                views            = excluded.views,
                likes            = excluded.likes,
                comments         = excluded.comments,
                virality_score   = excluded.virality_score,
                updated_at       = datetime('now')
            """,
            {
                "video_id": video_id,
                "title": title,
                "channel": channel,
                "duration_seconds": duration_seconds,
                "views": views,
                "likes": likes,
                "comments": comments,
                "published_at": published_at,
                "keyword": keyword,
                "virality_score": virality_score,
            },
        )

    # ---- niche baselines ----

    def historical_views_for_keyword(self, keyword: str, days: int) -> list[int]:
        cutoff = f"-{int(days)} days"
        rows = self.conn.execute(
            "SELECT views FROM videos WHERE keyword=? AND discovered_at >= datetime('now', ?)",
            (keyword, cutoff),
        ).fetchall()
        return [int(r["views"]) for r in rows]

    def niche_median_views(self, keyword: str) -> int:
        row = self.conn.execute(
            "SELECT median_views FROM niche_baselines WHERE keyword=?",
            (keyword,),
        ).fetchone()
        return int(row["median_views"]) if row else 1

    def upsert_niche_baseline(
        self, keyword: str, median_views: int, sample_size: int
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO niche_baselines (keyword, median_views, sample_size)
            VALUES (?, ?, ?)
            ON CONFLICT(keyword) DO UPDATE SET
                median_views = excluded.median_views,
                sample_size  = excluded.sample_size,
                computed_at  = datetime('now')
            """,
            (keyword, int(median_views), int(sample_size)),
        )

    # ---- discovery attempts (idempotency) ----

    def record_discovery_attempt(
        self, keyword: str, inspected_count: int, inserted_count: int
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO discovery_attempts (
                keyword, last_attempted_at, last_inspected, last_inserted
            ) VALUES (?, datetime('now'), ?, ?)
            ON CONFLICT(keyword) DO UPDATE SET
                last_attempted_at = datetime('now'),
                last_inspected    = excluded.last_inspected,
                last_inserted     = excluded.last_inserted
            """,
            (keyword, int(inspected_count), int(inserted_count)),
        )

    def is_in_cooldown(self, keyword: str, hours: int) -> bool:
        cutoff = f"-{int(hours)} hours"
        row = self.conn.execute(
            """
            SELECT 1 FROM discovery_attempts
            WHERE keyword = ?
              AND last_attempted_at > datetime('now', ?)
            """,
            (keyword, cutoff),
        ).fetchone()
        return row is not None

    # ---- runs ----

    def start_run(self, kind: str) -> int:
        cur = self.conn.execute("INSERT INTO runs (kind) VALUES (?)", (kind,))
        return cur.lastrowid

    def finish_run(self, run_id: int, success: bool, summary_json: str) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=datetime('now'), success=?, summary_json=? WHERE run_id=?",
            (1 if success else 0, summary_json, run_id),
        )

    # ---- named single-clip lookup (replaces repo.conn.execute inline SQL) ----

    def get_clip(self, clip_id: str) -> sqlite3.Row | None:
        """Fetch a single clips row by clip_id. Returns None if not found."""
        return self.conn.execute(
            "SELECT * FROM clips WHERE clip_id=?", (clip_id,)
        ).fetchone()

    def clip_has_youtube_id(self, clip_id: str) -> bool:
        """Return True if the clip row has a non-NULL youtube_video_id."""
        row = self.conn.execute(
            "SELECT youtube_video_id FROM clips WHERE clip_id=?", (clip_id,)
        ).fetchone()
        return row is not None and row["youtube_video_id"] is not None

    def set_clip_publish_at(self, clip_id: str, publish_at_utc: str) -> None:
        """Narrow update: write publish_at_utc without touching status."""
        self.conn.execute(
            "UPDATE clips SET publish_at_utc=?, updated_at=datetime('now') WHERE clip_id=?",
            (publish_at_utc, clip_id),
        )

    # ---- quota (absorbed from QuotaLedger) ----

    def quota_record(self, endpoint: str, units: int) -> None:
        """Record quota usage for today (UTC)."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.conn.execute(
            "INSERT INTO quota_usage (date, endpoint, units) VALUES (?, ?, ?)",
            (today, endpoint, int(units)),
        )

    def quota_today_total(self) -> int:
        """Sum of all units recorded today (UTC)."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage WHERE date=?",
            (today,),
        ).fetchone()
        return int(row["s"]) if row else 0

    def quota_would_exceed(self, units: int, ceiling: int) -> bool:
        """Return True if recording `units` more would push today's total past ceiling."""
        return (self.quota_today_total() + units) > ceiling

    # ---- Pivot.6: topics ----

    def unscripted_topics(self) -> list[sqlite3.Row]:
        """Return all topics with status='unscripted', oldest first."""
        return self.conn.execute(
            "SELECT * FROM topics WHERE status='unscripted' ORDER BY id ASC"
        ).fetchall()

    def update_topic_score(
        self,
        topic_id: int,
        topic_score_json: str,
        weighted_score: float,
        category: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE topics SET topic_score_json=?, weighted_score=?, category=? WHERE id=?",
            (topic_score_json, weighted_score, category, topic_id),
        )

    def mark_topic_scored(self, topic_id: int) -> None:
        self.conn.execute("UPDATE topics SET status='scored' WHERE id=?", (topic_id,))

    def insert_topic(
        self,
        *,
        url: str,
        title: str,
        source_feed: str,
        fetched_at: str,
        summary: str | None = None,
        published_at: str | None = None,
    ) -> int:
        """Insert a new unscripted topic. Returns the auto-incremented id."""
        cur = self.conn.execute(
            """
            INSERT INTO topics (url, title, summary, source_feed, fetched_at, published_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (url, title, summary, source_feed, fetched_at, published_at),
        )
        return cur.lastrowid

    def insert_seen_topic(
        self,
        *,
        url_hash: str,
        title_normalized: str,
        first_seen_at: str,
    ) -> None:
        """Insert a seen_topic row for future dedup. Ignores PK conflicts (idempotent)."""
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_topics (url_hash, title_normalized, first_seen_at) "
            "VALUES (?, ?, ?)",
            (url_hash, title_normalized, first_seen_at),
        )

    def seen_topics_in_window(self, days: int) -> list[sqlite3.Row]:
        """Return seen_topics rows first_seen_at within the last N days."""
        return self.conn.execute(
            "SELECT * FROM seen_topics WHERE first_seen_at >= datetime('now', ?)",
            (f"-{int(days)} days",),
        ).fetchall()

    def mark_topic_scripted(self, topic_id: int) -> None:
        self.conn.execute("UPDATE topics SET status='scripted' WHERE id=?", (topic_id,))

    def mark_topic_expired(self, topic_id: int) -> None:
        self.conn.execute("UPDATE topics SET status='expired' WHERE id=?", (topic_id,))

    # ---- Pivot.6: scripts ----

    def insert_script(
        self,
        *,
        script_id: str,
        topic_id: int,
        title: str,
        narration: str,
        shots_json: str,
        style_suffix: str,
        ollama_model: str,
        created_at: str,
        topic_score_json: str | None = None,
        category: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO scripts (
                script_id, topic_id, title, narration, shots_json,
                style_suffix, ollama_model, created_at,
                topic_score_json, category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (script_id, topic_id, title, narration, shots_json,
             style_suffix, ollama_model, created_at,
             topic_score_json, category),
        )

    def update_script_status(
        self,
        script_id: str,
        status: str,
        *,
        rejection_reason: str | None = None,
        quality_score: float | None = None,
        quality_score_json: str | None = None,
    ) -> None:
        sets = ["status=?"]
        params: list = [status]
        if rejection_reason is not None:
            sets.append("rejection_reason=?")
            params.append(rejection_reason)
        if quality_score is not None:
            sets.append("quality_score=?")
            params.append(quality_score)
        if quality_score_json is not None:
            sets.append("quality_score_json=?")
            params.append(quality_score_json)
        params.append(script_id)
        self.conn.execute(
            f"UPDATE scripts SET {', '.join(sets)} WHERE script_id=?", params
        )

    # ---- Pivot.6: clips for generation run ----

    def clips_for_generation_run(self) -> list[sqlite3.Row]:
        """Clips queued for AI video generation: ai_generated kind with a script_id."""
        return self.conn.execute(
            "SELECT * FROM clips WHERE content_kind='ai_generated' AND script_id IS NOT NULL "
            "ORDER BY created_at ASC, clip_id ASC"
        ).fetchall()

    def get_clip_with_script(self, clip_id: str) -> sqlite3.Row | None:
        """Joined clips + scripts row for the AI generation pipeline.

        Scripts columns are prefixed with `s_` to avoid collision with clips
        columns that share names (title, status, created_at).
        Returns None if the clip doesn't exist or has no linked script.
        """
        return self.conn.execute(
            """
            SELECT
                c.*,
                s.script_id    AS s_script_id,
                s.title        AS s_title,
                s.narration    AS s_narration,
                s.shots_json   AS s_shots_json,
                s.style_suffix AS s_style_suffix,
                s.category     AS s_category,
                s.status       AS s_status
            FROM clips c
            JOIN scripts s ON s.script_id = c.script_id
            WHERE c.clip_id = ?
            """,
            (clip_id,),
        ).fetchone()

    # ---- retention delete helpers ----

    def delete_dup_hashes_before(self, cutoff_iso: str) -> int:
        """Delete dup_hashes rows created before cutoff_iso. Returns deleted count."""
        cur = self.conn.execute(
            "DELETE FROM dup_hashes WHERE created_at <= ?", (cutoff_iso,)
        )
        return cur.rowcount

    def delete_quota_usage_before(self, cutoff_date: str) -> int:
        """Delete quota_usage rows with date <= cutoff_date (YYYY-MM-DD). Returns deleted count."""
        cur = self.conn.execute(
            "DELETE FROM quota_usage WHERE date <= ?", (cutoff_date,)
        )
        return cur.rowcount

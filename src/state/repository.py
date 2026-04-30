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
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            self.conn.execute("BEGIN")
            yield self.conn
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

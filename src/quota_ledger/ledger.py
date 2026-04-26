from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


class QuotaExceeded(Exception):
    pass


class QuotaLedger:
    """Per-endpoint, per-UTC-day quota tracker.

    YouTube quota resets at midnight Pacific (Google policy), but the conservative
    choice is to track in UTC and treat the ceiling as a daily budget. The 1k-unit
    headroom (config: youtube_quota_ceiling_units < youtube_quota_daily_units)
    absorbs the timezone slack.
    """

    def __init__(self, conn: sqlite3.Connection, ceiling_units: int) -> None:
        self.conn = conn
        self.ceiling_units = ceiling_units

    @staticmethod
    def _today_utc() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def today_total(self) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(units), 0) AS s FROM quota_usage WHERE date=?",
            (self._today_utc(),),
        ).fetchone()
        return int(row["s"]) if row else 0

    def would_exceed(self, units: int) -> bool:
        return (self.today_total() + units) > self.ceiling_units

    def check_or_raise(self, units: int, endpoint: str) -> None:
        if self.would_exceed(units):
            raise QuotaExceeded(
                f"Calling {endpoint} ({units} units) would exceed daily ceiling "
                f"{self.ceiling_units}; today already used {self.today_total()}"
            )

    def record(self, endpoint: str, units: int) -> None:
        self.conn.execute(
            "INSERT INTO quota_usage (date, endpoint, units) VALUES (?, ?, ?)",
            (self._today_utc(), endpoint, units),
        )

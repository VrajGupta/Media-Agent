"""Issue 34 — spike-82 cleanup verification."""

from pathlib import Path

import pytest


@pytest.mark.skipif(not Path("data/state.db").exists(), reason="live db absent")
def test_spike_82_rejected_and_not_in_pending():
    import sqlite3

    conn = sqlite3.connect("data/state.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT status, rejection_reason FROM clips WHERE clip_id=?",
        ("spike-82",),
    ).fetchone()
    assert row is not None
    assert row["status"] == "rejected_policy"
    assert "off_niche" in (row["rejection_reason"] or "").lower()

    pending_matches = list(Path("output/pending").glob("*spike*82*"))
    assert pending_matches == []

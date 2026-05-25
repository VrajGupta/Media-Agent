"""Issue 11 — insert/update ai_generated clips row after render.

Tests verify upsert behaviour through the public helper interface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.insert_ai_gen_clip import hook_from_narration, upsert_ai_gen_clip
from scripts.render_from_script import stable_clip_id
from src.state import Repository, connect, initialize_schema


@pytest.fixture
def repo(tmp_path):
    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    return Repository(conn)


def test_hook_from_narration_uses_first_five_words():
    narration = "Corti's Symphony beats OpenAI at medical speech recognition."
    assert hook_from_narration(narration) == "Corti's Symphony beats OpenAI at"


def test_upsert_ai_gen_clip_inserts_quality_pass_row(repo: Repository):
    script_id = "7cb41305-b39b-4cc2-855b-067e03549d25"
    output = Path("output/pending/__unscheduled__abc__corti-symphony.mp4")
    narration = "Corti's Symphony beats OpenAI at medical speech recognition."

    clip_id = upsert_ai_gen_clip(
        repo,
        script_id=script_id,
        output_path=output,
        duration_s=16.2,
        title="Corti's Symphony Beats OpenAI",
        narration=narration,
    )

    assert clip_id == stable_clip_id(script_id)
    row = repo.get_clip(clip_id)
    assert row is not None
    assert row["content_kind"] == "ai_generated"
    assert row["script_id"] == script_id
    assert row["status"] == "quality_pass"
    assert row["output_path"] == str(output)
    assert row["video_id"] is None
    assert row["hook"] == hook_from_narration(narration)


def test_upsert_ai_gen_clip_updates_output_path_on_rerun(repo: Repository):
    script_id = "7cb41305-b39b-4cc2-855b-067e03549d25"
    first = Path("output/pending/first.mp4")
    second = Path("output/pending/second.mp4")

    clip_id = upsert_ai_gen_clip(
        repo,
        script_id=script_id,
        output_path=first,
        duration_s=16.0,
        title="Title",
        narration="One two three four five six.",
    )
    upsert_ai_gen_clip(
        repo,
        script_id=script_id,
        output_path=second,
        duration_s=16.5,
        title="Title",
        narration="One two three four five six.",
    )

    row = repo.get_clip(clip_id)
    assert row["output_path"] == str(second)
    assert row["end_s"] == pytest.approx(16.5)

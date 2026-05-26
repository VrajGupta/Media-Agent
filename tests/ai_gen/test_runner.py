"""Unit tests for ai_gen.runner — no live API calls."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ai_gen.base import GenerationStatus, ShotResult
from src.ai_gen.runner import generate_shots


def _make_client(statuses: list[GenerationStatus], urls: list[str | None] = None):
    if urls is None:
        urls = ["https://cdn.example.com/v.mp4"] * len(statuses)
    client = MagicMock()
    client.provider_name = "mock"
    client.submit.side_effect = [f"ext_{i}" for i in range(len(statuses))]
    client.wait_for_completion.side_effect = [
        ShotResult(external_id=f"ext_{i}", status=s, download_url=u)
        for i, (s, u) in enumerate(zip(statuses, urls))
    ]
    # download writes a fake file
    def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake")
        return dest
    client.download.side_effect = fake_download
    return client


SHOTS = [{"prompt": f"shot {i}", "duration_s": 5} for i in range(3)]


def test_generate_shots_returns_paths_in_order(tmp_path):
    client = _make_client([GenerationStatus.SUCCEEDED] * 3)
    paths = generate_shots(SHOTS, tmp_path, client)
    assert len(paths) == 3
    for p in paths:
        assert p.exists()


def test_generate_shots_raises_on_failure(tmp_path):
    client = _make_client(
        [GenerationStatus.SUCCEEDED, GenerationStatus.FAILED, GenerationStatus.SUCCEEDED],
        urls=["https://u/0.mp4", None, "https://u/2.mp4"],
    )
    client.wait_for_completion.side_effect = [
        ShotResult("ext_0", GenerationStatus.SUCCEEDED, download_url="https://u/0.mp4"),
        ShotResult("ext_1", GenerationStatus.FAILED, error="content policy"),
        ShotResult("ext_2", GenerationStatus.SUCCEEDED, download_url="https://u/2.mp4"),
    ]
    with pytest.raises(RuntimeError, match="1 shot"):
        generate_shots(SHOTS, tmp_path, client)


def test_generate_shots_calls_submit_for_each(tmp_path):
    client = _make_client([GenerationStatus.SUCCEEDED] * 3)
    generate_shots(SHOTS, tmp_path, client)
    assert client.submit.call_count == 3


def test_generate_shots_submit_uses_aspect_ratio(tmp_path):
    client = _make_client([GenerationStatus.SUCCEEDED])
    generate_shots([SHOTS[0]], tmp_path, client, aspect_ratio="16:9")
    _, kwargs = client.submit.call_args
    assert kwargs["aspect_ratio"] == "16:9"


def test_generate_shots_records_openrouter_quota(tmp_path):
    from src.state import connect, initialize_schema
    from src.state.repository import Repository

    db = tmp_path / "state.db"
    conn = connect(db)
    initialize_schema(conn)
    repo = Repository(conn)

    client = _make_client([GenerationStatus.SUCCEEDED])
    client.wait_for_completion.side_effect = [
        ShotResult(
            "ext_0", GenerationStatus.SUCCEEDED,
            download_url="https://cdn.example.com/v.mp4",
            cost_cents=67,
        ),
    ]
    generate_shots([SHOTS[0]], tmp_path, client, repo=repo)
    assert repo.quota_today_total(provider="openrouter") == 67

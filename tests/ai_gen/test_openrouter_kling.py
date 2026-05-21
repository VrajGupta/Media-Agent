"""Unit tests for OpenRouterKlingClient — no live API calls."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.ai_gen.base import GenerationStatus
from src.ai_gen.openrouter_kling import OpenRouterKlingClient, _STATUS_MAP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return OpenRouterKlingClient(api_key="sk-or-test-key")


def _mock_response(body: dict) -> MagicMock:
    r = MagicMock()
    r.json.return_value = body
    r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


def test_status_map_covers_all_known_statuses():
    assert "pending" in _STATUS_MAP
    assert "in_progress" in _STATUS_MAP
    assert "completed" in _STATUS_MAP
    assert "failed" in _STATUS_MAP


def test_status_map_completed_maps_to_succeeded():
    assert _STATUS_MAP["completed"] == GenerationStatus.SUCCEEDED


def test_status_map_in_progress_maps_to_running():
    assert _STATUS_MAP["in_progress"] == GenerationStatus.RUNNING


def test_status_map_pending_maps_to_queued():
    assert _STATUS_MAP["pending"] == GenerationStatus.QUEUED


# ---------------------------------------------------------------------------
# submit()
# ---------------------------------------------------------------------------


def test_submit_returns_job_id(client):
    mock_resp = _mock_response({"id": "gen-abc123", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp):
        job_id = client.submit("a dark ocean trench, bioluminescent creatures", duration_s=5, aspect_ratio="9:16")
    assert job_id == "gen-abc123"


def test_submit_posts_to_correct_url(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt")
    url = mock_post.call_args[0][0]
    assert url == "https://openrouter.ai/api/v1/videos"


def test_submit_sends_correct_model(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt")
    body = mock_post.call_args[1]["json"]
    assert body["model"] == "kwaivgi/kling-v3.0-std"


def test_submit_sends_prompt_duration_aspect_ratio(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("weird biology fact", duration_s=10, aspect_ratio="9:16")
    body = mock_post.call_args[1]["json"]
    assert body["prompt"] == "weird biology fact"
    assert body["duration"] == 10
    assert body["aspect_ratio"] == "9:16"


def test_submit_uses_bearer_auth(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt")
    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer sk-or-test-key"


def test_submit_disables_audio(client):
    mock_resp = _mock_response({"id": "x", "status": "pending"})
    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("prompt")
    body = mock_post.call_args[1]["json"]
    assert body["enable_audio"] is False


def test_submit_raises_if_no_id(client):
    mock_resp = _mock_response({"status": "pending"})  # missing "id"
    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(ValueError, match="no id"):
            client.submit("prompt")


# ---------------------------------------------------------------------------
# poll()
# ---------------------------------------------------------------------------


def test_poll_completed_extracts_download_url(client):
    mock_resp = _mock_response({
        "id": "gen-abc",
        "status": "completed",
        "unsigned_urls": ["https://cdn.openrouter.ai/videos/gen-abc.mp4"],
    })
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-abc")
    assert result.status == GenerationStatus.SUCCEEDED
    assert result.download_url == "https://cdn.openrouter.ai/videos/gen-abc.mp4"


def test_poll_pending_maps_to_queued(client):
    mock_resp = _mock_response({"id": "gen-abc", "status": "pending"})
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-abc")
    assert result.status == GenerationStatus.QUEUED
    assert result.download_url is None


def test_poll_in_progress_maps_to_running(client):
    mock_resp = _mock_response({"id": "gen-abc", "status": "in_progress"})
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-abc")
    assert result.status == GenerationStatus.RUNNING


def test_poll_failed_captures_error(client):
    mock_resp = _mock_response({
        "id": "gen-abc",
        "status": "failed",
        "error": "content policy violation",
    })
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-abc")
    assert result.status == GenerationStatus.FAILED
    assert "content policy" in result.error


def test_poll_failed_fallback_error_message(client):
    mock_resp = _mock_response({"id": "gen-abc", "status": "failed"})
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-abc")
    assert result.status == GenerationStatus.FAILED
    assert result.error == "unknown error"


def test_poll_captures_cost_cents(client):
    mock_resp = _mock_response({
        "id": "gen-abc",
        "status": "completed",
        "unsigned_urls": ["https://cdn.openrouter.ai/videos/gen-abc.mp4"],
        "usage": {"cost": 0.14},
    })
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("gen-abc")
    assert result.cost_cents == 14


def test_poll_polls_correct_url(client):
    mock_resp = _mock_response({"id": "gen-abc", "status": "pending"})
    with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
        client.poll("gen-abc")
    url = mock_get.call_args[0][0]
    assert url == "https://openrouter.ai/api/v1/videos/gen-abc"


# ---------------------------------------------------------------------------
# download()
# ---------------------------------------------------------------------------


def test_download_writes_bytes_to_dest(tmp_path, client):
    fake_bytes = b"fake_mp4_bytes_from_openrouter"
    mock_resp = MagicMock()
    mock_resp.iter_content.return_value = [fake_bytes]
    mock_resp.raise_for_status = MagicMock()
    with patch.object(client._session, "get", return_value=mock_resp):
        dest = client.download("https://cdn.openrouter.ai/v.mp4", tmp_path / "shot.mp4")
    assert dest.read_bytes() == fake_bytes


def test_download_creates_parent_dirs(tmp_path, client):
    fake_bytes = b"data"
    mock_resp = MagicMock()
    mock_resp.iter_content.return_value = [fake_bytes]
    mock_resp.raise_for_status = MagicMock()
    nested = tmp_path / "a" / "b" / "shot.mp4"
    with patch.object(client._session, "get", return_value=mock_resp):
        client.download("https://cdn.openrouter.ai/v.mp4", nested)
    assert nested.exists()


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_submit_retries_on_connection_error(client):
    good_resp = _mock_response({"id": "gen-xyz", "status": "pending"})
    call_count = 0

    def side_effect(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise requests.ConnectionError("network down")
        return good_resp

    with patch("tenacity.nap.time.sleep"), \
         patch.object(client._session, "post", side_effect=side_effect):
        job_id = client.submit("p")

    assert job_id == "gen-xyz"
    assert call_count == 2


def test_poll_retries_on_timeout(client):
    good_resp = _mock_response({"id": "gen-xyz", "status": "pending"})
    call_count = 0

    def side_effect(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise requests.Timeout("timed out")
        return good_resp

    with patch("tenacity.nap.time.sleep"), \
         patch.object(client._session, "get", side_effect=side_effect):
        result = client.poll("gen-xyz")

    assert result.status == GenerationStatus.QUEUED
    assert call_count == 2


# ---------------------------------------------------------------------------
# Default model
# ---------------------------------------------------------------------------


def test_default_model_is_kling_v3_std():
    c = OpenRouterKlingClient(api_key="k")
    assert c.model == "kwaivgi/kling-v3.0-std"


def test_custom_model_accepted():
    c = OpenRouterKlingClient(api_key="k", model="kwaivgi/kling-v3.0-pro")
    assert c.model == "kwaivgi/kling-v3.0-pro"

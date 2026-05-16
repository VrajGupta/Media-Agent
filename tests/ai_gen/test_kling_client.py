"""Unit tests for KlingClient — no live API calls."""
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest
import requests

from src.ai_gen.base import GenerationStatus, ShotResult
from src.ai_gen.kling import KlingClient, _STATUS_MAP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return KlingClient(access_key="test_ak", secret_key="test_sk")


# ---------------------------------------------------------------------------
# JWT token generation
# ---------------------------------------------------------------------------


def test_token_contains_iss(client):
    token = client._make_token()
    payload = jwt.decode(token, "test_sk", algorithms=["HS256"])
    assert payload["iss"] == "test_ak"


def test_token_exp_is_future(client):
    token = client._make_token()
    payload = jwt.decode(token, "test_sk", algorithms=["HS256"])
    assert payload["exp"] > time.time()


def test_token_nbf_is_past(client):
    token = client._make_token()
    # nbf should be slightly in the past (clock-skew buffer)
    payload = jwt.decode(token, "test_sk", algorithms=["HS256"], options={"verify_nbf": False})
    assert payload["nbf"] <= time.time()


def test_token_cached_within_ttl(client):
    t1 = client._get_token()
    t2 = client._get_token()
    assert t1 == t2  # same token returned within TTL window


def test_token_refreshed_after_expiry(client):
    # Patch time.time in the kling module so the second _make_token() call
    # uses a timestamp 2 s later, guaranteeing exp advances even at int precision.
    # Call sequence: cond-check1, _make_token1, token_exp-set1,
    #                cond-check2, _make_token2, token_exp-set2  → 6 calls total.
    with patch("src.ai_gen.kling.time.time", side_effect=[1000.0, 1000.0, 1000.0, 1000.0, 1002.0, 1002.0]):
        t1 = client._get_token()
        client._token_exp = 999.0  # force expiry without a time.time() call
        t2 = client._get_token()
    no_verify = {"verify_exp": False}
    assert jwt.decode(t2, "test_sk", algorithms=["HS256"], options=no_verify)["exp"] > \
           jwt.decode(t1, "test_sk", algorithms=["HS256"], options=no_verify)["exp"]


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


def test_status_map_covers_all_known_statuses():
    assert "submitted" in _STATUS_MAP
    assert "processing" in _STATUS_MAP
    assert "succeed" in _STATUS_MAP
    assert "failed" in _STATUS_MAP


def test_status_map_succeed_maps_to_succeeded():
    assert _STATUS_MAP["succeed"] == GenerationStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# submit()
# ---------------------------------------------------------------------------


def test_submit_returns_task_id(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"task_id": "job_abc123"}}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "post", return_value=mock_resp):
        task_id = client.submit("test prompt", duration_s=5, aspect_ratio="9:16")

    assert task_id == "job_abc123"


def test_submit_sends_correct_body(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"task_id": "x"}}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
        client.submit("hello", duration_s=10, aspect_ratio="9:16")

    body = mock_post.call_args[1]["json"]
    assert body["prompt"] == "hello"
    assert body["duration"] == "10"
    assert body["aspect_ratio"] == "9:16"
    assert body["model_name"] == "kling-v1-6"


def test_submit_raises_if_no_task_id(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {}}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(ValueError, match="no task_id"):
            client.submit("p")


# ---------------------------------------------------------------------------
# poll()
# ---------------------------------------------------------------------------


def test_poll_succeeded_extracts_url(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "task_id": "abc",
            "task_status": "succeed",
            "task_result": {"videos": [{"url": "https://cdn.example.com/v.mp4"}]},
        }
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("abc")

    assert result.status == GenerationStatus.SUCCEEDED
    assert result.download_url == "https://cdn.example.com/v.mp4"


def test_poll_failed_captures_error(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "task_id": "abc",
            "task_status": "failed",
            "task_status_msg": "content policy violation",
        }
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("abc")

    assert result.status == GenerationStatus.FAILED
    assert "content policy" in result.error


def test_poll_processing_maps_to_running(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"task_id": "abc", "task_status": "processing"}}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.poll("abc")

    assert result.status == GenerationStatus.RUNNING


# ---------------------------------------------------------------------------
# download()
# ---------------------------------------------------------------------------


def test_download_writes_file(tmp_path, client):
    fake_content = b"fake_mp4_bytes"
    mock_resp = MagicMock()
    mock_resp.iter_content.return_value = [fake_content]
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "get", return_value=mock_resp):
        dest = client.download("https://cdn.example.com/v.mp4", tmp_path / "out.mp4")

    assert dest.read_bytes() == fake_content


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_submit_retries_on_connection_error(client):
    good_resp = MagicMock()
    good_resp.json.return_value = {"data": {"task_id": "abc"}}
    good_resp.raise_for_status = MagicMock()

    call_count = 0

    def side_effect(*a, **kw):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise requests.ConnectionError("network down")
        return good_resp

    with patch("tenacity.nap.time.sleep"), \
         patch.object(client._session, "post", side_effect=side_effect):
        task_id = client.submit("p")

    assert task_id == "abc"
    assert call_count == 2  # one failure + one success

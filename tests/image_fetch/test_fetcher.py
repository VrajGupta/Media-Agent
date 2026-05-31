"""P7.3 — image_fetch hybrid sourcing (HTTP fully mocked)."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.image_fetch.errors import LivingPersonEntityError, NoImageFoundError
from src.image_fetch.fetcher import fetch_image, resolve_licensed_image
from src.image_fetch.validation import validate_image_bytes


def _make_png(size: int = 600) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (size, size), color="red").save(buf, format="PNG")
    return buf.getvalue()


def _make_cfg(tmp_path, *, web_fallback=True):
    paths = SimpleNamespace(images_dir=str(tmp_path / "images"))
    image_fetch = SimpleNamespace(
        sources=["wikimedia", "openverse", "web"],
        min_resolution=512,
        max_candidates_per_source=5,
        web_fallback_enabled=web_fallback,
        living_person_patterns=["portrait of", "photo of"],
    )
    cfg = SimpleNamespace(image_fetch=image_fetch, paths=paths)
    cfg.abs_path = lambda rel: tmp_path / rel if not Path(rel).is_absolute() else Path(rel)
    return cfg


def _mock_session_get(data: bytes, content_type: str = "image/png"):
    session = MagicMock()
    resp = MagicMock()
    resp.content = data
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = MagicMock()
    session.get.return_value = resp
    return session


def test_validate_image_bytes_rejects_non_image():
    with pytest.raises(ValueError):
        validate_image_bytes(b"not-an-image", min_resolution=512)


def test_validate_image_bytes_rejects_undersized():
    with pytest.raises(ValueError, match="too small"):
        validate_image_bytes(_make_png(100), min_resolution=512)


def test_fetch_image_raises_for_living_person_entity(tmp_path):
    cfg = _make_cfg(tmp_path)
    with pytest.raises(LivingPersonEntityError):
        fetch_image("portrait of Tim Cook", None, cfg, cache_dir=tmp_path / "cache")


def test_fetch_image_cache_hit_skips_http(tmp_path):
    cfg = _make_cfg(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    img_path = cache_dir / "abc.jpg"
    img_path.write_bytes(_make_png())
    sidecar = cache_dir / "deadbeef.json"
    sidecar.write_text(json.dumps({
        "path": str(img_path),
        "source": "wikimedia",
        "license": "CC-BY",
        "source_url": "https://example.com",
        "width": 600,
        "height": 600,
    }), encoding="utf-8")

    session = MagicMock()
    with patch("src.image_fetch.fetcher._cache_key", return_value="deadbeef"):
        asset = fetch_image("OpenAI logo", None, cfg, cache_dir=cache_dir, session=session)
    session.get.assert_not_called()
    assert asset.source == "wikimedia"


def test_fetch_image_prefers_earlier_source(tmp_path):
    cfg = _make_cfg(tmp_path)
    cache_dir = tmp_path / "cache"
    png = _make_png()
    session = _mock_session_get(png)

    wiki_candidate = MagicMock()
    wiki_candidate.search.return_value = [
        MagicMock(
            url="https://example.com/wiki.png",
            source="wikimedia",
            license="CC-BY",
            source_url="https://commons.wikimedia.org/x",
            width=600,
            height=600,
        )
    ]
    web_candidate = MagicMock()
    web_candidate.search.return_value = [
        MagicMock(
            url="https://example.com/web.png",
            source="web",
            license="unknown",
            source_url="https://example.com",
            width=600,
            height=600,
        )
    ]

    with patch("src.image_fetch.fetcher.build_sources", return_value=[wiki_candidate, web_candidate]):
        asset = fetch_image("OpenAI logo", None, cfg, cache_dir=cache_dir, session=session)
    assert asset.source == "wikimedia"
    web_candidate.search.assert_not_called()


def test_fetch_image_falls_back_when_first_source_misses(tmp_path):
    cfg = _make_cfg(tmp_path)
    cache_dir = tmp_path / "cache"
    png = _make_png()
    session = _mock_session_get(png)

    wiki = MagicMock()
    wiki.search.return_value = []
    web = MagicMock()
    web.search.return_value = [
        MagicMock(
            url="https://example.com/web.png",
            source="web",
            license="unknown",
            source_url="https://example.com",
            width=600,
            height=600,
        )
    ]

    with patch("src.image_fetch.fetcher.build_sources", return_value=[wiki, web]):
        asset = fetch_image("RTX 5090", None, cfg, cache_dir=cache_dir, session=session)
    assert asset.source == "web"


def test_fetch_image_rejects_non_image_content_type(tmp_path):
    cfg = _make_cfg(tmp_path)
    cache_dir = tmp_path / "cache"
    session = _mock_session_get(b"<html>", content_type="text/html")

    source = MagicMock()
    source.search.return_value = [
        MagicMock(
            url="https://example.com/bad",
            source="web",
            license="unknown",
            source_url="https://example.com",
            width=600,
            height=600,
        )
    ]
    with patch("src.image_fetch.fetcher.build_sources", return_value=[source]):
        with pytest.raises(NoImageFoundError):
            fetch_image("OpenAI logo", None, cfg, cache_dir=cache_dir, session=session)


def test_fetch_image_writes_provenance_sidecar(tmp_path):
    cfg = _make_cfg(tmp_path)
    cache_dir = tmp_path / "cache"
    png = _make_png()
    session = _mock_session_get(png)

    source = MagicMock()
    source.search.return_value = [
        MagicMock(
            url="https://example.com/logo.png",
            source="logo",
            license="Clearbit",
            source_url="https://logo.clearbit.com/openai.com",
            width=600,
            height=600,
        )
    ]
    with patch("src.image_fetch.fetcher.build_sources", return_value=[source]):
        asset = fetch_image("OpenAI logo", None, cfg, cache_dir=cache_dir, session=session)
    sidecars = list(cache_dir.glob("*.json"))
    assert sidecars
    data = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert data["license"] == asset.license
    assert data["source_url"] == asset.source_url


def test_fetch_image_raises_when_all_sources_miss(tmp_path):
    cfg = _make_cfg(tmp_path)
    cache_dir = tmp_path / "cache"
    session = MagicMock()
    source = MagicMock()
    source.search.return_value = []
    with patch("src.image_fetch.fetcher.build_sources", return_value=[source]):
        with pytest.raises(NoImageFoundError):
            fetch_image("unknown widget", None, cfg, cache_dir=cache_dir, session=session)


def test_fetch_image_skips_web_when_disabled(tmp_path):
    cfg = _make_cfg(tmp_path, web_fallback=False)
    cache_dir = tmp_path / "cache"
    session = MagicMock()

    with patch("src.image_fetch.fetcher.build_sources") as mock_build:
        mock_build.return_value = []
        with pytest.raises(NoImageFoundError):
            fetch_image("OpenAI logo", None, cfg, cache_dir=cache_dir, session=session)
    assert "web" not in mock_build.call_args[0][0]


def test_resolve_licensed_image_never_consults_web(tmp_path):
    cfg = _make_cfg(tmp_path, web_fallback=True)
    cfg.image_fetch.sources = ["logo", "wikimedia", "openverse", "web"]
    cache_dir = tmp_path / "cache"
    session = MagicMock()
    source = MagicMock()
    candidate = MagicMock(
        url="https://example.com/logo.png",
        source="logo",
        license="CC0",
        source_url="https://example.com",
    )
    source.search.return_value = [candidate]
    session.get.return_value = MagicMock(
        raise_for_status=lambda: None,
        headers={"Content-Type": "image/png"},
        content=_make_png(),
    )

    with patch("src.image_fetch.fetcher.build_sources") as mock_build:
        mock_build.return_value = [source]
        asset = resolve_licensed_image(
            "OpenAI logo", None, cfg, cache_dir=cache_dir, session=session,
        )

    assert asset is not None
    assert "web" not in mock_build.call_args[0][0]


def test_resolve_licensed_image_returns_none_on_miss(tmp_path):
    cfg = _make_cfg(tmp_path, web_fallback=False)
    cache_dir = tmp_path / "cache"
    session = MagicMock()

    with patch("src.image_fetch.fetcher.build_sources") as mock_build:
        mock_build.return_value = []
        assert resolve_licensed_image(
            "unknown widget", None, cfg, cache_dir=cache_dir, session=session,
        ) is None

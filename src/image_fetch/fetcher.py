"""Hybrid image sourcing orchestrator."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import requests

from src.image_fetch.base import ImageAsset, ImageCandidate
from src.image_fetch.errors import LivingPersonEntityError, NoImageFoundError
from src.image_fetch.sources import build_sources
from src.image_fetch.validation import validate_image_bytes


def _cache_key(entity: str, query: str | None) -> str:
    raw = f"{entity}|{query or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _reject_living_person(entity: str, patterns: list[str]) -> None:
    lower = entity.lower()
    for pat in patterns:
        if pat.lower() in lower:
            raise LivingPersonEntityError(
                f"real_image entity must not reference a living person: {entity!r}"
            )


def _load_cached(cache_dir: Path, key: str) -> ImageAsset | None:
    sidecar = cache_dir / f"{key}.json"
    if not sidecar.exists():
        return None
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    image_path = Path(data["path"])
    if not image_path.exists():
        return None
    return ImageAsset(
        path=str(image_path),
        source=data["source"],
        license=data["license"],
        source_url=data["source_url"],
        width=int(data["width"]),
        height=int(data["height"]),
    )


def _write_cache(
    cache_dir: Path,
    key: str,
    image_path: Path,
    candidate: ImageCandidate,
    width: int,
    height: int,
) -> ImageAsset:
    sidecar = cache_dir / f"{key}.json"
    asset = ImageAsset(
        path=str(image_path),
        source=candidate.source,
        license=candidate.license,
        source_url=candidate.source_url,
        width=width,
        height=height,
    )
    sidecar.write_text(json.dumps({
        "path": asset.path,
        "source": asset.source,
        "license": asset.license,
        "source_url": asset.source_url,
        "width": asset.width,
        "height": asset.height,
    }, indent=2), encoding="utf-8")
    return asset


def _download_candidate(
    session: requests.Session,
    candidate: ImageCandidate,
    *,
    min_resolution: int,
) -> tuple[bytes, int, int]:
    resp = session.get(candidate.url, timeout=30)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if content_type and not content_type.startswith("image/"):
        raise ValueError(f"non-image content-type: {content_type}")
    data = resp.content
    width, height = validate_image_bytes(data, min_resolution=min_resolution)
    return data, width, height


def probe_licensed_image(
    entity: str,
    query: str | None,
    cfg,
    *,
    cache_dir: Path | None = None,
    session: requests.Session | None = None,
) -> bool:
    """Return True if licensed sources can satisfy entity (never consults web)."""
    if_cfg = cfg.image_fetch
    _reject_living_person(entity, if_cfg.living_person_patterns)

    cache_root = cache_dir or cfg.abs_path(cfg.paths.images_dir)
    key = _cache_key(entity, query)
    if _load_cached(cache_root, key) is not None:
        return True

    http = session or requests.Session()
    source_names = [n for n in if_cfg.sources if n != "web"]
    sources = build_sources(
        source_names,
        http,
        serpapi_key=os.environ.get("SERPAPI_KEY"),
    )

    for source in sources:
        try:
            candidates = source.search(entity, query)[: if_cfg.max_candidates_per_source]
        except Exception:
            continue
        if candidates:
            return True
    return False


def provenance_for_entity(
    entity: str,
    query: str | None,
    cfg,
    *,
    cache_dir: Path | None = None,
) -> ImageAsset | None:
    """Return cached provenance for entity without network I/O."""
    cache_root = cache_dir or cfg.abs_path(cfg.paths.images_dir)
    return _load_cached(cache_root, _cache_key(entity, query))


def fetch_image(
    entity: str,
    query: str | None,
    cfg,
    *,
    cache_dir: Path | None = None,
    session: requests.Session | None = None,
) -> ImageAsset:
    """Fetch a validated real image for entity; cache + provenance sidecar."""
    if_cfg = cfg.image_fetch
    _reject_living_person(entity, if_cfg.living_person_patterns)

    cache_root = cache_dir or cfg.abs_path(cfg.paths.images_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    key = _cache_key(entity, query)

    cached = _load_cached(cache_root, key)
    if cached is not None:
        return cached

    http = session or requests.Session()
    source_names = list(if_cfg.sources)
    if not if_cfg.web_fallback_enabled:
        source_names = [n for n in source_names if n != "web"]
    sources = build_sources(
        source_names,
        http,
        serpapi_key=os.environ.get("SERPAPI_KEY"),
    )

    for source in sources:
        try:
            candidates = source.search(entity, query)[: if_cfg.max_candidates_per_source]
        except Exception:
            continue
        for candidate in candidates:
            try:
                data, width, height = _download_candidate(
                    http, candidate, min_resolution=if_cfg.min_resolution,
                )
            except (ValueError, requests.RequestException):
                continue
            dest = cache_root / f"{key}.jpg"
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
            return _write_cache(cache_root, key, dest, candidate, width, height)

    raise NoImageFoundError(f"no valid image found for entity {entity!r}")

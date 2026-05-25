"""Concrete image sources for hybrid sourcing."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import requests

from src.image_fetch.base import ImageCandidate, Source


class LogoSource(Source):
    name = "logo"

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()

    def search(self, entity: str, query: str | None) -> list[ImageCandidate]:
        domain = _guess_domain(entity, query)
        if not domain:
            return []
        url = f"https://logo.clearbit.com/{domain}"
        return [ImageCandidate(
            url=url,
            source=self.name,
            license="Clearbit Logo API (trademark subject to holder)",
            source_url=url,
        )]


class WikimediaSource(Source):
    name = "wikimedia"

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()

    def search(self, entity: str, query: str | None) -> list[ImageCandidate]:
        term = query or entity
        api = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {term}",
            "gsrlimit": 5,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
        }
        resp = self._session.get(api, params=params, timeout=15)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        out: list[ImageCandidate] = []
        for page in pages.values():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            url = info.get("url")
            if not url:
                continue
            meta = info.get("extmetadata") or {}
            license_short = (meta.get("LicenseShortName") or {}).get("value", "CC")
            out.append(ImageCandidate(
                url=url,
                source=self.name,
                license=license_short,
                source_url=f"https://commons.wikimedia.org/?curid={page.get('pageid')}",
                width=info.get("width"),
                height=info.get("height"),
            ))
        return out


class OpenverseSource(Source):
    name = "openverse"

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()

    def search(self, entity: str, query: str | None) -> list[ImageCandidate]:
        term = quote(query or entity)
        api = f"https://api.openverse.org/v1/images/?q={term}&page_size=5"
        resp = self._session.get(api, timeout=15)
        resp.raise_for_status()
        results = resp.json().get("results") or []
        out: list[ImageCandidate] = []
        for item in results:
            url = item.get("url")
            if not url:
                continue
            out.append(ImageCandidate(
                url=url,
                source=self.name,
                license=item.get("license", "CC"),
                source_url=item.get("foreign_landing_url") or url,
                width=item.get("width"),
                height=item.get("height"),
            ))
        return out


class WebSearchSource(Source):
    name = "web"

    def __init__(self, session: requests.Session | None = None, *, serpapi_key: str | None = None):
        self._session = session or requests.Session()
        self._serpapi_key = serpapi_key

    def search(self, entity: str, query: str | None) -> list[ImageCandidate]:
        term = query or entity
        if self._serpapi_key:
            return self._search_serpapi(term)
        return self._search_ddgs(term)

    def _search_ddgs(self, term: str) -> list[ImageCandidate]:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore[no-redef]
        results = DDGS().images(term, max_results=5)
        out: list[ImageCandidate] = []
        for item in results:
            url = item.get("image")
            if not url:
                continue
            out.append(ImageCandidate(
                url=url,
                source=self.name,
                license="unknown (web search)",
                source_url=item.get("url") or url,
                width=item.get("width"),
                height=item.get("height"),
            ))
        return out

    def _search_serpapi(self, term: str) -> list[ImageCandidate]:
        resp = self._session.get(
            "https://serpapi.com/search.json",
            params={"engine": "google_images", "q": term, "api_key": self._serpapi_key},
            timeout=15,
        )
        resp.raise_for_status()
        images = resp.json().get("images_results") or []
        out: list[ImageCandidate] = []
        for item in images[:5]:
            url = item.get("original")
            if not url:
                continue
            out.append(ImageCandidate(
                url=url,
                source=self.name,
                license="unknown (SerpAPI web search)",
                source_url=item.get("link") or url,
                width=item.get("original_width"),
                height=item.get("original_height"),
            ))
        return out


_SOURCE_CLASSES: dict[str, type[Source]] = {
    "logo": LogoSource,
    "wikimedia": WikimediaSource,
    "openverse": OpenverseSource,
    "web": WebSearchSource,
}


def build_sources(
    names: list[str],
    session: requests.Session,
    *,
    serpapi_key: str | None = None,
) -> list[Source]:
    sources: list[Source] = []
    for name in names:
        cls = _SOURCE_CLASSES.get(name)
        if cls is None:
            continue
        if name == "web":
            sources.append(WebSearchSource(session, serpapi_key=serpapi_key))
        else:
            sources.append(cls(session))
    return sources


def _guess_domain(entity: str, query: str | None) -> str | None:
    text = f"{entity} {query or ''}".lower()
    known = {
        "openai": "openai.com",
        "nvidia": "nvidia.com",
        "google": "google.com",
        "microsoft": "microsoft.com",
        "apple": "apple.com",
        "meta": "meta.com",
        "amd": "amd.com",
        "intel": "intel.com",
        "tsmc": "tsmc.com",
    }
    for key, domain in known.items():
        if key in text:
            return domain
    match = re.search(r"([a-z0-9-]+\.(?:com|org|io|ai|net))", text)
    return match.group(1) if match else None

"""Source ABC and shared types for image_fetch."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    source: str
    license: str
    source_url: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class ImageAsset:
    path: str
    source: str
    license: str
    source_url: str
    width: int
    height: int


class Source(ABC):
    name: str

    @abstractmethod
    def search(self, entity: str, query: str | None) -> list[ImageCandidate]:
        """Return ranked image candidates for the entity."""

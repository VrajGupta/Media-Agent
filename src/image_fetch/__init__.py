"""Image sourcing for real_image shots (Pivot.7)."""

from src.image_fetch.fetcher import fetch_image, resolve_licensed_image
from src.image_fetch.base import ImageAsset, ImageCandidate

__all__ = ["fetch_image", "resolve_licensed_image", "ImageAsset", "ImageCandidate"]

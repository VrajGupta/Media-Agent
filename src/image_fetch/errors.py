"""Typed errors for image_fetch."""

from __future__ import annotations


class ImageFetchError(Exception):
    """Base error for image sourcing failures."""


class LivingPersonEntityError(ImageFetchError):
    """Entity appears to reference a living person."""


class NoImageFoundError(ImageFetchError):
    """No valid image found across all sources."""

"""Image validation helpers."""

from __future__ import annotations

import io

from PIL import Image


def validate_image_bytes(data: bytes, *, min_resolution: int) -> tuple[int, int]:
    """Decode image bytes; raise ValueError if invalid or too small."""
    if not data:
        raise ValueError("empty image data")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except Exception as exc:
        raise ValueError(f"undecodable image: {exc}") from exc
    if width < min_resolution or height < min_resolution:
        raise ValueError(
            f"image too small: {width}x{height} (min {min_resolution})"
        )
    return width, height

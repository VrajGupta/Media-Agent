"""Per-input shot normalization for assembler filtergraphs (ADR-0002)."""

from __future__ import annotations


def normalize_input_chain(
    index: int,
    *,
    width: int,
    height: int,
    fps: int,
    out_label: str | None = None,
) -> str:
    """Return the filter chain that conforms one input to the canonical format."""
    label = out_label if out_label is not None else f"vn{index}"
    return (
        f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={fps},format=yuv420p,settb=AVTB[{label}]"
    )

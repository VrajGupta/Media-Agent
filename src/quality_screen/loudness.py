"""Post-render loudness check (Phase 4.5).

Runs `ffmpeg -i <output> -af loudnorm=print_format=json -f null -` and
parses the trailing JSON object from stderr. Two-tier policy implemented
in the runner; this module only returns the measurement.

Fail-soft on subprocess error or malformed JSON: returns LoudnessMeasurement
with `infrastructure_failed=True` and the runner treats it as a pass-with-alert.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass
class LoudnessMeasurement:
    input_i: float = 0.0
    infrastructure_failed: bool = False
    reason: str = ""


# ffmpeg loudnorm prints a JSON block on stderr with newlines and a closing }.
# We extract the LAST {...} block to avoid picking up ffmpeg banner JSON.
_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def _extract_input_i(stderr_text: str) -> float | None:
    """Pull the loudnorm JSON from ffmpeg's stderr and return input_i.

    Returns None when no JSON block is found or input_i is not a number.
    """
    match = _JSON_BLOCK_RE.search(stderr_text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    raw = parsed.get("input_i")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def measure_loudness(path: Path) -> LoudnessMeasurement:
    """Returns LoudnessMeasurement. infrastructure_failed=True on subprocess
    or parse failure — runner treats as pass-with-alert (loudness_warn is the
    in-band concern, not a measurement bug).
    """
    bin_ = shutil.which("ffmpeg") or "ffmpeg"
    argv = [
        bin_, "-hide_banner", "-nostats",
        "-i", str(path),
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning(f"loudness ffmpeg subprocess error: {exc}")
        return LoudnessMeasurement(infrastructure_failed=True, reason=f"subprocess: {exc}")

    stderr = result.stderr or ""
    input_i = _extract_input_i(stderr)
    if input_i is None:
        # ffmpeg may exit nonzero but still print useful JSON; rely on parse alone.
        logger.warning(
            f"loudness JSON parse failed (rc={result.returncode}); stderr tail: "
            f"{stderr[-300:]!r}"
        )
        return LoudnessMeasurement(
            infrastructure_failed=True,
            reason=f"parse failed (rc={result.returncode})",
        )
    return LoudnessMeasurement(input_i=input_i)


def classify_loudness(input_i: float, target_lufs: float) -> str:
    """Return 'pass' (within ±0.5 LUFS), 'warn' (±0.5..±1.5), 'reject' (>±1.5)."""
    delta = abs(input_i - target_lufs)
    if delta <= 0.5:
        return "pass"
    if delta <= 1.5:
        return "warn"
    return "reject"

"""Integration test — mixed-resolution shots stitch to canonical 1080×1920."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.assembler.build import build_assembler_argv, write_concat_list


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)


def _lavfi_shot(tmp_path: Path, name: str, size: str, fps: int, duration: float) -> Path:
    out = tmp_path / name
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s={size}:r={fps}:d={duration}",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(out),
        ],
        check=True,
    )
    return out


def _lavfi_audio(tmp_path: Path, duration: float) -> Path:
    out = tmp_path / "narration.mp3"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=f=440:duration={duration}",
            "-c:a",
            "libmp3lame",
            str(out),
        ],
        check=True,
    )
    return out


def _probe_resolution(path: Path) -> tuple[int, int]:
    out = subprocess.check_output(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path),
        ],
        text=True,
    ).strip()
    w, h = out.split("x")
    return int(w), int(h)


def test_mixed_resolution_shots_stitch_to_1080x1920(tmp_path):
    """720×1280@24 + 1080×1920@30 must assemble without error -22."""
    shot_a = _lavfi_shot(tmp_path, "kling.mp4", "720x1280", 24, 2.0)
    shot_b = _lavfi_shot(tmp_path, "kenburns.mp4", "1080x1920", 30, 2.0)
    narration = _lavfi_audio(tmp_path, 3.5)
    concat_list = tmp_path / "concat.txt"
    write_concat_list([shot_a, shot_b], concat_list)
    output = tmp_path / "out.mp4"

    argv = build_assembler_argv(
        concat_list,
        narration,
        output,
        total_duration_s=3.5,
        shot_paths=[shot_a, shot_b],
        crossfade_enabled=True,
        crossfade_duration_s=0.25,
        shot_durations_s=[2.0, 2.0],
        resolution=(1080, 1920),
        fps=30,
        video_codec="libx264",
    )

    proc = subprocess.run(argv, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert output.exists() and output.stat().st_size > 0
    assert _probe_resolution(output) == (1080, 1920)


def test_generate_clip_hybrid_path_stitches_mixed_resolution(tmp_path):
    """Spike path (_generate_clip) assembles 720×1280 + 1080×1920 → 1080×1920."""
    import shutil
    from unittest.mock import MagicMock, patch

    from src.image_fetch.base import ImageAsset
    from src.gen_run import _generate_clip
    from tests.test_gen_run import _GenStubConfig, _hybrid_script

    asset = ImageAsset(
        path=str(tmp_path / "still.jpg"),
        source="logo",
        license="CC0",
        source_url="https://example.com",
        width=1080,
        height=1920,
    )
    (tmp_path / "still.jpg").write_bytes(b"x")

    cfg = _GenStubConfig(tmp_path)
    cfg.assembler.crossfade_enabled = True

    shots_dir = tmp_path / "shots"
    shots_dir.mkdir()
    kling = _lavfi_shot(shots_dir, "kling.mp4", "720x1280", 24, 2.0)
    ken_burns = _lavfi_shot(shots_dir, "kenburns.mp4", "1080x1920", 30, 2.0)
    script = _hybrid_script("spike22", "Hybrid normalization")

    def _fake_synthesize(_text, path, **_kwargs):
        src = _lavfi_audio(path.parent, 7.5)
        shutil.copy2(src, path)

    with patch("src.gen_run.resolve_licensed_image", return_value=asset), \
         patch("src.gen_run.generate_shots", return_value=[kling, kling]), \
         patch("src.gen_run._render_real_image_shot", return_value=ken_burns), \
         patch("src.gen_run.synthesize", side_effect=_fake_synthesize), \
         patch("src.gen_run.align", return_value=[{"word": "Hi", "start": 0.0, "end": 0.5}]), \
         patch("src.gen_run.OpenRouterKlingClient"):
        out = _generate_clip(
            script, cfg, MagicMock(), openrouter_api_key="sk-test", dry_run=False,
        )

    assert out is not None
    assert out.exists() and out.stat().st_size > 0
    assert _probe_resolution(out) == (1080, 1920)

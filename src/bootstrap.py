"""
Phase 0 environment health check.

Usage:
    python -m src.bootstrap --check        # verify env, no side effects beyond DB init
    python -m src.bootstrap --init-db      # create state.db with full schema

Each check prints a single line: ✓ <name> or ✗ <name>: <reason>.
Exit code is 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from src.config_loader import load_config
from src.state import connect, initialize_schema


def _ok(name: str, detail: str = "") -> bool:
    print(f"  OK   {name}" + (f"  ({detail})" if detail else ""))
    return True


def _fail(name: str, reason: str) -> bool:
    print(f"  FAIL {name}: {reason}")
    return False


def check_python() -> bool:
    if sys.version_info < (3, 11):
        return _fail("python", f"need 3.11+, got {sys.version_info.major}.{sys.version_info.minor}")
    return _ok("python", f"{sys.version_info.major}.{sys.version_info.minor}")


def check_ffmpeg() -> bool:
    path = shutil.which("ffmpeg")
    if not path:
        return _fail("ffmpeg", "not on PATH")
    try:
        out = subprocess.check_output([path, "-hide_banner", "-encoders"], stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError as e:
        return _fail("ffmpeg", f"failed to query encoders: {e}")
    has_nvenc = "h264_nvenc" in out
    if not has_nvenc:
        return _fail("ffmpeg-nvenc", "h264_nvenc encoder not present (CPU fallback would be slow)")
    return _ok("ffmpeg", f"{path}, h264_nvenc available")


def check_yt_dlp() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError as e:
        return _fail("yt-dlp", str(e))
    return _ok("yt-dlp")


def check_faster_whisper(device: str) -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError as e:
        return _fail("faster-whisper", str(e))
    if device == "cuda":
        try:
            import ctranslate2  # noqa: F401
            cuda_count = ctranslate2.get_cuda_device_count()
        except Exception as e:
            return _fail("faster-whisper-cuda", f"ctranslate2 import failed: {e}")
        if cuda_count == 0:
            return _fail("faster-whisper-cuda", "0 CUDA devices visible — install CUDA 12.x + cuDNN 9")
        return _ok("faster-whisper", f"CUDA devices={cuda_count}")
    return _ok("faster-whisper", "CPU mode")


def check_ollama(host: str, model: str) -> bool:
    try:
        import requests
    except ImportError as e:
        return _fail("ollama", f"requests not installed: {e}")
    try:
        r = requests.get(f"{host.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
    except Exception as e:
        return _fail("ollama", f"cannot reach {host} ({e}); install from https://ollama.com")
    models = [m.get("name", "") for m in r.json().get("models", [])]
    if not any(m.startswith(model.split(":")[0]) for m in models):
        return _fail(
            "ollama-model",
            f"{model} not pulled; run `ollama pull {model}`. Have: {models}",
        )
    return _ok("ollama", f"host={host}, model={model}")


def check_youtube_oauth(client_secrets: Path, oauth_token: Path) -> bool:
    if not client_secrets.exists():
        return _fail(
            "youtube-oauth",
            f"{client_secrets} missing — download OAuth Desktop client from Google Cloud Console",
        )
    if not oauth_token.exists():
        return _fail(
            "youtube-oauth",
            f"{oauth_token} missing — first-time auth not yet run (Phase 5 task)",
        )
    return _ok("youtube-oauth", "client_secrets + cached token present")


def check_gameplay_pool(pool: list[Path]) -> bool:
    missing = [str(p) for p in pool if not p.exists()]
    if missing:
        return _fail("gameplay-pool", f"missing files: {missing}")
    return _ok("gameplay-pool", f"{len(pool)} files")


def check_dirs(cfg) -> bool:
    needed = [
        cfg.abs_path(cfg.paths.raw_dir),
        cfg.abs_path(cfg.paths.transcripts_dir),
        cfg.abs_path(cfg.paths.pending_dir),
        cfg.abs_path(cfg.paths.approved_dir),
        cfg.abs_path(cfg.paths.rejected_dir),
        cfg.abs_path(cfg.paths.dry_run_dir),
        cfg.abs_path(cfg.paths.logs_dir),
    ]
    for d in needed:
        d.mkdir(parents=True, exist_ok=True)
    return _ok("project-dirs", f"{len(needed)} directories ready")


def init_db(cfg) -> None:
    db_path = cfg.abs_path(cfg.paths.state_db)
    conn = connect(db_path)
    initialize_schema(conn)
    conn.close()
    print(f"  OK   state.db initialized at {db_path}")


def run_checks(cfg) -> int:
    print("Media Agent — environment check\n")
    results: list[bool] = []
    results.append(check_python())
    results.append(check_dirs(cfg))
    results.append(check_ffmpeg())
    results.append(check_yt_dlp())
    results.append(check_faster_whisper(cfg.whisper_device))
    results.append(
        check_ollama(
            os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            cfg.ollama_model,
        )
    )
    results.append(
        check_youtube_oauth(
            cfg.abs_path(cfg.paths.client_secrets),
            cfg.abs_path(cfg.paths.oauth_token),
        )
    )
    results.append(
        check_gameplay_pool([cfg.abs_path(p) for p in cfg.gameplay_pool])
    )
    failures = sum(1 for ok in results if not ok)
    print()
    if failures:
        print(f"{failures} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="environment health check")
    parser.add_argument("--init-db", action="store_true", help="initialize state.db schema")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.init_db:
        init_db(cfg)
        return 0

    if args.check or len(sys.argv) == 1:
        return run_checks(cfg)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

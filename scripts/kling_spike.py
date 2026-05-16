"""Pivot.6.1 spike: verify Kling API works end-to-end.

Submits ONE test shot, polls until done, downloads, reports cost.
Run:
    python scripts/kling_spike.py
    python scripts/kling_spike.py --prompt "your prompt" --duration 5 --model kling-v1-6
"""

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add src to path so we can import without installing
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ai_gen.kling import KlingClient
from src.ai_gen.base import GenerationStatus

STYLE_SUFFIX = (
    "3D animated, Pixar-shaded surface, surreal cinematic lighting, "
    "vertical 9:16, photoreal textures with stylized characters, dark moody atmosphere"
)

TEST_PROMPTS = [
    "A microscopic view inside a human blood vessel, red blood cells flowing past camera, dark atmospheric lighting",
    "Deep ocean trench, bioluminescent creatures floating in darkness, slow camera push forward",
    "Close-up of a human eye dilating rapidly, veins visible, eerie ambient light",
    "Ancient bacteria colony multiplying exponentially in slow motion, petri dish perspective",
    "A sleeping human brain seen from inside, neurons firing like lightning storms in dark void",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default=TEST_PROMPTS[0])
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--model", default="kling-v1-6")
    parser.add_argument("--mode", default="std", choices=["std", "pro"])
    parser.add_argument("--no-style-suffix", action="store_true")
    parser.add_argument("--out", default="data/spike_output")
    args = parser.parse_args()

    access_key = os.environ.get("KLING_ACCESS_KEY")
    secret_key = os.environ.get("KLING_SECRET_KEY")
    if not access_key or not secret_key:
        print("ERROR: KLING_ACCESS_KEY and KLING_SECRET_KEY must be set in .env")
        sys.exit(1)

    prompt = args.prompt
    if not args.no_style_suffix:
        prompt = f"{prompt}. {STYLE_SUFFIX}"

    print(f"\n=== Kling spike ===")
    print(f"Model    : {args.model} ({args.mode})")
    print(f"Duration : {args.duration}s")
    print(f"Prompt   : {prompt[:120]}{'...' if len(prompt) > 120 else ''}")
    print()

    client = KlingClient(
        access_key=access_key,
        secret_key=secret_key,
        model_name=args.model,
        mode=args.mode,
    )

    # 1. Submit
    t0 = time.monotonic()
    print("Submitting...", end=" ", flush=True)
    try:
        external_id = client.submit(prompt, duration_s=args.duration, aspect_ratio="9:16")
    except Exception as exc:
        print(f"\nFAILED to submit: {exc}")
        sys.exit(1)
    print(f"task_id={external_id}")

    # 2. Poll
    print("Polling", end="", flush=True)
    result = None
    for _ in range(60):  # max 15 min
        result = client.poll(external_id)
        status = result.status
        if status == GenerationStatus.SUCCEEDED:
            print(" done!")
            break
        elif status == GenerationStatus.FAILED:
            print(f"\nFAILED: {result.error}")
            sys.exit(1)
        else:
            print(".", end="", flush=True)
            time.sleep(15)
    else:
        print("\nTIMEOUT (15 min)")
        sys.exit(1)

    # 3. Download
    elapsed = time.monotonic() - t0
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"spike_{int(time.time())}.mp4"

    print(f"Downloading → {out_path}...", end=" ", flush=True)
    client.download(result.download_url, out_path)
    size_mb = out_path.stat().st_size / 1e6
    print(f"{size_mb:.1f} MB")

    print(f"\nSuccess in {elapsed:.0f}s")
    print(f"Output: {out_path.resolve()}")
    if result.cost_cents is not None:
        print(f"Cost: ${result.cost_cents/100:.4f}")
    print("\nOpen the file and eyeball it against Zack D. Films reference videos.")


if __name__ == "__main__":
    main()

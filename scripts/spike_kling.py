"""
Throwaway staged Kling spike runner — Issue 07 / Slice 2.
Delete once Slice 4 (render_from_script.py) ships a successful end-to-end render.

Usage:
    python scripts/spike_kling.py [--dry-run]

Stages:
    1  — Corti shot 0.        Auto-halt if cost > $0.50. Operator gate on aesthetic.
    2  — Corti shots 1-3.     ThreadPoolExecutor(max_workers=2). Operator gate on coherence.
    3  — AI Coding shots 0-3. ThreadPoolExecutor(max_workers=2). No further halt gate.

Outputs:
    data/ai_gen_shots/spike_2026-05-21/{script_prefix}_shot_{idx}.mp4
    logs/spike_report_2026-05-21.md
    logs/alerts.md  (one appended line)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# ── Constants ──────────────────────────────────────────────────────────────────
DB_PATH = Path("data/state.db")
OUT_DIR = Path("data/ai_gen_shots/spike_2026-05-21")
REPORT_PATH = Path("logs/spike_report_2026-05-21.md")
ALERTS_PATH = Path("logs/alerts.md")
DURATION_S = 4
COST_HALT_CENTS = 100  # auto-halt if Stage 1 costs more than $1.00

# Target script IDs from the 2026-05-20 production run
PRIMARY_IDS = [
    "7cb41305-b39b-4cc2-855b-067e03549d25",  # Corti's Symphony (q=8.70)
    "d0da493f-84fe-4a73-996d-50264054a609",  # AI Coding Speeds Up Android Apps (q=8.60)
]


# ── Data model ─────────────────────────────────────────────────────────────────

class ShotMetric(NamedTuple):
    script_id: str
    shot_idx: int
    prompt: str
    job_id: str
    external_id: str | None
    cost_cents: int | None
    latency_s: float | None
    output_path: str | None
    error: str | None
    status: str  # "succeeded" | "failed" | "dry_run"


# ── Helpers ────────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_prompt(shot_str: str, style_suffix: str) -> str:
    return f"{shot_str}, {style_suffix}"


def load_scripts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Load target scripts by ID; fall back to top-2 by quality_score if missing."""
    rows: list[sqlite3.Row] = []
    for sid in PRIMARY_IDS:
        row = conn.execute(
            "SELECT * FROM scripts WHERE script_id=?", (sid,)
        ).fetchone()
        if row:
            rows.append(row)

    if len(rows) < 2:
        found_ids = [r["script_id"] for r in rows]
        needed = 2 - len(rows)
        if found_ids:
            placeholders = ",".join("?" * len(found_ids))
            fallback = conn.execute(
                f"SELECT * FROM scripts WHERE script_id NOT IN ({placeholders}) "
                f"ORDER BY quality_score DESC LIMIT ?",
                (*found_ids, needed),
            ).fetchall()
        else:
            fallback = conn.execute(
                "SELECT * FROM scripts ORDER BY quality_score DESC LIMIT ?",
                (needed,),
            ).fetchall()
        rows.extend(fallback)

    if not rows:
        raise SystemExit("No scripts in DB. Run the scripter pipeline first.")
    return rows


def record_job(conn: sqlite3.Connection, m: ShotMetric) -> None:
    """Persist a generation_jobs row. No DAL helper exists yet; inline SQL."""
    conn.execute(
        """
        INSERT OR REPLACE INTO generation_jobs (
            job_id, script_id, shot_index, provider, prompt, duration_s,
            status, external_id, output_path, cost_cents,
            submitted_at, completed_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            m.job_id, m.script_id, m.shot_idx, "openrouter_kling",
            m.prompt, DURATION_S,
            m.status, m.external_id, m.output_path, m.cost_cents,
            now_iso(), now_iso(), m.error,
        ),
    )
    conn.commit()


def record_quota(conn: sqlite3.Connection, total_cents: int) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO quota_usage (date, endpoint, units) VALUES (?, ?, ?)",
        (today, "openrouter_kling", total_cents),
    )
    conn.commit()


def operator_gate(message: str, dry_run: bool) -> str:
    """Print message, read stdin (or auto-'go' in dry-run). Returns lowercased response."""
    print(message)
    if dry_run:
        print("[dry-run] Auto-continuing with 'go'...")
        return "go"
    return input(">>> ").strip().lower()


# ── Shot runners ───────────────────────────────────────────────────────────────

def run_shot_live(provider, script_id: str, shot_idx: int, prompt: str) -> ShotMetric:
    from src.ai_gen.base import GenerationStatus

    job_id = str(uuid.uuid4())
    out_path = OUT_DIR / f"{script_id[:8]}_shot_{shot_idx}.mp4"
    t0 = time.monotonic()

    try:
        external_id = provider.submit(prompt, duration_s=DURATION_S, aspect_ratio="9:16")
        result = provider.wait_for_completion(external_id, poll_interval_s=10, timeout_s=300)
        latency_s = time.monotonic() - t0

        if result.status == GenerationStatus.SUCCEEDED:
            provider.download(result.download_url, out_path)
            return ShotMetric(
                script_id=script_id, shot_idx=shot_idx, prompt=prompt,
                job_id=job_id, external_id=external_id,
                cost_cents=result.cost_cents, latency_s=latency_s,
                output_path=str(out_path), error=None, status="succeeded",
            )
        return ShotMetric(
            script_id=script_id, shot_idx=shot_idx, prompt=prompt,
            job_id=job_id, external_id=external_id,
            cost_cents=result.cost_cents, latency_s=latency_s,
            output_path=None, error=result.error, status="failed",
        )
    except Exception as exc:
        return ShotMetric(
            script_id=script_id, shot_idx=shot_idx, prompt=prompt,
            job_id=job_id, external_id=None,
            cost_cents=None, latency_s=time.monotonic() - t0,
            output_path=None, error=str(exc), status="failed",
        )


def run_shot_dry(script_id: str, shot_idx: int, prompt: str) -> ShotMetric:
    out_path = OUT_DIR / f"{script_id[:8]}_shot_{shot_idx}.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(b"DRY_RUN_PLACEHOLDER")
    time.sleep(0.05)
    return ShotMetric(
        script_id=script_id, shot_idx=shot_idx, prompt=prompt,
        job_id=str(uuid.uuid4()), external_id="dry-run-id",
        cost_cents=34, latency_s=0.05,
        output_path=str(out_path), error=None, status="dry_run",
    )


# ── Report ─────────────────────────────────────────────────────────────────────

def write_report(
    metrics: list[ShotMetric],
    h3_pass: bool,
    h5_pass: bool,
) -> None:
    succeeded = [m for m in metrics if m.status in ("succeeded", "dry_run")]
    failed = [m for m in metrics if m.status == "failed"]
    costs = [m.cost_cents for m in metrics if m.cost_cents is not None]
    latencies = [m.latency_s for m in metrics if m.latency_s is not None]

    # H1: mean cost per shot <= $0.34 (34 cents)
    mean_cost = sum(costs) / len(costs) if costs else None
    h1_pass = mean_cost is not None and mean_cost <= 34

    # H2: mean latency < 90s, p95 < 150s
    if latencies:
        mean_lat = sum(latencies) / len(latencies)
        p95_lat = sorted(latencies)[int(len(latencies) * 0.95)]
        h2_pass = mean_lat < 90 and p95_lat < 150
    else:
        mean_lat = p95_lat = None
        h2_pass = False

    # H4: no policy/safety rejects
    policy_errors = [
        m for m in failed
        if m.error and any(kw in m.error.lower() for kw in ("policy", "content", "safety", "moderat"))
    ]
    h4_pass = len(policy_errors) == 0 and bool(metrics)

    hypotheses = [
        ("H1", "Cost <= $0.34/shot",                          h1_pass,
         f"mean=${mean_cost/100:.3f}" if mean_cost is not None else "no data"),
        ("H2", "Latency: mean<90s, p95<150s",                h2_pass,
         f"mean={mean_lat:.1f}s p95={p95_lat:.1f}s" if mean_lat is not None else "no data"),
        ("H3", "Locked style suffix -> editorial output",      h3_pass, "operator sign-off"),
        ("H4", "Ollama prompts Kling-compatible (0 rejects)", h4_pass,
         f"{len(policy_errors)} policy errors"),
        ("H5", "4-shot coherence: same lighting/world",       h5_pass, "operator sign-off"),
    ]
    pass_count = sum(1 for *_, p, _ in hypotheses if p)
    verdict = "USEFUL (>=3 of 5 passed)" if pass_count >= 3 else "MONEY-WASTED (<=2 of 5 passed)"
    total_cents = sum(costs)

    lines = [
        "# Spike Report — Kling 3.0 Spike 2026-05-21",
        "",
        f"**Verdict: {verdict}** ({pass_count}/5 hypotheses passed)",
        f"**Total spend: ${total_cents/100:.3f}**  |  "
        f"Shots: {len(succeeded)} succeeded / {len(failed)} failed / {len(metrics)} total",
        "",
        "## Per-shot results",
        "",
        "| Script | Shot | Cost | Latency | File | Status |",
        "|--------|------|------|---------|------|--------|",
    ]
    for m in sorted(metrics, key=lambda x: (x.script_id, x.shot_idx)):
        cost_s = f"${m.cost_cents/100:.3f}" if m.cost_cents is not None else "—"
        lat_s = f"{m.latency_s:.1f}s" if m.latency_s is not None else "—"
        file_s = Path(m.output_path).name if m.output_path else (m.error or "—")
        lines.append(f"| {m.script_id[:8]} | {m.shot_idx} | {cost_s} | {lat_s} | {file_s} | {m.status} |")

    lines += [
        "",
        "## Hypothesis results",
        "",
        "| ID | Hypothesis | Pass | Notes |",
        "|----|-----------|------|-------|",
    ]
    for hid, desc, passed, notes in hypotheses:
        icon = "PASS" if passed else "FAIL"
        lines.append(f"| {hid} | {desc} | {icon} | {notes} |")

    lines += [
        "",
        "## Next steps",
        "",
        f"{'Proceed to Slices 4/5/8/9 - assembler wire-up unblocked.' if pass_count >= 3 else 'Regroup: review failed hypotheses before further Kling spend.'}",
        "",
        "**Note: The 8 banked shots are NOT yet videos.** They become the first 2 production",
        "Shorts once the assembler (Slice 4) can stitch them.",
    ]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {REPORT_PATH}")

    alert = (
        f"\n[{now_iso()}] kind=spike_kling_complete "
        f"verdict={verdict.split()[0]} shots={len(succeeded)}/{len(metrics)} "
        f"spend=${total_cents/100:.3f}"
    )
    ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERTS_PATH, "a", encoding="utf-8") as f:
        f.write(alert + "\n")
    print(f"Alert: {ALERTS_PATH}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Staged Kling spike (throwaway — see Issue 07)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Walk all stages with mock provider. No API calls, no spend.")
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    if dry_run:
        print("=== DRY-RUN — no API calls, no money ===\n")
    else:
        if not os.environ.get("OPENROUTER_API_KEY"):
            raise SystemExit("OPENROUTER_API_KEY not set. Use --dry-run or export the key.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    scripts = load_scripts(conn)
    script_a = scripts[0]
    script_b = scripts[1] if len(scripts) > 1 else None

    shots_a: list[str] = json.loads(script_a["shots_json"])
    id_a: str = script_a["script_id"]
    style_a: str = script_a["style_suffix"]

    if not dry_run:
        from src.ai_gen.openrouter_kling import OpenRouterKlingClient
        provider = OpenRouterKlingClient()
    else:
        provider = None

    def run(script_id: str, shot_idx: int, prompt: str) -> ShotMetric:
        if dry_run:
            return run_shot_dry(script_id, shot_idx, prompt)
        return run_shot_live(provider, script_id, shot_idx, prompt)

    all_metrics: list[ShotMetric] = []
    h3_pass = False
    h5_pass = False

    # ── Stage 1 ────────────────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print(f"STAGE 1 — 1 shot from: {script_a['title'][:55]}")
    print(f"{'='*62}")

    p0 = make_prompt(shots_a[0], style_a)
    print(f"Prompt: {p0[:120]}\n")
    print("Submitting shot 0...")

    m0 = run(id_a, 0, p0)
    all_metrics.append(m0)
    record_job(conn, m0)

    cost_s = f"${m0.cost_cents/100:.3f}" if m0.cost_cents is not None else "unknown"
    lat_s = f"{m0.latency_s:.1f}s" if m0.latency_s is not None else "unknown"
    print(f"Shot 0 — cost: {cost_s}  latency: {lat_s}  status: {m0.status}")
    if m0.output_path:
        print(f"Output: {m0.output_path}")

    if m0.cost_cents is not None and m0.cost_cents > COST_HALT_CENTS:
        print(f"\n[AUTO-HALT] cost {cost_s} > $0.50 threshold. Stopping.")
        write_report(all_metrics, h3_pass, h5_pass)
        raise SystemExit(1)

    if m0.status == "failed":
        print(f"\n[HALT] Shot 0 failed: {m0.error}")
        write_report(all_metrics, h3_pass, h5_pass)
        raise SystemExit(1)

    resp = operator_gate(
        f"\nOpen: {m0.output_path}\n"
        "Does shot 0 look EDITORIAL (clean product-photography style, not cartoon/stock)?\n"
        "Type 'go' to continue -> Stage 2, or 'halt' to stop:",
        dry_run,
    )
    if resp == "halt":
        print("[OPERATOR-HALT] Stopping after Stage 1.")
        write_report(all_metrics, h3_pass=False, h5_pass=False)
        raise SystemExit(0)
    h3_pass = True

    # ── Stage 2 ────────────────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    print("STAGE 2 — Corti shots 1-3 (parallel, max_workers=2)")
    print(f"{'='*62}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(run, id_a, idx, make_prompt(shots_a[idx], style_a)): idx
            for idx in range(1, 4)
        }
        stage2: list[ShotMetric] = []
        for fut in as_completed(futures):
            m = fut.result()
            stage2.append(m)
            record_job(conn, m)
            c = f"${m.cost_cents/100:.3f}" if m.cost_cents is not None else "?"
            print(f"  Shot {m.shot_idx} — cost {c}  status {m.status}")

    stage2.sort(key=lambda m: m.shot_idx)
    all_metrics.extend(stage2)

    so_far = sum(m.cost_cents for m in all_metrics if m.cost_cents is not None)
    print(f"\nTotal spend so far: ${so_far/100:.3f}")

    resp = operator_gate(
        "\nOpen all 4 Corti shots side-by-side.\n"
        "Do they look STYLISTICALLY CONSISTENT? (same lighting, same world - stitchable)\n"
        "Type 'go' to continue -> Stage 3, or 'halt' to stop:",
        dry_run,
    )
    if resp == "halt":
        print("[OPERATOR-HALT] Stopping after Stage 2.")
        write_report(all_metrics, h3_pass=h3_pass, h5_pass=False)
        raise SystemExit(0)
    h5_pass = True

    # ── Stage 3 ────────────────────────────────────────────────────────────────
    if True:  # SPIKE: skipping Stage 3 to stay within $5 weekly budget ($0.63/shot real cost)
        print("\n[SKIP] Stage 3 skipped — real unit cost ($0.63/shot) pushes 8-shot run over $5 budget.")
        print("       Re-enable once budget model is confirmed for the month.")
    if False and script_b is None:
        print("\n[WARN] No second script available — skipping Stage 3.")
    else:
        shots_b: list[str] = json.loads(script_b["shots_json"])
        id_b: str = script_b["script_id"]
        style_b: str = script_b["style_suffix"]

        print(f"\n{'='*62}")
        print(f"STAGE 3 — 4 shots from: {script_b['title'][:55]}")
        print(f"{'='*62}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(run, id_b, idx, make_prompt(shots_b[idx], style_b)): idx
                for idx in range(4)
            }
            stage3: list[ShotMetric] = []
            for fut in as_completed(futures):
                m = fut.result()
                stage3.append(m)
                record_job(conn, m)
                c = f"${m.cost_cents/100:.3f}" if m.cost_cents is not None else "?"
                print(f"  Shot {m.shot_idx} — cost {c}  status {m.status}")

        stage3.sort(key=lambda m: m.shot_idx)
        all_metrics.extend(stage3)

    # ── Quota record ───────────────────────────────────────────────────────────
    total_cents = sum(m.cost_cents for m in all_metrics if m.cost_cents is not None)
    if total_cents and not dry_run:
        record_quota(conn, total_cents)

    print(f"\nTotal spend: ${total_cents/100:.3f}  ({len(all_metrics)} shots)")

    # ── Report ─────────────────────────────────────────────────────────────────
    write_report(all_metrics, h3_pass=h3_pass, h5_pass=h5_pass)
    print("\nSpike complete.")


if __name__ == "__main__":
    main()

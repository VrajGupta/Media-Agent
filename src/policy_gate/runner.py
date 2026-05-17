"""Policy gate orchestration (Phase 4.5): selected -> policy_pass | rejected_policy.

Per-clip flow:
  status preflight -> load transcript -> build clip text -> evaluate ->
  apply status transition (or fail-soft on infrastructure failure).

Failure handling:
  - missing transcript                    -> error_no_transcript, status unchanged.
  - banlist / profanity / nsfw / hook_sanity content fail
                                          -> rejected_policy, reason="<check>:<value>".
  - all checks pass                       -> policy_pass, reason cleared.
  - Ollama unreachable / contract failure -> status unchanged, alert at run end.
"""

from __future__ import annotations

import functools
import json
import os
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger

from src.config_loader import Config
from src.observability import append_alert
from src.policy_gate import hook_sanity as hook_mod
from src.policy_gate import nsfw as nsfw_mod
from src.policy_gate import topic_filter as topic_mod
from src.policy_gate.evaluator import PolicyVerdict, evaluate_clip_policy
from src.state import Repository
from src.transcripts.clip_text import clip_text_from_words, words_in_clip_window


class PolicyOutcome(str, Enum):
    policy_pass = "policy_pass"
    rejected_policy = "rejected_policy"
    skipped_wrong_status = "skipped_wrong_status"
    skipped_already_gated = "skipped_already_gated"
    skipped_locked = "skipped_locked"               # rendered or scheduled or uploaded
    error_no_transcript = "error_no_transcript"
    infrastructure_failed = "infrastructure_failed"  # Ollama bug; left at 'selected'


@dataclass
class PolicyResult:
    clip_id: str
    outcome: PolicyOutcome
    failed_check: Optional[str] = None
    failed_value: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class _BatchAlerts:
    no_transcript: list[str] = field(default_factory=list)
    infra_failures: list[str] = field(default_factory=list)


def _preflight(row: sqlite3.Row, force: bool) -> Optional[PolicyOutcome]:
    """Return a skip outcome if the clip should bypass the gate, else None."""
    status = row["status"]
    # The standalone CLI never gates downstream clips. The pre-upload re-check
    # uses evaluate_clip_policy directly and is responsible for its own
    # constraints (Phase 5).
    if status in ("rendered", "quality_pass", "rejected_quality", "approved", "uploaded"):
        return PolicyOutcome.skipped_locked
    if status not in ("selected", "policy_pass", "rejected_policy"):
        return PolicyOutcome.skipped_wrong_status
    if status in ("policy_pass", "rejected_policy") and not force:
        return PolicyOutcome.skipped_already_gated
    return None


def _load_transcript_words(transcripts_dir: Path, video_id: str) -> Optional[list[dict]]:
    """Read cached transcript JSON and flatten segments[].words[]."""
    path = transcripts_dir / f"{video_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"transcript unreadable for {video_id}: {exc}")
        return None
    words: list[dict] = []
    for seg in payload.get("segments", []) or []:
        words.extend(seg.get("words") or [])
    return words


def gate_one_clip(
    *,
    repo: Repository,
    cfg: Config,
    clip_id: str,
    force: bool = False,
    dry_run: bool = False,
    nsfw_fn=None,
    hook_fn=None,
    topic_fn=None,
) -> PolicyResult:
    row = repo.conn.execute("SELECT * FROM clips WHERE clip_id=?", (clip_id,)).fetchone()
    if row is None:
        logger.warning(f"clip_id {clip_id} not in DB")
        return PolicyResult(clip_id, PolicyOutcome.skipped_wrong_status, reason="not in DB")

    skip = _preflight(row, force)
    if skip is not None:
        return PolicyResult(clip_id, skip)

    video_id = row["video_id"]
    transcripts_dir = cfg.abs_path(cfg.paths.transcripts_dir)
    all_words = _load_transcript_words(transcripts_dir, video_id)
    if all_words is None:
        return PolicyResult(
            clip_id, PolicyOutcome.error_no_transcript,
            reason="transcript missing or unreadable",
        )

    start_s = float(row["start_s"])
    end_s = float(row["end_s"])
    window_words = words_in_clip_window(all_words, start_s, end_s)
    clip_text = clip_text_from_words(window_words)

    verdict: PolicyVerdict = evaluate_clip_policy(
        cfg,
        clip_text,
        row["suggested_title"] or "",
        nsfw_fn=nsfw_fn,
        hook_fn=hook_fn,
        topic_fn=topic_fn,
    )

    if verdict.infrastructure_failed:
        logger.warning(
            f"policy_gate infrastructure fail for {clip_id}: {verdict.infrastructure_reason}"
        )
        return PolicyResult(
            clip_id,
            PolicyOutcome.infrastructure_failed,
            reason=verdict.infrastructure_reason,
        )

    if not verdict.passed:
        if not dry_run:
            repo.set_clip_status(
                clip_id, "rejected_policy",
                reason=verdict.reason_string,
            )
        logger.info(
            f"rejected_policy {clip_id}: {verdict.reason_string}"
        )
        return PolicyResult(
            clip_id, PolicyOutcome.rejected_policy,
            failed_check=verdict.failed_check,
            failed_value=verdict.failed_value,
            reason=verdict.reason_string,
        )

    if not dry_run:
        repo.set_clip_status(clip_id, "policy_pass", reason=None)
    logger.info(f"policy_pass {clip_id}")
    return PolicyResult(clip_id, PolicyOutcome.policy_pass)


def run_all(
    repo: Repository,
    cfg: Config,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[PolicyResult]:
    ollama_host = os.environ.get("OLLAMA_HOST")
    nsfw_fn = functools.partial(nsfw_mod.classify_nsfw, model=cfg.ollama_model, host=ollama_host)
    hook_fn = functools.partial(hook_mod.rate_hook_sanity, model=cfg.ollama_model, host=ollama_host)
    topic_fn = functools.partial(topic_mod.classify_topic, model=cfg.ollama_model, host=ollama_host)

    if force:
        rows = repo.conn.execute(
            "SELECT clip_id FROM clips "
            "WHERE status IN ('selected','policy_pass','rejected_policy') "
            "ORDER BY clip_id"
        ).fetchall()
    else:
        rows = [r for r in repo.clips_for_policy_gate()]

    if not rows:
        logger.info("policy_gate: no candidates")
        return []

    alert = functools.partial(append_alert, cfg.abs_path(cfg.paths.logs_dir))
    alerts = _BatchAlerts()
    results: list[PolicyResult] = []

    for row in rows:
        result = gate_one_clip(
            repo=repo, cfg=cfg, clip_id=row["clip_id"],
            force=force, dry_run=dry_run,
            nsfw_fn=nsfw_fn, hook_fn=hook_fn, topic_fn=topic_fn,
        )
        results.append(result)
        if result.outcome == PolicyOutcome.error_no_transcript:
            alerts.no_transcript.append(result.clip_id)
        elif result.outcome == PolicyOutcome.infrastructure_failed:
            alerts.infra_failures.append(f"{result.clip_id}: {result.reason}")

    if not dry_run:
        if alerts.no_transcript:
            alert(
                kind="policy_no_transcript",
                message=(
                    f"{len(alerts.no_transcript)} clips lacked a transcript: "
                    f"{alerts.no_transcript[:5]}"
                ),
            )
        if alerts.infra_failures:
            alert(
                kind="policy_ollama_unreachable",
                message=(
                    f"{len(alerts.infra_failures)} clips left at 'selected' "
                    f"after Ollama infrastructure failure; first: {alerts.infra_failures[0]}"
                ),
            )

    summary = {o.value: 0 for o in PolicyOutcome}
    for r in results:
        summary[r.outcome.value] += 1
    summary_str = ", ".join(f"{k}={v}" for k, v in summary.items() if v)
    logger.info(f"policy_gate summary: {summary_str} (total={len(results)})")
    return results

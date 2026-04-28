"""Discovery orchestration: per-keyword and run-all.

Pipeline per keyword:
  cooldown gate -> search.list pagination -> videos.list enrichment
  -> duration filter -> niche-median compute -> virality scoring
  -> threshold filter -> status-preserving upsert + attempt record.

Idempotency:
  - is_in_cooldown short-circuits before any API call.
  - discovery_upsert_video preserves downstream statuses on conflict.
  - The survivor upserts and the attempt record commit together via repo.tx().

dry_run:
  - API calls happen and quota IS recorded (Google bills real units).
  - No videos / niche_baselines / discovery_attempts writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger

from src.config_loader import Config
from src.discovery import enrich as enrich_mod
from src.discovery import search as search_mod
from src.discovery.virality import (
    compute_age_hours,
    compute_niche_median,
    score_virality,
)
from src.observability import append_alert
from src.quota_ledger import QuotaExceeded, QuotaLedger
from src.state import Repository


@dataclass
class KeywordResult:
    keyword: str
    skipped: bool
    fetched: int
    enriched: int
    passed_duration: int
    passed_threshold: int
    inserted: int
    quota_units_used: int


def _quota_units_for(ledger: QuotaLedger, baseline: int) -> int:
    return ledger.today_total() - baseline


def run_for_keyword(
    cfg: Config,
    repo: Repository,
    ledger: QuotaLedger,
    youtube,
    keyword: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> KeywordResult:
    quota_baseline = ledger.today_total()

    if not force and repo.is_in_cooldown(keyword, cfg.discovery_min_interval_hours):
        logger.info(f"skip: cooldown active for '{keyword}' (<{cfg.discovery_min_interval_hours}h since last attempt)")
        return KeywordResult(
            keyword=keyword,
            skipped=True,
            fetched=0,
            enriched=0,
            passed_duration=0,
            passed_threshold=0,
            inserted=0,
            quota_units_used=0,
        )

    tag = "[DRY-RUN] " if dry_run else ""
    logger.info(f"{tag}discovery start: keyword='{keyword}'")

    ids = search_mod.search_video_ids(
        youtube,
        ledger,
        keyword,
        max_inspected=cfg.discovery_max_inspected_per_keyword,
        recency_window_days=cfg.recency_window_days,
        page_size=cfg.search_max_results_per_keyword,
        search_unit_cost=cfg.search_list_unit_cost,
    )
    logger.info(f"{tag}fetched {len(ids)} ids for '{keyword}'")

    metas = enrich_mod.enrich_videos(
        youtube,
        ledger,
        ids,
        videos_unit_cost=cfg.videos_list_unit_cost,
    )
    logger.info(f"{tag}enriched {len(metas)} of {len(ids)} for '{keyword}'")

    long_form = [m for m in metas if m.duration_seconds >= cfg.min_source_duration_seconds]
    logger.info(f"{tag}{len(long_form)} pass duration filter (>={cfg.min_source_duration_seconds}s)")

    historical_views = repo.historical_views_for_keyword(keyword, 30)
    median = compute_niche_median([m.views for m in long_form] + historical_views)
    logger.info(
        f"{tag}niche median for '{keyword}' = {median:,} "
        f"(sample: {len(long_form)} fresh + {len(historical_views)} historical)"
    )

    now_utc = datetime.now(timezone.utc)
    scored: list[tuple] = []
    for m in long_form:
        age_hours = compute_age_hours(m.published_at, now_utc)
        score = score_virality(m.views, age_hours, m.likes, m.comments, median)
        if score >= cfg.virality_score_threshold:
            scored.append((m, score))
    logger.info(f"{tag}{len(scored)} pass virality threshold (>={cfg.virality_score_threshold})")

    if dry_run:
        for m, score in sorted(scored, key=lambda x: -x[1])[:10]:
            logger.info(f"[DRY-RUN]   score={score:.2f}  views={m.views:,}  {m.title[:80]!r}")
        return KeywordResult(
            keyword=keyword,
            skipped=False,
            fetched=len(ids),
            enriched=len(metas),
            passed_duration=len(long_form),
            passed_threshold=len(scored),
            inserted=0,
            quota_units_used=_quota_units_for(ledger, quota_baseline),
        )

    with repo.tx():
        repo.upsert_niche_baseline(keyword, median, len(long_form))
        for m, score in scored:
            repo.discovery_upsert_video(
                video_id=m.video_id,
                title=m.title,
                channel=m.channel,
                duration_seconds=m.duration_seconds,
                views=m.views,
                likes=m.likes,
                comments=m.comments,
                published_at=m.published_at,
                keyword=keyword,
                virality_score=score,
            )
        repo.record_discovery_attempt(
            keyword=keyword,
            inspected_count=len(metas),
            inserted_count=len(scored),
        )

    quota_used = _quota_units_for(ledger, quota_baseline)
    logger.info(f"discovery done: keyword='{keyword}' inserted={len(scored)} quota_used={quota_used}")
    return KeywordResult(
        keyword=keyword,
        skipped=False,
        fetched=len(ids),
        enriched=len(metas),
        passed_duration=len(long_form),
        passed_threshold=len(scored),
        inserted=len(scored),
        quota_units_used=quota_used,
    )


def run_all(
    cfg: Config,
    repo: Repository,
    ledger: QuotaLedger,
    youtube,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[KeywordResult]:
    results: list[KeywordResult] = []
    for keyword in cfg.keywords:
        try:
            result = run_for_keyword(
                cfg, repo, ledger, youtube, keyword, force=force, dry_run=dry_run
            )
        except QuotaExceeded as e:
            logger.warning(f"quota ceiling reached at '{keyword}': {e}")
            append_alert(
                cfg.abs_path(cfg.paths.logs_dir),
                kind="quota_ceiling",
                message=f"discovery aborted at keyword '{keyword}': {e}",
            )
            break
        results.append(result)
    return results

"""Scheduler registration for feature-off US Quote／Intraday materialization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable

from app.config import settings
from app.db.session import SessionLocal
from app.us_market.intraday_maintenance import prune_expired_us_quote_snapshots
from app.us_market.intraday_materializer import (
    USMaterializerProfile,
    materialize_us_intraday_capability,
)
from app.us_market.trading_calendar import US_MARKET_TIMEZONE


logger = logging.getLogger(__name__)


def collect_us_quote_snapshots(*, now: datetime | None = None) -> dict[str, Any]:
    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols=settings.scheduler_us_intraday_materializer_symbols,
        max_symbols=settings.scheduler_us_intraday_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_intraday_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_intraday_materializer_max_external_calls,
        lane_id="equity_research",
        instrument_type="stock",
        now=now,
    )
    logger.info(
        "US Quote materializer status=%s requested=%s refreshed=%s failed=%s "
        "calls=%s duration_ms=%s reason=%s.",
        result["status"],
        result["requested_count"],
        result["refreshed_count"],
        result["failed_count"],
        result["external_call_count"],
        result["duration_ms"],
        result.get("reason"),
    )
    return result


def collect_us_intraday_bars(*, now: datetime | None = None) -> dict[str, Any]:
    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols=settings.scheduler_us_intraday_materializer_symbols,
        max_symbols=settings.scheduler_us_intraday_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_intraday_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_intraday_materializer_max_external_calls,
        lane_id="equity_research",
        instrument_type="stock",
        profile=USMaterializerProfile(
            profile_id="recurring_current",
            intraday_bars=settings.scheduler_us_intraday_materializer_bars,
        ),
        now=now,
    )
    logger.info(
        "US Intraday materializer status=%s requested=%s refreshed=%s failed=%s "
        "calls=%s duration_ms=%s reason=%s.",
        result["status"],
        result["requested_count"],
        result["refreshed_count"],
        result["failed_count"],
        result["external_call_count"],
        result["duration_ms"],
        result.get("reason"),
    )
    return result


def collect_us_index_quote_snapshots(*, now: datetime | None = None) -> dict[str, Any]:
    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols=settings.scheduler_us_index_quote_symbols,
        max_symbols=settings.scheduler_us_index_quote_max_symbols,
        max_provider_calls=2,
        max_external_calls=settings.scheduler_us_index_quote_max_external_calls,
        lane_id="index_current",
        instrument_type="index",
        now=now,
    )
    logger.info(
        "US Index Quote materializer status=%s requested=%s refreshed=%s failed=%s "
        "calls=%s duration_ms=%s reason=%s.",
        result["status"],
        result["requested_count"],
        result["refreshed_count"],
        result["failed_count"],
        result["external_call_count"],
        result["duration_ms"],
        result.get("reason"),
    )
    return result


def cleanup_us_quote_snapshots(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
) -> dict[str, object]:
    db = session_factory()
    try:
        result = prune_expired_us_quote_snapshots(
            db,
            now=now,
            retention_days=settings.us_quote_snapshot_retention_days,
            max_rows=settings.scheduler_us_quote_cleanup_max_rows,
        )
        logger.info(
            "US Quote retention status=%s deleted=%s remaining_expired=%s.",
            result["status"],
            result["deleted_count"],
            result["remaining_expired"],
        )
        return result
    finally:
        db.close()


def add_us_intraday_materializer_jobs(scheduler: Any) -> bool:
    if not settings.enable_scheduler:
        return False

    now = datetime.now(timezone.utc)
    registered = False
    if settings.enable_us_intraday_materializer:
        scheduler.add_job(
            collect_us_quote_snapshots,
            trigger="interval",
            seconds=settings.scheduler_us_quote_materializer_interval_seconds,
            id="us_quote_snapshot_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=10),
        )
        scheduler.add_job(
            collect_us_intraday_bars,
            trigger="interval",
            seconds=settings.scheduler_us_intraday_materializer_interval_seconds,
            id="us_intraday_bar_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=40),
        )
        registered = True
    if settings.enable_us_index_quote_materializer:
        scheduler.add_job(
            collect_us_index_quote_snapshots,
            trigger="interval",
            seconds=settings.scheduler_us_quote_materializer_interval_seconds,
            id="us_index_quote_snapshot_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=20),
        )
        registered = True
    if settings.enable_us_quote_retention_scheduler:
        scheduler.add_job(
            cleanup_us_quote_snapshots,
            trigger="cron",
            hour=3,
            minute=15,
            timezone=US_MARKET_TIMEZONE,
            id="us_quote_snapshot_retention",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        registered = True
    return registered


__all__ = [
    "add_us_intraday_materializer_jobs",
    "cleanup_us_quote_snapshots",
    "collect_us_index_quote_snapshots",
    "collect_us_intraday_bars",
    "collect_us_quote_snapshots",
]

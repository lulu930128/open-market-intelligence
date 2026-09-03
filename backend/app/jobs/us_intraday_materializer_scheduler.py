"""Scheduler registration for feature-off US Quote／Intraday materialization."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
import time
from threading import Lock, Thread
from typing import Any, Callable

from app.config import settings
from app.db.session import SessionLocal
from app.db.models import PortfolioHolding, USWatchlistItem
from app.us_market.intraday_maintenance import prune_expired_us_quote_snapshots
from app.us_market.source_health import snapshot_us_source_health
from app.us_market.intraday_materializer import (
    US_RECURRING_MATERIALIZER_PROFILE,
    materialize_us_intraday_capability,
)
from app.us_market.active_equity_targets import active_us_equity_viewer_symbols
from app.us_market.trading_calendar import US_MARKET_TIMEZONE


logger = logging.getLogger(__name__)
_SCHEDULED_US_ACTIVE_LANE_LOCK = Lock()
_SCHEDULED_US_CANARY_LANE_LOCK = Lock()
_SCHEDULED_US_INDEX_LANE_LOCK = Lock()
_INDEX_BATCH_STATE_LOCK = Lock()
_INDEX_BATCH_OFFSETS = {"quote.snapshot": 0, "intraday.bars": 0}
_READ_MODEL_PUBLISH_LOCK = Lock()
_READ_MODEL_PUBLISH_IN_FLIGHT: set[str] = set()
_READ_MODEL_PUBLISH_MAX_IN_FLIGHT = 4


def _rotating_index_batch(capability: str) -> tuple[str, int, int]:
    configured = list(
        dict.fromkeys(
            value.strip()
            for value in settings.scheduler_us_index_quote_symbols.split(",")
            if value.strip()
        )
    )[: settings.scheduler_us_index_quote_max_symbols]
    if not configured:
        return "", 0, 60
    batch_size = min(
        settings.scheduler_us_index_quote_batch_size
        if capability == "quote.snapshot"
        else settings.scheduler_us_index_intraday_batch_size,
        len(configured),
    )
    with _INDEX_BATCH_STATE_LOCK:
        start = _INDEX_BATCH_OFFSETS[capability] % len(configured)
        batch = [
            configured[(start + offset) % len(configured)]
            for offset in range(batch_size)
        ]
    cycle_count = (len(configured) + batch_size - 1) // batch_size
    full_cycle_seconds = (
        settings.scheduler_us_quote_materializer_interval_seconds
        if capability == "quote.snapshot"
        else settings.scheduler_us_index_intraday_materializer_interval_seconds
    )
    run_interval_seconds = max(5, full_cycle_seconds // cycle_count)
    return ",".join(batch), batch_size, run_interval_seconds


def _advance_index_batch(capability: str, batch_size: int) -> None:
    configured_count = len(
        list(
            dict.fromkeys(
                value.strip()
                for value in settings.scheduler_us_index_quote_symbols.split(",")
                if value.strip()
            )
        )[: settings.scheduler_us_index_quote_max_symbols]
    )
    if configured_count == 0 or batch_size == 0:
        return
    with _INDEX_BATCH_STATE_LOCK:
        _INDEX_BATCH_OFFSETS[capability] = (
            _INDEX_BATCH_OFFSETS[capability] + batch_size
        ) % configured_count


def _equity_canary_universe() -> tuple[str, str]:
    active_symbols = set(active_us_equity_viewer_symbols())
    configured = [
        symbol.strip()
        for symbol in settings.scheduler_us_intraday_materializer_symbols.split(",")
        if symbol.strip() and symbol.strip().upper() not in active_symbols
    ]
    owner = (
        "configuration_canary_minus_active_viewers"
        if active_symbols
        else "configuration_canary"
    )
    return ",".join(configured), owner


def _active_equity_materializer_universe(
    *,
    now: datetime | None = None,
) -> tuple[str, str]:
    ordered = list(active_us_equity_viewer_symbols(now=now))
    owner_parts = ["active_viewer"] if ordered else []

    configured = settings.scheduler_us_active_equity_materializer_symbols
    if settings.enable_us_dynamic_equity_materializer_universe:
        owner_parts.extend(("portfolio", "watchlist"))

        db = SessionLocal()
        try:
            ordered.extend(
                row.symbol
                for row in (
                    db.query(PortfolioHolding)
                    .filter(
                        PortfolioHolding.market == "US",
                        PortfolioHolding.is_active.is_(True),
                    )
                    .order_by(PortfolioHolding.id.asc())
                    .all()
                )
            )
            ordered.extend(
                row.symbol
                for row in (
                    db.query(USWatchlistItem)
                    .filter(USWatchlistItem.enabled.is_(True))
                    .order_by(USWatchlistItem.priority.asc(), USWatchlistItem.id.asc())
                    .all()
                )
            )
        finally:
            db.close()
    if configured.strip():
        ordered.extend(configured.split(","))
        owner_parts.append("configuration_dynamic")
    return ",".join(ordered), "+".join(owner_parts) or "active_equity_empty"


def collect_us_quote_snapshots(*, now: datetime | None = None) -> dict[str, Any]:
    configured_symbols, universe_owner = _equity_canary_universe()
    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols=configured_symbols,
        max_symbols=settings.scheduler_us_intraday_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_intraday_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_intraday_materializer_max_external_calls,
        lane_id="equity_canary",
        instrument_type="stock",
        universe_owner=universe_owner,
        now=now,
        run_lock=_SCHEDULED_US_CANARY_LANE_LOCK,
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
    configured_symbols, universe_owner = _equity_canary_universe()
    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols=configured_symbols,
        max_symbols=settings.scheduler_us_intraday_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_intraday_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_intraday_materializer_max_external_calls,
        lane_id="equity_canary",
        instrument_type="stock",
        universe_owner=universe_owner,
        profile=replace(
            US_RECURRING_MATERIALIZER_PROFILE,
            intraday_bars=settings.scheduler_us_intraday_materializer_bars,
        ),
        now=now,
        run_lock=_SCHEDULED_US_CANARY_LANE_LOCK,
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


def collect_us_active_quote_snapshots(*, now: datetime | None = None) -> dict[str, Any]:
    configured_symbols, universe_owner = _active_equity_materializer_universe(now=now)
    return materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols=configured_symbols,
        max_symbols=settings.scheduler_us_active_equity_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_active_equity_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_active_equity_materializer_max_external_calls,
        lane_id="equity_active",
        instrument_type="stock",
        universe_owner=universe_owner,
        now=now,
        run_lock=_SCHEDULED_US_ACTIVE_LANE_LOCK,
    )


def _publish_intraday_consumer_read_model(symbol: str) -> None:
    """Publish one cache-only projection without extending a producer job."""

    started_at = time.monotonic()
    db = SessionLocal()
    try:
        from app.us_market.service import get_us_intraday_trend

        get_us_intraday_trend(
            symbol=symbol,
            session_scope="regular",
            interval="1m",
            db=db,
            bypass_read_cache=True,
        )
        logger.info(
            "US intraday read-model publish completed symbol=%s duration_ms=%s.",
            symbol,
            int((time.monotonic() - started_at) * 1000),
        )
    except Exception as exc:
        db.rollback()
        logger.warning(
            "US intraday read-model publish failed symbol=%s error_type=%s.",
            symbol,
            type(exc).__name__,
        )
    finally:
        db.close()
        with _READ_MODEL_PUBLISH_LOCK:
            _READ_MODEL_PUBLISH_IN_FLIGHT.discard(symbol)


def _schedule_intraday_consumer_read_model(symbol: str) -> bool:
    """Start one bounded daemon publisher and deduplicate in-flight symbols."""

    with _READ_MODEL_PUBLISH_LOCK:
        if (
            symbol in _READ_MODEL_PUBLISH_IN_FLIGHT
            or len(_READ_MODEL_PUBLISH_IN_FLIGHT)
            >= _READ_MODEL_PUBLISH_MAX_IN_FLIGHT
        ):
            return False
        _READ_MODEL_PUBLISH_IN_FLIGHT.add(symbol)
    try:
        Thread(
            target=_publish_intraday_consumer_read_model,
            args=(symbol,),
            name=f"us-intraday-read-model-{symbol}",
            daemon=True,
        ).start()
    except Exception:
        with _READ_MODEL_PUBLISH_LOCK:
            _READ_MODEL_PUBLISH_IN_FLIGHT.discard(symbol)
        raise
    return True


def _publish_intraday_consumer_read_models(result: dict[str, Any]) -> dict[str, Any]:
    """Schedule bounded cache-only projections after persisted producer truth."""

    successful_symbols = [
        str(item.get("symbol") or "")
        for item in result.get("results", [])
        if item.get("status") == "success" and item.get("symbol")
    ]
    scheduled = [
        symbol
        for symbol in successful_symbols
        if _schedule_intraday_consumer_read_model(symbol)
    ]
    result["consumer_cache_publish_scheduled_count"] = len(scheduled)
    result["consumer_cache_publish_scheduled_symbols"] = scheduled
    result["consumer_cache_publish_deferred_symbols"] = [
        symbol for symbol in successful_symbols if symbol not in scheduled
    ]
    return result


def collect_us_active_intraday_bars(*, now: datetime | None = None) -> dict[str, Any]:
    configured_symbols, universe_owner = _active_equity_materializer_universe(now=now)
    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols=configured_symbols,
        max_symbols=settings.scheduler_us_active_equity_materializer_max_symbols,
        max_provider_calls=settings.scheduler_us_active_equity_materializer_max_provider_calls,
        max_external_calls=settings.scheduler_us_active_equity_materializer_max_external_calls,
        lane_id="equity_active",
        instrument_type="stock",
        universe_owner=universe_owner,
        profile=replace(
            US_RECURRING_MATERIALIZER_PROFILE,
            intraday_bars=settings.scheduler_us_intraday_materializer_bars,
        ),
        now=now,
        run_lock=_SCHEDULED_US_ACTIVE_LANE_LOCK,
    )
    return _publish_intraday_consumer_read_models(result)


def collect_us_index_quote_snapshots(*, now: datetime | None = None) -> dict[str, Any]:
    configured_symbols, batch_size, _run_interval = _rotating_index_batch(
        "quote.snapshot"
    )
    result = materialize_us_intraday_capability(
        "quote.snapshot",
        configured_symbols=configured_symbols,
        max_symbols=max(batch_size, 1),
        max_provider_calls=2,
        max_external_calls=min(
            settings.scheduler_us_index_quote_max_external_calls,
            max(batch_size * 2, 1),
        ),
        lane_id="index_current",
        instrument_type="index",
        universe_owner="configuration_round_robin",
        now=now,
        run_lock=_SCHEDULED_US_INDEX_LANE_LOCK,
    )
    if result.get("reason") != "materializer_run_in_flight":
        _advance_index_batch("quote.snapshot", batch_size)
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


def collect_us_index_intraday_bars(*, now: datetime | None = None) -> dict[str, Any]:
    configured_symbols, batch_size, _run_interval = _rotating_index_batch(
        "intraday.bars"
    )
    result = materialize_us_intraday_capability(
        "intraday.bars",
        configured_symbols=configured_symbols,
        max_symbols=max(batch_size, 1),
        max_provider_calls=2,
        max_external_calls=min(
            settings.scheduler_us_index_intraday_max_external_calls,
            max(batch_size * 2, 1),
        ),
        lane_id="index_current",
        instrument_type="index",
        universe_owner="configuration_round_robin",
        profile=replace(
            US_RECURRING_MATERIALIZER_PROFILE,
            intraday_bars=settings.scheduler_us_index_intraday_materializer_bars,
        ),
        now=now,
        run_lock=_SCHEDULED_US_INDEX_LANE_LOCK,
    )
    if result.get("reason") != "materializer_run_in_flight":
        _advance_index_batch("intraday.bars", batch_size)
    logger.info(
        "US Index Intraday materializer status=%s requested=%s refreshed=%s "
        "failed=%s calls=%s duration_ms=%s reason=%s.",
        result["status"],
        result["requested_count"],
        result["refreshed_count"],
        result["failed_count"],
        result["external_call_count"],
        result["duration_ms"],
        result.get("reason"),
    )
    return _publish_intraday_consumer_read_models(result)


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


def snapshot_us_source_health_job(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
) -> dict[str, Any]:
    """Persist a bounded cache-only health observation; never performs provider IO."""

    db = session_factory()
    try:
        payload = snapshot_us_source_health(db, now=now)
        return {
            "status": "success",
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary") or {},
            "provider_io_performed": False,
        }
    finally:
        db.close()


def add_us_intraday_materializer_jobs(scheduler: Any) -> bool:
    if not us_intraday_materializer_jobs_requested():
        return False

    now = datetime.now(timezone.utc)
    registered = False
    if settings.enable_us_intraday_materializer:
        # Active viewers get an independent owner lane, so long-running index
        # work cannot starve a viewed stock. Quote and intraday serialize
        # inside each owner lane, bounding concurrent provider parsing and
        # SQLite persistence to active, canary, and index work at most.
        scheduler.add_job(
            collect_us_active_quote_snapshots,
            trigger="interval",
            seconds=settings.scheduler_us_quote_materializer_interval_seconds,
            id="us_active_quote_snapshot_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=5),
        )
        scheduler.add_job(
            collect_us_quote_snapshots,
            trigger="interval",
            seconds=settings.scheduler_us_quote_materializer_interval_seconds,
            id="us_quote_snapshot_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=15),
        )
        scheduler.add_job(
            collect_us_active_intraday_bars,
            trigger="interval",
            seconds=settings.scheduler_us_intraday_materializer_interval_seconds,
            id="us_active_intraday_bar_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=35),
        )
        scheduler.add_job(
            collect_us_intraday_bars,
            trigger="interval",
            seconds=settings.scheduler_us_intraday_materializer_interval_seconds,
            id="us_intraday_bar_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=55),
        )
        registered = True
    if settings.enable_us_index_quote_materializer:
        _symbols, _batch_size, quote_run_interval = _rotating_index_batch(
            "quote.snapshot"
        )
        with _INDEX_BATCH_STATE_LOCK:
            _INDEX_BATCH_OFFSETS["quote.snapshot"] = 0
        scheduler.add_job(
            collect_us_index_quote_snapshots,
            trigger="interval",
            seconds=quote_run_interval,
            id="us_index_quote_snapshot_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=30),
        )
        registered = True
    if settings.enable_us_index_intraday_materializer:
        _symbols, _batch_size, intraday_run_interval = _rotating_index_batch(
            "intraday.bars"
        )
        with _INDEX_BATCH_STATE_LOCK:
            _INDEX_BATCH_OFFSETS["intraday.bars"] = 0
        scheduler.add_job(
            collect_us_index_intraday_bars,
            trigger="interval",
            seconds=intraday_run_interval,
            id="us_index_intraday_bar_materialization",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=85),
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
    if settings.enable_us_source_health_snapshot_scheduler:
        scheduler.add_job(
            snapshot_us_source_health_job,
            trigger="interval",
            seconds=settings.scheduler_us_source_health_snapshot_interval_seconds,
            id="us_source_health_snapshot",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=now + timedelta(seconds=110),
        )
        registered = True
    return registered


def us_intraday_materializer_jobs_requested() -> bool:
    """Return whether any independently owned US intraday job is requested."""

    return any(
        (
            settings.enable_us_intraday_materializer,
            settings.enable_us_index_quote_materializer,
            settings.enable_us_index_intraday_materializer,
            settings.enable_us_quote_retention_scheduler,
            settings.enable_us_source_health_snapshot_scheduler,
        )
    )


__all__ = [
    "add_us_intraday_materializer_jobs",
    "cleanup_us_quote_snapshots",
    "collect_us_active_intraday_bars",
    "collect_us_active_quote_snapshots",
    "collect_us_index_quote_snapshots",
    "collect_us_index_intraday_bars",
    "collect_us_intraday_bars",
    "collect_us_quote_snapshots",
    "snapshot_us_source_health_job",
    "us_intraday_materializer_jobs_requested",
]

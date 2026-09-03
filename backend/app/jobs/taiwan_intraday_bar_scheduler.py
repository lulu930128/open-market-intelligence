from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
from threading import Lock
from typing import Any, Callable

from app.config import settings
from app.db.session import SessionLocal
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    taiwan_market_session_phase,
)
from app.market.tw_intraday_capabilities import (
    NSTOCK_INTRADAY_DESCRIPTOR,
    YAHOO_INTRADAY_DESCRIPTOR,
)
from app.market.tw_intraday_universe import (
    resolve_taiwan_intraday_target_universe,
)
from app.market.tw_intraday_platform import (
    project_taiwan_intraday_bars,
    read_taiwan_intraday_bars,
    refresh_taiwan_intraday_bars,
)


logger = logging.getLogger(__name__)

TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES = (25, 30, 33)
TAIWAN_INTRADAY_CLOSE_TAIL_TRIGGER_SECOND = 5
TAIWAN_INTRADAY_CLOSE_TAIL_COOLDOWN_SECONDS = 120
TAIWAN_INTRADAY_CLOSE_TAIL_DESCRIPTORS = (
    NSTOCK_INTRADAY_DESCRIPTOR,
    YAHOO_INTRADAY_DESCRIPTOR,
)
_close_tail_attempts: dict[tuple[str, str], datetime] = {}
_close_tail_attempts_lock = Lock()


def _inside_close_tail_window(local_now: datetime) -> bool:
    clock = local_now.timetz().replace(tzinfo=None)
    return time(13, 25) <= clock < time(13, 35)


def _claim_close_tail_attempt(
    *,
    stock_id: str,
    local_now: datetime,
    attempt_registry: dict[tuple[str, str], datetime] | None = None,
) -> tuple[bool, datetime | None]:
    registry = attempt_registry if attempt_registry is not None else _close_tail_attempts
    key = (local_now.date().isoformat(), stock_id)

    def claim() -> tuple[bool, datetime | None]:
        for stale_key in tuple(registry):
            if stale_key[0] != key[0]:
                registry.pop(stale_key, None)
        last_attempt = registry.get(key)
        retry_at = (
            last_attempt + timedelta(seconds=TAIWAN_INTRADAY_CLOSE_TAIL_COOLDOWN_SECONDS)
            if last_attempt is not None
            else None
        )
        if retry_at is not None and local_now < retry_at:
            return False, retry_at
        registry[key] = local_now
        return True, None

    if attempt_registry is not None:
        return claim()
    with _close_tail_attempts_lock:
        return claim()


def _close_tail_postcondition(
    db: Any,
    result: Any,
    *,
    projector: Callable[..., Any],
) -> dict[str, Any]:
    points, metadata = projector(db, result)
    coverage = dict(metadata.get("series_coverage") or {})
    complete = bool(
        coverage.get("status") == "complete_session"
        and coverage.get("continuous_session_covered") is True
        and int(coverage.get("gap_count") or 0) == 0
    )
    return {
        "complete": complete,
        "coverage_status": coverage.get("status") or "missing",
        "gap_count": int(coverage.get("gap_count") or 0),
        "observed_bar_count": int(coverage.get("observed_bar_count") or len(points)),
        "first_bar_at": coverage.get("first_bar_at"),
        "last_bar_at": coverage.get("last_bar_at"),
        "provider": metadata.get("provider"),
        "source": metadata.get("source"),
        "limitations": list(metadata.get("limitations") or []),
    }


def collect_taiwan_intraday_bars(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
    universe_resolver: Callable[[Any], dict[str, Any]] = (
        resolve_taiwan_intraday_target_universe
    ),
    refresher: Callable[..., Any] = refresh_taiwan_intraday_bars,
) -> dict[str, Any]:
    """Materialize bounded Tier-A Taiwan intraday bars outside read paths."""

    local_now = (now or datetime.now(TAIWAN_TZ)).astimezone(TAIWAN_TZ)
    phase = taiwan_market_session_phase(local_now)
    if not is_taiwan_trading_day(local_now.date()) or phase not in {
        "regular",
        "closing_auction",
    }:
        return {
            "status": "skipped",
            "reason": "outside_taiwan_intraday_acquisition_window",
            "phase": phase,
            "requested_count": 0,
            "refreshed_count": 0,
            "failed_count": 0,
            "results": [],
        }

    db = session_factory()
    try:
        universe = universe_resolver(db)
        symbols = [
            str(symbol).strip().upper()
            for symbol in universe.get("symbols") or []
            if str(symbol).strip()
        ]
        results: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                resolved = refresher(
                    db,
                    stock_id=symbol,
                    interval="1m",
                    range_value="1d",
                    requested_at=local_now,
                )
                results.append(
                    {
                        "stock_id": symbol,
                        "status": "success",
                        "resolved_status": resolved.resolved.health.status.value,
                        "bar_count": len(resolved.resolved.bars),
                    }
                )
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "Taiwan intraday bar refresh failed stock_id=%s: %s",
                    symbol,
                    exc,
                )
                results.append(
                    {
                        "stock_id": symbol,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                    }
                )
        refreshed_count = sum(item["status"] == "success" for item in results)
        failed_count = len(results) - refreshed_count
        return {
            "status": (
                "success"
                if results and failed_count == 0
                else "partial"
                if results
                else "skipped"
            ),
            "reason": None if results else "no_tier_a_symbols",
            "phase": phase,
            "requested_count": len(symbols),
            "eligible_count": int(universe.get("eligible_count") or 0),
            "selected_count": int(universe.get("selected_count") or len(symbols)),
            "skipped_count": int(universe.get("skipped_count") or 0),
            "refreshed_count": refreshed_count,
            "failed_count": failed_count,
            "universe": universe,
            "results": results,
        }
    finally:
        db.close()


def reconcile_taiwan_intraday_close_tails(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
    universe_resolver: Callable[..., dict[str, Any]] = (
        resolve_taiwan_intraday_target_universe
    ),
    reader: Callable[..., Any] = read_taiwan_intraday_bars,
    refresher: Callable[..., Any] = refresh_taiwan_intraday_bars,
    projector: Callable[..., Any] = project_taiwan_intraday_bars,
    attempt_registry: dict[tuple[str, str], datetime] | None = None,
) -> dict[str, Any]:
    """Reconcile a bounded Tier-A regular-session tail outside every GET path."""

    local_now = (now or datetime.now(TAIWAN_TZ)).astimezone(TAIWAN_TZ)
    if not is_taiwan_trading_day(local_now.date()) or not _inside_close_tail_window(
        local_now
    ):
        return {
            "status": "skipped",
            "reason": "outside_taiwan_intraday_close_tail_window",
            "trade_date": local_now.date().isoformat(),
            "requested_count": 0,
            "complete_count": 0,
            "partial_count": 0,
            "failed_count": 0,
            "cooldown_count": 0,
            "refresh_attempt_count": 0,
            "results": [],
        }

    db = session_factory()
    try:
        universe = universe_resolver(
            db,
            max_symbols=settings.scheduler_taiwan_intraday_bar_max_symbols,
        )
        symbols = list(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in universe.get("symbols") or []
                if str(symbol).strip()
            )
        )[: settings.scheduler_taiwan_intraday_bar_max_symbols]
        results: list[dict[str, Any]] = []
        for stock_id in symbols:
            try:
                cached = reader(
                    db,
                    stock_id=stock_id,
                    interval="1m",
                    range_value="1d",
                    requested_at=local_now,
                )
                before = _close_tail_postcondition(
                    db,
                    cached,
                    projector=projector,
                )
                if before["complete"]:
                    results.append(
                        {
                            "stock_id": stock_id,
                            "status": "already_complete",
                            "refresh_attempted": False,
                            "before": before,
                            "after": before,
                        }
                    )
                    continue

                claimed, retry_at = _claim_close_tail_attempt(
                    stock_id=stock_id,
                    local_now=local_now,
                    attempt_registry=attempt_registry,
                )
                if not claimed:
                    results.append(
                        {
                            "stock_id": stock_id,
                            "status": "cooldown",
                            "refresh_attempted": False,
                            "retry_at": retry_at,
                            "before": before,
                            "after": before,
                        }
                    )
                    continue

                refreshed = refresher(
                    db,
                    stock_id=stock_id,
                    interval="1m",
                    range_value="1d",
                    requested_at=local_now,
                    descriptors=TAIWAN_INTRADAY_CLOSE_TAIL_DESCRIPTORS,
                )
                after = _close_tail_postcondition(
                    db,
                    refreshed,
                    projector=projector,
                )
                results.append(
                    {
                        "stock_id": stock_id,
                        "status": "reconciled" if after["complete"] else "partial",
                        "refresh_attempted": True,
                        "before": before,
                        "after": after,
                    }
                )
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "Taiwan intraday close-tail reconciliation failed stock_id=%s: %s",
                    stock_id,
                    exc,
                )
                results.append(
                    {
                        "stock_id": stock_id,
                        "status": "failed",
                        "refresh_attempted": False,
                        "error_type": type(exc).__name__,
                    }
                )

        complete_count = sum(
            item["status"] in {"already_complete", "reconciled"}
            for item in results
        )
        partial_count = sum(item["status"] == "partial" for item in results)
        failed_count = sum(item["status"] == "failed" for item in results)
        cooldown_count = sum(item["status"] == "cooldown" for item in results)
        refresh_attempt_count = sum(
            item.get("refresh_attempted") is True for item in results
        )
        return {
            "status": (
                "success"
                if results and complete_count == len(results)
                else "partial"
                if results
                else "skipped"
            ),
            "reason": None if results else "no_tier_a_symbols",
            "trade_date": local_now.date().isoformat(),
            "requested_count": len(symbols),
            "complete_count": complete_count,
            "partial_count": partial_count,
            "failed_count": failed_count,
            "cooldown_count": cooldown_count,
            "refresh_attempt_count": refresh_attempt_count,
            "universe": universe,
            "results": results,
        }
    finally:
        db.close()


def add_taiwan_intraday_bar_jobs(scheduler: Any) -> bool:
    if not settings.enable_taiwan_intraday_bar_scheduler:
        return False
    interval_seconds = max(
        int(settings.scheduler_taiwan_intraday_bar_interval_seconds),
        60,
    )
    scheduler.add_job(
        collect_taiwan_intraday_bars,
        trigger="interval",
        seconds=interval_seconds,
        id="taiwan_intraday_bar_materialization",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        next_run_time=datetime.now(TAIWAN_TZ) + timedelta(seconds=10),
    )
    for minute in TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES:
        scheduler.add_job(
            reconcile_taiwan_intraday_close_tails,
            trigger="cron",
            day_of_week="mon-fri",
            hour=13,
            minute=minute,
            second=TAIWAN_INTRADAY_CLOSE_TAIL_TRIGGER_SECOND,
            id=f"taiwan_intraday_close_tail_13{minute:02d}",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    return True


__all__ = [
    "TAIWAN_INTRADAY_CLOSE_TAIL_COOLDOWN_SECONDS",
    "TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES",
    "TAIWAN_INTRADAY_CLOSE_TAIL_TRIGGER_SECOND",
    "add_taiwan_intraday_bar_jobs",
    "collect_taiwan_intraday_bars",
    "reconcile_taiwan_intraday_close_tails",
]

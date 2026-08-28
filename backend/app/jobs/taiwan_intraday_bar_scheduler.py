from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Callable

from app.config import settings
from app.db.session import SessionLocal
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    taiwan_market_session_phase,
)
from app.market.tw_intraday_universe import (
    resolve_taiwan_intraday_target_universe,
)
from app.market.tw_intraday_platform import refresh_taiwan_intraday_bars


logger = logging.getLogger(__name__)


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
    return True


__all__ = [
    "add_taiwan_intraday_bar_jobs",
    "collect_taiwan_intraday_bars",
]

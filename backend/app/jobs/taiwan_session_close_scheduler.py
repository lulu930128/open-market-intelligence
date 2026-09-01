from __future__ import annotations

from datetime import datetime, time
from functools import partial
import logging
from typing import Any, Callable

from app.config import settings
from app.db.session import SessionLocal
from app.market.public_quote_platform import (
    acquire_taiwan_session_close,
    project_taiwan_session_close,
    read_taiwan_session_close,
)
from app.market.providers.twse_mis_realtime_acquisition import (
    TwseMisRealtimeAcquisitionAdapter,
)
from app.market.quote_depth import (
    project_taiwan_closing_depth_snapshot,
    resolve_taiwan_stock_quote_phase,
)
from app.market.taiwan_realtime_platform import (
    acquire_taiwan_depth,
    read_taiwan_depth,
)
from app.market.trading_calendar import (
    TAIWAN_TZ,
    is_taiwan_trading_day,
    taiwan_market_session,
)
from app.market.tw_intraday_universe import (
    resolve_taiwan_tier_a_target_plan,
)
from app.market.tw_realtime_capabilities import MIS_ORDER_BOOK_DESCRIPTOR
from app.market_data.contracts import MarketSession
from app.market_data.policies import RealtimePolicy


logger = logging.getLogger(__name__)

TAIWAN_SESSION_CLOSE_RETRY_MINUTES = (30, 31, 32, 33, 34)
TAIWAN_SESSION_CLOSE_TRIGGER_SECOND = 1


def _inside_closeout_window(local_now: datetime) -> bool:
    clock = local_now.timetz().replace(tzinfo=None)
    return time(13, 30, 1) <= clock < time(13, 35)


def _mis_depth_acquisition(local_now: datetime) -> TwseMisRealtimeAcquisitionAdapter:
    return TwseMisRealtimeAcquisitionAdapter(clock=lambda: local_now)


def collect_taiwan_session_closes(
    *,
    now: datetime | None = None,
    session_factory: Callable[[], Any] = SessionLocal,
    universe_resolver: Callable[..., dict[str, Any]] = (
        partial(
            resolve_taiwan_tier_a_target_plan,
            operation_profile="production_session_close",
        )
    ),
    reader: Callable[..., Any] = read_taiwan_session_close,
    acquirer: Callable[..., Any] = acquire_taiwan_session_close,
    projector: Callable[[Any], dict[str, object]] = project_taiwan_session_close,
    depth_reader: Callable[..., Any] = read_taiwan_depth,
    depth_acquirer: Callable[..., Any] = acquire_taiwan_depth,
    depth_projector: Callable[..., dict[str, object]] = (
        project_taiwan_closing_depth_snapshot
    ),
    depth_acquisition_factory: Callable[[datetime], Any] = _mis_depth_acquisition,
) -> dict[str, Any]:
    """Confirm close price/volume and preserve one bounded closing book snapshot."""

    local_now = (now or datetime.now(TAIWAN_TZ)).astimezone(TAIWAN_TZ)
    if (
        not is_taiwan_trading_day(local_now.date())
        or not _inside_closeout_window(local_now)
    ):
        return {
            "status": "skipped",
            "reason": "outside_taiwan_session_closeout_window",
            "trade_date": local_now.date().isoformat(),
            "requested_count": 0,
            "confirmed_count": 0,
            "pending_count": 0,
            "failed_count": 0,
            "depth_snapshot_count": 0,
            "depth_pending_count": 0,
            "depth_failed_count": 0,
            "results": [],
        }

    db = session_factory()
    try:
        universe = universe_resolver(
            db,
            max_symbols=settings.scheduler_taiwan_session_close_max_symbols,
        )
        symbols = [
            str(symbol).strip().upper()
            for symbol in universe.get("symbols") or []
            if str(symbol).strip()
        ][: settings.scheduler_taiwan_session_close_max_symbols]
        results: list[dict[str, Any]] = []
        phase = resolve_taiwan_stock_quote_phase(now=local_now)
        can_acquire_depth = (
            taiwan_market_session(local_now) is MarketSession.CLOSE_RESOLUTION
        )
        for stock_id in symbols:
            try:
                cached = projector(
                    reader(db, stock_id=stock_id, requested_at=local_now)
                )
                already_final = cached.get("available") is True
                projected = (
                    cached
                    if already_final
                    else projector(
                        acquirer(db, stock_id=stock_id, requested_at=local_now)
                    )
                )
                available = projected.get("available") is True
                item: dict[str, Any] = {
                    "stock_id": stock_id,
                    "status": (
                        "already_final"
                        if already_final
                        else "confirmed"
                        if available
                        else "pending"
                    ),
                    "session_close_status": projected.get("status"),
                    "provider": projected.get("provider"),
                    "event_time": projected.get("event_time"),
                    "closing_match_volume_shares": projected.get(
                        "closing_match_volume_shares"
                    ),
                    "session_cumulative_volume_shares": projected.get(
                        "session_cumulative_volume_shares"
                    ),
                    "volume_status": projected.get("volume_status"),
                    "limitations": list(projected.get("limitations") or []),
                }

                try:
                    depth_snapshot = depth_projector(
                        depth_reader(
                            db,
                            stock_id=stock_id,
                            requested_at=local_now,
                        ),
                        phase=phase,
                    )
                    if depth_snapshot.get("available") is not True and can_acquire_depth:
                        depth_snapshot = depth_projector(
                            depth_acquirer(
                                db,
                                stock_id=stock_id,
                                policy=RealtimePolicy.PREFER_LIVE,
                                descriptors=(MIS_ORDER_BOOK_DESCRIPTOR,),
                                acquisition=depth_acquisition_factory(local_now),
                                requested_at=local_now,
                                session=MarketSession.CLOSE_RESOLUTION,
                            ),
                            phase=phase,
                        )
                    item.update(
                        {
                            "depth_snapshot_status": depth_snapshot.get("status"),
                            "depth_snapshot_available": (
                                depth_snapshot.get("available") is True
                            ),
                            "depth_snapshot_provider": depth_snapshot.get("provider"),
                            "depth_snapshot_event_time": depth_snapshot.get("event_time"),
                            "depth_snapshot_bid_level_count": depth_snapshot.get(
                                "bid_level_count", 0
                            ),
                            "depth_snapshot_ask_level_count": depth_snapshot.get(
                                "ask_level_count", 0
                            ),
                        }
                    )
                except Exception as exc:
                    db.rollback()
                    logger.warning(
                        "Taiwan closing depth snapshot failed stock_id=%s: %s",
                        stock_id,
                        exc,
                    )
                    item.update(
                        {
                            "depth_snapshot_status": "failed",
                            "depth_snapshot_available": False,
                            "depth_snapshot_error_type": type(exc).__name__,
                        }
                    )
                results.append(item)
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "Taiwan session closeout failed stock_id=%s: %s",
                    stock_id,
                    exc,
                )
                results.append(
                    {
                        "stock_id": stock_id,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                    }
                )

        confirmed_count = sum(
            item["status"] in {"confirmed", "already_final"}
            for item in results
        )
        pending_count = sum(item["status"] == "pending" for item in results)
        failed_count = sum(item["status"] == "failed" for item in results)
        depth_snapshot_count = sum(
            item.get("depth_snapshot_available") is True for item in results
        )
        depth_failed_count = sum(
            item.get("depth_snapshot_status") == "failed" for item in results
        )
        depth_pending_count = sum(
            item.get("status") != "failed"
            and item.get("depth_snapshot_available") is not True
            and item.get("depth_snapshot_status") != "failed"
            for item in results
        )
        return {
            "status": (
                "success"
                if results
                and confirmed_count == len(results)
                and depth_snapshot_count == len(results)
                else "partial"
                if results
                else "skipped"
            ),
            "reason": None if results else "no_tier_a_symbols",
            "trade_date": local_now.date().isoformat(),
            "requested_count": len(symbols),
            "confirmed_count": confirmed_count,
            "pending_count": pending_count,
            "failed_count": failed_count,
            "depth_snapshot_count": depth_snapshot_count,
            "depth_pending_count": depth_pending_count,
            "depth_failed_count": depth_failed_count,
            "universe": universe,
            "results": results,
        }
    finally:
        db.close()


def add_taiwan_session_close_jobs(scheduler: Any) -> bool:
    if not settings.enable_taiwan_session_close_scheduler:
        return False
    for minute in TAIWAN_SESSION_CLOSE_RETRY_MINUTES:
        scheduler.add_job(
            collect_taiwan_session_closes,
            trigger="cron",
            day_of_week="mon-fri",
            hour=13,
            minute=minute,
            second=TAIWAN_SESSION_CLOSE_TRIGGER_SECOND,
            id=f"taiwan_session_closeout_13{minute:02d}",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    return True


__all__ = [
    "TAIWAN_SESSION_CLOSE_RETRY_MINUTES",
    "TAIWAN_SESSION_CLOSE_TRIGGER_SECOND",
    "add_taiwan_session_close_jobs",
    "collect_taiwan_session_closes",
]

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.db.session import SessionLocal
from app.market.quote_contract_health import (
    resolve_taiwan_quote_contract_universe,
)
from app.market.quote_contract_capture import (
    TAIWAN_QUOTE_CONTRACT_SLOTS,
    capture_taiwan_quote_contract_snapshot,
)
from app.market.trading_calendar import is_taiwan_trading_day


logger = logging.getLogger(__name__)


def _configured_quote_contract_symbols(db: Any) -> list[str]:
    return list(resolve_taiwan_quote_contract_universe(db)["symbols"])


def collect_taiwan_quote_contract_snapshots(
    capture_slot: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if capture_slot not in TAIWAN_QUOTE_CONTRACT_SLOTS:
        raise ValueError(f"Unsupported Taiwan quote capture slot: {capture_slot}")
    local_now = now or datetime.now(ZoneInfo(settings.timezone))
    if not is_taiwan_trading_day(local_now.date()):
        result = {
            "status": "skipped",
            "reason": "not_taiwan_trading_day",
            "capture_slot": capture_slot,
            "trade_date": local_now.date().isoformat(),
            "captured_count": 0,
            "failed_count": 0,
            "results": [],
        }
        logger.info(
            "Taiwan quote contract capture skipped slot=%s date=%s reason=%s.",
            capture_slot,
            result["trade_date"],
            result["reason"],
        )
        return result

    db = SessionLocal()
    try:
        universe = resolve_taiwan_quote_contract_universe(db)
        symbols = list(universe["symbols"])
        contract_context = {
            "version": "tw.quote.scheduler.capture.v1",
            "universe": universe,
            "capture_slot": capture_slot,
            "trade_date": local_now.date().isoformat(),
            "requested_count": len(symbols),
        }
        results = [
            capture_taiwan_quote_contract_snapshot(
                db=db,
                stock_id=stock_id,
                capture_slot=capture_slot,
                now=local_now,
                contract_context=contract_context,
            )
            for stock_id in symbols
        ]
        captured_count = sum(
            str(item.get("capture_status") or "").startswith("captured")
            for item in results
        )
        failed_count = len(results) - captured_count
        status = (
            "success"
            if results and failed_count == 0
            else "partial"
            if results
            else "skipped"
        )
        result = {
            "status": status,
            "reason": None if results else "no_configured_or_watchlist_symbols",
            "capture_slot": capture_slot,
            "trade_date": local_now.date().isoformat(),
            "requested_count": len(symbols),
            "captured_count": captured_count,
            "failed_count": failed_count,
            "universe": universe,
            "symbol_set_digest": universe["symbol_set_digest"],
            "target": universe["target"],
            "results": results,
        }
        logger.info(
            "Taiwan quote contract capture slot=%s date=%s requested=%s "
            "captured=%s failed=%s status=%s.",
            capture_slot,
            result["trade_date"],
            len(symbols),
            captured_count,
            failed_count,
            status,
        )
        return result
    except Exception:
        db.rollback()
        logger.exception(
            "Taiwan quote contract capture failed slot=%s date=%s.",
            capture_slot,
            local_now.date(),
        )
        raise
    finally:
        db.close()


def add_taiwan_quote_contract_snapshot_jobs(scheduler: Any) -> bool:
    if not settings.enable_taiwan_quote_contract_scheduler:
        return False
    for capture_slot in TAIWAN_QUOTE_CONTRACT_SLOTS:
        hour_text, minute_text = capture_slot.split(":", maxsplit=1)
        scheduler.add_job(
            collect_taiwan_quote_contract_snapshots,
            trigger="cron",
            day_of_week="mon-fri",
            hour=int(hour_text),
            minute=int(minute_text),
            kwargs={"capture_slot": capture_slot},
            id=f"taiwan_quote_contract_snapshot_{hour_text}{minute_text}",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    return True

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.db.session import SessionLocal
from app.market.index_contract_snapshot import (
    TAIWAN_INDEX_CONTRACT_IDS,
    TAIWAN_INDEX_CONTRACT_SLOTS,
    capture_taiwan_index_contract_snapshot,
)
from app.market.trading_calendar import is_taiwan_trading_day


logger = logging.getLogger(__name__)


def collect_taiwan_index_contract_snapshots(
    capture_slot: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if capture_slot not in TAIWAN_INDEX_CONTRACT_SLOTS:
        raise ValueError(
            f"Unsupported Taiwan index capture slot: {capture_slot}"
        )
    local_now = now or datetime.now(ZoneInfo(settings.timezone))
    if not is_taiwan_trading_day(local_now.date()):
        return {
            "status": "skipped",
            "reason": "not_taiwan_trading_day",
            "capture_slot": capture_slot,
            "trade_date": local_now.date().isoformat(),
            "captured_count": 0,
            "failed_count": 0,
            "results": [],
        }

    db = SessionLocal()
    try:
        results = [
            capture_taiwan_index_contract_snapshot(
                db,
                index_id=index_id,
                capture_slot=capture_slot,
                now=local_now,
            )
            for index_id in TAIWAN_INDEX_CONTRACT_IDS
        ]
        captured_count = sum(
            item.get("capture_status") == "captured"
            for item in results
        )
        failed_count = len(results) - captured_count
        status = "success" if failed_count == 0 else "partial"
        logger.info(
            "Taiwan index contract capture slot=%s captured=%s failed=%s.",
            capture_slot,
            captured_count,
            failed_count,
        )
        return {
            "status": status,
            "reason": None,
            "capture_slot": capture_slot,
            "trade_date": local_now.date().isoformat(),
            "requested_count": len(TAIWAN_INDEX_CONTRACT_IDS),
            "captured_count": captured_count,
            "failed_count": failed_count,
            "results": results,
        }
    finally:
        db.close()


def add_taiwan_index_contract_snapshot_jobs(scheduler: Any) -> bool:
    if not settings.enable_taiwan_quote_contract_scheduler:
        return False
    for capture_slot in TAIWAN_INDEX_CONTRACT_SLOTS:
        hour_text, minute_text = capture_slot.split(":", maxsplit=1)
        scheduler.add_job(
            collect_taiwan_index_contract_snapshots,
            trigger="cron",
            day_of_week="mon-fri",
            hour=int(hour_text),
            minute=int(minute_text),
            kwargs={"capture_slot": capture_slot},
            id=f"taiwan_index_contract_snapshot_{hour_text}{minute_text}",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
    return True


__all__ = [
    "add_taiwan_index_contract_snapshot_jobs",
    "collect_taiwan_index_contract_snapshots",
]

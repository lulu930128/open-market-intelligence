from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.market.providers.kgi_superpy import (
    KGI_SUPERPY_PROVIDER,
    fetch_kgi_superpy_data_backfill,
)
from app.market.schemas import TaiwanKgiDataBackfillRequest
from app.market.trading_calendar import TAIWAN_TZ


def _overall_status(results: list[dict[str, Any]]) -> str:
    statuses = {str(result.get("status") or "failed") for result in results}
    if statuses <= {"available", "empty"}:
        return "available" if "available" in statuses else "empty"
    if "available" in statuses or "empty" in statuses:
        return "partial"
    if statuses == {"plan_restricted"}:
        return "plan_restricted"
    if statuses == {"disabled"}:
        return "disabled"
    if statuses == {"unavailable"}:
        return "unavailable"
    return "failed"


def backfill_taiwan_kgi_market_data(
    *,
    stock_id: str,
    request: TaiwanKgiDataBackfillRequest,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = str(stock_id or "").strip()
    if not normalized or not normalized.isalnum() or len(normalized) > 16:
        raise ValueError("A valid Taiwan stock symbol is required.")

    requested_at = now or datetime.now(timezone.utc)
    if requested_at.tzinfo is None:
        requested_at = requested_at.replace(tzinfo=timezone.utc)
    target_date: date = request.trade_date or requested_at.astimezone(TAIWAN_TZ).date()
    trade_date_text = target_date.strftime("%Y%m%d")
    results = [
        fetch_kgi_superpy_data_backfill(
            resource=resource,
            stock_id=normalized,
            trade_date=trade_date_text,
            timeframe_minutes=request.timeframe_minutes,
            days=request.price_volume_days,
            limit=request.limit,
        )
        for resource in request.resources
    ]
    warnings = [
        f"{result.get('resource')}: {result.get('error')}"
        for result in results
        if result.get("error")
    ]
    return {
        "kind": "taiwan_kgi_data_backfill",
        "contract_version": "tw-kgi-data-v1",
        "stock_id": normalized,
        "provider": KGI_SUPERPY_PROVIDER,
        "status": _overall_status(results),
        "trade_date": target_date,
        "requested_at": requested_at,
        "provider_request_count": len(results),
        "resources": results,
        "warnings": warnings,
        "persistence": "none_raw_bounded_response",
        "read_path_side_effects": False,
    }


__all__ = ["backfill_taiwan_kgi_market_data"]

"""TWSE MIS provider IO for Taiwan current-session index snapshots."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.market.index_parsers import as_float, as_int, parse_trade_date
from app.market.providers import http_get, twse_mis
from app.market.providers.tw_current_market import CurrentMarketProviderPayload
from app.market.providers.twse_mis_guard import (
    TWSE_MIS_PROVIDER_GUARD,
    response_failure_metadata,
)
from app.market_data.contracts import OperationalStatus


TAIPEI_TZ = timezone(timedelta(hours=8))
_INDEX_CONFIG = {
    "TAIEX": {"symbol": "^TWII", "channel": "tse_t00.tw"},
    "TPEX": {"symbol": "^TWOII", "channel": "otc_o00.tw"},
}


def _snapshot_time(date_text: object, time_text: object) -> str | None:
    if not date_text or not time_text:
        return None
    try:
        text = str(date_text)
        snapshot_date = (
            date(int(text[:4]), int(text[4:6]), int(text[6:8]))
            if len(text) == 8 and text.isdigit()
            else parse_trade_date(text)
        )
        if snapshot_date is None:
            return None
        parts = [int(part) for part in str(time_text).split(":")]
        if len(parts) != 3:
            return None
        return datetime.combine(
            snapshot_date,
            time(parts[0], parts[1], parts[2]),
            tzinfo=TAIPEI_TZ,
        ).isoformat()
    except (TypeError, ValueError):
        return None


def read_twse_mis_current_index(
    scope: str,
    timeout_seconds: int,
) -> CurrentMarketProviderPayload:
    normalized = str(scope or "").strip().upper()
    config = _INDEX_CONFIG.get(normalized)
    if config is None:
        return CurrentMarketProviderPayload(
            payload=None,
            status="failed",
            url=twse_mis.STOCK_INFO_URL,
            error=f"unsupported Taiwan current index: {normalized}",
            operational_status=OperationalStatus.UNAVAILABLE,
            detail_code="UNSUPPORTED_CURRENT_INDEX",
            external_calls=0,
        )
    decision = TWSE_MIS_PROVIDER_GUARD.before_request()
    if not decision.allowed:
        return CurrentMarketProviderPayload(
            payload=None,
            status="rate_limited" if decision.status == "rate_limited" else "cooldown",
            url=twse_mis.STOCK_INFO_URL,
            status_code=429 if decision.status == "rate_limited" else None,
            error=decision.detail_code,
            operational_status=(
                OperationalStatus.RATE_LIMITED
                if decision.status == "rate_limited"
                else OperationalStatus.UNAVAILABLE
            ),
            detail_code=decision.detail_code,
            retry_after_seconds=decision.retry_after_seconds,
            cooldown_until=decision.cooldown_until,
            external_calls=0,
        )
    try:
        message = twse_mis.fetch_index_message(
            config["channel"],
            target=normalized,
            timeout_seconds=timeout_seconds,
            request=http_get,
        )
        event_time = _snapshot_time(
            message.get("d") if message else None,
            (message.get("t") or message.get("%")) if message else None,
        )
        price = as_float(message.get("z")) if message else None
        points = (
            [
                {
                    "time": event_time,
                    "price": price,
                    "volume": as_int(message.get("v") or message.get("m")),
                    "open": as_float(message.get("o")) or price,
                    "high": as_float(message.get("h")) or price,
                    "low": as_float(message.get("l")) or price,
                }
            ]
            if event_time is not None and price is not None and message
            else []
        )
        payload = {
            "stock_id": normalized,
            "symbol": config["symbol"],
            "source": "twse_mis_index_snapshot",
            "provider": "twse_mis",
            "interval": "snapshot",
            "trade_date": event_time[:10] if event_time else None,
            "coverage_status": "single_snapshot" if points else "missing",
            "is_partial": True,
            "volume_unit": None,
            "volume_semantics": "not_provided_for_cash_index",
            "previous_close": as_float(message.get("y")) if message else None,
            "point_count": len(points),
            "points": points,
        }
        TWSE_MIS_PROVIDER_GUARD.record_success()
        return CurrentMarketProviderPayload(
            payload=payload,
            status="available" if points else "missing",
            url=twse_mis.STOCK_INFO_URL,
            operational_status=OperationalStatus.HEALTHY,
            detail_code="TWSE_MIS_INDEX_AVAILABLE",
        )
    except Exception as exc:
        status_code, headers = response_failure_metadata(exc)
        guard = (
            TWSE_MIS_PROVIDER_GUARD.record_http_failure(
                status_code,
                headers=headers,
            )
            if status_code is not None
            else TWSE_MIS_PROVIDER_GUARD.record_failure(
                detail_code=f"TWSE_MIS_{type(exc).__name__.upper()}"
            )
        )
        return CurrentMarketProviderPayload(
            payload=None,
            status="rate_limited" if status_code == 429 else "failed",
            url=twse_mis.STOCK_INFO_URL,
            status_code=status_code,
            error=f"{type(exc).__name__}: {exc}",
            operational_status=(
                OperationalStatus.RATE_LIMITED
                if status_code == 429
                else OperationalStatus.FAILED
            ),
            detail_code=guard.detail_code,
            retry_after_seconds=guard.retry_after_seconds,
            cooldown_until=guard.cooldown_until,
        )


__all__ = ["read_twse_mis_current_index"]

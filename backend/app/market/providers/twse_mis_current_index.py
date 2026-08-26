"""TWSE MIS provider IO for Taiwan current-session index snapshots."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.market.index_parsers import as_float, as_int, parse_trade_date
from app.market.providers import http_get, twse_mis
from app.market.providers.tw_current_market import CurrentMarketProviderPayload


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
        return CurrentMarketProviderPayload(
            payload=payload,
            status="available" if points else "missing",
            url=twse_mis.STOCK_INFO_URL,
        )
    except Exception as exc:
        return CurrentMarketProviderPayload(
            payload=None,
            status="failed",
            url=twse_mis.STOCK_INFO_URL,
            error=f"{type(exc).__name__}: {exc}",
        )


__all__ = ["read_twse_mis_current_index"]

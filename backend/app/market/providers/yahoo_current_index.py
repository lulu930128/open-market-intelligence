"""Yahoo provider IO for Taiwan current-session index snapshots."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.market.index_parsers import as_float, as_int, list_value
from app.market.providers import http_get, yahoo
from app.market.providers.tw_current_market import CurrentMarketProviderPayload


_INDEX_SYMBOLS = {"TAIEX": "^TWII", "TPEX": "^TWOII"}


def read_yahoo_current_index(
    scope: str,
    timeout_seconds: int,
) -> CurrentMarketProviderPayload:
    normalized = str(scope or "").strip().upper()
    symbol = _INDEX_SYMBOLS.get(normalized)
    url = yahoo.CHART_URL.format(symbol=symbol or normalized)
    if symbol is None:
        return CurrentMarketProviderPayload(
            payload=None,
            status="failed",
            url=url,
            error=f"unsupported Taiwan current index: {normalized}",
        )
    try:
        payload = yahoo.fetch_index_chart_payload(
            symbol=symbol,
            range_value="1d",
            interval="1m",
            timeout_seconds=timeout_seconds,
            request=http_get,
        )
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not isinstance(result, dict):
            raise ValueError("Yahoo chart payload has no intraday result")
        meta = result.get("meta") or {}
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        timestamps = result.get("timestamp") or []
        offset = int(meta.get("gmtoffset") or 28800)
        tz = timezone(timedelta(seconds=offset))
        points: list[dict[str, object]] = []
        for index, timestamp in enumerate(timestamps):
            close = as_float(list_value(quote.get("close") or [], index))
            if close is None:
                continue
            points.append(
                {
                    "time": datetime.fromtimestamp(int(timestamp), tz=tz).isoformat(),
                    "price": close,
                    "volume": as_int(list_value(quote.get("volume") or [], index)),
                    "open": as_float(list_value(quote.get("open") or [], index)),
                    "high": as_float(list_value(quote.get("high") or [], index)),
                    "low": as_float(list_value(quote.get("low") or [], index)),
                }
            )
        provider_payload = {
            "stock_id": normalized,
            "symbol": symbol,
            "source": "yahoo_finance_chart",
            "provider": "yahoo_chart",
            "interval": "1m",
            "trade_date": points[-1]["time"][:10] if points else None,
            "coverage_status": "available" if len(points) > 1 else "partial",
            "is_partial": len(points) <= 1,
            "volume_unit": None,
            "volume_semantics": "provider_index_volume_not_market_trade_value",
            "previous_close": as_float(meta.get("chartPreviousClose"))
            or as_float(meta.get("regularMarketPreviousClose")),
            "point_count": len(points),
            "points": points,
        }
        return CurrentMarketProviderPayload(
            payload=provider_payload,
            status="available" if points else "missing",
            url=url,
        )
    except Exception as exc:
        return CurrentMarketProviderPayload(
            payload=None,
            status="failed",
            url=url,
            error=f"{type(exc).__name__}: {exc}",
        )


__all__ = ["read_yahoo_current_index"]

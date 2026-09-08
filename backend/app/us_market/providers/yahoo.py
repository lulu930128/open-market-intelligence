from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.us_market.errors import USMarketDataFetchError
from app.us_market.symbols import normalize_us_symbol

from ._http import get as provider_get


PROVIDER_NAME = "yahoo_chart"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def fetch_yahoo_chart_payload(
    *,
    symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int,
    include_prepost: bool = False,
    resource: str = "daily_price",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[dict[str, Any], str]:
    if (start_at is None) != (end_at is None):
        raise ValueError("start_at and end_at must be provided together")
    period = {"range": range_value}
    if start_at is not None and end_at is not None:
        if start_at.utcoffset() is None or end_at.utcoffset() is None or end_at <= start_at:
            raise ValueError("historical range must be timezone-aware and ordered")
        period = {"period1": int(start_at.timestamp()), "period2": int(end_at.timestamp())}
    normalized_symbol = normalize_us_symbol(symbol)
    response = provider_get(
        YAHOO_CHART_URL.format(symbol=quote(normalized_symbol, safe="")),
        provider=PROVIDER_NAME,
        resource=resource,
        target=normalized_symbol,
        params={
            **period,
            "interval": interval,
            "includePrePost": "true" if include_prepost else "false",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()

    if not isinstance(payload, dict):
        raise USMarketDataFetchError("Yahoo chart returned a non-object JSON payload.")

    return payload, response.url

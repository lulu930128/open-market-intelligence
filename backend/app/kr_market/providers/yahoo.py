from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.kr_market.errors import KRMarketDataFetchError
from app.kr_market.symbols import normalize_kr_symbol

from ._http import get as provider_get


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def fetch_yahoo_chart_payload(
    *,
    symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_kr_symbol(symbol)
    response = provider_get(
        YAHOO_CHART_URL.format(symbol=quote(normalized_symbol, safe="")),
        provider="yahoo_chart",
        resource="daily_price",
        target=normalized_symbol,
        params={
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
        },
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise KRMarketDataFetchError("Yahoo chart returned a non-object JSON payload.")
    return payload, response.url

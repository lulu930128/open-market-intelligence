from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ._http import get


PROVIDER = "yahoo_chart"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_HEADERS = {
    "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
    "Accept": "application/json,text/plain,*/*",
}


def fetch_chart_payload(
    *,
    provider_symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int,
) -> tuple[Any, str]:
    response = get(
        CHART_URL.format(symbol=quote(provider_symbol, safe="")),
        provider=PROVIDER,
        resource="ohlcv",
        target=provider_symbol,
        params={
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
        },
        headers=DEFAULT_HEADERS,
        timeout_seconds=timeout_seconds,
    )
    response.raise_for_status()
    return response.json(), response.url

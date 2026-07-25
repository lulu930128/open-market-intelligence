from __future__ import annotations

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
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_us_symbol(symbol)
    response = provider_get(
        YAHOO_CHART_URL.format(symbol=quote(normalized_symbol, safe="")),
        provider=PROVIDER_NAME,
        resource=resource,
        target=normalized_symbol,
        params={
            "range": range_value,
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

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.jp_market.errors import JPMarketDataFetchError
from app.jp_market.symbols import normalize_jp_symbol

from ._http import get as provider_get


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
YAHOO_QUOTE_SUMMARY_MODULES = (
    "price",
    "assetProfile",
    "summaryDetail",
    "defaultKeyStatistics",
    "financialData",
    "calendarEvents",
)


def fetch_yahoo_chart_payload(
    *,
    symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_jp_symbol(symbol)
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
        raise JPMarketDataFetchError("Yahoo chart returned a non-object JSON payload.")

    return payload, response.url


def fetch_yahoo_quote_summary_payload(
    *,
    symbol: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_jp_symbol(symbol)
    response = provider_get(
        YAHOO_QUOTE_SUMMARY_URL.format(symbol=quote(normalized_symbol, safe="")),
        provider="yahoo_quote_summary",
        resource="fundamentals",
        target=normalized_symbol,
        params={"modules": ",".join(YAHOO_QUOTE_SUMMARY_MODULES)},
        headers={
            "User-Agent": "OpenMarketIntelligence/1.1 (+local development)",
            "Accept": "application/json,text/plain,*/*",
        },
        timeout_seconds=timeout_seconds,
    )
    payload = response.json()

    if not isinstance(payload, dict):
        raise JPMarketDataFetchError("Yahoo quote summary returned a non-object JSON payload.")

    return payload, response.url

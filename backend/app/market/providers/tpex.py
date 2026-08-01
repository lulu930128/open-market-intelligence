from __future__ import annotations

from datetime import date
from typing import Any

from ._http import DEFAULT_HEADERS, ResponseGetter, get, get_json, json_from_response


PROVIDER = "tpex_openapi"
INDEX_5S_PROVIDER = "tpex_index_5s"
DAILY_INDEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_daily_trading_index"
DAILY_QUOTES_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
INDEX_5S_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/miIndex"
MARKET_HIGHLIGHT_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/highlight"


def _resource(url: str) -> str:
    if "indexInfo/miIndex" in url:
        return "index_intraday"
    if "afterTrading/highlight" in url:
        return "market_daily_history"
    if "tpex_3insti_summary" in url:
        return "institutional_summary"
    if "/margin/balance" in url:
        return "margin_balance"
    if "mainboard_quotes" in url:
        return "daily_quotes"
    return "market_daily"


def fetch_json(
    url: str,
    *,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> Any:
    if request is not None:
        response = request(
            url,
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        return json_from_response(response)
    return get_json(
        url,
        provider=PROVIDER,
        resource=_resource(url),
        target="TPEX",
        timeout_seconds=timeout_seconds,
    )


def fetch_index_5s_payload(
    trade_date: date,
    *,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> Any:
    params = {
        "response": "json",
        "date": trade_date.strftime("%Y/%m/%d"),
    }
    if request is not None:
        response = request(
            INDEX_5S_URL,
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        return json_from_response(response)

    return get_json(
        INDEX_5S_URL,
        provider=INDEX_5S_PROVIDER,
        resource="index_intraday",
        target="TPEX",
        params=params,
        timeout_seconds=timeout_seconds,
    )


def fetch_market_highlight_payload(
    trade_date: date,
    *,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> Any:
    params = {
        "response": "json",
        "date": trade_date.strftime("%Y/%m/%d"),
    }
    if request is not None:
        response = request(
            MARKET_HIGHLIGHT_URL,
            params=params,
            headers=DEFAULT_HEADERS,
            timeout=timeout_seconds,
        )
        return json_from_response(response)

    return get_json(
        MARKET_HIGHLIGHT_URL,
        provider=PROVIDER,
        resource="market_daily_history",
        target="TPEX",
        params=params,
        timeout_seconds=timeout_seconds,
    )


def get_response(
    url: str,
    *,
    timeout_seconds: int = 20,
    **kwargs: Any,
):
    return get(
        url,
        provider=PROVIDER,
        resource=_resource(url),
        target="TPEX",
        timeout_seconds=timeout_seconds,
        **kwargs,
    )

from __future__ import annotations

from typing import Any

from ._http import DEFAULT_HEADERS, ResponseGetter, get, get_json, json_from_response


PROVIDER = "tpex_openapi"
DAILY_INDEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_daily_trading_index"
DAILY_QUOTES_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"


def _resource(url: str) -> str:
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

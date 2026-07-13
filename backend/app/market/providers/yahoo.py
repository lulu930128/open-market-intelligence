from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

from ._http import DEFAULT_HEADERS, ResponseGetter, get, json_from_response


PROVIDER = "yahoo_chart"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def fetch_index_chart_payload(
    *,
    symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int = 20,
    request: ResponseGetter | None = None,
) -> dict[str, Any]:
    url = CHART_URL.format(symbol=quote(symbol, safe=""))
    request_kwargs = {
        "params": {
            "range": range_value,
            "interval": interval,
            "includePrePost": "false",
        },
        "headers": DEFAULT_HEADERS,
    }
    if request is not None:
        response = request(url, timeout=timeout_seconds, **request_kwargs)
    else:
        response = get(
            url,
            provider=PROVIDER,
            resource="index_chart",
            target=symbol,
            timeout_seconds=timeout_seconds,
            **request_kwargs,
        )
    payload = json_from_response(response)
    if not isinstance(payload, dict):
        raise ValueError("Yahoo chart returned a non-object JSON payload.")
    return payload


def get_response(
    url: str,
    *,
    timeout_seconds: int = 20,
    **kwargs: Any,
):
    symbol = unquote(url.rstrip("/").rsplit("/", 1)[-1])
    resource = "index_chart" if symbol.startswith("^") else "stock_intraday"
    return get(
        url,
        provider=PROVIDER,
        resource=resource,
        target=symbol or "all",
        timeout_seconds=timeout_seconds,
        **kwargs,
    )

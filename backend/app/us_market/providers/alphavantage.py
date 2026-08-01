from __future__ import annotations

from typing import Any

import requests

from app.us_market.errors import USMarketDataFetchError
from app.us_market.symbols import normalize_us_symbol

from ._http import get as provider_get
from ._http import redact_url_params


PROVIDER_NAME = "alphavantage"
ALPHAVANTAGE_QUERY_URL = "https://www.alphavantage.co/query"


def _payload_or_raise(response: requests.Response) -> dict[str, Any]:
    payload = response.json()

    if not isinstance(payload, dict):
        raise USMarketDataFetchError("Alpha Vantage returned a non-object JSON payload.")

    error_message = (
        payload.get("Error Message")
        or payload.get("Note")
        or payload.get("Information")
    )
    if error_message:
        raise USMarketDataFetchError(str(error_message))

    return payload


def _fetch_payload(
    *,
    function_name: str,
    symbol: str,
    api_key: str,
    resource: str,
    timeout_seconds: int,
    extra_params: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_us_symbol(symbol)
    params = {
        "function": function_name,
        "symbol": normalized_symbol,
    }
    if extra_params:
        params.update(extra_params)
    params["apikey"] = api_key

    response = provider_get(
        ALPHAVANTAGE_QUERY_URL,
        provider=PROVIDER_NAME,
        resource=resource,
        target=normalized_symbol,
        params=params,
        timeout_seconds=timeout_seconds,
    )
    return _payload_or_raise(response), redact_url_params(response.url)


def fetch_alphavantage_daily_payload(
    *,
    symbol: str,
    api_key: str,
    outputsize: str,
    adjusted: bool,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    function_name = "TIME_SERIES_DAILY_ADJUSTED" if adjusted else "TIME_SERIES_DAILY"
    return _fetch_payload(
        function_name=function_name,
        symbol=symbol,
        api_key=api_key,
        resource="daily_price",
        timeout_seconds=timeout_seconds,
        extra_params={"outputsize": outputsize},
    )


def fetch_alphavantage_overview_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    return _fetch_payload(
        function_name="OVERVIEW",
        symbol=symbol,
        api_key=api_key,
        resource="profile",
        timeout_seconds=timeout_seconds,
    )


def fetch_alphavantage_dividends_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    return _fetch_payload(
        function_name="DIVIDENDS",
        symbol=symbol,
        api_key=api_key,
        resource="corporate_actions",
        timeout_seconds=timeout_seconds,
    )


def fetch_alphavantage_splits_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    return _fetch_payload(
        function_name="SPLITS",
        symbol=symbol,
        api_key=api_key,
        resource="corporate_actions",
        timeout_seconds=timeout_seconds,
    )


def fetch_alphavantage_earnings_calendar_csv(
    *,
    api_key: str,
    horizon: str = "3month",
    timeout_seconds: int,
) -> tuple[str, str]:
    response = provider_get(
        ALPHAVANTAGE_QUERY_URL,
        provider=PROVIDER_NAME,
        resource="corporate_events",
        target="all",
        params={
            "function": "EARNINGS_CALENDAR",
            "horizon": horizon,
            "apikey": api_key,
        },
        timeout_seconds=timeout_seconds,
    )
    body = response.text
    if body.lstrip().startswith("{"):
        payload = _payload_or_raise(response)
        raise USMarketDataFetchError(
            f"Alpha Vantage returned JSON instead of an earnings calendar CSV: {payload!r}"
        )
    return body, redact_url_params(response.url)

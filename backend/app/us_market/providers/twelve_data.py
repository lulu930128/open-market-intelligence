"""Bounded Twelve Data REST clients for quote and time-series source readiness."""

from __future__ import annotations

from typing import Any

from app.us_market.symbols import normalize_us_symbol

from ._http import get as provider_get
from ._http import redact_url_params
from .errors import USProviderDataError


PROVIDER_NAME = "twelve_data"
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"


def _payload_or_raise(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise USProviderDataError(
            provider=PROVIDER_NAME,
            code="TWELVE_DATA_NON_OBJECT_PAYLOAD",
            category="schema",
            message="Twelve Data returned a non-object JSON payload.",
        )
    if str(payload.get("status") or "").lower() != "error":
        return payload
    raw_code = payload.get("code")
    message = str(payload.get("message") or "").lower()
    category = (
        "rate_limit"
        if raw_code == 429 or "rate limit" in message
        else "auth"
        if raw_code in {401, 403} or "api key" in message
        else "invalid_symbol"
        if "symbol" in message
        else "provider_error"
    )
    code = {
        "rate_limit": "TWELVE_DATA_RATE_LIMITED",
        "auth": "TWELVE_DATA_AUTH_FAILED",
        "invalid_symbol": "TWELVE_DATA_INVALID_SYMBOL",
        "provider_error": "TWELVE_DATA_PROVIDER_ERROR",
    }[category]
    raise USProviderDataError(
        provider=PROVIDER_NAME,
        code=code,
        category=category,
        message=f"Twelve Data rejected the request: {code}.",
    )


def _get_payload(
    endpoint: str,
    *,
    symbol: str,
    api_key: str,
    resource: str,
    params: dict[str, str],
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_us_symbol(symbol)
    if not api_key.strip():
        raise USProviderDataError(
            provider=PROVIDER_NAME,
            code="TWELVE_DATA_API_KEY_NOT_CONFIGURED",
            category="configuration",
            message="Twelve Data API key is not configured.",
        )
    response = provider_get(
        f"{TWELVE_DATA_BASE_URL}/{endpoint}",
        provider=PROVIDER_NAME,
        resource=resource,
        target=normalized_symbol,
        params={"symbol": normalized_symbol, **params},
        headers={
            "Authorization": f"apikey {api_key}",
            "Accept": "application/json",
        },
        timeout_seconds=timeout_seconds,
    )
    return _payload_or_raise(response.json()), redact_url_params(response.url)


def fetch_twelve_data_quote_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    return _get_payload(
        "quote",
        symbol=symbol,
        api_key=api_key,
        resource="quote",
        params={},
        timeout_seconds=timeout_seconds,
    )


def fetch_twelve_data_time_series_payload(
    *,
    symbol: str,
    api_key: str,
    interval: str,
    outputsize: int,
    timezone_name: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    if outputsize < 1 or outputsize > 5_000:
        raise ValueError("Twelve Data outputsize must be between 1 and 5000")
    return _get_payload(
        "time_series",
        symbol=symbol,
        api_key=api_key,
        resource="intraday_bars",
        params={
            "interval": interval,
            "outputsize": str(outputsize),
            "timezone": timezone_name,
            "order": "ASC",
        },
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "fetch_twelve_data_quote_payload",
    "fetch_twelve_data_time_series_payload",
]

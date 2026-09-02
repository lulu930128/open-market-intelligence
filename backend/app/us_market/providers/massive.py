"""Bounded Massive Indices REST client with secret-safe typed failures."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from app.us_market.market_data.massive_symbols import massive_index_provider_symbol

from ._http import get as provider_get
from .errors import USProviderDataError


PROVIDER_NAME = "massive"
MASSIVE_BASE_URL = "https://api.massive.com"


def _provider_error(*, code: str, category: str) -> USProviderDataError:
    return USProviderDataError(
        provider=PROVIDER_NAME,
        code=code,
        category=category,
        message=f"Massive rejected the request: {code}.",
    )


def _payload_or_raise(payload: Any, *, status_code: int = 200) -> dict[str, Any]:
    if status_code == 429:
        raise _provider_error(code="MASSIVE_RATE_LIMITED", category="rate_limit")
    if status_code == 401:
        raise _provider_error(code="MASSIVE_AUTH_FAILED", category="auth")
    if status_code == 403:
        raise _provider_error(code="MASSIVE_NOT_ENTITLED", category="entitlement")
    if status_code >= 400:
        raise _provider_error(code="MASSIVE_REQUEST_FAILED", category="provider_error")
    if not isinstance(payload, dict):
        raise _provider_error(code="MASSIVE_NON_OBJECT_PAYLOAD", category="schema")

    status = str(payload.get("status") or "").strip().upper()
    if status in {"ERROR", "NOT_AUTHORIZED"}:
        raw = " ".join(
            str(payload.get(name) or "")
            for name in ("error", "message")
        ).upper()
        if "NOT_ENTITLED" in raw or "NOT AUTHORIZED" in raw:
            raise _provider_error(code="MASSIVE_NOT_ENTITLED", category="entitlement")
        if "NOT_FOUND" in raw or "NOT FOUND" in raw:
            raise _provider_error(code="MASSIVE_TICKER_NOT_FOUND", category="invalid_symbol")
        if "API KEY" in raw or "AUTH" in raw:
            raise _provider_error(code="MASSIVE_AUTH_FAILED", category="auth")
        if "LIMIT" in raw or "TOO MANY" in raw:
            raise _provider_error(code="MASSIVE_RATE_LIMITED", category="rate_limit")
        raise _provider_error(code="MASSIVE_PROVIDER_ERROR", category="provider_error")

    results = payload.get("results")
    if isinstance(results, list) and len(results) == 1 and isinstance(results[0], dict):
        item_error = str(results[0].get("error") or "").strip().upper()
        if item_error == "NOT_ENTITLED":
            raise _provider_error(code="MASSIVE_NOT_ENTITLED", category="entitlement")
        if item_error == "NOT_FOUND":
            raise _provider_error(code="MASSIVE_TICKER_NOT_FOUND", category="invalid_symbol")
    return payload


def _get_payload(
    url: str,
    *,
    api_key: str,
    resource: str,
    target: str,
    timeout_seconds: int,
    params: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    token = str(api_key or "").strip()
    if not token:
        raise _provider_error(
            code="MASSIVE_API_KEY_NOT_CONFIGURED",
            category="configuration",
        )
    response = provider_get(
        url,
        provider=PROVIDER_NAME,
        resource=resource,
        target=target,
        params=params,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        timeout_seconds=timeout_seconds,
    )
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise _provider_error(
            code="MASSIVE_INVALID_JSON_PAYLOAD",
            category="schema",
        ) from exc
    return (
        _payload_or_raise(
            payload,
            status_code=int(getattr(response, "status_code", 200)),
        ),
        str(response.url),
    )


def fetch_massive_index_snapshot_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    provider_symbol = massive_index_provider_symbol(symbol)
    return _get_payload(
        f"{MASSIVE_BASE_URL}/v3/snapshot/indices",
        api_key=api_key,
        resource="indices_snapshot",
        target=symbol,
        params={"ticker.any_of": provider_symbol},
        timeout_seconds=timeout_seconds,
    )


def fetch_massive_index_aggregates_payload(
    *,
    symbol: str,
    api_key: str,
    interval: str,
    start_at: datetime,
    end_at: datetime,
    limit: int,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise ValueError("Massive aggregate start_at must be timezone-aware")
    if end_at.tzinfo is None or end_at.utcoffset() is None:
        raise ValueError("Massive aggregate end_at must be timezone-aware")
    if start_at >= end_at:
        raise ValueError("Massive aggregate range must be increasing")
    if limit < 1 or limit > 5_000:
        raise ValueError("Massive aggregate limit must be between 1 and 5000")
    timespan = {"1m": "minute", "1d": "day"}.get(interval)
    if timespan is None:
        raise ValueError("Massive index aggregates support only 1m and 1d")
    provider_symbol = massive_index_provider_symbol(symbol)
    encoded_symbol = quote(provider_symbol, safe="")
    from_value = str(int(start_at.timestamp() * 1000))
    to_value = str(int(end_at.timestamp() * 1000))
    return _get_payload(
        (
            f"{MASSIVE_BASE_URL}/v2/aggs/ticker/{encoded_symbol}/range/"
            f"1/{timespan}/{from_value}/{to_value}"
        ),
        api_key=api_key,
        resource=f"indices_aggregates_{interval}",
        target=symbol,
        params={"adjusted": "false", "sort": "asc", "limit": str(limit)},
        timeout_seconds=timeout_seconds,
    )


def fetch_massive_index_reference_payload(
    *,
    symbol: str,
    api_key: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], str]:
    provider_symbol = massive_index_provider_symbol(symbol)
    return _get_payload(
        f"{MASSIVE_BASE_URL}/v3/reference/tickers",
        api_key=api_key,
        resource="indices_reference",
        target=symbol,
        params={"ticker": provider_symbol, "market": "indices", "active": "true"},
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "fetch_massive_index_aggregates_payload",
    "fetch_massive_index_reference_payload",
    "fetch_massive_index_snapshot_payload",
]

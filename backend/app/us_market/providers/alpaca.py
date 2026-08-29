"""Bounded Alpaca historical stock-bars client."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from app.us_market.symbols import normalize_us_symbol

from ._http import get as provider_get
from .errors import USProviderDataError


PROVIDER_NAME = "alpaca"
ALPACA_STOCK_BARS_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Alpaca request timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _payload_or_raise(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise USProviderDataError(
            provider=PROVIDER_NAME,
            code="ALPACA_NON_OBJECT_PAYLOAD",
            category="schema",
            message="Alpaca returned a non-object JSON payload.",
        )
    message = str(payload.get("message") or "").strip()
    if message and "bars" not in payload:
        lowered = message.lower()
        category = (
            "entitlement"
            if "subscription" in lowered or "permit" in lowered
            else "invalid_symbol"
            if "symbol" in lowered
            else "provider_error"
        )
        code = (
            "ALPACA_PLAN_RESTRICTED"
            if category == "entitlement"
            else "ALPACA_INVALID_SYMBOL"
            if category == "invalid_symbol"
            else "ALPACA_PROVIDER_ERROR"
        )
        raise USProviderDataError(
            provider=PROVIDER_NAME,
            code=code,
            category=category,
            message=f"Alpaca rejected the historical bars request: {code}.",
        )
    return payload


def fetch_alpaca_stock_bars_payload(
    *,
    symbol: str,
    api_key_id: str,
    api_secret_key: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    limit: int,
    feed: str,
    adjustment: str,
    sort: str,
    timeout_seconds: int,
    page_token: str | None = None,
) -> tuple[dict[str, Any], str]:
    normalized_symbol = normalize_us_symbol(symbol)
    if not api_key_id.strip() or not api_secret_key.strip():
        raise USProviderDataError(
            provider=PROVIDER_NAME,
            code="ALPACA_CREDENTIALS_NOT_CONFIGURED",
            category="configuration",
            message="Alpaca credentials are not configured.",
        )
    if limit < 1 or limit > 10_000:
        raise ValueError("Alpaca bars limit must be between 1 and 10000")
    if feed not in {"sip", "iex"}:
        raise ValueError("Alpaca stock bars feed must be sip or iex")
    if adjustment != "raw":
        raise ValueError("OMI Alpaca stock bars require adjustment=raw")
    if sort not in {"asc", "desc"}:
        raise ValueError("Alpaca stock bars sort must be asc or desc")
    params = {
        "timeframe": timeframe,
        "start": _rfc3339(start),
        "end": _rfc3339(end),
        "limit": str(limit),
        "feed": feed,
        "adjustment": adjustment,
        "sort": sort,
    }
    if page_token:
        params["page_token"] = page_token
    response = provider_get(
        ALPACA_STOCK_BARS_URL.format(symbol=quote(normalized_symbol, safe="")),
        provider=PROVIDER_NAME,
        resource="sip_historical_bars",
        target=normalized_symbol,
        params=params,
        headers={
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret_key,
            "Accept": "application/json",
        },
        timeout_seconds=timeout_seconds,
    )
    return _payload_or_raise(response.json()), response.url


__all__ = ["fetch_alpaca_stock_bars_payload"]

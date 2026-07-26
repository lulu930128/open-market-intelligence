from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.crypto_market.contract import (
    BINANCE_PROVIDER,
    BITOPRO_PROVIDER,
    COINGECKO_PROVIDER,
    COINGLASS_PROVIDER,
    OKX_PROVIDER,
)
from app.observability.provider_http import ProviderRequestContext
from app.observability.provider_http import get as provider_get


def _provider(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if "bitopro" in host:
        return BITOPRO_PROVIDER
    if "binance" in host:
        return BINANCE_PROVIDER
    if "okx" in host:
        return OKX_PROVIDER
    if "coinglass" in host:
        return COINGLASS_PROVIDER
    if "coingecko" in host:
        return COINGECKO_PROVIDER
    return "unknown"


def _resource(url: str) -> str:
    path = urlsplit(url).path.lower()
    if "longshort" in path:
        return "long_short_ratio"
    if "liquidation/aggregated-heatmap" in path:
        return "liquidation_heatmap"
    if "liquidation/order" in path:
        return "liquidation_event"
    if "coins/markets" in path:
        return "market_cap"
    if any(token in path for token in ("premiumindex", "openinterest", "funding-rate", "open-interest")):
        return "derivatives"
    if any(token in path for token in ("klines", "candles", "trading-history")):
        return "ohlcv"
    if any(token in path for token in ("depth", "books", "order-book")):
        return "order_book"
    if "ticker" in path:
        return "ticker"
    return "market_data"


def _target(url: str, params: dict[str, Any] | None) -> str:
    values = params or {}
    for key in ("symbol", "instId", "ids"):
        value = values.get(key)
        if value not in (None, ""):
            return str(value)
    path_target = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return path_target or "all"


def request_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: int,
) -> Any:
    response = provider_get(
        ProviderRequestContext(
            market="crypto",
            provider=_provider(url),
            resource=_resource(url),
            target=_target(url, params),
        ),
        url,
        params=params,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


__all__ = ["request_json"]

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.settings.schemas import (
    RefreshExecutionMarketPolicyRead,
    RefreshExecutionMarketsRead,
    RefreshExecutionSettingsRead,
    RefreshExecutionSettingsWrite,
)
from app.settings.store import (
    get_refresh_execution_setting_payload,
    save_refresh_execution_setting_payload,
)


SUPPORTED_REFRESH_EXECUTION_MARKETS = ("tw", "us", "jp", "kr")
REFRESH_EXECUTION_SETTING_KIND = "refresh_execution_settings"
REFRESH_EXECUTION_SETTING_VERSION = "refresh_execution_settings.v1"

_OBSERVED_STOCK_DEFAULTS = {
    "tw": 0.8,
    "us": 12.0,
    "jp": 1.0,
    "kr": 1.0,
}
_SUBRESOURCE_DEFAULTS = {
    "tw": 0.2,
    "us": 12.0,
    "jp": 15.0,
    "kr": 15.0,
}


def get_refresh_execution_settings(
    db: Session | None = None,
) -> RefreshExecutionSettingsRead:
    persisted_settings = get_refresh_execution_setting_payload(db=db)
    source = "database" if persisted_settings is not None else "backend_config"

    return _refresh_execution_settings_response(
        markets=_resolve_refresh_execution_markets(
            persisted_settings=persisted_settings,
        ),
        source=source,
    )


def update_refresh_execution_settings(
    db: Session,
    payload: RefreshExecutionSettingsWrite,
) -> RefreshExecutionSettingsRead:
    settings_payload = _refresh_execution_payload(payload)
    markets = _resolve_refresh_execution_markets(persisted_settings=settings_payload)
    save_refresh_execution_setting_payload(db, settings_payload)

    return _refresh_execution_settings_response(markets=markets, source="database")


def resolve_observed_stock_refresh_interval_seconds(
    *,
    market: str,
    explicit_sleep_seconds: float | None,
    db: Session | None = None,
) -> float:
    if explicit_sleep_seconds is not None:
        return float(explicit_sleep_seconds)

    return _market_policy(
        market=market,
        db=db,
    ).observed_stock_refresh_interval_seconds


def resolve_subresource_refresh_interval_seconds(
    *,
    market: str,
    explicit_sleep_seconds: float | None,
    db: Session | None = None,
) -> float:
    if explicit_sleep_seconds is not None:
        return float(explicit_sleep_seconds)

    return _market_policy(
        market=market,
        db=db,
    ).subresource_refresh_interval_seconds


def resolve_market_refresh_interval_seconds(
    *,
    market: str,
    explicit_sleep_seconds: float | None = None,
    db: Session | None = None,
) -> float:
    if explicit_sleep_seconds is not None:
        return float(explicit_sleep_seconds)

    return _market_policy(
        market=market,
        db=db,
    ).market_refresh_interval_seconds


def _market_policy(
    *,
    market: str,
    db: Session | None,
) -> RefreshExecutionMarketPolicyRead:
    market_key = market.lower().strip()
    if market_key not in SUPPORTED_REFRESH_EXECUTION_MARKETS:
        raise ValueError(f"Unsupported refresh execution market '{market}'.")

    markets = get_refresh_execution_settings(db=db).markets
    return getattr(markets, market_key)


def _refresh_execution_settings_response(
    *,
    markets: RefreshExecutionMarketsRead,
    source: str,
) -> RefreshExecutionSettingsRead:
    return RefreshExecutionSettingsRead(
        kind=REFRESH_EXECUTION_SETTING_KIND,
        version=REFRESH_EXECUTION_SETTING_VERSION,
        source=source,
        markets=markets,
    )


def _resolve_refresh_execution_markets(
    *,
    persisted_settings: Mapping[str, Any] | None,
) -> RefreshExecutionMarketsRead:
    merged = _default_refresh_execution_payload()
    if persisted_settings is not None:
        persisted_markets = persisted_settings.get("markets", persisted_settings)
        if not isinstance(persisted_markets, Mapping):
            raise ValueError("Refresh execution settings must contain a markets mapping.")

        for market in SUPPORTED_REFRESH_EXECUTION_MARKETS:
            market_payload = persisted_markets.get(market)
            if market_payload is None:
                continue
            if not isinstance(market_payload, Mapping):
                raise ValueError(
                    f"Refresh execution settings for market '{market}' must be a mapping."
                )
            for field in merged[market]:
                if field in market_payload:
                    merged[market][field] = market_payload[field]

    return RefreshExecutionMarketsRead(**merged)


def _default_refresh_execution_payload() -> dict[str, dict[str, float]]:
    return {
        "tw": {
            "observed_stock_refresh_interval_seconds": _OBSERVED_STOCK_DEFAULTS["tw"],
            "subresource_refresh_interval_seconds": _SUBRESOURCE_DEFAULTS["tw"],
            "market_refresh_interval_seconds": settings.scheduler_market_refresh_sleep_seconds,
        },
        "us": {
            "observed_stock_refresh_interval_seconds": _OBSERVED_STOCK_DEFAULTS["us"],
            "subresource_refresh_interval_seconds": _SUBRESOURCE_DEFAULTS["us"],
            "market_refresh_interval_seconds": settings.scheduler_us_market_refresh_sleep_seconds,
        },
        "jp": {
            "observed_stock_refresh_interval_seconds": _OBSERVED_STOCK_DEFAULTS["jp"],
            "subresource_refresh_interval_seconds": _SUBRESOURCE_DEFAULTS["jp"],
            "market_refresh_interval_seconds": settings.scheduler_jp_market_refresh_sleep_seconds,
        },
        "kr": {
            "observed_stock_refresh_interval_seconds": _OBSERVED_STOCK_DEFAULTS["kr"],
            "subresource_refresh_interval_seconds": _SUBRESOURCE_DEFAULTS["kr"],
            "market_refresh_interval_seconds": settings.scheduler_kr_market_refresh_sleep_seconds,
        },
    }


def _refresh_execution_payload(payload: RefreshExecutionSettingsWrite) -> dict[str, Any]:
    return {"markets": payload.markets.model_dump()}

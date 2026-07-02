from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.crypto_market.assets import (
    CryptoAssetDefinition,
    SUBSCRIPTION_ALWAYS_ON,
    list_crypto_assets,
)
from app.settings.schemas import (
    MarketDataSubscriptionItemRead,
    MarketDataSubscriptionSettingsRead,
    MarketDataSubscriptionSettingsWrite,
)
from app.settings.store import (
    get_market_data_subscription_setting_payload,
    save_market_data_subscription_setting_payload,
)


MARKET_DATA_SUBSCRIPTION_SETTING_KIND = "market_data_subscription_settings"
MARKET_DATA_SUBSCRIPTION_SETTING_VERSION = "market_data_subscription_settings.v1"

SUBSCRIPTION_MODES = {"always_on", "on_select", "manual", "disabled"}
MANUAL_REFRESH_SUBSCRIPTION_MODES = frozenset({"always_on", "on_select", "manual"})
ALWAYS_ON_SUBSCRIPTION_MODES = frozenset({"always_on"})
MIN_INTERVAL_SECONDS = 1.0
MAX_INTERVAL_SECONDS = 86400.0


def _crypto_resources(asset: CryptoAssetDefinition) -> dict[str, bool]:
    resources = {
        "quote": True,
        "order_book": True,
        "ohlcv": True,
        "market_cap": bool(asset.market_cap),
    }
    if asset.binance_perpetual or asset.okx_perpetual:
        resources["derivatives"] = True
    if asset.binance_perpetual:
        resources["liquidation_event"] = True
        resources["long_short_ratio"] = True
    if asset.taiwan_spread:
        resources["taiwan_spread"] = True
    if asset.asset == "USDT":
        resources["twd_reference"] = True
    return resources


def _crypto_intervals(asset: CryptoAssetDefinition) -> dict[str, float]:
    if asset.default_subscription_mode == SUBSCRIPTION_ALWAYS_ON:
        intervals = {
            "quote_seconds": 5.0,
            "order_book_seconds": 5.0,
            "ohlcv_seconds": 30.0,
            "market_cap_seconds": 900.0,
        }
        if asset.binance_perpetual or asset.okx_perpetual:
            intervals["derivatives_seconds"] = 120.0
        if asset.binance_perpetual:
            intervals["liquidation_event_seconds"] = 5.0
            intervals["long_short_ratio_seconds"] = 300.0
        return intervals

    intervals = {
        "quote_seconds": 15.0,
        "order_book_seconds": 30.0,
        "ohlcv_seconds": 120.0 if asset.asset == "USDT" else 60.0,
        "market_cap_seconds": 900.0,
    }
    if asset.binance_perpetual or asset.okx_perpetual:
        intervals["derivatives_seconds"] = 300.0
    if asset.binance_perpetual:
        intervals["liquidation_event_seconds"] = 15.0
        intervals["long_short_ratio_seconds"] = 900.0
    return intervals


def _crypto_note(asset: CryptoAssetDefinition) -> str:
    if asset.asset == "BTC":
        return "Primary crypto asset; eligible for future trade workflow review."
    if asset.asset == "USDT":
        return "Taiwan USDT/TWD conversion reference."
    return "Watch-only crypto context."


def _crypto_subscription_payloads() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "key": f"crypto:{asset.asset}",
            "market": "crypto",
            "group": "crypto",
            "label": asset.asset,
            "mode": asset.default_subscription_mode,
            "resources": _crypto_resources(asset),
            "intervals": _crypto_intervals(asset),
            "note": _crypto_note(asset),
        }
        for asset in list_crypto_assets()
    )


DEFAULT_RESOURCE_MARKET_DATA_SUBSCRIPTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "commodity:metals:GC",
        "market": "resource",
        "group": "metals",
        "label": "黃金",
        "mode": "manual",
        "resources": {"quote": True, "ohlcv": True},
        "intervals": {"quote_seconds": 60.0, "ohlcv_seconds": 300.0},
        "provider_status": "provider_pending",
        "note": "Watch-only commodity context; provider refresh is not wired yet.",
    },
    {
        "key": "commodity:metals:SI",
        "market": "resource",
        "group": "metals",
        "label": "白銀",
        "mode": "manual",
        "resources": {"quote": True, "ohlcv": True},
        "intervals": {"quote_seconds": 60.0, "ohlcv_seconds": 300.0},
        "provider_status": "provider_pending",
        "note": "Watch-only commodity context; provider refresh is not wired yet.",
    },
    {
        "key": "commodity:metals:HG",
        "market": "resource",
        "group": "metals",
        "label": "銅",
        "mode": "manual",
        "resources": {"quote": True, "ohlcv": True},
        "intervals": {"quote_seconds": 60.0, "ohlcv_seconds": 300.0},
        "provider_status": "provider_pending",
        "note": "Watch-only commodity context; provider refresh is not wired yet.",
    },
    {
        "key": "commodity:energy:CL",
        "market": "resource",
        "group": "energy",
        "label": "WTI 原油",
        "mode": "manual",
        "resources": {"quote": True, "ohlcv": True},
        "intervals": {"quote_seconds": 60.0, "ohlcv_seconds": 300.0},
        "provider_status": "provider_pending",
        "note": "Watch-only commodity context; provider refresh is not wired yet.",
    },
    {
        "key": "commodity:energy:BZ",
        "market": "resource",
        "group": "energy",
        "label": "Brent 原油",
        "mode": "manual",
        "resources": {"quote": True, "ohlcv": True},
        "intervals": {"quote_seconds": 60.0, "ohlcv_seconds": 300.0},
        "provider_status": "provider_pending",
        "note": "Watch-only commodity context; provider refresh is not wired yet.",
    },
    {
        "key": "commodity:energy:NG",
        "market": "resource",
        "group": "energy",
        "label": "天然氣",
        "mode": "manual",
        "resources": {"quote": True, "ohlcv": True},
        "intervals": {"quote_seconds": 60.0, "ohlcv_seconds": 300.0},
        "provider_status": "provider_pending",
        "note": "Watch-only commodity context; provider refresh is not wired yet.",
    },
)

DEFAULT_MARKET_DATA_SUBSCRIPTIONS: tuple[dict[str, Any], ...] = (
    *_crypto_subscription_payloads(),
    *DEFAULT_RESOURCE_MARKET_DATA_SUBSCRIPTIONS,
)


def get_market_data_subscription_settings(
    db: Session | None = None,
) -> MarketDataSubscriptionSettingsRead:
    persisted_settings = get_market_data_subscription_setting_payload(db=db)
    source = "database" if persisted_settings is not None else "backend_config"

    return _market_data_subscription_response(
        items=_resolve_subscription_items(persisted_settings=persisted_settings),
        source=source,
    )


def update_market_data_subscription_settings(
    db: Session,
    payload: MarketDataSubscriptionSettingsWrite,
) -> MarketDataSubscriptionSettingsRead:
    resolved_items = _resolve_subscription_items(
        persisted_settings=_subscription_payload(payload),
    )
    save_market_data_subscription_setting_payload(
        db,
        {
            "items": [
                {
                    "key": item.key,
                    "mode": item.mode,
                    "resources": item.resources,
                    "intervals": item.intervals,
                }
                for item in resolved_items
            ]
        },
    )

    return _market_data_subscription_response(items=resolved_items, source="database")


def get_market_data_subscription_item(
    db: Session | None,
    key: str,
) -> MarketDataSubscriptionItemRead | None:
    normalized_key = key.strip()
    if not normalized_key:
        return None

    settings = get_market_data_subscription_settings(db=db)
    return next((item for item in settings.items if item.key == normalized_key), None)


def market_data_subscription_skip_reason(
    db: Session | None,
    *,
    key: str,
    resource: str,
    allowed_modes: frozenset[str] = MANUAL_REFRESH_SUBSCRIPTION_MODES,
) -> str | None:
    item = get_market_data_subscription_item(db, key)
    normalized_resource = resource.strip()
    if item is None:
        return f"missing data subscription policy for {key}"
    if item.mode not in allowed_modes:
        return f"data subscription mode {item.mode} blocks {normalized_resource}"
    if not item.resources.get(normalized_resource, False):
        return f"data subscription resource {normalized_resource} is disabled for {key}"
    return None


def _market_data_subscription_response(
    *,
    items: list[MarketDataSubscriptionItemRead],
    source: str,
) -> MarketDataSubscriptionSettingsRead:
    return MarketDataSubscriptionSettingsRead(
        kind=MARKET_DATA_SUBSCRIPTION_SETTING_KIND,
        version=MARKET_DATA_SUBSCRIPTION_SETTING_VERSION,
        source=source,
        items=items,
    )


def _resolve_subscription_items(
    *,
    persisted_settings: Mapping[str, Any] | None,
) -> list[MarketDataSubscriptionItemRead]:
    merged = _default_subscription_payload_by_key()
    if persisted_settings is not None:
        persisted_items = persisted_settings.get("items")
        if not isinstance(persisted_items, list):
            raise ValueError("Market data subscription settings must contain an items list.")

        for item_payload in persisted_items:
            if not isinstance(item_payload, Mapping):
                raise ValueError("Each market data subscription item must be a mapping.")

            key = str(item_payload.get("key", "")).strip()
            if not key:
                raise ValueError("Market data subscription item key cannot be empty.")
            if key not in merged:
                continue

            merged_item = merged[key]
            mode = str(item_payload.get("mode", merged_item["mode"])).strip()
            if mode not in SUBSCRIPTION_MODES:
                raise ValueError(f"Unsupported subscription mode '{mode}' for '{key}'.")
            merged_item["mode"] = mode

            resources = item_payload.get("resources")
            if resources is not None:
                if not isinstance(resources, Mapping):
                    raise ValueError(f"Resources for '{key}' must be a mapping.")
                merged_item["resources"] = _merge_resources(
                    default_resources=merged_item["resources"],
                    resource_payload=resources,
                    key=key,
                )

            intervals = item_payload.get("intervals")
            if intervals is not None:
                if not isinstance(intervals, Mapping):
                    raise ValueError(f"Intervals for '{key}' must be a mapping.")
                merged_item["intervals"] = _merge_intervals(
                    default_intervals=merged_item["intervals"],
                    interval_payload=intervals,
                    key=key,
                )

    return [
        MarketDataSubscriptionItemRead(**merged[item["key"]])
        for item in DEFAULT_MARKET_DATA_SUBSCRIPTIONS
    ]


def _default_subscription_payload_by_key() -> dict[str, dict[str, Any]]:
    return {
        str(item["key"]): deepcopy(item)
        for item in DEFAULT_MARKET_DATA_SUBSCRIPTIONS
    }


def _merge_resources(
    *,
    default_resources: Mapping[str, Any],
    resource_payload: Mapping[str, Any],
    key: str,
) -> dict[str, bool]:
    merged = {str(name): bool(value) for name, value in default_resources.items()}
    for resource_key, value in resource_payload.items():
        resource_name = str(resource_key).strip()
        if resource_name not in merged:
            continue
        if not isinstance(value, bool):
            raise ValueError(
                f"Resource flag '{resource_name}' for '{key}' must be a boolean."
            )
        merged[resource_name] = value
    return merged


def _merge_intervals(
    *,
    default_intervals: Mapping[str, Any],
    interval_payload: Mapping[str, Any],
    key: str,
) -> dict[str, float]:
    merged = {str(name): float(value) for name, value in default_intervals.items()}
    for interval_key, value in interval_payload.items():
        interval_name = str(interval_key).strip()
        if interval_name not in merged:
            continue
        try:
            interval_value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Interval '{interval_name}' for '{key}' must be numeric."
            ) from exc
        if (
            not math.isfinite(interval_value)
            or interval_value < MIN_INTERVAL_SECONDS
            or interval_value > MAX_INTERVAL_SECONDS
        ):
            raise ValueError(
                f"Interval '{interval_name}' for '{key}' must be between "
                f"{MIN_INTERVAL_SECONDS:g} and {MAX_INTERVAL_SECONDS:g} seconds."
            )
        merged[interval_name] = interval_value
    return merged


def _subscription_payload(
    payload: MarketDataSubscriptionSettingsWrite,
) -> dict[str, Any]:
    return {"items": [item.model_dump() for item in payload.items]}

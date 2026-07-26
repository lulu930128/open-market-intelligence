from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.crypto_market.assets import CryptoAssetDefinition, list_crypto_assets
from app.crypto_market.auto_refresh import crypto_auto_refresh_status
from app.crypto_market.contract import PERPETUAL, SPOT, list_provider_instruments
from app.crypto_market.source_health import build_crypto_source_health
from app.crypto_market.watchlist import list_crypto_watchlist_items
from app.crypto_market.ws_runtime import crypto_realtime_collector_status
from app.settings.market_data_subscription import get_market_data_subscription_settings


@dataclass(frozen=True)
class CryptoWorkspaceSlotSpec:
    key: str
    tier: str
    resources: tuple[str, ...]
    event_driven: bool = False
    provider_pending: bool = False


CORE_SLOT_SPECS: tuple[CryptoWorkspaceSlotSpec, ...] = (
    CryptoWorkspaceSlotSpec("spot_quote", "core", ("crypto_ticker",)),
    CryptoWorkspaceSlotSpec("order_book", "core", ("crypto_order_book",)),
    CryptoWorkspaceSlotSpec("ohlcv", "core", ("crypto_ohlcv",)),
    CryptoWorkspaceSlotSpec("derivatives", "core", ("crypto_derivatives",)),
    CryptoWorkspaceSlotSpec("market_cap", "core", ("crypto_market_cap",)),
)

SUPPORT_SLOT_SPECS: tuple[CryptoWorkspaceSlotSpec, ...] = (
    CryptoWorkspaceSlotSpec("taiwan_spread", "context", ("crypto_spread",)),
    CryptoWorkspaceSlotSpec("long_short_ratio", "advanced", ("crypto_long_short_ratio",)),
    CryptoWorkspaceSlotSpec(
        "liquidation_event",
        "advanced",
        ("crypto_liquidation_event",),
        event_driven=True,
    ),
    CryptoWorkspaceSlotSpec(
        "liquidation_heatmap",
        "advanced",
        ("crypto_liquidation_heatmap",),
        event_driven=True,
    ),
    CryptoWorkspaceSlotSpec(
        "cvd",
        "advanced",
        ("crypto_cvd_spot", "crypto_cvd_perpetual"),
        provider_pending=True,
    ),
)

MIN_OHLCV_ROWS_PER_PROVIDER = 100


def _latest_timestamp(entries: list[dict[str, Any]]) -> str | None:
    timestamps = [
        str(entry["latest_fetched_at"])
        for entry in entries
        if entry.get("latest_fetched_at")
    ]
    return max(timestamps) if timestamps else None


def _slot_applicable(asset: CryptoAssetDefinition, key: str) -> bool:
    has_spot = bool(asset.local_twd_provider_symbol or asset.binance_spot or asset.okx_spot)
    has_perpetual = bool(asset.binance_perpetual or asset.okx_perpetual)
    if key in {"spot_quote", "order_book", "ohlcv"}:
        return has_spot
    if key == "derivatives":
        return has_perpetual
    if key == "market_cap":
        return asset.market_cap
    if key == "taiwan_spread":
        return asset.taiwan_spread
    if key in {"long_short_ratio", "liquidation_event"}:
        return asset.binance_perpetual
    if key == "liquidation_heatmap":
        return has_perpetual
    if key == "cvd":
        return asset.binance_spot or asset.binance_perpetual
    return False


def _provider_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "provider": str(entry.get("provider") or "unknown"),
            "target": str(entry.get("target") or ""),
            "status": str(entry.get("status") or "unknown"),
            "row_count": int(entry.get("row_count") or 0),
            "latest_fetched_at": entry.get("latest_fetched_at"),
        }
        for entry in entries
    ]


def _build_slot(
    asset: CryptoAssetDefinition,
    spec: CryptoWorkspaceSlotSpec,
    health_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    applicable = _slot_applicable(asset, spec.key)
    entries = [
        entry
        for entry in health_entries
        if str(entry.get("resource") or "") in spec.resources
    ]
    row_count = sum(int(entry.get("row_count") or 0) for entry in entries)
    latest_fetched_at = _latest_timestamp(entries)

    if not applicable:
        status = "not_applicable"
        reason = "The backend provider contract does not define this resource for the asset."
    elif spec.provider_pending and row_count <= 0:
        status = "provider_pending"
        reason = "The resource contract exists, but no production refresh path is connected yet."
    elif spec.key == "liquidation_heatmap" and not asset.binance_perpetual and row_count <= 0:
        status = "api_key_required"
        reason = "Processed heatmap coverage requires a configured provider; no local event fallback applies."
    elif spec.event_driven and row_count <= 0:
        status = "event_quiet"
        reason = "The event-driven resource is connected, but no matching local events are stored."
    else:
        statuses = {str(entry.get("status") or "unknown") for entry in entries}
        live_count = sum(1 for entry in entries if entry.get("ok") or entry.get("status") == "live")
        if (
            spec.key == "ohlcv"
            and entries
            and live_count == len(entries)
            and any(int(entry.get("row_count") or 0) < MIN_OHLCV_ROWS_PER_PROVIDER for entry in entries)
        ):
            status = "partial"
            reason = (
                "Fresh OHLCV rows exist, but at least one provider has fewer than "
                f"{MIN_OHLCV_ROWS_PER_PROVIDER} cached bars."
            )
        elif entries and live_count == len(entries):
            status = "ready"
            reason = "All contracted provider rows are within the configured freshness threshold."
        elif live_count > 0:
            status = "partial"
            reason = "At least one provider is current while another provider is stale or missing."
        elif spec.event_driven and row_count > 0 and statuses <= {"stale", "empty"}:
            status = "event_quiet"
            reason = "Historical events exist, but the event stream has been quiet beyond the freshness window."
        elif "stale" in statuses:
            status = "stale"
            reason = "Local rows exist, but none are within the configured freshness threshold."
        else:
            status = "missing"
            reason = "No local rows are available for the contracted resource."

    return {
        "key": spec.key,
        "tier": spec.tier,
        "status": status,
        "applicable": applicable,
        "row_count": row_count,
        "provider_count": len(entries),
        "ready_provider_count": sum(
            1 for entry in entries if entry.get("ok") or entry.get("status") == "live"
        ),
        "latest_fetched_at": latest_fetched_at,
        "providers": _provider_rows(entries),
        "reason": reason,
    }


def _slot_summary(slots: list[dict[str, Any]], *, tier: str) -> dict[str, int]:
    tier_slots = [slot for slot in slots if slot["tier"] == tier]
    statuses = (
        "ready",
        "partial",
        "stale",
        "missing",
        "event_quiet",
        "provider_pending",
        "api_key_required",
        "not_applicable",
    )
    return {
        "slot_count": len(tier_slots),
        "applicable_count": sum(1 for slot in tier_slots if slot["applicable"]),
        **{
            f"{status}_count": sum(1 for slot in tier_slots if slot["status"] == status)
            for status in statuses
        },
    }


def _asset_maturity(core_summary: dict[str, int]) -> str:
    applicable_count = core_summary["applicable_count"]
    if applicable_count <= 0 or core_summary["missing_count"] == applicable_count:
        return "missing"
    if core_summary["ready_count"] == applicable_count:
        return "ready"
    if core_summary["missing_count"] > 0 or core_summary["partial_count"] > 0:
        return "partial"
    if core_summary["stale_count"] > 0:
        return "stale"
    return "partial"


def _runtime_summary() -> dict[str, Any]:
    realtime = crypto_realtime_collector_status()
    auto_refresh = crypto_auto_refresh_status()
    return {
        "realtime": {
            "enabled": bool(realtime.get("enabled")),
            "running": bool(realtime.get("running")),
            "active_task_count": int(realtime.get("active_task_count") or 0),
            "latest_count": int(realtime.get("latest_count") or 0),
            "last_error": realtime.get("last_error"),
        },
        "auto_refresh": {
            "enabled": bool(auto_refresh.get("enabled")),
            "running": bool(auto_refresh.get("running")),
            "active_resource_count": int(auto_refresh.get("active_resource_count") or 0),
            "active_plan_count": int(auto_refresh.get("active_plan_count") or 0),
            "last_error": auto_refresh.get("last_error"),
        },
    }


def build_crypto_workspace_summary(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated_at = now or datetime.now(timezone.utc)
    assets = list_crypto_assets()
    watchlist_assets = {
        str(item.get("asset") or "").strip().upper()
        for item in list_crypto_watchlist_items(db, enabled=True)
    }
    subscription_settings = get_market_data_subscription_settings(db=db)
    subscriptions_by_asset = {
        item.key.split(":", maxsplit=1)[1].strip().upper(): item
        for item in subscription_settings.items
        if item.market == "crypto" and item.key.startswith("crypto:")
    }
    asset_rows: list[dict[str, Any]] = []

    for asset in assets:
        subscription = subscriptions_by_asset.get(asset.asset)
        source_health = build_crypto_source_health(
            db,
            base=asset.asset,
            required_only=False,
            include_events=False,
            max_entries=200,
            now=generated_at,
        )
        health_entries = [
            entry
            for entry in source_health.get("entries") or []
            if isinstance(entry, dict)
            and not str(entry.get("resource") or "").startswith("crypto_realtime")
        ]
        slots = [
            _build_slot(asset, spec, health_entries)
            for spec in (*CORE_SLOT_SPECS, *SUPPORT_SLOT_SPECS)
        ]
        core_summary = _slot_summary(slots, tier="core")
        advanced_summary = _slot_summary(slots, tier="advanced")
        context_summary = _slot_summary(slots, tier="context")
        instruments = list_provider_instruments(symbol=f"{asset.asset}-USDT")
        if asset.local_twd_provider_symbol:
            instruments.extend(list_provider_instruments(symbol=f"{asset.asset}-TWD"))
        as_of_values = [
            str(slot["latest_fetched_at"])
            for slot in slots
            if slot.get("latest_fetched_at")
        ]
        asset_rows.append(
            {
                "asset": asset.asset,
                "name": asset.name,
                "priority": asset.priority,
                "default_subscription_mode": asset.default_subscription_mode,
                "subscription_mode": (
                    subscription.mode if subscription else asset.default_subscription_mode
                ),
                "subscription_resources": dict(subscription.resources) if subscription else {},
                "watchlisted": asset.asset in watchlist_assets,
                "instrument_count": len(instruments),
                "spot_instrument_count": sum(
                    1 for instrument in instruments if instrument.instrument_type == SPOT
                ),
                "derivative_instrument_count": sum(
                    1 for instrument in instruments if instrument.instrument_type == PERPETUAL
                ),
                "maturity": _asset_maturity(core_summary),
                "as_of": max(as_of_values) if as_of_values else None,
                "core_summary": core_summary,
                "context_summary": context_summary,
                "advanced_summary": advanced_summary,
                "slots": slots,
            }
        )

    maturity_statuses = ("ready", "partial", "stale", "missing")
    summary = {
        "asset_count": len(asset_rows),
        "watchlist_count": len(watchlist_assets),
        "always_on_count": sum(
            1 for row in asset_rows if row["subscription_mode"] == "always_on"
        ),
        "on_select_count": sum(
            1 for row in asset_rows if row["subscription_mode"] == "on_select"
        ),
        **{
            f"{status}_count": sum(1 for row in asset_rows if row["maturity"] == status)
            for status in maturity_statuses
        },
    }
    warnings: list[str] = []
    if summary["stale_count"]:
        warnings.append(f"{summary['stale_count']} crypto asset(s) have stale core data.")
    if summary["partial_count"]:
        warnings.append(f"{summary['partial_count']} crypto asset(s) have partial core coverage.")
    if summary["missing_count"]:
        warnings.append(f"{summary['missing_count']} crypto asset(s) have no usable core coverage.")
    if summary["on_select_count"]:
        warnings.append(
            f"{summary['on_select_count']} crypto asset(s) use on_select refresh and may be stale until selected."
        )
    warnings.append(
        "CVD remains provider_pending; empty liquidation rows are event_quiet rather than provider failure."
    )

    return {
        "kind": "crypto_workspace_summary",
        "generated_at": generated_at.isoformat(),
        "registry_count": len(assets),
        "watchlist_count": len(watchlist_assets),
        "summary": summary,
        "runtime": _runtime_summary(),
        "assets": asset_rows,
        "warnings": warnings,
    }

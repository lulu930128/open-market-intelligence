from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.crypto_market.assets import get_crypto_asset
from app.crypto_market.contract import PERPETUAL, SPOT, list_provider_instruments
from app.crypto_market.service import (
    refresh_crypto_derivatives,
    refresh_crypto_market_caps,
    refresh_crypto_order_books,
    refresh_crypto_ohlcv,
    refresh_crypto_ohlcv_bundle,
    refresh_crypto_spreads,
    refresh_crypto_tickers,
)
from app.db.session import SessionLocal
from app.settings.market_data_subscription import (
    ALWAYS_ON_SUBSCRIPTION_MODES,
    get_market_data_subscription_settings,
)
from app.settings.schemas import (
    MarketDataSubscriptionItemRead,
    MarketDataSubscriptionSettingsRead,
)


logger = logging.getLogger(__name__)

DERIVATIVES_PROVIDERS = "binance,okx"
DEFAULT_OHLCV_BUNDLE_INTERVAL_SECONDS = 900.0
OHLCV_FAST_INTERVALS = ("1m",)
OHLCV_BUNDLE_INTERVALS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M")
AUTO_REFRESH_RESOURCES = (
    "quote",
    "order_book",
    "ohlcv",
    "derivatives",
    "market_cap",
    "taiwan_spread",
)
INTERVAL_KEY_BY_RESOURCE = {
    "quote": "quote_seconds",
    "order_book": "order_book_seconds",
    "ohlcv": "ohlcv_seconds",
    "derivatives": "derivatives_seconds",
    "market_cap": "market_cap_seconds",
    # Spread depends on fresh local/global tickers, so use the quote cadence.
    "taiwan_spread": "quote_seconds",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        item = value.strip().upper()
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _provider_csv(provider: str) -> str:
    return provider.strip().lower()


def _asset_from_subscription_item(item: MarketDataSubscriptionItemRead) -> str | None:
    prefix, _, asset = item.key.partition(":")
    if item.market != "crypto" or prefix != "crypto":
        return None
    normalized = asset.strip().upper()
    return normalized or None


def _spot_resource_for_auto_refresh(resource: str) -> str:
    if resource == "quote":
        return "ticker"
    return resource


def _instrument_symbol_batches_for_assets(
    assets: tuple[str, ...],
    *,
    instrument_type: str,
    resource: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    asset_set = {asset.strip().upper() for asset in assets}
    grouped: dict[str, list[str]] = {}
    for instrument in list_provider_instruments(
        instrument_type=instrument_type,
        resource=resource,
    ):
        if instrument.base_asset not in asset_set:
            continue
        grouped.setdefault(instrument.provider, []).append(instrument.symbol)
    return tuple(
        (provider, _unique(symbols))
        for provider, symbols in sorted(grouped.items())
        if symbols
    )


def _spot_symbol_batches_for_assets(
    assets: tuple[str, ...],
    *,
    resource: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _instrument_symbol_batches_for_assets(
        assets,
        instrument_type=SPOT,
        resource=_spot_resource_for_auto_refresh(resource),
    )


def _derivative_symbol_batches_for_assets(
    assets: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _instrument_symbol_batches_for_assets(
        assets,
        instrument_type=PERPETUAL,
        resource="derivatives",
    )


def _taiwan_spread_bases_for_assets(assets: tuple[str, ...]) -> tuple[str, ...]:
    bases: list[str] = []
    for asset in assets:
        definition = get_crypto_asset(asset)
        if definition and definition.taiwan_spread:
            bases.append(definition.asset)
    return _unique(bases)


def _interval_for_item(
    item: MarketDataSubscriptionItemRead,
    resource: str,
    *,
    fallback_seconds: float,
) -> float:
    interval_key = INTERVAL_KEY_BY_RESOURCE[resource]
    raw_value = item.intervals.get(interval_key, fallback_seconds)
    try:
        interval = float(raw_value)
    except (TypeError, ValueError):
        return fallback_seconds
    if interval <= 0:
        return fallback_seconds
    return interval


@dataclass(frozen=True)
class CryptoAutoRefreshPlan:
    resource: str
    interval_seconds: float
    providers: str | None = None
    symbols: tuple[str, ...] = ()
    assets: tuple[str, ...] = ()
    bases: tuple[str, ...] = ()
    mode: str = "default"
    ohlcv_intervals: tuple[str, ...] = ()

    def state_key(self) -> str:
        provider_part = (self.providers or "all").replace(",", "+")
        if self.mode != "default" or self.ohlcv_intervals:
            mode_part = self.mode or "default"
            interval_part = "+".join(self.ohlcv_intervals) if self.ohlcv_intervals else "all"
            return f"{self.resource}:{provider_part}:{mode_part}:{interval_part}"
        return f"{self.resource}:{provider_part}"

    def targets(self) -> tuple[str, ...]:
        if self.symbols:
            return self.symbols
        if self.assets:
            return self.assets
        return self.bases


@dataclass
class CryptoAutoRefreshResourceState:
    key: str
    resource: str
    providers: str | None = None
    mode: str = "default"
    ohlcv_intervals: tuple[str, ...] = ()
    enabled: bool = False
    interval_seconds: float | None = None
    targets: tuple[str, ...] = ()
    running: bool = False
    next_due_at: datetime | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_requested_count: int | None = None
    last_refreshed_count: int | None = None
    last_error_count: int | None = None
    last_skipped_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "resource": self.resource,
            "providers": self.providers,
            "mode": self.mode,
            "ohlcv_intervals": list(self.ohlcv_intervals),
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "targets": list(self.targets),
            "running": self.running,
            "next_due_at": _iso(self.next_due_at),
            "last_started_at": _iso(self.last_started_at),
            "last_finished_at": _iso(self.last_finished_at),
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_requested_count": self.last_requested_count,
            "last_refreshed_count": self.last_refreshed_count,
            "last_error_count": self.last_error_count,
            "last_skipped_count": self.last_skipped_count,
        }


def build_crypto_auto_refresh_plans(
    subscription_settings: MarketDataSubscriptionSettingsRead,
    *,
    min_interval_seconds: float | None = None,
    ohlcv_bundle_interval_seconds: float | None = None,
) -> list[CryptoAutoRefreshPlan]:
    min_interval = max(float(min_interval_seconds or 1.0), 1.0)
    ohlcv_bundle_interval = max(
        float(ohlcv_bundle_interval_seconds or DEFAULT_OHLCV_BUNDLE_INTERVAL_SECONDS),
        min_interval,
    )
    resource_assets: dict[str, list[str]] = {resource: [] for resource in AUTO_REFRESH_RESOURCES}
    resource_intervals: dict[str, float] = {}

    for item in subscription_settings.items:
        if item.mode not in ALWAYS_ON_SUBSCRIPTION_MODES:
            continue
        asset = _asset_from_subscription_item(item)
        if asset is None:
            continue

        for resource in AUTO_REFRESH_RESOURCES:
            if not item.resources.get(resource, False):
                continue
            resource_assets[resource].append(asset)
            interval = _interval_for_item(item, resource, fallback_seconds=min_interval)
            resource_intervals[resource] = min(
                resource_intervals.get(resource, interval),
                interval,
            )

    plans: list[CryptoAutoRefreshPlan] = []

    for resource in AUTO_REFRESH_RESOURCES:
        assets = _unique(resource_assets[resource])
        if not assets:
            continue
        interval_seconds = max(resource_intervals.get(resource, min_interval), min_interval)

        if resource in {"quote", "order_book"}:
            for provider, symbols in _spot_symbol_batches_for_assets(
                assets,
                resource=resource,
            ):
                plans.append(
                    CryptoAutoRefreshPlan(
                        resource=resource,
                        interval_seconds=interval_seconds,
                        providers=_provider_csv(provider),
                        symbols=symbols,
                    )
                )
        elif resource == "ohlcv":
            for provider, symbols in _spot_symbol_batches_for_assets(
                assets,
                resource=resource,
            ):
                plans.append(
                    CryptoAutoRefreshPlan(
                        resource=resource,
                        interval_seconds=interval_seconds,
                        providers=_provider_csv(provider),
                        symbols=symbols,
                        mode="fast",
                        ohlcv_intervals=OHLCV_FAST_INTERVALS,
                    )
                )
                plans.append(
                    CryptoAutoRefreshPlan(
                        resource=resource,
                        interval_seconds=max(ohlcv_bundle_interval, interval_seconds),
                        providers=_provider_csv(provider),
                        symbols=symbols,
                        mode="coverage",
                        ohlcv_intervals=OHLCV_BUNDLE_INTERVALS,
                    )
                )
        elif resource == "derivatives":
            for provider, symbols in _derivative_symbol_batches_for_assets(assets):
                plans.append(
                    CryptoAutoRefreshPlan(
                        resource=resource,
                        interval_seconds=interval_seconds,
                        providers=_provider_csv(provider),
                        symbols=symbols,
                    )
                )
        elif resource == "market_cap":
            plans.append(
                CryptoAutoRefreshPlan(
                    resource=resource,
                    interval_seconds=interval_seconds,
                    assets=assets,
                )
            )
        elif resource == "taiwan_spread":
            bases = _taiwan_spread_bases_for_assets(assets)
            if bases:
                plans.append(
                    CryptoAutoRefreshPlan(
                        resource=resource,
                        interval_seconds=interval_seconds,
                        providers=DERIVATIVES_PROVIDERS,
                        bases=bases,
                    )
                )

    return plans


def _load_auto_refresh_plans() -> list[CryptoAutoRefreshPlan]:
    with SessionLocal() as db:
        subscription_settings = get_market_data_subscription_settings(db=db)
    return build_crypto_auto_refresh_plans(
        subscription_settings,
        min_interval_seconds=settings.crypto_market_auto_refresh_min_interval_seconds,
        ohlcv_bundle_interval_seconds=settings.crypto_market_auto_refresh_ohlcv_bundle_seconds,
    )


def _execute_auto_refresh_plan(plan: CryptoAutoRefreshPlan) -> dict[str, Any]:
    with SessionLocal() as db:
        if plan.resource == "quote":
            return refresh_crypto_tickers(
                db,
                providers=plan.providers,
                symbols=",".join(plan.symbols),
            )
        if plan.resource == "order_book":
            return refresh_crypto_order_books(
                db,
                providers=plan.providers,
                symbols=",".join(plan.symbols),
                depth_limit=settings.crypto_market_ws_order_book_depth,
            )
        if plan.resource == "ohlcv":
            if plan.mode == "coverage":
                return refresh_crypto_ohlcv_bundle(
                    db,
                    providers=plan.providers,
                    symbols=",".join(plan.symbols),
                    intervals=",".join(plan.ohlcv_intervals),
                )
            return refresh_crypto_ohlcv(
                db,
                providers=plan.providers,
                symbols=",".join(plan.symbols),
                interval=plan.ohlcv_intervals[0] if plan.ohlcv_intervals else "1m",
                limit=settings.crypto_market_auto_refresh_ohlcv_limit,
            )
        if plan.resource == "derivatives":
            return refresh_crypto_derivatives(
                db,
                providers=plan.providers,
                symbols=",".join(plan.symbols),
            )
        if plan.resource == "market_cap":
            return refresh_crypto_market_caps(
                db,
                assets=",".join(plan.assets),
                vs_currency="usd",
            )
        if plan.resource == "taiwan_spread":
            return refresh_crypto_spreads(
                db,
                bases=",".join(plan.bases),
                global_providers=plan.providers,
            )
    raise ValueError(f"Unsupported crypto auto-refresh resource: {plan.resource}")


class CryptoAutoRefreshManager:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._reloading = False
        self._reload_count = 0
        self._last_started_at: datetime | None = None
        self._last_stopped_at: datetime | None = None
        self._last_reload_at: datetime | None = None
        self._last_reload_reason: str | None = None
        self._last_error: str | None = None
        self._states: dict[str, CryptoAutoRefreshResourceState] = {
            resource: CryptoAutoRefreshResourceState(key=resource, resource=resource)
            for resource in AUTO_REFRESH_RESOURCES
        }
        self._reload_lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        if not settings.enable_crypto_market_auto_refresh:
            self._last_error = None
            logger.info("Crypto auto-refresh disabled by configuration.")
            return

        self._running = True
        self._last_started_at = _now()
        self._last_stopped_at = None
        self._last_error = None
        self._task = asyncio.create_task(
            self._run_loop(),
            name="crypto-auto-refresh",
        )
        logger.info("Started crypto auto-refresh manager.")

    async def stop(self) -> None:
        if not self._task and not self._running:
            return
        self._running = False
        task = self._task
        self._task = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for state in self._states.values():
            state.running = False
        self._last_stopped_at = _now()
        logger.info("Stopped crypto auto-refresh manager.")

    async def reload(self, *, reason: str = "manual") -> dict[str, Any]:
        async with self._reload_lock:
            self._reloading = True
            self._reload_count += 1
            self._last_reload_at = _now()
            self._last_reload_reason = reason
            try:
                await self.stop()
                for state in self._states.values():
                    state.next_due_at = None
                await self.start()
            finally:
                self._reloading = False
            return self.status()

    async def run_once(self, *, force: bool = False) -> None:
        plans = await asyncio.to_thread(_load_auto_refresh_plans)
        active_keys = {plan.state_key() for plan in plans}

        for key, state in self._states.items():
            if key not in active_keys:
                state.enabled = False
                state.interval_seconds = None
                state.targets = ()
                state.providers = None
                state.mode = "default"
                state.ohlcv_intervals = ()
                state.next_due_at = None

        now = _now()
        for plan in plans:
            key = plan.state_key()
            state = self._states.setdefault(
                key,
                CryptoAutoRefreshResourceState(key=key, resource=plan.resource),
            )
            state.enabled = True
            state.resource = plan.resource
            state.providers = plan.providers
            state.mode = plan.mode
            state.ohlcv_intervals = plan.ohlcv_intervals
            state.interval_seconds = plan.interval_seconds
            state.targets = plan.targets()

            if not force and state.next_due_at is not None and now < state.next_due_at:
                continue

            await self._run_plan(plan, state)
            state.next_due_at = _now() + timedelta(seconds=plan.interval_seconds)
            now = _now()

    async def _run_loop(self) -> None:
        loop_seconds = max(float(settings.crypto_market_auto_refresh_loop_seconds), 0.5)
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Crypto auto-refresh loop failed.")
            await asyncio.sleep(loop_seconds)

    async def _run_plan(
        self,
        plan: CryptoAutoRefreshPlan,
        state: CryptoAutoRefreshResourceState,
    ) -> None:
        state.running = True
        state.last_started_at = _now()
        state.last_error = None
        try:
            result = await asyncio.to_thread(_execute_auto_refresh_plan, plan)
            state.last_status = str(result.get("status") or "")
            state.last_requested_count = int(result.get("requested_count") or 0)
            state.last_refreshed_count = int(result.get("refreshed_count") or 0)
            state.last_error_count = int(result.get("error_count") or 0)
            state.last_skipped_count = int(result.get("skipped_count") or 0)
        except Exception as exc:
            state.last_status = "error"
            state.last_error = str(exc)
            state.last_error_count = 1
            logger.warning(
                "Crypto auto-refresh failed for resource=%s targets=%s: %s",
                plan.resource,
                ",".join(plan.targets()),
                exc,
            )
        finally:
            state.running = False
            state.last_finished_at = _now()

    def status(self) -> dict[str, Any]:
        active_states = [state for state in self._states.values() if state.enabled]
        active_resources = {state.resource for state in active_states}
        return {
            "kind": "crypto_auto_refresh_status",
            "enabled": bool(settings.enable_crypto_market_auto_refresh),
            "running": self._running,
            "subscription_policy": "always_on",
            "reloading": self._reloading,
            "reload_count": self._reload_count,
            "last_reload_at": _iso(self._last_reload_at),
            "last_reload_reason": self._last_reload_reason,
            "last_started_at": _iso(self._last_started_at),
            "last_stopped_at": _iso(self._last_stopped_at),
            "last_error": self._last_error,
            "active_resource_count": len(active_resources),
            "active_plan_count": len(active_states),
            "resources": [state.to_dict() for state in self._states.values()],
        }


crypto_auto_refresh_manager = CryptoAutoRefreshManager()


async def start_crypto_auto_refresh() -> CryptoAutoRefreshManager:
    await crypto_auto_refresh_manager.start()
    return crypto_auto_refresh_manager


async def stop_crypto_auto_refresh() -> None:
    await crypto_auto_refresh_manager.stop()


async def reload_crypto_auto_refresh(*, reason: str = "manual") -> dict[str, Any]:
    return await crypto_auto_refresh_manager.reload(reason=reason)


def crypto_auto_refresh_status() -> dict[str, Any]:
    return crypto_auto_refresh_manager.status()

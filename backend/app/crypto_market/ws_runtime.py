from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.crypto_market.contract import ProviderInstrument, normalize_provider
from app.db.session import SessionLocal
from app.settings.market_data_subscription import (
    ALWAYS_ON_SUBSCRIPTION_MODES,
    market_data_subscription_skip_reason,
)
from app.crypto_market.realtime import (
    CryptoRealtimeStreamSpec,
    OHLCV_RESOURCE,
    ORDER_BOOK_RESOURCE,
    TICKER_RESOURCE,
    build_crypto_realtime_stream_specs,
    crypto_realtime_store,
    parse_realtime_message,
)
from app.crypto_market.realtime_persistence import crypto_realtime_persistence_manager


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _split_csv(value: str | None) -> set[str]:
    return {normalize_provider(item) for item in (value or "").split(",") if normalize_provider(item)}


REALTIME_SUBSCRIPTION_RESOURCES = {
    TICKER_RESOURCE: "quote",
    ORDER_BOOK_RESOURCE: "order_book",
    OHLCV_RESOURCE: "ohlcv",
}


def _subscription_key_for_instrument(instrument: ProviderInstrument) -> str:
    return f"crypto:{instrument.base_asset.strip().upper()}"


def _background_realtime_resource_enabled(db, instrument: ProviderInstrument, resource: str) -> bool:
    subscription_resource = REALTIME_SUBSCRIPTION_RESOURCES.get(resource)
    if subscription_resource is None:
        return False
    return (
        market_data_subscription_skip_reason(
            db,
            key=_subscription_key_for_instrument(instrument),
            resource=subscription_resource,
            allowed_modes=ALWAYS_ON_SUBSCRIPTION_MODES,
        )
        is None
    )


class CryptoRealtimeCollectorManager:
    def __init__(self, stream_specs: list[CryptoRealtimeStreamSpec] | None = None) -> None:
        self.stream_specs = stream_specs or build_crypto_realtime_stream_specs()
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._reload_lock = asyncio.Lock()
        self._reloading = False
        self._last_started_at: datetime | None = None
        self._last_stopped_at: datetime | None = None
        self._last_reload_at: datetime | None = None
        self._last_reload_reason: str | None = None
        self._reload_count = 0
        self._last_error: str | None = None
        self._websockets_available: bool | None = None

    @property
    def running(self) -> bool:
        return self._running

    def _enabled_specs(self) -> list[CryptoRealtimeStreamSpec]:
        enabled_providers = _split_csv(settings.crypto_market_ws_enabled_providers)
        with SessionLocal() as db:
            policy_specs = build_crypto_realtime_stream_specs(
                resource_enabled=lambda instrument, resource: _background_realtime_resource_enabled(
                    db,
                    instrument,
                    resource,
                )
            )
        return [
            spec
            for spec in policy_specs
            if spec.provider in enabled_providers and spec.verified
        ]

    def enabled_specs(self) -> list[CryptoRealtimeStreamSpec]:
        return self._enabled_specs()

    async def reload(self, *, reason: str = "manual") -> dict[str, Any]:
        async with self._reload_lock:
            self._reloading = True
            self._reload_count += 1
            self._last_reload_at = _now()
            self._last_reload_reason = reason
            was_running = self._running

            try:
                await self.stop()
                if settings.enable_crypto_market_ws_collector:
                    await self.start()
                else:
                    self._last_error = None
                logger.info(
                    "Reloaded crypto realtime collectors. reason=%s was_running=%s now_running=%s",
                    reason,
                    was_running,
                    self._running,
                )
            finally:
                self._reloading = False

            return self.status()

    async def start(self) -> None:
        if self._running:
            return
        if not settings.enable_crypto_market_ws_collector:
            self._last_error = None
            logger.info("Crypto realtime collector disabled by configuration.")
            return
        try:
            import websockets  # noqa: F401
        except ImportError:
            self._websockets_available = False
            self._last_error = "Python package 'websockets' is not installed."
            logger.warning("Crypto realtime collector disabled: %s", self._last_error)
            return
        self._websockets_available = True
        specs = self._enabled_specs()
        if not specs:
            self._last_error = "No verified crypto realtime stream specs are enabled."
            logger.warning("Crypto realtime collector disabled: %s", self._last_error)
            return
        self._running = True
        self._last_started_at = _now()
        self._last_stopped_at = None
        self._last_error = None
        await crypto_realtime_persistence_manager.start()
        self._tasks = [
            asyncio.create_task(self._run_stream(spec), name=f"crypto-ws-{spec.provider}-{spec.resource}")
            for spec in specs
        ]
        logger.info("Started %s crypto realtime collector task(s).", len(self._tasks))

    async def stop(self) -> None:
        if not self._tasks and not self._running:
            return
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        await crypto_realtime_persistence_manager.stop()
        self._last_stopped_at = _now()
        logger.info("Stopped crypto realtime collectors.")

    async def _run_stream(self, spec: CryptoRealtimeStreamSpec) -> None:
        import websockets

        reconnect_delay = max(float(settings.crypto_market_ws_reconnect_initial_seconds), 0.1)
        max_delay = max(float(settings.crypto_market_ws_reconnect_max_seconds), reconnect_delay)
        while self._running:
            try:
                async with websockets.connect(spec.url, ping_interval=20, ping_timeout=20) as websocket:
                    reconnect_delay = max(float(settings.crypto_market_ws_reconnect_initial_seconds), 0.1)
                    if spec.subscribe_message:
                        await websocket.send(json.dumps(spec.subscribe_message))
                    async for message in websocket:
                        if not self._running:
                            break
                        payload = json.loads(message)
                        updates = parse_realtime_message(spec.provider, payload)
                        for update in updates:
                            crypto_realtime_store.update(update)
                        crypto_realtime_persistence_manager.enqueue_many(updates)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = f"{spec.provider}/{spec.resource}: {exc}"
                logger.warning("Crypto realtime stream failed provider=%s resource=%s: %s", spec.provider, spec.resource, exc)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_delay)

    def status(self) -> dict[str, Any]:
        task_count = len(self._tasks)
        active_task_count = sum(1 for task in self._tasks if not task.done())
        enabled_providers = sorted(_split_csv(settings.crypto_market_ws_enabled_providers))
        enabled_streams = self._enabled_specs()
        return {
            "kind": "crypto_realtime_collector_status",
            "enabled": bool(settings.enable_crypto_market_ws_collector),
            "running": self._running,
            "websockets_available": self._websockets_available,
            "enabled_providers": enabled_providers,
            "subscription_policy": "always_on",
            "reloading": self._reloading,
            "reload_count": self._reload_count,
            "last_reload_at": self._last_reload_at.isoformat() if self._last_reload_at else None,
            "last_reload_reason": self._last_reload_reason,
            "task_count": task_count,
            "active_task_count": active_task_count,
            "last_started_at": self._last_started_at.isoformat() if self._last_started_at else None,
            "last_stopped_at": self._last_stopped_at.isoformat() if self._last_stopped_at else None,
            "last_error": self._last_error,
            "latest_count": len(crypto_realtime_store.latest()),
            "persistence": crypto_realtime_persistence_manager.status(),
            "streams": [spec.to_dict() for spec in self.stream_specs],
            "enabled_streams": [spec.to_dict() for spec in enabled_streams],
        }


crypto_realtime_collector_manager = CryptoRealtimeCollectorManager()


async def start_crypto_realtime_collectors() -> CryptoRealtimeCollectorManager:
    await crypto_realtime_collector_manager.start()
    return crypto_realtime_collector_manager


async def stop_crypto_realtime_collectors() -> None:
    await crypto_realtime_collector_manager.stop()


def crypto_realtime_collector_status() -> dict[str, Any]:
    return crypto_realtime_collector_manager.status()


def crypto_realtime_enabled_stream_specs() -> list[CryptoRealtimeStreamSpec]:
    return crypto_realtime_collector_manager.enabled_specs()


async def reload_crypto_realtime_collectors(*, reason: str = "manual") -> dict[str, Any]:
    return await crypto_realtime_collector_manager.reload(reason=reason)

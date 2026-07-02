from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.crypto_market.realtime import CryptoRealtimeUpdate, LIQUIDATION_RESOURCE, OHLCV_RESOURCE
from app.crypto_market.service import persist_crypto_realtime_updates
from app.db.session import SessionLocal


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


SessionFactory = Callable[[], Session]
PersistFunction = Callable[[Session, list[CryptoRealtimeUpdate]], dict[str, Any]]


class CryptoRealtimePersistenceManager:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        persist_func: PersistFunction = persist_crypto_realtime_updates,
        enabled: bool | None = None,
        flush_interval_seconds: float | None = None,
        max_pending_keys: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._persist_func = persist_func
        self._enabled_override = enabled
        self._flush_interval_override = flush_interval_seconds
        self._max_pending_keys_override = max_pending_keys
        self._task: asyncio.Task | None = None
        self._running = False
        self._lock = RLock()
        self._pending: dict[tuple[Any, ...], CryptoRealtimeUpdate] = {}
        self._enqueued_count = 0
        self._dropped_count = 0
        self._persisted_count = 0
        self._skipped_count = 0
        self._error_count = 0
        self._flush_count = 0
        self._last_flush_started_at: datetime | None = None
        self._last_flush_completed_at: datetime | None = None
        self._last_error: str | None = None
        self._last_batch_size = 0
        self._last_result: dict[str, Any] | None = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        return bool(settings.enable_crypto_market_ws_persistence)

    @property
    def flush_interval_seconds(self) -> float:
        if self._flush_interval_override is not None:
            return max(float(self._flush_interval_override), 0.1)
        return max(float(settings.crypto_market_ws_persistence_flush_seconds), 0.1)

    @property
    def max_pending_keys(self) -> int:
        if self._max_pending_keys_override is not None:
            return max(int(self._max_pending_keys_override), 1)
        return max(int(settings.crypto_market_ws_persistence_max_pending_keys), 1)

    def _pending_key(self, update: CryptoRealtimeUpdate) -> tuple[Any, ...]:
        if update.resource == OHLCV_RESOURCE:
            return (
                update.provider,
                update.resource,
                update.symbol,
                update.instrument_type,
                update.data.get("interval"),
                update.data.get("bar_time"),
            )
        if update.resource == LIQUIDATION_RESOURCE:
            return (
                update.provider,
                update.resource,
                update.symbol,
                update.instrument_type,
                update.event_time,
                update.data.get("liquidation_side"),
                update.data.get("order_side"),
                update.data.get("price"),
                update.data.get("quantity"),
                update.data.get("notional"),
            )
        return update.key()

    def enqueue(self, update: CryptoRealtimeUpdate) -> bool:
        if not self.enabled:
            return False
        key = self._pending_key(update)
        with self._lock:
            if key not in self._pending and len(self._pending) >= self.max_pending_keys:
                self._dropped_count += 1
                return False
            self._pending[key] = update
            self._enqueued_count += 1
            return True

    def enqueue_many(self, updates: list[CryptoRealtimeUpdate] | tuple[CryptoRealtimeUpdate, ...]) -> int:
        accepted = 0
        for update in updates:
            if self.enqueue(update):
                accepted += 1
        return accepted

    async def start(self) -> None:
        if self._running or not self.enabled:
            return
        self._running = True
        self._last_error = None
        self._task = asyncio.create_task(self._run_loop(), name="crypto-ws-persistence")
        logger.info("Started crypto realtime persistence manager.")

    async def stop(self) -> None:
        if not self._task and not self._running:
            return
        self._running = False
        task = self._task
        self._task = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.flush_once()
        logger.info("Stopped crypto realtime persistence manager.")

    async def flush_once(self) -> dict[str, Any] | None:
        updates = self._take_pending()
        if not updates:
            return None
        self._last_flush_started_at = _now()
        self._last_batch_size = len(updates)
        try:
            result = await asyncio.to_thread(self._persist_updates, updates)
        except Exception as exc:
            self._error_count += len(updates)
            self._last_error = str(exc)
            logger.warning("Crypto realtime persistence flush failed: %s", exc)
            return {
                "status": "error",
                "requested_count": len(updates),
                "persisted_count": 0,
                "error_count": len(updates),
                "error": str(exc),
            }
        self._flush_count += 1
        self._last_flush_completed_at = _now()
        self._last_error = None
        self._last_result = result
        self._persisted_count += int(result.get("persisted_count") or 0)
        self._skipped_count += int(result.get("skipped_count") or 0)
        self._error_count += int(result.get("error_count") or 0)
        return result

    async def _run_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.flush_interval_seconds)
            await self.flush_once()

    def _take_pending(self) -> list[CryptoRealtimeUpdate]:
        with self._lock:
            updates = list(self._pending.values())
            self._pending.clear()
        return updates

    def _persist_updates(self, updates: list[CryptoRealtimeUpdate]) -> dict[str, Any]:
        with self._session_factory() as db:
            return self._persist_func(db, updates)

    def status(self) -> dict[str, Any]:
        with self._lock:
            pending_count = len(self._pending)
        status = "disabled"
        ok = not self.enabled
        if self.enabled:
            if self._last_error:
                status = "error"
                ok = False
            elif self._running:
                status = "running"
                ok = True
            else:
                status = "stopped"
                ok = False
        return {
            "enabled": self.enabled,
            "running": self._running,
            "ok": ok,
            "status": status,
            "pending_count": pending_count,
            "max_pending_keys": self.max_pending_keys,
            "flush_interval_seconds": self.flush_interval_seconds,
            "last_batch_size": self._last_batch_size,
            "flush_count": self._flush_count,
            "enqueued_count": self._enqueued_count,
            "dropped_count": self._dropped_count,
            "persisted_count": self._persisted_count,
            "skipped_count": self._skipped_count,
            "error_count": self._error_count,
            "last_flush_started_at": _iso(self._last_flush_started_at),
            "last_flush_completed_at": _iso(self._last_flush_completed_at),
            "last_error": self._last_error,
            "last_result": self._last_result,
        }


crypto_realtime_persistence_manager = CryptoRealtimePersistenceManager()

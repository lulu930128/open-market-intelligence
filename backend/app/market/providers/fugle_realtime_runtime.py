"""Background-owned Fugle single-connection runtime and bounded materializer."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from threading import Lock
from typing import Any, Protocol

import websockets
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import SessionLocal
from app.market.intraday_transaction import TaiwanIntradayBarTransaction
from app.market.providers.fugle_realtime import (
    FUGLE_TAIEX_SYMBOL,
    FUGLE_WEBSOCKET_URL,
    FugleIndexSessionNotMaterializable,
    FugleIndexValueAnomaly,
    FugleRealtimeBuffer,
    FugleSubscriptionAllocator,
    fugle_bar_acquisition,
    fugle_index_acquisition,
    fugle_quote_acquisition,
)
from app.market.public_quote_platform import (
    build_taiwan_public_quote_requirement,
    read_taiwan_public_last_trade_quote,
)
from app.market.public_quote_transaction import TaiwanPublicQuoteTransaction
from app.market.tw_current_market_capabilities import (
    TW_CURRENT_INDEX_CAPABILITY_ID,
    TW_CURRENT_INDEX_DATASET_ID,
)
from app.market.tw_current_market_platform import (
    build_taiwan_current_requirement,
    read_taiwan_current_index,
    read_taiwan_index_previous_close_seed,
)
from app.market.tw_current_market_transaction import TaiwanCurrentMarketTransaction
from app.market.tw_intraday_platform import (
    build_taiwan_intraday_requirement,
    read_taiwan_intraday_bars,
)
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market_data.contracts import InstrumentKey, InstrumentType
from app.market_data.integration_contracts import RequestBounds
from app.market_data.policies import RealtimePolicy


logger = logging.getLogger(__name__)


class FugleSocket(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str: ...


ConnectFactory = Callable[..., Any]


def _instrument(db: Session, symbol: str) -> InstrumentKey:
    instrument = resolve_taiwan_instrument(db, symbol)
    if instrument.instrument_type is InstrumentType.INDEX:
        raise ValueError("Fugle stock stream does not materialize Taiwan index events")
    return instrument


class FugleCanonicalMaterializer:
    """Persist each accepted stream hash at most once per runtime process."""

    def __init__(self, buffer: FugleRealtimeBuffer) -> None:
        self._buffer = buffer
        self._lock = Lock()
        self._materialized_hashes: dict[tuple[str, str], str] = {}

    def _claim(self, channel: str, symbol: str, content_hash: str) -> bool:
        key = (channel, symbol)
        with self._lock:
            if self._materialized_hashes.get(key) == content_hash:
                return False
            self._materialized_hashes[key] = content_hash
            return True

    def _release(self, channel: str, symbol: str, content_hash: str) -> None:
        key = (channel, symbol)
        with self._lock:
            if self._materialized_hashes.get(key) == content_hash:
                self._materialized_hashes.pop(key, None)

    def materialize(self, db: Session, *, active_stock: str | None) -> dict[str, object]:
        results: dict[str, object] = {}
        index_record = self._buffer.latest("indices", FUGLE_TAIEX_SYMBOL)
        if index_record is not None and self._claim(
            "indices",
            FUGLE_TAIEX_SYMBOL,
            index_record.content_hash,
        ):
            try:
                seed = read_taiwan_index_previous_close_seed(
                    db,
                    index_id="TAIEX",
                    event_at=index_record.event_at,
                    requested_at=index_record.received_at,
                )
                if seed is None:
                    results["index"] = {
                        "status": "pending",
                        "limitation": "FUGLE_INDEX_PREVIOUS_CLOSE_SEED_MISSING",
                    }
                    # A missing seed is retryable. Do not consume this stream hash,
                    # otherwise the same latest index record could never materialize
                    # after an official/MIS previous-close seed becomes available.
                    self._release(
                        "indices",
                        FUGLE_TAIEX_SYMBOL,
                        index_record.content_hash,
                    )
                    return self._materialize_stock(
                        db,
                        active_stock=active_stock,
                        results=results,
                    )
                requirement = build_taiwan_current_requirement(
                    dataset_id=TW_CURRENT_INDEX_DATASET_ID,
                    capability_id=TW_CURRENT_INDEX_CAPABILITY_ID,
                    scope_key="TAIEX",
                    requested_at=index_record.received_at,
                    policy=RealtimePolicy.PREFER_LIVE,
                    acquiring=True,
                )
                acquisition = fugle_index_acquisition(
                    index_record,
                    requirement,
                    previous_close=Decimal(seed.previous_close),
                )
                persistence = TaiwanCurrentMarketTransaction(
                    db
                ).persist_market_index_acquisition(requirement, acquisition)
                reread = read_taiwan_current_index(
                    db,
                    index_id="TAIEX",
                    requested_at=index_record.received_at,
                )
                results["index"] = {
                    "status": "materialized",
                    "raw_result_ids": list(persistence.raw_result_ids),
                    "selected_provider": reread.resolved.health.selected_provider,
                    "candidates": [
                        item.model_dump(mode="json")
                        for item in reread.resolved.candidates
                    ],
                }
            except FugleIndexValueAnomaly:
                results["index"] = {
                    "status": "rejected",
                    "limitation": "FUGLE_INDEX_VALUE_IMPLAUSIBLE",
                }
            except FugleIndexSessionNotMaterializable:
                results["index"] = {
                    "status": "pending",
                    "limitation": "FUGLE_INDEX_COMPLETED_SESSION_NOT_MATERIALIZABLE",
                }
            except Exception:
                self._release("indices", FUGLE_TAIEX_SYMBOL, index_record.content_hash)
                raise

        return self._materialize_stock(
            db,
            active_stock=active_stock,
            results=results,
        )

    def _materialize_stock(
        self,
        db: Session,
        *,
        active_stock: str | None,
        results: dict[str, object],
    ) -> dict[str, object]:
        normalized_stock = str(active_stock or "").strip().upper()
        if not normalized_stock:
            return results
        instrument = _instrument(db, normalized_stock)
        quote_record = self._buffer.latest("aggregates", normalized_stock)
        if quote_record is not None and self._claim(
            "aggregates",
            normalized_stock,
            quote_record.content_hash,
        ):
            try:
                requirement = build_taiwan_public_quote_requirement(
                    instrument=instrument,
                    policy=RealtimePolicy.REQUIRE_LIVE,
                    requested_at=quote_record.received_at,
                    bounds=RequestBounds(
                        max_provider_attempts=0,
                        max_external_calls=0,
                        max_subscriptions=1,
                        timeout_seconds=30,
                        max_candidates=3,
                        max_rows=1,
                    ),
                )
                acquisition = fugle_quote_acquisition(quote_record, requirement)
                persistence = TaiwanPublicQuoteTransaction(db).persist_quote_acquisition(
                    requirement,
                    acquisition,
                )
                reread = read_taiwan_public_last_trade_quote(
                    db,
                    stock_id=normalized_stock,
                    requested_at=quote_record.received_at,
                )
                results["quote"] = {
                    "status": "materialized",
                    "raw_result_ids": list(persistence.raw_result_ids),
                    "selected_provider": reread.resolved.health.selected_provider,
                }
            except Exception:
                self._release("aggregates", normalized_stock, quote_record.content_hash)
                raise

        bar_record = self._buffer.latest("candles", normalized_stock)
        if bar_record is not None and self._claim(
            "candles",
            normalized_stock,
            bar_record.content_hash,
        ):
            try:
                requirement = build_taiwan_intraday_requirement(
                    instrument=instrument,
                    interval="1m",
                    range_value="1d",
                    policy=RealtimePolicy.PREFER_LIVE,
                    requested_at=bar_record.received_at,
                    acquiring=True,
                )
                acquisition = fugle_bar_acquisition(bar_record, requirement)
                persistence = TaiwanIntradayBarTransaction(db).persist_bar_acquisition(
                    requirement,
                    acquisition,
                )
                reread = read_taiwan_intraday_bars(
                    db,
                    stock_id=normalized_stock,
                    interval="1m",
                    range_value="1d",
                    requested_at=bar_record.received_at,
                )
                results["bars"] = {
                    "status": "materialized",
                    "raw_result_ids": list(persistence.raw_result_ids),
                    "selected_provider": reread.resolved.health.selected_provider,
                }
            except Exception:
                self._release("candles", normalized_stock, bar_record.content_hash)
                raise
        return results


class FugleRealtimeRuntime:
    """Maintain exactly one authenticated Fugle WebSocket connection."""

    def __init__(
        self,
        *,
        api_key: str,
        websocket_url: str = FUGLE_WEBSOCKET_URL,
        active_stock: str | None = None,
        stale_seconds: int = 75,
        materialize_interval_seconds: int = 5,
        reconnect_max_seconds: int = 30,
        connect: ConnectFactory = websockets.connect,
        clock=lambda: datetime.now(timezone.utc),
        session_factory=SessionLocal,
    ) -> None:
        cleaned_key = str(api_key or "").strip()
        if not cleaned_key:
            raise ValueError("Fugle API key is required")
        self._api_key = cleaned_key
        self.websocket_url = websocket_url
        self.stale_seconds = max(int(stale_seconds), 35)
        self.materialize_interval_seconds = max(int(materialize_interval_seconds), 1)
        self.reconnect_max_seconds = max(int(reconnect_max_seconds), 1)
        self._connect = connect
        self._clock = clock
        self._session_factory = session_factory
        self.buffer = FugleRealtimeBuffer()
        self.allocator = FugleSubscriptionAllocator()
        self.allocator.set_active_stock(active_stock)
        self.materializer = FugleCanonicalMaterializer(self.buffer)
        self._runner: asyncio.Task[None] | None = None
        self._materializer_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self.connection_status = "stopped"
        self.entitlement_status = "unknown"
        self.last_message_at: datetime | None = None
        self.last_error: str | None = None
        self.reconnect_count = 0
        self._pending_subscriptions: set[tuple[str, str]] = set()
        self._pending_unsubscribe_ids: set[str] = set()

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._stop_event.clear()
        self._runner = asyncio.create_task(self._run(), name="fugle-realtime")
        self._materializer_task = asyncio.create_task(
            self._materialize_loop(),
            name="fugle-materializer",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        tasks = tuple(
            task
            for task in (self._runner, self._materializer_task)
            if task is not None
        )
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._runner = None
        self._materializer_task = None
        self.connection_status = "stopped"
        self.allocator.reset_server_bindings()

    def set_active_stock(self, symbol: str | None) -> bool:
        previous = self.allocator.active_stock
        changed = self.allocator.set_active_stock(symbol)
        if changed and previous:
            self.buffer.clear_symbol(previous)
        return changed

    def quote_readiness(self, symbol: str) -> dict[str, object]:
        normalized = str(symbol or "").strip().upper()
        if not normalized or not normalized.isdigit():
            raise ValueError("Fugle quote readiness requires a numeric Taiwan symbol")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Fugle runtime clock must be timezone-aware")
        record = self.buffer.latest("aggregates", normalized)
        age_seconds = (
            (now - record.received_at).total_seconds()
            if record is not None
            else None
        )
        allocated = self.allocator.active_stock == normalized
        connected = self.connection_status == "connected"
        authenticated = self.entitlement_status == "entitled"
        subscribed = self.allocator.is_bound("aggregates", normalized)
        fresh_record = (
            record is not None
            and age_seconds is not None
            and age_seconds >= 0
            and age_seconds <= self.stale_seconds
        )
        ready = (
            allocated
            and connected
            and authenticated
            and subscribed
            and fresh_record
        )
        detail_code = (
            "FUGLE_QUOTE_READY"
            if ready
            else "FUGLE_QUOTE_SLOT_NOT_ALLOCATED"
            if not allocated
            else "FUGLE_STREAM_NOT_CONNECTED"
            if not connected
            else "FUGLE_AUTH_NOT_READY"
            if not authenticated
            else "FUGLE_QUOTE_SUBSCRIPTION_PENDING"
            if not subscribed
            else "FUGLE_QUOTE_RECORD_MISSING"
            if record is None
            else "FUGLE_QUOTE_RECORD_STALE"
        )
        return {
            "symbol": normalized,
            "connection": self.connection_status,
            "authenticated": authenticated,
            "subscribed": subscribed,
            "fresh_record": fresh_record,
            "record_age_seconds": age_seconds,
            "record_event_at": record.event_at if record is not None else None,
            "ready": ready,
            "detail_code": detail_code,
        }

    def index_readiness(self) -> dict[str, object]:
        """Expose bounded IX0001 identity/value evidence without raw payloads."""

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Fugle runtime clock must be timezone-aware")
        record = self.buffer.latest("indices", FUGLE_TAIEX_SYMBOL)
        age_seconds = (
            (now - record.received_at).total_seconds()
            if record is not None
            else None
        )
        subscribed = self.allocator.is_bound("indices", FUGLE_TAIEX_SYMBOL)
        fresh_record = (
            record is not None
            and age_seconds is not None
            and age_seconds >= 0
            and age_seconds <= self.stale_seconds
        )
        raw_value = record.payload.get("index") if record is not None else None
        try:
            value = float(raw_value) if raw_value is not None else None
        except (TypeError, ValueError):
            value = None
        ready = (
            self.connection_status == "connected"
            and self.entitlement_status == "entitled"
            and subscribed
            and fresh_record
            and record is not None
            and record.symbol == FUGLE_TAIEX_SYMBOL
            and value is not None
            and value > 0
        )
        return {
            "expected_symbol": FUGLE_TAIEX_SYMBOL,
            "record_symbol": record.symbol if record is not None else None,
            "connection": self.connection_status,
            "authenticated": self.entitlement_status == "entitled",
            "subscribed": subscribed,
            "fresh_record": fresh_record,
            "record_age_seconds": age_seconds,
            "record_event_at": record.event_at if record is not None else None,
            "record_value": value,
            "ready": ready,
        }

    async def _send_commands(self, socket: FugleSocket) -> None:
        commands = self.allocator.commands()
        unsubscribe_ids = tuple(
            item
            for item in commands.unsubscribe_ids
            if item not in self._pending_unsubscribe_ids
        )
        if unsubscribe_ids:
            self._pending_unsubscribe_ids.update(unsubscribe_ids)
            await socket.send(
                json.dumps(
                    {
                        "event": "unsubscribe",
                        "data": {"ids": list(unsubscribe_ids)},
                    },
                    separators=(",", ":"),
                )
            )
            return
        for subscription in commands.subscribe:
            key = (subscription.channel, subscription.symbol)
            if key in self._pending_subscriptions:
                continue
            self._pending_subscriptions.add(key)
            await socket.send(
                json.dumps(
                    {
                        "event": "subscribe",
                        "data": {
                            "channel": subscription.channel,
                            "symbol": subscription.symbol,
                        },
                    },
                    separators=(",", ":"),
                )
            )

    def _handle_control(self, envelope: dict[str, Any]) -> None:
        event = str(envelope.get("event") or "")
        data = envelope.get("data")
        if event == "subscribed":
            rows = data if isinstance(data, list) else [data]
            for row in rows:
                if isinstance(row, dict):
                    self._pending_subscriptions.discard(
                        (
                            str(row.get("channel") or ""),
                            str(row.get("symbol") or "").strip().upper(),
                        )
                    )
                    self.allocator.acknowledge_subscribed(
                        channel_id=str(row.get("id") or ""),
                        channel=str(row.get("channel") or ""),
                        symbol=str(row.get("symbol") or ""),
                    )
        elif event == "unsubscribed":
            rows = data if isinstance(data, list) else [data]
            self.allocator.acknowledge_unsubscribed(
                str(row.get("id") or "")
                for row in rows
                if isinstance(row, dict)
            )
            self._pending_unsubscribe_ids.difference_update(
                str(row.get("id") or "")
                for row in rows
                if isinstance(row, dict)
            )

    async def _connection(self) -> None:
        self.allocator.reset_server_bindings()
        self._pending_subscriptions.clear()
        self._pending_unsubscribe_ids.clear()
        self.connection_status = "connecting"
        async with self._connect(
            self.websocket_url,
            open_timeout=20,
            close_timeout=5,
        ) as socket:
            self.connection_status = "connected"
            self.last_message_at = self._clock()
            await socket.send(
                json.dumps(
                    {"event": "auth", "data": {"apikey": self._api_key}},
                    separators=(",", ":"),
                )
            )
            authenticated = False
            while not self._stop_event.is_set():
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    if (
                        self.last_message_at is not None
                        and (self._clock() - self.last_message_at).total_seconds()
                        > self.stale_seconds
                    ):
                        raise TimeoutError("FUGLE_STREAM_HEARTBEAT_STALE")
                    if authenticated:
                        await self._send_commands(socket)
                    continue
                received_at = self._clock()
                self.last_message_at = received_at
                envelope = json.loads(message)
                if not isinstance(envelope, dict):
                    raise ValueError("Fugle WebSocket envelope must be an object")
                event = str(envelope.get("event") or "")
                if event == "authenticated":
                    authenticated = True
                    self.entitlement_status = "entitled"
                    await self._send_commands(socket)
                elif event == "error":
                    detail = str(
                        (envelope.get("data") or {}).get("message")
                        if isinstance(envelope.get("data"), dict)
                        else "Fugle WebSocket error"
                    )
                    self.entitlement_status = (
                        "auth_failed" if "auth" in detail.casefold() else "plan_restricted"
                    )
                    raise RuntimeError("FUGLE_PROVIDER_ERROR")
                elif event == "data":
                    self.buffer.ingest(envelope, received_at=received_at)
                else:
                    self._handle_control(envelope)
                if authenticated:
                    await self._send_commands(socket)

    async def _run(self) -> None:
        delay = 1
        while not self._stop_event.is_set():
            try:
                await self._connection()
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connection_status = "disconnected"
                self.last_error = f"{type(exc).__name__}:{exc}"[:256]
                self.reconnect_count += 1
                logger.warning(
                    "Fugle realtime connection interrupted; retrying in %s seconds (%s).",
                    delay,
                    type(exc).__name__,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * 2, self.reconnect_max_seconds)

    def _materialize_once(self) -> None:
        db = self._session_factory()
        try:
            result = self.materializer.materialize(
                db,
                active_stock=self.allocator.active_stock,
            )
            if result:
                logger.debug("Fugle canonical materialization completed surfaces=%s.", sorted(result))
        except Exception:
            db.rollback()
            logger.exception("Fugle canonical materialization failed.")
        finally:
            db.close()

    async def _materialize_loop(self) -> None:
        while not self._stop_event.is_set():
            await asyncio.to_thread(self._materialize_once)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.materialize_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    def health(self) -> dict[str, object]:
        active_stock = self.allocator.active_stock
        return {
            "provider": "fugle_marketdata",
            "connection": self.connection_status,
            "entitlement": self.entitlement_status,
            "last_message_at": self.last_message_at,
            "last_error": self.last_error,
            "reconnect_count": self.reconnect_count,
            "subscriptions": self.allocator.snapshot(),
            "buffer": self.buffer.metrics(),
            "index_readiness": self.index_readiness(),
            "active_quote_readiness": (
                self.quote_readiness(active_stock) if active_stock else None
            ),
        }


_FUGLE_RUNTIME: FugleRealtimeRuntime | None = None


async def start_fugle_realtime() -> FugleRealtimeRuntime | None:
    global _FUGLE_RUNTIME
    if not settings.enable_fugle_realtime:
        return None
    api_key = str(settings.fugle_api_key or "").strip()
    if not api_key:
        logger.warning("Fugle realtime is enabled but FUGLE_API_KEY is missing; collector stays disabled.")
        return None
    if _FUGLE_RUNTIME is None:
        _FUGLE_RUNTIME = FugleRealtimeRuntime(
            api_key=api_key,
            websocket_url=settings.fugle_websocket_url,
            active_stock=settings.fugle_active_stock,
            stale_seconds=settings.fugle_stream_stale_seconds,
            materialize_interval_seconds=settings.fugle_materialize_interval_seconds,
            reconnect_max_seconds=settings.fugle_reconnect_max_seconds,
        )
    await _FUGLE_RUNTIME.start()
    return _FUGLE_RUNTIME


async def stop_fugle_realtime() -> None:
    global _FUGLE_RUNTIME
    runtime = _FUGLE_RUNTIME
    _FUGLE_RUNTIME = None
    if runtime is not None:
        await runtime.stop()


def get_fugle_realtime_runtime() -> FugleRealtimeRuntime | None:
    return _FUGLE_RUNTIME


__all__ = [
    "FugleCanonicalMaterializer",
    "FugleRealtimeRuntime",
    "get_fugle_realtime_runtime",
    "start_fugle_realtime",
    "stop_fugle_realtime",
]

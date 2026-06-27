from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlencode

from app.config import settings
from app.crypto_market.contract import (
    BINANCE_PROVIDER,
    BITOPRO_PROVIDER,
    OKX_PROVIDER,
    SPOT,
    ProviderInstrument,
    list_provider_instruments,
    normalize_provider,
    normalize_symbol,
)


TICKER_RESOURCE = "ticker"
ORDER_BOOK_RESOURCE = "order_book"
OHLCV_RESOURCE = "ohlcv"
COLLECTOR_RESOURCE = "collector"


@dataclass(frozen=True)
class CryptoRealtimeStreamSpec:
    provider: str
    resource: str
    symbols: tuple[str, ...]
    url: str
    instrument_type: str = SPOT
    verified: bool = True
    notes: str = ""
    subscribe_message: dict[str, Any] | None = None
    message_resources: tuple[str, ...] = ()

    def covered_resources(self) -> tuple[str, ...]:
        if self.message_resources:
            return self.message_resources
        if self.resource == "combined":
            return (TICKER_RESOURCE, ORDER_BOOK_RESOURCE, OHLCV_RESOURCE)
        return (self.resource,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "resource": self.resource,
            "message_resources": list(self.covered_resources()),
            "symbols": list(self.symbols),
            "instrument_type": self.instrument_type,
            "url": self.url,
            "verified": self.verified,
            "notes": self.notes,
            "subscribe_message": self.subscribe_message,
        }


@dataclass(frozen=True)
class CryptoRealtimeUpdate:
    provider: str
    resource: str
    symbol: str
    provider_symbol: str
    instrument_type: str
    event_time: datetime | None
    received_at: datetime
    feed_lag_ms: int | None
    sequence: int | None
    data: dict[str, Any]
    raw_payload: Any

    def key(self) -> tuple[str, str, str, str]:
        return (self.provider, self.resource, self.symbol, self.instrument_type)

    def to_dict(self, *, now: datetime | None = None, stale_seconds: int | None = None) -> dict[str, Any]:
        current = now or utc_now()
        age_ms = max(int((current - self.received_at).total_seconds() * 1000), 0)
        stale_threshold = stale_seconds if stale_seconds is not None else settings.crypto_market_ws_message_stale_seconds
        stale = age_ms > max(int(stale_threshold), 1) * 1000
        return {
            "provider": self.provider,
            "resource": self.resource,
            "symbol": self.symbol,
            "provider_symbol": self.provider_symbol,
            "instrument_type": self.instrument_type,
            "event_time": self.event_time.isoformat() if self.event_time else None,
            "received_at": self.received_at.isoformat(),
            "feed_lag_ms": self.feed_lag_ms,
            "last_message_age_ms": age_ms,
            "stale": stale,
            "sequence": self.sequence,
            "data": dict(self.data),
        }


class CryptoRealtimeStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._updates: dict[tuple[str, str, str, str], CryptoRealtimeUpdate] = {}

    def clear(self) -> None:
        with self._lock:
            self._updates.clear()

    def update(self, update: CryptoRealtimeUpdate) -> None:
        with self._lock:
            self._updates[update.key()] = update

    def latest(
        self,
        *,
        provider: str | None = None,
        resource: str | None = None,
        symbol: str | None = None,
        instrument_type: str | None = None,
        now: datetime | None = None,
        stale_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized_provider = normalize_provider(provider) if provider else None
        normalized_symbol = normalize_symbol(symbol) if symbol else None
        normalized_resource = (resource or "").strip().lower() or None
        normalized_instrument_type = (instrument_type or "").strip().lower() or None
        with self._lock:
            updates = list(self._updates.values())
        rows = []
        for update in updates:
            if normalized_provider and update.provider != normalized_provider:
                continue
            if normalized_resource and update.resource != normalized_resource:
                continue
            if normalized_symbol and update.symbol != normalized_symbol:
                continue
            if normalized_instrument_type and update.instrument_type != normalized_instrument_type:
                continue
            rows.append(update.to_dict(now=now, stale_seconds=stale_seconds))
        return sorted(rows, key=lambda item: item["received_at"], reverse=True)

    def health_entries(
        self,
        *,
        stream_specs: list[CryptoRealtimeStreamSpec],
        now: datetime | None = None,
        stale_seconds: int | None = None,
        collector_enabled: bool,
        provider: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        current = now or utc_now()
        stale_threshold = max(int(stale_seconds or settings.crypto_market_ws_message_stale_seconds), 1)
        normalized_provider = normalize_provider(provider) if provider else None
        normalized_symbol = normalize_symbol(symbol) if symbol else None
        entries: list[dict[str, Any]] = [
            {
                "resource": "crypto_realtime_collector",
                "provider": "all",
                "target": "all",
                "status": "enabled" if collector_enabled else "disabled",
                "ok": bool(collector_enabled),
                "row_count": len(self._updates),
                "required": False,
                "latest_fetched_at": None,
                "latest_data_key": None,
                "data_quality": "ok" if collector_enabled else "disabled",
                "reason": (
                    "Crypto realtime collector is enabled."
                    if collector_enabled
                    else "Crypto realtime collector is disabled by configuration."
                ),
            }
        ]
        for spec in stream_specs:
            if normalized_provider and spec.provider != normalized_provider:
                continue
            for target in spec.symbols:
                if normalized_symbol and normalize_symbol(target) != normalized_symbol:
                    continue
                for resource in spec.covered_resources():
                    key = (spec.provider, resource, normalize_symbol(target), spec.instrument_type)
                    with self._lock:
                        update = self._updates.get(key)
                    if update is None:
                        status = "empty" if collector_enabled else "disabled"
                        ok = False
                        data_quality = "empty" if collector_enabled else "disabled"
                        reason = (
                            "No realtime WebSocket message has been received for this stream resource."
                            if collector_enabled
                            else "Realtime collector is disabled by configuration."
                        )
                        latest_fetched_at = None
                        latest_data_key = resource
                    else:
                        age_seconds = max(int((current - update.received_at).total_seconds()), 0)
                        if age_seconds > stale_threshold:
                            status = "stale"
                            ok = False
                            data_quality = "stale"
                            reason = f"Latest realtime message is {age_seconds}s old; threshold is {stale_threshold}s."
                        else:
                            status = "live"
                            ok = True
                            data_quality = "ok"
                            reason = "Latest realtime message is within the configured freshness threshold."
                        latest_fetched_at = update.received_at.isoformat()
                        latest_data_key = update.provider_symbol
                    entries.append(
                        {
                            "resource": f"crypto_realtime_{resource}",
                            "provider": spec.provider,
                            "target": normalize_symbol(target),
                            "status": status,
                            "ok": ok,
                            "row_count": 1 if update is not None else 0,
                            "required": collector_enabled and spec.verified,
                            "latest_fetched_at": latest_fetched_at,
                            "latest_data_key": latest_data_key,
                            "data_quality": data_quality,
                            "reason": reason,
                        }
                    )
        return entries


crypto_realtime_store = CryptoRealtimeStore()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (float, int)):
        return float(value)
    cleaned = str(value).strip().replace(",", "")
    if cleaned == "" or cleaned.lower() in {"null", "none", "nan"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _datetime_from_millis(value: Any) -> datetime | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return datetime.fromtimestamp(parsed / 1000, tz=timezone.utc)


def _datetime_from_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _feed_lag_ms(*, event_time: datetime | None, received_at: datetime) -> int | None:
    if event_time is None:
        return None
    return max(int((received_at - event_time).total_seconds() * 1000), 0)


def _provider_symbol_to_symbol(provider_symbol: str) -> str:
    return normalize_symbol(provider_symbol.replace("_", "-"))


def _bitopro_provider_symbols() -> tuple[str, ...]:
    return tuple(
        instrument.provider_symbol.upper()
        for instrument in list_provider_instruments(provider=BITOPRO_PROVIDER, instrument_type=SPOT)
        if TICKER_RESOURCE in instrument.resources
    )


def _binance_stream_symbol(instrument: ProviderInstrument) -> str:
    return instrument.provider_symbol.lower()


RealtimeResourcePredicate = Callable[[ProviderInstrument, str], bool]


def _resource_enabled(
    resource_enabled: RealtimeResourcePredicate | None,
    instrument: ProviderInstrument,
    resource: str,
) -> bool:
    return resource in instrument.resources and (
        resource_enabled is None or resource_enabled(instrument, resource)
    )


def build_crypto_realtime_stream_specs(
    *,
    resource_enabled: RealtimeResourcePredicate | None = None,
) -> list[CryptoRealtimeStreamSpec]:
    bitopro_ticker_instruments = tuple(
        instrument
        for instrument in list_provider_instruments(provider=BITOPRO_PROVIDER, instrument_type=SPOT)
        if _resource_enabled(resource_enabled, instrument, TICKER_RESOURCE)
    )
    bitopro_order_book_instruments = tuple(
        instrument
        for instrument in list_provider_instruments(provider=BITOPRO_PROVIDER, instrument_type=SPOT)
        if _resource_enabled(resource_enabled, instrument, ORDER_BOOK_RESOURCE)
    )
    bitopro_pairs = tuple(instrument.provider_symbol.upper() for instrument in bitopro_ticker_instruments)
    bitopro_order_pairs = tuple(
        f"{instrument.provider_symbol.upper()}:{settings.crypto_market_ws_order_book_depth}"
        for instrument in bitopro_order_book_instruments
    )
    binance_spot = tuple(
        instrument
        for instrument in list_provider_instruments(provider=BINANCE_PROVIDER, instrument_type=SPOT)
        if any(
            _resource_enabled(resource_enabled, instrument, resource)
            for resource in (TICKER_RESOURCE, ORDER_BOOK_RESOURCE, OHLCV_RESOURCE)
        )
    )
    okx_spot = tuple(
        instrument
        for instrument in list_provider_instruments(provider=OKX_PROVIDER, instrument_type=SPOT)
        if any(
            _resource_enabled(resource_enabled, instrument, resource)
            for resource in (TICKER_RESOURCE, ORDER_BOOK_RESOURCE, OHLCV_RESOURCE)
        )
    )
    specs: list[CryptoRealtimeStreamSpec] = []
    if bitopro_pairs:
        specs.append(
            CryptoRealtimeStreamSpec(
                provider=BITOPRO_PROVIDER,
                resource=TICKER_RESOURCE,
                symbols=tuple(instrument.symbol for instrument in bitopro_ticker_instruments),
                url=(
                    f"{settings.bitopro_ws_base_url.rstrip('/')}/v1/pub/tickers?"
                    + urlencode({"pairs": ",".join(bitopro_pairs)})
                ),
                notes="BitoPro public ticker stream.",
            )
        )
    if bitopro_order_pairs:
        specs.append(
            CryptoRealtimeStreamSpec(
                provider=BITOPRO_PROVIDER,
                resource=ORDER_BOOK_RESOURCE,
                symbols=tuple(instrument.symbol for instrument in bitopro_order_book_instruments),
                url=(
                    f"{settings.bitopro_ws_base_url.rstrip('/')}/v1/pub/order-books?"
                    + urlencode({"pairs": ",".join(bitopro_order_pairs)})
                ),
                notes="BitoPro public order-book stream with bounded depth.",
            )
        )
    binance_streams: list[str] = []
    binance_resources: list[str] = []
    for instrument in binance_spot:
        symbol = _binance_stream_symbol(instrument)
        if _resource_enabled(resource_enabled, instrument, TICKER_RESOURCE):
            binance_streams.append(f"{symbol}@miniTicker")
            if TICKER_RESOURCE not in binance_resources:
                binance_resources.append(TICKER_RESOURCE)
        if _resource_enabled(resource_enabled, instrument, ORDER_BOOK_RESOURCE):
            binance_streams.append(f"{symbol}@depth{settings.crypto_market_ws_order_book_depth}")
            if ORDER_BOOK_RESOURCE not in binance_resources:
                binance_resources.append(ORDER_BOOK_RESOURCE)
        if _resource_enabled(resource_enabled, instrument, OHLCV_RESOURCE):
            binance_streams.append(f"{symbol}@kline_1m")
            if OHLCV_RESOURCE not in binance_resources:
                binance_resources.append(OHLCV_RESOURCE)
    if binance_streams:
        specs.append(
            CryptoRealtimeStreamSpec(
                provider=BINANCE_PROVIDER,
                resource="combined",
                symbols=tuple(instrument.symbol for instrument in binance_spot),
                url=f"{settings.binance_spot_ws_base_url.rstrip('/')}/stream?streams={'/'.join(binance_streams)}",
                notes="Binance combined stream for mini ticker, bounded depth, and 1m kline.",
                message_resources=tuple(binance_resources),
            )
        )
    okx_args: list[dict[str, str]] = []
    okx_resources: list[str] = []
    for instrument in okx_spot:
        if _resource_enabled(resource_enabled, instrument, TICKER_RESOURCE):
            okx_args.append({"channel": "tickers", "instId": instrument.provider_symbol})
            if TICKER_RESOURCE not in okx_resources:
                okx_resources.append(TICKER_RESOURCE)
        if _resource_enabled(resource_enabled, instrument, ORDER_BOOK_RESOURCE):
            okx_args.append({"channel": "books5", "instId": instrument.provider_symbol})
            if ORDER_BOOK_RESOURCE not in okx_resources:
                okx_resources.append(ORDER_BOOK_RESOURCE)
        if _resource_enabled(resource_enabled, instrument, OHLCV_RESOURCE):
            okx_args.append({"channel": "candle1m", "instId": instrument.provider_symbol})
            if OHLCV_RESOURCE not in okx_resources:
                okx_resources.append(OHLCV_RESOURCE)
    if okx_args:
        specs.append(
            CryptoRealtimeStreamSpec(
                provider=OKX_PROVIDER,
                resource="combined",
                symbols=tuple(instrument.symbol for instrument in okx_spot),
                url=settings.okx_ws_public_url,
                verified=False,
                notes="OKX public stream scaffold; official docs must be re-verified before enabling by default.",
                subscribe_message={"op": "subscribe", "args": okx_args},
                message_resources=tuple(okx_resources),
            )
        )
    return specs


def _update_from_bitopro_ticker(payload: dict[str, Any], *, received_at: datetime) -> CryptoRealtimeUpdate | None:
    provider_symbol = str(payload.get("pair") or "").strip().upper()
    if not provider_symbol:
        return None
    event_time = _datetime_from_millis(payload.get("timestamp")) or _datetime_from_iso(payload.get("datetime"))
    symbol = _provider_symbol_to_symbol(provider_symbol)
    return CryptoRealtimeUpdate(
        provider=BITOPRO_PROVIDER,
        resource=TICKER_RESOURCE,
        symbol=symbol,
        provider_symbol=provider_symbol.lower(),
        instrument_type=SPOT,
        event_time=event_time,
        received_at=received_at,
        feed_lag_ms=_feed_lag_ms(event_time=event_time, received_at=received_at),
        sequence=None,
        data={
            "last_price": _parse_float(payload.get("lastPrice")),
            "high_24h": _parse_float(payload.get("high24hr")),
            "low_24h": _parse_float(payload.get("low24hr")),
            "price_change_24h": _parse_float(payload.get("priceChange24hr")),
            "base_volume_24h": _parse_float(payload.get("volume24hr")),
        },
        raw_payload=payload,
    )


def _level_from_bitopro(value: Any) -> dict[str, float | int | None] | None:
    if not isinstance(value, dict):
        return None
    return {
        "price": _parse_float(value.get("price")),
        "size": _parse_float(value.get("amount")),
        "count": _parse_int(value.get("count")),
    }


def _level_from_sequence(value: Any) -> dict[str, float | int | None] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    return {
        "price": _parse_float(value[0]),
        "size": _parse_float(value[1]),
        "count": _parse_int(value[2]) if len(value) > 2 else None,
    }


def _order_book_data(
    *,
    bids: list[dict[str, float | int | None]],
    asks: list[dict[str, float | int | None]],
) -> dict[str, Any]:
    best_bid = bids[0] if bids else {}
    best_ask = asks[0] if asks else {}
    best_bid_price = _parse_float(best_bid.get("price"))
    best_ask_price = _parse_float(best_ask.get("price"))
    spread = (
        best_ask_price - best_bid_price
        if best_bid_price is not None and best_ask_price is not None
        else None
    )
    midpoint = (
        (best_ask_price + best_bid_price) / 2
        if best_bid_price is not None and best_ask_price is not None
        else None
    )
    return {
        "best_bid_price": best_bid_price,
        "best_bid_size": _parse_float(best_bid.get("size")),
        "best_ask_price": best_ask_price,
        "best_ask_size": _parse_float(best_ask.get("size")),
        "spread": spread,
        "spread_pct": (spread / midpoint * 100) if spread is not None and midpoint else None,
        "bids": bids,
        "asks": asks,
    }


def _update_from_bitopro_order_book(payload: dict[str, Any], *, received_at: datetime) -> CryptoRealtimeUpdate | None:
    provider_symbol = str(payload.get("pair") or "").strip().upper()
    if not provider_symbol:
        return None
    event_time = _datetime_from_millis(payload.get("timestamp")) or _datetime_from_iso(payload.get("datetime"))
    bids = [level for level in (_level_from_bitopro(row) for row in payload.get("bids", [])) if level is not None]
    asks = [level for level in (_level_from_bitopro(row) for row in payload.get("asks", [])) if level is not None]
    return CryptoRealtimeUpdate(
        provider=BITOPRO_PROVIDER,
        resource=ORDER_BOOK_RESOURCE,
        symbol=_provider_symbol_to_symbol(provider_symbol),
        provider_symbol=provider_symbol.lower(),
        instrument_type=SPOT,
        event_time=event_time,
        received_at=received_at,
        feed_lag_ms=_feed_lag_ms(event_time=event_time, received_at=received_at),
        sequence=None,
        data=_order_book_data(bids=bids, asks=asks),
        raw_payload=payload,
    )


def _update_from_binance_mini_ticker(payload: dict[str, Any], *, received_at: datetime) -> CryptoRealtimeUpdate | None:
    provider_symbol = str(payload.get("s") or "").strip().upper()
    if not provider_symbol:
        return None
    event_time = _datetime_from_millis(payload.get("E"))
    return CryptoRealtimeUpdate(
        provider=BINANCE_PROVIDER,
        resource=TICKER_RESOURCE,
        symbol=_provider_symbol_to_symbol(provider_symbol.replace("USDT", "-USDT")),
        provider_symbol=provider_symbol,
        instrument_type=SPOT,
        event_time=event_time,
        received_at=received_at,
        feed_lag_ms=_feed_lag_ms(event_time=event_time, received_at=received_at),
        sequence=None,
        data={
            "last_price": _parse_float(payload.get("c")),
            "high_24h": _parse_float(payload.get("h")),
            "low_24h": _parse_float(payload.get("l")),
            "base_volume_24h": _parse_float(payload.get("v")),
            "quote_volume_24h": _parse_float(payload.get("q")),
        },
        raw_payload=payload,
    )


def _binance_symbol_from_stream(stream_name: str | None) -> str | None:
    if not stream_name:
        return None
    raw_symbol = stream_name.split("@", maxsplit=1)[0].upper()
    return _binance_symbol_from_provider_symbol(raw_symbol)


def _binance_symbol_from_provider_symbol(provider_symbol: str | None) -> str | None:
    raw_symbol = str(provider_symbol or "").strip().upper()
    if raw_symbol.endswith("USDT"):
        return f"{raw_symbol[:-4]}-USDT"
    return _provider_symbol_to_symbol(raw_symbol)


def _update_from_binance_order_book(
    payload: dict[str, Any],
    *,
    received_at: datetime,
    stream_name: str | None,
) -> CryptoRealtimeUpdate | None:
    symbol = _binance_symbol_from_provider_symbol(payload.get("s")) or _binance_symbol_from_stream(stream_name)
    normalized_symbol = normalize_symbol(str(symbol or ""))
    if not normalized_symbol:
        return None
    provider_symbol = normalized_symbol.replace("-", "")
    event_time = _datetime_from_millis(payload.get("E"))
    bids_key = "bids" if "bids" in payload else "b"
    asks_key = "asks" if "asks" in payload else "a"
    bids = [level for level in (_level_from_sequence(row) for row in payload.get(bids_key, [])) if level is not None]
    asks = [level for level in (_level_from_sequence(row) for row in payload.get(asks_key, [])) if level is not None]
    return CryptoRealtimeUpdate(
        provider=BINANCE_PROVIDER,
        resource=ORDER_BOOK_RESOURCE,
        symbol=normalized_symbol,
        provider_symbol=provider_symbol,
        instrument_type=SPOT,
        event_time=event_time,
        received_at=received_at,
        feed_lag_ms=_feed_lag_ms(event_time=event_time, received_at=received_at),
        sequence=_parse_int(payload.get("lastUpdateId") or payload.get("u")),
        data=_order_book_data(bids=bids, asks=asks),
        raw_payload=payload,
    )


def _update_from_binance_kline(payload: dict[str, Any], *, received_at: datetime) -> CryptoRealtimeUpdate | None:
    kline = payload.get("k") if isinstance(payload.get("k"), dict) else None
    if not kline:
        return None
    provider_symbol = str(kline.get("s") or payload.get("s") or "").strip().upper()
    if not provider_symbol:
        return None
    symbol = _binance_symbol_from_provider_symbol(provider_symbol) or provider_symbol
    event_time = _datetime_from_millis(payload.get("E"))
    bar_time = _datetime_from_millis(kline.get("t"))
    return CryptoRealtimeUpdate(
        provider=BINANCE_PROVIDER,
        resource=OHLCV_RESOURCE,
        symbol=normalize_symbol(symbol),
        provider_symbol=provider_symbol,
        instrument_type=SPOT,
        event_time=event_time,
        received_at=received_at,
        feed_lag_ms=_feed_lag_ms(event_time=event_time, received_at=received_at),
        sequence=_parse_int(kline.get("L")),
        data={
            "interval": kline.get("i"),
            "bar_time": bar_time.isoformat() if bar_time else None,
            "open_price": _parse_float(kline.get("o")),
            "high_price": _parse_float(kline.get("h")),
            "low_price": _parse_float(kline.get("l")),
            "close_price": _parse_float(kline.get("c")),
            "base_volume": _parse_float(kline.get("v")),
            "quote_volume": _parse_float(kline.get("q")),
            "closed": bool(kline.get("x")),
        },
        raw_payload=payload,
    )


def _update_from_okx_message(payload: dict[str, Any], *, received_at: datetime) -> list[CryptoRealtimeUpdate]:
    arg = payload.get("arg") if isinstance(payload.get("arg"), dict) else {}
    channel = str(arg.get("channel") or "").strip()
    provider_symbol = str(arg.get("instId") or "").strip().upper()
    rows = payload.get("data") if isinstance(payload.get("data"), list) else []
    updates: list[CryptoRealtimeUpdate] = []
    for row in rows:
        if not isinstance(row, dict) and not isinstance(row, list):
            continue
        event_time = None
        data: dict[str, Any] = {}
        resource = TICKER_RESOURCE
        if channel == "tickers" and isinstance(row, dict):
            event_time = _datetime_from_millis(row.get("ts"))
            data = {
                "last_price": _parse_float(row.get("last")),
                "bid_price": _parse_float(row.get("bidPx")),
                "ask_price": _parse_float(row.get("askPx")),
                "high_24h": _parse_float(row.get("high24h")),
                "low_24h": _parse_float(row.get("low24h")),
                "base_volume_24h": _parse_float(row.get("vol24h")),
                "quote_volume_24h": _parse_float(row.get("volCcy24h")),
            }
        elif channel.startswith("books") and isinstance(row, dict):
            resource = ORDER_BOOK_RESOURCE
            event_time = _datetime_from_millis(row.get("ts"))
            bids = [level for level in (_level_from_sequence(item) for item in row.get("bids", [])) if level is not None]
            asks = [level for level in (_level_from_sequence(item) for item in row.get("asks", [])) if level is not None]
            data = _order_book_data(bids=bids, asks=asks)
        elif channel.startswith("candle") and isinstance(row, list) and len(row) >= 6:
            resource = OHLCV_RESOURCE
            event_time = _datetime_from_millis(row[0])
            data = {
                "interval": channel.removeprefix("candle"),
                "bar_time": event_time.isoformat() if event_time else None,
                "open_price": _parse_float(row[1]),
                "high_price": _parse_float(row[2]),
                "low_price": _parse_float(row[3]),
                "close_price": _parse_float(row[4]),
                "base_volume": _parse_float(row[5]),
                "quote_volume": _parse_float(row[6]) if len(row) > 6 else None,
            }
        else:
            continue
        updates.append(
            CryptoRealtimeUpdate(
                provider=OKX_PROVIDER,
                resource=resource,
                symbol=_provider_symbol_to_symbol(provider_symbol),
                provider_symbol=provider_symbol,
                instrument_type=SPOT,
                event_time=event_time,
                received_at=received_at,
                feed_lag_ms=_feed_lag_ms(event_time=event_time, received_at=received_at),
                sequence=_parse_int(row.get("seqId")) if isinstance(row, dict) else None,
                data=data,
                raw_payload=payload,
            )
        )
    return updates


def parse_realtime_message(
    provider: str,
    payload: Any,
    *,
    received_at: datetime | None = None,
    stream_name: str | None = None,
) -> list[CryptoRealtimeUpdate]:
    if not isinstance(payload, dict):
        return []
    current = received_at or utc_now()
    normalized_provider = normalize_provider(provider)
    if normalized_provider == BITOPRO_PROVIDER:
        event = str(payload.get("event") or "").strip().upper()
        if event == "TICKER":
            update = _update_from_bitopro_ticker(payload, received_at=current)
            return [update] if update else []
        if event == "ORDER_BOOK":
            update = _update_from_bitopro_order_book(payload, received_at=current)
            return [update] if update else []
        return []
    if normalized_provider == BINANCE_PROVIDER:
        wrapped_stream = payload.get("stream") if isinstance(payload.get("stream"), str) else None
        row = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        stream = wrapped_stream or stream_name
        event = str(row.get("e") or "").strip()
        if event == "24hrMiniTicker":
            update = _update_from_binance_mini_ticker(row, received_at=current)
            return [update] if update else []
        if event == "depthUpdate" or "bids" in row or "b" in row:
            update = _update_from_binance_order_book(row, received_at=current, stream_name=stream)
            return [update] if update else []
        if event == "kline":
            update = _update_from_binance_kline(row, received_at=current)
            return [update] if update else []
        return []
    if normalized_provider == OKX_PROVIDER:
        return _update_from_okx_message(payload, received_at=current)
    return []


def apply_realtime_message(
    provider: str,
    payload: Any,
    *,
    received_at: datetime | None = None,
    stream_name: str | None = None,
    store: CryptoRealtimeStore = crypto_realtime_store,
) -> list[dict[str, Any]]:
    updates = parse_realtime_message(provider, payload, received_at=received_at, stream_name=stream_name)
    for update in updates:
        store.update(update)
    return [update.to_dict(now=received_at or utc_now()) for update in updates]

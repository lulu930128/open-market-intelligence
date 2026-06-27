from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from urllib.parse import urlencode

import requests

from app.config import settings
from app.crypto_market.contract import (
    BINANCE_PROVIDER,
    BITOPRO_PROVIDER,
    COINGECKO_COIN_IDS,
    COINGECKO_PROVIDER,
    OKX_PROVIDER,
    PERPETUAL,
    SPOT,
    ProviderInstrument,
    get_provider_instrument,
    normalize_symbol,
    split_symbol,
)
from app.http_client import get as http_get


class CryptoMarketDataFetchError(Exception):
    pass


@dataclass(frozen=True)
class CryptoTickerRecord:
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    last_price: float | None
    bid_price: float | None
    bid_size: float | None
    ask_price: float | None
    ask_size: float | None
    high_24h: float | None
    low_24h: float | None
    price_change_24h: float | None
    price_change_pct_24h: float | None
    base_volume_24h: float | None
    quote_volume_24h: float | None
    event_time: datetime | None
    source_url: str
    raw_payload_hash: str
    raw_payload: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class CryptoOrderBookRecord:
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    depth_limit: int
    bids: list[dict[str, float | int | None]]
    asks: list[dict[str, float | int | None]]
    best_bid_price: float | None
    best_bid_size: float | None
    best_ask_price: float | None
    best_ask_size: float | None
    spread: float | None
    spread_pct: float | None
    event_time: datetime | None
    source_url: str
    raw_payload_hash: str
    raw_payload: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class CryptoOhlcvBarRecord:
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    interval: str
    bar_time: datetime
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    base_volume: float | None
    quote_volume: float | None
    source_url: str
    raw_payload_hash: str
    raw_payload: Any
    fetched_at: datetime


@dataclass(frozen=True)
class CryptoDerivativesMetricRecord:
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    mark_price: float | None
    index_price: float | None
    funding_rate: float | None
    next_funding_time: datetime | None
    open_interest: float | None
    open_interest_value: float | None
    event_time: datetime | None
    source_url: str
    raw_payload_hash: str
    raw_payload: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class CryptoMarketCapRecord:
    provider: str
    coin_id: str
    symbol: str
    name: str | None
    vs_currency: str
    current_price: float | None
    market_cap: float | None
    market_cap_rank: int | None
    total_volume: float | None
    high_24h: float | None
    low_24h: float | None
    price_change_pct_24h: float | None
    circulating_supply: float | None
    total_supply: float | None
    max_supply: float | None
    last_updated: datetime | None
    source_url: str
    raw_payload_hash: str
    raw_payload: dict[str, Any]
    fetched_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_base_url(value: str) -> str:
    return value.rstrip("/")


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def raw_payload_json(value: Any) -> str:
    return _json_dumps(value)


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
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


def _datetime_from_seconds(value: Any) -> datetime | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return datetime.fromtimestamp(parsed, tz=timezone.utc)


def _datetime_from_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _request_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    try:
        response = http_get(
            url,
            params=params,
            headers=headers,
            timeout=settings.crypto_market_http_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise CryptoMarketDataFetchError(f"Failed to fetch crypto market data from {url}: {exc}") from exc


def _response_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{_clean_base_url(base_url)}{path}"
    if params:
        return f"{url}?{urlencode(params)}"
    return url


def _ticker_from_instrument(
    instrument: ProviderInstrument,
    *,
    last_price: float | None,
    bid_price: float | None,
    bid_size: float | None,
    ask_price: float | None,
    ask_size: float | None,
    high_24h: float | None,
    low_24h: float | None,
    price_change_24h: float | None,
    price_change_pct_24h: float | None,
    base_volume_24h: float | None,
    quote_volume_24h: float | None,
    event_time: datetime | None,
    source_url: str,
    payload: dict[str, Any],
    fetched_at: datetime,
) -> CryptoTickerRecord:
    return CryptoTickerRecord(
        provider=instrument.provider,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        last_price=last_price,
        bid_price=bid_price,
        bid_size=bid_size,
        ask_price=ask_price,
        ask_size=ask_size,
        high_24h=high_24h,
        low_24h=low_24h,
        price_change_24h=price_change_24h,
        price_change_pct_24h=price_change_pct_24h,
        base_volume_24h=base_volume_24h,
        quote_volume_24h=quote_volume_24h,
        event_time=event_time,
        source_url=source_url,
        raw_payload_hash=_json_hash(payload),
        raw_payload=payload,
        fetched_at=fetched_at,
    )


def fetch_bitopro_ticker(symbol: str) -> CryptoTickerRecord:
    instrument = get_provider_instrument(
        provider=BITOPRO_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="ticker",
    )
    path = f"/tickers/{instrument.provider_symbol}"
    url = _response_url(settings.bitopro_api_base_url, path)
    fetched_at = _now()
    payload = _request_json(url)
    records = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(records, dict):
        row = records
    elif isinstance(records, list) and records:
        row = records[0]
    else:
        row = payload
    if not isinstance(row, dict):
        raise CryptoMarketDataFetchError("BitoPro ticker payload did not contain a ticker object.")
    return _ticker_from_instrument(
        instrument,
        last_price=_parse_float(row.get("lastPrice")),
        bid_price=None,
        bid_size=None,
        ask_price=None,
        ask_size=None,
        high_24h=_parse_float(row.get("high24hr")),
        low_24h=_parse_float(row.get("low24hr")),
        price_change_24h=_parse_float(row.get("priceChange24hr")),
        price_change_pct_24h=None,
        base_volume_24h=_parse_float(row.get("volume24hr")),
        quote_volume_24h=None,
        event_time=None,
        source_url=url,
        payload=payload if isinstance(payload, dict) else {"data": payload},
        fetched_at=fetched_at,
    )


def fetch_binance_ticker(symbol: str) -> CryptoTickerRecord:
    instrument = get_provider_instrument(
        provider=BINANCE_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="ticker",
    )
    params = {"symbol": instrument.provider_symbol}
    path = "/api/v3/ticker/24hr"
    url = _response_url(settings.binance_spot_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(f"{_clean_base_url(settings.binance_spot_api_base_url)}{path}", params=params)
    if not isinstance(payload, dict):
        raise CryptoMarketDataFetchError("Binance ticker payload did not contain a ticker object.")
    return _ticker_from_instrument(
        instrument,
        last_price=_parse_float(payload.get("lastPrice")),
        bid_price=_parse_float(payload.get("bidPrice")),
        bid_size=_parse_float(payload.get("bidQty")),
        ask_price=_parse_float(payload.get("askPrice")),
        ask_size=_parse_float(payload.get("askQty")),
        high_24h=_parse_float(payload.get("highPrice")),
        low_24h=_parse_float(payload.get("lowPrice")),
        price_change_24h=_parse_float(payload.get("priceChange")),
        price_change_pct_24h=_parse_float(payload.get("priceChangePercent")),
        base_volume_24h=_parse_float(payload.get("volume")),
        quote_volume_24h=_parse_float(payload.get("quoteVolume")),
        event_time=_datetime_from_millis(payload.get("closeTime")),
        source_url=url,
        payload=payload,
        fetched_at=fetched_at,
    )


def fetch_okx_ticker(symbol: str) -> CryptoTickerRecord:
    instrument = get_provider_instrument(
        provider=OKX_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="ticker",
    )
    params = {"instId": instrument.provider_symbol}
    path = "/api/v5/market/ticker"
    url = _response_url(settings.okx_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(f"{_clean_base_url(settings.okx_api_base_url)}{path}", params=params)
    data = payload.get("data") if isinstance(payload, dict) else None
    row = data[0] if isinstance(data, list) and data else None
    if not isinstance(row, dict):
        raise CryptoMarketDataFetchError("OKX ticker payload did not contain a ticker object.")
    open_24h = _parse_float(row.get("open24h"))
    last_price = _parse_float(row.get("last"))
    price_change = last_price - open_24h if last_price is not None and open_24h not in {None, 0} else None
    price_change_pct = (price_change / open_24h * 100) if price_change is not None and open_24h else None
    return _ticker_from_instrument(
        instrument,
        last_price=last_price,
        bid_price=_parse_float(row.get("bidPx")),
        bid_size=_parse_float(row.get("bidSz")),
        ask_price=_parse_float(row.get("askPx")),
        ask_size=_parse_float(row.get("askSz")),
        high_24h=_parse_float(row.get("high24h")),
        low_24h=_parse_float(row.get("low24h")),
        price_change_24h=price_change,
        price_change_pct_24h=price_change_pct,
        base_volume_24h=_parse_float(row.get("vol24h")),
        quote_volume_24h=_parse_float(row.get("volCcy24h")),
        event_time=_datetime_from_millis(row.get("ts")),
        source_url=url,
        payload=payload,
        fetched_at=fetched_at,
    )


def _level_from_sequence(value: Any) -> dict[str, float | int | None] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    return {
        "price": _parse_float(value[0]),
        "size": _parse_float(value[1]),
        "count": _parse_int(value[3]) if len(value) > 3 else None,
    }


def _level_from_dict(value: Any) -> dict[str, float | int | None] | None:
    if not isinstance(value, dict):
        return None
    return {
        "price": _parse_float(value.get("price")),
        "size": _parse_float(value.get("amount") or value.get("size") or value.get("qty")),
        "count": _parse_int(value.get("count")),
    }


def _book_record(
    instrument: ProviderInstrument,
    *,
    bids: list[dict[str, float | int | None]],
    asks: list[dict[str, float | int | None]],
    depth_limit: int,
    event_time: datetime | None,
    source_url: str,
    payload: dict[str, Any],
    fetched_at: datetime,
) -> CryptoOrderBookRecord:
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
    spread_pct = (spread / midpoint * 100) if spread is not None and midpoint else None
    return CryptoOrderBookRecord(
        provider=instrument.provider,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        depth_limit=depth_limit,
        bids=bids,
        asks=asks,
        best_bid_price=best_bid_price,
        best_bid_size=_parse_float(best_bid.get("size")),
        best_ask_price=best_ask_price,
        best_ask_size=_parse_float(best_ask.get("size")),
        spread=spread,
        spread_pct=spread_pct,
        event_time=event_time,
        source_url=source_url,
        raw_payload_hash=_json_hash(payload),
        raw_payload=payload,
        fetched_at=fetched_at,
    )


def fetch_bitopro_order_book(symbol: str, *, limit: int = 5) -> CryptoOrderBookRecord:
    instrument = get_provider_instrument(
        provider=BITOPRO_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="order_book",
    )
    normalized_limit = min(max(int(limit), 1), 50)
    params = {"limit": normalized_limit}
    path = f"/order-book/{instrument.provider_symbol}"
    url = _response_url(settings.bitopro_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(f"{_clean_base_url(settings.bitopro_api_base_url)}{path}", params=params)
    if not isinstance(payload, dict):
        raise CryptoMarketDataFetchError("BitoPro order book payload did not contain an object.")
    bids = [
        level
        for level in (_level_from_dict(row) for row in payload.get("bids", []))
        if level is not None
    ]
    asks = [
        level
        for level in (_level_from_dict(row) for row in payload.get("asks", []))
        if level is not None
    ]
    return _book_record(
        instrument,
        bids=bids,
        asks=asks,
        depth_limit=normalized_limit,
        event_time=None,
        source_url=url,
        payload=payload,
        fetched_at=fetched_at,
    )


def fetch_binance_order_book(symbol: str, *, limit: int = 5) -> CryptoOrderBookRecord:
    instrument = get_provider_instrument(
        provider=BINANCE_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="order_book",
    )
    normalized_limit = min(max(int(limit), 1), 5000)
    params = {"symbol": instrument.provider_symbol, "limit": normalized_limit}
    path = "/api/v3/depth"
    url = _response_url(settings.binance_spot_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(f"{_clean_base_url(settings.binance_spot_api_base_url)}{path}", params=params)
    if not isinstance(payload, dict):
        raise CryptoMarketDataFetchError("Binance order book payload did not contain an object.")
    bids = [
        level
        for level in (_level_from_sequence(row) for row in payload.get("bids", []))
        if level is not None
    ]
    asks = [
        level
        for level in (_level_from_sequence(row) for row in payload.get("asks", []))
        if level is not None
    ]
    return _book_record(
        instrument,
        bids=bids,
        asks=asks,
        depth_limit=normalized_limit,
        event_time=None,
        source_url=url,
        payload=payload,
        fetched_at=fetched_at,
    )


def fetch_okx_order_book(symbol: str, *, limit: int = 5) -> CryptoOrderBookRecord:
    instrument = get_provider_instrument(
        provider=OKX_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="order_book",
    )
    normalized_limit = min(max(int(limit), 1), 400)
    params = {"instId": instrument.provider_symbol, "sz": normalized_limit}
    path = "/api/v5/market/books"
    url = _response_url(settings.okx_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(f"{_clean_base_url(settings.okx_api_base_url)}{path}", params=params)
    data = payload.get("data") if isinstance(payload, dict) else None
    row = data[0] if isinstance(data, list) and data else None
    if not isinstance(row, dict):
        raise CryptoMarketDataFetchError("OKX order book payload did not contain an order book object.")
    bids = [
        level
        for level in (_level_from_sequence(level) for level in row.get("bids", []))
        if level is not None
    ]
    asks = [
        level
        for level in (_level_from_sequence(level) for level in row.get("asks", []))
        if level is not None
    ]
    return _book_record(
        instrument,
        bids=bids,
        asks=asks,
        depth_limit=normalized_limit,
        event_time=_datetime_from_millis(row.get("ts")),
        source_url=url,
        payload=payload,
        fetched_at=fetched_at,
    )


def _bar_record(
    instrument: ProviderInstrument,
    *,
    interval: str,
    bar_time: datetime | None,
    open_price: float | None,
    high_price: float | None,
    low_price: float | None,
    close_price: float | None,
    base_volume: float | None,
    quote_volume: float | None,
    source_url: str,
    payload: Any,
    fetched_at: datetime,
) -> CryptoOhlcvBarRecord | None:
    if bar_time is None:
        return None
    return CryptoOhlcvBarRecord(
        provider=instrument.provider,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        interval=interval,
        bar_time=bar_time,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        base_volume=base_volume,
        quote_volume=quote_volume,
        source_url=source_url,
        raw_payload_hash=_json_hash(payload),
        raw_payload=payload,
        fetched_at=fetched_at,
    )


def _bitopro_resolution(interval: str) -> str:
    if interval not in {"1m", "5m", "15m", "30m", "1h", "3h", "4h", "6h", "12h", "1d", "1w", "1M"}:
        raise ValueError(f"Unsupported BitoPro OHLC interval: {interval}")
    return interval


def _binance_interval(interval: str) -> str:
    if interval not in {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w", "1M"}:
        raise ValueError(f"Unsupported Binance kline interval: {interval}")
    return interval


def _okx_interval(interval: str) -> str:
    mapping = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D", "1w": "1W"}
    if interval not in mapping:
        raise ValueError(f"Unsupported OKX candle interval: {interval}")
    return mapping[interval]


def fetch_bitopro_ohlcv(
    symbol: str,
    *,
    interval: str = "1m",
    start_time: datetime,
    end_time: datetime,
) -> list[CryptoOhlcvBarRecord]:
    instrument = get_provider_instrument(
        provider=BITOPRO_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="ohlcv",
    )
    resolution = _bitopro_resolution(interval)
    params = {
        "resolution": resolution,
        "from": int(start_time.timestamp()),
        "to": int(end_time.timestamp()),
    }
    path = f"/trading-history/{instrument.provider_symbol}"
    url = _response_url(settings.bitopro_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(f"{_clean_base_url(settings.bitopro_api_base_url)}{path}", params=params)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise CryptoMarketDataFetchError("BitoPro OHLC payload did not contain a data list.")
    records: list[CryptoOhlcvBarRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = _bar_record(
            instrument,
            interval=interval,
            bar_time=_datetime_from_millis(row.get("timestamp")),
            open_price=_parse_float(row.get("open")),
            high_price=_parse_float(row.get("high")),
            low_price=_parse_float(row.get("low")),
            close_price=_parse_float(row.get("close")),
            base_volume=_parse_float(row.get("volume")),
            quote_volume=None,
            source_url=url,
            payload=row,
            fetched_at=fetched_at,
        )
        if record is not None:
            records.append(record)
    return records


def fetch_binance_ohlcv(symbol: str, *, interval: str = "1m", limit: int = 100) -> list[CryptoOhlcvBarRecord]:
    instrument = get_provider_instrument(
        provider=BINANCE_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="ohlcv",
    )
    normalized_interval = _binance_interval(interval)
    params = {"symbol": instrument.provider_symbol, "interval": normalized_interval, "limit": min(max(int(limit), 1), 1000)}
    path = "/api/v3/klines"
    url = _response_url(settings.binance_spot_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(f"{_clean_base_url(settings.binance_spot_api_base_url)}{path}", params=params)
    if not isinstance(payload, list):
        raise CryptoMarketDataFetchError("Binance kline payload did not contain a list.")
    records: list[CryptoOhlcvBarRecord] = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 6:
            continue
        record = _bar_record(
            instrument,
            interval=interval,
            bar_time=_datetime_from_millis(row[0]),
            open_price=_parse_float(row[1]),
            high_price=_parse_float(row[2]),
            low_price=_parse_float(row[3]),
            close_price=_parse_float(row[4]),
            base_volume=_parse_float(row[5]),
            quote_volume=_parse_float(row[7]) if len(row) > 7 else None,
            source_url=url,
            payload=row,
            fetched_at=fetched_at,
        )
        if record is not None:
            records.append(record)
    return records


def fetch_okx_ohlcv(symbol: str, *, interval: str = "1m", limit: int = 100) -> list[CryptoOhlcvBarRecord]:
    instrument = get_provider_instrument(
        provider=OKX_PROVIDER,
        symbol=symbol,
        instrument_type=SPOT,
        resource="ohlcv",
    )
    params = {"instId": instrument.provider_symbol, "bar": _okx_interval(interval), "limit": min(max(int(limit), 1), 300)}
    path = "/api/v5/market/candles"
    url = _response_url(settings.okx_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(f"{_clean_base_url(settings.okx_api_base_url)}{path}", params=params)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise CryptoMarketDataFetchError("OKX candles payload did not contain a data list.")
    records: list[CryptoOhlcvBarRecord] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        record = _bar_record(
            instrument,
            interval=interval,
            bar_time=_datetime_from_millis(row[0]),
            open_price=_parse_float(row[1]),
            high_price=_parse_float(row[2]),
            low_price=_parse_float(row[3]),
            close_price=_parse_float(row[4]),
            base_volume=_parse_float(row[5]),
            quote_volume=_parse_float(row[6]) if len(row) > 6 else None,
            source_url=url,
            payload=row,
            fetched_at=fetched_at,
        )
        if record is not None:
            records.append(record)
    return records


def fetch_binance_derivatives_metric(symbol: str) -> CryptoDerivativesMetricRecord:
    instrument = get_provider_instrument(
        provider=BINANCE_PROVIDER,
        symbol=symbol,
        instrument_type=PERPETUAL,
        resource="derivatives",
    )
    params = {"symbol": instrument.provider_symbol}
    premium_path = "/fapi/v1/premiumIndex"
    oi_path = "/fapi/v1/openInterest"
    fetched_at = _now()
    premium_payload = _request_json(
        f"{_clean_base_url(settings.binance_futures_api_base_url)}{premium_path}",
        params=params,
    )
    oi_payload = _request_json(
        f"{_clean_base_url(settings.binance_futures_api_base_url)}{oi_path}",
        params=params,
    )
    if not isinstance(premium_payload, dict) or not isinstance(oi_payload, dict):
        raise CryptoMarketDataFetchError("Binance derivatives payload did not contain expected objects.")
    payload = {"premium_index": premium_payload, "open_interest": oi_payload}
    source_url = _response_url(settings.binance_futures_api_base_url, premium_path, params)
    event_times = [
        value
        for value in (
            _datetime_from_millis(premium_payload.get("time")),
            _datetime_from_millis(oi_payload.get("time")),
        )
        if value is not None
    ]
    return CryptoDerivativesMetricRecord(
        provider=instrument.provider,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        mark_price=_parse_float(premium_payload.get("markPrice")),
        index_price=_parse_float(premium_payload.get("indexPrice")),
        funding_rate=_parse_float(premium_payload.get("lastFundingRate")),
        next_funding_time=_datetime_from_millis(premium_payload.get("nextFundingTime")),
        open_interest=_parse_float(oi_payload.get("openInterest")),
        open_interest_value=None,
        event_time=max(event_times) if event_times else None,
        source_url=source_url,
        raw_payload_hash=_json_hash(payload),
        raw_payload=payload,
        fetched_at=fetched_at,
    )


def fetch_okx_derivatives_metric(symbol: str) -> CryptoDerivativesMetricRecord:
    instrument = get_provider_instrument(
        provider=OKX_PROVIDER,
        symbol=symbol,
        instrument_type=PERPETUAL,
        resource="derivatives",
    )
    funding_params = {"instId": instrument.provider_symbol}
    oi_params = {"instType": "SWAP", "instId": instrument.provider_symbol}
    funding_path = "/api/v5/public/funding-rate"
    oi_path = "/api/v5/public/open-interest"
    fetched_at = _now()
    funding_payload = _request_json(f"{_clean_base_url(settings.okx_api_base_url)}{funding_path}", params=funding_params)
    oi_payload = _request_json(f"{_clean_base_url(settings.okx_api_base_url)}{oi_path}", params=oi_params)
    funding_rows = funding_payload.get("data") if isinstance(funding_payload, dict) else None
    oi_rows = oi_payload.get("data") if isinstance(oi_payload, dict) else None
    funding = funding_rows[0] if isinstance(funding_rows, list) and funding_rows else {}
    oi = oi_rows[0] if isinstance(oi_rows, list) and oi_rows else {}
    if not isinstance(funding, dict) or not isinstance(oi, dict):
        raise CryptoMarketDataFetchError("OKX derivatives payload did not contain expected objects.")
    payload = {"funding_rate": funding_payload, "open_interest": oi_payload}
    event_times = [
        value
        for value in (
            _datetime_from_millis(funding.get("fundingTime")),
            _datetime_from_millis(oi.get("ts")),
        )
        if value is not None
    ]
    return CryptoDerivativesMetricRecord(
        provider=instrument.provider,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        mark_price=None,
        index_price=None,
        funding_rate=_parse_float(funding.get("fundingRate")),
        next_funding_time=_datetime_from_millis(funding.get("nextFundingTime")),
        open_interest=_parse_float(oi.get("oi")),
        open_interest_value=_parse_float(oi.get("oiCcy")),
        event_time=max(event_times) if event_times else None,
        source_url=_response_url(settings.okx_api_base_url, funding_path, funding_params),
        raw_payload_hash=_json_hash(payload),
        raw_payload=payload,
        fetched_at=fetched_at,
    )


def fetch_coingecko_market_caps(
    *,
    ids: list[str] | None = None,
    vs_currency: str = "usd",
    per_page: int = 100,
) -> list[CryptoMarketCapRecord]:
    requested_ids = ids or list(COINGECKO_COIN_IDS.values())
    normalized_ids = [str(coin_id).strip().lower() for coin_id in requested_ids if str(coin_id).strip()]
    params = {
        "vs_currency": vs_currency.strip().lower(),
        "ids": ",".join(normalized_ids),
        "order": "market_cap_desc",
        "per_page": min(max(int(per_page), 1), 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "1h,24h,7d",
    }
    headers = {}
    api_key = (settings.coingecko_api_key or "").strip().strip('"').strip("'")
    if api_key:
        headers[settings.coingecko_api_key_header] = api_key
    path = "/coins/markets"
    url = _response_url(settings.coingecko_api_base_url, path, params)
    fetched_at = _now()
    payload = _request_json(
        f"{_clean_base_url(settings.coingecko_api_base_url)}{path}",
        params=params,
        headers=headers or None,
    )
    if not isinstance(payload, list):
        raise CryptoMarketDataFetchError("CoinGecko market data payload did not contain a list.")
    records: list[CryptoMarketCapRecord] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        records.append(
            CryptoMarketCapRecord(
                provider=COINGECKO_PROVIDER,
                coin_id=str(row.get("id") or "").strip().lower(),
                symbol=str(row.get("symbol") or "").strip().upper(),
                name=str(row.get("name")).strip() if row.get("name") else None,
                vs_currency=params["vs_currency"],
                current_price=_parse_float(row.get("current_price")),
                market_cap=_parse_float(row.get("market_cap")),
                market_cap_rank=_parse_int(row.get("market_cap_rank")),
                total_volume=_parse_float(row.get("total_volume")),
                high_24h=_parse_float(row.get("high_24h")),
                low_24h=_parse_float(row.get("low_24h")),
                price_change_pct_24h=_parse_float(row.get("price_change_percentage_24h")),
                circulating_supply=_parse_float(row.get("circulating_supply")),
                total_supply=_parse_float(row.get("total_supply")),
                max_supply=_parse_float(row.get("max_supply")),
                last_updated=_datetime_from_iso(row.get("last_updated")),
                source_url=url,
                raw_payload_hash=_json_hash(row),
                raw_payload=row,
                fetched_at=fetched_at,
            )
        )
    return records


def provider_for_ticker(provider: str):
    return {
        BITOPRO_PROVIDER: fetch_bitopro_ticker,
        BINANCE_PROVIDER: fetch_binance_ticker,
        OKX_PROVIDER: fetch_okx_ticker,
    }[provider]


def provider_for_order_book(provider: str):
    return {
        BITOPRO_PROVIDER: fetch_bitopro_order_book,
        BINANCE_PROVIDER: fetch_binance_order_book,
        OKX_PROVIDER: fetch_okx_order_book,
    }[provider]


def provider_for_ohlcv(provider: str):
    return {
        BITOPRO_PROVIDER: fetch_bitopro_ohlcv,
        BINANCE_PROVIDER: fetch_binance_ohlcv,
        OKX_PROVIDER: fetch_okx_ohlcv,
    }[provider]


def provider_for_derivatives(provider: str):
    return {
        BINANCE_PROVIDER: fetch_binance_derivatives_metric,
        OKX_PROVIDER: fetch_okx_derivatives_metric,
    }[provider]


def symbol_from_base_quote(base_asset: str, quote_asset: str) -> str:
    return normalize_symbol(f"{base_asset}-{quote_asset}")


def coingecko_ids_for_assets(assets: list[str] | None = None) -> list[str]:
    if assets is None:
        return list(COINGECKO_COIN_IDS.values())
    ids: list[str] = []
    for asset in assets:
        normalized_asset = str(asset or "").strip().upper()
        coin_id = COINGECKO_COIN_IDS.get(normalized_asset)
        if coin_id and coin_id not in ids:
            ids.append(coin_id)
    return ids


def canonical_parts(symbol: str) -> tuple[str, str]:
    return split_symbol(symbol)

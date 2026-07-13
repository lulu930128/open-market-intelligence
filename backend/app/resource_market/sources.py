from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from app.config import settings
from app.resource_market.contract import (
    ResourceInstrument,
    SUPPORTED_RESOURCE_OHLCV_INTERVALS,
    YAHOO_CHART_PROVIDER,
)
from app.resource_market.providers import yahoo


YAHOO_CHART_URL = yahoo.CHART_URL
SUPPORTED_YAHOO_INTERVALS = set(SUPPORTED_RESOURCE_OHLCV_INTERVALS)
YAHOO_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "1d": "1d",
    "1w": "1wk",
    "1M": "1mo",
}
YAHOO_RANGE_BY_INTERVAL = {
    "1m": "5d",
    "5m": "1mo",
    "15m": "60d",
    "30m": "60d",
    "1h": "2y",
    "1d": "10y",
    "1w": "max",
    "1M": "max",
}


class ResourceMarketDataFetchError(Exception):
    pass


@dataclass(frozen=True)
class ResourceQuoteRecord:
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    name: str
    root_folder: str
    group: str
    asset_class: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    contract_key: str
    last_price: float | None
    bid_price: float | None
    ask_price: float | None
    open_price: float | None
    high_price: float | None
    low_price: float | None
    previous_close: float | None
    price_change: float | None
    price_change_pct: float | None
    volume: float | None
    open_interest: float | None
    event_time: datetime | None
    source_url: str
    raw_payload_hash: str
    raw_payload: dict[str, Any]
    fetched_at: datetime


@dataclass(frozen=True)
class ResourceOhlcvRecord:
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    name: str
    root_folder: str
    group: str
    asset_class: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    contract_key: str
    interval: str
    bar_time: datetime
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    volume: float | None
    open_interest: float | None
    source_url: str
    raw_payload_hash: str
    raw_payload: dict[str, Any]
    fetched_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), timezone.utc)
    except (OSError, TypeError, ValueError):
        return None


def _normalize_ohlcv_bar_time(value: datetime, interval: str) -> datetime:
    if interval == "1M":
        return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if interval == "1w":
        week_start = value - timedelta(days=value.weekday())
        return week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    return value


def _list_value(values: Any, index: int) -> Any:
    if not isinstance(values, list) or index >= len(values):
        return None
    return values[index]


def _latest_valid_index(*series: Any) -> int | None:
    max_length = max((len(item) for item in series if isinstance(item, list)), default=0)
    for index in range(max_length - 1, -1, -1):
        if any(_parse_float(_list_value(item, index)) is not None for item in series):
            return index
    return None


def _compact_ohlcv_payload_metadata(
    *,
    payload_hash: str,
    result: dict[str, Any],
    timestamps: Any,
    interval: str,
) -> dict[str, Any]:
    meta = result.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    timestamp_values = timestamps if isinstance(timestamps, list) else []
    return {
        "source": YAHOO_CHART_PROVIDER,
        "payload_hash": payload_hash,
        "symbol": meta.get("symbol"),
        "exchange_name": meta.get("exchangeName"),
        "instrument_type": meta.get("instrumentType"),
        "timezone": meta.get("timezone"),
        "exchange_timezone_name": meta.get("exchangeTimezoneName"),
        "data_granularity": meta.get("dataGranularity"),
        "interval": interval,
        "timestamp_count": len(timestamp_values),
        "first_timestamp": timestamp_values[0] if timestamp_values else None,
        "last_timestamp": timestamp_values[-1] if timestamp_values else None,
    }


def _first_result(payload: dict[str, Any]) -> dict[str, Any]:
    error = payload.get("chart", {}).get("error")
    if error:
        raise ResourceMarketDataFetchError(str(error))
    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise ResourceMarketDataFetchError("Yahoo chart payload does not contain result data.")
    return result


def _quote_values(result: dict[str, Any]) -> dict[str, Any]:
    indicators = result.get("indicators") or {}
    quote_values = (indicators.get("quote") or [{}])[0]
    if not isinstance(quote_values, dict):
        raise ResourceMarketDataFetchError("Yahoo chart payload does not contain quote data.")
    return quote_values


def _validate_yahoo_symbol(meta: dict[str, Any], instrument: ResourceInstrument) -> None:
    returned_symbol = str(meta.get("symbol") or "").upper()
    expected_symbol = instrument.provider_symbol.upper()
    if returned_symbol and returned_symbol != expected_symbol:
        raise ResourceMarketDataFetchError(
            f"Yahoo chart symbol mismatch. requested={expected_symbol} returned={returned_symbol}."
        )


def fetch_yahoo_chart_payload(
    *,
    provider_symbol: str,
    range_value: str,
    interval: str,
    timeout_seconds: int | None = None,
) -> tuple[dict[str, Any], str]:
    payload, source_url = yahoo.fetch_chart_payload(
        provider_symbol=provider_symbol,
        range_value=range_value,
        interval=interval,
        timeout_seconds=timeout_seconds or settings.resource_market_http_timeout_seconds,
    )
    if not isinstance(payload, dict):
        raise ResourceMarketDataFetchError("Yahoo chart returned a non-object JSON payload.")
    return payload, source_url


def fetch_yahoo_chart_payload_for_interval(
    *,
    instrument: ResourceInstrument,
    interval: str,
) -> tuple[dict[str, Any], str]:
    normalized_interval = normalize_resource_interval(interval)
    return fetch_yahoo_chart_payload(
        provider_symbol=instrument.provider_symbol,
        range_value=YAHOO_RANGE_BY_INTERVAL[normalized_interval],
        interval=YAHOO_INTERVAL_MAP[normalized_interval],
    )


def normalize_resource_interval(interval: str | None) -> str:
    normalized = (interval or "15m").strip()
    if normalized not in SUPPORTED_YAHOO_INTERVALS:
        raise ValueError(f"interval must be one of: {', '.join(sorted(SUPPORTED_YAHOO_INTERVALS))}.")
    return normalized


def parse_yahoo_quote_record(
    payload: dict[str, Any],
    *,
    instrument: ResourceInstrument,
    source_url: str,
) -> ResourceQuoteRecord:
    result = _first_result(payload)
    meta = result.get("meta") or {}
    if not isinstance(meta, dict):
        raise ResourceMarketDataFetchError("Yahoo chart payload does not contain metadata.")
    _validate_yahoo_symbol(meta, instrument)

    quote_values = _quote_values(result)
    timestamps = result.get("timestamp") or []
    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []
    latest_index = _latest_valid_index(closes, opens, highs, lows)

    latest_close = (
        _parse_float(_list_value(closes, latest_index))
        if latest_index is not None
        else None
    )
    last_price = _parse_float(meta.get("regularMarketPrice")) or latest_close
    previous_close = _parse_float(meta.get("previousClose")) or _parse_float(
        meta.get("chartPreviousClose")
    )
    price_change = (
        last_price - previous_close
        if last_price is not None and previous_close is not None
        else None
    )
    price_change_pct = (
        (price_change / previous_close) * 100
        if price_change is not None and previous_close not in (None, 0)
        else None
    )
    event_time = _parse_timestamp(meta.get("regularMarketTime"))
    if event_time is None and latest_index is not None:
        event_time = _parse_timestamp(_list_value(timestamps, latest_index))

    return ResourceQuoteRecord(
        provider=YAHOO_CHART_PROVIDER,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        name=instrument.name,
        root_folder=instrument.root_folder,
        group=instrument.group,
        asset_class=instrument.asset_class,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        contract_key=instrument.contract_type,
        last_price=last_price,
        bid_price=None,
        ask_price=None,
        open_price=_parse_float(meta.get("regularMarketOpen"))
        or (
            _parse_float(_list_value(opens, latest_index))
            if latest_index is not None
            else None
        ),
        high_price=_parse_float(meta.get("regularMarketDayHigh"))
        or (
            _parse_float(_list_value(highs, latest_index))
            if latest_index is not None
            else None
        ),
        low_price=_parse_float(meta.get("regularMarketDayLow"))
        or (
            _parse_float(_list_value(lows, latest_index))
            if latest_index is not None
            else None
        ),
        previous_close=previous_close,
        price_change=price_change,
        price_change_pct=price_change_pct,
        volume=_parse_float(meta.get("regularMarketVolume"))
        or (
            _parse_float(_list_value(volumes, latest_index))
            if latest_index is not None
            else None
        ),
        open_interest=None,
        event_time=event_time,
        source_url=source_url,
        raw_payload_hash=_payload_hash(payload),
        raw_payload=payload,
        fetched_at=_now(),
    )


def parse_yahoo_ohlcv_records(
    payload: dict[str, Any],
    *,
    instrument: ResourceInstrument,
    interval: str,
    source_url: str,
    limit: int,
) -> list[ResourceOhlcvRecord]:
    normalized_interval = normalize_resource_interval(interval)
    result = _first_result(payload)
    meta = result.get("meta") or {}
    if isinstance(meta, dict):
        _validate_yahoo_symbol(meta, instrument)

    quote_values = _quote_values(result)
    timestamps = result.get("timestamp") or []
    opens = quote_values.get("open") or []
    highs = quote_values.get("high") or []
    lows = quote_values.get("low") or []
    closes = quote_values.get("close") or []
    volumes = quote_values.get("volume") or []
    fetched_at = _now()
    payload_hash = _payload_hash(payload)
    compact_raw_payload = _compact_ohlcv_payload_metadata(
        payload_hash=payload_hash,
        result=result,
        timestamps=timestamps,
        interval=normalized_interval,
    )
    records_by_time: dict[datetime, ResourceOhlcvRecord] = {}

    for index, timestamp in enumerate(timestamps):
        bar_time = _parse_timestamp(timestamp)
        close_price = _parse_float(_list_value(closes, index))
        if bar_time is None or close_price is None:
            continue
        bar_time = _normalize_ohlcv_bar_time(bar_time, normalized_interval)
        records_by_time[bar_time] = ResourceOhlcvRecord(
            provider=YAHOO_CHART_PROVIDER,
            exchange=instrument.exchange,
            symbol=instrument.symbol,
            provider_symbol=instrument.provider_symbol,
            name=instrument.name,
            root_folder=instrument.root_folder,
            group=instrument.group,
            asset_class=instrument.asset_class,
            base_asset=instrument.base_asset,
            quote_asset=instrument.quote_asset,
            instrument_type=instrument.instrument_type,
            contract_key=instrument.contract_type,
            interval=normalized_interval,
            bar_time=bar_time,
            open_price=_parse_float(_list_value(opens, index)),
            high_price=_parse_float(_list_value(highs, index)),
            low_price=_parse_float(_list_value(lows, index)),
            close_price=close_price,
            volume=_parse_float(_list_value(volumes, index)),
            open_interest=None,
            source_url=source_url,
            raw_payload_hash=payload_hash,
            raw_payload=compact_raw_payload,
            fetched_at=fetched_at,
        )

    records = sorted(records_by_time.values(), key=lambda record: record.bar_time)
    return records[-max(limit, 1) :]

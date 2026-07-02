from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.crypto_market.assets import taiwan_spread_assets
from app.crypto_market.contract import (
    BINANCE_PROVIDER,
    BITOPRO_PROVIDER,
    BYBIT_PROVIDER,
    COINGLASS_PROVIDER,
    COINGECKO_COIN_IDS,
    COINGECKO_PROVIDER,
    OKX_PROVIDER,
    OMI_LOCAL_PROVIDER,
    PERPETUAL,
    SPOT,
    get_provider_instrument,
    list_provider_instruments,
    normalize_instrument_type,
    normalize_provider,
    normalize_symbol,
    ohlcv_intervals_for_provider,
    provider_supports_ohlcv_interval,
    provider_contract,
)
from app.crypto_market import sources
from app.crypto_market.sources import (
    CryptoCvdBucketRecord,
    CryptoDerivativesMetricRecord,
    CryptoLiquidationEventRecord,
    CryptoLiquidationHeatmapCellRecord,
    CryptoLongShortRatioRecord,
    CryptoMarketCapRecord,
    CryptoOrderBookRecord,
    CryptoOhlcvBarRecord,
    CryptoTickerRecord,
    raw_payload_json,
)
from app.crypto_market.realtime import (
    LIQUIDATION_RESOURCE,
    OHLCV_RESOURCE,
    ORDER_BOOK_RESOURCE,
    TICKER_RESOURCE,
    CryptoRealtimeUpdate,
)
from app.db.models import (
    CryptoCvdHistory,
    CryptoDerivativesMetric,
    CryptoDerivativesMetricHistory,
    CryptoLiquidationEvent,
    CryptoLiquidationHeatmapCell,
    CryptoLiquidityHistory,
    CryptoLongShortRatioHistory,
    CryptoMarketCapSnapshot,
    CryptoOrderBookSnapshot,
    CryptoOhlcvBar,
    CryptoSpreadSnapshot,
    CryptoSpreadHistory,
    CryptoTickerHistory,
    CryptoTickerSnapshot,
    utc_now,
)
from app.observability.provider_health import record_provider_event
from app.settings.market_data_subscription import (
    MANUAL_REFRESH_SUBSCRIPTION_MODES,
    market_data_subscription_skip_reason,
)


def _unique_instrument_symbols(
    *,
    instrument_type: str,
    resource: str,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            instrument.symbol
            for instrument in list_provider_instruments(
                instrument_type=instrument_type,
                resource=resource,
            )
        )
    )


CRYPTO_DEFAULT_TICKER_PROVIDERS = (BITOPRO_PROVIDER, BINANCE_PROVIDER, OKX_PROVIDER)
CRYPTO_DEFAULT_OHLCV_PROVIDERS = (BITOPRO_PROVIDER, BINANCE_PROVIDER, OKX_PROVIDER)
CRYPTO_DEFAULT_DERIVATIVES_PROVIDERS = (BINANCE_PROVIDER, OKX_PROVIDER)
CRYPTO_DEFAULT_SYMBOLS = _unique_instrument_symbols(instrument_type=SPOT, resource="ticker")
CRYPTO_DEFAULT_DERIVATIVES_SYMBOLS = _unique_instrument_symbols(
    instrument_type=PERPETUAL,
    resource="derivatives",
)
CRYPTO_DEFAULT_SPREAD_BASES = taiwan_spread_assets()
CRYPTO_ADVANCED_METRIC_PROVIDERS = (
    BINANCE_PROVIDER,
    OKX_PROVIDER,
    BYBIT_PROVIDER,
    COINGLASS_PROVIDER,
    OMI_LOCAL_PROVIDER,
)
CRYPTO_DEFAULT_OHLCV_LOOKBACK_HOURS = 6
CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS: dict[str, int] = {
    "1m": 720,
    "5m": 720,
    "15m": 720,
    "30m": 720,
    "1h": 720,
    "4h": 720,
    "1d": 730,
    "1w": 520,
    "1M": 240,
}


class CryptoMarketError(Exception):
    pass


class CryptoMarketUnsupportedError(CryptoMarketError):
    pass


def get_crypto_provider_contract() -> dict[str, Any]:
    return provider_contract()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _split_csv(value: str | list[str] | tuple[str, ...] | None, *, default: tuple[str, ...]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        raw_values = value.split(",")
    else:
        raw_values = list(value)
    cleaned: list[str] = []
    for item in raw_values:
        normalized = str(item or "").strip()
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned or list(default)


def normalize_providers(
    providers: str | list[str] | tuple[str, ...] | None,
    *,
    default: tuple[str, ...],
) -> list[str]:
    normalized: list[str] = []
    for provider in _split_csv(providers, default=default):
        item = normalize_provider(provider)
        if item not in {BITOPRO_PROVIDER, BINANCE_PROVIDER, OKX_PROVIDER, COINGECKO_PROVIDER}:
            raise CryptoMarketUnsupportedError(f"Unsupported crypto provider: {provider}")
        if item not in normalized:
            normalized.append(item)
    return normalized


def normalize_advanced_metric_providers(
    providers: str | list[str] | tuple[str, ...] | None,
    *,
    default: tuple[str, ...] = CRYPTO_ADVANCED_METRIC_PROVIDERS,
) -> list[str]:
    supported = set(CRYPTO_ADVANCED_METRIC_PROVIDERS)
    normalized: list[str] = []
    for provider in _split_csv(providers, default=default):
        item = normalize_provider(provider)
        if item not in supported:
            raise CryptoMarketUnsupportedError(f"Unsupported crypto advanced-metric provider: {provider}")
        if item not in normalized:
            normalized.append(item)
    return normalized


def normalize_symbols(
    symbols: str | list[str] | tuple[str, ...] | None,
    *,
    default: tuple[str, ...] = CRYPTO_DEFAULT_SYMBOLS,
) -> list[str]:
    normalized: list[str] = []
    for symbol in _split_csv(symbols, default=default):
        item = normalize_symbol(symbol)
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _crypto_subscription_key_for_asset(asset: str) -> str:
    return f"crypto:{asset.strip().upper()}"


def _crypto_subscription_key_for_symbol(symbol: str) -> str:
    return _crypto_subscription_key_for_asset(normalize_symbol(symbol).split("-")[0])


def _subscription_skip_for_crypto_symbol(
    db: Session,
    *,
    symbol: str,
    resource: str,
    allowed_modes: frozenset[str] = MANUAL_REFRESH_SUBSCRIPTION_MODES,
) -> str | None:
    return market_data_subscription_skip_reason(
        db,
        key=_crypto_subscription_key_for_symbol(symbol),
        resource=resource,
        allowed_modes=allowed_modes,
    )


def _subscription_skip_for_crypto_asset(
    db: Session,
    *,
    asset: str,
    resource: str,
    allowed_modes: frozenset[str] = MANUAL_REFRESH_SUBSCRIPTION_MODES,
) -> str | None:
    return market_data_subscription_skip_reason(
        db,
        key=_crypto_subscription_key_for_asset(asset),
        resource=resource,
        allowed_modes=allowed_modes,
    )


def _record_event(
    db: Session,
    *,
    provider: str,
    resource: str,
    target: str,
    status: str,
    message: str | None = None,
    error_message: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    try:
        record_provider_event(
            db,
            market="crypto",
            provider=provider,
            resource=resource,
            target=target,
            status=status,
            event_type="refresh",
            message=message,
            error_message=error_message,
            detail=detail,
        )
    except Exception:
        db.rollback()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _sampled_at(value: datetime, sample_seconds: int) -> datetime:
    seconds = max(int(sample_seconds), 1)
    observed = _as_utc(value)
    timestamp = int(observed.timestamp())
    return datetime.fromtimestamp(timestamp - (timestamp % seconds), tz=timezone.utc)


def _history_enabled() -> bool:
    return bool(settings.enable_crypto_market_history)


def _upsert_ticker_history(db: Session, record: CryptoTickerRecord) -> CryptoTickerHistory | None:
    if not _history_enabled():
        return None
    sampled_at = _sampled_at(record.fetched_at, settings.crypto_market_history_sample_seconds)
    row = (
        db.query(CryptoTickerHistory)
        .filter(CryptoTickerHistory.provider == record.provider)
        .filter(CryptoTickerHistory.symbol == record.symbol)
        .filter(CryptoTickerHistory.instrument_type == record.instrument_type)
        .filter(CryptoTickerHistory.sampled_at == sampled_at)
        .first()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "last_price": record.last_price,
        "bid_price": record.bid_price,
        "bid_size": record.bid_size,
        "ask_price": record.ask_price,
        "ask_size": record.ask_size,
        "high_24h": record.high_24h,
        "low_24h": record.low_24h,
        "price_change_24h": record.price_change_24h,
        "price_change_pct_24h": record.price_change_pct_24h,
        "base_volume_24h": record.base_volume_24h,
        "quote_volume_24h": record.quote_volume_24h,
        "event_time": record.event_time,
        "source_url": record.source_url,
        "raw_payload_json": raw_payload_json(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoTickerHistory(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            sampled_at=sampled_at,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _upsert_liquidity_history(db: Session, record: CryptoOrderBookRecord) -> CryptoLiquidityHistory | None:
    if not _history_enabled():
        return None
    sampled_at = _sampled_at(record.fetched_at, settings.crypto_market_history_sample_seconds)
    row = (
        db.query(CryptoLiquidityHistory)
        .filter(CryptoLiquidityHistory.provider == record.provider)
        .filter(CryptoLiquidityHistory.symbol == record.symbol)
        .filter(CryptoLiquidityHistory.instrument_type == record.instrument_type)
        .filter(CryptoLiquidityHistory.depth_limit == record.depth_limit)
        .filter(CryptoLiquidityHistory.sampled_at == sampled_at)
        .first()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "best_bid_price": record.best_bid_price,
        "best_bid_size": record.best_bid_size,
        "best_ask_price": record.best_ask_price,
        "best_ask_size": record.best_ask_size,
        "spread": record.spread,
        "spread_pct": record.spread_pct,
        "bids_json": _json_dumps(record.bids),
        "asks_json": _json_dumps(record.asks),
        "event_time": record.event_time,
        "source_url": record.source_url,
        "raw_payload_json": raw_payload_json(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoLiquidityHistory(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            depth_limit=record.depth_limit,
            sampled_at=sampled_at,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _upsert_derivatives_history(
    db: Session,
    record: CryptoDerivativesMetricRecord,
) -> CryptoDerivativesMetricHistory | None:
    if not _history_enabled():
        return None
    sampled_at = _sampled_at(
        record.fetched_at,
        settings.crypto_market_derivatives_history_sample_seconds,
    )
    row = (
        db.query(CryptoDerivativesMetricHistory)
        .filter(CryptoDerivativesMetricHistory.provider == record.provider)
        .filter(CryptoDerivativesMetricHistory.symbol == record.symbol)
        .filter(CryptoDerivativesMetricHistory.instrument_type == record.instrument_type)
        .filter(CryptoDerivativesMetricHistory.sampled_at == sampled_at)
        .first()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "mark_price": record.mark_price,
        "index_price": record.index_price,
        "funding_rate": record.funding_rate,
        "next_funding_time": record.next_funding_time,
        "open_interest": record.open_interest,
        "open_interest_value": record.open_interest_value,
        "event_time": record.event_time,
        "source_url": record.source_url,
        "raw_payload_json": raw_payload_json(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoDerivativesMetricHistory(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            sampled_at=sampled_at,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _upsert_spread_history(db: Session, snapshot: CryptoSpreadSnapshot) -> CryptoSpreadHistory | None:
    if not _history_enabled():
        return None
    sampled_at = _sampled_at(
        snapshot.observed_at,
        settings.crypto_market_spread_history_sample_seconds,
    )
    row = (
        db.query(CryptoSpreadHistory)
        .filter(CryptoSpreadHistory.base_asset == snapshot.base_asset)
        .filter(CryptoSpreadHistory.local_provider == snapshot.local_provider)
        .filter(CryptoSpreadHistory.global_provider == snapshot.global_provider)
        .filter(CryptoSpreadHistory.local_symbol == snapshot.local_symbol)
        .filter(CryptoSpreadHistory.global_symbol == snapshot.global_symbol)
        .filter(CryptoSpreadHistory.fx_symbol == snapshot.fx_symbol)
        .filter(CryptoSpreadHistory.sampled_at == sampled_at)
        .first()
    )
    values = {
        "quote_asset": snapshot.quote_asset,
        "fx_provider": snapshot.fx_provider,
        "local_price": snapshot.local_price,
        "global_price": snapshot.global_price,
        "fx_rate": snapshot.fx_rate,
        "implied_twd_price": snapshot.implied_twd_price,
        "spread": snapshot.spread,
        "spread_pct": snapshot.spread_pct,
        "observed_at": snapshot.observed_at,
        "source_state_json": snapshot.source_state_json,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoSpreadHistory(
            base_asset=snapshot.base_asset,
            local_provider=snapshot.local_provider,
            global_provider=snapshot.global_provider,
            local_symbol=snapshot.local_symbol,
            global_symbol=snapshot.global_symbol,
            fx_symbol=snapshot.fx_symbol,
            sampled_at=sampled_at,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def upsert_crypto_liquidation_event(
    db: Session,
    record: CryptoLiquidationEventRecord,
) -> CryptoLiquidationEvent:
    provider = normalize_provider(record.provider)
    symbol = normalize_symbol(record.symbol)
    instrument_type = normalize_instrument_type(record.instrument_type)
    liquidation_side = record.liquidation_side.strip().lower()
    notional = record.notional
    if notional is None and record.price is not None and record.quantity is not None:
        notional = record.price * record.quantity

    row = (
        db.query(CryptoLiquidationEvent)
        .filter(CryptoLiquidationEvent.provider == provider)
        .filter(CryptoLiquidationEvent.symbol == symbol)
        .filter(CryptoLiquidationEvent.instrument_type == instrument_type)
        .filter(CryptoLiquidationEvent.event_time == record.event_time)
        .filter(CryptoLiquidationEvent.liquidation_side == liquidation_side)
        .filter(CryptoLiquidationEvent.price == record.price)
        .filter(CryptoLiquidationEvent.quantity == record.quantity)
        .one_or_none()
    )
    if row is None:
        row = CryptoLiquidationEvent(
            provider=provider,
            exchange=record.exchange,
            symbol=symbol,
            provider_symbol=record.provider_symbol,
            base_asset=record.base_asset.upper(),
            quote_asset=record.quote_asset.upper(),
            instrument_type=instrument_type,
            liquidation_side=liquidation_side,
            order_side=(record.order_side.strip().lower() if record.order_side else None),
            price=record.price,
            average_price=record.average_price,
            quantity=record.quantity,
            notional=notional,
            event_time=record.event_time,
            source_url=record.source_url,
            raw_payload_json=raw_payload_json(record.raw_payload) if record.raw_payload is not None else None,
            fetched_at=record.fetched_at,
        )
        db.add(row)
    else:
        row.exchange = record.exchange
        row.provider_symbol = record.provider_symbol
        row.base_asset = record.base_asset.upper()
        row.quote_asset = record.quote_asset.upper()
        row.order_side = record.order_side.strip().lower() if record.order_side else None
        row.average_price = record.average_price
        row.notional = notional
        row.source_url = record.source_url
        row.raw_payload_json = raw_payload_json(record.raw_payload) if record.raw_payload is not None else None
        row.fetched_at = record.fetched_at
    return row


def upsert_crypto_liquidation_heatmap_cell(
    db: Session,
    record: CryptoLiquidationHeatmapCellRecord,
) -> CryptoLiquidationHeatmapCell:
    provider = normalize_provider(record.provider)
    symbol = normalize_symbol(record.symbol)
    instrument_type = normalize_instrument_type(record.instrument_type)
    source_kind = record.source_kind.strip().lower()
    method = record.method.strip().lower()
    liquidation_side = record.liquidation_side.strip().lower()
    bucket_seconds = max(int(record.bucket_seconds), 1)

    row = (
        db.query(CryptoLiquidationHeatmapCell)
        .filter(CryptoLiquidationHeatmapCell.provider == provider)
        .filter(CryptoLiquidationHeatmapCell.source_kind == source_kind)
        .filter(CryptoLiquidationHeatmapCell.method == method)
        .filter(CryptoLiquidationHeatmapCell.symbol == symbol)
        .filter(CryptoLiquidationHeatmapCell.instrument_type == instrument_type)
        .filter(CryptoLiquidationHeatmapCell.time_bucket == record.time_bucket)
        .filter(CryptoLiquidationHeatmapCell.bucket_seconds == bucket_seconds)
        .filter(CryptoLiquidationHeatmapCell.price_bucket == record.price_bucket)
        .filter(CryptoLiquidationHeatmapCell.liquidation_side == liquidation_side)
        .one_or_none()
    )
    if row is None:
        row = CryptoLiquidationHeatmapCell(
            provider=provider,
            source_kind=source_kind,
            method=method,
            exchange=record.exchange,
            symbol=symbol,
            provider_symbol=record.provider_symbol,
            base_asset=record.base_asset.upper(),
            quote_asset=record.quote_asset.upper(),
            instrument_type=instrument_type,
            time_bucket=record.time_bucket,
            bucket_seconds=bucket_seconds,
            price_bucket=record.price_bucket,
            price_bucket_size=record.price_bucket_size,
            liquidation_side=liquidation_side,
            liquidation_notional=record.liquidation_notional,
            liquidation_quantity=record.liquidation_quantity,
            event_count=max(int(record.event_count), 0),
            intensity=record.intensity,
            generated_at=record.generated_at,
            source_url=record.source_url,
            raw_payload_json=raw_payload_json(record.raw_payload) if record.raw_payload is not None else None,
            fetched_at=record.fetched_at,
        )
        db.add(row)
    else:
        row.exchange = record.exchange
        row.provider_symbol = record.provider_symbol
        row.base_asset = record.base_asset.upper()
        row.quote_asset = record.quote_asset.upper()
        row.price_bucket_size = record.price_bucket_size
        row.liquidation_notional = record.liquidation_notional
        row.liquidation_quantity = record.liquidation_quantity
        row.event_count = max(int(record.event_count), 0)
        row.intensity = record.intensity
        row.generated_at = record.generated_at
        row.source_url = record.source_url
        row.raw_payload_json = raw_payload_json(record.raw_payload) if record.raw_payload is not None else None
        row.fetched_at = record.fetched_at
    return row


def upsert_crypto_cvd_history(
    db: Session,
    record: CryptoCvdBucketRecord,
) -> CryptoCvdHistory:
    provider = normalize_provider(record.provider)
    symbol = normalize_symbol(record.symbol)
    instrument_type = normalize_instrument_type(record.instrument_type)
    bucket_seconds = max(int(record.bucket_seconds), 1)
    row = (
        db.query(CryptoCvdHistory)
        .filter(CryptoCvdHistory.provider == provider)
        .filter(CryptoCvdHistory.symbol == symbol)
        .filter(CryptoCvdHistory.instrument_type == instrument_type)
        .filter(CryptoCvdHistory.bucket_seconds == bucket_seconds)
        .filter(CryptoCvdHistory.sampled_at == record.sampled_at)
        .one_or_none()
    )
    if row is None:
        row = CryptoCvdHistory(
            provider=provider,
            exchange=record.exchange,
            symbol=symbol,
            provider_symbol=record.provider_symbol,
            base_asset=record.base_asset.upper(),
            quote_asset=record.quote_asset.upper(),
            instrument_type=instrument_type,
            bucket_seconds=bucket_seconds,
            sampled_at=record.sampled_at,
            buy_base_volume=record.buy_base_volume,
            sell_base_volume=record.sell_base_volume,
            buy_quote_volume=record.buy_quote_volume,
            sell_quote_volume=record.sell_quote_volume,
            net_base_volume=record.net_base_volume,
            net_quote_volume=record.net_quote_volume,
            cumulative_base_delta=record.cumulative_base_delta,
            cumulative_quote_delta=record.cumulative_quote_delta,
            trade_count=max(int(record.trade_count), 0),
            event_time=record.event_time,
            source_url=record.source_url,
            raw_payload_json=raw_payload_json(record.raw_payload) if record.raw_payload is not None else None,
            fetched_at=record.fetched_at,
        )
        db.add(row)
    else:
        row.exchange = record.exchange
        row.provider_symbol = record.provider_symbol
        row.base_asset = record.base_asset.upper()
        row.quote_asset = record.quote_asset.upper()
        row.buy_base_volume = record.buy_base_volume
        row.sell_base_volume = record.sell_base_volume
        row.buy_quote_volume = record.buy_quote_volume
        row.sell_quote_volume = record.sell_quote_volume
        row.net_base_volume = record.net_base_volume
        row.net_quote_volume = record.net_quote_volume
        row.cumulative_base_delta = record.cumulative_base_delta
        row.cumulative_quote_delta = record.cumulative_quote_delta
        row.trade_count = max(int(record.trade_count), 0)
        row.event_time = record.event_time
        row.source_url = record.source_url
        row.raw_payload_json = raw_payload_json(record.raw_payload) if record.raw_payload is not None else None
        row.fetched_at = record.fetched_at
    return row


def upsert_crypto_long_short_ratio_history(
    db: Session,
    record: CryptoLongShortRatioRecord,
) -> CryptoLongShortRatioHistory:
    provider = normalize_provider(record.provider)
    symbol = normalize_symbol(record.symbol)
    instrument_type = normalize_instrument_type(record.instrument_type)
    ratio_scope = record.ratio_scope.strip().lower()
    row = (
        db.query(CryptoLongShortRatioHistory)
        .filter(CryptoLongShortRatioHistory.provider == provider)
        .filter(CryptoLongShortRatioHistory.symbol == symbol)
        .filter(CryptoLongShortRatioHistory.instrument_type == instrument_type)
        .filter(CryptoLongShortRatioHistory.ratio_scope == ratio_scope)
        .filter(CryptoLongShortRatioHistory.sampled_at == record.sampled_at)
        .one_or_none()
    )
    if row is None:
        row = CryptoLongShortRatioHistory(
            provider=provider,
            exchange=record.exchange,
            symbol=symbol,
            provider_symbol=record.provider_symbol,
            base_asset=record.base_asset.upper(),
            quote_asset=record.quote_asset.upper(),
            instrument_type=instrument_type,
            ratio_scope=ratio_scope,
            long_ratio=record.long_ratio,
            short_ratio=record.short_ratio,
            long_short_ratio=record.long_short_ratio,
            event_time=record.event_time,
            sampled_at=record.sampled_at,
            source_url=record.source_url,
            raw_payload_json=raw_payload_json(record.raw_payload) if record.raw_payload is not None else None,
            fetched_at=record.fetched_at,
        )
        db.add(row)
    else:
        row.exchange = record.exchange
        row.provider_symbol = record.provider_symbol
        row.base_asset = record.base_asset.upper()
        row.quote_asset = record.quote_asset.upper()
        row.long_ratio = record.long_ratio
        row.short_ratio = record.short_ratio
        row.long_short_ratio = record.long_short_ratio
        row.event_time = record.event_time
        row.source_url = record.source_url
        row.raw_payload_json = raw_payload_json(record.raw_payload) if record.raw_payload is not None else None
        row.fetched_at = record.fetched_at
    return row


def _upsert_ticker(db: Session, record: CryptoTickerRecord) -> CryptoTickerSnapshot:
    row = (
        db.query(CryptoTickerSnapshot)
        .filter(CryptoTickerSnapshot.provider == record.provider)
        .filter(CryptoTickerSnapshot.symbol == record.symbol)
        .filter(CryptoTickerSnapshot.instrument_type == record.instrument_type)
        .first()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "last_price": record.last_price,
        "bid_price": record.bid_price,
        "bid_size": record.bid_size,
        "ask_price": record.ask_price,
        "ask_size": record.ask_size,
        "high_24h": record.high_24h,
        "low_24h": record.low_24h,
        "price_change_24h": record.price_change_24h,
        "price_change_pct_24h": record.price_change_pct_24h,
        "base_volume_24h": record.base_volume_24h,
        "quote_volume_24h": record.quote_volume_24h,
        "event_time": record.event_time,
        "source_url": record.source_url,
        "raw_payload_json": raw_payload_json(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoTickerSnapshot(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    _upsert_ticker_history(db, record)
    return row


def _upsert_order_book(db: Session, record: CryptoOrderBookRecord) -> CryptoOrderBookSnapshot:
    row = (
        db.query(CryptoOrderBookSnapshot)
        .filter(CryptoOrderBookSnapshot.provider == record.provider)
        .filter(CryptoOrderBookSnapshot.symbol == record.symbol)
        .filter(CryptoOrderBookSnapshot.instrument_type == record.instrument_type)
        .filter(CryptoOrderBookSnapshot.depth_limit == record.depth_limit)
        .first()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "best_bid_price": record.best_bid_price,
        "best_bid_size": record.best_bid_size,
        "best_ask_price": record.best_ask_price,
        "best_ask_size": record.best_ask_size,
        "spread": record.spread,
        "spread_pct": record.spread_pct,
        "bids_json": _json_dumps(record.bids),
        "asks_json": _json_dumps(record.asks),
        "event_time": record.event_time,
        "source_url": record.source_url,
        "raw_payload_json": raw_payload_json(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoOrderBookSnapshot(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            depth_limit=record.depth_limit,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    _upsert_liquidity_history(db, record)
    return row


def _upsert_ohlcv_bar(db: Session, record: CryptoOhlcvBarRecord) -> CryptoOhlcvBar:
    row = (
        db.query(CryptoOhlcvBar)
        .filter(CryptoOhlcvBar.provider == record.provider)
        .filter(CryptoOhlcvBar.symbol == record.symbol)
        .filter(CryptoOhlcvBar.instrument_type == record.instrument_type)
        .filter(CryptoOhlcvBar.interval == record.interval)
        .filter(CryptoOhlcvBar.bar_time == record.bar_time)
        .first()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "open_price": record.open_price,
        "high_price": record.high_price,
        "low_price": record.low_price,
        "close_price": record.close_price,
        "base_volume": record.base_volume,
        "quote_volume": record.quote_volume,
        "source_url": record.source_url,
        "raw_payload_json": raw_payload_json(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoOhlcvBar(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            interval=record.interval,
            bar_time=record.bar_time,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _upsert_derivatives_metric(
    db: Session,
    record: CryptoDerivativesMetricRecord,
) -> CryptoDerivativesMetric:
    row = (
        db.query(CryptoDerivativesMetric)
        .filter(CryptoDerivativesMetric.provider == record.provider)
        .filter(CryptoDerivativesMetric.symbol == record.symbol)
        .filter(CryptoDerivativesMetric.instrument_type == record.instrument_type)
        .first()
    )
    values = {
        "exchange": record.exchange,
        "provider_symbol": record.provider_symbol,
        "base_asset": record.base_asset,
        "quote_asset": record.quote_asset,
        "mark_price": record.mark_price,
        "index_price": record.index_price,
        "funding_rate": record.funding_rate,
        "next_funding_time": record.next_funding_time,
        "open_interest": record.open_interest,
        "open_interest_value": record.open_interest_value,
        "event_time": record.event_time,
        "source_url": record.source_url,
        "raw_payload_json": raw_payload_json(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoDerivativesMetric(
            provider=record.provider,
            symbol=record.symbol,
            instrument_type=record.instrument_type,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    _upsert_derivatives_history(db, record)
    return row


def _upsert_market_cap(db: Session, record: CryptoMarketCapRecord) -> CryptoMarketCapSnapshot:
    row = (
        db.query(CryptoMarketCapSnapshot)
        .filter(CryptoMarketCapSnapshot.provider == record.provider)
        .filter(CryptoMarketCapSnapshot.coin_id == record.coin_id)
        .filter(CryptoMarketCapSnapshot.vs_currency == record.vs_currency)
        .first()
    )
    values = {
        "symbol": record.symbol,
        "name": record.name,
        "current_price": record.current_price,
        "market_cap": record.market_cap,
        "market_cap_rank": record.market_cap_rank,
        "total_volume": record.total_volume,
        "high_24h": record.high_24h,
        "low_24h": record.low_24h,
        "price_change_pct_24h": record.price_change_pct_24h,
        "circulating_supply": record.circulating_supply,
        "total_supply": record.total_supply,
        "max_supply": record.max_supply,
        "last_updated": record.last_updated,
        "source_url": record.source_url,
        "raw_payload_json": raw_payload_json(record.raw_payload),
        "fetched_at": record.fetched_at,
        "updated_at": utc_now(),
    }
    if row is None:
        row = CryptoMarketCapSnapshot(
            provider=record.provider,
            coin_id=record.coin_id,
            vs_currency=record.vs_currency,
            **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _run_refresh_items(
    db: Session,
    *,
    providers: list[str],
    symbols: list[str],
    resource: str,
    fetcher_factory: Callable[[str], Callable[..., Any]],
    upsert: Callable[[Session, Any], Any],
    instrument_type: str = SPOT,
    fetch_kwargs: dict[str, Any] | None = None,
    subscription_resource: str | None = None,
) -> dict[str, Any]:
    rows = []
    errors = []
    skipped = []
    fetch_kwargs = fetch_kwargs or {}
    for provider in providers:
        if provider == COINGECKO_PROVIDER:
            skipped.append({"provider": provider, "reason": f"provider does not support {resource}"})
            continue
        try:
            fetcher = fetcher_factory(provider)
        except KeyError:
            skipped.append({"provider": provider, "reason": f"provider does not support {resource}"})
            continue
        for symbol in symbols:
            normalized_symbol = normalize_symbol(symbol)
            try:
                list_provider_instruments(
                    provider=provider,
                    symbol=normalized_symbol,
                    instrument_type=instrument_type,
                    resource=resource,
                )[0]
            except IndexError:
                skipped.append(
                    {
                        "provider": provider,
                        "symbol": normalized_symbol,
                        "instrument_type": instrument_type,
                        "reason": "unsupported provider/symbol/resource combination",
                    }
                )
                continue

            subscription_reason = _subscription_skip_for_crypto_symbol(
                db,
                symbol=normalized_symbol,
                resource=subscription_resource or resource,
            )
            if subscription_reason:
                skipped.append(
                    {
                        "provider": provider,
                        "symbol": normalized_symbol,
                        "instrument_type": instrument_type,
                        "reason": subscription_reason,
                    }
                )
                continue

            try:
                record = fetcher(normalized_symbol, **fetch_kwargs)
                row = upsert(db, record)
                rows.append(row)
                _record_event(
                    db,
                    provider=provider,
                    resource=f"crypto_{resource}",
                    target=normalized_symbol,
                    status="success",
                    message=f"Refreshed crypto {resource} for {normalized_symbol}.",
                )
            except Exception as exc:
                db.rollback()
                errors.append({"provider": provider, "symbol": normalized_symbol, "error": str(exc)})
                _record_event(
                    db,
                    provider=provider,
                    resource=f"crypto_{resource}",
                    target=normalized_symbol,
                    status="error",
                    error_message=str(exc),
                )

    db.commit()
    for row in rows:
        db.refresh(row)
    return {
        "status": _status_for_counts(len(rows), len(errors)),
        "resource": resource,
        "requested_count": len(providers) * len(symbols),
        "refreshed_count": len(rows),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "errors": errors,
        "skipped": skipped,
        "rows": rows,
    }


def _status_for_counts(success_count: int, error_count: int) -> str:
    if success_count > 0 and error_count == 0:
        return "success"
    if success_count > 0 and error_count > 0:
        return "partial_success"
    if error_count > 0:
        return "error"
    return "empty"


def _raw_payload_hash(value: Any) -> str:
    return hashlib.sha256(raw_payload_json(value).encode("utf-8")).hexdigest()


def _datetime_from_realtime_value(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _realtime_source_url(update: CryptoRealtimeUpdate) -> str:
    return f"websocket:{update.provider}:{update.resource}:{update.provider_symbol}"


def _realtime_instrument(update: CryptoRealtimeUpdate, *, resource: str):
    try:
        return get_provider_instrument(
            provider=update.provider,
            symbol=update.symbol,
            instrument_type=update.instrument_type,
            resource=resource,
        )
    except ValueError:
        return None


def _ticker_record_from_realtime(update: CryptoRealtimeUpdate) -> CryptoTickerRecord | None:
    instrument = _realtime_instrument(update, resource=TICKER_RESOURCE)
    if instrument is None:
        return None
    data = update.data
    return CryptoTickerRecord(
        provider=instrument.provider,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        last_price=data.get("last_price"),
        bid_price=data.get("bid_price"),
        bid_size=data.get("bid_size"),
        ask_price=data.get("ask_price"),
        ask_size=data.get("ask_size"),
        high_24h=data.get("high_24h"),
        low_24h=data.get("low_24h"),
        price_change_24h=data.get("price_change_24h"),
        price_change_pct_24h=data.get("price_change_pct_24h"),
        base_volume_24h=data.get("base_volume_24h"),
        quote_volume_24h=data.get("quote_volume_24h"),
        event_time=update.event_time,
        source_url=_realtime_source_url(update),
        raw_payload_hash=_raw_payload_hash(update.raw_payload),
        raw_payload=update.raw_payload if isinstance(update.raw_payload, dict) else {"payload": update.raw_payload},
        fetched_at=update.received_at,
    )


def _order_book_record_from_realtime(update: CryptoRealtimeUpdate) -> CryptoOrderBookRecord | None:
    instrument = _realtime_instrument(update, resource=ORDER_BOOK_RESOURCE)
    if instrument is None:
        return None
    data = update.data
    return CryptoOrderBookRecord(
        provider=instrument.provider,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        depth_limit=max(int(settings.crypto_market_ws_order_book_depth), 1),
        bids=list(data.get("bids") or []),
        asks=list(data.get("asks") or []),
        best_bid_price=data.get("best_bid_price"),
        best_bid_size=data.get("best_bid_size"),
        best_ask_price=data.get("best_ask_price"),
        best_ask_size=data.get("best_ask_size"),
        spread=data.get("spread"),
        spread_pct=data.get("spread_pct"),
        event_time=update.event_time,
        source_url=_realtime_source_url(update),
        raw_payload_hash=_raw_payload_hash(update.raw_payload),
        raw_payload=update.raw_payload if isinstance(update.raw_payload, dict) else {"payload": update.raw_payload},
        fetched_at=update.received_at,
    )


def _ohlcv_record_from_realtime(update: CryptoRealtimeUpdate) -> CryptoOhlcvBarRecord | None:
    instrument = _realtime_instrument(update, resource=OHLCV_RESOURCE)
    if instrument is None:
        return None
    data = update.data
    bar_time = _datetime_from_realtime_value(data.get("bar_time"))
    if bar_time is None:
        return None
    interval = str(data.get("interval") or "1m").strip() or "1m"
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
        open_price=data.get("open_price"),
        high_price=data.get("high_price"),
        low_price=data.get("low_price"),
        close_price=data.get("close_price"),
        base_volume=data.get("base_volume"),
        quote_volume=data.get("quote_volume"),
        source_url=_realtime_source_url(update),
        raw_payload_hash=_raw_payload_hash(update.raw_payload),
        raw_payload=update.raw_payload,
        fetched_at=update.received_at,
    )


def _liquidation_event_record_from_realtime(update: CryptoRealtimeUpdate) -> CryptoLiquidationEventRecord | None:
    instrument = _realtime_instrument(update, resource=LIQUIDATION_RESOURCE)
    if instrument is None:
        return None
    data = update.data
    return CryptoLiquidationEventRecord(
        provider=instrument.provider,
        exchange=instrument.exchange,
        symbol=instrument.symbol,
        provider_symbol=instrument.provider_symbol,
        base_asset=instrument.base_asset,
        quote_asset=instrument.quote_asset,
        instrument_type=instrument.instrument_type,
        liquidation_side=str(data.get("liquidation_side") or "unknown"),
        order_side=str(data.get("order_side")) if data.get("order_side") else None,
        price=data.get("price"),
        average_price=data.get("average_price"),
        quantity=data.get("quantity"),
        notional=data.get("notional"),
        event_time=update.event_time or update.received_at,
        source_url=_realtime_source_url(update),
        raw_payload=update.raw_payload if isinstance(update.raw_payload, dict) else {"payload": update.raw_payload},
        fetched_at=update.received_at,
    )


def persist_crypto_realtime_updates(
    db: Session,
    updates: list[CryptoRealtimeUpdate] | tuple[CryptoRealtimeUpdate, ...],
) -> dict[str, Any]:
    persisted_by_resource = {
        TICKER_RESOURCE: 0,
        ORDER_BOOK_RESOURCE: 0,
        OHLCV_RESOURCE: 0,
        LIQUIDATION_RESOURCE: 0,
    }
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for update in updates:
        try:
            if update.resource == TICKER_RESOURCE:
                record = _ticker_record_from_realtime(update)
                if record is None:
                    skipped.append({"resource": update.resource, "provider": update.provider, "symbol": update.symbol})
                    continue
                _upsert_ticker(db, record)
                persisted_by_resource[TICKER_RESOURCE] += 1
            elif update.resource == ORDER_BOOK_RESOURCE:
                record = _order_book_record_from_realtime(update)
                if record is None:
                    skipped.append({"resource": update.resource, "provider": update.provider, "symbol": update.symbol})
                    continue
                _upsert_order_book(db, record)
                persisted_by_resource[ORDER_BOOK_RESOURCE] += 1
            elif update.resource == OHLCV_RESOURCE:
                record = _ohlcv_record_from_realtime(update)
                if record is None:
                    skipped.append({"resource": update.resource, "provider": update.provider, "symbol": update.symbol})
                    continue
                _upsert_ohlcv_bar(db, record)
                persisted_by_resource[OHLCV_RESOURCE] += 1
            elif update.resource == LIQUIDATION_RESOURCE:
                record = _liquidation_event_record_from_realtime(update)
                if record is None:
                    skipped.append({"resource": update.resource, "provider": update.provider, "symbol": update.symbol})
                    continue
                upsert_crypto_liquidation_event(db, record)
                persisted_by_resource[LIQUIDATION_RESOURCE] += 1
            else:
                skipped.append({"resource": update.resource, "provider": update.provider, "symbol": update.symbol})
        except Exception as exc:
            errors.append(
                {
                    "resource": update.resource,
                    "provider": update.provider,
                    "symbol": update.symbol,
                    "error": str(exc),
                }
            )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    persisted_count = sum(persisted_by_resource.values())
    return {
        "status": _status_for_counts(persisted_count, len(errors)),
        "resource": "realtime",
        "requested_count": len(updates),
        "persisted_count": persisted_count,
        "persisted_by_resource": persisted_by_resource,
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "skipped": skipped,
        "errors": errors,
    }


def refresh_crypto_tickers(
    db: Session,
    *,
    providers: str | list[str] | tuple[str, ...] | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    provider_list = normalize_providers(providers, default=CRYPTO_DEFAULT_TICKER_PROVIDERS)
    symbol_list = normalize_symbols(symbols)
    return _run_refresh_items(
        db,
        providers=provider_list,
        symbols=symbol_list,
        resource="ticker",
        subscription_resource="quote",
        fetcher_factory=sources.provider_for_ticker,
        upsert=_upsert_ticker,
    )


def refresh_crypto_order_books(
    db: Session,
    *,
    providers: str | list[str] | tuple[str, ...] | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    depth_limit: int = 5,
) -> dict[str, Any]:
    provider_list = normalize_providers(providers, default=CRYPTO_DEFAULT_TICKER_PROVIDERS)
    symbol_list = normalize_symbols(symbols)
    return _run_refresh_items(
        db,
        providers=provider_list,
        symbols=symbol_list,
        resource="order_book",
        fetcher_factory=sources.provider_for_order_book,
        upsert=_upsert_order_book,
        fetch_kwargs={"limit": depth_limit},
    )


def _ohlcv_default_lookback_hours(interval: str) -> int:
    return {
        "1m": CRYPTO_DEFAULT_OHLCV_LOOKBACK_HOURS,
        "5m": 24,
        "15m": 72,
        "30m": 168,
        "1h": 336,
        "4h": 2016,
        "1d": 8760,
        "1w": 26280,
        "1M": 70080,
    }.get(interval, CRYPTO_DEFAULT_OHLCV_LOOKBACK_HOURS)


def _ohlcv_time_window(
    *,
    interval: str,
    start_time: datetime | None,
    end_time: datetime | None,
) -> tuple[datetime, datetime]:
    normalized_end = end_time or _now()
    if normalized_end.tzinfo is None:
        normalized_end = normalized_end.replace(tzinfo=timezone.utc)
    normalized_start = start_time or (
        normalized_end - timedelta(hours=_ohlcv_default_lookback_hours(interval))
    )
    if normalized_start.tzinfo is None:
        normalized_start = normalized_start.replace(tzinfo=timezone.utc)
    if normalized_start >= normalized_end:
        raise CryptoMarketError("OHLCV start_time must be before end_time.")
    return normalized_start, normalized_end


def refresh_crypto_ohlcv(
    db: Session,
    *,
    providers: str | list[str] | tuple[str, ...] | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    interval: str = "1m",
    limit: int = 100,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    provider_list = normalize_providers(providers, default=CRYPTO_DEFAULT_OHLCV_PROVIDERS)
    symbol_list = normalize_symbols(symbols)
    normalized_interval = (interval or "1m").strip()
    normalized_limit = max(1, min(int(limit), 1000))
    window_start, window_end = _ohlcv_time_window(
        interval=normalized_interval,
        start_time=start_time,
        end_time=end_time,
    )
    rows = []
    errors = []
    skipped = []

    for provider in provider_list:
        if provider == COINGECKO_PROVIDER:
            skipped.append({"provider": provider, "reason": "provider does not support ohlcv"})
            continue
        try:
            fetcher = sources.provider_for_ohlcv(provider)
        except KeyError:
            skipped.append({"provider": provider, "reason": "provider does not support ohlcv"})
            continue
        for symbol in symbol_list:
            normalized_symbol = normalize_symbol(symbol)
            if not provider_supports_ohlcv_interval(provider, normalized_interval):
                skipped.append(
                    {
                        "provider": provider,
                        "symbol": normalized_symbol,
                        "instrument_type": SPOT,
                        "interval": normalized_interval,
                        "reason": "provider does not support ohlcv interval",
                    }
                )
                continue
            if not list_provider_instruments(
                provider=provider,
                symbol=normalized_symbol,
                instrument_type=SPOT,
                resource="ohlcv",
            ):
                skipped.append(
                    {
                        "provider": provider,
                        "symbol": normalized_symbol,
                        "instrument_type": SPOT,
                        "reason": "unsupported provider/symbol/resource combination",
                    }
                )
                continue
            subscription_reason = _subscription_skip_for_crypto_symbol(
                db,
                symbol=normalized_symbol,
                resource="ohlcv",
            )
            if subscription_reason:
                skipped.append(
                    {
                        "provider": provider,
                        "symbol": normalized_symbol,
                        "instrument_type": SPOT,
                        "reason": subscription_reason,
                    }
                )
                continue
            try:
                if provider == BITOPRO_PROVIDER:
                    records = fetcher(
                        normalized_symbol,
                        interval=normalized_interval,
                        start_time=window_start,
                        end_time=window_end,
                    )
                else:
                    records = fetcher(
                        normalized_symbol,
                        interval=normalized_interval,
                        limit=normalized_limit,
                    )
                for record in records:
                    rows.append(_upsert_ohlcv_bar(db, record))
                _record_event(
                    db,
                    provider=provider,
                    resource="crypto_ohlcv",
                    target=normalized_symbol,
                    status="success",
                    message=f"Refreshed {len(records)} crypto OHLCV bar(s) for {normalized_symbol}.",
                    detail={
                        "interval": normalized_interval,
                        "limit": normalized_limit,
                        "start_time": window_start.isoformat(),
                        "end_time": window_end.isoformat(),
                    },
                )
            except Exception as exc:
                db.rollback()
                errors.append({"provider": provider, "symbol": normalized_symbol, "error": str(exc)})
                _record_event(
                    db,
                    provider=provider,
                    resource="crypto_ohlcv",
                    target=normalized_symbol,
                    status="error",
                    error_message=str(exc),
                    detail={"interval": normalized_interval},
                )

    db.commit()
    for row in rows:
        db.refresh(row)
    return {
        "status": _status_for_counts(len(rows), len(errors)),
        "resource": "ohlcv",
        "requested_count": len(provider_list) * len(symbol_list),
        "refreshed_count": len(rows),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "errors": errors,
        "skipped": skipped,
        "rows": rows,
    }


def _normalize_ohlcv_bundle_intervals(
    intervals: str | list[str] | tuple[str, ...] | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    raw_intervals = _split_csv(
        intervals,
        default=tuple(CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS),
    )
    normalized: list[str] = []
    skipped: list[dict[str, Any]] = []
    for raw_interval in raw_intervals:
        interval = str(raw_interval or "").strip()
        if not interval:
            continue
        if interval not in CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS:
            skipped.append(
                {
                    "interval": interval,
                    "reason": "unsupported ohlcv bundle interval",
                    "supported_intervals": list(CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS),
                }
            )
            continue
        if interval not in normalized:
            normalized.append(interval)
    return normalized, skipped


def refresh_crypto_ohlcv_bundle(
    db: Session,
    *,
    providers: str | list[str] | tuple[str, ...] | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    intervals: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    provider_list = normalize_providers(providers, default=CRYPTO_DEFAULT_OHLCV_PROVIDERS)
    interval_list, skipped = _normalize_ohlcv_bundle_intervals(intervals)
    interval_results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    requested_count = 0
    refreshed_count = 0

    for interval in interval_list:
        limit = CRYPTO_OHLCV_BUNDLE_INTERVAL_LIMITS[interval]
        supported_providers = [
            provider
            for provider in provider_list
            if interval in ohlcv_intervals_for_provider(provider)
        ]
        result = refresh_crypto_ohlcv(
            db,
            providers=provider_list,
            symbols=symbols,
            interval=interval,
            limit=limit,
        )
        requested_count += int(result.get("requested_count") or 0)
        refreshed_count += int(result.get("refreshed_count") or 0)
        errors.extend(
            {"interval": interval, **error}
            for error in result.get("errors", [])
            if isinstance(error, dict)
        )
        skipped.extend(
            {"interval": interval, **item}
            for item in result.get("skipped", [])
            if isinstance(item, dict)
        )
        interval_results.append(
            {
                "interval": interval,
                "limit": limit,
                "supported_providers": supported_providers,
                "status": result.get("status", "empty"),
                "resource": "ohlcv",
                "requested_count": int(result.get("requested_count") or 0),
                "refreshed_count": int(result.get("refreshed_count") or 0),
                "error_count": int(result.get("error_count") or 0),
                "skipped_count": int(result.get("skipped_count") or 0),
                "errors": result.get("errors", []),
                "skipped": result.get("skipped", []),
            }
        )

    return {
        "status": _status_for_counts(refreshed_count, len(errors)),
        "resource": "ohlcv_bundle",
        "requested_count": requested_count,
        "refreshed_count": refreshed_count,
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "errors": errors,
        "skipped": skipped,
        "intervals": interval_results,
    }


def refresh_crypto_derivatives(
    db: Session,
    *,
    providers: str | list[str] | tuple[str, ...] | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    provider_list = normalize_providers(providers, default=CRYPTO_DEFAULT_DERIVATIVES_PROVIDERS)
    symbol_list = normalize_symbols(symbols, default=CRYPTO_DEFAULT_DERIVATIVES_SYMBOLS)
    return _run_refresh_items(
        db,
        providers=provider_list,
        symbols=symbol_list,
        resource="derivatives",
        fetcher_factory=sources.provider_for_derivatives,
        upsert=_upsert_derivatives_metric,
        instrument_type=PERPETUAL,
    )


def refresh_crypto_market_caps(
    db: Session,
    *,
    assets: str | list[str] | tuple[str, ...] | None = None,
    ids: str | list[str] | tuple[str, ...] | None = None,
    vs_currency: str = "usd",
) -> dict[str, Any]:
    skipped = []
    coin_id_to_asset = {coin_id: asset for asset, coin_id in COINGECKO_COIN_IDS.items()}
    requested_assets: list[str] = []
    if ids:
        requested_ids_input = [item.strip().lower() for item in _split_csv(ids, default=())]
        for coin_id in requested_ids_input:
            asset = coin_id_to_asset.get(coin_id)
            if asset is None:
                skipped.append({"coin_id": coin_id, "reason": "unknown CoinGecko asset mapping"})
                continue
            requested_assets.append(asset)
    else:
        requested_assets = [
            item.strip().upper()
            for item in _split_csv(assets, default=tuple(COINGECKO_COIN_IDS))
        ]

    enabled_assets = []
    for asset in requested_assets:
        subscription_reason = _subscription_skip_for_crypto_asset(
            db,
            asset=asset,
            resource="market_cap",
        )
        if subscription_reason:
            skipped.append({"asset": asset, "reason": subscription_reason})
            continue
        enabled_assets.append(asset)

    requested_ids = sources.coingecko_ids_for_assets(enabled_assets)
    errors = []
    rows = []
    if requested_ids:
        try:
            records = sources.fetch_coingecko_market_caps(ids=requested_ids, vs_currency=vs_currency)
            for record in records:
                rows.append(_upsert_market_cap(db, record))
            _record_event(
                db,
                provider=COINGECKO_PROVIDER,
                resource="crypto_market_cap",
                target=",".join(requested_ids or []),
                status="success",
                message=f"Refreshed {len(rows)} crypto market-cap row(s).",
            )
        except Exception as exc:
            db.rollback()
            errors.append({"provider": COINGECKO_PROVIDER, "error": str(exc)})
            _record_event(
                db,
                provider=COINGECKO_PROVIDER,
                resource="crypto_market_cap",
                target=",".join(requested_ids or []),
                status="error",
                error_message=str(exc),
            )
    db.commit()
    for row in rows:
        db.refresh(row)
    return {
        "status": _status_for_counts(len(rows), len(errors)),
        "resource": "market_cap",
        "requested_count": len(requested_assets),
        "refreshed_count": len(rows),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "errors": errors,
        "skipped": skipped,
        "rows": rows,
    }


def list_latest_crypto_tickers(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    limit: int = 100,
) -> list[CryptoTickerSnapshot]:
    query = db.query(CryptoTickerSnapshot)
    if provider:
        query = query.filter(CryptoTickerSnapshot.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoTickerSnapshot.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoTickerSnapshot.instrument_type == normalize_instrument_type(instrument_type))
    return (
        query.order_by(CryptoTickerSnapshot.fetched_at.desc(), CryptoTickerSnapshot.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def list_latest_crypto_order_books(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    limit: int = 100,
) -> list[CryptoOrderBookSnapshot]:
    query = db.query(CryptoOrderBookSnapshot)
    if provider:
        query = query.filter(CryptoOrderBookSnapshot.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoOrderBookSnapshot.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoOrderBookSnapshot.instrument_type == normalize_instrument_type(instrument_type))
    return (
        query.order_by(CryptoOrderBookSnapshot.fetched_at.desc(), CryptoOrderBookSnapshot.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def list_latest_crypto_ohlcv_bars(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    interval: str | None = None,
    limit: int = 500,
) -> list[CryptoOhlcvBar]:
    query = db.query(CryptoOhlcvBar)
    if provider:
        query = query.filter(CryptoOhlcvBar.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoOhlcvBar.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoOhlcvBar.instrument_type == normalize_instrument_type(instrument_type))
    if interval:
        query = query.filter(CryptoOhlcvBar.interval == interval.strip())
    return (
        query.order_by(CryptoOhlcvBar.bar_time.desc(), CryptoOhlcvBar.fetched_at.desc(), CryptoOhlcvBar.id.desc())
        .limit(max(1, min(limit, 5000)))
        .all()
    )


def list_crypto_ohlcv_coverage(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    interval: str | None = None,
) -> list[dict[str, Any]]:
    query = db.query(
        CryptoOhlcvBar.provider.label("provider"),
        func.max(CryptoOhlcvBar.exchange).label("exchange"),
        CryptoOhlcvBar.symbol.label("symbol"),
        CryptoOhlcvBar.instrument_type.label("instrument_type"),
        CryptoOhlcvBar.interval.label("interval"),
        func.count(CryptoOhlcvBar.id).label("row_count"),
        func.min(CryptoOhlcvBar.bar_time).label("first_bar_time"),
        func.max(CryptoOhlcvBar.bar_time).label("last_bar_time"),
        func.max(CryptoOhlcvBar.fetched_at).label("latest_fetched_at"),
    )
    if provider:
        query = query.filter(CryptoOhlcvBar.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoOhlcvBar.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoOhlcvBar.instrument_type == normalize_instrument_type(instrument_type))
    if interval:
        query = query.filter(CryptoOhlcvBar.interval == interval.strip())

    rows = (
        query.group_by(
            CryptoOhlcvBar.provider,
            CryptoOhlcvBar.symbol,
            CryptoOhlcvBar.instrument_type,
            CryptoOhlcvBar.interval,
        )
        .order_by(
            CryptoOhlcvBar.provider.asc(),
            CryptoOhlcvBar.symbol.asc(),
            CryptoOhlcvBar.instrument_type.asc(),
            CryptoOhlcvBar.interval.asc(),
        )
        .all()
    )
    return [dict(row._mapping) for row in rows]


def list_latest_crypto_derivatives(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    limit: int = 100,
) -> list[CryptoDerivativesMetric]:
    query = db.query(CryptoDerivativesMetric)
    if provider:
        query = query.filter(CryptoDerivativesMetric.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoDerivativesMetric.symbol.in_(normalize_symbols(symbols)))
    return (
        query.order_by(CryptoDerivativesMetric.fetched_at.desc(), CryptoDerivativesMetric.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def _bounded_history_limit(limit: int) -> int:
    return max(1, min(int(limit), 5000))


def _apply_time_range(query, model, *, start_time: datetime | None, end_time: datetime | None):
    if start_time is not None:
        query = query.filter(model.sampled_at >= start_time)
    if end_time is not None:
        query = query.filter(model.sampled_at <= end_time)
    return query


def _apply_column_time_range(query, column, *, start_time: datetime | None, end_time: datetime | None):
    if start_time is not None:
        query = query.filter(column >= start_time)
    if end_time is not None:
        query = query.filter(column <= end_time)
    return query


def _order_history_query(query, model, *, ascending: bool):
    order = model.sampled_at.asc() if ascending else model.sampled_at.desc()
    return query.order_by(order, model.id.asc() if ascending else model.id.desc())


def _order_by_column_query(query, model, column, *, ascending: bool):
    order = column.asc() if ascending else column.desc()
    return query.order_by(order, model.id.asc() if ascending else model.id.desc())


def list_crypto_ticker_history(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
    ascending: bool = True,
) -> list[CryptoTickerHistory]:
    query = db.query(CryptoTickerHistory)
    if provider:
        query = query.filter(CryptoTickerHistory.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoTickerHistory.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoTickerHistory.instrument_type == normalize_instrument_type(instrument_type))
    query = _apply_time_range(query, CryptoTickerHistory, start_time=start_time, end_time=end_time)
    return _order_history_query(query, CryptoTickerHistory, ascending=ascending).limit(_bounded_history_limit(limit)).all()


def list_crypto_liquidity_history(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    depth_limit: int | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
    ascending: bool = True,
) -> list[CryptoLiquidityHistory]:
    query = db.query(CryptoLiquidityHistory)
    if provider:
        query = query.filter(CryptoLiquidityHistory.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoLiquidityHistory.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoLiquidityHistory.instrument_type == normalize_instrument_type(instrument_type))
    if depth_limit is not None:
        query = query.filter(CryptoLiquidityHistory.depth_limit == max(int(depth_limit), 1))
    query = _apply_time_range(query, CryptoLiquidityHistory, start_time=start_time, end_time=end_time)
    return _order_history_query(query, CryptoLiquidityHistory, ascending=ascending).limit(_bounded_history_limit(limit)).all()


def list_crypto_derivatives_history(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
    ascending: bool = True,
) -> list[CryptoDerivativesMetricHistory]:
    query = db.query(CryptoDerivativesMetricHistory)
    if provider:
        query = query.filter(CryptoDerivativesMetricHistory.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoDerivativesMetricHistory.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoDerivativesMetricHistory.instrument_type == normalize_instrument_type(instrument_type))
    query = _apply_time_range(query, CryptoDerivativesMetricHistory, start_time=start_time, end_time=end_time)
    return _order_history_query(query, CryptoDerivativesMetricHistory, ascending=ascending).limit(_bounded_history_limit(limit)).all()


def list_crypto_spread_history(
    db: Session,
    *,
    base: str | None = None,
    global_provider: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
    ascending: bool = True,
) -> list[CryptoSpreadHistory]:
    query = db.query(CryptoSpreadHistory)
    if base:
        query = query.filter(CryptoSpreadHistory.base_asset == base.strip().upper())
    if global_provider:
        query = query.filter(CryptoSpreadHistory.global_provider == normalize_provider(global_provider))
    query = _apply_time_range(query, CryptoSpreadHistory, start_time=start_time, end_time=end_time)
    return _order_history_query(query, CryptoSpreadHistory, ascending=ascending).limit(_bounded_history_limit(limit)).all()


def list_crypto_liquidation_events(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    liquidation_side: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
    ascending: bool = True,
) -> list[CryptoLiquidationEvent]:
    query = db.query(CryptoLiquidationEvent)
    if provider:
        query = query.filter(CryptoLiquidationEvent.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoLiquidationEvent.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoLiquidationEvent.instrument_type == normalize_instrument_type(instrument_type))
    if liquidation_side:
        query = query.filter(CryptoLiquidationEvent.liquidation_side == liquidation_side.strip().lower())
    query = _apply_column_time_range(
        query,
        CryptoLiquidationEvent.event_time,
        start_time=start_time,
        end_time=end_time,
    )
    return (
        _order_by_column_query(query, CryptoLiquidationEvent, CryptoLiquidationEvent.event_time, ascending=ascending)
        .limit(_bounded_history_limit(limit))
        .all()
    )


def list_crypto_liquidation_heatmap_cells(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    source_kind: str | None = None,
    method: str | None = None,
    liquidation_side: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 5000,
    ascending: bool = True,
) -> list[CryptoLiquidationHeatmapCell]:
    query = db.query(CryptoLiquidationHeatmapCell)
    if provider:
        query = query.filter(CryptoLiquidationHeatmapCell.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoLiquidationHeatmapCell.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoLiquidationHeatmapCell.instrument_type == normalize_instrument_type(instrument_type))
    if source_kind:
        query = query.filter(CryptoLiquidationHeatmapCell.source_kind == source_kind.strip().lower())
    if method:
        query = query.filter(CryptoLiquidationHeatmapCell.method == method.strip().lower())
    if liquidation_side:
        query = query.filter(CryptoLiquidationHeatmapCell.liquidation_side == liquidation_side.strip().lower())
    query = _apply_column_time_range(
        query,
        CryptoLiquidationHeatmapCell.time_bucket,
        start_time=start_time,
        end_time=end_time,
    )
    return (
        _order_by_column_query(
            query,
            CryptoLiquidationHeatmapCell,
            CryptoLiquidationHeatmapCell.time_bucket,
            ascending=ascending,
        )
        .limit(_bounded_history_limit(limit))
        .all()
    )


def list_crypto_cvd_history(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    bucket_seconds: int | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
    ascending: bool = True,
) -> list[CryptoCvdHistory]:
    query = db.query(CryptoCvdHistory)
    if provider:
        query = query.filter(CryptoCvdHistory.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoCvdHistory.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoCvdHistory.instrument_type == normalize_instrument_type(instrument_type))
    if bucket_seconds is not None:
        query = query.filter(CryptoCvdHistory.bucket_seconds == max(int(bucket_seconds), 1))
    query = _apply_time_range(query, CryptoCvdHistory, start_time=start_time, end_time=end_time)
    return _order_history_query(query, CryptoCvdHistory, ascending=ascending).limit(_bounded_history_limit(limit)).all()


def list_crypto_long_short_ratio_history(
    db: Session,
    *,
    provider: str | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str | None = None,
    ratio_scope: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 1000,
    ascending: bool = True,
) -> list[CryptoLongShortRatioHistory]:
    query = db.query(CryptoLongShortRatioHistory)
    if provider:
        query = query.filter(CryptoLongShortRatioHistory.provider == normalize_provider(provider))
    if symbols:
        query = query.filter(CryptoLongShortRatioHistory.symbol.in_(normalize_symbols(symbols)))
    if instrument_type:
        query = query.filter(CryptoLongShortRatioHistory.instrument_type == normalize_instrument_type(instrument_type))
    if ratio_scope:
        query = query.filter(CryptoLongShortRatioHistory.ratio_scope == ratio_scope.strip().lower())
    query = _apply_time_range(query, CryptoLongShortRatioHistory, start_time=start_time, end_time=end_time)
    return (
        _order_history_query(query, CryptoLongShortRatioHistory, ascending=ascending)
        .limit(_bounded_history_limit(limit))
        .all()
    )


def _range_start_time(range_value: str, *, now: datetime) -> datetime | None:
    value = str(range_value or "").strip().lower()
    if value.endswith("h"):
        try:
            hours = int(value[:-1])
        except ValueError:
            return None
        return now - timedelta(hours=max(hours, 1))
    if value.endswith("d"):
        try:
            days = int(value[:-1])
        except ValueError:
            return None
        return now - timedelta(days=max(days, 1))
    if value.endswith("y"):
        try:
            years = int(value[:-1])
        except ValueError:
            return None
        return now - timedelta(days=max(years, 1) * 365)
    return None


def _liquidation_price_bucket(price: float | None) -> tuple[float, float] | None:
    if price is None or price <= 0:
        return None
    bucket_size = max(round(price * 0.001, 2), 1.0)
    return (round(price / bucket_size) * bucket_size, bucket_size)


def build_local_liquidation_heatmap_from_events(
    db: Session,
    *,
    symbols: str | list[str] | tuple[str, ...],
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    bucket_seconds: int = 300,
) -> list[CryptoLiquidationHeatmapCellRecord]:
    normalized_symbols = normalize_symbols(symbols, default=CRYPTO_DEFAULT_DERIVATIVES_SYMBOLS)
    seconds = max(int(bucket_seconds), 1)
    query = db.query(CryptoLiquidationEvent).filter(CryptoLiquidationEvent.symbol.in_(normalized_symbols))
    if start_time is not None:
        query = query.filter(CryptoLiquidationEvent.event_time >= start_time)
    if end_time is not None:
        query = query.filter(CryptoLiquidationEvent.event_time <= end_time)
    events = query.order_by(CryptoLiquidationEvent.event_time.asc(), CryptoLiquidationEvent.id.asc()).all()
    aggregates: dict[tuple[str, datetime, float, str], dict[str, Any]] = {}
    for event in events:
        bucket = _liquidation_price_bucket(event.price)
        if bucket is None:
            continue
        price_bucket, price_bucket_size = bucket
        time_bucket = _sampled_at(event.event_time, seconds)
        side = (event.liquidation_side or "unknown").strip().lower()
        key = (event.symbol, time_bucket, price_bucket, side)
        row = aggregates.setdefault(
            key,
            {
                "event": event,
                "price_bucket_size": price_bucket_size,
                "notional": 0.0,
                "quantity": 0.0,
                "event_count": 0,
            },
        )
        row["notional"] += float(event.notional or 0)
        row["quantity"] += float(event.quantity or 0)
        row["event_count"] += 1
    max_notional = max((row["notional"] for row in aggregates.values()), default=0.0)
    generated_at = _now()
    records: list[CryptoLiquidationHeatmapCellRecord] = []
    for (symbol, time_bucket, price_bucket, side), row in sorted(aggregates.items(), key=lambda item: item[0]):
        event = row["event"]
        records.append(
            CryptoLiquidationHeatmapCellRecord(
                provider=OMI_LOCAL_PROVIDER,
                source_kind="estimated",
                method="local_liquidation_event_bucket",
                exchange="OMI Local",
                symbol=symbol,
                provider_symbol=event.provider_symbol,
                base_asset=event.base_asset,
                quote_asset=event.quote_asset,
                instrument_type=event.instrument_type,
                time_bucket=time_bucket,
                bucket_seconds=seconds,
                price_bucket=price_bucket,
                price_bucket_size=row["price_bucket_size"],
                liquidation_side=side,
                liquidation_notional=row["notional"],
                liquidation_quantity=row["quantity"] if row["quantity"] else None,
                event_count=int(row["event_count"]),
                intensity=(row["notional"] / max_notional if max_notional > 0 else None),
                generated_at=generated_at,
                source_url="local:crypto_liquidation_event",
                raw_payload={
                    "event_count": int(row["event_count"]),
                    "source": "crypto_liquidation_event",
                },
                fetched_at=generated_at,
            )
        )
    return records


def _pending_advanced_metric_refresh_result(
    *,
    resource: str,
    providers: str | list[str] | tuple[str, ...] | None,
    symbols: str | list[str] | tuple[str, ...] | None,
    default_symbols: tuple[str, ...],
    instrument_type: str,
    provider_default: tuple[str, ...] = CRYPTO_ADVANCED_METRIC_PROVIDERS,
) -> dict[str, Any]:
    normalized_providers = normalize_advanced_metric_providers(providers, default=provider_default)
    normalized_symbols = normalize_symbols(symbols, default=default_symbols)
    normalized_instrument_type = normalize_instrument_type(instrument_type)
    skipped = [
        {
            "provider": provider,
            "symbol": symbol,
            "instrument_type": normalized_instrument_type,
            "reason": "provider_not_connected",
        }
        for provider in normalized_providers
        for symbol in normalized_symbols
    ]
    return {
        "status": "skipped" if skipped else "empty",
        "resource": resource,
        "requested_count": len(skipped),
        "refreshed_count": 0,
        "error_count": 0,
        "skipped_count": len(skipped),
        "errors": [],
        "skipped": skipped,
        "rows": [],
    }


def refresh_crypto_liquidation_heatmap(
    db: Session,
    *,
    providers: str | list[str] | tuple[str, ...] | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    range_value: str | None = None,
    allow_local_fallback: bool | None = None,
) -> dict[str, Any]:
    normalized_providers = normalize_advanced_metric_providers(
        providers,
        default=(COINGLASS_PROVIDER,),
    )
    normalized_symbols = normalize_symbols(symbols, default=CRYPTO_DEFAULT_DERIVATIVES_SYMBOLS)
    effective_range = str(range_value or settings.crypto_market_liquidation_heatmap_range or "24h").strip() or "24h"
    fallback_enabled = (
        bool(settings.enable_crypto_market_liquidation_local_fallback)
        if allow_local_fallback is None
        else bool(allow_local_fallback)
    )
    now = _now()
    start_time = _range_start_time(effective_range, now=now)
    errors: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    rows: list[CryptoLiquidationHeatmapCell] = []

    def persist_heatmap_records(records: list[CryptoLiquidationHeatmapCellRecord]) -> list[CryptoLiquidationHeatmapCell]:
        persisted = [upsert_crypto_liquidation_heatmap_cell(db, record) for record in records]
        db.commit()
        for row in persisted:
            db.refresh(row)
        return persisted

    def try_local_fallback(symbol: str, *, reason: str) -> bool:
        if not fallback_enabled:
            skipped.append(
                {
                    "provider": OMI_LOCAL_PROVIDER,
                    "symbol": symbol,
                    "instrument_type": PERPETUAL,
                    "reason": "local_fallback_disabled",
                    "trigger": reason,
                }
            )
            return False
        try:
            records = build_local_liquidation_heatmap_from_events(
                db,
                symbols=(symbol,),
                start_time=start_time,
                end_time=now,
            )
            if not records:
                skipped.append(
                    {
                        "provider": OMI_LOCAL_PROVIDER,
                        "symbol": symbol,
                        "instrument_type": PERPETUAL,
                        "reason": "local_estimate_no_events",
                        "trigger": reason,
                    }
                )
                return False
            rows.extend(persist_heatmap_records(records))
            _record_event(
                db,
                provider=OMI_LOCAL_PROVIDER,
                resource="crypto_liquidation_heatmap",
                target=symbol,
                status="success",
                message=f"Built local liquidation heatmap fallback for {symbol}.",
                detail={"trigger": reason, "row_count": len(records)},
            )
            return True
        except Exception as exc:
            db.rollback()
            errors.append(
                {
                    "provider": OMI_LOCAL_PROVIDER,
                    "symbol": symbol,
                    "error": str(exc),
                    "trigger": reason,
                }
            )
            _record_event(
                db,
                provider=OMI_LOCAL_PROVIDER,
                resource="crypto_liquidation_heatmap",
                target=symbol,
                status="error",
                error_message=str(exc),
                detail={"trigger": reason},
            )
            return False

    for provider in normalized_providers:
        for symbol in normalized_symbols:
            if provider == COINGLASS_PROVIDER:
                try:
                    records = sources.fetch_coinglass_liquidation_heatmap(
                        symbol,
                        range_value=effective_range,
                    )
                    if not records:
                        skipped.append(
                            {
                                "provider": provider,
                                "symbol": symbol,
                                "instrument_type": PERPETUAL,
                                "reason": "coinglass_empty",
                            }
                        )
                        try_local_fallback(symbol, reason="coinglass_empty")
                        continue
                    rows.extend(persist_heatmap_records(records))
                    _record_event(
                        db,
                        provider=provider,
                        resource="crypto_liquidation_heatmap",
                        target=symbol,
                        status="success",
                        message=f"Refreshed CoinGlass liquidation heatmap for {symbol}.",
                        detail={"range": effective_range, "row_count": len(records)},
                    )
                    continue
                except Exception as exc:
                    db.rollback()
                    message = str(exc)
                    if "API key is not configured" in message:
                        skipped.append(
                            {
                                "provider": provider,
                                "symbol": symbol,
                                "instrument_type": PERPETUAL,
                                "reason": "coinglass_api_key_missing",
                            }
                        )
                    else:
                        errors.append({"provider": provider, "symbol": symbol, "error": message})
                        _record_event(
                            db,
                            provider=provider,
                            resource="crypto_liquidation_heatmap",
                            target=symbol,
                            status="error",
                            error_message=message,
                            detail={"range": effective_range},
                        )

                    try:
                        order_records = sources.fetch_coinglass_liquidation_orders(
                            symbol,
                            exchange=settings.crypto_market_liquidation_fallback_exchange,
                            min_liquidation_amount=settings.crypto_market_liquidation_min_amount,
                            start_time=start_time,
                            end_time=now,
                        )
                        for record in order_records:
                            upsert_crypto_liquidation_event(db, record)
                        if order_records:
                            db.commit()
                            _record_event(
                                db,
                                provider=provider,
                                resource="crypto_liquidation_event",
                                target=symbol,
                                status="success",
                                message=f"Refreshed CoinGlass liquidation orders for local heatmap fallback: {symbol}.",
                                detail={"row_count": len(order_records)},
                            )
                    except Exception as order_exc:
                        if "API key is not configured" not in str(order_exc):
                            errors.append(
                                {
                                    "provider": provider,
                                    "symbol": symbol,
                                    "resource": "liquidation_order",
                                    "error": str(order_exc),
                                }
                            )
                    try_local_fallback(symbol, reason="coinglass_unavailable")
                continue

            if provider == OMI_LOCAL_PROVIDER:
                try_local_fallback(symbol, reason="manual_local_provider")
                continue

            skipped.append(
                {
                    "provider": provider,
                    "symbol": symbol,
                    "instrument_type": PERPETUAL,
                    "reason": "provider_not_connected",
                }
            )

    db.commit()
    status_value = _status_for_counts(len(rows), len(errors))
    if not rows and not errors and skipped:
        status_value = "skipped"
    return {
        "status": status_value,
        "resource": "liquidation_heatmap",
        "requested_count": len(normalized_providers) * len(normalized_symbols),
        "refreshed_count": len(rows),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "errors": errors,
        "skipped": skipped,
        "rows": rows,
    }


def refresh_crypto_cvd(
    db: Session,
    *,
    providers: str | list[str] | tuple[str, ...] | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
    instrument_type: str = SPOT,
) -> dict[str, Any]:
    _ = db
    normalized_instrument_type = normalize_instrument_type(instrument_type)
    default_symbols = CRYPTO_DEFAULT_DERIVATIVES_SYMBOLS if normalized_instrument_type == PERPETUAL else CRYPTO_DEFAULT_SYMBOLS
    provider_default = (BINANCE_PROVIDER, OKX_PROVIDER)
    return _pending_advanced_metric_refresh_result(
        resource="cvd",
        providers=providers,
        symbols=symbols,
        default_symbols=default_symbols,
        instrument_type=normalized_instrument_type,
        provider_default=provider_default,
    )


def refresh_crypto_long_short_ratios(
    db: Session,
    *,
    providers: str | list[str] | tuple[str, ...] | None = None,
    symbols: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    normalized_providers = normalize_advanced_metric_providers(
        providers,
        default=(BINANCE_PROVIDER, BYBIT_PROVIDER),
    )
    normalized_symbols = normalize_symbols(symbols, default=CRYPTO_DEFAULT_DERIVATIVES_SYMBOLS)
    rows: list[CryptoLongShortRatioHistory] = []
    errors: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for provider in normalized_providers:
        for symbol in normalized_symbols:
            if provider == BINANCE_PROVIDER:
                try:
                    records = sources.fetch_binance_long_short_account_ratio(
                        symbol,
                        period=settings.crypto_market_long_short_ratio_period,
                        limit=settings.crypto_market_long_short_ratio_limit,
                    )
                    if not records:
                        skipped.append(
                            {
                                "provider": provider,
                                "symbol": symbol,
                                "instrument_type": PERPETUAL,
                                "reason": "binance_long_short_ratio_empty",
                            }
                        )
                        continue
                    rows.extend(upsert_crypto_long_short_ratio_history(db, record) for record in records)
                    db.commit()
                    for row in rows[-len(records):]:
                        db.refresh(row)
                    _record_event(
                        db,
                        provider=provider,
                        resource="crypto_long_short_ratio",
                        target=symbol,
                        status="success",
                        message=f"Refreshed Binance long/short account ratio for {symbol}.",
                        detail={
                            "period": settings.crypto_market_long_short_ratio_period,
                            "limit": settings.crypto_market_long_short_ratio_limit,
                            "row_count": len(records),
                        },
                    )
                    continue
                except Exception as exc:
                    db.rollback()
                    message = str(exc)
                    errors.append({"provider": provider, "symbol": symbol, "error": message})
                    _record_event(
                        db,
                        provider=provider,
                        resource="crypto_long_short_ratio",
                        target=symbol,
                        status="error",
                        error_message=message,
                        detail={
                            "period": settings.crypto_market_long_short_ratio_period,
                            "limit": settings.crypto_market_long_short_ratio_limit,
                        },
                    )
                    continue

            skipped.append(
                {
                    "provider": provider,
                    "symbol": symbol,
                    "instrument_type": PERPETUAL,
                    "reason": "provider_not_connected",
                }
            )

    db.commit()
    status_value = _status_for_counts(len(rows), len(errors))
    if not rows and not errors and skipped:
        status_value = "skipped"
    return {
        "status": status_value,
        "resource": "long_short_ratio",
        "requested_count": len(normalized_providers) * len(normalized_symbols),
        "refreshed_count": len(rows),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "errors": errors,
        "skipped": skipped,
        "rows": rows,
    }


def list_latest_crypto_market_caps(
    db: Session,
    *,
    vs_currency: str | None = None,
    limit: int = 100,
) -> list[CryptoMarketCapSnapshot]:
    query = db.query(CryptoMarketCapSnapshot)
    if vs_currency:
        query = query.filter(CryptoMarketCapSnapshot.vs_currency == vs_currency.strip().lower())
    return (
        query.order_by(CryptoMarketCapSnapshot.market_cap_rank.asc(), CryptoMarketCapSnapshot.id.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def _latest_ticker(
    db: Session,
    *,
    provider: str,
    symbol: str,
    instrument_type: str = SPOT,
) -> CryptoTickerSnapshot | None:
    return (
        db.query(CryptoTickerSnapshot)
        .filter(CryptoTickerSnapshot.provider == provider)
        .filter(CryptoTickerSnapshot.symbol == symbol)
        .filter(CryptoTickerSnapshot.instrument_type == instrument_type)
        .order_by(CryptoTickerSnapshot.fetched_at.desc(), CryptoTickerSnapshot.id.desc())
        .first()
    )


def refresh_crypto_spreads(
    db: Session,
    *,
    bases: str | list[str] | tuple[str, ...] | None = None,
    global_providers: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    base_assets = [item.strip().upper() for item in _split_csv(bases, default=CRYPTO_DEFAULT_SPREAD_BASES)]
    provider_list = normalize_providers(global_providers, default=(BINANCE_PROVIDER, OKX_PROVIDER))
    rows = []
    errors = []
    skipped = []
    observed_at = _now()
    fx_row = _latest_ticker(db, provider=BITOPRO_PROVIDER, symbol="USDT-TWD", instrument_type=SPOT)
    if fx_row is None or fx_row.last_price in {None, 0}:
        return {
            "status": "empty",
            "resource": "spread",
            "requested_count": len(base_assets) * len(provider_list),
            "refreshed_count": 0,
            "error_count": 0,
            "skipped_count": len(base_assets) * len(provider_list),
            "errors": [],
            "skipped": [{"reason": "missing bitopro USDT-TWD local FX ticker"}],
            "rows": [],
        }
    for base_asset in base_assets:
        subscription_reason = _subscription_skip_for_crypto_asset(
            db,
            asset=base_asset,
            resource="taiwan_spread",
        )
        if subscription_reason:
            skipped.append({"base_asset": base_asset, "reason": subscription_reason})
            continue
        local_symbol = f"{base_asset}-TWD"
        local_row = _latest_ticker(db, provider=BITOPRO_PROVIDER, symbol=local_symbol, instrument_type=SPOT)
        if local_row is None or local_row.last_price is None:
            skipped.append({"base_asset": base_asset, "reason": f"missing local ticker {local_symbol}"})
            continue
        for global_provider in provider_list:
            global_symbol = f"{base_asset}-USDT"
            global_row = _latest_ticker(db, provider=global_provider, symbol=global_symbol, instrument_type=SPOT)
            if global_row is None or global_row.last_price is None:
                skipped.append(
                    {
                        "base_asset": base_asset,
                        "global_provider": global_provider,
                        "reason": f"missing global ticker {global_symbol}",
                    }
                )
                continue
            implied_twd = global_row.last_price * fx_row.last_price
            spread = local_row.last_price - implied_twd
            spread_pct = (spread / implied_twd * 100) if implied_twd else None
            row = (
                db.query(CryptoSpreadSnapshot)
                .filter(CryptoSpreadSnapshot.base_asset == base_asset)
                .filter(CryptoSpreadSnapshot.local_provider == BITOPRO_PROVIDER)
                .filter(CryptoSpreadSnapshot.global_provider == global_provider)
                .filter(CryptoSpreadSnapshot.local_symbol == local_symbol)
                .filter(CryptoSpreadSnapshot.global_symbol == global_symbol)
                .filter(CryptoSpreadSnapshot.fx_symbol == "USDT-TWD")
                .first()
            )
            source_state = {
                "local_fetched_at": local_row.fetched_at.isoformat() if local_row.fetched_at else None,
                "global_fetched_at": global_row.fetched_at.isoformat() if global_row.fetched_at else None,
                "fx_fetched_at": fx_row.fetched_at.isoformat() if fx_row.fetched_at else None,
            }
            values = {
                "quote_asset": "TWD",
                "fx_provider": BITOPRO_PROVIDER,
                "local_price": local_row.last_price,
                "global_price": global_row.last_price,
                "fx_rate": fx_row.last_price,
                "implied_twd_price": implied_twd,
                "spread": spread,
                "spread_pct": spread_pct,
                "observed_at": observed_at,
                "source_state_json": _json_dumps(source_state),
                "updated_at": utc_now(),
            }
            if row is None:
                row = CryptoSpreadSnapshot(
                    base_asset=base_asset,
                    local_provider=BITOPRO_PROVIDER,
                    global_provider=global_provider,
                    local_symbol=local_symbol,
                    global_symbol=global_symbol,
                    fx_symbol="USDT-TWD",
                    **values,
                )
                db.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            _upsert_spread_history(db, row)
            rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return {
        "status": _status_for_counts(len(rows), len(errors)),
        "resource": "spread",
        "requested_count": len(base_assets) * len(provider_list),
        "refreshed_count": len(rows),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "errors": errors,
        "skipped": skipped,
        "rows": rows,
    }


def list_latest_crypto_spreads(
    db: Session,
    *,
    base: str | None = None,
    global_provider: str | None = None,
    limit: int = 100,
) -> list[CryptoSpreadSnapshot]:
    query = db.query(CryptoSpreadSnapshot)
    if base:
        query = query.filter(CryptoSpreadSnapshot.base_asset == base.strip().upper())
    if global_provider:
        query = query.filter(CryptoSpreadSnapshot.global_provider == normalize_provider(global_provider))
    return (
        query.order_by(CryptoSpreadSnapshot.observed_at.desc(), CryptoSpreadSnapshot.id.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )

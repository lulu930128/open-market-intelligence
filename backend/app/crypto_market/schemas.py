from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CryptoProviderContractRead(BaseModel):
    kind: str
    market: str
    execution_enabled: bool
    ai_execution_enabled: bool
    notes: list[str]
    providers: dict[str, Any]
    ohlcv_intervals: dict[str, list[str]] = Field(default_factory=dict)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    instruments: list[dict[str, Any]]
    coin_ids: dict[str, str]


class CryptoWatchlistGroupCreate(BaseModel):
    parent_id: int | None = None
    group_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 100
    is_active: bool = True


class CryptoWatchlistGroupUpdate(BaseModel):
    parent_id: int | None = None
    group_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class CryptoWatchlistGroupRead(BaseModel):
    id: int
    parent_id: int | None = None
    group_name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CryptoWatchlistGroupTreeRead(BaseModel):
    id: int
    parent_id: int | None = None
    group_name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    children: list["CryptoWatchlistGroupTreeRead"] = Field(default_factory=list)


class CryptoWatchlistItemCreate(BaseModel):
    group_id: int
    asset: str = Field(..., min_length=1, max_length=20)
    note: str | None = None
    priority: int = 100
    tags: str | None = None
    enabled: bool = True


class CryptoWatchlistItemUpdate(BaseModel):
    group_id: int | None = None
    asset: str | None = Field(default=None, min_length=1, max_length=20)
    note: str | None = None
    priority: int | None = None
    tags: str | None = None
    enabled: bool | None = None


class CryptoWatchlistItemRead(BaseModel):
    id: int
    group_id: int
    asset: str
    asset_name: str | None = None
    note: str | None = None
    priority: int
    tags: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CryptoWatchlistGroupDeleteResultRead(BaseModel):
    group_id: int
    recursive: bool
    deleted_group_count: int
    deleted_item_count: int


class CryptoTickerRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str

    last_price: float | None = None
    bid_price: float | None = None
    bid_size: float | None = None
    ask_price: float | None = None
    ask_size: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    price_change_24h: float | None = None
    price_change_pct_24h: float | None = None
    base_volume_24h: float | None = None
    quote_volume_24h: float | None = None

    event_time: datetime | None = None
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoTickerHistoryRead(CryptoTickerRead):
    sampled_at: datetime

    model_config = ConfigDict(from_attributes=True)


def _decode_depth_levels(value: Any) -> list[dict[str, float | int | None]]:
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []

    levels: list[dict[str, float | int | None]] = []
    for row in value[:100]:
        if not isinstance(row, dict):
            continue
        price = row.get("price")
        size = row.get("size")
        if not isinstance(price, (int, float)) or not isinstance(size, (int, float)):
            continue
        levels.append(
            {
                "price": price,
                "size": size,
                **({"count": row.get("count")} if isinstance(row.get("count"), (int, float)) else {}),
            }
        )
    return levels


class CryptoOrderBookRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    depth_limit: int

    best_bid_price: float | None = None
    best_bid_size: float | None = None
    best_ask_price: float | None = None
    best_ask_size: float | None = None
    spread: float | None = None
    spread_pct: float | None = None
    bids: list[dict[str, float | int | None]] = Field(default_factory=list)
    asks: list[dict[str, float | int | None]] = Field(default_factory=list)

    event_time: datetime | None = None
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def parse_depth_json(cls, value: Any) -> Any:
        if isinstance(value, dict):
            payload = dict(value)
            payload.setdefault("bids", _decode_depth_levels(payload.get("bids_json")))
            payload.setdefault("asks", _decode_depth_levels(payload.get("asks_json")))
            return payload

        bids_json = getattr(value, "bids_json", None)
        asks_json = getattr(value, "asks_json", None)
        if bids_json is None and asks_json is None:
            return value

        payload = {
            name: getattr(value, name)
            for name in (
                "id",
                "provider",
                "exchange",
                "symbol",
                "provider_symbol",
                "base_asset",
                "quote_asset",
                "instrument_type",
                "depth_limit",
                "best_bid_price",
                "best_bid_size",
                "best_ask_price",
                "best_ask_size",
                "spread",
                "spread_pct",
                "event_time",
                "source_url",
                "fetched_at",
                "created_at",
                "updated_at",
            )
        }
        if hasattr(value, "sampled_at"):
            payload["sampled_at"] = getattr(value, "sampled_at")
        payload["bids"] = _decode_depth_levels(bids_json)
        payload["asks"] = _decode_depth_levels(asks_json)
        return payload


class CryptoLiquidityHistoryRead(CryptoOrderBookRead):
    sampled_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoOhlcvBarRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    interval: str
    bar_time: datetime

    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    base_volume: float | None = None
    quote_volume: float | None = None

    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoOhlcvCoverageRead(BaseModel):
    provider: str
    exchange: str | None = None
    symbol: str
    instrument_type: str
    interval: str
    row_count: int
    first_bar_time: datetime | None = None
    last_bar_time: datetime | None = None
    latest_fetched_at: datetime | None = None


class CryptoDerivativesMetricRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str

    mark_price: float | None = None
    index_price: float | None = None
    funding_rate: float | None = None
    next_funding_time: datetime | None = None
    open_interest: float | None = None
    open_interest_value: float | None = None

    event_time: datetime | None = None
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoDerivativesMetricHistoryRead(CryptoDerivativesMetricRead):
    sampled_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoMarketCapRead(BaseModel):
    id: int
    provider: str
    coin_id: str
    symbol: str
    name: str | None = None
    vs_currency: str

    current_price: float | None = None
    market_cap: float | None = None
    market_cap_rank: int | None = None
    total_volume: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    price_change_pct_24h: float | None = None
    circulating_supply: float | None = None
    total_supply: float | None = None
    max_supply: float | None = None

    last_updated: datetime | None = None
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoSpreadRead(BaseModel):
    id: int
    base_asset: str
    quote_asset: str
    local_provider: str
    global_provider: str
    fx_provider: str
    local_symbol: str
    global_symbol: str
    fx_symbol: str

    local_price: float | None = None
    global_price: float | None = None
    fx_rate: float | None = None
    implied_twd_price: float | None = None
    spread: float | None = None
    spread_pct: float | None = None

    observed_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoSpreadHistoryRead(CryptoSpreadRead):
    sampled_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoLiquidationEventRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str

    liquidation_side: str
    order_side: str | None = None
    price: float | None = None
    average_price: float | None = None
    quantity: float | None = None
    notional: float | None = None

    event_time: datetime
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoLiquidationHeatmapCellRead(BaseModel):
    id: int
    provider: str
    source_kind: str
    method: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str

    time_bucket: datetime
    bucket_seconds: int
    price_bucket: float
    price_bucket_size: float | None = None
    liquidation_side: str
    liquidation_notional: float | None = None
    liquidation_quantity: float | None = None
    event_count: int
    intensity: float | None = None

    generated_at: datetime
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoCvdHistoryRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str

    bucket_seconds: int
    sampled_at: datetime
    buy_base_volume: float | None = None
    sell_base_volume: float | None = None
    buy_quote_volume: float | None = None
    sell_quote_volume: float | None = None
    net_base_volume: float | None = None
    net_quote_volume: float | None = None
    cumulative_base_delta: float | None = None
    cumulative_quote_delta: float | None = None
    trade_count: int

    event_time: datetime | None = None
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoLongShortRatioHistoryRead(BaseModel):
    id: int
    provider: str
    exchange: str
    symbol: str
    provider_symbol: str
    base_asset: str
    quote_asset: str
    instrument_type: str
    ratio_scope: str

    long_ratio: float | None = None
    short_ratio: float | None = None
    long_short_ratio: float | None = None

    event_time: datetime | None = None
    sampled_at: datetime
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CryptoRefreshResultRead(BaseModel):
    status: str
    resource: str
    requested_count: int
    refreshed_count: int
    error_count: int
    skipped_count: int
    errors: list[dict[str, Any]]
    skipped: list[dict[str, Any]]


class CryptoTickerRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoTickerRead]


class CryptoOrderBookRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoOrderBookRead]


class CryptoOhlcvRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoOhlcvBarRead]


class CryptoOhlcvBundleIntervalRefreshRead(CryptoRefreshResultRead):
    interval: str
    limit: int
    supported_providers: list[str]


class CryptoOhlcvBundleRefreshResultRead(CryptoRefreshResultRead):
    intervals: list[CryptoOhlcvBundleIntervalRefreshRead]


class CryptoDerivativesRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoDerivativesMetricRead]


class CryptoMarketCapRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoMarketCapRead]


class CryptoSpreadRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoSpreadRead]


class CryptoLiquidationHeatmapRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoLiquidationHeatmapCellRead]


class CryptoCvdRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoCvdHistoryRead]


class CryptoLongShortRatioRefreshResultRead(CryptoRefreshResultRead):
    rows: list[CryptoLongShortRatioHistoryRead]


class CryptoSourceHealthRead(BaseModel):
    kind: str
    generated_at: str
    filters: dict[str, Any]
    summary: dict[str, int]
    entries: list[dict[str, Any]]


class CryptoRealtimeStreamRead(BaseModel):
    provider: str
    resource: str
    message_resources: list[str] = Field(default_factory=list)
    symbols: list[str]
    instrument_type: str
    url: str
    verified: bool
    notes: str
    subscribe_message: dict[str, Any] | None = None


class CryptoRealtimeLatestRead(BaseModel):
    provider: str
    resource: str
    symbol: str
    provider_symbol: str
    instrument_type: str
    event_time: str | None = None
    received_at: str
    feed_lag_ms: int | None = None
    last_message_age_ms: int
    stale: bool
    sequence: int | None = None
    data: dict[str, Any]


class CryptoRealtimeStatusRead(BaseModel):
    kind: str
    enabled: bool
    running: bool
    websockets_available: bool | None = None
    enabled_providers: list[str]
    subscription_policy: str | None = None
    reloading: bool = False
    reload_count: int = 0
    last_reload_at: str | None = None
    last_reload_reason: str | None = None
    task_count: int
    active_task_count: int
    last_started_at: str | None = None
    last_stopped_at: str | None = None
    last_error: str | None = None
    latest_count: int
    persistence: dict[str, Any] = Field(default_factory=dict)
    streams: list[CryptoRealtimeStreamRead]
    enabled_streams: list[CryptoRealtimeStreamRead] = Field(default_factory=list)

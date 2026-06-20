from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class JPStockMasterRead(BaseModel):
    id: int

    symbol: str
    local_code: str | None = None
    security_name: str | None = None
    exchange: str | None = None
    market_segment: str | None = None
    sector_33_code: str | None = None
    sector_33_name: str | None = None
    sector_17_code: str | None = None
    sector_17_name: str | None = None
    size_code: str | None = None
    size_name: str | None = None
    asset_type: str
    listing_source: str
    currency: str
    exchange_timezone_name: str | None = None

    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JPDailyPriceRead(BaseModel):
    id: int

    provider: str
    symbol: str
    trade_date: date
    currency: str

    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    adjusted_close: float | None = None

    trade_volume: int | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JPDailyPriceRefreshResultRead(BaseModel):
    status: str
    provider: str
    symbol: str
    fetched_count: int
    inserted_count: int
    updated_count: int
    message: str


class JPStockMasterSyncResultRead(BaseModel):
    status: str
    provider: str
    source_url: str
    scanned_count: int
    created_count: int
    updated_count: int
    deactivated_count: int = 0
    message: str


class JPOhlcPointRead(BaseModel):
    time: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None


class JPOhlcChartRead(BaseModel):
    symbol: str
    timeframe: str
    bars: int
    lookback_days: int
    from_date: date
    to_date: date
    point_count: int
    points: list[JPOhlcPointRead]
    backfill: dict | None = None


class JPResourceSlotRead(BaseModel):
    key: str
    status: str
    available: bool
    source: str | None = None
    latest_date: date | None = None
    row_count: int = 0


class JPResourceSummaryRead(BaseModel):
    symbol: str
    slots: list[JPResourceSlotRead]


class JPWatchlistGroupCreate(BaseModel):
    parent_id: int | None = None
    group_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 100
    is_active: bool = True


class JPWatchlistGroupUpdate(BaseModel):
    parent_id: int | None = None
    group_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class JPWatchlistGroupRead(BaseModel):
    id: int
    parent_id: int | None = None
    group_name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JPWatchlistGroupTreeRead(BaseModel):
    id: int
    parent_id: int | None = None
    group_name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    children: list["JPWatchlistGroupTreeRead"] = []


class JPWatchlistGroupDeleteResultRead(BaseModel):
    deleted_group_id: int
    deleted_item_count: int
    deleted_group_count: int


class JPWatchlistItemCreate(BaseModel):
    group_id: int
    symbol: str = Field(..., min_length=1, max_length=32)
    note: str | None = None
    priority: int = 100
    tags: str | None = None
    enabled: bool = True


class JPWatchlistItemUpdate(BaseModel):
    group_id: int | None = None
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    note: str | None = None
    priority: int | None = None
    tags: str | None = None
    enabled: bool | None = None


class JPWatchlistItemRead(BaseModel):
    id: int
    group_id: int
    symbol: str
    local_code: str | None = None
    security_name: str | None = None
    exchange: str | None = None
    market_segment: str | None = None
    sector_33_name: str | None = None
    asset_type: str | None = None
    note: str | None = None
    priority: int
    tags: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

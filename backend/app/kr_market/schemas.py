from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class KRStockMasterRead(BaseModel):
    id: int

    symbol: str
    local_code: str | None = None
    security_name: str | None = None
    security_name_kr: str | None = None
    exchange: str | None = None
    market_segment: str | None = None
    sector: str | None = None
    industry: str | None = None
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


class KRStockMasterSyncResultRead(BaseModel):
    status: str
    provider: str
    source_url: str | None = None
    scanned_count: int
    created_count: int
    updated_count: int
    deactivated_count: int = 0
    message: str


class KRDailyPriceRead(BaseModel):
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

    price_change: float | None = None
    change_pct: float | None = None
    trade_volume: int | None = None
    trade_value: int | None = None
    market_cap: int | None = None
    listed_shares: int | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KRDailyPriceRefreshResultRead(BaseModel):
    status: str
    provider: str
    symbol: str
    fetched_count: int
    inserted_count: int
    updated_count: int
    message: str


class KRCompanyFundamentalRead(BaseModel):
    id: int

    provider: str
    symbol: str
    corp_code: str | None = None
    stock_code: str | None = None
    company_name: str | None = None

    fiscal_year: int | None = None
    report_code: str | None = None
    report_name: str | None = None
    statement_name: str | None = None
    account_name: str | None = None
    account_id: str | None = None

    current_amount: int | None = None
    previous_amount: int | None = None
    currency: str | None = None
    disclosed_date: date | None = None
    receipt_no: str | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KRInvestorTradeDailyRead(BaseModel):
    id: int

    provider: str
    symbol: str
    trade_date: date
    investor_type: str
    buy_value: int | None = None
    sell_value: int | None = None
    net_buy_value: int | None = None
    buy_volume: int | None = None
    sell_volume: int | None = None
    net_buy_volume: int | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KRResourceRefreshResultRead(BaseModel):
    status: str
    provider: str
    symbol: str | None = None
    fetched_count: int
    inserted_count: int
    updated_count: int
    message: str


class KROhlcPointRead(BaseModel):
    time: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None


class KROhlcChartRead(BaseModel):
    symbol: str
    timeframe: str
    bars: int
    lookback_days: int
    from_date: date
    to_date: date
    point_count: int
    points: list[KROhlcPointRead]
    backfill: dict | None = None


class KRResourceSlotRead(BaseModel):
    key: str
    status: str
    available: bool
    source: str | None = None
    latest_date: date | None = None
    row_count: int = 0
    metrics: dict[str, int | float | str | None] = Field(default_factory=dict)


class KRResourceSummaryRead(BaseModel):
    symbol: str
    slots: list[KRResourceSlotRead]


class KRSourceHealthEntryRead(BaseModel):
    resource: str
    provider: str
    target: str
    status: str
    ok: bool
    row_count: int
    latest_data_date: date | None = None
    latest_fetched_at: datetime | None = None
    expected_data_date: date | None = None
    freshness_lag_days: int | None = None
    source_url: str | None = None
    data_quality: str
    reason: str
    rate_limited: bool = False
    retry_after_seconds: int | None = None
    error_message: str | None = None
    latest_event_id: int | None = None
    latest_event_at: datetime | None = None
    latest_event_status: str | None = None
    latest_event_severity: str | None = None
    latest_event_message: str | None = None
    recent_event_count: int = 0
    recent_error_count: int = 0
    consecutive_error_count: int = 0


class KRSourceHealthSummaryRead(BaseModel):
    entry_count: int
    ok_count: int
    empty_count: int
    stale_count: int
    error_count: int


class KRSourceHealthRead(BaseModel):
    kind: str
    generated_at: datetime
    filters: dict[str, str | None] = Field(default_factory=dict)
    expected_daily_price_date: date | None = None
    summary: KRSourceHealthSummaryRead
    entries: list[KRSourceHealthEntryRead] = Field(default_factory=list)


class KRWatchlistReadinessItemRead(BaseModel):
    symbol: str
    security_name: str | None = None
    group_id: int
    market_segment: str | None = None
    latest_daily_date: date | None = None
    latest_daily_provider: str | None = None
    daily_row_count: int = 0
    daily_status: str
    latest_investor_date: date | None = None
    investor_row_count: int = 0
    latest_fundamental_date: date | None = None
    fundamental_row_count: int = 0
    readiness_status: str
    missing_resources: list[str] = Field(default_factory=list)


class KRWatchlistReadinessSummaryRead(BaseModel):
    requested_symbol_count: int
    ready_count: int
    partial_count: int
    no_data_count: int
    daily_current_count: int
    daily_stale_count: int
    daily_empty_count: int
    investor_available_count: int
    fundamental_available_count: int


class KRWatchlistReadinessRead(BaseModel):
    kind: str
    group_id: int | None = None
    include_children: bool
    enabled_only: bool
    expected_daily_price_date: date | None = None
    summary: KRWatchlistReadinessSummaryRead
    results: list[KRWatchlistReadinessItemRead]


class KRWatchlistGroupCreate(BaseModel):
    parent_id: int | None = None
    group_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 100
    is_active: bool = True


class KRWatchlistGroupUpdate(BaseModel):
    parent_id: int | None = None
    group_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class KRWatchlistGroupRead(BaseModel):
    id: int
    parent_id: int | None = None
    group_name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KRWatchlistGroupTreeRead(BaseModel):
    id: int
    parent_id: int | None = None
    group_name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    children: list["KRWatchlistGroupTreeRead"] = Field(default_factory=list)


class KRWatchlistGroupDeleteResultRead(BaseModel):
    deleted_group_id: int
    deleted_item_count: int
    deleted_group_count: int


class KRWatchlistItemCreate(BaseModel):
    group_id: int
    symbol: str = Field(..., min_length=1, max_length=32)
    note: str | None = None
    priority: int = 100
    tags: str | None = None
    enabled: bool = True


class KRWatchlistItemUpdate(BaseModel):
    group_id: int | None = None
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    note: str | None = None
    priority: int | None = None
    tags: str | None = None
    enabled: bool | None = None


class KRWatchlistItemRead(BaseModel):
    id: int
    group_id: int
    symbol: str
    local_code: str | None = None
    security_name: str | None = None
    security_name_kr: str | None = None
    exchange: str | None = None
    market_segment: str | None = None
    sector: str | None = None
    industry: str | None = None
    asset_type: str | None = None
    note: str | None = None
    priority: int
    tags: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class KRWatchlistRankingItemRead(BaseModel):
    rank: int
    symbol: str
    security_name: str | None = None
    exchange: str | None = None
    market_segment: str | None = None
    sector: str | None = None
    industry: str | None = None
    asset_type: str | None = None
    group_id: int
    trade_date: date | None = None
    close: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    status: str
    source: str | None = None
    error_message: str | None = None


class KRWatchlistRankingRead(BaseModel):
    group_id: int | None = None
    include_children: bool
    rank_by: str
    sort_order: str
    requested_symbol_count: int
    ranked_count: int
    no_data_count: int
    error_count: int
    trade_date: date | None = None
    target_trade_date: date | None = None
    is_current: bool = True
    current_symbol_count: int = 0
    stale_symbol_count: int = 0
    results: list[KRWatchlistRankingItemRead]

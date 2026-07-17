from __future__ import annotations

from datetime import date, datetime
from typing import Any

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


class JPResourceRefreshResultRead(BaseModel):
    status: str
    provider: str
    symbol: str
    fetched_count: int
    inserted_count: int
    updated_count: int
    message: str


class JPSourceHealthEntryRead(BaseModel):
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
    latest_event_id: int | None = None
    latest_event_at: datetime | None = None
    latest_event_status: str | None = None
    latest_event_severity: str | None = None
    latest_event_message: str | None = None
    recent_event_count: int = 0
    recent_error_count: int = 0
    consecutive_error_count: int = 0


class JPSourceHealthSummaryRead(BaseModel):
    entry_count: int
    ok_count: int
    empty_count: int
    stale_count: int
    error_count: int


class JPSourceHealthRead(BaseModel):
    kind: str
    generated_at: datetime
    filters: dict[str, str | None] = Field(default_factory=dict)
    expected_daily_price_date: date | None = None
    freshness_policy: dict[str, Any] = Field(default_factory=dict)
    summary: JPSourceHealthSummaryRead
    entries: list[JPSourceHealthEntryRead] = Field(default_factory=list)


class JPCompanyFundamentalRead(BaseModel):
    id: int

    provider: str
    symbol: str
    company_name: str | None = None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None

    market_cap: int | None = None
    enterprise_value: int | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None

    disclosed_date: date | None = None
    fiscal_period: str | None = None
    fiscal_year_end: date | None = None
    document_type: str | None = None

    eps_ttm: float | None = None
    forward_eps: float | None = None
    revenue_ttm: int | None = None
    net_sales: int | None = None
    operating_profit: int | None = None
    ordinary_profit: int | None = None
    profit: int | None = None
    forecast_net_sales: int | None = None
    forecast_operating_profit: int | None = None
    forecast_ordinary_profit: int | None = None
    forecast_profit: int | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    profit_margin: float | None = None
    return_on_equity: float | None = None
    return_on_assets: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None

    total_assets: int | None = None
    equity: int | None = None
    equity_to_asset_ratio: float | None = None
    total_cash: int | None = None
    total_debt: int | None = None
    operating_cash_flow: int | None = None
    investing_cash_flow: int | None = None
    financing_cash_flow: int | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    shares_outstanding: int | None = None
    book_value: float | None = None

    earnings_date: date | None = None
    ex_dividend_date: date | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    latest_data_date: date | None = None
    expected_data_date: date | None = None
    freshness_status: str = "unknown"
    is_current: bool = False
    refresh_recommended: bool = False


class JPIntradayTrendPointRead(BaseModel):
    time: str
    session: str = "regular"
    price: float
    volume: int | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None


class JPIntradayTrendRead(BaseModel):
    stock_id: str
    symbol: str | None = None
    source: str
    session_scope: str = "regular"
    session_phase: str | None = None
    has_extended_hours: bool = False
    regular_point_count: int = 0
    extended_point_count: int = 0
    previous_close: float | None = None
    previous_close_source: str | None = None
    previous_close_trade_date: str | None = None
    previous_close_provider: str | None = None
    regular_session_close: float | None = None
    regular_session_close_time: str | None = None
    point_count: int
    points: list[JPIntradayTrendPointRead]
    source_url: str | None = None
    warnings: list[str] = Field(default_factory=list)


class JPMarketCoverageRead(BaseModel):
    scope: str
    active_stock_count: int
    observed_symbol_count: int
    current_symbol_count: int
    stale_symbol_count: int
    missing_symbol_count: int
    active_coverage_ratio: float
    observed_current_ratio: float
    status: str
    is_partial: bool


class JPMarketBreadthRead(BaseModel):
    trade_date: date | None = None
    advance_count: int
    decline_count: int
    unchanged_count: int
    no_comparison_count: int
    total_count: int
    coverage_count: int
    source: str
    is_partial: bool


class JPMarketSectorBreadthRead(BaseModel):
    sector: str
    covered_count: int
    advance_count: int
    decline_count: int
    unchanged_count: int
    average_change_pct: float | None = None


class JPMarketMoverRead(BaseModel):
    symbol: str
    security_name: str | None = None
    sector: str | None = None
    trade_date: date
    close: float
    previous_close: float
    change: float
    change_pct: float
    volume: int | None = None
    provider: str


class JPMarketIndexSnapshotRead(BaseModel):
    symbol: str
    label: str
    role: str
    latest_data_date: date | None = None
    expected_data_date: date | None = None
    freshness_status: str
    is_current: bool
    close: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    provider: str | None = None
    point_count: int = 0


class JPMarketOverviewRead(BaseModel):
    kind: str
    generated_at: datetime
    expected_trade_date: date
    calendar_status: dict[str, Any]
    coverage: JPMarketCoverageRead
    watchlist_coverage: dict[str, Any]
    breadth: JPMarketBreadthRead
    sectors: list[JPMarketSectorBreadthRead]
    indices: list[JPMarketIndexSnapshotRead]
    top_gainers: list[JPMarketMoverRead]
    top_losers: list[JPMarketMoverRead]
    source_health: dict[str, Any]
    refresh_recommended: bool
    refresh_scope: str
    warnings: list[str] = Field(default_factory=list)


class JPResourceSlotRead(BaseModel):
    key: str
    status: str
    available: bool
    source: str | None = None
    latest_date: date | None = None
    row_count: int = 0
    metrics: dict[str, int | float | str | None] = Field(default_factory=dict)


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


class JPWatchlistRankingItemRead(BaseModel):
    rank: int
    symbol: str
    security_name: str | None = None
    exchange: str | None = None
    market_segment: str | None = None
    sector_33_name: str | None = None
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
    latest_fetched_at: datetime | None = None
    freshness_status: str = "unknown"


class JPWatchlistRankingRead(BaseModel):
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
    missing_symbol_count: int = 0
    future_symbol_count: int = 0
    coverage_status: str = "unknown"
    refresh_recommended: bool = False
    results: list[JPWatchlistRankingItemRead]

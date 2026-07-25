from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class USStockMasterRead(BaseModel):
    id: int

    symbol: str
    security_name: str | None = None
    exchange: str | None = None
    asset_type: str
    listing_source: str

    market_category: str | None = None
    financial_status: str | None = None
    cqs_symbol: str | None = None
    nasdaq_symbol: str | None = None

    cik: str | None = None
    sec_company_name: str | None = None

    is_etf: bool | None = None
    is_test_issue: bool
    round_lot_size: int | None = None

    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class USSymbolSyncResultRead(BaseModel):
    status: str
    scanned_count: int
    created_count: int
    updated_count: int
    deactivated_count: int = 0
    missing_count: int = 0
    message: str


class USDailyPriceRead(BaseModel):
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
    dividend_amount: float | None = None
    split_coefficient: float | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class USDailyPriceRefreshResultRead(BaseModel):
    status: str
    provider: str
    symbol: str
    fetched_count: int
    inserted_count: int
    updated_count: int
    message: str


class USDailyPriceQualityRepairResultRead(BaseModel):
    status: str
    dry_run: bool
    symbol: str | None = None
    provider: str
    limit: int
    total_dirty_count: int
    candidate_count: int
    remaining_dirty_count: int
    affected_symbol_count: int
    deleted_count: int
    refreshed_symbol_count: int = 0
    refresh_error_count: int = 0
    affected_symbols: list[str] = Field(default_factory=list)
    sample_rows: list[dict] = Field(default_factory=list)
    refresh_results: list[dict] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    message: str


class USOhlcPointRead(BaseModel):
    time: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None


class USOhlcChartRead(BaseModel):
    symbol: str
    timeframe: str
    bars: int
    lookback_days: int
    from_date: date
    to_date: date
    point_count: int
    points: list[USOhlcPointRead]
    backfill: dict | None = None
    intraday_overlay: dict | None = None
    latest_data_date: date | None = None
    expected_data_date: date | None = None
    freshness_status: str = "missing"
    is_current: bool = False
    refresh_recommended: bool = True


class USIntradayTrendPointRead(BaseModel):
    time: str
    session: str = "regular"
    price: float
    volume: int | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None


class USIntradaySourceStatusRead(BaseModel):
    provider: str = "yahoo_chart"
    status: str = "unavailable"
    freshness_status: str = "missing"
    market_phase: str | None = None
    is_live_window: bool = False
    as_of: str | None = None
    lag_seconds: float | None = None
    is_fallback: bool = False
    has_usable_data: bool = False
    message: str | None = None


class USIntradayTrendRead(BaseModel):
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
    points: list[USIntradayTrendPointRead]
    volume_pace: dict | None = None
    source_status: USIntradaySourceStatusRead
    source_url: str | None = None
    warnings: list[str] = Field(default_factory=list)


class USSecCompanyFactRead(BaseModel):
    id: int

    fact_key: str
    cik: str
    symbol: str | None = None
    entity_name: str | None = None

    taxonomy: str
    tag: str
    label: str | None = None
    description: str | None = None
    unit: str

    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str | None = None
    filed_date: date | None = None
    period_start_date: date | None = None
    period_end_date: date | None = None
    accession_number: str | None = None
    frame: str | None = None

    value_numeric: float | None = None
    value_text: str | None = None

    source_url: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class USSecFactRefreshResultRead(BaseModel):
    status: str
    symbol: str
    cik: str
    fetched_count: int
    inserted_count: int
    updated_count: int
    message: str


class USSecFundamentalMetricRead(BaseModel):
    metric: str
    tag: str
    label: str | None = None
    unit: str

    value_numeric: float | None = None
    value_text: str | None = None

    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str | None = None
    filed_date: date | None = None
    period_start_date: date | None = None
    period_end_date: date | None = None
    accession_number: str | None = None
    source_url: str | None = None


class USSecFundamentalSummaryRead(BaseModel):
    symbol: str
    cik: str | None = None
    entity_name: str | None = None
    metric_count: int
    metrics: list[USSecFundamentalMetricRead]


class USCompanyProfileRead(BaseModel):
    id: int

    provider: str
    symbol: str
    company_name: str | None = None
    description: str | None = None

    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    currency: str | None = None

    market_cap: int | None = None
    ebitda: int | None = None
    pe_ratio: float | None = None
    peg_ratio: float | None = None
    beta: float | None = None
    dividend_yield: float | None = None
    eps: float | None = None
    revenue_ttm: int | None = None
    profit_margin: float | None = None

    fiscal_year_end: str | None = None
    latest_quarter: date | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class USCorporateActionRead(BaseModel):
    id: int

    provider: str
    symbol: str
    action_type: str
    event_date: date

    declaration_date: date | None = None
    record_date: date | None = None
    payment_date: date | None = None

    amount: float | None = None
    split_from: float | None = None
    split_to: float | None = None
    split_ratio: float | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class USShortVolumeDailyRead(BaseModel):
    id: int

    provider: str
    symbol: str
    trade_date: date
    market_center: str

    short_volume: int | None = None
    short_exempt_volume: int | None = None
    total_volume: int | None = None
    short_ratio: float | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MacroSeriesObservationRead(BaseModel):
    id: int

    provider: str
    series_id: str
    series_name: str | None = None
    observation_date: date
    value: float | None = None
    unit: str | None = None
    frequency: str | None = None

    source_url: str | None = None
    raw_payload_hash: str | None = None
    fetched_at: datetime

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class USResourceRefreshResultRead(BaseModel):
    status: str
    provider: str
    symbol: str | None = None
    trade_date: date | None = None
    series_id: str | None = None
    fetched_count: int
    inserted_count: int
    updated_count: int
    message: str


class USSourceHealthEntryRead(BaseModel):
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


class USSourceHealthSummaryRead(BaseModel):
    entry_count: int
    ok_count: int
    empty_count: int
    stale_count: int
    error_count: int


class USSourceHealthRead(BaseModel):
    kind: str
    generated_at: datetime
    filters: dict[str, str | None] = Field(default_factory=dict)
    expected_daily_price_date: date | None = None
    summary: USSourceHealthSummaryRead
    entries: list[USSourceHealthEntryRead] = Field(default_factory=list)


class USWatchlistGroupCreate(BaseModel):
    parent_id: int | None = None
    group_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 100
    is_active: bool = True


class USWatchlistGroupUpdate(BaseModel):
    parent_id: int | None = None
    group_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class USWatchlistGroupRead(BaseModel):
    id: int
    parent_id: int | None = None
    group_name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class USWatchlistGroupTreeRead(BaseModel):
    id: int
    parent_id: int | None = None
    group_name: str
    description: str | None = None
    sort_order: int
    is_active: bool
    children: list["USWatchlistGroupTreeRead"] = []


class USWatchlistGroupDeleteResultRead(BaseModel):
    deleted_group_id: int
    deleted_item_count: int
    deleted_group_count: int


class USWatchlistItemCreate(BaseModel):
    group_id: int
    symbol: str = Field(..., min_length=1, max_length=32)
    note: str | None = None
    priority: int = 100
    tags: str | None = None
    enabled: bool = True


class USWatchlistItemUpdate(BaseModel):
    group_id: int | None = None
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    note: str | None = None
    priority: int | None = None
    tags: str | None = None
    enabled: bool | None = None


class USWatchlistItemRead(BaseModel):
    id: int
    group_id: int
    symbol: str
    security_name: str | None = None
    exchange: str | None = None
    asset_type: str | None = None
    note: str | None = None
    priority: int
    tags: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class USWatchlistRankingItemRead(BaseModel):
    rank: int
    symbol: str
    security_name: str | None = None
    exchange: str | None = None
    asset_type: str | None = None
    group_id: int
    trade_date: date | None = None
    time: str | None = None
    session: str | None = None
    close: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    status: str
    source: str | None = None
    has_extended_hours: bool = False
    intraday_previous_close: float | None = None
    intraday_points: list[dict] = Field(default_factory=list)
    error_message: str | None = None


class USWatchlistRankingRead(BaseModel):
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
    results: list[USWatchlistRankingItemRead]

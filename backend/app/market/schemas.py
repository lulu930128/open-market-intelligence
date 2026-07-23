from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MarketCalendarReleaseWindowRead(BaseModel):
    key: str
    label: str
    release_time: str
    release_at: datetime
    next_release_at: datetime
    expected_trade_date: date | None = None
    status: str
    is_released: bool


class MarketCalendarSessionRead(BaseModel):
    preopen_time: str | None = None
    pre_market_open_time: str | None = None
    open_time: str
    close_time: str
    after_hours_close_time: str | None = None
    lunch_start_time: str | None = None
    lunch_end_time: str | None = None
    next_session_start_at: datetime
    is_polling_window: bool
    is_extended_polling_window: bool = False
    is_after_close: bool


class MarketCalendarMarketStatusRead(BaseModel):
    market: str
    timezone: str
    checked_at: datetime
    date: date
    is_trading_day: bool
    phase: str
    reason: str
    holiday_name: str | None = None
    previous_trading_day: date
    next_trading_day: date
    session: MarketCalendarSessionRead
    release_windows: dict[str, MarketCalendarReleaseWindowRead] = Field(default_factory=dict)
    calendar_source: str | None = None
    calendar_verified_years: list[int] = Field(default_factory=list)
    calendar_limit: str | None = None
    calendar_cache_status: str = "fallback"
    calendar_last_refreshed_at: datetime | None = None
    calendar_source_url: str | None = None
    calendar_warning: str | None = None


class MarketCalendarStatusRead(BaseModel):
    kind: str
    generated_at: datetime
    markets: dict[str, MarketCalendarMarketStatusRead] = Field(default_factory=dict)


class MarketCalendarRefreshResultRead(BaseModel):
    market: str
    status: str
    provider: str
    source_url: str | None = None
    fetched_at: datetime | None = None
    holiday_count: int = 0
    verified_years: list[int] = Field(default_factory=list)
    error_message: str | None = None


class MarketCalendarRefreshRead(BaseModel):
    kind: str
    started_at: datetime
    completed_at: datetime
    requested_markets: list[str] = Field(default_factory=list)
    request_limit: int
    success_count: int
    error_count: int
    results: dict[str, MarketCalendarRefreshResultRead] = Field(default_factory=dict)


class TaiwanDispositionSecurityRead(BaseModel):
    provider: str
    market: str
    source_url: str
    announced_date: date | None = None
    stock_id: str
    stock_name: str | None = None
    start_date: date
    end_date: date
    matching_interval_minutes: int | None = None
    reason: str | None = None
    measure: str | None = None
    requires_full_precollection: bool = False
    margin_trading_suspended: bool = False
    detail: str | None = None
    status: str
    is_active: bool


class TaiwanDispositionStatusRead(BaseModel):
    stock_id: str
    checked_at: datetime
    is_disposition: bool
    is_active: bool
    status: str
    cache_status: str
    cache_fetched_at: datetime | None = None
    warning: str | None = None
    provider: str | None = None
    market: str | None = None
    source_url: str | None = None
    announced_date: date | None = None
    stock_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    matching_interval_minutes: int | None = None
    reason: str | None = None
    measure: str | None = None
    requires_full_precollection: bool = False
    margin_trading_suspended: bool = False
    detail: str | None = None


class TaiwanDispositionSourceStatusRead(BaseModel):
    provider: str
    market: str
    source: str
    source_url: str
    status: str
    fetched_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    warning: str | None = None
    entry_count: int = 0


class TaiwanDispositionListRead(BaseModel):
    kind: str
    generated_at: datetime
    as_of: date
    active_count: int
    upcoming_count: int
    result_count: int
    sources: dict[str, TaiwanDispositionSourceStatusRead] = Field(default_factory=dict)
    results: list[TaiwanDispositionSecurityRead] = Field(default_factory=list)


class TaiwanDispositionRefreshProviderRead(BaseModel):
    provider: str
    market: str
    status: str
    entry_count: int
    source_url: str
    error_message: str | None = None


class TaiwanDispositionRefreshRead(BaseModel):
    kind: str
    started_at: datetime
    completed_at: datetime
    request_limit: int
    success_count: int
    error_count: int
    active_count: int
    upcoming_count: int
    results: dict[str, TaiwanDispositionRefreshProviderRead] = Field(default_factory=dict)


class TaiwanCorporateEventRead(BaseModel):
    event_id: str
    event_type: str
    timing_status: str
    provider: str
    market: str
    source_name: str
    source_url: str
    stock_id: str
    stock_name: str | None = None
    start_date: date
    end_date: date
    start_time: str | None = None
    title: str
    summary: str | None = None
    location: str | None = None
    cash_dividend: float | None = None
    stock_dividend_ratio: float | None = None
    financial_report_related: bool = False
    related_event_id: str | None = None
    company_url: str | None = None
    video_url: str | None = None
    status: str
    days_until: int


class TaiwanCorporateEventWindowFailureRead(BaseModel):
    provider: str
    market: str
    window: str
    stage: str
    status: str
    exception_type: str
    attempt_count: int
    retryable: bool
    message: str
    http_status_code: int | None = None
    rate_limited: bool = False
    retry_after_seconds: int | None = None


class TaiwanCorporateEventSourceStatusRead(BaseModel):
    provider: str
    market: str
    source: str
    source_url: str
    status: str
    fetched_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    last_failure_details: list[TaiwanCorporateEventWindowFailureRead] = Field(
        default_factory=list
    )
    partial_success: bool = False
    successful_windows: list[str] = Field(default_factory=list)
    recovered_windows: list[str] = Field(default_factory=list)
    retry_count: int = 0
    warning: str | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None
    entry_count: int = 0


class TaiwanCorporateEventListRead(BaseModel):
    kind: str
    generated_at: datetime
    as_of: date
    date_from: date
    date_to: date
    stock_id: str | None = None
    market: str | None = None
    event_types: list[str] = Field(default_factory=list)
    result_count: int
    warning: str | None = None
    sources: dict[str, TaiwanCorporateEventSourceStatusRead] = Field(default_factory=dict)
    results: list[TaiwanCorporateEventRead] = Field(default_factory=list)


class TaiwanStockEventSummaryRead(BaseModel):
    stock_id: str
    checked_at: datetime
    reminder_days: int
    cache_status: str
    cache_fetched_at: datetime | None = None
    warning: str | None = None
    result_count: int
    results: list[TaiwanCorporateEventRead] = Field(default_factory=list)


class TaiwanStockEventHistoryRead(BaseModel):
    stock_id: str
    checked_at: datetime
    history_years: int
    cache_status: str
    cache_fetched_at: datetime | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None
    warning: str | None = None
    total_count: int
    result_count: int
    results: list[TaiwanCorporateEventRead] = Field(default_factory=list)


class TaiwanCorporateEventRefreshProviderRead(BaseModel):
    provider: str
    market: str
    status: str
    entry_count: int
    request_count: int
    retry_count: int = 0
    successful_windows: list[str] = Field(default_factory=list)
    recovered_windows: list[str] = Field(default_factory=list)
    failure_details: list[TaiwanCorporateEventWindowFailureRead] = Field(
        default_factory=list
    )
    source_url: str
    error_message: str | None = None


class TaiwanCorporateEventRefreshRead(BaseModel):
    kind: str
    started_at: datetime
    completed_at: datetime
    request_limit: int
    request_count: int
    success_count: int
    partial_count: int = 0
    error_count: int
    event_count: int
    results: dict[str, TaiwanCorporateEventRefreshProviderRead] = Field(default_factory=dict)


class TaiwanSourceHealthEntryRead(BaseModel):
    resource: str
    label: str
    frequency: str
    target: str
    status: str
    ok: bool
    row_count: int
    required: bool = True
    latest_data_date: date | None = None
    latest_data_key: str | None = None
    latest_updated_at: datetime | None = None
    expected_data_date: date | None = None
    freshness_lag_days: int | None = None
    release_status: str | None = None
    release_is_released: bool | None = None
    data_quality: str
    reason: str
    provider: str | None = None
    source: str | None = None
    latest_observed_at: datetime | None = None
    age_seconds: int | None = None
    stale_after_seconds: int | None = None
    latest_event_id: int | None = None
    latest_event_at: datetime | None = None
    latest_event_status: str | None = None
    latest_event_severity: str | None = None
    latest_event_message: str | None = None
    recent_event_count: int = 0
    recent_error_count: int = 0
    consecutive_error_count: int = 0


class TaiwanSourceHealthSummaryRead(BaseModel):
    entry_count: int
    ok_count: int
    empty_count: int
    stale_count: int
    not_applicable_count: int
    error_count: int


class TaiwanSourceHealthRead(BaseModel):
    kind: str
    generated_at: datetime
    filters: dict[str, str | None] = Field(default_factory=dict)
    market_calendar: dict[str, Any] = Field(default_factory=dict)
    summary: TaiwanSourceHealthSummaryRead
    entries: list[TaiwanSourceHealthEntryRead] = Field(default_factory=list)


class MarketDailyPriceRead(BaseModel):
    id: int

    source_id: int
    raw_result_id: int

    trade_date: date

    stock_id: str
    stock_name: str | None = None

    trade_volume: int | None = None
    trade_value: int | None = None

    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None

    price_change: float | None = None
    transaction_count: int | None = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ParseTwseDailyResultRead(BaseModel):
    raw_result_id: int
    source_id: int
    parser_type: str
    status: str

    parsed_count: int
    skipped_count: int
    inserted_count: int
    replaced_trade_dates: list[date]

    message: str | None = None


class MarketDailyChartRead(BaseModel):
    time: date

    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None

    volume: int | None = None
    trade_value: int | None = None
    transaction_count: int | None = None


class TwseBackfillMonthRead(BaseModel):
    month: str
    url: str

    fetch_log_id: int | None = None
    raw_result_id: int | None = None

    http_status_code: int | None = None
    data_quality_status: str | None = None
    data_quality_message: str | None = None
    row_count: int | None = None

    parsed_count: int = 0
    skipped_count: int = 0

    status: str
    error_message: str | None = None


class TwseBackfillResultRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    source_id: int

    start_date: date
    end_date: date

    requested_month_count: int
    fetched_month_count: int
    skipped_existing_month_count: int = 0

    parsed_count: int
    inserted_count: int
    skipped_count: int

    status: str
    message: str

    months: list[TwseBackfillMonthRead]


class MarketOhlcChartRead(BaseModel):
    stock_id: str
    timeframe: str
    bars: int
    lookback_days: int
    from_date: date
    to_date: date
    point_count: int
    points: list[MarketDailyChartRead]
    backfill: dict | None = None
    intraday_overlay: dict[str, Any] | None = None
    latest_data_date: date | None = None
    expected_data_date: date | None = None
    freshness_status: str = "missing"
    is_current: bool = False
    refresh_recommended: bool = True


class ChartDrawingSnapshotWrite(BaseModel):
    label: str | None = None
    time_mode: str | None = None
    selected_drawing_id: str | None = None
    drawings: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None
    source: str = "frontend"


class ChartDrawingSnapshotRead(BaseModel):
    id: int
    market: str
    symbol: str
    timeframe: str
    label: str | None = None
    time_mode: str | None = None
    selected_drawing_id: str | None = None
    drawing_count: int
    drawings: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None
    source: str
    created_at: datetime
    updated_at: datetime


class MarketBreadthRead(BaseModel):
    market: str
    scope: str | None = None
    label: str | None = None
    trade_date: date | None = None
    as_of: datetime | None = None
    advance_count: int
    decline_count: int
    unchanged_count: int
    total_count: int
    limit_up_count: int | None = None
    limit_down_count: int | None = None
    trade_value: int | None = None
    coverage_count: int | None = None
    unknown_count: int | None = None
    message_count: int | None = None
    missing_count: int | None = None
    warnings: list[str] = Field(default_factory=list)
    source: str | None = None


class MarketBreadthStatusRead(BaseModel):
    slot: str = "market_breadth"
    status: str
    scope: str | None = None
    source: str | None = None
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class MarketIndexSnapshotRead(BaseModel):
    index_id: str
    label: str
    short_label: str
    market: str
    symbol: str
    source: str
    as_of: datetime | None = None
    time: date | None = None

    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    estimated_volume: int | None = None
    trade_value: int | None = None
    estimated_trade_value: int | None = None

    ma20: float | None = None
    price_vs_ma20: float | None = None
    point_count: int = 0
    points: list[MarketDailyChartRead] = Field(default_factory=list)
    breadth: MarketBreadthRead | None = None
    breadth_status: MarketBreadthStatusRead
    error_message: str | None = None


class MarketIndexSummaryRead(BaseModel):
    as_of: datetime
    source: str
    indices: list[MarketIndexSnapshotRead]
    cache_status: str = "unknown"
    refresh_recommended: bool = False
    warnings: list[str] = Field(default_factory=list)


class TaiwanMarketVolumeBaselineRead(BaseModel):
    requested_days: int
    sample_days: int
    median_cumulative_trade_value: int | None = None
    pace_ratio: float | None = None


class TaiwanMarketVolumeMarketRead(BaseModel):
    market: str
    index_id: str
    cumulative_trade_value: int | None = None
    estimated_full_day_trade_value: int | None = None
    advance_count: int | None = None
    decline_count: int | None = None
    unchanged_count: int | None = None
    total_count: int | None = None
    session_status: str
    quality_status: str
    source: str
    source_category: str
    official_flag: bool
    derived_flag: bool


class TaiwanMarketVolumeStateRead(BaseModel):
    kind: str
    generated_at: datetime
    as_of: datetime | None = None
    trade_date: date | None = None
    status: str
    session_status: str
    comparison_minute: str | None = None
    calculation_basis: str | None = None
    current_cumulative_trade_value: int | None = None
    previous_minute_cumulative_trade_value: int | None = None
    one_minute_trade_value_change: int | None = None
    same_time_baseline_5d: TaiwanMarketVolumeBaselineRead
    same_time_baseline_20d: TaiwanMarketVolumeBaselineRead
    history_trade_dates: list[str] = Field(default_factory=list)
    markets: list[TaiwanMarketVolumeMarketRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MarketIndexDailyStatRefreshRead(BaseModel):
    status: str
    index_id: str
    market: str
    source: str | None = None
    requested_month_count: int
    fetched_month_count: int
    skipped_existing_month_count: int
    inserted_count: int
    updated_count: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    message: str


class MarketChipResourceStatusRead(BaseModel):
    resource: str
    status: str
    data_date: date | None = None
    expected_data_date: date | None = None
    pending_trade_date: date | None = None
    source: str | None = None
    reason: str | None = None
    coverage_count: int | None = None
    total_count: int | None = None
    warnings: list[str] = Field(default_factory=list)


class MarketChipDailyRead(BaseModel):
    id: int
    index_id: str
    market: str
    trade_date: date

    close_value: float | None = None
    price_change: float | None = None
    price_change_pct: float | None = None
    trade_value: int | None = None

    foreign_futures_net_oi: int | None = None
    foreign_futures_net_oi_change: int | None = None
    retail_futures_net_oi: int | None = None
    retail_futures_net_oi_change: int | None = None

    put_volume: int | None = None
    call_volume: int | None = None
    put_call_volume_ratio_pct: float | None = None
    put_open_interest: int | None = None
    call_open_interest: int | None = None
    put_call_open_interest_ratio_pct: float | None = None

    total_institutional_net_value: int | None = None
    foreign_investor_net_value: int | None = None
    investment_trust_net_value: int | None = None
    dealer_net_value: int | None = None
    dealer_self_net_value: int | None = None
    dealer_hedge_net_value: int | None = None
    government_bank_net_value: int | None = None

    margin_balance_change_value: int | None = None
    margin_balance_change_shares: int | None = None
    short_balance_change_shares: int | None = None
    margin_status: MarketChipResourceStatusRead
    government_bank_status: MarketChipResourceStatusRead

    source_grade: str
    source_details: dict[str, Any] | None = None

    created_at: datetime
    updated_at: datetime


class MarketIndexListItemRead(BaseModel):
    rank: int
    market: str
    name: str
    close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    trade_date: date | None = None


class MarketIndexListRead(BaseModel):
    market: str
    source: str
    as_of: datetime
    count: int
    items: list[MarketIndexListItemRead]


class MarketIndexContributionItemRead(BaseModel):
    rank: int
    stock_id: str
    stock_name: str | None = None
    close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    contribution_points: float | None = None
    market_value_change: float | None = None
    trade_value: int | None = None


class MarketIndexContributionRead(BaseModel):
    index_id: str
    market: str
    source: str
    method: str
    as_of: datetime
    trade_date: date | None = None
    index_close: float | None = None
    index_change: float | None = None
    total_market_value: float | None = None
    positive: list[MarketIndexContributionItemRead]
    negative: list[MarketIndexContributionItemRead]


class IntradayTrendPointRead(BaseModel):
    time: str
    price: float
    volume: int | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None


class IntradayTrendRead(BaseModel):
    stock_id: str
    symbol: str | None = None
    source: str
    source_provenance: dict[str, Any] | None = None
    previous_close: float | None = None
    point_count: int
    trading_mode: str = "continuous"
    analysis_basis: str = "time_bars"
    batch_interval_minutes: int | None = None
    disposition_start_date: date | None = None
    disposition_end_date: date | None = None
    effective_match_count: int | None = None
    points: list[IntradayTrendPointRead]


class TaiwanStockQuoteDepthLevelRead(BaseModel):
    level: int
    price: float | None = None
    size_lots: int | None = None


class TaiwanStockQuoteDepthFreshnessRead(BaseModel):
    status: str
    is_live: bool
    is_stale: bool
    age_seconds: int | None = None
    fetch_age_seconds: int | None = None
    expected_trade_date: date | None = None
    message: str
    source_error: str | None = None
    source_error_detail: dict[str, Any] | None = None


class TaiwanStockQuoteDepthRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    market: str | None = None
    provider: str
    source: str
    source_url: str | None = None
    exchange_channel: str | None = None
    session_phase: str
    market_status: str
    phase_label: str
    timezone: str | None = None
    session_start: str | None = None
    session_end: str | None = None
    holiday_name: str | None = None
    trade_date: date | None = None
    quote_time: datetime | None = None
    fetched_at: datetime | None = None

    last_price: float | None = None
    previous_close: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    total_volume_lots: int | None = None

    best_bid_price: float | None = None
    best_bid_size_lots: int | None = None
    best_ask_price: float | None = None
    best_ask_size_lots: int | None = None
    bid_total_size_lots: int | None = None
    ask_total_size_lots: int | None = None
    spread: float | None = None
    spread_pct: float | None = None

    bid_levels: list[TaiwanStockQuoteDepthLevelRead]
    ask_levels: list[TaiwanStockQuoteDepthLevelRead]
    depth_available: bool
    refresh_outcome: str = "not_attempted"
    freshness: TaiwanStockQuoteDepthFreshnessRead


class MarketIntradayChartPointRead(BaseModel):
    time: datetime

    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None

    volume: int | None = None
    trade_value: int | None = None
    transaction_count: int | None = None


class MarketIntradayChartRead(BaseModel):
    stock_id: str
    symbol: str | None = None
    interval: str
    range: str
    provider: str
    source: str
    from_time: datetime | None = None
    to_time: datetime | None = None
    point_count: int
    cached_count: int
    refreshed_count: int
    trading_mode: str = "continuous"
    analysis_basis: str = "time_bars"
    batch_interval_minutes: int | None = None
    disposition_start_date: date | None = None
    disposition_end_date: date | None = None
    effective_match_count: int | None = None
    points: list[MarketIntradayChartPointRead]


class TaiwanFuturesProductRead(BaseModel):
    symbol: str
    product_code: str
    product_name: str
    official_code: str
    taifex_cid: str
    multiplier: int
    tick_size: float
    underlying_index_id: str
    regular_session: str
    after_hours_session: str


class TaiwanFuturesMarketStatusRead(BaseModel):
    status: str
    is_open: bool
    phase: str
    reason: str
    timezone: str
    checked_at: datetime
    holiday_name: str | None = None
    regular_session: str
    after_hours_session: str
    current_session: str | None = None
    current_session_start_at: datetime | None = None
    current_session_end_at: datetime | None = None
    last_session: str | None = None
    last_session_start_at: datetime | None = None
    last_session_end_at: datetime | None = None
    next_session: str | None = None
    next_session_start_at: datetime | None = None
    next_session_end_at: datetime | None = None


class TaiwanFuturesQuoteFreshnessRead(BaseModel):
    status: str
    is_live: bool
    is_stale: bool
    is_session_mismatch: bool
    expected_session: str
    age_seconds: int | None = None
    message: str
    source_error: str | None = None
    last_session_quote_lag_seconds: int | None = None
    market_status: TaiwanFuturesMarketStatusRead


class TaiwanFuturesQuoteRead(BaseModel):
    id: int
    provider: str
    market: str
    symbol: str
    product_code: str
    product_name: str
    contract_symbol: str
    contract_month: str | None = None
    session: str
    trade_date: date | None = None
    quote_time: datetime

    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    last_price: float | None = None
    reference_price: float | None = None
    settlement_price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    amplitude_pct: float | None = None

    total_volume: int | None = None
    open_interest: int | None = None
    bid_price: float | None = None
    bid_size: int | None = None
    ask_price: float | None = None
    ask_size: int | None = None

    source: str
    source_url: str | None = None
    fetched_at: datetime
    freshness: TaiwanFuturesQuoteFreshnessRead
    created_at: datetime
    updated_at: datetime


class TaiwanFuturesIntradayBarRead(BaseModel):
    id: int
    provider: str
    market: str
    symbol: str
    product_code: str
    product_name: str
    contract_symbol: str
    contract_month: str | None = None
    session: str
    interval: str
    bar_time: datetime

    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    total_volume: int | None = None
    open_interest: int | None = None

    source: str
    source_url: str | None = None
    created_at: datetime
    updated_at: datetime


class TaiwanFuturesDailyBarRead(BaseModel):
    id: int
    provider: str
    market: str
    symbol: str
    product_code: str
    product_name: str
    contract_symbol: str
    contract_month: str
    trade_date: date

    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    settlement_price: float | None = None
    change: float | None = None
    change_pct: float | None = None

    after_hours_volume: int | None = None
    regular_volume: int | None = None
    total_volume: int | None = None
    open_interest: int | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    historical_high_price: float | None = None
    historical_low_price: float | None = None

    source: str
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class TaiwanFuturesDailyRefreshRead(BaseModel):
    status: str
    symbol: str
    requested_end_date: date
    effective_end_date: date
    latest_released_trade_date: date
    release_time: str
    skipped_unreleased_end_date: bool = False
    refreshed_row_count: int = 0
    warning: str | None = None
    rows: list[TaiwanFuturesDailyBarRead] = Field(default_factory=list)


class TaiwanOptionChainDailyRead(BaseModel):
    id: int
    provider: str
    trade_date: date
    product_code: str
    contract_month: str
    expiry_date: date | None = None
    strike_price: float
    option_type: str
    session: str
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    close_price: float | None = None
    settlement_price: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    historical_high_price: float | None = None
    historical_low_price: float | None = None
    official_delta: float | None = None
    implied_volatility_pct: float | None = None
    gamma: float | None = None
    vega_per_vol_pct: float | None = None
    theta_per_day: float | None = None
    spot_reference: float | None = None
    pricing_source: str | None = None
    calculation_model: str | None = None
    calculation_status: str
    risk_free_rate: float | None = None
    dividend_yield: float | None = None
    source: str
    source_url: str | None = None
    delta_source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TaiwanDerivativesLargeTraderDailyRead(BaseModel):
    id: int
    provider: str
    trade_date: date
    instrument_type: str
    contract_code: str
    contract_name: str | None = None
    option_type: str
    settlement_bucket: str
    trader_type: str
    top5_buy: int | None = None
    top5_sell: int | None = None
    top10_buy: int | None = None
    top10_sell: int | None = None
    market_open_interest: int | None = None
    top5_buy_concentration_pct: float | None = None
    top5_sell_concentration_pct: float | None = None
    top10_buy_concentration_pct: float | None = None
    top10_sell_concentration_pct: float | None = None
    source: str
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class TaiwanFuturesTermStructureDailyRead(BaseModel):
    id: int
    provider: str
    trade_date: date
    symbol: str
    product_code: str
    contract_month: str
    expiry_date: date | None = None
    last_price: float | None = None
    settlement_price: float | None = None
    open_interest: int | None = None
    spot_close: float | None = None
    basis_points: float | None = None
    basis_pct: float | None = None
    annualized_basis_pct: float | None = None
    calculation_status: str
    source: str
    source_url: str | None = None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TaiwanDerivativesRefreshRead(BaseModel):
    status: str
    as_of: date | None = None
    expected_trade_date: date
    is_stale: bool
    dataset_trade_dates: dict[str, date | None] = Field(default_factory=dict)
    stale_datasets: list[str] = Field(default_factory=list)
    unverified_date_datasets: list[str] = Field(default_factory=list)
    provider: str
    provider_request_count: int
    successful_request_count: int
    failed_request_count: int
    counts: dict[str, int]
    calculation: dict[str, Any]
    errors: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class TechnicalReportRowRead(BaseModel):
    key: str
    label: str
    description: str
    value: Any = None
    display_value: str
    direction: float | None = None
    tone: str = "neutral"
    basis: str
    source: str


class TechnicalReportBadgeRead(BaseModel):
    label: str
    tone: str


class TechnicalReportRead(BaseModel):
    kind: str
    stock_id: str
    timeframe: str
    phase: str
    confidence: str
    generated_at: datetime
    title: str
    summary: str
    score: int
    value: float | None = None
    value_label: str
    rows: list[TechnicalReportRowRead]
    badges: list[TechnicalReportBadgeRead] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, str]] = Field(default_factory=list)


class OvernightImpactSymbolMoveRead(BaseModel):
    symbol: str
    change_pct: float | None = None


class OvernightImpactFactorRead(BaseModel):
    key: str
    symbol: str
    label: str
    role: str
    trade_date: date | None = None
    close: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    score_change_pct: float | None = None
    weight: float
    normalized_weight: float | None = None
    weighted_contribution: float | None = None
    tone: str = "neutral"
    source: str
    provider: str | None = None


class OvernightImpactBasketRead(BaseModel):
    group_id: int
    group_name: str
    role: str
    trade_date: date | None = None
    symbol_count: int
    valid_count: int
    missing_count: int = 0
    average_change_pct: float | None = None
    score_change_pct: float | None = None
    weight: float
    normalized_weight: float | None = None
    weighted_contribution: float | None = None
    tone: str = "neutral"
    top_symbols: list[OvernightImpactSymbolMoveRead] = Field(default_factory=list)
    bottom_symbols: list[OvernightImpactSymbolMoveRead] = Field(default_factory=list)
    source: str


class OvernightImpactMappingRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    market: str | None = None
    industry: str | None = None
    category: str | None = None
    profiles: list[str] = Field(default_factory=list)
    reason: str


class AdrParityMappingRead(BaseModel):
    stock_id: str
    stock_name: str
    adr_symbol: str
    adr_name: str
    adr_exchange: str
    local_shares_per_adr: int
    source_label: str
    source_url: str
    verified_on: date


class AdrParityRead(BaseModel):
    kind: str
    status: str
    is_current: bool
    stock_id: str
    stock_name: str | None = None
    mapping: AdrParityMappingRead
    formula: str
    adr_close_usd: float | None = None
    adr_trade_date: date | None = None
    adr_provider: str | None = None
    expected_adr_trade_date: date | None = None
    usd_twd: float | None = None
    fx_source_symbol: str | None = None
    fx_provider: str | None = None
    fx_as_of: datetime | None = None
    fx_age_seconds: int | None = None
    tw_reference_price_twd: float | None = None
    tw_reference_trade_date: date | None = None
    target_tw_trade_date: date | None = None
    implied_tw_price_twd: float | None = None
    implied_gap_pct: float | None = None
    parity_adr_price_usd: float | None = None
    tw_comparison_price_twd: float | None = None
    tw_comparison_trade_date: date | None = None
    tw_comparison_as_of: datetime | None = None
    tw_comparison_source: str | None = None
    tw_session_phase: str | None = None
    comparison_mode: str
    remaining_gap_pct: float | None = None
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    freshness: dict[str, Any] = Field(default_factory=dict)


class FxTrendRead(BaseModel):
    status: str
    source_symbol: str | None = None
    provider: str | None = None
    usd_twd: float | None = None
    data_date: date | None = None
    as_of: datetime | None = None
    age_seconds: int | None = None
    history_points: int = 0
    usd_twd_change_1d_pct: float | None = None
    usd_twd_change_5d_pct: float | None = None
    usd_twd_change_20d_pct: float | None = None
    twd_change_1d_pct: float | None = None
    twd_change_5d_pct: float | None = None
    twd_change_20d_pct: float | None = None
    regime: str


class ForeignFlowWindowRead(BaseModel):
    days: int
    available_days: int
    net_value_twd: int | None = None
    turnover_twd: int | None = None
    turnover_ratio_pct: float | None = None
    net_shares: int | None = None


class ForeignFlowRead(BaseModel):
    scope: str
    status: str
    state: str
    state_basis_days: int | None = None
    trade_date: date | None = None
    expected_trade_date: date
    windows: list[ForeignFlowWindowRead] = Field(default_factory=list)


class FxFlowContextRead(BaseModel):
    kind: str
    status: str
    is_current: bool
    stock_id: str
    signal: str
    signal_horizon_days: int
    causality: str
    fx: FxTrendRead
    market_foreign: ForeignFlowRead
    stock_foreign: ForeignFlowRead
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    freshness: dict[str, Any] = Field(default_factory=dict)


class OvernightImpactRead(BaseModel):
    kind: str
    stock_id: str
    stock_name: str | None = None
    as_of: date | None = None
    generated_at: datetime
    stance: str
    title: str
    summary: str
    score: int
    weighted_change_pct: float | None = None
    confidence: str
    tw_mapping: OvernightImpactMappingRead
    adr_parity: AdrParityRead | None = None
    fx_flow_context: FxFlowContextRead | None = None
    factors: list[OvernightImpactFactorRead] = Field(default_factory=list)
    baskets: list[OvernightImpactBasketRead] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    freshness: dict[str, Any] = Field(default_factory=dict)
    evidence_passport: dict[str, Any] = Field(default_factory=dict)


class DailyIndicatorPointRead(BaseModel):
    time: date

    close: float | None = None
    volume: int | None = None

    change: float | None = None
    change_pct: float | None = None

    ma: dict[str, float | None]
    volume_ma: dict[str, float | None]
    ema: dict[str, float | None] = Field(default_factory=dict)
    macd: dict[str, float | None] = Field(default_factory=dict)
    rsi: dict[str, float | None] = Field(default_factory=dict)
    atr: dict[str, float | None] = Field(default_factory=dict)
    adx: dict[str, float | None] = Field(default_factory=dict)
    roc: dict[str, float | None] = Field(default_factory=dict)
    mfi: dict[str, float | None] = Field(default_factory=dict)
    donchian: dict[str, float | None] = Field(default_factory=dict)
    bollinger: dict[str, float | None] = Field(default_factory=dict)
    kd: dict[str, float | None] = Field(default_factory=dict)
    support_resistance: dict[str, float | None] = Field(default_factory=dict)


class InstitutionalTradeDailyRead(BaseModel):
    id: int
    source_id: int
    raw_result_id: int
    trade_date: date
    stock_id: str
    stock_name: str | None = None
    foreign_investor_buy: int | None = None
    foreign_investor_sell: int | None = None
    foreign_investor_net: int | None = None
    foreign_dealer_buy: int | None = None
    foreign_dealer_sell: int | None = None
    foreign_dealer_net: int | None = None
    investment_trust_buy: int | None = None
    investment_trust_sell: int | None = None
    investment_trust_net: int | None = None
    dealer_self_buy: int | None = None
    dealer_self_sell: int | None = None
    dealer_self_net: int | None = None
    dealer_hedge_buy: int | None = None
    dealer_hedge_sell: int | None = None
    dealer_hedge_net: int | None = None
    dealer_buy: int | None = None
    dealer_sell: int | None = None
    dealer_net: int | None = None
    total_institutional_net: int | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class InstitutionalHoldingRatioPointRead(BaseModel):
    trade_date: date
    foreign_investor_ratio: float | None = None
    investment_trust_ratio: float | None = None
    dealer_ratio: float | None = None


class InstitutionalHoldingRatioRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    trade_date: date | None = None
    foreign_investor_ratio: float | None = None
    investment_trust_ratio: float | None = None
    dealer_ratio: float | None = None
    source_name: str
    source_url: str
    fetched_at: datetime
    history: list[InstitutionalHoldingRatioPointRead] = []


class MarginTradingDailyRead(BaseModel):
    id: int
    source_id: int
    raw_result_id: int
    trade_date: date
    stock_id: str
    stock_name: str | None = None
    margin_buy: int | None = None
    margin_sell: int | None = None
    margin_cash_repayment: int | None = None
    margin_previous_balance: int | None = None
    margin_today_balance: int | None = None
    margin_next_limit: int | None = None
    short_covering: int | None = None
    short_sale: int | None = None
    short_stock_repayment: int | None = None
    short_previous_balance: int | None = None
    short_today_balance: int | None = None
    short_next_limit: int | None = None
    offset: int | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class StockChipCoverageRead(BaseModel):
    stock_id: str
    shareholding_latest_date: date | None = None
    shareholding_week_count: int = 0
    shareholding_row_count: int = 0
    margin_latest_trade_date: date | None = None
    margin_row_count: int = 0
    has_shareholding: bool = False
    has_margin: bool = False


class BrokerBranchTradeDailyRead(BaseModel):
    id: int
    source_id: int
    raw_result_id: int
    trade_date: date
    stock_id: str
    stock_name: str | None = None
    branch_code: str
    branch_name: str
    buy_lots: int | None = None
    sell_lots: int | None = None
    net_lots: int | None = None
    buy_avg_price: float | None = None
    sell_avg_price: float | None = None
    buy_rank: int | None = None
    sell_rank: int | None = None
    source_label: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BrokerBranchTradeDailySummaryRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    trade_date: date | None = None
    source_name: str | None = None
    source_url: str
    source_label: str | None = None
    is_latest: bool = False
    requested_days: int = 1
    available_days: int = 0
    trade_dates: list[date] = Field(default_factory=list)
    is_partial: bool = False
    row_count: int = 0
    buy_top: list[BrokerBranchTradeDailyRead] = Field(default_factory=list)
    sell_top: list[BrokerBranchTradeDailyRead] = Field(default_factory=list)


class ShareholdingDistributionWeeklyRead(BaseModel):
    id: int
    source_id: int
    raw_result_id: int
    data_date: date
    stock_id: str
    stock_name: str | None = None
    holding_level: str
    holding_level_order: int | None = None
    holder_count: int | None = None
    share_count: int | None = None
    share_ratio: float | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MonthlyRevenueRead(BaseModel):
    id: int
    source_id: int
    raw_result_id: int
    report_date: date | None = None
    period: date
    stock_id: str
    stock_name: str | None = None
    market: str | None = None
    industry: str | None = None
    monthly_revenue: int | None = None
    previous_month_revenue: int | None = None
    previous_year_month_revenue: int | None = None
    month_over_month_pct: float | None = None
    year_over_year_pct: float | None = None
    cumulative_revenue: int | None = None
    previous_year_cumulative_revenue: int | None = None
    cumulative_year_over_year_pct: float | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FinancialMetricQuarterlyRead(BaseModel):
    id: int
    source_id: int
    raw_result_id: int
    report_date: date | None = None
    released_at: date | None = None
    filed_at: date | None = None
    fiscal_year: int
    quarter: int
    period: str
    stock_id: str
    stock_name: str | None = None
    market: str | None = None
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    net_income_attributable_parent: float | None = None
    eps: float | None = None
    total_assets: float | None = None
    total_equity: float | None = None
    parent_equity: float | None = None
    book_value_per_share: float | None = None
    roe: float | None = None
    roa: float | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

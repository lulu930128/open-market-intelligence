from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class MarketBreadthRead(BaseModel):
    market: str
    trade_date: date | None = None
    advance_count: int
    decline_count: int
    unchanged_count: int
    total_count: int
    limit_up_count: int | None = None
    limit_down_count: int | None = None
    trade_value: int | None = None
    source: str | None = None


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
    error_message: str | None = None


class MarketIndexSummaryRead(BaseModel):
    as_of: datetime
    source: str
    indices: list[MarketIndexSnapshotRead]


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
    previous_close: float | None = None
    point_count: int
    points: list[IntradayTrendPointRead]


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
    points: list[MarketIntradayChartPointRead]


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

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.market.schemas import MarketOhlcChartRead, TechnicalReportRead


class TaiwanDashboardSessionRead(BaseModel):
    phase: str
    presentation_state: str
    trade_date: date
    is_current_trading_day: bool
    next_transition_at: datetime


class TaiwanDashboardFreshnessRead(BaseModel):
    status: str
    cache_only: Literal[True] = True
    oldest_as_of: datetime | None = None
    newest_as_of: datetime | None = None
    max_age_seconds: int | None = None
    source: str


class TaiwanDashboardBreadthRead(BaseModel):
    market: str
    status: str
    session_phase: str
    price_semantics: str
    provisional: bool
    decision_usable: bool
    universe: int
    coverage: int
    advance: int
    decline: int
    unchanged: int
    unknown: int
    coverage_ratio: float
    as_of: datetime | None = None
    warnings: list[str] = Field(default_factory=list)


class TaiwanDashboardIndexEstimateRead(BaseModel):
    index_id: str
    market: str
    status: str
    estimate: float | None = None
    change: float | None = None
    change_pct: float | None = None
    baseline_close: float | None = None
    baseline_trade_date: date | None = None
    component_universe_count: int
    eligible_component_count: int
    observed_component_count: int
    component_data_coverage_ratio: float
    observed_weight: float | None = None
    uncovered_weight: float | None = None
    constituent_as_of: date | None = None
    shares_as_of: date | None = None
    divisor_adjustment_status: str
    methodology_version: str
    component_universe_source: str
    provisional: Literal[True] = True
    official: Literal[False] = False
    decision_usable: Literal[False] = False
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TaiwanDashboardGroupRead(BaseModel):
    group_id: str
    group_key: str | None = None
    label: str
    market: str
    status: str
    universe: int
    coverage: int
    unknown: int
    coverage_ratio: float
    advance_ratio: float | None = None
    mean_change_pct: float | None = None
    median_change_pct: float | None = None
    dispersion_pct: float | None = None
    as_of: datetime | None = None
    provisional: bool
    decision_usable: bool


class TaiwanDashboardWatchlistSelectionRead(BaseModel):
    group_id: int | None = None
    group_name: str | None = None
    selection_policy: str
    include_children: bool
    enabled_only: bool
    limit: int
    truncated: bool


class TaiwanDashboardWatchlistItemRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    market: str | None = None
    status: str
    price: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    price_semantics: str
    as_of: datetime | None = None
    warning: str | None = None


class TaiwanDashboardWatchlistGroupRead(BaseModel):
    group_id: int
    group_name: str
    parent_id: int | None = None
    sort_order: int


class TaiwanDashboardWatchlistRead(BaseModel):
    status: str
    groups: list[TaiwanDashboardWatchlistGroupRead] = Field(default_factory=list)
    selection: TaiwanDashboardWatchlistSelectionRead
    items: list[TaiwanDashboardWatchlistItemRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TaiwanMarketDashboardRead(BaseModel):
    kind: Literal["omi.tw_market_dashboard"] = "omi.tw_market_dashboard"
    version: Literal["omi.tw_market_dashboard.v1"] = "omi.tw_market_dashboard.v1"
    snapshot_id: str
    state_version: int
    trade_date: date
    session: TaiwanDashboardSessionRead
    as_of: datetime | None = None
    indices: list[TaiwanDashboardIndexEstimateRead]
    breadth: dict[str, TaiwanDashboardBreadthRead]
    hot_groups: list[TaiwanDashboardGroupRead]
    watchlist: TaiwanDashboardWatchlistRead
    freshness: TaiwanDashboardFreshnessRead
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TaiwanDashboardSymbolRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    market: str
    industry: str | None = None


class TaiwanDashboardSymbolSearchRead(BaseModel):
    kind: Literal["omi.tw_symbol_search"] = "omi.tw_symbol_search"
    version: Literal["omi.tw_symbol_search.v1"] = "omi.tw_symbol_search.v1"
    query: str
    count: int
    limit: int
    items: list[TaiwanDashboardSymbolRead]


class TaiwanDashboardMovingAveragePointRead(BaseModel):
    time: date
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None


class TaiwanDashboardStockDetailRead(BaseModel):
    kind: Literal["omi.tw_stock_dashboard_detail"] = (
        "omi.tw_stock_dashboard_detail"
    )
    version: Literal["omi.tw_stock_dashboard_detail.v1"] = (
        "omi.tw_stock_dashboard_detail.v1"
    )
    stock_id: str
    stock_name: str | None = None
    market: str
    timeframe: str
    bars: int
    cache_only: Literal[True] = True
    chart: MarketOhlcChartRead
    moving_averages: list[TaiwanDashboardMovingAveragePointRead] = Field(
        default_factory=list
    )
    technical: TechnicalReportRead
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

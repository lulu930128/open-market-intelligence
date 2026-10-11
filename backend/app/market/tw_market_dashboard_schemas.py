from __future__ import annotations

from app.market_data.contracts import BreadthLimitObservation

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from app.market.schemas import MarketOhlcChartRead, TechnicalReportRead
from app.market.tw_workspace_research import TaiwanWorkspaceResearchRead


class TaiwanDashboardSessionRead(BaseModel):
    phase: str
    presentation_state: str
    trade_date: date
    is_current_trading_day: bool
    next_transition_at: datetime


class TaiwanDashboardFreshnessRead(BaseModel):
    status: str
    basis: str = "producer_cadence"
    cache_only: Literal[True] = True
    oldest_as_of: datetime | None = None
    newest_as_of: datetime | None = None
    max_age_seconds: int | None = None
    source: str
    producer_cadence_seconds: int | None = None


class TaiwanDashboardBreadthRead(BaseModel):
    market: str
    status: str
    session_phase: str
    price_semantics: str
    provisional: bool
    decision_usable: bool
    deprecated: bool = False
    canonical_ref: str | None = None
    universe: int
    coverage: int
    advance: int
    decline: int
    unchanged: int
    unknown: int
    limits: BreadthLimitObservation | None = None
    limit_up_count: int | None = None
    limit_down_count: int | None = None
    classification_diagnostics: dict[str, int] = Field(default_factory=dict)
    auction_breadth: dict[str, Any] | None = None
    acquisition_diagnostics: dict[str, Any] | None = None
    coverage_ratio: float
    received_count: int | None = Field(default=None, ge=0)
    received_coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    classified_coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    observation_coverage_count: int | None = Field(default=None, ge=0)
    observation_coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    observation_coverage_status: str = "unknown"
    directional_coverage_count: int | None = Field(default=None, ge=0)
    directional_coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    directional_coverage_status: str = "unknown"
    directional_unavailable_count: int | None = Field(default=None, ge=0)
    valid_no_trade_count: int | None = Field(default=None, ge=0)
    trade_state_resolution_status: str = "unknown"
    observation_received_at: datetime | None = None
    observation_received_freshness: str | None = None
    last_trade_recency: str | None = None
    classification_summary: dict[str, int | None] = Field(default_factory=dict)
    classification_reason_counts: dict[str, int] = Field(default_factory=dict)
    coverage_reason_counts: dict[str, int | None] = Field(default_factory=dict)
    raw_unknown_reason_counts: dict[str, int] = Field(default_factory=dict)
    scope: str | None = None
    source: str | None = None
    trade_date: date | None = None
    failed_batch_count: int | None = None
    as_of: datetime | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_coverage_reconciliation(self):
        if min(self.universe, self.coverage, self.advance, self.decline, self.unchanged, self.unknown) < 0:
            raise ValueError("breadth counts must be nonnegative")
        if self.classification_summary:
            from app.market.tw_breadth_projection import project_breadth_coverage

            projected = project_breadth_coverage({
                "advance_count": self.advance, "decline_count": self.decline,
                "unchanged_count": self.unchanged, "total_count": self.universe,
                "not_received_count": self.classification_summary.get("not_received"),
                "received_unclassified_count": self.classification_summary.get("received_unclassified"),
                "coverage_reason_counts": self.classification_reason_counts,
            })
            for key, value in projected.items():
                if getattr(self, key) != value:
                    raise ValueError(f"breadth {key} does not reconcile")
        if self.advance + self.decline + self.unchanged != self.coverage:
            raise ValueError(
                "advance + decline + unchanged must equal breadth coverage"
            )
        if self.coverage + self.unknown != self.universe:
            raise ValueError("coverage + unknown must equal breadth universe")
        if self.coverage_reason_counts:
            classified = self.coverage_reason_counts.get("classified")
            if classified != self.coverage:
                raise ValueError(
                    "coverage_reason_counts.classified must equal coverage"
                )
            explained_unknown = sum(
                value
                for key, value in self.coverage_reason_counts.items()
                if key != "classified" and value is not None
            )
            if explained_unknown != self.unknown:
                raise ValueError(
                    "known coverage reason counts must reconcile to unknown"
                )
        return self


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


class TaiwanDashboardResolvedIndexRead(BaseModel):
    index_id: str
    market: str
    status: str
    value: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    event_time: datetime | None = None
    trade_date: date | None = None
    source: str | None = None
    provider: str | None = None
    selected_candidate: str | None = None
    authority: Literal[
        "official_exchange",
        "provider",
        "derived_proxy",
        "unknown",
    ]
    finalization: Literal["intraday", "provisional", "final", "unknown"]
    official_source: bool
    official_close_confirmed: bool
    provisional_estimate: bool
    selection_reason: str
    acquisition_policy: Literal["cache_only"] = "cache_only"
    resolution_version: str
    resolution_id: str
    official_close_status: str
    official: bool
    provisional: bool
    decision_usable: bool
    quote_semantics: str
    delivery_status: str
    compatibility_fallback: bool = False
    compatibility_fallback_reason: str | None = None
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
    lane: Literal["actual", "indicative"] = "actual"
    price_semantics: str | None = None
    observation_freshness: str | None = None
    observation_received_freshness: str | None = None
    last_trade_recency: str | None = None
    breadth_usable: bool | None = None
    observation_coverage_count: int | None = Field(default=None, ge=0)
    observation_coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    directional_coverage_count: int | None = Field(default=None, ge=0)
    directional_coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    directional_unavailable_count: int | None = Field(default=None, ge=0)
    valid_no_trade_count: int | None = Field(default=None, ge=0)
    coverage_reason_counts: dict[str, int] | None = None
    facts_usable_for_ranking: bool = False
    intraday_research_usable: bool = False
    freshness_member_counts: dict[str, int] = Field(default_factory=dict)
    delayed_member_count: int = 0
    stale_member_count: int = 0
    lineage: dict[str, Any] = Field(default_factory=dict)
    execution_grade_usable: bool = False
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
    instrument_type: str
    market: str | None = None
    status: str
    price: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    price_semantics: str
    trade_date: date | None = None
    expected_trade_date: date
    as_of: datetime | None = None
    freshness_status: str
    provider: str | None = None
    source: str | None = None
    reason_code: str
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
    resolved_indices: list[TaiwanDashboardResolvedIndexRead] = Field(
        default_factory=list
    )
    headline_index_field: Literal["resolved_indices"] = "resolved_indices"
    breadth: dict[str, TaiwanDashboardBreadthRead]
    resolved_breadth: dict[str, TaiwanDashboardBreadthRead] = Field(
        default_factory=dict
    )
    headline_breadth_field: Literal["resolved_breadth"] = "resolved_breadth"
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
    time: str
    ma5: float | None = None
    ma20: float | None = None
    ma60: float | None = None


class TaiwanDashboardIntradayChartPointRead(BaseModel):
    time: datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    volume_status: str = "not_provided"
    is_partial: bool = False
    finalized: bool = False


class TaiwanDashboardSeriesCoverageRead(BaseModel):
    """Additive view of the canonical resolver metadata, never reclassified."""

    model_config = ConfigDict(extra="allow")
    contract_version: str | None = None
    status: str | None = None
    trade_date: date | None = None
    session_completed: bool | None = None
    expected_from: datetime | None = None
    expected_to: datetime | None = None
    expected_bucket_count: int | None = None
    observed_bucket_count: int | None = None
    missing_bucket_count: int | None = None
    current_cumulative_volume_complete: bool | None = None


class TaiwanDashboardIntradayChartRead(BaseModel):
    source: str
    interval: str
    trade_date: date | None = None
    point_count: int
    cache_status: str
    cache_hit: bool
    volume_unit: str = "shares"
    volume_semantics: str
    series_coverage: TaiwanDashboardSeriesCoverageRead | None = None
    coverage_scope: Literal["resolver_series_before_display_slice"] = "resolver_series_before_display_slice"
    cache_trade_date: date | None = None
    cache_latest_time: datetime | None = None
    resolved_health: dict[str, Any] | None = None
    limitations: list[str] = Field(default_factory=list)
    points: list[TaiwanDashboardIntradayChartPointRead] = Field(
        default_factory=list
    )


class TaiwanStockChartRead(BaseModel):
    kind: Literal["omi.tw_stock_chart"] = "omi.tw_stock_chart"
    version: Literal["omi.tw_stock_chart.v1"] = "omi.tw_stock_chart.v1"
    stock_id: str
    stock_name: str | None = None
    instrument_type: Literal["stock", "etf", "unknown"] = "unknown"
    market: str
    timeframe: str
    bars: int
    cache_only: Literal[True] = True
    chart: MarketOhlcChartRead
    intraday_chart: TaiwanDashboardIntradayChartRead | None = None
    moving_averages: list[TaiwanDashboardMovingAveragePointRead] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TaiwanDashboardStockDetailRead(TaiwanStockChartRead):
    kind: Literal["omi.tw_stock_dashboard_detail"] = "omi.tw_stock_dashboard_detail"
    version: Literal["omi.tw_stock_dashboard_detail.v2"] = "omi.tw_stock_dashboard_detail.v2"
    technical: TechnicalReportRead


class TaiwanStockResearchRead(BaseModel):
    kind: Literal["omi.tw_stock_research"] = "omi.tw_stock_research"
    version: Literal["omi.tw_stock_research.v1"] = "omi.tw_stock_research.v1"
    stock_id: str
    timeframe: str
    cache_only: Literal[True] = True
    technical: TechnicalReportRead
    warnings: list[str] = Field(default_factory=list)


class TaiwanStockResearchResponseRead(RootModel[TaiwanStockResearchRead | TaiwanWorkspaceResearchRead]):
    """Preserve the full v1 envelope while exposing opt-in workspace v1."""


class TaiwanWorkspaceHeaderRead(BaseModel):
    kind: Literal["omi.tw_workspace_header"] = "omi.tw_workspace_header"
    version: Literal["omi.tw_workspace_header.v1"] = "omi.tw_workspace_header.v1"
    cache_only: Literal[True] = True
    generated_at: datetime
    session: TaiwanDashboardSessionRead
    freshness: TaiwanDashboardFreshnessRead
    resolved_indices: list[TaiwanDashboardResolvedIndexRead]
    resolved_breadth: dict[str, TaiwanDashboardBreadthRead]
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class TaiwanWorkspaceWatchlistRead(TaiwanDashboardWatchlistRead):
    kind: Literal["omi.tw_workspace_watchlist"] = "omi.tw_workspace_watchlist"
    version: Literal["omi.tw_workspace_watchlist.v1"] = "omi.tw_workspace_watchlist.v1"
    cache_only: Literal[True] = True
    generated_at: datetime


class TaiwanWorkspaceHotGroupsRead(BaseModel):
    kind: Literal["omi.tw_workspace_hot_groups"] = "omi.tw_workspace_hot_groups"
    version: Literal["omi.tw_workspace_hot_groups.v1"] = "omi.tw_workspace_hot_groups.v1"
    cache_only: Literal[True] = True
    generated_at: datetime
    status: str
    lane: Literal["actual", "indicative"]
    as_of: datetime | None = None
    hot_groups: list[TaiwanDashboardGroupRead]
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

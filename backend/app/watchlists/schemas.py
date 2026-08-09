from datetime import datetime, date

from pydantic import BaseModel, ConfigDict, Field


class WatchlistGroupCreate(BaseModel):
    parent_id: int | None = None
    group_name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 100
    is_active: bool = True


class WatchlistGroupUpdate(BaseModel):
    parent_id: int | None = None
    group_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class WatchlistGroupMove(BaseModel):
    parent_id: int | None = None
    before_group_id: int | None = None


class WatchlistGroupRead(BaseModel):
    id: int
    parent_id: int | None = None

    group_name: str
    description: str | None = None

    sort_order: int
    is_active: bool

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistGroupTreeRead(BaseModel):
    id: int
    parent_id: int | None = None

    group_name: str
    description: str | None = None

    sort_order: int
    is_active: bool

    children: list["WatchlistGroupTreeRead"] = []


class WatchlistItemCreate(BaseModel):
    group_id: int
    stock_id: str = Field(..., min_length=1, max_length=20)

    note: str | None = None
    priority: int = 100
    tags: str | None = None
    enabled: bool = True


class WatchlistItemUpdate(BaseModel):
    group_id: int | None = None
    stock_id: str | None = Field(default=None, min_length=1, max_length=20)

    note: str | None = None
    priority: int | None = None
    tags: str | None = None
    enabled: bool | None = None


class WatchlistItemMove(BaseModel):
    group_id: int
    before_item_id: int | None = None


class WatchlistItemRead(BaseModel):
    id: int

    group_id: int
    stock_id: str
    stock_name: str | None = None

    note: str | None = None
    priority: int
    tags: str | None = None
    enabled: bool

    created_at: datetime
    updated_at: datetime


class WatchlistBackfillStockResultRead(BaseModel):
    stock_id: str
    stock_name: str | None = None
    market: str | None = None

    status: str
    parsed_count: int = 0
    inserted_count: int = 0
    skipped_count: int = 0

    message: str | None = None
    error_message: str | None = None


class WatchlistGroupBackfillResultRead(BaseModel):
    group_id: int
    include_children: bool

    start_date: date
    end_date: date

    requested_stock_count: int
    success_count: int
    warning_count: int
    error_count: int
    skipped_count: int

    results: list[WatchlistBackfillStockResultRead]


class WatchlistLatestIndicatorRead(BaseModel):
    stock_id: str
    stock_name: str | None = None

    time: date | None = None
    close: float | None = None
    volume: int | None = None

    change: float | None = None
    change_pct: float | None = None

    ma: dict[str, float | None] = Field(default_factory=dict)
    volume_ma: dict[str, float | None] = Field(default_factory=dict)

    status: str
    error_message: str | None = None


class WatchlistGroupLatestIndicatorsRead(BaseModel):
    group_id: int
    include_children: bool

    requested_stock_count: int
    success_count: int
    no_data_count: int
    error_count: int

    results: list[WatchlistLatestIndicatorRead]


class WatchlistSignalRead(BaseModel):
    key: str
    label: str
    direction: str
    level: str
    message: str
    value: float | None = None
    reference: float | None = None


class WatchlistStockLatestSignalsRead(BaseModel):
    stock_id: str
    stock_name: str | None = None

    time: str | date | None = None
    close: float | None = None
    volume: int | None = None
    change_pct: float | None = None

    score: int
    status: str

    signals: list[WatchlistSignalRead] = Field(default_factory=list)
    error_message: str | None = None


class WatchlistGroupLatestSignalsRead(BaseModel):
    group_id: int
    include_children: bool

    requested_stock_count: int
    bullish_count: int
    bearish_count: int
    neutral_count: int
    no_data_count: int
    error_count: int

    results: list[WatchlistStockLatestSignalsRead]


class WatchlistRankingItemRead(BaseModel):
    rank: int
    market_rank: int | None = None
    rank_value: float | int | None = None
    rank_trade_date: date | None = None

    stock_id: str
    stock_name: str | None = None

    time: str | date | None = None
    close: float | None = None
    volume: int | None = None
    change: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    limit_status: str | None = None

    score: int
    status: str

    signal_count: int
    signal_keys: list[str] = Field(default_factory=list)

    primary_signal_key: str | None = None
    primary_signal_label: str | None = None

    indicator_snapshot: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    context_snapshot: dict[str, dict[str, object]] = Field(default_factory=dict)

    intraday_previous_close: float | None = None
    intraday_points: list[dict] = Field(default_factory=list)

    error_message: str | None = None


class WatchlistGroupRankingRead(BaseModel):
    group_id: int
    include_children: bool

    rank_by: str
    sort_order: str
    rank_scope: str = "watchlist"
    rank_trade_date: date | None = None
    rank_universe_count: int = 0

    requested_stock_count: int
    ranked_count: int
    no_data_count: int
    error_count: int

    trade_date: date | None = None
    target_trade_date: date | None = None
    is_current: bool = True
    current_stock_count: int = 0
    stale_stock_count: int = 0

    underlying_trade_date: date | None = None
    coverage_ratio: float = 1.0
    is_live: bool = False
    is_full: bool = False
    is_live_ranking: bool = False
    is_full_requested_universe: bool = False
    is_full_market: bool = False
    ranking_universe_type: str = "requested_watchlist"
    ranking_universe_count: int = 0
    ranking_returned_count: int = 0
    ranking_coverage_ratio: float = 1.0
    ranking_semantics: str = "latest_completed_daily_rows"

    results: list[WatchlistRankingItemRead]


class WatchlistGroupRankingBatchRead(BaseModel):
    group_id: int
    include_children: bool

    rank_by: str
    sort_order: str

    offset: int
    batch_size: int
    total_stock_count: int
    requested_stock_count: int
    ranked_count: int
    no_data_count: int
    error_count: int

    trade_date: date | None = None
    target_trade_date: date | None = None
    is_current: bool = True
    current_stock_count: int = 0
    stale_stock_count: int = 0
    has_more: bool

    results: list[WatchlistRankingItemRead]


class WatchlistRadarBucketRead(BaseModel):
    key: str
    label: str
    description: str
    count: int


class WatchlistRadarV2EvaluationRead(BaseModel):
    rule_version: str
    rule_config_hash: str
    feature_version: str
    feature_config_hash: str
    direction: int
    direction_score: float
    evidence_score: float
    within_family_conflict_score: float
    cross_family_conflict_score: float
    timeframe_conflict_score: float
    conflict_score: float
    risk_score: float
    confidence_score: float
    priority_score: float
    context_alignment_score: float
    primary_bucket: str
    urgency: str
    evidence_grade: str
    instrument_regime: str
    instrument_regime_clarity: float
    market_regime: str
    market_regime_clarity: float
    combined_regime_clarity: float
    volatility_state: str
    data_status: str
    freshness_status: str
    data_quality_score: float
    state_tags: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    family_scores: dict[str, dict[str, object]] = Field(default_factory=dict)
    signal_contributions: list[dict[str, object]] = Field(default_factory=list)
    limitations: list[dict[str, object]] = Field(default_factory=list)


class WatchlistRadarEngineRead(BaseModel):
    active_version: str
    active_config_hash: str | None = None
    shadow_version: str
    shadow_config_hash: str
    mode: str
    rollback_version: str
    technical_direction_owner: str
    cross_market_context_mode: str = "disabled"
    legacy_status: str = "available"
    legacy_frozen_at: date | None = None


class WatchlistRadarV2ReadinessRead(BaseModel):
    operational_status: str
    validation_status: str
    backtest_status: str
    latest_backtest_id: int | None = None
    completed_backtest_count: int = 0
    outcome_count: int = 0
    finalized_outcome_count: int = 0
    pending_outcome_count: int = 0
    limitations: list[dict[str, object]] = Field(default_factory=list)


class WatchlistRadarV2SummaryRead(BaseModel):
    evaluated_count: int
    universe_evaluated_count: int = 0
    universe_scope: str = "presentation_results_fallback"
    direction_changed_count: int
    bucket_changed_count: int
    conflict_count: int
    insufficient_count: int
    market_regime: str
    market_regime_clarity: float
    market_limitations: list[dict[str, object]] = Field(default_factory=list)
    market_snapshot: dict[str, object] = Field(default_factory=dict)
    readiness: WatchlistRadarV2ReadinessRead | None = None
    cross_market_context: dict[str, object] = Field(default_factory=dict)


class WatchlistRadarItemRead(BaseModel):
    rank: int
    source_rank: int | None = None

    bucket: str
    bucket_label: str
    urgency: str
    priority_score: float
    technical_evidence_score: float
    technical_score: float = 0
    technical_grade: str = "watch"
    technical_grade_label: str = "觀察"
    technical_grade_description: str = ""
    direction: str = "neutral"
    direction_label: str = "觀望"
    setup_label: str = ""
    timing_label: str = ""
    risk_label: str = ""
    factor_scores: dict[str, float] = Field(default_factory=dict)
    price_levels: dict[str, object] = Field(default_factory=dict)
    technical_notes: list[str] = Field(default_factory=list)
    action_label: str
    reason: str

    stock_id: str
    stock_name: str | None = None

    time: str | date | None = None
    trade_date: date | None = None
    close: float | None = None
    volume: int | None = None
    change: float | None = None
    previous_close: float | None = None
    change_pct: float | None = None
    limit_status: str | None = None

    score: int
    status: str

    signal_count: int
    signal_keys: list[str] = Field(default_factory=list)
    matched_signal_keys: list[str] = Field(default_factory=list)
    matched_signal_labels: list[str] = Field(default_factory=list)
    signal_labels: list[str] = Field(default_factory=list)

    primary_signal_key: str | None = None
    primary_signal_label: str | None = None

    indicator_snapshot: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    context_snapshot: dict[str, dict[str, object]] = Field(default_factory=dict)
    context_signals: list[dict[str, object]] = Field(default_factory=list)
    context_summary: str = ""
    context_score: float = 0

    stale: bool = False
    error_message: str | None = None
    radar_v2: WatchlistRadarV2EvaluationRead | None = None


class WatchlistGroupRadarRead(BaseModel):
    group_id: int
    include_children: bool

    mode: str
    max_results: int
    market: str | None = None
    scope_label: str | None = None
    data_limitations: list[str] = Field(default_factory=list)

    requested_stock_count: int
    ranked_count: int
    matched_count: int
    radar_count: int
    no_data_count: int
    error_count: int

    trade_date: date | None = None
    target_trade_date: date | None = None
    is_current: bool = True
    current_stock_count: int = 0
    stale_stock_count: int = 0

    buckets: list[WatchlistRadarBucketRead]
    results: list[WatchlistRadarItemRead]
    cache_status: str = "computed"
    snapshot_id: int | None = None
    snapshot_date: date | None = None
    calculated_at: datetime | None = None
    radar_engine: WatchlistRadarEngineRead | None = None
    radar_v2_summary: WatchlistRadarV2SummaryRead | None = None


class WatchlistRadarV2PersistResultRead(BaseModel):
    status: str
    rule_version: str
    rule_config_hash: str
    group_id: int
    mode: str
    snapshot_date: date
    snapshot_run_id: int | None = None
    feature_created_count: int
    evaluation_created_count: int
    projection_created_count: int
    event_created_count: int
    event_updated_count: int
    event_link_created_count: int = 0
    event_unobserved_count: int = 0
    universe_scope: str = "presentation_results_fallback"
    universe_observed_count: int = 0
    universe_evaluated_count: int = 0
    observation_status_counts: dict[str, int] = Field(default_factory=dict)
    evaluation_ids: list[int] = Field(default_factory=list)
    skipped_count: int
    skipped: list[dict[str, object]] = Field(default_factory=list)
    outcomes: dict[str, object] | None = None


class WatchlistRadarV2ProjectionHistoryRead(BaseModel):
    group_id: int
    mode: str
    snapshot_date: date
    rule_version: str
    rule_config_hash: str
    universe_observed_count: int
    selected_count: int
    observed_at: datetime


class WatchlistRadarV2OutcomeItemRead(BaseModel):
    evaluation_id: int | None = None
    stock_id: str
    stock_name: str | None = None
    source_rank: int | None = None
    status: str
    summary_state: str
    horizon_end_trade_date: date | None = None
    signal_close_return_pct: float | None = None
    signal_mfe_pct: float | None = None
    signal_mae_pct: float | None = None
    outcome_quality: str
    limitations: list[dict[str, object]] = Field(default_factory=list)


class WatchlistRadarV2OutcomeSummaryRead(BaseModel):
    status: str
    group_id: int
    mode: str
    snapshot_date: date | None = None
    horizon_trading_days: int
    rule_version: str
    outcome_contract_version: str
    total_count: int
    finalized_count: int
    pending_count: int
    summary_state_counts: dict[str, int] = Field(default_factory=dict)
    items: list[WatchlistRadarV2OutcomeItemRead] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)


class WatchlistRadarV2BacktestRead(BaseModel):
    id: int
    run_key: str
    status: str
    rule_version: str
    rule_config_hash: str
    feature_version: str
    feature_config_hash: str
    outcome_contract_version: str
    outcome_config_hash: str
    period_start: date
    period_end: date
    purge_trading_days: int
    embargo_trading_days: int
    requested_sample_count: int
    eligible_sample_count: int
    excluded_sample_count: int
    coverage_ratio: float
    horizons: list[int] = Field(default_factory=list)
    universe: dict[str, object] = Field(default_factory=dict)
    coverage: dict[str, object] = Field(default_factory=dict)
    splits: dict[str, object] = Field(default_factory=dict)
    baseline: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, object] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class WatchlistRadarSnapshotRead(BaseModel):
    id: int
    group_id: int
    include_children: bool
    enabled_only: bool
    mode: str
    max_results: int
    calculation_limit: int
    radar_rule_version: str

    snapshot_date: date
    trade_date: date | None = None
    target_trade_date: date | None = None
    is_current: bool = True
    current_stock_count: int = 0
    stale_stock_count: int = 0

    requested_stock_count: int = 0
    ranked_count: int = 0
    matched_count: int = 0
    radar_count: int = 0
    no_data_count: int = 0
    error_count: int = 0

    buckets: list[WatchlistRadarBucketRead] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime


class WatchlistRadarOutcomeItemRead(BaseModel):
    id: int | None = None
    snapshot_item_id: int
    rank: int
    stock_id: str
    stock_name: str | None = None
    bucket: str
    bucket_label: str
    status: str
    reason: str

    snapshot_date: date
    outcome_trade_date: date | None = None
    signal_close_price: float | None = None
    outcome_open_price: float | None = None
    outcome_high_price: float | None = None
    outcome_low_price: float | None = None
    outcome_close_price: float | None = None
    outcome_volume: int | None = None

    open_gap_pct: float | None = None
    close_return_pct: float | None = None
    max_favorable_pct: float | None = None
    max_adverse_pct: float | None = None
    intraday_range_pct: float | None = None
    volume_change_pct: float | None = None
    radar_item: WatchlistRadarItemRead | None = None


class WatchlistRadarOutcomeBucketSummaryRead(BaseModel):
    bucket: str
    bucket_label: str
    total_count: int
    hit_count: int = 0
    miss_count: int = 0
    neutral_count: int = 0
    unevaluable_count: int = 0
    pending_count: int = 0
    avg_close_return_pct: float | None = None
    avg_max_adverse_pct: float | None = None


class WatchlistRadarOutcomeSummaryRead(BaseModel):
    status: str
    snapshot: WatchlistRadarSnapshotRead | None = None
    evaluated_at: datetime | None = None

    total_count: int = 0
    hit_count: int = 0
    miss_count: int = 0
    neutral_count: int = 0
    unevaluable_count: int = 0
    pending_count: int = 0

    avg_close_return_pct: float | None = None
    avg_max_favorable_pct: float | None = None
    avg_max_adverse_pct: float | None = None

    bucket_summaries: list[WatchlistRadarOutcomeBucketSummaryRead] = Field(default_factory=list)
    items: list[WatchlistRadarOutcomeItemRead] = Field(default_factory=list)
    data_limitations: list[str] = Field(default_factory=list)


class WatchlistGroupDeleteResultRead(BaseModel):
    group_id: int
    recursive: bool

    deleted_group_count: int
    deleted_item_count: int

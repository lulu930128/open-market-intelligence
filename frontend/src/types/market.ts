export type WatchlistGroupNode = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  children: WatchlistGroupNode[];
};

export type WatchlistGroupRead = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type WatchlistItemRead = {
  id: number;
  group_id: number;
  stock_id: string;
  stock_name: string | null;
  market: string | null;
  instrument_type: string;
  note: string | null;
  priority: number;
  tags: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type TaiwanEtfProfileRead = {
  report_date: string | null;
  fund_short_name: string | null;
  fund_name: string | null;
  fund_name_en: string | null;
  fund_type: string | null;
  benchmark_name: string | null;
  is_customized_index: boolean | null;
  investment_scope: string | null;
  has_performance_benchmark: boolean | null;
  performance_benchmark_name: string | null;
  has_foreign_components: boolean | null;
  tax_id: string | null;
  established_date: string | null;
  listed_date: string | null;
  fund_manager: string | null;
  issued_units: number | null;
  custodian: string | null;
  issuer_name: string | null;
  source: string;
  source_url: string | null;
  fetched_at: string;
};

export type TaiwanEtfNavDailyRead = {
  nav_date: string;
  issuer_name: string | null;
  fund_name: string | null;
  nav: number | null;
  previous_nav: number | null;
  nav_change: number | null;
  nav_change_pct: number | null;
  close_price: number | null;
  premium_discount_pct: number | null;
  benchmark_name: string | null;
  benchmark_date: string | null;
  benchmark_close: number | null;
  benchmark_previous_close: number | null;
  benchmark_change: number | null;
  benchmark_change_pct: number | null;
  source: string;
  source_url: string | null;
  fetched_at: string;
};

export type TaiwanEtfPcfComponentRead = {
  source_section: string;
  asset_type: string;
  symbol: string;
  name: string | null;
  name_en: string | null;
  contract_month: string | null;
  quantity: number | null;
  weight_pct: number | null;
  cash_in_lieu: string | null;
  minimum_creation: boolean | null;
  order_index: number;
};

export type TaiwanEtfPcfRead = {
  effective_date: string;
  reference_date: string | null;
  fund_id: string | null;
  fund_name: string | null;
  full_name: string | null;
  name_en: string | null;
  total_net_assets: number | null;
  issued_units: number | null;
  unit_nav: number | null;
  creation_unit: number | null;
  estimated_creation_value: number | null;
  estimated_cash_component: number | null;
  unit_change: number | null;
  actual_cash_component: number | null;
  redemption_method: string;
  component_count: number;
  components: TaiwanEtfPcfComponentRead[];
  source_updated_at: string | null;
  source: string;
  source_url: string | null;
  fetched_at: string;
};

export type TaiwanEtfInavRead = {
  observed_at: string;
  fund_short_name: string | null;
  investment_area: string | null;
  estimated_nav: number;
  nav_change: number | null;
  market_price: number | null;
  price_change: number | null;
  premium_discount_pct: number | null;
  source: string;
  source_url: string | null;
  fetched_at: string;
};

export type TaiwanEtfValuationMetricRead = {
  value: number | null;
  as_of_date: string | null;
  observed_at: string | null;
  fetched_at: string | null;
  source: string | null;
  source_url: string | null;
  basis: string;
  status: string;
  issue_codes: string[];
};

export type TaiwanEtfValuationRead = {
  status: string;
  basis: "daily_close" | "intraday" | string;
  market_price: TaiwanEtfValuationMetricRead;
  nav: TaiwanEtfValuationMetricRead;
  premium_discount_pct: number | null;
  premium_discount_status: string;
  aligned: boolean;
  issue_codes: string[];
};

export type TaiwanEtfStrategyRead = {
  management_style: "active" | "passive" | "unknown" | string;
  benchmark_role:
    | "tracked_index"
    | "performance_benchmark"
    | "unknown"
    | string;
  benchmark_name: string | null;
};

export type TaiwanEtfResourceStateRead = {
  applicable: boolean | null;
  connector_supported: boolean;
  status: string;
  reason_code: string | null;
  as_of_date: string | null;
  observed_at: string | null;
  source: string | null;
};

export type TaiwanEtfOverviewRead = {
  stock_id: string;
  stock_name: string | null;
  market: string;
  instrument_type: "etf" | string;
  status: "current" | "partial" | "stale" | "missing" | string;
  capabilities: Record<string, boolean>;
  profile: TaiwanEtfProfileRead | null;
  daily_nav: TaiwanEtfNavDailyRead | null;
  pcf: TaiwanEtfPcfRead | null;
  intraday_nav: TaiwanEtfInavRead | null;
  valuation: TaiwanEtfValuationRead;
  strategy: TaiwanEtfStrategyRead;
  resource_states: Record<string, TaiwanEtfResourceStateRead>;
  freshness: {
    status: "current" | "stale" | "missing" | string;
    timezone: string;
    nav_release_time: string;
    expected_nav_date: string;
    latest_nav_date: string | null;
    nav_is_current: boolean;
    profile_report_date: string | null;
    expected_pcf_date: string | null;
    latest_pcf_date: string | null;
    pcf_status: string;
    expected_inav_date: string | null;
    latest_inav_at: string | null;
    inav_status: string;
    inav_age_seconds: number | null;
    session_phase: string | null;
    refresh_recommended: boolean;
    checked_at: string;
  };
  sources: Array<{
    resource: string;
    provider: string;
    source_url: string;
    status: string;
    observed_date: string | null;
    fetched_at: string | null;
  }>;
  warnings: string[];
  refresh: {
    requested_resources: string[];
    refreshed_resources: string[];
    request_count: number;
    target_nav_date: string | null;
    target_pcf_date: string | null;
    inav_observed_at: string | null;
    errors: Record<string, string>;
  } | null;
};

export type PortfolioMarket = "tw" | "us" | "jp" | "kr";

export type PortfolioHoldingRead = {
  id: number;
  market: PortfolioMarket;
  symbol: string;
  symbol_name: string | null;
  quantity: number;
  cost_amount: number | null;
  currency: string;
  average_cost: number | null;
  source: string;
  source_updated_at: string | null;
  note: string | null;
  tags: string | null;
  strategy_horizon: string | null;
  opened_at: string | null;
  is_active: boolean;
  position_context: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type KgiPortfolioSyncRead = {
  market: "tw" | "us";
  status: "synced";
  source: "kgi_superpy";
  holding_count: number;
  created_count: number;
  updated_count: number;
  removed_count: number;
  missing_cost_basis_count: number;
  warnings: string[];
  source_updated_at: string;
};

export type WatchlistBackfillStockResult = {
  stock_id: string;
  stock_name: string | null;
  market: string | null;
  status: string;
  parsed_count: number;
  inserted_count: number;
  skipped_count: number;
  message: string | null;
  error_message: string | null;
};

export type WatchlistGroupBackfillResult = {
  group_id: number;
  include_children: boolean;
  start_date: string;
  end_date: string;
  requested_stock_count: number;
  success_count: number;
  warning_count: number;
  error_count: number;
  skipped_count: number;
  results: WatchlistBackfillStockResult[];
};

export type JobRunRead = {
  id: number;
  job_type: string;
  status: "queued" | "running" | "success" | "error" | string;
  target: string | null;
  progress_current: number;
  progress_total: number;
  message: string | null;
  error_message: string | null;
  request: unknown;
  result: unknown;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  updated_at: string;
};

export type ChartDrawingSnapshotRead = {
  id: number;
  market: string;
  symbol: string;
  timeframe: string;
  label: string | null;
  time_mode: string | null;
  selected_drawing_id: string | null;
  drawing_count: number;
  drawings: Array<Record<string, unknown>>;
  summary: Record<string, unknown> | null;
  source: string;
  created_at: string;
  updated_at: string;
};

export type ChartDrawingSnapshotWrite = {
  label?: string | null;
  time_mode?: string | null;
  selected_drawing_id?: string | null;
  drawings: Array<Record<string, unknown>>;
  summary?: Record<string, unknown> | null;
  source?: string;
};

export type RankingItem = {
  rank: number;
  market_rank?: number | null;
  rank_value?: number | null;
  rank_trade_date?: string | null;
  stock_id: string;
  stock_name: string | null;
  time: string | null;
  close: number | null;
  volume: number | null;
  change: number | null;
  previous_close: number | null;
  change_pct: number | null;
  limit_status: "limit_up" | "limit_down" | null;
  score: number | null;
  status: string;
  signal_count: number;
  signal_keys: string[];
  primary_signal_key: string | null;
  primary_signal_label: string | null;
  indicator_snapshot: Record<string, Record<string, number | null>>;
  context_snapshot: Record<string, Record<string, number | string | null>>;
  intraday_previous_close: number | null;
  intraday_points: Array<{
    time: string;
    price: number;
  }>;
  error_message: string | null;
};

export type RankingResponse = {
  group_id: number;
  include_children: boolean;
  rank_by: string;
  sort_order: string;
  rank_scope?: "watchlist" | "tw_market" | string;
  rank_trade_date?: string | null;
  rank_universe_count?: number;
  requested_stock_count: number;
  ranked_count: number;
  no_data_count: number;
  error_count: number;
  trade_date: string | null;
  target_trade_date: string | null;
  is_current: boolean;
  current_stock_count: number;
  stale_stock_count: number;
  results: RankingItem[];
};

export type RankingBatchResponse = {
  group_id: number;
  include_children: boolean;
  rank_by: string;
  sort_order: string;
  offset: number;
  batch_size: number;
  total_stock_count: number;
  requested_stock_count: number;
  ranked_count: number;
  no_data_count: number;
  error_count: number;
  trade_date: string | null;
  target_trade_date: string | null;
  is_current: boolean;
  current_stock_count: number;
  stale_stock_count: number;
  has_more: boolean;
  results: RankingItem[];
};

export type WatchlistRadarMode =
  | "action"
  | "surge"
  | "breakout"
  | "volume"
  | "overheat"
  | "weakness"
  | "risk"
  | "momentum";

export type WatchlistRadarBucketRead = {
  key: string;
  label: string;
  description: string;
  count: number;
};

export type WatchlistRadarPriceLevels = Record<string, number | string | boolean | null>;

export type WatchlistRadarContextSignal = {
  key: string;
  source: string;
  label: string;
  tone: "positive" | "negative" | "warning" | "neutral" | string;
  stance: "confirm" | "contradict" | "risk" | "info" | string;
  description: string;
  value_label: string | null;
  context_status?: string;
  context_stance?: string;
  snapshot_id?: string | null;
  methodology_version?: string | null;
  relation_snapshot_version?: string | null;
  coverage?: Record<string, unknown>;
  limitations?: string[];
  decision_usable?: boolean;
};

export type WatchlistRadarItemRead = {
  rank: number;
  source_rank: number | null;
  bucket: string;
  bucket_label: string;
  urgency: "high" | "medium" | "low" | string;
  priority_score: number;
  technical_evidence_score: number;
  technical_score: number;
  technical_grade: "strong" | "medium" | "watch" | string;
  technical_grade_label: string;
  technical_grade_description: string;
  direction: "bullish" | "bearish" | "mixed" | "neutral" | string;
  direction_label: string;
  setup_label: string;
  timing_label: string;
  risk_label: string;
  factor_scores: Record<string, number>;
  price_levels: WatchlistRadarPriceLevels;
  technical_notes: string[];
  action_label: string;
  reason: string;
  stock_id: string;
  stock_name: string | null;
  time: string | null;
  trade_date: string | null;
  close: number | null;
  volume: number | null;
  change: number | null;
  previous_close: number | null;
  change_pct: number | null;
  limit_status: "limit_up" | "limit_down" | null;
  score: number;
  status: string;
  signal_count: number;
  signal_keys: string[];
  matched_signal_keys: string[];
  matched_signal_labels: string[];
  signal_labels: string[];
  primary_signal_key: string | null;
  primary_signal_label: string | null;
  indicator_snapshot: Record<string, Record<string, number | null>>;
  context_snapshot: Record<string, Record<string, unknown>>;
  context_signals: WatchlistRadarContextSignal[];
  context_summary: string;
  context_score: number;
  stale: boolean;
  error_message: string | null;
  radar_v2?: WatchlistRadarV2EvaluationRead | null;
};

export type WatchlistRadarV2EvaluationRead = {
  rule_version: string;
  rule_config_hash: string;
  feature_version: string;
  feature_config_hash: string;
  direction: -1 | 0 | 1 | number;
  direction_score: number;
  evidence_score: number;
  within_family_conflict_score: number;
  cross_family_conflict_score: number;
  timeframe_conflict_score: number;
  conflict_score: number;
  risk_score: number;
  confidence_score: number;
  priority_score: number;
  context_alignment_score: number;
  primary_bucket: string;
  urgency: string;
  evidence_grade: "strong" | "medium" | "weak" | "insufficient" | string;
  instrument_regime: string;
  instrument_regime_clarity: number;
  market_regime: string;
  market_regime_clarity: number;
  combined_regime_clarity: number;
  volatility_state: string;
  data_status: string;
  freshness_status: string;
  data_quality_score: number;
  state_tags: string[];
  risk_tags: string[];
  family_scores: Record<string, Record<string, unknown>>;
  signal_contributions: Array<Record<string, unknown>>;
  limitations: Array<Record<string, unknown>>;
};

export type WatchlistRadarEngineRead = {
  active_version: string;
  active_config_hash?: string | null;
  shadow_version: string;
  shadow_config_hash: string;
  mode: "shadow" | string;
  rollback_version: string;
  technical_direction_owner: string;
  cross_market_context_mode?: "display_only" | "disabled" | string;
  legacy_status?: string;
  legacy_frozen_at?: string | null;
};

export type WatchlistRadarV2ReadinessRead = {
  operational_status: string;
  validation_status: "verified" | "blocked" | "unverified" | string;
  backtest_status: string;
  latest_backtest_id?: number | null;
  completed_backtest_count: number;
  outcome_count: number;
  finalized_outcome_count: number;
  pending_outcome_count: number;
  limitations: Array<Record<string, unknown>>;
};

export type WatchlistRadarV2SummaryRead = {
  evaluated_count: number;
  universe_evaluated_count: number;
  universe_scope: string;
  direction_changed_count: number;
  bucket_changed_count: number;
  conflict_count: number;
  insufficient_count: number;
  market_regime: string;
  market_regime_clarity: number;
  market_limitations: Array<Record<string, unknown>>;
  market_snapshot?: Record<string, unknown>;
  readiness?: WatchlistRadarV2ReadinessRead | null;
  cross_market_context?: {
    enabled: boolean;
    mode: "display_only" | string;
    snapshot_count: number;
    materialization_status: "materialized_snapshot" | "not_materialized" | string;
    limitations: string[];
    decision_usable_count: number;
    status_counts: Record<string, number>;
    snapshot_ids: string[];
    methodology_versions: string[];
    relation_snapshot_versions: string[];
    ranking_effect: "none" | string;
    missing_count: number;
  };
};

export type WatchlistGroupRadarRead = {
  group_id: number;
  include_children: boolean;
  mode: WatchlistRadarMode;
  max_results: number;
  market?: string | null;
  scope_label?: string | null;
  data_limitations?: string[];
  requested_stock_count: number;
  ranked_count: number;
  matched_count: number;
  radar_count: number;
  no_data_count: number;
  error_count: number;
  trade_date: string | null;
  target_trade_date: string | null;
  is_current: boolean;
  current_stock_count: number;
  stale_stock_count: number;
  buckets: WatchlistRadarBucketRead[];
  results: WatchlistRadarItemRead[];
  cache_status?: "computed" | "snapshot" | "v2_snapshot" | "frozen_v1_snapshot";
  snapshot_id?: number | null;
  snapshot_date?: string | null;
  calculated_at?: string | null;
  radar_engine?: WatchlistRadarEngineRead | null;
  radar_v2_summary?: WatchlistRadarV2SummaryRead | null;
};

export type WatchlistRadarSnapshotRead = {
  id: number;
  group_id: number;
  include_children: boolean;
  enabled_only: boolean;
  mode: string;
  max_results: number;
  calculation_limit: number;
  radar_rule_version: string;
  snapshot_date: string;
  trade_date: string | null;
  target_trade_date: string | null;
  is_current: boolean;
  current_stock_count: number;
  stale_stock_count: number;
  requested_stock_count: number;
  ranked_count: number;
  matched_count: number;
  radar_count: number;
  no_data_count: number;
  error_count: number;
  buckets: WatchlistRadarBucketRead[];
  data_limitations: string[];
  created_at: string;
  updated_at: string;
};

export type WatchlistRadarOutcomeStatus =
  | "no_snapshot"
  | "not_evaluated"
  | "evaluated"
  | "pending"
  | "hit"
  | "miss"
  | "neutral"
  | "unevaluable"
  | string;

export type WatchlistRadarOutcomeItemRead = {
  id: number | null;
  snapshot_item_id: number;
  rank: number;
  stock_id: string;
  stock_name: string | null;
  bucket: string;
  bucket_label: string;
  status: WatchlistRadarOutcomeStatus;
  reason: string;
  snapshot_date: string;
  outcome_trade_date: string | null;
  signal_close_price: number | null;
  outcome_open_price: number | null;
  outcome_high_price: number | null;
  outcome_low_price: number | null;
  outcome_close_price: number | null;
  outcome_volume: number | null;
  open_gap_pct: number | null;
  close_return_pct: number | null;
  max_favorable_pct: number | null;
  max_adverse_pct: number | null;
  intraday_range_pct: number | null;
  volume_change_pct: number | null;
  radar_item: WatchlistRadarItemRead | null;
};

export type WatchlistRadarOutcomeBucketSummaryRead = {
  bucket: string;
  bucket_label: string;
  total_count: number;
  hit_count: number;
  miss_count: number;
  neutral_count: number;
  unevaluable_count: number;
  pending_count: number;
  avg_close_return_pct: number | null;
  avg_max_adverse_pct: number | null;
};

export type WatchlistRadarOutcomeSummaryRead = {
  status: WatchlistRadarOutcomeStatus;
  snapshot: WatchlistRadarSnapshotRead | null;
  evaluated_at: string | null;
  total_count: number;
  hit_count: number;
  miss_count: number;
  neutral_count: number;
  unevaluable_count: number;
  pending_count: number;
  avg_close_return_pct: number | null;
  avg_max_favorable_pct: number | null;
  avg_max_adverse_pct: number | null;
  bucket_summaries: WatchlistRadarOutcomeBucketSummaryRead[];
  items: WatchlistRadarOutcomeItemRead[];
  data_limitations: string[];
};

export type WatchlistRadarV2OutcomeItemRead = {
  evaluation_id: number | null;
  stock_id: string;
  stock_name: string | null;
  source_rank: number | null;
  status: string;
  summary_state: string;
  horizon_end_trade_date: string | null;
  signal_close_return_pct: number | null;
  signal_mfe_pct: number | null;
  signal_mae_pct: number | null;
  outcome_quality: string;
  pending_reason:
    | "not_due"
    | "ready_to_reconcile"
    | "awaiting_daily_bar"
    | string
    | null;
  limitations: Array<Record<string, unknown>>;
};

export type WatchlistRadarV2OutcomeSummaryRead = {
  status: string;
  group_id: number;
  mode: string;
  snapshot_date: string | null;
  horizon_trading_days: number;
  rule_version: string;
  outcome_contract_version: string;
  total_count: number;
  finalized_count: number;
  pending_count: number;
  latest_available_trade_date: string | null;
  last_reconciled_at: string | null;
  pending_reason_counts: Record<string, number>;
  summary_state_counts: Record<string, number>;
  items: WatchlistRadarV2OutcomeItemRead[];
  data_limitations: string[];
};

export type Signal = {
  key: string;
  label: string;
  direction: string;
  level: string;
  message: string;
  value: number | null;
  reference: number | null;
};

export type SignalItem = {
  stock_id: string;
  stock_name: string | null;
  time: string | null;
  close: number | null;
  volume: number | null;
  change_pct: number | null;
  score: number;
  status: string;
  signals: Signal[];
  error_message: string | null;
};

export type SignalsResponse = {
  group_id: number;
  include_children: boolean;
  requested_stock_count: number;
  bullish_count: number;
  bearish_count: number;
  neutral_count: number;
  no_data_count: number;
  error_count: number;
  results: SignalItem[];
};

export type IndicatorItem = {
  stock_id: string;
  stock_name: string | null;
  time: string | null;
  close: number | null;
  volume: number | null;
  change: number | null;
  change_pct: number | null;
  ma: Record<string, number | null>;
  volume_ma: Record<string, number | null>;
  status: string;
  error_message: string | null;
};

export type IndicatorsResponse = {
  group_id: number;
  include_children: boolean;
  requested_stock_count: number;
  success_count: number;
  no_data_count: number;
  error_count: number;
  results: IndicatorItem[];
};

export type ChartPoint = {
  time: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  trade_value: number | null;
  transaction_count: number | null;
};

export type OhlcIntradayOverlay = {
  source: string | null;
  trade_date: string;
  point_count: number;
  latest_time: string | null;
  previous_close: number | null;
  provisional: boolean;
};

export type OhlcChartResponse = {
  stock_id: string;
  timeframe: "daily" | "weekly" | "monthly";
  bars: number;
  lookback_days: number;
  from_date: string;
  to_date: string;
  point_count: number;
  points: ChartPoint[];
  backfill: Record<string, unknown> | null;
  intraday_overlay: OhlcIntradayOverlay | null;
  volume_unit: "shares" | string | null;
  volume_semantics: string;
  volume_status: "available" | "not_provided" | string;
  data_quality?: "ok" | "partial" | "unavailable" | string;
  warnings?: string[];
  latest_data_date: string | null;
  latest_finalized_data_date: string | null;
  expected_data_date: string | null;
  freshness_status: "current" | "stale" | "missing" | "future" | string;
  is_current: boolean;
  refresh_recommended: boolean;
};

export type MarketBreadth = {
  market: string;
  version?: string | null;
  state_contract_version?: string | null;
  status?: string | null;
  market_session?: string | null;
  price_semantics?: string | null;
  decision_usable?: boolean;
  is_provisional?: boolean;
  scope?: "full_market" | "registered_universe" | "local_dataset" | string | null;
  label?: string | null;
  trade_date: string | null;
  as_of?: string | null;
  snapshot_as_of?: string | null;
  oldest_price_as_of?: string | null;
  newest_price_as_of?: string | null;
  advance_count: number;
  decline_count: number;
  unchanged_count: number;
  total_count: number;
  limit_up_count: number | null;
  limit_down_count: number | null;
  trade_value: number | null;
  coverage_count?: number | null;
  classified_count?: number | null;
  coverage_ratio?: number | null;
  universe_definition?: Record<string, unknown> | null;
  unknown_count?: number | null;
  message_count?: number | null;
  missing_count?: number | null;
  warnings?: string[];
  source: string | null;
  trade_value_is_estimate?: boolean;
  trade_value_semantics?: string | null;
  trade_value_confidence?: string | null;
  auction_breadth?: {
    market: string;
    status: string;
    market_session: string;
    scope: string;
    trade_date: string | null;
    as_of: string | null;
    advance_count: number;
    decline_count: number;
    unchanged_count: number;
    coverage_count: number;
    unknown_count: number;
    universe_count: number;
    price_semantics: "auction_indicative" | string;
    is_provisional: boolean;
    decision_usable: false;
    source: string;
  } | null;
};

export type MarketBreadthStatus = {
  slot: "market_breadth" | string;
  status: "ready" | "partial" | "pending" | "failed" | string;
  scope: string | null;
  source: string | null;
  market_session?: string | null;
  decision_usable?: boolean;
  reason: string | null;
  warnings: string[];
};

export type MarketIndexSnapshot = {
  index_id: string;
  label: string;
  short_label: string;
  market: string;
  symbol: string;
  source: string;
  as_of: string | null;
  time: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  estimated_volume: number | null;
  trade_value: number | null;
  estimated_trade_value: number | null;
  ma20: number | null;
  price_vs_ma20: number | null;
  point_count: number;
  points: ChartPoint[];
  breadth: MarketBreadth | null;
  breadth_status: MarketBreadthStatus;
  error_message: string | null;
};

export type MarketIndexSummary = {
  as_of: string;
  source: string;
  indices: MarketIndexSnapshot[];
  cache_status?:
    | "live"
    | "memory_cache"
    | "shared_cache"
    | "stale_memory_cache"
    | "stale_shared_cache"
    | "local_cache"
    | "unknown";
  refresh_recommended?: boolean;
  warnings?: string[];
};

export type MarketChipResourceStatus = {
  resource: string;
  status: "ready" | "partial" | "stale" | "missing" | "not_available" | string;
  data_date: string | null;
  expected_data_date: string | null;
  pending_trade_date: string | null;
  source: string | null;
  reason: string | null;
  coverage_count: number | null;
  total_count: number | null;
  warnings: string[];
};

export type MarketChipDaily = {
  id: number;
  index_id: string;
  market: string;
  trade_date: string;
  close_value: number | null;
  price_change: number | null;
  price_change_pct: number | null;
  trade_value: number | null;
  foreign_futures_net_oi: number | null;
  foreign_futures_net_oi_change: number | null;
  retail_futures_net_oi: number | null;
  retail_futures_net_oi_change: number | null;
  put_volume: number | null;
  call_volume: number | null;
  put_call_volume_ratio_pct: number | null;
  put_open_interest: number | null;
  call_open_interest: number | null;
  put_call_open_interest_ratio_pct: number | null;
  total_institutional_net_value: number | null;
  foreign_investor_net_value: number | null;
  investment_trust_net_value: number | null;
  dealer_net_value: number | null;
  dealer_self_net_value: number | null;
  dealer_hedge_net_value: number | null;
  government_bank_net_value: number | null;
  margin_balance_change_value: number | null;
  margin_balance_change_shares: number | null;
  short_balance_change_shares: number | null;
  margin_status: MarketChipResourceStatus;
  government_bank_status: MarketChipResourceStatus;
  source_grade: string;
  source_details: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type TaiwanFuturesMarketStatus = {
  status: "open" | "closed" | string;
  is_open: boolean;
  phase: string;
  reason: string;
  timezone: string;
  checked_at: string;
  holiday_name: string | null;
  regular_session: string;
  after_hours_session: string;
  current_session: string | null;
  current_session_start_at: string | null;
  current_session_end_at: string | null;
  last_session: string | null;
  last_session_start_at: string | null;
  last_session_end_at: string | null;
  next_session: string | null;
  next_session_start_at: string | null;
  next_session_end_at: string | null;
};

export type TaiwanFuturesQuote = {
  id: number;
  provider: string;
  market: string;
  symbol: string;
  product_code: string;
  product_name: string;
  contract_symbol: string;
  contract_month: string | null;
  session: string;
  trade_date: string | null;
  quote_time: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  last_price: number | null;
  reference_price: number | null;
  settlement_price: number | null;
  change: number | null;
  change_pct: number | null;
  amplitude_pct: number | null;
  total_volume: number | null;
  open_interest: number | null;
  bid_price: number | null;
  bid_size: number | null;
  ask_price: number | null;
  ask_size: number | null;
  source: string;
  source_url: string | null;
  fetched_at: string;
  freshness: {
    status: "live" | "closed" | "cached" | "session_mismatch" | "stale" | string;
    is_live: boolean;
    is_stale: boolean;
    is_session_mismatch: boolean;
    expected_session: string;
    age_seconds: number | null;
    message: string;
    source_error: string | null;
    last_session_quote_lag_seconds: number | null;
    market_status: TaiwanFuturesMarketStatus;
  };
  created_at: string;
  updated_at: string;
};

export type TaiwanFuturesDailyBar = {
  id: number;
  provider: string;
  market: string;
  symbol: string;
  product_code: string;
  product_name: string;
  contract_symbol: string;
  contract_month: string;
  trade_date: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  settlement_price: number | null;
  change: number | null;
  change_pct: number | null;
  after_hours_volume: number | null;
  regular_volume: number | null;
  total_volume: number | null;
  open_interest: number | null;
  bid_price: number | null;
  ask_price: number | null;
  historical_high_price: number | null;
  historical_low_price: number | null;
  source: string;
  source_url: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type TaiwanFuturesDailyRefresh = {
  status: "success" | "partial" | "failed";
  symbol: string;
  requested_end_date: string;
  effective_end_date: string;
  latest_released_trade_date: string;
  release_time: string;
  skipped_unreleased_end_date: boolean;
  refreshed_row_count: number;
  warning: string | null;
  rows: TaiwanFuturesDailyBar[];
};

export type TaiwanFuturesIntradayBar = {
  id: number;
  provider: string;
  market: string;
  symbol: string;
  product_code: string;
  product_name: string;
  contract_symbol: string;
  contract_month: string | null;
  session: string;
  interval: string;
  bar_time: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  total_volume: number | null;
  open_interest: number | null;
  source: string;
  source_url: string | null;
  created_at: string;
  updated_at: string;
};

export type MarketIndexListItem = {
  rank: number;
  market: string;
  name: string;
  close: number | null;
  change: number | null;
  change_pct: number | null;
  trade_date: string | null;
};

export type MarketIndexListResponse = {
  market: string;
  source: string;
  as_of: string;
  count: number;
  items: MarketIndexListItem[];
};

export type MarketIndexContributionItem = {
  rank: number;
  stock_id: string;
  stock_name: string | null;
  close: number | null;
  change: number | null;
  change_pct: number | null;
  contribution_points: number | null;
  market_value_change: number | null;
  trade_value: number | null;
};

export type MarketIndexContributionResponse = {
  index_id: string;
  market: string;
  source: string;
  method: string;
  as_of: string;
  trade_date: string | null;
  index_close: number | null;
  index_change: number | null;
  total_market_value: number | null;
  positive: MarketIndexContributionItem[];
  negative: MarketIndexContributionItem[];
};

export type IntradayTrendPoint = {
  time: string;
  session?: string;
  price: number;
  volume: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  cumulative_volume?: number | null;
  trade_value?: number | null;
  close?: number | null;
  bar_type?: string | null;
  source_event_type?: string | null;
  market_event?: string | null;
  finalized?: boolean | null;
  is_partial?: boolean | null;
  display_eligible?: boolean | null;
  indicator_eligible?: boolean | null;
  price_semantics?: string | null;
  volume_status?: string | null;
  trade_value_status?: string | null;
};

export type IntradayPriceDiagnostics = {
  history_price_source: string | null;
  latest_history_time: string | null;
  latest_history_price: number | null;
  latest_actual_trade_time: string | null;
  latest_actual_trade_price: number | null;
  current_price_source: string | null;
  lag_seconds: number | null;
  current_trade_available: boolean;
  current_trade_unavailable_reason: string | null;
  current_price_applied_to_history: boolean;
};

export type IntradayTrendCapabilities = {
  supports_volume: boolean;
  supports_vwap: boolean;
  supports_price_limit: boolean;
  supports_quote_depth: boolean;
};

export type IntradayCurrentObservation = {
  value: number | null;
  observed_at: string | null;
  confirmed_at: string | null;
  price_semantics: string;
  provider: string | null;
  freshness_status: string;
  decision_usable: boolean;
};

export type StockVolumePaceBaseline = {
  requested_days: number;
  sample_days: number;
  minimum_display_sample_days: number;
  median_cumulative_volume: number | null;
  pace_ratio: number | null;
  difference_pct: number | null;
  history_trade_dates: string[];
};

export type StockVolumePace = {
  kind: string;
  stock_id: string;
  market: string;
  session_scope: "regular";
  status: "ready" | "partial" | "empty";
  as_of: string | null;
  trade_date: string | null;
  comparison_minute: string | null;
  current_cumulative_volume: number | null;
  same_time_baseline_5d: StockVolumePaceBaseline;
  same_time_baseline_20d: StockVolumePaceBaseline;
  warnings: string[];
};

export type USIntradaySourceStatus = {
  provider: string;
  status: "ok" | "degraded" | "unavailable";
  freshness_status:
    | "current"
    | "delayed"
    | "stale"
    | "off_session"
    | "missing"
    | "provider_error";
  market_phase: string | null;
  is_live_window: boolean;
  as_of: string | null;
  lag_seconds: number | null;
  is_fallback: boolean;
  has_usable_data: boolean;
  message: string | null;
};

export type IntradayTrendResponse = {
  stock_id: string;
  symbol: string | null;
  source: string;
  provider?: string | null;
  interval?: string | null;
  source_interval?: string | null;
  effective_interval?: string | null;
  source_point_count?: number | null;
  aggregation_method?: string | null;
  bar_finalization_status?: string | null;
  trade_date?: string | null;
  coverage_status?: string | null;
  session_scope?: string;
  session_phase?: string | null;
  has_extended_hours?: boolean;
  regular_point_count?: number;
  extended_point_count?: number;
  previous_close: number | null;
  previous_close_source?: string | null;
  previous_close_trade_date?: string | null;
  previous_close_provider?: string | null;
  expected_previous_close_trade_date?: string | null;
  previous_close_status?: "current" | "missing" | "unknown" | string;
  rejected_previous_close_trade_date?: string | null;
  regular_session_close?: number | null;
  regular_session_close_time?: string | null;
  regular_session_close_source?: string | null;
  regular_session_close_provider?: string | null;
  point_count: number;
  points: IntradayTrendPoint[];
  volume_pace?: StockVolumePace | null;
  source_status?: USIntradaySourceStatus | null;
  as_of?: string | null;
  total_volume?: number | null;
  volume_unit?: string;
  volume_semantics?: string;
  trade_value_unit?: string;
  is_partial?: boolean;
  source_url?: string | null;
  warnings?: string[];
  fetched_pages?: number;
  polling_interval_seconds?: number | null;
  bar_contract_version?: string | null;
  bar_type_counts?: Record<string, number>;
  partial_bar_count?: number;
  finalized_bar_count?: number;
  indicator_eligible_count?: number;
  post_close_summary_count?: number;
  history_price_source?: string | null;
  latest_history_time?: string | null;
  latest_history_price?: number | null;
  latest_actual_trade_time?: string | null;
  latest_actual_trade_price?: number | null;
  current_price_source?: string | null;
  lag_seconds?: number | null;
  current_trade_available?: boolean;
  current_trade_unavailable_reason?: string | null;
  current_price_applied_to_history?: boolean;
  capabilities?: IntradayTrendCapabilities;
  current_observation?: IntradayCurrentObservation | null;
  observations?: IntradayCurrentObservation[];
};

export type TaiwanStockQuoteDepthLevel = {
  level: number;
  price: number | null;
  size_lots: number | null;
};

export type TaiwanStockQuoteDepthFreshness = {
  status: string;
  is_live: boolean;
  is_stale: boolean;
  age_seconds: number | null;
  expected_trade_date: string | null;
  message: string;
  source_error: string | null;
};

export type TaiwanStockQuoteDepthPreviewMode = "preopen" | "live";

export type TaiwanStockQuoteVolumeReconciliationRead = {
  reference_dataset: string;
  reference_source: string | null;
  reference_trade_date: string | null;
  reference_volume_shares: number | null;
  reference_volume_scope: string;
  snapshot_trade_date: string | null;
  snapshot_volume_shares: number | null;
  snapshot_volume_scope: string;
  difference_shares: number | null;
  difference_pct: number | null;
  difference_semantics: string;
  tolerance_pct: number | null;
  status: "scope_different" | "not_comparable" | "mismatch" | string;
  reason: string | null;
  decision_usable: boolean;
};

export type TaiwanStockQuoteDepthRead = {
  stock_id: string;
  stock_name: string | null;
  market: string | null;
  provider: string;
  source: string;
  source_url: string | null;
  source_chain?: string[];
  primary_provider?: string | null;
  primary_source_status?: string | null;
  primary_source_error?: string | null;
  fallback_reason?: string | null;
  fallback_used?: boolean;
  exchange_channel: string | null;
  session_phase: string;
  presentation_trade_date?: string | null;
  presentation_session_state?: string;
  presentation_session_transition_at?: string | null;
  market_calendar_phase?: string;
  instrument_phase?: string;
  observation_reason_code?: string | null;
  actual_trade_reason_code?: string | null;
  observation_semantics?: string;
  phase_label: string;
  trade_date: string | null;
  quote_time: string | null;
  fetched_at: string | null;
  last_price: number | null;
  previous_close: number | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  change: number | null;
  change_pct: number | null;
  total_volume_lots: number | null;
  cumulative_volume_lots?: number | null;
  cumulative_volume_shares?: number | null;
  last_trade_volume_lots?: number | null;
  last_trade_volume_shares?: number | null;
  lot_size?: number;
  volume_unit?: string;
  canonical_volume_unit?: string;
  provider_volume_unit?: string;
  volume_semantics?: string;
  volume_scope?: string;
  volume_source?: string;
  volume_source_field?: string;
  volume_status?: string;
  provider_volume_available?: boolean;
  last_trade_volume_semantics?: string;
  last_trade_volume_source_field?: string;
  last_trade_volume_status?: string;
  official_daily_volume_shares?: number | null;
  official_daily_volume_trade_date?: string | null;
  official_daily_volume_source?: string | null;
  official_daily_volume_scope?: string;
  volume_includes_odd_lot?: boolean | null;
  volume_includes_after_hours?: boolean | null;
  volume_includes_closing_auction?: boolean | null;
  volume_reconciliation?: TaiwanStockQuoteVolumeReconciliationRead | null;
  volume_decision_usable?: boolean;
  best_bid_price: number | null;
  best_bid_size_lots: number | null;
  best_ask_price: number | null;
  best_ask_size_lots: number | null;
  bid_total_size_lots: number | null;
  ask_total_size_lots: number | null;
  spread: number | null;
  spread_pct: number | null;
  bid_levels: TaiwanStockQuoteDepthLevel[];
  ask_levels: TaiwanStockQuoteDepthLevel[];
  depth_available: boolean;
  auction_book_available?: boolean;
  auction_book_status?: string;
  auction_book_time?: string | null;
  auction_best_bid?: number | null;
  auction_best_ask?: number | null;
  auction_indicative_available?: boolean;
  auction_indicative_status?: string;
  auction_indicative_source?: string | null;
  auction_phase?: string | null;
  auction_event_time?: string | null;
  indicative_match_available?: boolean;
  indicative_match_price?: number | null;
  indicative_match_volume_lots?: number | null;
  indicative_match_price_source_field?: string | null;
  indicative_match_volume_source_field?: string | null;
  indicative_match_status_source_field?: string | null;
  actual_trade_occurred?: boolean;
  actual_trade_price_cached?: boolean;
  actual_trade_price_source?: string | null;
  actual_trade_price_as_of?: string | null;
  quote_semantics?: string;
  delivery_status?: string;
  price_available?: boolean;
  session_close_available?: boolean;
  session_close_status?: string;
  session_close_price?: number | null;
  session_close_trade_date?: string | null;
  session_close_event_time?: string | null;
  session_close_confirmed_at?: string | null;
  official_close_available?: boolean;
  official_close_status?: string;
  official_close_price?: number | null;
  official_close_trade_date?: string | null;
  freshness: TaiwanStockQuoteDepthFreshness;
};

export type TaiwanRealtimeQuoteLeaseRead = {
  lease_id: string | null;
  stock_id: string;
  provider: string;
  owner_kind: "frontend_viewer" | "acceptance_probe";
  status: string;
  expires_in_seconds: number | null;
  fallback_source: string;
  message: string;
  error: string | null;
};

export type TaiwanRealtimeTradeRead = {
  event_id: string;
  sequence: number;
  event_time: string | null;
  received_at: string;
  manager_ingested_at: string | null;
  session_phase: string | null;
  provider_delay_raw: unknown;
  provider_delay_unit: "unknown";
  price: number;
  volume_lots: number;
  total_volume_lots: number | null;
  amount: number | null;
  price_direction: "up" | "down" | "flat" | string;
  direction_semantics: string;
};

export type TaiwanRealtimeAuctionObservationRead = {
  event_id: string;
  sequence: number;
  event_time: string | null;
  received_at: string;
  manager_ingested_at: string | null;
  session_phase: string | null;
  provider_delay_raw: unknown;
  provider_delay_unit: "unknown";
  indicative_match_price: number | null;
  indicative_match_volume_lots: number | null;
  best_bid_price: number | null;
  best_ask_price: number | null;
  top5_bid_volume_lots: number | null;
  top5_ask_volume_lots: number | null;
  top5_imbalance: number | null;
  diff_bid_volume_lots: Array<number | null>;
  diff_ask_volume_lots: Array<number | null>;
  semantics: string;
};

export type TaiwanRealtimeMinuteKBarRead = {
  event_id: string;
  sequence: number;
  event_time: string;
  received_at: string;
  timeframe_minutes: number;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume_lots: number | null;
  average_price: number | null;
  total_amount: number | null;
};

export type TaiwanRealtimeDepthMetricsRead = {
  event_time: string | null;
  received_at: string;
  best_bid_price: number | null;
  best_ask_price: number | null;
  spread: number | null;
  spread_pct: number | null;
  top5_bid_volume_lots: number | null;
  top5_ask_volume_lots: number | null;
  top5_imbalance: number | null;
  top5_imbalance_formula: string | null;
  diff_bid_volume_lots: Array<number | null>;
  diff_ask_volume_lots: Array<number | null>;
  simtrade: boolean;
};

export type TaiwanRealtimeDepthLevelRead = {
  level: number;
  price: number | null;
  price_state: string;
  size_shares: number | null;
  size_lots: number | null;
};

export type TaiwanRealtimeDepthRead = {
  provider: string;
  source: string;
  capability: string;
  state: string;
  event_time: string | null;
  received_at: string | null;
  manager_ingested_at: string | null;
  stream_sampled_at: string;
  freshness_status: string;
  is_stale: boolean;
  age_seconds: number | null;
  bid_levels: TaiwanRealtimeDepthLevelRead[];
  ask_levels: TaiwanRealtimeDepthLevelRead[];
};

export type TaiwanRealtimeLatencyRead = {
  event_at: string | null;
  bridge_received_at: string | null;
  manager_ingested_at: string | null;
  stream_sampled_at: string;
  event_to_bridge_ms: number | null;
  bridge_to_manager_ms: number | null;
  manager_to_stream_ms: number | null;
  event_to_stream_ms: number | null;
  provider_delay_raw: unknown;
  provider_delay_unit: "unknown";
  provider_delay_semantics: "provider_reported_raw_value_unit_not_verified";
};

export type TaiwanRealtimeCallbackDiagnosticRead = {
  sequence: number;
  event_time: string | null;
  received_at: string;
  manager_ingested_at: string | null;
  session_phase: string | null;
  provider_trial_flag: boolean;
  actual_trade_evidence: boolean;
  cumulative_volume_lots: number | null;
  previous_cumulative_volume_lots: number | null;
  cumulative_relation:
    | "baseline"
    | "advanced"
    | "unchanged"
    | "decreased"
    | "missing"
    | "invalid"
    | "cross_date_rejected";
  projection_action:
    | "baseline_only"
    | "trade_added"
    | "auction_added"
    | "same_cumulative_suppressed"
    | "decreasing_cumulative_suppressed"
    | "trade_signature_suppressed"
    | "auction_signature_suppressed"
    | "non_trade_suppressed"
    | "cross_date_rejected";
  projection_event_id: string | null;
};

export type TaiwanRealtimeDiagnosticCountersRead = {
  callback_count: number;
  baseline_only_count: number;
  cumulative_advanced_count: number;
  same_cumulative_count: number;
  decreasing_cumulative_count: number;
  missing_cumulative_count: number;
  invalid_cumulative_count: number;
  trade_addition_count: number;
  auction_addition_count: number;
  trade_signature_suppression_count: number;
  auction_signature_suppression_count: number;
  non_trade_suppression_count: number;
  trial_leak_count: number;
  cross_date_rejected_count: number;
};

export type TaiwanRealtimeMarketStreamRead = {
  projection_scope: "presentation_only";
  canonical_truth: false;
  decision_usable: false;
  research_usable: false;
  provider_specific: true;
  kind: string;
  contract_version: string;
  stock_id: string;
  provider: string;
  source: string;
  status: string;
  active_leases: number;
  sequence: number;
  generated_at: string;
  event_time: string | null;
  received_at: string | null;
  session_phase: string | null;
  selection_reason: string;
  fallback_used: boolean;
  is_stale: boolean;
  capability_status: Record<string, string>;
  limits: Record<string, number>;
  recent_trades: TaiwanRealtimeTradeRead[];
  auction_observations: TaiwanRealtimeAuctionObservationRead[];
  minute_kbars: TaiwanRealtimeMinuteKBarRead[];
  depth_metrics: TaiwanRealtimeDepthMetricsRead | null;
  depth: TaiwanRealtimeDepthRead | null;
  latency: TaiwanRealtimeLatencyRead | null;
  diagnostic_counters: TaiwanRealtimeDiagnosticCountersRead;
  diagnostic_events: TaiwanRealtimeCallbackDiagnosticRead[];
  warnings: string[];
};

export type TaiwanQuoteContractReplaySnapshotRead = {
  capture_slot: string;
  status: string;
  scheduled_at: string | null;
  captured_at: string | null;
  quote_time: string | null;
  freshness_status: string | null;
  refresh_outcome: string | null;
  error: string | null;
  quote: TaiwanStockQuoteDepthRead | null;
};

export type TaiwanQuoteContractReplayRead = {
  kind: string;
  stock_id: string;
  trade_date: string | null;
  timezone: string;
  required_slots: string[];
  required_count: number;
  captured_count: number;
  coverage_ratio: number;
  complete: boolean;
  missing_slots: string[];
  snapshots: TaiwanQuoteContractReplaySnapshotRead[];
  source: string;
  replay_semantics: string;
  read_path_side_effects: boolean;
};

export type IntradayHistoryResponse = {
  stock_id: string;
  symbol: string | null;
  interval: "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | string;
  range: string;
  provider: string;
  source: string;
  from_time: string | null;
  to_time: string | null;
  point_count: number;
  cached_count: number;
  refreshed_count: number;
  read_policy?: "cache_only" | string;
  acquisition_status?: string | null;
  resolved_health?: Record<string, unknown> | null;
  candidate_rejections?: Array<Record<string, unknown>>;
  limitations?: string[];
  component_raw_result_ids?: string[];
  calculation_versions?: string[];
  points: ChartPoint[];
};

export type StockTechnicalReportRow = {
  key: string;
  label: string;
  description: string;
  value: unknown;
  display_value: string;
  direction: number | null;
  tone: "positive" | "negative" | "neutral" | "warning" | string;
  basis: string;
  source: string;
};

export type StockTechnicalReportBadge = {
  label: string;
  tone: "positive" | "negative" | "neutral" | "warning" | string;
};

export type StockTechnicalReportRead = {
  kind: string;
  stock_id: string;
  timeframe: "today" | "daily" | "weekly" | "monthly";
  phase: string;
  confidence: "low" | "medium" | "high" | string;
  generated_at: string;
  title: string;
  summary: string;
  score: number;
  value: number | null;
  value_label: string;
  rows: StockTechnicalReportRow[];
  badges: StockTechnicalReportBadge[];
  data: Record<string, unknown>;
  missing: string[];
  warnings: string[];
  source_refs: Array<Record<string, string>>;
};

export type OvernightImpactSymbolMove = {
  symbol: string;
  change_pct: number | null;
};

export type OvernightImpactFactor = {
  key: string;
  symbol: string;
  label: string;
  role: string;
  trade_date: string | null;
  close: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  score_change_pct: number | null;
  weight: number;
  normalized_weight: number | null;
  weighted_contribution: number | null;
  tone: string;
  source: string;
  provider: string | null;
};

export type OvernightImpactBasket = {
  group_id: number;
  group_name: string;
  role: string;
  trade_date: string | null;
  symbol_count: number;
  valid_count: number;
  missing_count: number;
  average_change_pct: number | null;
  score_change_pct: number | null;
  weight: number;
  normalized_weight: number | null;
  weighted_contribution: number | null;
  tone: string;
  top_symbols: OvernightImpactSymbolMove[];
  bottom_symbols: OvernightImpactSymbolMove[];
  source: string;
};

export type AdrParityRead = {
  kind: string;
  status: "ready" | "partial" | "stale" | string;
  is_current: boolean;
  stock_id: string;
  stock_name: string | null;
  mapping: {
    stock_id: string;
    stock_name: string;
    adr_symbol: string;
    adr_name: string;
    adr_exchange: string;
    local_shares_per_adr: number;
    source_label: string;
    source_url: string;
    verified_on: string;
  };
  mapping_resolution?: {
    selected_source: string;
    registry_status: string;
    shadow_status: string;
    shadow_differences: string[];
    relation_id: number | null;
    relation_version: number | null;
    relation_valid_from: string | null;
    relation_valid_to: string | null;
    relation_verified_at: string | null;
    evidence_ids: number[];
    registry_schema_version: string | null;
    warnings: string[];
    limitations: string[];
  } | null;
  formula: string;
  adr_close_usd: number | null;
  adr_trade_date: string | null;
  adr_provider: string | null;
  expected_adr_trade_date: string | null;
  usd_twd: number | null;
  fx_source_symbol: string | null;
  fx_provider: string | null;
  fx_as_of: string | null;
  fx_age_seconds: number | null;
  fx_freshness?: {
    purpose?: string;
    status?: string;
    usable?: boolean;
    session_status?: string;
    expected_data_date?: string | null;
    actual_data_date?: string | null;
    next_expected_update_at?: string | null;
    refresh_eligible?: boolean;
    reason_codes?: string[];
  } | null;
  tw_reference_price_twd: number | null;
  tw_reference_trade_date: string | null;
  target_tw_trade_date: string | null;
  implied_tw_price_twd: number | null;
  implied_gap_pct: number | null;
  parity_adr_price_usd: number | null;
  tw_comparison_price_twd: number | null;
  tw_comparison_trade_date: string | null;
  tw_comparison_as_of: string | null;
  tw_comparison_source: string | null;
  tw_session_phase: string | null;
  comparison_mode: string;
  remaining_gap_pct: number | null;
  missing: string[];
  warnings: string[];
  source_refs: Array<Record<string, string>>;
  freshness: Record<string, unknown>;
};

export type CrossMarketInstrumentRef = {
  market: string;
  instrument_type: string;
  canonical_symbol: string;
  provider_symbol: string | null;
  exchange: string | null;
  currency: string | null;
};

export type CrossMarketContextSignal = {
  signal_id: string;
  relation_id: number | null;
  relation_version: number | null;
  source: CrossMarketInstrumentRef;
  target: CrossMarketInstrumentRef;
  bucket: string;
  relation_type: string;
  relation_subtype?: string | null;
  event_context?: string | null;
  calculation: Record<string, unknown>;
  direction: string;
  configured_weight: number;
  quality_multiplier: number;
  effective_weight: number;
  normalized_weight: number | null;
  contribution: number | null;
  status: string;
  decision_usable: boolean;
  confidence_tier: string;
  freshness: Record<string, unknown>;
  evidence_refs: string[];
  source_refs: Array<Record<string, string>>;
  warnings: string[];
  limitations: string[];
  excluded_reason: string | null;
};

export type CrossMarketTargetContextRead = {
  kind: "cross_market_target_context" | string;
  schema_version: "cross_market.context.v1" | string;
  target: CrossMarketInstrumentRef;
  status: string;
  decision_usable: boolean;
  as_of: string | null;
  decision_at: string;
  methodology_version: string;
  relation_snapshot_version: string;
  snapshot_id: string;
  summary: {
    stance: string;
    score: number | null;
    confidence: string;
    title: string;
    reason_codes: string[];
  };
  direct_equivalents: AdrParityRead[];
  signals: CrossMarketContextSignal[];
  bucket_scores: Record<string, number | null>;
  coverage: {
    configured_signal_count: number;
    available_signal_count: number;
    decision_usable_signal_count: number;
    configured_weight: number;
    available_weight: number;
    decision_usable_weight: number;
    coverage_ratio: number;
    excluded_by_reason: Record<string, number>;
  };
  freshness: Record<string, unknown>;
  missing: string[];
  warnings: string[];
  limitations: string[];
  source_refs: Array<Record<string, string>>;
  evidence_passport: Record<string, unknown>;
};

export type FxTrendRead = {
  status: string;
  source_symbol: string | null;
  provider: string | null;
  usd_twd: number | null;
  data_date: string | null;
  as_of: string | null;
  age_seconds: number | null;
  freshness: {
    purpose?: string;
    status?: string;
    usable?: boolean;
    session_status?: string;
    expected_data_date?: string | null;
    actual_data_date?: string | null;
    next_expected_update_at?: string | null;
    refresh_eligible?: boolean;
    reason_codes?: string[];
  };
  history_points: number;
  observed_history_points?: number;
  excluded_provisional_points?: number;
  usd_twd_change_1d_pct: number | null;
  usd_twd_change_5d_pct: number | null;
  usd_twd_change_20d_pct: number | null;
  twd_change_1d_pct: number | null;
  twd_change_5d_pct: number | null;
  twd_change_20d_pct: number | null;
  regime: string;
};

export type ForeignFlowWindowRead = {
  days: number;
  available_days: number;
  net_value_twd: number | null;
  turnover_twd: number | null;
  turnover_ratio_pct: number | null;
  net_shares: number | null;
};

export type ForeignFlowRead = {
  scope: string;
  status: string;
  state: string;
  state_basis_days: number | null;
  trade_date: string | null;
  expected_trade_date: string;
  windows: ForeignFlowWindowRead[];
};

export type FxFlowContextRead = {
  kind: string;
  status: "ready" | "partial" | "stale" | string;
  is_current: boolean;
  stock_id: string;
  signal: string;
  signal_horizon_days: number;
  causality: string;
  fx: FxTrendRead;
  market_foreign: ForeignFlowRead;
  stock_foreign: ForeignFlowRead;
  missing: string[];
  warnings: string[];
  source_refs: Array<Record<string, string>>;
  freshness: Record<string, unknown>;
};

export type TaiwanNextSessionPlanStatus =
  | "ready"
  | "partial"
  | "pending"
  | "stale"
  | "missing"
  | "not_applicable";

export type TaiwanNextSessionPlanLevelRead = {
  key: string;
  period: number;
  transition_price: number;
  current_ma: number | null;
  projected_ma_if_flat: number;
  drift_if_flat: number | null;
  dropped_close: number | null;
  as_of_close_relation: "above" | "below" | "at";
  role_at_as_of_close: "support" | "reclaim" | "pivot";
  move_from_as_of_close_pct: number | null;
  required_close_count: number;
  available_close_count: number;
  window_start_date: string;
  window_end_date: string;
  candidate_price_semantics: string;
  comparison_rule: string;
};

export type TaiwanNextSessionScenarioZoneRead = {
  key: string;
  lower_bound: number | null;
  upper_bound: number | null;
  lower_bound_rule: "inclusive" | "exclusive" | null;
  upper_bound_rule: "inclusive" | "exclusive" | null;
  at_or_above_level_keys: string[];
  below_level_keys: string[];
};

export type TaiwanNextSessionPlanRead = {
  kind: string;
  version: string;
  market: string;
  stock_id: string;
  stock_name: string | null;
  instrument_type: string | null;
  currency: string;
  price_unit: string;
  status: TaiwanNextSessionPlanStatus;
  generated_at: string;
  as_of_trade_date: string | null;
  target_trade_date: string | null;
  target_session_state:
    | "unavailable"
    | "upcoming"
    | "active"
    | "completed_waiting_refresh"
    | "expired";
  as_of_close: number | null;
  methodology: {
    id: string;
    version: string;
    price_series: string;
    candidate_price_semantics: string;
    transition_formula: string;
    projected_ma_formula: string;
    comparison_rule: string;
  };
  freshness: {
    status: "missing" | "current" | "stale" | "future";
    expected_trade_date: string;
    latest_trade_date: string | null;
    calendar_day_lag: number | null;
    trading_day_lag: number | null;
    release_time: string;
    release_timezone: string;
    checked_at: string;
  };
  history: {
    requested_limit: number;
    raw_row_count: number;
    distinct_trade_date_count: number;
    duplicate_trade_date_count: number;
    valid_close_count: number;
    first_trade_date: string | null;
    latest_trade_date: string | null;
    source_ids: number[];
    max_gap_days: number;
  };
  readiness: {
    status: TaiwanNextSessionPlanStatus;
    decision_usable: boolean;
    reason_codes: string[];
    available_level_keys: string[];
    missing_level_keys: string[];
  };
  levels: TaiwanNextSessionPlanLevelRead[];
  known_range: {
    period: number;
    support: number | null;
    resistance: number | null;
    previous_session_low: number | null;
    previous_session_high: number | null;
    previous_session_close: number | null;
    window_start_date: string | null;
    window_end_date: string | null;
    method: string;
  };
  scenario_zones: TaiwanNextSessionScenarioZoneRead[];
  corporate_action_adjustment: {
    status: "not_applied";
    event_check: "not_performed";
    price_series: string;
  };
  missing: string[];
  warning_codes: string[];
  warnings: string[];
  limitation_codes: string[];
  limitations: string[];
  source_refs: Array<{
    type: "table" | "calendar" | "derived";
    name: string;
  }>;
};

export type OvernightImpactRead = {
  kind: string;
  stock_id: string;
  stock_name: string | null;
  as_of: string | null;
  generated_at: string;
  stance: string;
  title: string;
  summary: string;
  score: number;
  weighted_change_pct: number | null;
  confidence: "low" | "medium" | "high" | string;
  tw_mapping: {
    stock_id: string;
    stock_name: string | null;
    market: string | null;
    industry: string | null;
    category: string | null;
    profiles: string[];
    reason: string;
  };
  adr_parity?: AdrParityRead | null;
  cross_market_context?: CrossMarketTargetContextRead | null;
  context_status?: string | null;
  decision_usable?: boolean | null;
  signals?: CrossMarketContextSignal[];
  bucket_scores?: Record<string, number | null>;
  coverage?: CrossMarketTargetContextRead["coverage"];
  methodology_version?: string | null;
  relation_snapshot_version?: string | null;
  snapshot_id?: string | null;
  limitations?: string[];
  source?: string | null;
  fx_flow_context?: FxFlowContextRead | null;
  refresh_decision?: {
    status?: string;
    should_execute?: boolean;
    reason?: string;
    planned_source_count?: number;
    deferred_source_count?: number;
    cooldown_source_count?: number;
  };
  refresh_plan?: Record<string, unknown>;
  factors: OvernightImpactFactor[];
  baskets: OvernightImpactBasket[];
  missing: string[];
  warnings: string[];
  source_refs: Array<Record<string, string>>;
  freshness: Record<string, unknown>;
  evidence_passport: Record<string, unknown>;
};

export type StockIndicatorPoint = {
  time: string;
  algorithm_version?: string | null;
  price_basis?: string | null;
  calculation_role?: string | null;
  parameter_contract?: Record<string, number | number[] | string | null>;
  bar_status?: string | null;
  session_close_finalization?: string | null;
  official_daily_confirmed?: boolean;
  event_time?: string | null;
  source?: string | null;
  volume_semantics?: string | null;
  indicator_semantics?: Record<string, string | null>;
  decision_usable?: boolean;
  volume_based_decision_usable?: boolean;
  warnings?: string[];
  close: number | null;
  volume: number | null;
  change: number | null;
  change_pct: number | null;
  ma: Record<string, number | null>;
  volume_ma: Record<string, number | null>;
  ema?: Record<string, number | null>;
  macd?: Record<string, number | null>;
  rsi?: Record<string, number | null>;
  atr?: Record<string, number | null>;
  adx?: Record<string, number | null>;
  roc?: Record<string, number | null>;
  mfi?: Record<string, number | null>;
  donchian?: Record<string, number | null>;
  bollinger?: Record<string, number | null>;
  kd?: Record<string, number | null>;
  pvo?: Record<string, number | null>;
  support_resistance?: Record<string, number | null>;
};

export type TaiwanDispositionStatusRead = {
  stock_id: string;
  checked_at: string;
  is_disposition: boolean;
  is_active: boolean;
  status: "active" | "upcoming" | "none" | string;
  cache_status: "current" | "degraded" | "stale" | "missing" | string;
  cache_fetched_at: string | null;
  warning: string | null;
  provider: string | null;
  market: string | null;
  source_url: string | null;
  announced_date: string | null;
  stock_name: string | null;
  start_date: string | null;
  end_date: string | null;
  matching_interval_minutes: number | null;
  reason: string | null;
  measure: string | null;
  requires_full_precollection: boolean;
  margin_trading_suspended: boolean;
  detail: string | null;
};

export type TaiwanCorporateEventRead = {
  event_id: string;
  event_type: "ex_dividend" | "financial_report" | "investor_conference" | string;
  timing_status: "scheduled" | "actual" | "deadline" | string;
  provider: string;
  market: string;
  source_name: string;
  source_url: string;
  stock_id: string;
  stock_name: string | null;
  start_date: string;
  end_date: string;
  start_time: string | null;
  title: string;
  summary: string | null;
  location: string | null;
  cash_dividend: number | null;
  stock_dividend_ratio: number | null;
  financial_report_related: boolean;
  related_event_id: string | null;
  company_url: string | null;
  video_url: string | null;
  status: "today" | "ongoing" | "upcoming" | "past" | string;
  days_until: number;
};

export type TaiwanCorporateEventSourceStatusRead = {
  provider: string;
  market: string;
  source: string;
  source_url: string;
  status: "current" | "degraded" | "stale" | "missing" | string;
  fetched_at: string | null;
  last_attempt_at: string | null;
  last_error: string | null;
  warning: string | null;
  coverage_start: string | null;
  coverage_end: string | null;
  entry_count: number;
};

export type TaiwanCorporateEventListRead = {
  kind: string;
  generated_at: string;
  as_of: string;
  date_from: string;
  date_to: string;
  stock_id: string | null;
  market: string | null;
  event_types: string[];
  result_count: number;
  warning: string | null;
  sources: Record<string, TaiwanCorporateEventSourceStatusRead>;
  results: TaiwanCorporateEventRead[];
};

export type TaiwanStockEventSummaryRead = {
  stock_id: string;
  checked_at: string;
  reminder_days: number;
  cache_status: "current" | "degraded" | "stale" | "missing" | string;
  cache_fetched_at: string | null;
  warning: string | null;
  result_count: number;
  results: TaiwanCorporateEventRead[];
};

export type TaiwanStockEventHistoryRead = {
  stock_id: string;
  checked_at: string;
  history_years: number;
  cache_status: "current" | "degraded" | "stale" | "missing" | string;
  cache_fetched_at: string | null;
  coverage_start: string | null;
  coverage_end: string | null;
  warning: string | null;
  total_count: number;
  result_count: number;
  results: TaiwanCorporateEventRead[];
};

export type StockMasterRead = {
  id: number;
  stock_id: string;
  stock_name: string | null;
  market: string;
  instrument_type: string;
  industry: string | null;
  category: string | null;
  is_active: boolean;
  notes: string | null;
  disposition: TaiwanDispositionStatusRead | null;
  upcoming_events: TaiwanStockEventSummaryRead | null;
  event_history: TaiwanStockEventHistoryRead | null;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
};

export type USStockMasterRead = {
  id: number;
  symbol: string;
  security_name: string | null;
  exchange: string | null;
  asset_type: string;
  listing_source: string;
  market_category: string | null;
  financial_status: string | null;
  cqs_symbol: string | null;
  nasdaq_symbol: string | null;
  cik: string | null;
  sec_company_name: string | null;
  is_etf: boolean | null;
  is_test_issue: boolean;
  round_lot_size: number | null;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
};

export type JPStockMasterRead = {
  id: number;
  symbol: string;
  local_code: string | null;
  security_name: string | null;
  exchange: string | null;
  market_segment: string | null;
  sector_33_code: string | null;
  sector_33_name: string | null;
  sector_17_code: string | null;
  sector_17_name: string | null;
  size_code: string | null;
  size_name: string | null;
  asset_type: string;
  listing_source: string;
  currency: string;
  exchange_timezone_name: string | null;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
};

export type JPWatchlistGroupNode = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  children: JPWatchlistGroupNode[];
};

export type JPWatchlistGroupRead = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type JPWatchlistItemRead = {
  id: number;
  group_id: number;
  symbol: string;
  local_code: string | null;
  security_name: string | null;
  exchange: string | null;
  market_segment: string | null;
  sector_33_name: string | null;
  asset_type: string | null;
  note: string | null;
  priority: number;
  tags: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type JPStockMasterSyncResultRead = {
  status: string;
  provider: string;
  source_url: string;
  scanned_count: number;
  created_count: number;
  updated_count: number;
  deactivated_count: number;
  message: string;
};

export type JPDailyPriceRead = {
  id: number;
  provider: string;
  symbol: string;
  trade_date: string;
  currency: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  adjusted_close: number | null;
  trade_volume: number | null;
  source_url: string | null;
  raw_payload_hash: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type JPDailyPriceRefreshResultRead = {
  status: string;
  provider: string;
  symbol: string;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string;
};

export type JPResourceRefreshResultRead = {
  status: string;
  provider: string;
  symbol: string;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string;
};

export type JPCompanyFundamentalRead = {
  id: number;
  provider: string;
  symbol: string;
  company_name: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  currency: string | null;
  market_cap: number | null;
  enterprise_value: number | null;
  trailing_pe: number | null;
  forward_pe: number | null;
  price_to_book: number | null;
  dividend_yield: number | null;
  beta: number | null;
  disclosed_date: string | null;
  fiscal_period: string | null;
  fiscal_year_end: string | null;
  document_type: string | null;
  eps_ttm: number | null;
  forward_eps: number | null;
  revenue_ttm: number | null;
  net_sales: number | null;
  operating_profit: number | null;
  ordinary_profit: number | null;
  profit: number | null;
  forecast_net_sales: number | null;
  forecast_operating_profit: number | null;
  forecast_ordinary_profit: number | null;
  forecast_profit: number | null;
  gross_margin: number | null;
  operating_margin: number | null;
  profit_margin: number | null;
  return_on_equity: number | null;
  return_on_assets: number | null;
  revenue_growth: number | null;
  earnings_growth: number | null;
  total_assets: number | null;
  equity: number | null;
  equity_to_asset_ratio: number | null;
  total_cash: number | null;
  total_debt: number | null;
  operating_cash_flow: number | null;
  investing_cash_flow: number | null;
  financing_cash_flow: number | null;
  debt_to_equity: number | null;
  current_ratio: number | null;
  quick_ratio: number | null;
  shares_outstanding: number | null;
  book_value: number | null;
  earnings_date: string | null;
  ex_dividend_date: string | null;
  source_url: string | null;
  raw_payload_hash: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type JPWatchlistResourceRefreshResultRead = {
  status: string;
  group_id: number | null;
  symbol_count: number;
  success_count: number;
  partial_success_count: number;
  skipped_count: number;
  error_count: number;
  symbol_error_count: number;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string | null;
};

export type JPWatchlistRankingItemRead = {
  rank: number;
  symbol: string;
  security_name: string | null;
  exchange: string | null;
  market_segment: string | null;
  sector_33_name: string | null;
  asset_type: string | null;
  group_id: number;
  trade_date: string | null;
  close: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  status: string;
  latest_fetched_at: string | null;
  freshness_status: "current" | "stale" | "missing" | "future" | string;
  source: string | null;
  error_message: string | null;
};

export type JPWatchlistRankingRead = {
  group_id: number | null;
  include_children: boolean;
  rank_by: string;
  sort_order: string;
  requested_symbol_count: number;
  ranked_count: number;
  no_data_count: number;
  error_count: number;
  trade_date: string | null;
  target_trade_date: string | null;
  is_current: boolean;
  current_symbol_count: number;
  stale_symbol_count: number;
  missing_symbol_count: number;
  future_symbol_count: number;
  coverage_status: "current" | "partial" | "missing" | string;
  refresh_recommended: boolean;
  results: JPWatchlistRankingItemRead[];
};

export type JPOhlcPointRead = {
  time: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
};

export type JPOhlcChartRead = {
  symbol: string;
  timeframe: string;
  bars: number;
  lookback_days: number;
  from_date: string;
  to_date: string;
  point_count: number;
  points: JPOhlcPointRead[];
  backfill: Record<string, unknown> | null;
  latest_data_date: string | null;
  expected_data_date: string | null;
  freshness_status: "current" | "stale" | "missing" | "future" | string;
  is_current: boolean;
  refresh_recommended: boolean;
};

export type JPMarketCoverageRead = {
  scope: string;
  active_stock_count: number;
  observed_symbol_count: number;
  current_symbol_count: number;
  stale_symbol_count: number;
  missing_symbol_count: number;
  active_coverage_ratio: number;
  observed_current_ratio: number;
  status: string;
  is_partial: boolean;
};

export type JPMarketBreadthRead = {
  trade_date: string | null;
  advance_count: number;
  decline_count: number;
  unchanged_count: number;
  no_comparison_count: number;
  total_count: number;
  coverage_count: number;
  source: string;
  is_partial: boolean;
};

export type JPMarketSectorBreadthRead = {
  sector: string;
  covered_count: number;
  advance_count: number;
  decline_count: number;
  unchanged_count: number;
  average_change_pct: number | null;
};

export type JPMarketIndexSnapshotRead = {
  symbol: string;
  label: string;
  role: string;
  latest_data_date: string | null;
  expected_data_date: string | null;
  freshness_status: string;
  is_current: boolean;
  close: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  provider: string | null;
  point_count: number;
};

export type JPMarketMoverRead = {
  symbol: string;
  security_name: string | null;
  sector: string | null;
  trade_date: string;
  close: number;
  previous_close: number;
  change: number;
  change_pct: number;
  volume: number | null;
  provider: string;
};

export type JPMarketOverviewRead = {
  kind: "jp_market_overview";
  generated_at: string;
  expected_trade_date: string;
  calendar_status: Record<string, unknown>;
  coverage: JPMarketCoverageRead;
  watchlist_coverage: Record<string, unknown>;
  breadth: JPMarketBreadthRead;
  sectors: JPMarketSectorBreadthRead[];
  indices: JPMarketIndexSnapshotRead[];
  top_gainers: JPMarketMoverRead[];
  top_losers: JPMarketMoverRead[];
  source_health: Record<string, unknown>;
  refresh_recommended: boolean;
  refresh_scope: string;
  warnings: string[];
};

export type JPResourceSlotRead = {
  key: string;
  status: "available" | "empty" | "planned" | string;
  available: boolean;
  source: string | null;
  latest_date: string | null;
  row_count: number;
  metrics?: Record<string, string | number | null>;
};

export type JPResourceSummaryRead = {
  symbol: string;
  slots: JPResourceSlotRead[];
};

export type KRStockMasterRead = {
  id: number;
  symbol: string;
  local_code: string | null;
  security_name: string | null;
  security_name_kr: string | null;
  exchange: string | null;
  market_segment: string | null;
  sector: string | null;
  industry: string | null;
  asset_type: string;
  listing_source: string;
  currency: string;
  exchange_timezone_name: string | null;
  is_active: boolean;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
};

export type KRWatchlistGroupNode = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  children: KRWatchlistGroupNode[];
};

export type KRWatchlistGroupRead = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type KRWatchlistItemRead = {
  id: number;
  group_id: number;
  symbol: string;
  local_code: string | null;
  security_name: string | null;
  security_name_kr: string | null;
  exchange: string | null;
  market_segment: string | null;
  sector: string | null;
  industry: string | null;
  asset_type: string | null;
  note: string | null;
  priority: number;
  tags: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type KRStockMasterSyncResultRead = {
  status: string;
  provider: string;
  source_url: string | null;
  scanned_count: number;
  created_count: number;
  updated_count: number;
  deactivated_count: number;
  message: string;
};

export type KRDailyPriceRefreshResultRead = {
  status: string;
  provider: string;
  symbol: string;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string;
};

export type KRMarketIndexRead = {
  id: number | null;
  index_id: string;
  provider_symbol: string;
  name: string;
  short_name: string;
  name_kr: string | null;
  market_segment: string;
  index_family: string;
  provider: string;
  currency: string;
  source_url: string | null;
  exchange_timezone_name: string;
  sort_order: number;
  is_active: boolean;
};

export type KRIndexRefreshResultRead = {
  status: string;
  provider: string;
  index_id: string;
  provider_symbol: string | null;
  from_date: string | null;
  to_date: string | null;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string;
};

export type KRMarketBreadthRead = {
  index_id: string;
  market_segment: string;
  trade_date: string | null;
  advance_count: number;
  decline_count: number;
  unchanged_count: number;
  total_count: number;
  positive_ratio: number | null;
  advance_decline_ratio: number | null;
  average_change_pct: number | null;
  trade_value: number | null;
  source: string | null;
  status: string;
  coverage_note: string | null;
};

export type KRMarketBreadthRefreshResultRead = {
  status: string;
  provider: string;
  market_id: string;
  trade_date: string | null;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string;
};

export type KRIndexSnapshotRead = KRMarketIndexRead & {
  latest_date: string | null;
  close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  latest_provider: string | null;
  latest_source_url: string | null;
  status: string;
  breadth: KRMarketBreadthRead | null;
};

export type KRIndexSummaryRead = {
  kind: string;
  generated_at: string;
  expected_daily_price_date: string | null;
  summary: {
    index_count: number;
    current_count: number;
    stale_count: number;
    empty_count: number;
  };
  indices: KRIndexSnapshotRead[];
};

export type KRResourceRefreshResultRead = {
  status: string;
  provider: string;
  symbol: string | null;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string;
};

export type KRCompanyFundamentalRead = {
  id: number;
  provider: string;
  symbol: string;
  corp_code: string | null;
  stock_code: string | null;
  company_name: string | null;
  fiscal_year: number | null;
  report_code: string | null;
  report_name: string | null;
  statement_name: string | null;
  account_name: string | null;
  account_id: string | null;
  current_amount: number | null;
  previous_amount: number | null;
  currency: string | null;
  disclosed_date: string | null;
  receipt_no: string | null;
  source_url: string | null;
  raw_payload_hash: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type KRInvestorTradeDailyRead = {
  id: number;
  provider: string;
  symbol: string;
  trade_date: string;
  investor_type: string;
  buy_value: number | null;
  sell_value: number | null;
  net_buy_value: number | null;
  buy_volume: number | null;
  sell_volume: number | null;
  net_buy_volume: number | null;
  source_url: string | null;
  raw_payload_hash: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type KRWatchlistRankingItemRead = {
  rank: number;
  symbol: string;
  security_name: string | null;
  exchange: string | null;
  market_segment: string | null;
  sector: string | null;
  industry: string | null;
  asset_type: string | null;
  group_id: number;
  trade_date: string | null;
  close: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  status: string;
  source: string | null;
  error_message: string | null;
};

export type KRWatchlistRankingRead = {
  group_id: number | null;
  include_children: boolean;
  rank_by: string;
  sort_order: string;
  requested_symbol_count: number;
  ranked_count: number;
  no_data_count: number;
  error_count: number;
  trade_date: string | null;
  target_trade_date: string | null;
  is_current: boolean;
  current_symbol_count: number;
  stale_symbol_count: number;
  results: KRWatchlistRankingItemRead[];
};

export type KRWatchlistReadinessItemRead = {
  symbol: string;
  security_name: string | null;
  group_id: number;
  market_segment: string | null;
  latest_daily_date: string | null;
  latest_daily_provider: string | null;
  daily_row_count: number;
  daily_status: string;
  latest_investor_date: string | null;
  investor_row_count: number;
  latest_fundamental_date: string | null;
  fundamental_row_count: number;
  readiness_status: string;
  missing_resources: string[];
};

export type KRWatchlistReadinessRead = {
  kind: string;
  group_id: number | null;
  include_children: boolean;
  enabled_only: boolean;
  expected_daily_price_date: string | null;
  summary: {
    requested_symbol_count: number;
    ready_count: number;
    partial_count: number;
    no_data_count: number;
    daily_current_count: number;
    daily_stale_count: number;
    daily_empty_count: number;
    investor_available_count: number;
    fundamental_available_count: number;
  };
  results: KRWatchlistReadinessItemRead[];
};

export type KROhlcPointRead = {
  time: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
};

export type KROhlcChartRead = {
  symbol: string;
  timeframe: string;
  bars: number;
  lookback_days: number;
  from_date: string;
  to_date: string;
  point_count: number;
  points: KROhlcPointRead[];
  backfill: Record<string, unknown> | null;
  latest_data_date: string | null;
  expected_data_date: string | null;
  freshness_status: "current" | "stale" | "missing" | "future" | string;
  is_current: boolean;
  refresh_recommended: boolean;
};

export type KRIndexOhlcChartRead = {
  index_id: string;
  provider_symbol: string;
  name: string;
  short_name: string;
  timeframe: string;
  bars: number;
  lookback_days: number;
  from_date: string;
  to_date: string;
  point_count: number;
  points: KROhlcPointRead[];
  backfill: Record<string, unknown> | null;
  latest_data_date: string | null;
  expected_data_date: string | null;
  freshness_status: "current" | "stale" | "missing" | "future" | string;
  is_current: boolean;
  refresh_recommended: boolean;
};

export type KRResourceSlotRead = {
  key: string;
  status: "available" | "empty" | "planned" | string;
  available: boolean;
  source: string | null;
  latest_date: string | null;
  row_count: number;
  metrics?: Record<string, string | number | null>;
};

export type KRResourceSummaryRead = {
  symbol: string;
  slots: KRResourceSlotRead[];
};

export type KRSourceHealthEntryRead = {
  resource: string;
  provider: string;
  target: string;
  status: string;
  ok: boolean;
  row_count: number;
  latest_data_date: string | null;
  expected_data_date: string | null;
  data_quality: string;
  reason: string;
  error_message: string | null;
};

export type KRSourceHealthRead = {
  kind: string;
  generated_at: string;
  expected_daily_price_date: string | null;
  summary: {
    entry_count: number;
    ok_count: number;
    empty_count: number;
    stale_count: number;
    error_count: number;
  };
  entries: KRSourceHealthEntryRead[];
};

export type USSymbolSyncResultRead = {
  status: string;
  scanned_count: number;
  created_count: number;
  updated_count: number;
  deactivated_count: number;
  message: string;
};

export type USDailyPriceRead = {
  id: number;
  provider: string;
  symbol: string;
  trade_date: string;
  currency: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  adjusted_close: number | null;
  trade_volume: number | null;
  dividend_amount: number | null;
  split_coefficient: number | null;
  source_url: string | null;
  raw_payload_hash: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type USDailyPriceRefreshResultRead = {
  status: string;
  provider: string;
  symbol: string;
  fetched_count: number;
  eligible_count: number;
  skipped_count: number;
  inserted_count: number;
  updated_count: number;
  unchanged_count: number;
  expected_trade_date: string | null;
  latest_eligible_trade_date: string | null;
  selected_event_at: string | null;
  selected_source: string | null;
  fallback_used: boolean;
  selection_reason: string | null;
  external_call_count: number;
  providers_attempted: string[];
  resource_attempts: Array<{
    provider: string;
    resource_id: string;
  }>;
  persistence_committed: boolean;
  postcondition_satisfied: boolean;
  raw_result_ids: number[];
  warnings: string[];
  message: string;
};

export type USOhlcPointRead = {
  time: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
};

export type USOhlcChartRead = {
  symbol: string;
  timeframe: string;
  bars: number;
  lookback_days: number;
  from_date: string;
  to_date: string;
  point_count: number;
  points: USOhlcPointRead[];
  volume_unit: string | null;
  volume_semantics: string | null;
  volume_status: "available" | "not_applicable" | "not_provided" | string;
  backfill: Record<string, unknown> | null;
  intraday_overlay: Record<string, unknown> | null;
  latest_data_date: string | null;
  latest_trade_date: string | null;
  latest_finalized_data_date: string | null;
  expected_data_date: string | null;
  expected_trade_date: string | null;
  freshness_status: "current" | "stale" | "missing" | "future" | string;
  coverage_status: "complete" | "best_available" | "partial" | "missing" | string;
  request_coverage_status: "complete" | "best_available" | "partial" | "missing" | string;
  continuity_status: "complete" | "partial" | "missing" | string;
  history_status:
    | "complete"
    | "best_available"
    | "insufficient_history"
    | "missing"
    | string;
  history_fetch_scope: "full" | "compact" | "unknown" | string;
  first_data_date: string | null;
  continuity_start_date: string | null;
  contiguous_through_date: string | null;
  latest_expected_date_present: boolean;
  missing_trade_date_count: number;
  missing_trade_dates: string[];
  missing_trade_dates_truncated: boolean;
  requested_bar_count: number;
  available_bar_count: number;
  expected_previous_close_trade_date: string | null;
  previous_close: number | null;
  previous_close_trade_date: string | null;
  previous_close_provider: string | null;
  previous_close_fetched_at: string | null;
  previous_close_status: "current" | "partial" | "missing" | string;
  is_current: boolean;
  refresh_recommended: boolean;
  coverage_refresh_recommended: boolean;
  selected_provider: string | null;
  selected_source: string | null;
  selected_event_at: string | null;
  fallback_used: boolean;
  selection_reason: string | null;
  facts_usable: boolean;
  decision_usable: boolean;
  usability_status: "decision_usable" | "facts_only" | "unusable" | string;
  limitations: string[];
};

export type USTechnicalQualityRead = {
  status: "available" | "partial" | "missing" | string;
  facts_usable: boolean;
  decision_usable: boolean;
  bar_count: number;
  facts_minimum_bars: number;
  decision_minimum_bars: number;
  corporate_action_coverage: string;
  freshness_status: string;
  reason_codes: string[];
};

export type USTechnicalIndicatorsRead = {
  kind: "technical_indicators" | string;
  schema_version: string;
  algorithm_version: string;
  market: string;
  symbol: string;
  timeframe: string;
  price_basis: string;
  status: string;
  as_of: string | null;
  bar_count: number;
  current: {
    time?: string | null;
    close?: number | null;
    change_pct?: number | null;
    volume?: number | null;
    moving_averages?: Record<string, number | null>;
    price_vs_ma20_pct?: number | null;
    volume_vs_ma20_pct?: number | null;
  };
  quality: USTechnicalQualityRead;
};

export type USTechnicalStructureRead = {
  kind: "technical_structure" | string;
  schema_version: string;
  status: string;
  as_of: string | null;
  selected_title: string;
  trend_state: "bullish_stack" | "below_ma20" | "ma_consolidation" | "insufficient" | string;
  breakout_state: string;
  metrics: {
    price_vs_ma20_pct?: number | null;
    volume_vs_ma20_pct?: number | null;
    day_change_pct?: number | null;
  };
  quality: USTechnicalQualityRead;
};

export type USMarketResearchRead = {
  kind: "us_market_research" | string;
  schema_version: string;
  market: "US" | string;
  symbol: string;
  status: string;
  as_of: string | null;
  technical_indicators: USTechnicalIndicatorsRead;
  technical_structure: USTechnicalStructureRead;
  corporate_action_coverage: {
    status: string;
    observed_event_count: number;
    completeness_checkpoint: string | null;
  };
  market_coverage: Record<string, unknown>;
  missing: string[];
  warnings: string[];
};

export type USSecCompanyFactRead = {
  id: number;
  fact_key: string;
  cik: string;
  symbol: string | null;
  entity_name: string | null;
  taxonomy: string;
  tag: string;
  label: string | null;
  description: string | null;
  unit: string;
  fiscal_year: number | null;
  fiscal_period: string | null;
  form: string | null;
  filed_date: string | null;
  period_start_date: string | null;
  period_end_date: string | null;
  accession_number: string | null;
  frame: string | null;
  value_numeric: number | null;
  value_text: string | null;
  source_url: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type USSecFactRefreshResultRead = {
  status: string;
  symbol: string;
  cik: string;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string;
};

export type USSecFundamentalMetricRead = {
  metric: string;
  tag: string;
  label: string | null;
  unit: string;
  value_numeric: number | null;
  value_text: string | null;
  fiscal_year: number | null;
  fiscal_period: string | null;
  form: string | null;
  filed_date: string | null;
  period_start_date: string | null;
  period_end_date: string | null;
  accession_number: string | null;
  source_url: string | null;
};

export type USSecFundamentalSummaryRead = {
  symbol: string;
  cik: string | null;
  entity_name: string | null;
  metric_count: number;
  metrics: USSecFundamentalMetricRead[];
};

export type USSecInsiderOwnerRead = {
  cik: string;
  name: string;
  is_director: boolean;
  is_officer: boolean;
  is_ten_percent_owner: boolean;
  is_other: boolean;
  officer_title: string | null;
  other_text: string | null;
};

export type USSecInsiderTransactionRead = {
  transaction_id: string;
  accession_number: string;
  form_type: "4" | "4/A" | string;
  filing_date: string | null;
  accepted_at: string | null;
  period_of_report: string | null;
  transaction_date: string | null;
  table_type: "non_derivative" | "derivative" | string;
  category: string;
  transaction_code: string | null;
  acquired_disposed_code: string | null;
  security_title: string | null;
  shares: string | null;
  price_per_share: string | null;
  post_transaction_shares: string | null;
  direct_indirect_code: string | null;
  nature_of_ownership: string | null;
  conversion_exercise_price: string | null;
  exercise_date: string | null;
  expiration_date: string | null;
  underlying_security_title: string | null;
  underlying_shares: string | null;
  equity_swap_involved: boolean | null;
  aff10b5_one: boolean | null;
  is_amendment: boolean;
  owners: USSecInsiderOwnerRead[];
  footnotes: Array<{ id: string; text: string | null }>;
  issue_codes: string[];
  source_url: string;
};

export type USSecInsiderTransactionsRead = {
  contract_version: "omi.sec.insiders.v1" | string;
  symbol: string;
  cik: string | null;
  status: "current" | "ready_empty" | "missing" | "stale" | "partial" | "blocked" | string;
  as_of: string | null;
  freshness: {
    status: string;
    last_checked_at: string | null;
    last_success_at: string | null;
    latest_filing_date: string | null;
    latest_accession_number: string | null;
    basis: string;
    observation_window_hours: number;
  };
  summary: {
    filing_count: number;
    amendment_count: number;
    transaction_count: number;
    open_market_purchase_count: number;
    open_market_sale_count: number;
    open_market_purchase_shares: string | null;
    open_market_sale_shares: string | null;
    other_transaction_count: number;
    latest_transaction_date: string | null;
  };
  transactions: USSecInsiderTransactionRead[];
  quality: {
    issue_codes: string[];
    warnings: string[];
    limitations: string[];
  };
  source_refs: Array<{
    provider: string;
    accession_number: string;
    form_type: string;
    filing_date: string | null;
    source_url: string;
  }>;
  pagination: {
    limit: number;
    returned_count: number;
    next_cursor: string | null;
  };
};

export type USSec13FQuarterRead = {
  report_quarter: string;
  report_period_end: string;
  reporting_manager_count: number;
  reported_row_count: number;
  reported_long_shares: string | null;
  reported_long_value_usd: string | null;
  reported_put_value_usd: string | null;
  reported_call_value_usd: string | null;
  new_manager_count: number | null;
  increased_manager_count: number | null;
  reduced_manager_count: number | null;
  exited_manager_count: number | null;
  status: string;
};

export type USSec13FManagerRead = {
  manager_cik: string | null;
  manager_name: string;
  report_period_end: string;
  reported_long_shares: string | null;
  reported_value_usd: string | null;
  prior_reported_long_shares: string | null;
  reported_long_shares_change: string | null;
  direction: "new" | "increased" | "reduced" | "unchanged" | "not_observed" | string;
  reported_value_share: number;
};

export type USSec13FInstitutionalHoldingsRead = {
  contract_version: "omi.sec.13f.v1" | string;
  symbol: string;
  cik: string | null;
  status: "current" | "partial" | "missing" | "blocked" | string;
  as_of: string | null;
  freshness: {
    status: string;
    latest_release_period?: string | null;
    latest_report_period_end?: string | null;
    basis?: string;
    is_delayed_quarterly_filing?: boolean;
    reason?: string;
  };
  summary: Partial<USSec13FQuarterRead>;
  quarters: USSec13FQuarterRead[];
  managers: USSec13FManagerRead[];
  quality: {
    decision_usable: boolean;
    mapping_version?: string;
    mapping_row_coverage?: number;
    mapping_value_coverage?: number;
    unresolved_row_count?: number;
    unresolved_value_usd?: string | null;
    limitations: string[];
  };
  source_refs: Array<{
    period_key: string;
    source_url: string | null;
    source_sha256?: string;
    holdings_sha256?: string;
  }>;
};

export type USCompanyProfileRead = {
  id: number;
  provider: string;
  symbol: string;
  company_name: string | null;
  description: string | null;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  country: string | null;
  currency: string | null;
  market_cap: number | null;
  ebitda: number | null;
  pe_ratio: number | null;
  peg_ratio: number | null;
  beta: number | null;
  dividend_yield: number | null;
  eps: number | null;
  revenue_ttm: number | null;
  profit_margin: number | null;
  fiscal_year_end: string | null;
  latest_quarter: string | null;
  source_url: string | null;
  raw_payload_hash: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type USCorporateActionRead = {
  id: number;
  provider: string;
  symbol: string;
  action_type: string;
  event_date: string;
  declaration_date: string | null;
  record_date: string | null;
  payment_date: string | null;
  amount: number | null;
  split_from: number | null;
  split_to: number | null;
  split_ratio: number | null;
  source_url: string | null;
  raw_payload_hash: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type USShortVolumeDailyRead = {
  id: number;
  provider: string;
  symbol: string;
  trade_date: string;
  market_center: string;
  short_volume: number | null;
  short_exempt_volume: number | null;
  total_volume: number | null;
  short_ratio: number | null;
  source_url: string | null;
  raw_payload_hash: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type USResourceRefreshResultRead = {
  status: string;
  provider: string;
  symbol: string | null;
  trade_date: string | null;
  series_id: string | null;
  fetched_count: number;
  inserted_count: number;
  updated_count: number;
  message: string;
};

export type USWatchlistGroupNode = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  children: USWatchlistGroupNode[];
};

export type USWatchlistGroupRead = {
  id: number;
  parent_id: number | null;
  group_name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type USWatchlistItemRead = {
  id: number;
  group_id: number;
  symbol: string;
  security_name: string | null;
  exchange: string | null;
  asset_type: string | null;
  note: string | null;
  priority: number;
  tags: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type USWatchlistRankingItemRead = {
  rank: number;
  symbol: string;
  security_name: string | null;
  exchange: string | null;
  asset_type: string | null;
  group_id: number;
  trade_date: string | null;
  time: string | null;
  session: string | null;
  close: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  status: string;
  source: string | null;
  has_extended_hours: boolean;
  intraday_previous_close: number | null;
  intraday_points: Array<{
    time: string;
    price: number;
  }>;
  error_message: string | null;
};

export type USWatchlistRankingRead = {
  group_id: number | null;
  include_children: boolean;
  rank_by: string;
  sort_order: string;
  requested_symbol_count: number;
  ranked_count: number;
  no_data_count: number;
  error_count: number;
  trade_date: string | null;
  target_trade_date: string | null;
  is_current: boolean;
  current_symbol_count: number;
  stale_symbol_count: number;
  results: USWatchlistRankingItemRead[];
};

export type InstitutionalHoldingRatioPointRead = {
  trade_date: string | null;
  foreign_investor_ratio: number | null;
  investment_trust_ratio: number | null;
  dealer_ratio: number | null;
};

export type InstitutionalHoldingRatioRead = InstitutionalHoldingRatioPointRead & {
  stock_id: string;
  stock_name: string | null;
  source_name: string;
  source_url: string;
  fetched_at: string;
  history: InstitutionalHoldingRatioPointRead[];
  classification: "compatibility_cache";
  lineage_status: "raw_receipt_not_persisted";
  canonical_truth: false;
  decision_usable: false;
  raw_receipt_id: null;
  limitations: string[];
};

export type InstitutionalTradeDailyRead = {
  id: number;
  source_id: number;
  raw_result_id: number;
  trade_date: string;
  stock_id: string;
  stock_name: string | null;
  foreign_investor_buy: number | null;
  foreign_investor_sell: number | null;
  foreign_investor_net: number | null;
  foreign_dealer_buy: number | null;
  foreign_dealer_sell: number | null;
  foreign_dealer_net: number | null;
  investment_trust_buy: number | null;
  investment_trust_sell: number | null;
  investment_trust_net: number | null;
  dealer_self_buy: number | null;
  dealer_self_sell: number | null;
  dealer_self_net: number | null;
  dealer_hedge_buy: number | null;
  dealer_hedge_sell: number | null;
  dealer_hedge_net: number | null;
  dealer_buy: number | null;
  dealer_sell: number | null;
  dealer_net: number | null;
  total_institutional_net: number | null;
  created_at: string;
  updated_at: string;
};

export type MarginTradingDailyRead = {
  id: number;
  source_id: number;
  raw_result_id: number;
  trade_date: string;
  stock_id: string;
  stock_name: string | null;
  margin_buy: number | null;
  margin_sell: number | null;
  margin_cash_repayment: number | null;
  margin_previous_balance: number | null;
  margin_today_balance: number | null;
  margin_next_limit: number | null;
  short_covering: number | null;
  short_sale: number | null;
  short_stock_repayment: number | null;
  short_previous_balance: number | null;
  short_today_balance: number | null;
  short_next_limit: number | null;
  offset: number | null;
  note: string | null;
  created_at: string;
  updated_at: string;
};

export type StockChipCoverageRead = {
  stock_id: string;
  shareholding_latest_date: string | null;
  shareholding_week_count: number;
  shareholding_row_count: number;
  margin_latest_trade_date: string | null;
  margin_row_count: number;
  has_shareholding: boolean;
  has_margin: boolean;
};

export type BrokerBranchTradeDailyRead = {
  id: number;
  source_id: number;
  raw_result_id: number;
  trade_date: string;
  stock_id: string;
  stock_name: string | null;
  branch_code: string;
  branch_name: string;
  buy_lots: number | null;
  sell_lots: number | null;
  net_lots: number | null;
  buy_avg_price: number | null;
  sell_avg_price: number | null;
  buy_rank: number | null;
  sell_rank: number | null;
  source_label: string | null;
  created_at: string;
  updated_at: string;
};

export type BrokerBranchTradeDailySummaryRead = {
  stock_id: string;
  stock_name: string | null;
  trade_date: string | null;
  source_name: string | null;
  source_url: string;
  source_label: string | null;
  is_latest: boolean;
  requested_days: number;
  available_days: number;
  trade_dates: string[];
  is_partial: boolean;
  row_count: number;
  buy_top: BrokerBranchTradeDailyRead[];
  sell_top: BrokerBranchTradeDailyRead[];
};

export type ShareholdingDistributionWeeklyRead = {
  id: number;
  source_id: number;
  raw_result_id: number;
  data_date: string;
  stock_id: string;
  stock_name: string | null;
  holding_level: string;
  holding_level_order: number | null;
  holder_count: number | null;
  share_count: number | null;
  share_ratio: number | null;
  created_at: string;
  updated_at: string;
};

export type MonthlyRevenueRead = {
  id: number;
  source_id: number;
  raw_result_id: number;
  report_date: string | null;
  period: string;
  stock_id: string;
  stock_name: string | null;
  market: string | null;
  industry: string | null;
  monthly_revenue: number | null;
  previous_month_revenue: number | null;
  previous_year_month_revenue: number | null;
  month_over_month_pct: number | null;
  year_over_year_pct: number | null;
  cumulative_revenue: number | null;
  previous_year_cumulative_revenue: number | null;
  cumulative_year_over_year_pct: number | null;
  note: string | null;
  created_at: string;
  updated_at: string;
};

export type FinancialMetricQuarterlyRead = {
  id: number;
  source_id: number;
  raw_result_id: number;
  report_date: string | null;
  fiscal_year: number;
  quarter: number;
  period: string;
  stock_id: string;
  stock_name: string | null;
  market: string | null;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  net_income_attributable_parent: number | null;
  eps: number | null;
  total_assets: number | null;
  total_equity: number | null;
  parent_equity: number | null;
  book_value_per_share: number | null;
  roe: number | null;
  roa: number | null;
  period_scope?: "ytd" | "annual" | "unknown" | string | null;
  months_covered?: number | null;
  flow_semantics?: string | null;
  eps_semantics?: string | null;
  raw_eps?: number | null;
  single_quarter_eps?: number | null;
  adjusted_eps_ytd?: number | null;
  ttm_eps?: number | null;
  source_restated_status?: string | null;
  share_basis_status?: string | null;
  date_semantics_status?: string | null;
  normalization_status?: string | null;
  valuation_status?: string | null;
  decision_usable?: boolean | null;
  normalization_warnings?: string[];
  created_at: string;
  updated_at: string;
};

export type TaiwanFinancialQualityRead = {
  freshness: string;
  continuity: string;
  semantic_validity: string;
  decision_usable: boolean;
  issues: string[];
  revenue_continuity: {
    status?: string;
    observed_from?: string | null;
    observed_to?: string | null;
    missing_periods?: string[];
    duplicate_periods?: string[];
    decision_usable?: boolean;
    issues?: string[];
  };
};

export type TaiwanFinancialNormalizedFactRead = {
  source_fact_id: string;
  period: string;
  period_scope: string;
  period_end: string;
  metric_code: string;
  normalized_value: number | string;
  normalized_unit: string;
  adjustment_factor: number | string;
  comparison_basis_id: string;
  normalization_status: string;
  normalization_version: string;
  normalization_mode: string;
  decision_usable: boolean;
  action_ids: string[];
  issue_codes: string[];
  known_at: string;
};

export type TaiwanFinancialSingleQuarterEpsRead = {
  metric_code: string;
  period: string;
  period_end: string;
  value: number | string;
  unit: string;
  status: string;
  comparison_basis_id: string;
  normalization_version: string;
  input_fact_ids: string[];
  action_ids: string[];
  issue_codes: string[];
  known_at: string;
};

export type TaiwanFinancialContractRead = {
  contract_version: "omi.financial.v1" | string;
  target: {
    market: string;
    stock_id: string;
  };
  as_of: string;
  mode: "current_comparable" | "as_reported_as_of" | string;
  as_reported: Record<string, unknown>;
  normalized: {
    status?: string;
    facts?: TaiwanFinancialNormalizedFactRead[];
    comparison_basis_id?: string | null;
    normalization_version?: string | null;
  };
  derived: {
    status?: string;
    single_quarter_eps?: TaiwanFinancialSingleQuarterEpsRead[];
    annual_reconciliations?: Array<{
      fiscal_year: number;
      annual_value: number | string | null;
      discrete_sum: number | string | null;
      difference: number | string | null;
      status: string;
      input_fact_ids: string[];
      issue_codes: string[];
    }>;
    ttm_eps?: number | string | null;
    ttm_eps_exact?: number | string | null;
    ttm_eps_status?: string;
    ttm_periods?: string[];
  };
  valuation: {
    status?: string;
    pe_ttm?: number | string | null;
    pe_ttm_exact?: number | string | null;
    price?: number | string | null;
    price_as_of?: string | null;
    price_basis?: string | null;
    price_resolution_status?: string | null;
    expected_price_trade_date?: string | null;
    price_trade_date?: string | null;
    price_source?: string | null;
    price_source_id?: number | null;
    price_source_reliability?: string | null;
    price_raw_result_id?: number | null;
    financial_basis?: string | null;
    decision_usable?: boolean;
  };
  basis_assessment?: {
    assessment_type: string;
    outcome: string;
    effective_date: string;
    issue_code: string;
    rationale: string;
    resolution_requirements: string[];
    evidence_package_hash: string;
    known_at: string | null;
    reviewed_at: string | null;
    reviewed_by: string;
  } | null;
  quality: TaiwanFinancialQualityRead;
  source_refs: Array<Record<string, unknown>>;
};
export type OmiStatusDimensions = {
  version: string;
  status_authority: "backend_status_taxonomy" | string;
  service_status: "available" | "degraded" | "unavailable" | string;
  data_quality:
    | "current"
    | "stale"
    | "partial"
    | "missing"
    | "failed"
    | "pending"
    | "not_applicable"
    | "unknown"
    | string;
  decision_readiness: "ready" | "limited" | "blocked" | "not_applicable" | string;
  provider_status:
    | "available"
    | "degraded"
    | "unavailable"
    | "unknown"
    | "not_applicable"
    | string;
  reason_codes: string[];
};

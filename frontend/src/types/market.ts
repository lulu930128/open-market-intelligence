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
  note: string | null;
  priority: number;
  tags: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
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

export type WatchlistRadarPriceLevels = Record<string, number | string | null>;

export type WatchlistRadarContextSignal = {
  key: string;
  source: string;
  label: string;
  tone: "positive" | "negative" | "warning" | "neutral" | string;
  stance: "confirm" | "contradict" | "risk" | "info" | string;
  description: string;
  value_label: string | null;
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
  context_snapshot: Record<string, Record<string, number | string | null>>;
  context_signals: WatchlistRadarContextSignal[];
  context_summary: string;
  context_score: number;
  stale: boolean;
  error_message: string | null;
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
  intraday_overlay: Record<string, unknown> | null;
};

export type MarketBreadth = {
  market: string;
  trade_date: string | null;
  advance_count: number;
  decline_count: number;
  unchanged_count: number;
  total_count: number;
  limit_up_count: number | null;
  limit_down_count: number | null;
  trade_value: number | null;
  source: string | null;
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
  error_message: string | null;
};

export type MarketIndexSummary = {
  as_of: string;
  source: string;
  indices: MarketIndexSnapshot[];
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
  source_grade: string;
  source_details: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
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
    status: "live" | "cached" | "session_mismatch" | "stale" | string;
    is_live: boolean;
    is_stale: boolean;
    is_session_mismatch: boolean;
    expected_session: string;
    age_seconds: number | null;
    message: string;
    source_error: string | null;
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
  price: number;
  volume: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
};

export type IntradayTrendResponse = {
  stock_id: string;
  symbol: string | null;
  source: string;
  previous_close: number | null;
  point_count: number;
  points: IntradayTrendPoint[];
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

export type TaiwanStockQuoteDepthRead = {
  stock_id: string;
  stock_name: string | null;
  market: string | null;
  provider: string;
  source: string;
  source_url: string | null;
  exchange_channel: string | null;
  session_phase: string;
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
  freshness: TaiwanStockQuoteDepthFreshness;
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
  support_resistance?: Record<string, number | null>;
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
  inserted_count: number;
  updated_count: number;
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
  backfill: Record<string, unknown> | null;
  intraday_overlay: Record<string, unknown> | null;
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
  close: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  status: string;
  source: string | null;
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
  created_at: string;
  updated_at: string;
};

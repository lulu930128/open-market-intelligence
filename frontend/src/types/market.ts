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
  results: RankingItem[];
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
  timeframe: "today" | "daily";
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

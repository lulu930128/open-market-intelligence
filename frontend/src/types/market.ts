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
  change_pct: number | null;
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

export type StockIndicatorPoint = {
  time: string;
  close: number | null;
  volume: number | null;
  change: number | null;
  change_pct: number | null;
  ma: Record<string, number | null>;
  volume_ma: Record<string, number | null>;
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

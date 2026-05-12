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

export type RankingItem = {
  rank: number;
  stock_id: string;
  stock_name: string | null;
  time: string | null;
  close: number | null;
  volume: number | null;
  change_pct: number | null;
  score: number;
  status: string;
  signal_count: number;
  signal_keys: string[];
  primary_signal_key: string | null;
  primary_signal_label: string | null;
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
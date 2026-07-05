export type ResourceCommodityGroupKey = "metals" | "energy";
export type ResourceInterval = "1m" | "5m" | "15m" | "30m" | "1h" | "1d" | "1w" | "1M";

export type ResourceCommodityInstrument = {
  key: string;
  group: ResourceCommodityGroupKey;
  displayName: string;
  symbol: string;
  exchange: string;
  providerSymbol: string;
  quoteAsset: string;
  providerStatus: string;
  role: string;
};

export type ResourceProviderContract = {
  kind: string;
  market: string;
  execution_enabled: boolean;
  ai_execution_enabled: boolean;
  trade_candidate_symbols: string[];
  notes: string[];
  root_folders: Array<Record<string, unknown>>;
  providers: Record<string, unknown>;
  ohlcv_intervals?: Record<string, ResourceInterval[]>;
  chart_profiles?: Record<string, {
    default_interval?: ResourceInterval;
    intervals?: ResourceInterval[];
  }>;
  instruments: ResourceInstrumentRead[];
};

export type ResourceInstrumentRead = {
  key: string;
  root_folder: string;
  group: ResourceCommodityGroupKey | string;
  asset_class: string;
  name: string;
  display_name: string;
  symbol: string;
  provider: string;
  exchange: string;
  provider_symbol: string;
  base_asset: string;
  quote_asset: string;
  instrument_type: string;
  contract_type: string;
  resources: string[];
  tradable: boolean;
  trade_candidate: boolean;
  provider_status: string;
  role: string;
};

export type ResourceQuoteSnapshot = {
  id: number;
  provider: string;
  exchange: string;
  symbol: string;
  provider_symbol: string;
  name: string | null;
  root_folder: string;
  group: string;
  asset_class: string;
  base_asset: string;
  quote_asset: string;
  instrument_type: string;
  contract_key: string;
  contract_month: string | null;
  last_price: number | null;
  bid_price: number | null;
  ask_price: number | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  previous_close: number | null;
  price_change: number | null;
  price_change_pct: number | null;
  volume: number | null;
  open_interest: number | null;
  event_time: string | null;
  source_url: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type ResourceOhlcvBar = {
  id: number;
  provider: string;
  exchange: string;
  symbol: string;
  provider_symbol: string;
  name: string | null;
  root_folder: string;
  group: string;
  asset_class: string;
  base_asset: string;
  quote_asset: string;
  instrument_type: string;
  contract_key: string;
  contract_month: string | null;
  interval: string;
  bar_time: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  volume: number | null;
  open_interest: number | null;
  source_url: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
};

export type ResourceRefreshResult = {
  status: string;
  provider: string;
  resource: string;
  requested_count: number;
  refreshed_count: number;
  error_count: number;
  skipped_count: number;
  warnings: string[];
  errors: Array<{ symbol: string; message: string }>;
  message: string;
  interval?: string | null;
  results?: Array<Record<string, unknown>> | null;
};

export type ResourceSourceHealthEntry = {
  resource: string;
  provider: string;
  target: string;
  status: string;
  ok: boolean;
  row_count: number;
  required?: boolean;
  latest_fetched_at?: string | null;
  latest_data_key?: string | null;
  data_quality?: string;
  reason?: string;
  age_seconds?: number | null;
  stale_seconds?: number | null;
  session_status?: string;
  latest_event_at?: string | null;
  latest_event_status?: string | null;
  latest_event_severity?: string | null;
  latest_event_message?: string | null;
  recent_event_count?: number;
  recent_error_count?: number;
  consecutive_error_count?: number;
};

export type ResourceSourceHealth = {
  kind: string;
  generated_at: string;
  filters: Record<string, unknown>;
  summary: {
    entry_count: number;
    ok_count: number;
    empty_count: number;
    stale_count: number;
    delayed_count?: number;
    error_count: number;
    disabled_count: number;
  };
  entries: ResourceSourceHealthEntry[];
};

export const RESOURCE_COMMODITY_GROUPS: {
  key: ResourceCommodityGroupKey;
  label: string;
}[] = [
  { key: "metals", label: "金屬" },
  { key: "energy", label: "能源" },
];

export const RESOURCE_OHLCV_INTERVALS: ResourceInterval[] = [
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "1d",
  "1w",
  "1M",
];

export const RESOURCE_COMMODITY_INSTRUMENTS: ResourceCommodityInstrument[] = [
  {
    key: "commodity:metals:GC",
    group: "metals",
    displayName: "黃金",
    symbol: "GC",
    exchange: "COMEX",
    providerSymbol: "GC=F",
    quoteAsset: "USD",
    providerStatus: "best_effort_delayed",
    role: "Gold futures watch-only Yahoo chart context",
  },
  {
    key: "commodity:metals:SI",
    group: "metals",
    displayName: "白銀",
    symbol: "SI",
    exchange: "COMEX",
    providerSymbol: "SI=F",
    quoteAsset: "USD",
    providerStatus: "best_effort_delayed",
    role: "Silver futures watch-only Yahoo chart context",
  },
  {
    key: "commodity:metals:HG",
    group: "metals",
    displayName: "銅",
    symbol: "HG",
    exchange: "COMEX",
    providerSymbol: "HG=F",
    quoteAsset: "USD",
    providerStatus: "best_effort_delayed",
    role: "Copper futures watch-only Yahoo chart context",
  },
  {
    key: "commodity:energy:CL",
    group: "energy",
    displayName: "WTI 原油",
    symbol: "CL",
    exchange: "NYMEX",
    providerSymbol: "CL=F",
    quoteAsset: "USD",
    providerStatus: "best_effort_delayed",
    role: "WTI crude oil futures watch-only Yahoo chart context",
  },
  {
    key: "commodity:energy:BZ",
    group: "energy",
    displayName: "Brent 原油",
    symbol: "BZ",
    exchange: "NYMEX",
    providerSymbol: "BZ=F",
    quoteAsset: "USD",
    providerStatus: "best_effort_delayed",
    role: "Brent crude oil futures watch-only Yahoo chart context",
  },
  {
    key: "commodity:energy:NG",
    group: "energy",
    displayName: "天然氣",
    symbol: "NG",
    exchange: "NYMEX",
    providerSymbol: "NG=F",
    quoteAsset: "USD",
    providerStatus: "best_effort_delayed",
    role: "Natural gas futures watch-only Yahoo chart context",
  },
];

export function resourceInstrumentsForGroup(group: ResourceCommodityGroupKey) {
  return RESOURCE_COMMODITY_INSTRUMENTS.filter((instrument) => instrument.group === group);
}

export function resourceInstrumentByKey(key: string | null | undefined) {
  if (!key) return null;
  return RESOURCE_COMMODITY_INSTRUMENTS.find((instrument) => instrument.key === key) ?? null;
}

export function resourceSymbolFromKey(key: string | null | undefined) {
  const fallback = resourceInstrumentByKey(key);
  if (fallback) return fallback.symbol;
  const parts = key?.split(":") ?? [];
  return (parts[parts.length - 1] ?? "").trim().toUpperCase();
}

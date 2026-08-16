export type ResourceCommodityGroupKey = "metals" | "energy";
export type ResourceCurrencyGroupKey =
  | "twd_to_foreign"
  | "foreign_to_twd"
  | "foreign_to_foreign";
export type ResourceRootFolderKey = "commodity" | "currency";
export type ResourceInstrumentGroupKey =
  | ResourceCommodityGroupKey
  | ResourceCurrencyGroupKey;
export type ResourceInterval = "1m" | "5m" | "15m" | "30m" | "1h" | "1d" | "1w" | "1M";

export type ResourceMarketInstrument = {
  key: string;
  rootFolder: ResourceRootFolderKey;
  group: ResourceInstrumentGroupKey;
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
  freshness?: {
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
  labelKey: string;
}[] = [
  { key: "metals", labelKey: "crypto.sidebar.groups.metals" },
  { key: "energy", labelKey: "crypto.sidebar.groups.energy" },
];

export const RESOURCE_CURRENCY_GROUPS: {
  key: ResourceCurrencyGroupKey;
  labelKey: string;
}[] = [
  { key: "twd_to_foreign", labelKey: "crypto.sidebar.groups.twdToForeign" },
  { key: "foreign_to_twd", labelKey: "crypto.sidebar.groups.foreignToTwd" },
  { key: "foreign_to_foreign", labelKey: "crypto.sidebar.groups.foreignToForeign" },
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

export const RESOURCE_COMMODITY_INSTRUMENTS: ResourceMarketInstrument[] = [
  {
    key: "commodity:metals:GC",
    rootFolder: "commodity",
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
    rootFolder: "commodity",
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
    rootFolder: "commodity",
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
    rootFolder: "commodity",
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
    rootFolder: "commodity",
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
    rootFolder: "commodity",
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

export const RESOURCE_CURRENCY_INSTRUMENTS: ResourceMarketInstrument[] = [
  {
    key: "currency:twd_to_foreign:TWD-USD",
    rootFolder: "currency",
    group: "twd_to_foreign",
    displayName: "台幣／美元",
    symbol: "TWD-USD",
    exchange: "FX",
    providerSymbol: "TWDUSD=X",
    quoteAsset: "USD",
    providerStatus: "best_effort_delayed",
    role: "TWD/USD foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
  {
    key: "currency:twd_to_foreign:TWD-JPY",
    rootFolder: "currency",
    group: "twd_to_foreign",
    displayName: "台幣／日圓",
    symbol: "TWD-JPY",
    exchange: "FX",
    providerSymbol: "TWDJPY=X",
    quoteAsset: "JPY",
    providerStatus: "best_effort_delayed",
    role: "TWD/JPY foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
  {
    key: "currency:twd_to_foreign:TWD-KRW",
    rootFolder: "currency",
    group: "twd_to_foreign",
    displayName: "台幣／韓元",
    symbol: "TWD-KRW",
    exchange: "FX",
    providerSymbol: "TWDKRW=X",
    quoteAsset: "KRW",
    providerStatus: "best_effort_delayed",
    role: "TWD/KRW foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
  {
    key: "currency:foreign_to_twd:USD-TWD",
    rootFolder: "currency",
    group: "foreign_to_twd",
    displayName: "美元／台幣",
    symbol: "USD-TWD",
    exchange: "FX",
    providerSymbol: "USDTWD=X",
    quoteAsset: "TWD",
    providerStatus: "best_effort_delayed",
    role: "USD/TWD foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
  {
    key: "currency:foreign_to_twd:JPY-TWD",
    rootFolder: "currency",
    group: "foreign_to_twd",
    displayName: "日圓／台幣",
    symbol: "JPY-TWD",
    exchange: "FX",
    providerSymbol: "JPYTWD=X",
    quoteAsset: "TWD",
    providerStatus: "best_effort_delayed",
    role: "JPY/TWD foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
  {
    key: "currency:foreign_to_twd:KRW-TWD",
    rootFolder: "currency",
    group: "foreign_to_twd",
    displayName: "韓元／台幣",
    symbol: "KRW-TWD",
    exchange: "FX",
    providerSymbol: "KRWTWD=X",
    quoteAsset: "TWD",
    providerStatus: "best_effort_delayed",
    role: "KRW/TWD foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
  {
    key: "currency:foreign_to_foreign:USD-JPY",
    rootFolder: "currency",
    group: "foreign_to_foreign",
    displayName: "美元／日圓",
    symbol: "USD-JPY",
    exchange: "FX",
    providerSymbol: "USDJPY=X",
    quoteAsset: "JPY",
    providerStatus: "best_effort_delayed",
    role: "USD/JPY foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
  {
    key: "currency:foreign_to_foreign:USD-KRW",
    rootFolder: "currency",
    group: "foreign_to_foreign",
    displayName: "美元／韓元",
    symbol: "USD-KRW",
    exchange: "FX",
    providerSymbol: "USDKRW=X",
    quoteAsset: "KRW",
    providerStatus: "best_effort_delayed",
    role: "USD/KRW foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
  {
    key: "currency:foreign_to_foreign:EUR-USD",
    rootFolder: "currency",
    group: "foreign_to_foreign",
    displayName: "歐元／美元",
    symbol: "EUR-USD",
    exchange: "FX",
    providerSymbol: "EURUSD=X",
    quoteAsset: "USD",
    providerStatus: "best_effort_delayed",
    role: "EUR/USD foreign-exchange watch-only Yahoo chart context; delayed/best-effort.",
  },
];

export const RESOURCE_MARKET_INSTRUMENTS: ResourceMarketInstrument[] = [
  ...RESOURCE_COMMODITY_INSTRUMENTS,
  ...RESOURCE_CURRENCY_INSTRUMENTS,
];

export function resourceMarketInstrumentFromRead(
  instrument: ResourceInstrumentRead
): ResourceMarketInstrument | null {
  if (instrument.root_folder !== "commodity" && instrument.root_folder !== "currency") {
    return null;
  }
  return {
    key: instrument.key,
    rootFolder: instrument.root_folder,
    group: instrument.group as ResourceInstrumentGroupKey,
    displayName: instrument.display_name,
    symbol: instrument.symbol,
    exchange: instrument.exchange,
    providerSymbol: instrument.provider_symbol,
    quoteAsset: instrument.quote_asset,
    providerStatus: instrument.provider_status,
    role: instrument.role,
  };
}

export function resourceInstrumentsForGroup(
  group: ResourceInstrumentGroupKey,
  instruments: readonly ResourceMarketInstrument[] = RESOURCE_MARKET_INSTRUMENTS
) {
  return instruments.filter((instrument) => instrument.group === group);
}

export function resourceInstrumentByKey(
  key: string | null | undefined,
  instruments: readonly ResourceMarketInstrument[] = RESOURCE_MARKET_INSTRUMENTS
) {
  if (!key) return null;
  return instruments.find((instrument) => instrument.key === key) ?? null;
}

export function resourceSymbolFromKey(key: string | null | undefined) {
  const fallback = resourceInstrumentByKey(key);
  if (fallback) return fallback.symbol;
  const parts = key?.split(":") ?? [];
  return (parts[parts.length - 1] ?? "").trim().toUpperCase();
}

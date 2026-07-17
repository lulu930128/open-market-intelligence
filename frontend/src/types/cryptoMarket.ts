export const CRYPTO_BASE_OPTIONS = [
  "BTC",
  "ETH",
  "USDT",
  "SOL",
  "BNB",
  "XRP",
  "DOGE",
  "TON",
  "LINK",
] as const;

export type CryptoBaseAsset = string;

export type CryptoProvider = "bitopro" | "binance" | "okx";
export type CryptoInstrumentType = "spot";
export const CRYPTO_KLINE_INTERVALS = [
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "4h",
  "1d",
  "1w",
  "1M",
] as const;
export type CryptoOhlcvInterval = (typeof CRYPTO_KLINE_INTERVALS)[number];
export type CryptoProviderOhlcvIntervals = Partial<
  Record<CryptoProvider, CryptoOhlcvInterval[]>
>;

export type CryptoAssetResources = {
  local_twd?: boolean;
  binance_spot?: boolean;
  okx_spot?: boolean;
  binance_perpetual?: boolean;
  okx_perpetual?: boolean;
  market_cap?: boolean;
  taiwan_spread?: boolean;
};

export type CryptoAssetDefinition = {
  asset: string;
  name?: string | null;
  coin_id?: string | null;
  priority?: string;
  default_subscription_mode?: string;
  local_twd_provider_symbol?: string | null;
  resources?: CryptoAssetResources;
};

export type CryptoProviderContract = {
  kind?: string;
  market?: string;
  assets?: CryptoAssetDefinition[];
  instruments?: Array<Record<string, unknown>>;
  ohlcv_intervals?: Partial<Record<CryptoProvider, string[]>>;
  status_taxonomy?: Record<string, string>;
  providers?: Record<
    string,
    {
      role?: string;
      resources?: string[];
      resource_status?: Record<string, string>;
      status?: string;
      canonical_symbols?: string[];
      canonical_assets?: string[];
      ohlcv_intervals?: string[];
    }
  >;
};

export type CryptoWorkspaceMaturity = "ready" | "partial" | "stale" | "missing";

export type CryptoWorkspaceSlotStatus =
  | CryptoWorkspaceMaturity
  | "event_quiet"
  | "provider_pending"
  | "api_key_required"
  | "not_applicable";

export type CryptoWorkspaceSlot = {
  key: string;
  tier: "core" | "context" | "advanced" | string;
  status: CryptoWorkspaceSlotStatus;
  applicable: boolean;
  row_count: number;
  provider_count: number;
  ready_provider_count: number;
  latest_fetched_at: string | null;
  providers: Array<{
    provider: string;
    target: string;
    status: string;
    row_count: number;
    latest_fetched_at: string | null;
  }>;
  reason: string;
};

export type CryptoWorkspaceAsset = {
  asset: CryptoBaseAsset;
  name: string;
  priority: string;
  default_subscription_mode: string;
  subscription_mode: string;
  subscription_resources: Record<string, boolean>;
  watchlisted: boolean;
  instrument_count: number;
  spot_instrument_count: number;
  derivative_instrument_count: number;
  maturity: CryptoWorkspaceMaturity;
  as_of: string | null;
  core_summary: Record<string, number>;
  context_summary: Record<string, number>;
  advanced_summary: Record<string, number>;
  slots: CryptoWorkspaceSlot[];
};

export type CryptoWorkspaceSummary = {
  kind: "crypto_workspace_summary";
  generated_at: string;
  registry_count: number;
  watchlist_count: number;
  summary: {
    asset_count: number;
    watchlist_count: number;
    always_on_count: number;
    on_select_count: number;
    ready_count: number;
    partial_count: number;
    stale_count: number;
    missing_count: number;
  };
  runtime: {
    realtime?: Record<string, unknown>;
    auto_refresh?: Record<string, unknown>;
  };
  assets: CryptoWorkspaceAsset[];
  warnings: string[];
};

export type CryptoKLineInstrument = {
  key: string;
  provider: CryptoProvider;
  sourceProviders?: CryptoProvider[];
  primaryProvider?: CryptoProvider;
  exchange: string;
  symbol: string;
  baseAsset: CryptoBaseAsset;
  quoteAsset: string;
  instrumentType: CryptoInstrumentType;
  role: string;
  supportedIntervals?: CryptoOhlcvInterval[];
  providerIntervals?: CryptoProviderOhlcvIntervals;
  hidden?: boolean;
};

const FALLBACK_LOCAL_TWD_BASES = new Set<CryptoBaseAsset>(["BTC", "ETH", "USDT"]);
const CRYPTO_KLINE_INTERVAL_SET = new Set<string>(CRYPTO_KLINE_INTERVALS);
const FALLBACK_OHLCV_INTERVALS_BY_PROVIDER: CryptoProviderOhlcvIntervals = {
  bitopro: ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"],
  binance: ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"],
  okx: ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"],
};

function providerLabel(provider: CryptoProvider) {
  if (provider === "bitopro") return "BitoPro";
  if (provider === "binance") return "Binance";
  return "OKX";
}

export function normalizeCryptoBaseAsset(value: string): CryptoBaseAsset {
  return value.trim().toUpperCase();
}

export function cryptoBaseOptionsFromAssets(
  assets?: CryptoAssetDefinition[] | null
): CryptoBaseAsset[] {
  const baseOptions: CryptoBaseAsset[] = [];
  const seen = new Set<string>();

  assets?.forEach((asset) => {
    const base = normalizeCryptoBaseAsset(asset.asset ?? "");
    if (!base || seen.has(base)) return;
    seen.add(base);
    baseOptions.push(base);
  });

  return baseOptions.length > 0
    ? baseOptions
    : CRYPTO_BASE_OPTIONS.map((base) => normalizeCryptoBaseAsset(base));
}

function assetDefinitionByBase(
  assets: CryptoAssetDefinition[] | null | undefined,
  base: CryptoBaseAsset
) {
  const normalizedBase = normalizeCryptoBaseAsset(base);
  return assets?.find((asset) => normalizeCryptoBaseAsset(asset.asset ?? "") === normalizedBase) ?? null;
}

function supportsLocalTwd(
  base: CryptoBaseAsset,
  definition: CryptoAssetDefinition | null
) {
  if (definition) {
    return definition.resources?.local_twd === true || Boolean(definition.local_twd_provider_symbol);
  }
  return FALLBACK_LOCAL_TWD_BASES.has(normalizeCryptoBaseAsset(base));
}

function sourceProvidersForGlobalSpot(
  base: CryptoBaseAsset,
  definition: CryptoAssetDefinition | null
): CryptoProvider[] {
  if (definition) {
    const providers: CryptoProvider[] = [];
    if (definition.resources?.binance_spot) providers.push("binance");
    if (definition.resources?.okx_spot) providers.push("okx");
    return providers;
  }

  return normalizeCryptoBaseAsset(base) === "USDT" ? [] : ["binance", "okx"];
}

function normalizeOhlcvIntervals(intervals: readonly string[] | null | undefined) {
  const seen = new Set<string>();
  const normalized: CryptoOhlcvInterval[] = [];

  intervals?.forEach((interval) => {
    if (!CRYPTO_KLINE_INTERVAL_SET.has(interval) || seen.has(interval)) return;
    seen.add(interval);
    normalized.push(interval as CryptoOhlcvInterval);
  });

  return normalized;
}

function intervalsForProvider(
  provider: CryptoProvider,
  contractIntervals?: Partial<Record<CryptoProvider, string[]>> | null
) {
  const fromContract = normalizeOhlcvIntervals(contractIntervals?.[provider]);
  if (fromContract.length) return fromContract;
  return FALLBACK_OHLCV_INTERVALS_BY_PROVIDER[provider] ?? [...CRYPTO_KLINE_INTERVALS];
}

function providerIntervalsFor(
  providers: readonly CryptoProvider[],
  contractIntervals?: Partial<Record<CryptoProvider, string[]>> | null
) {
  const providerIntervals: CryptoProviderOhlcvIntervals = {};
  providers.forEach((provider) => {
    providerIntervals[provider] = intervalsForProvider(provider, contractIntervals);
  });
  return providerIntervals;
}

function unionProviderIntervals(providerIntervals: CryptoProviderOhlcvIntervals) {
  const supported = new Set<CryptoOhlcvInterval>();
  Object.values(providerIntervals).forEach((intervals) => {
    intervals?.forEach((interval) => supported.add(interval));
  });
  return CRYPTO_KLINE_INTERVALS.filter((interval) => supported.has(interval));
}

export function buildCryptoKlineInstruments(
  baseOptions: readonly CryptoBaseAsset[] = cryptoBaseOptionsFromAssets(),
  assets?: CryptoAssetDefinition[] | null,
  ohlcvIntervals?: Partial<Record<CryptoProvider, string[]>> | null
) {
  const instruments: CryptoKLineInstrument[] = [];

  baseOptions.forEach((rawBase) => {
    const base = normalizeCryptoBaseAsset(rawBase);
    const definition = assetDefinitionByBase(assets, base);

    if (supportsLocalTwd(base, definition)) {
      const providerIntervals = providerIntervalsFor(["bitopro"], ohlcvIntervals);
      instruments.push({
        key: `bitopro:${base}-TWD:spot`,
        provider: "bitopro",
        exchange: "BitoPro",
        symbol: `${base}-TWD`,
        baseAsset: base,
        quoteAsset: "TWD",
        instrumentType: "spot",
        role:
          base === "USDT"
            ? "Taiwan USDT/TWD conversion reference"
            : "Taiwan TWD spot reference",
        supportedIntervals: unionProviderIntervals(providerIntervals),
        providerIntervals,
      });
    }

    const sourceProviders = sourceProvidersForGlobalSpot(base, definition);
    if (!sourceProviders.length) return;

    const primaryProvider = sourceProviders.includes("binance")
      ? "binance"
      : sourceProviders[0];
    const exchangeLabel = sourceProviders.map(providerLabel).join(" / ");
    const providerIntervals = providerIntervalsFor(sourceProviders, ohlcvIntervals);

    instruments.push({
      key: `global:${base}-USDT:spot`,
      provider: primaryProvider,
      sourceProviders,
      primaryProvider,
      exchange: exchangeLabel,
      symbol: `${base}-USDT`,
      baseAsset: base,
      quoteAsset: "USDT",
      instrumentType: "spot",
      role: sourceProviders.length > 1
        ? "Global spot composite / primary provider with fallback"
        : "Global spot reference",
      supportedIntervals: unionProviderIntervals(providerIntervals),
      providerIntervals,
    });

    sourceProviders.forEach((provider) => {
      const singleProviderIntervals = providerIntervalsFor([provider], ohlcvIntervals);
      instruments.push({
        key: `${provider}:${base}-USDT:spot`,
        provider,
        exchange: providerLabel(provider),
        symbol: `${base}-USDT`,
        baseAsset: base,
        quoteAsset: "USDT",
        instrumentType: "spot",
        role: provider === "binance" ? "Global high-liquidity spot" : "Secondary global spot",
        supportedIntervals: unionProviderIntervals(singleProviderIntervals),
        providerIntervals: singleProviderIntervals,
        hidden: true,
      });
    });
  });

  return instruments;
}

export const CRYPTO_KLINE_INSTRUMENTS: CryptoKLineInstrument[] = buildCryptoKlineInstruments();

export const DEFAULT_CRYPTO_INSTRUMENT_KEY_BY_BASE = Object.fromEntries(
  CRYPTO_BASE_OPTIONS.map((base) => [
    base,
    defaultCryptoInstrumentKeyForBase(base),
  ])
) as Record<CryptoBaseAsset, string>;

export function defaultCryptoInstrumentKeyForBase(
  base: CryptoBaseAsset,
  instruments: readonly CryptoKLineInstrument[] = CRYPTO_KLINE_INSTRUMENTS
) {
  const normalizedBase = normalizeCryptoBaseAsset(base);
  const visibleInstruments = cryptoInstrumentsForBase(normalizedBase, instruments);
  const globalInstrument = visibleInstruments.find((instrument) =>
    instrument.key.startsWith(`global:${normalizedBase}-`)
  );
  const localInstrument = visibleInstruments.find(
    (instrument) =>
      instrument.provider === "bitopro" &&
      instrument.symbol === `${normalizedBase}-TWD`
  );

  return globalInstrument?.key ?? localInstrument?.key ?? visibleInstruments[0]?.key ?? "";
}

export function cryptoInstrumentsForBase(
  base: CryptoBaseAsset,
  instruments: readonly CryptoKLineInstrument[] = CRYPTO_KLINE_INSTRUMENTS
) {
  const normalizedBase = normalizeCryptoBaseAsset(base);
  return instruments.filter(
    (instrument) => instrument.baseAsset === normalizedBase && !instrument.hidden
  );
}

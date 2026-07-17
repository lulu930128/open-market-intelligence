"use client";

import { fetchJson, requestJson } from "@/lib/api";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import { omiChartColors } from "@/lib/themeColors";
import {
  cryptoSubscriptionItem,
  cryptoSubscriptionResourceEnabled,
  loadMarketDataSubscriptionSettings,
  type MarketDataSubscriptionItem,
  type MarketDataSubscriptionSettingsRead,
} from "@/lib/marketDataSubscriptions";
import { useI18n, type TranslationFunction } from "@/i18n";
import {
  CRYPTO_BASE_OPTIONS,
  buildCryptoKlineInstruments,
  cryptoBaseOptionsFromAssets,
  cryptoInstrumentsForBase,
  type CryptoBaseAsset,
  type CryptoAssetDefinition,
  type CryptoKLineInstrument,
  type CryptoProvider,
  type CryptoProviderContract,
} from "@/types/cryptoMarket";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CryptoKLinePanel from "@/components/CryptoKLinePanel";
import { StateSurface } from "@/components/LoadingPlaceholders";

type CryptoTicker = {
  provider: string;
  exchange: string;
  symbol: string;
  provider_symbol: string;
  last_price: number | null;
  bid_price: number | null;
  ask_price: number | null;
  high_24h: number | null;
  low_24h: number | null;
  price_change_24h: number | null;
  price_change_pct_24h: number | null;
  base_volume_24h: number | null;
  quote_volume_24h: number | null;
  fetched_at: string;
};

type CryptoOrderBook = {
  provider: string;
  exchange: string;
  symbol: string;
  provider_symbol: string;
  best_bid_price: number | null;
  best_bid_size: number | null;
  best_ask_price: number | null;
  best_ask_size: number | null;
  spread: number | null;
  spread_pct: number | null;
  bids?: OrderBookDepthLevel[];
  asks?: OrderBookDepthLevel[];
  fetched_at: string;
};

type OrderBookDepthLevel = {
  price: number | null;
  size: number | null;
  count?: number | null;
};

type CryptoDerivatives = {
  provider: string;
  exchange: string;
  symbol: string;
  mark_price: number | null;
  index_price: number | null;
  funding_rate: number | null;
  next_funding_time: string | null;
  open_interest: number | null;
  open_interest_value: number | null;
  fetched_at: string;
};

type CryptoMarketCap = {
  coin_id: string;
  symbol: string;
  name: string | null;
  current_price: number | null;
  market_cap: number | null;
  market_cap_rank: number | null;
  total_volume: number | null;
  price_change_pct_24h: number | null;
  fetched_at: string;
};

type CryptoSpread = {
  base_asset: string;
  global_provider: string;
  local_price: number | null;
  global_price: number | null;
  fx_rate: number | null;
  implied_twd_price: number | null;
  spread: number | null;
  spread_pct: number | null;
  observed_at: string;
};

type CryptoTickerHistory = CryptoTicker & {
  sampled_at: string;
  bid_size?: number | null;
  ask_size?: number | null;
};

type CryptoLiquidityHistory = CryptoOrderBook & {
  sampled_at: string;
};

type CryptoDerivativesHistory = CryptoDerivatives & {
  sampled_at: string;
};

type CryptoSpreadHistory = CryptoSpread & {
  sampled_at: string;
};

type CryptoLongShortRatioHistory = {
  provider: string;
  exchange: string;
  symbol: string;
  provider_symbol: string;
  base_asset: string;
  quote_asset: string;
  instrument_type: string;
  ratio_scope: string;
  long_ratio: number | null;
  short_ratio: number | null;
  long_short_ratio: number | null;
  event_time: string | null;
  sampled_at: string;
  fetched_at: string;
};

type CryptoLiquidationHeatmapCell = {
  provider: string;
  source_kind: string;
  method: string;
  exchange: string;
  symbol: string;
  provider_symbol: string;
  base_asset: string;
  quote_asset: string;
  instrument_type: string;
  time_bucket: string;
  bucket_seconds: number;
  price_bucket: number;
  price_bucket_size: number | null;
  liquidation_side: string;
  liquidation_notional: number | null;
  liquidation_quantity: number | null;
  event_count: number;
  intensity: number | null;
  generated_at: string;
  fetched_at: string;
};

type CryptoTrendHistory = {
  quote: CryptoTickerHistory[];
  liquidity: CryptoLiquidityHistory[];
  derivatives: CryptoDerivativesHistory[];
  spreads: CryptoSpreadHistory[];
  longShortRatios: CryptoLongShortRatioHistory[];
};

type TrendPoint = {
  time: string;
  value: number;
};

type TrendSeries = {
  key: string;
  label: string;
  color: string;
  points: TrendPoint[];
};

type LiquidityHeatmapCell = {
  key: string;
  provider: string;
  symbol: string;
  side: "bid" | "ask";
  time: string;
  price: number;
  size: number;
  intensity: number;
};

type LiquidityHeatmap = {
  cells: LiquidityHeatmapCell[];
  minPrice: number;
  maxPrice: number;
  minTime: number;
  maxTime: number;
  latestMid: number | null;
};

type LiquidationHeatmapCell = {
  key: string;
  provider: string;
  sourceKind: string;
  side: string;
  time: string;
  price: number;
  notional: number;
  eventCount: number;
  intensity: number;
};

type LiquidationHeatmap = {
  cells: LiquidationHeatmapCell[];
  minPrice: number;
  maxPrice: number;
  minTime: number;
  maxTime: number;
  totalNotional: number;
  totalEvents: number;
  providers: string[];
};

type CryptoRealtimeStatus = {
  enabled: boolean;
  running: boolean;
  websockets_available: boolean | null;
  subscription_policy?: string | null;
  task_count: number;
  active_task_count: number;
  latest_count: number;
  last_error: string | null;
  enabled_streams?: Array<{
    provider: string;
    resource: string;
    symbols: string[];
    message_resources?: string[];
  }>;
};

type CryptoAutoRefreshStatus = {
  enabled: boolean;
  running: boolean;
  subscription_policy?: string | null;
  active_resource_count: number;
  active_plan_count?: number;
  last_error: string | null;
  resources: Array<{
    key?: string;
    resource: string;
    providers?: string | null;
    mode?: string;
    ohlcv_intervals?: string[];
    enabled: boolean;
    interval_seconds: number | null;
    targets: string[];
    running: boolean;
    next_due_at: string | null;
    last_status: string | null;
    last_error: string | null;
    last_refreshed_count: number | null;
    last_error_count: number | null;
  }>;
};

type CryptoRealtimeLatest = {
  provider: string;
  resource: string;
  symbol: string;
  last_message_age_ms: number;
  stale: boolean;
  feed_lag_ms: number | null;
  data: Record<string, unknown>;
};

type CryptoSourceHealthEntry = {
  resource: string;
  provider: string;
  target: string;
  status: string;
  ok: boolean;
  row_count: number;
  reason: string;
};

type CryptoSourceHealth = {
  generated_at: string;
  summary: {
    entry_count: number;
    ok_count: number;
    empty_count: number;
    stale_count: number;
    error_count: number;
    disabled_count: number;
  };
  entries: CryptoSourceHealthEntry[];
};

type CryptoRefreshResult = {
  status: string;
  resource: string;
  requested_count: number;
  refreshed_count: number;
  error_count: number;
  skipped_count: number;
  intervals?: Array<{
    interval: string;
    status: string;
    requested_count: number;
    refreshed_count: number;
    error_count: number;
    skipped_count: number;
  }>;
};

function fallbackSubscriptionItem(base: CryptoBaseAsset): MarketDataSubscriptionItem {
  const normalizedBase = base.toUpperCase();
  const alwaysOn = normalizedBase === "BTC";
  const usdtReference = normalizedBase === "USDT";
  const resources: Record<string, boolean> = {
    quote: true,
    order_book: true,
    ohlcv: true,
    market_cap: true,
  };

  if (usdtReference) {
    resources.twd_reference = true;
  } else {
    resources.derivatives = true;
    resources.liquidation_event = true;
    resources.long_short_ratio = true;
  }

  if (normalizedBase === "BTC" || normalizedBase === "ETH") {
    resources.taiwan_spread = true;
  }

  return {
    key: `crypto:${normalizedBase}`,
    market: "crypto",
    group: "crypto",
    label: normalizedBase,
    mode: alwaysOn ? "always_on" : "on_select",
    resources,
    intervals: {
      quote_seconds: alwaysOn ? 5 : 15,
      order_book_seconds: alwaysOn ? 5 : 30,
      ohlcv_seconds: usdtReference ? 120 : alwaysOn ? 30 : 60,
      derivatives_seconds: alwaysOn ? 120 : 300,
      liquidation_event_seconds: alwaysOn ? 5 : 15,
      long_short_ratio_seconds: alwaysOn ? 300 : 900,
      market_cap_seconds: 900,
    },
    note: "Frontend fallback used only when the settings API is unavailable.",
  };
}

const FALLBACK_MARKET_DATA_SUBSCRIPTION_SETTINGS: MarketDataSubscriptionSettingsRead = {
  kind: "market_data_subscription_settings",
  version: "frontend_fallback.v1",
  source: "frontend_fallback",
  items: CRYPTO_BASE_OPTIONS.map(fallbackSubscriptionItem),
};

const EMPTY_CRYPTO_TREND_HISTORY: CryptoTrendHistory = {
  quote: [],
  liquidity: [],
  derivatives: [],
  spreads: [],
  longShortRatios: [],
};

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("en-US", {
    maximumFractionDigits: digits,
  });
}

function formatCompactNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const absValue = Math.abs(value);
  if (absValue >= 1_000_000_000) return `${formatNumber(value / 1_000_000_000, digits)}B`;
  if (absValue >= 1_000_000) return `${formatNumber(value / 1_000_000, digits)}M`;
  if (absValue >= 1_000) return `${formatNumber(value / 1_000, digits)}K`;
  return formatNumber(value, digits);
}

function formatPct(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("en-US", { maximumFractionDigits: digits })}%`;
}

function formatTime(value: string | null | undefined, locale: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString(locale, { hour12: false });
}

function formatDateTimeShort(value: string | null | undefined, locale: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatAge(ms: number | null | undefined) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${Math.round(ms / 1000)}s`;
}

function statusClass(status: string | null | undefined, ok?: boolean) {
  if (ok || status === "live" || status === "success") return "border-omi-market-up/40 text-omi-market-up";
  if (status === "stale" || status === "partial_success") return "border-omi-warning/40 text-omi-warning";
  if (status === "empty" || status === "disabled") return "border-omi-border text-omi-text-muted";
  if (status === "error") return "border-omi-danger/50 text-omi-danger";
  return "border-omi-border text-omi-text-muted";
}

function compactProvider(provider: string) {
  if (provider === "bitopro") return "BitoPro";
  if (provider === "binance") return "Binance";
  if (provider === "okx") return "OKX";
  if (provider === "coingecko") return "CoinGecko";
  if (provider === "coinglass") return "CoinGlass";
  if (provider === "omi_local") return "OMI local";
  return provider;
}

function normalizedContractResource(resource: string) {
  return resource
    .replace(/^crypto_realtime_/, "")
    .replace(/^crypto_/, "")
    .replace(/^realtime_/, "");
}

function contractResourceStatus(
  contract: CryptoProviderContract | null,
  entry: CryptoSourceHealthEntry
) {
  const provider = contract?.providers?.[entry.provider];
  const resource = normalizedContractResource(entry.resource);
  return provider?.resource_status?.[resource] ?? provider?.status ?? null;
}

function healthEntryCategory(
  entry: CryptoSourceHealthEntry,
  maturity: string | null,
  t: TranslationFunction
) {
  const resource = normalizedContractResource(entry.resource);
  if (entry.resource.includes("realtime") || entry.resource.includes("persistence")) {
    return t("crypto.market.healthRealtime");
  }
  if (
    resource.includes("cvd") ||
    resource.includes("liquidation") ||
    resource.includes("long_short") ||
    maturity === "event_driven" ||
    maturity === "api_key_required" ||
    maturity === "provider_pending" ||
    maturity === "local_fallback"
  ) {
    return t("crypto.market.healthAdvanced");
  }
  return t("crypto.market.healthCore");
}

function healthStatusLabel(
  entry: CryptoSourceHealthEntry,
  maturity: string | null,
  t: TranslationFunction
) {
  if (entry.ok) return t("crypto.market.status.ok");
  if (entry.status === "stale") return t("crypto.market.status.stale");
  if (entry.status === "disabled") return t("crypto.market.status.disabled");
  if (entry.status === "error") return t("crypto.market.status.error");
  if (maturity === "provider_pending") return t("crypto.market.status.providerPending");
  if (maturity === "api_key_required") return t("crypto.market.status.apiKeyRequired");
  if (maturity === "local_fallback") return t("crypto.market.status.localFallback");
  if (maturity === "event_driven") return t("crypto.market.status.noRecentEvent");
  if (entry.status === "empty") return t("crypto.market.status.empty");
  return entry.status;
}

function healthDisplayEntries(entries: CryptoSourceHealthEntry[]) {
  const issues = entries.filter((entry) => !entry.ok);
  if (issues.length) {
    return issues.sort((left, right) => {
      const leftErrorScore = left.status === "error" ? 0 : left.status === "stale" ? 1 : 2;
      const rightErrorScore = right.status === "error" ? 0 : right.status === "stale" ? 1 : 2;
      return leftErrorScore - rightErrorScore;
    });
  }
  return entries;
}

function subscriptionModeLabel(
  item: MarketDataSubscriptionItem | null,
  t: TranslationFunction
) {
  if (!item) return t("crypto.market.subscriptionModes.loading");
  if (item.mode === "always_on") return t("crypto.market.subscriptionModes.always_on");
  if (item.mode === "on_select") return t("crypto.market.subscriptionModes.on_select");
  if (item.mode === "manual") return t("crypto.market.subscriptionModes.manual");
  return t("crypto.market.subscriptionModes.disabled");
}

function subscriptionSourceLabel(
  settings: MarketDataSubscriptionSettingsRead | null,
  t: TranslationFunction
) {
  if (!settings) return t("crypto.market.subscriptionSource.loading");
  if (settings.source === "frontend_fallback") {
    return t("crypto.market.subscriptionSource.frontendFallback");
  }
  return settings.source;
}

type LoadOutcome<T> =
  | { ok: true; label: string; value: T }
  | { ok: false; label: string; error: Error };

type CryptoDataView = "overview" | "risk" | "signals" | "raw" | "health";

const CRYPTO_PANEL_REFRESH_INTERVAL_MS = 30000;

function normalizeLoadError(error: unknown) {
  return error instanceof Error ? error : new Error(String(error));
}

async function loadOutcome<T>(
  label: string,
  promise: Promise<T>
): Promise<LoadOutcome<T>> {
  try {
    return { ok: true, label, value: await promise };
  } catch (error) {
    return { ok: false, label, error: normalizeLoadError(error) };
  }
}

function loadFailureList(outcomes: readonly LoadOutcome<unknown>[]) {
  return outcomes.flatMap((outcome) =>
    outcome.ok ? [] : [{ label: outcome.label, error: outcome.error }]
  );
}

function loadFailureMessage(
  t: TranslationFunction,
  messageKey: string,
  failures: { label: string; error: Error }[]
) {
  const resources = failures
    .map((failure) => failure.label)
    .slice(0, 6)
    .join(", ");
  const detail = failures[0]?.error.message;
  const message = t(messageKey, { resources });
  return detail ? `${message}: ${detail}` : message;
}

async function loadMarketDataSubscriptionSettingsForPanel() {
  try {
    return await loadMarketDataSubscriptionSettings();
  } catch {
    return FALLBACK_MARKET_DATA_SUBSCRIPTION_SETTINGS;
  }
}

function refreshBasesForResource(
  settings: MarketDataSubscriptionSettingsRead | null,
  selectedBase: CryptoBaseAsset,
  resource: string,
  baseOptions: readonly CryptoBaseAsset[]
) {
  const bases: CryptoBaseAsset[] = [];
  baseOptions.forEach((base) => {
    if (!cryptoSubscriptionResourceEnabled(settings, base, resource)) return;
    const item = cryptoSubscriptionItem(settings, base);
    if (item?.mode === "always_on" || base === selectedBase) {
      bases.push(base);
    }
  });
  return bases;
}

function spotProviderSymbolBatches(
  bases: CryptoBaseAsset[],
  instruments: readonly CryptoKLineInstrument[]
) {
  const symbolsByProvider = new Map<CryptoProvider, Set<string>>();

  bases.forEach((base) => {
    cryptoInstrumentsForBase(base, instruments).forEach((instrument) => {
      const providers = instrument.sourceProviders?.length
        ? instrument.sourceProviders
        : [instrument.provider];
      providers.forEach((provider) => {
        const symbols = symbolsByProvider.get(provider) ?? new Set<string>();
        symbols.add(instrument.symbol);
        symbolsByProvider.set(provider, symbols);
      });
    });
  });

  return Array.from(symbolsByProvider.entries()).map(([provider, symbols]) => ({
    providers: provider,
    symbols: Array.from(symbols),
  }));
}

function assetDefinitionByBase(
  assets: readonly CryptoAssetDefinition[] | null | undefined,
  base: CryptoBaseAsset
) {
  return assets?.find((asset) => asset.asset.toUpperCase() === base.toUpperCase()) ?? null;
}

function supportsTaiwanSpread(
  base: CryptoBaseAsset,
  assets: readonly CryptoAssetDefinition[] | null | undefined
) {
  const definition = assetDefinitionByBase(assets, base);
  if (!definition) return base === "BTC" || base === "ETH";
  return definition.resources?.taiwan_spread === true;
}

function derivativeProviderSymbolBatches(
  bases: CryptoBaseAsset[],
  assets: readonly CryptoAssetDefinition[] | null | undefined
) {
  const symbolsByProvider = new Map<"binance" | "okx", Set<string>>();

  bases.forEach((base) => {
    if (base === "USDT") return;

    const definition = assetDefinitionByBase(assets, base);
    const supportsBinance = definition
      ? definition.resources?.binance_perpetual === true
      : true;
    const supportsOkx = definition
      ? definition.resources?.okx_perpetual === true
      : true;

    ([
      ["binance", supportsBinance],
      ["okx", supportsOkx],
    ] as const).forEach(([provider, supported]) => {
      if (!supported) return;
      const symbols = symbolsByProvider.get(provider) ?? new Set<string>();
      symbols.add(`${base}-USDT`);
      symbolsByProvider.set(provider, symbols);
    });
  });

  return Array.from(symbolsByProvider.entries()).map(([provider, symbols]) => ({
    providers: provider,
    symbols: Array.from(symbols),
  }));
}

function liquidationSymbolsForBases(
  bases: CryptoBaseAsset[],
  assets: readonly CryptoAssetDefinition[] | null | undefined
) {
  const symbols = new Set<string>();

  bases.forEach((base) => {
    if (base === "USDT") return;

    const definition = assetDefinitionByBase(assets, base);
    const supportsBinance = definition
      ? definition.resources?.binance_perpetual === true
      : true;
    if (!supportsBinance) return;

    symbols.add(`${base}-USDT`);
  });

  return Array.from(symbols);
}

function firstBySymbol(rows: CryptoTicker[], provider: string, symbol: string) {
  return rows.find((row) => row.provider === provider && row.symbol === symbol) ?? null;
}

function finiteNumber(value: number | null | undefined) {
  return value !== null && value !== undefined && Number.isFinite(value) ? value : null;
}

function sumFiniteValues(...values: Array<number | null | undefined>) {
  let hasValue = false;
  const total = values.reduce<number>((sum, value) => {
    const nextValue = finiteNumber(value);
    if (nextValue === null) return sum;
    hasValue = true;
    return sum + nextValue;
  }, 0);

  return hasValue ? total : null;
}

function historySymbolsForBase(base: CryptoBaseAsset) {
  if (base === "USDT") return "USDT-TWD";
  return `${base}-USDT,${base}-TWD`;
}

function buildTrendSeries<T>(
  rows: readonly T[],
  options: {
    getKey: (row: T) => string;
    getLabel: (row: T) => string;
    getTime: (row: T) => string | null | undefined;
    getValue: (row: T) => number | null | undefined;
    colors?: readonly string[];
  }
): TrendSeries[] {
  const colors = options.colors ?? [
    omiChartColors.info,
    omiChartColors.warning,
    omiChartColors.teal,
    omiChartColors.purple,
  ];
  const seriesByKey = new Map<string, TrendSeries>();

  rows.forEach((row) => {
    const time = options.getTime(row);
    const value = finiteNumber(options.getValue(row));
    if (!time || value === null) return;

    const key = options.getKey(row);
    let series = seriesByKey.get(key);
    if (!series) {
      series = {
        key,
        label: options.getLabel(row),
        color: colors[seriesByKey.size % colors.length] ?? omiChartColors.info,
        points: [],
      };
      seriesByKey.set(key, series);
    }
    series.points.push({ time, value });
  });

  return Array.from(seriesByKey.values())
    .map((series) => ({
      ...series,
      points: series.points.sort((a, b) => Date.parse(a.time) - Date.parse(b.time)),
    }))
    .filter((series) => series.points.length >= 2);
}

function depthLevelValue(value: number | null | undefined) {
  return value !== null && value !== undefined && Number.isFinite(value) ? value : null;
}

function buildLiquidityHeatmap(rows: readonly CryptoLiquidityHistory[]): LiquidityHeatmap | null {
  const recentRows = rows
    .filter((row) => Number.isFinite(Date.parse(row.sampled_at)))
    .slice()
    .sort((a, b) => Date.parse(a.sampled_at) - Date.parse(b.sampled_at))
    .slice(-140);
  const rawCells: Array<Omit<LiquidityHeatmapCell, "intensity">> = [];

  recentRows.forEach((row, rowIndex) => {
    ([
      ["bid", row.bids ?? []],
      ["ask", row.asks ?? []],
    ] as const).forEach(([side, levels]) => {
      levels.slice(0, 12).forEach((level, levelIndex) => {
        const price = depthLevelValue(level.price);
        const size = depthLevelValue(level.size);
        if (price === null || size === null || size <= 0) return;
        rawCells.push({
          key: `${row.provider}-${row.symbol}-${row.sampled_at}-${side}-${levelIndex}-${rowIndex}`,
          provider: row.provider,
          symbol: row.symbol,
          side,
          time: row.sampled_at,
          price,
          size,
        });
      });
    });
  });

  if (!rawCells.length) return null;

  const prices = rawCells.map((cell) => cell.price);
  const times = rawCells.map((cell) => Date.parse(cell.time));
  const sizes = rawCells.map((cell) => cell.size);
  const maxSize = Math.max(...sizes, 1);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const latestRow = recentRows[recentRows.length - 1] ?? null;
  const latestBid = depthLevelValue(latestRow?.best_bid_price);
  const latestAsk = depthLevelValue(latestRow?.best_ask_price);

  return {
    cells: rawCells.map((cell) => ({
      ...cell,
      intensity: Math.sqrt(cell.size / maxSize),
    })),
    minPrice,
    maxPrice,
    minTime,
    maxTime,
    latestMid: latestBid !== null && latestAsk !== null ? (latestBid + latestAsk) / 2 : null,
  };
}

function normalizedIntensity(value: number | null | undefined) {
  const numberValue = finiteNumber(value);
  if (numberValue === null) return null;
  return Math.max(0, Math.min(numberValue, 1));
}

function buildLiquidationHeatmap(rows: readonly CryptoLiquidationHeatmapCell[]): LiquidationHeatmap | null {
  const recentRows = rows
    .filter((row) => Number.isFinite(Date.parse(row.time_bucket)))
    .slice()
    .sort((a, b) => Date.parse(a.time_bucket) - Date.parse(b.time_bucket))
    .slice(-180);
  const rawCells: Array<Omit<LiquidationHeatmapCell, "intensity"> & { rawIntensity: number | null }> = [];

  recentRows.forEach((row, rowIndex) => {
    const price = finiteNumber(row.price_bucket);
    if (price === null) return;
    const notional = finiteNumber(row.liquidation_notional) ?? 0;
    rawCells.push({
      key: `${row.provider}-${row.method}-${row.symbol}-${row.time_bucket}-${row.price_bucket}-${row.liquidation_side}-${rowIndex}`,
      provider: row.provider,
      sourceKind: row.source_kind,
      side: row.liquidation_side || "unknown",
      time: row.time_bucket,
      price,
      notional,
      eventCount: Math.max(Number(row.event_count ?? 0), 0),
      rawIntensity: normalizedIntensity(row.intensity),
    });
  });

  if (!rawCells.length) return null;

  const prices = rawCells.map((cell) => cell.price);
  const times = rawCells.map((cell) => Date.parse(cell.time));
  const notionals = rawCells.map((cell) => cell.notional);
  const maxNotional = Math.max(...notionals, 1);
  const providerSet = new Set<string>();
  let totalNotional = 0;
  let totalEvents = 0;

  rawCells.forEach((cell) => {
    providerSet.add(cell.provider);
    totalNotional += cell.notional;
    totalEvents += cell.eventCount;
  });

  return {
    cells: rawCells.map(({ rawIntensity, ...cell }) => ({
      ...cell,
      intensity: rawIntensity ?? Math.sqrt(cell.notional / maxNotional),
    })),
    minPrice: Math.min(...prices),
    maxPrice: Math.max(...prices),
    minTime: Math.min(...times),
    maxTime: Math.max(...times),
    totalNotional,
    totalEvents,
    providers: Array.from(providerSet).sort(),
  };
}

type Props = {
  selectedBase: CryptoBaseAsset;
  selectedInstrumentKey: string | null;
};

function emitCryptoRefreshStatus(results: CryptoRefreshResult[], t: TranslationFunction) {
  const requestedCount = results.reduce((sum, result) => sum + result.requested_count, 0);
  const refreshedCount = results.reduce((sum, result) => sum + result.refreshed_count, 0);
  const errorCount = results.reduce((sum, result) => sum + result.error_count, 0);
  const skippedCount = results.reduce((sum, result) => sum + result.skipped_count, 0);
  const resources = results.map((result) => result.resource).join(", ");

  emitDataStatusEvent({
    market: "crypto",
    level: errorCount > 0 ? "warning" : refreshedCount > 0 ? "success" : "info",
    title: errorCount > 0
      ? t("crypto.market.refreshPartial")
      : t("crypto.market.refreshComplete"),
    message: t("crypto.market.refreshSummary", {
      resources: resources || t("crypto.market.subscriptionFallback"),
      requested: requestedCount,
      refreshed: refreshedCount,
      skipped: skippedCount,
      errors: errorCount,
    }),
    source: t("crypto.market.eyebrow"),
  });
}

function summarizeCryptoAutoRefreshIssue(
  status: CryptoAutoRefreshStatus | null,
  t: TranslationFunction
) {
  if (!status) return null;

  const failedResources = status.resources.filter((resource) => {
    if (!resource.enabled) return false;
    if (resource.last_error) return true;
    if ((resource.last_error_count ?? 0) > 0) return true;
    return resource.last_status === "error" || resource.last_status === "partial_success";
  });

  if (!status.last_error && failedResources.length === 0) return null;

  const errorCount = failedResources.reduce(
    (sum, resource) => sum + (resource.last_error_count ?? 0),
    status.last_error ? 1 : 0
  );
  const resourceLabels = failedResources
    .slice(0, 6)
    .map((resource) => (
      resource.providers ? `${resource.resource}/${resource.providers}` : resource.resource
    ));
  const firstDetail =
    status.last_error ??
    failedResources.find((resource) => resource.last_error)?.last_error ??
    failedResources.find((resource) => resource.last_status)?.last_status ??
    "";
  const signature = [
    status.last_error ?? "",
    failedResources
      .map((resource) => [
        resource.key ?? resource.resource,
        resource.providers ?? "",
        resource.last_status ?? "",
        resource.last_error_count ?? 0,
        resource.last_error ?? "",
      ].join(":"))
      .join("|"),
  ].join("#");

  return {
    signature,
    level: status.last_error ? "error" as const : "warning" as const,
    title: status.last_error
      ? t("crypto.market.autoRefreshFailed")
      : t("crypto.market.autoRefreshPartial"),
    message: t("crypto.market.autoRefreshSummary", {
      resources: resourceLabels.join(", ") || t("crypto.market.subscriptionFallback"),
      plans: failedResources.length,
      errors: errorCount,
      detail: firstDetail,
    }),
  };
}

export default function CryptoMarketPanel({ selectedBase, selectedInstrumentKey }: Props) {
  const { locale, t } = useI18n();
  const [quotes, setQuotes] = useState<CryptoTicker[]>([]);
  const [orderBooks, setOrderBooks] = useState<CryptoOrderBook[]>([]);
  const [derivatives, setDerivatives] = useState<CryptoDerivatives[]>([]);
  const [marketCaps, setMarketCaps] = useState<CryptoMarketCap[]>([]);
  const [spreads, setSpreads] = useState<CryptoSpread[]>([]);
  const [trendHistory, setTrendHistory] = useState<CryptoTrendHistory>(EMPTY_CRYPTO_TREND_HISTORY);
  const [liquidationHeatmapRows, setLiquidationHeatmapRows] = useState<CryptoLiquidationHeatmapCell[]>([]);
  const [realtimeStatus, setRealtimeStatus] = useState<CryptoRealtimeStatus | null>(null);
  const [realtimeLatest, setRealtimeLatest] = useState<CryptoRealtimeLatest[]>([]);
  const [autoRefreshStatus, setAutoRefreshStatus] = useState<CryptoAutoRefreshStatus | null>(null);
  const [sourceHealth, setSourceHealth] = useState<CryptoSourceHealth | null>(null);
  const [providerContract, setProviderContract] = useState<CryptoProviderContract | null>(null);
  const [providerAssets, setProviderAssets] = useState<CryptoAssetDefinition[] | null>(null);
  const [providerOhlcvIntervals, setProviderOhlcvIntervals] =
    useState<CryptoProviderContract["ohlcv_intervals"] | null>(null);
  const [subscriptionSettings, setSubscriptionSettings] =
    useState<MarketDataSubscriptionSettingsRead | null>(null);
  const [chartProfessionalMode, setChartProfessionalMode] = useState(false);
  const [klineRefreshRevision, setKlineRefreshRevision] = useState(0);
  const [activeDataView, setActiveDataView] = useState<CryptoDataView>("overview");
  const onSelectRefreshKeyRef = useRef<string | null>(null);
  const lastAutoRefreshIssueRef = useRef<string | null>(null);
  const cryptoBaseOptions = useMemo(
    () => cryptoBaseOptionsFromAssets(providerAssets),
    [providerAssets]
  );
  const cryptoKlineInstruments = useMemo(
    () => buildCryptoKlineInstruments(cryptoBaseOptions, providerAssets, providerOhlcvIntervals),
    [cryptoBaseOptions, providerAssets, providerOhlcvIntervals]
  );

  const loadRealtime = useCallback(async () => {
    const [status, latest, autoStatus] = await Promise.all([
      fetchJson<CryptoRealtimeStatus>("/api/crypto-market/realtime/status").catch(() => null),
      fetchJson<CryptoRealtimeLatest[]>("/api/crypto-market/realtime/latest").catch(() => null),
      fetchJson<CryptoAutoRefreshStatus>("/api/crypto-market/auto-refresh/status").catch(() => null),
    ]);

    if (status) {
      setRealtimeStatus(status);
    }
    if (latest) {
      setRealtimeLatest(latest);
    }
    setAutoRefreshStatus(autoStatus);
  }, []);

  const loadData = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;

    try {
      const [
        quotesResult,
        orderBooksResult,
        derivativesResult,
        marketCapsResult,
        spreadsResult,
        quoteHistoryResult,
        liquidityHistoryResult,
        derivativesHistoryResult,
        spreadHistoryResult,
        longShortRatioHistoryResult,
        liquidationHeatmapResult,
        sourceHealthResult,
        providerContractResult,
        subscriptionSettingsResult,
      ] = await Promise.all([
        loadOutcome(
          t("crypto.market.quotes"),
          fetchJson<CryptoTicker[]>("/api/crypto-market/quotes/latest", { limit: 50 })
        ),
        loadOutcome(
          t("crypto.market.orderBook"),
          fetchJson<CryptoOrderBook[]>("/api/crypto-market/order-books/latest", { limit: 50 })
        ),
        loadOutcome(
          t("crypto.market.perpetuals"),
          fetchJson<CryptoDerivatives[]>("/api/crypto-market/derivatives/latest", { limit: 50 })
        ),
        loadOutcome(
          t("crypto.market.marketCap"),
          fetchJson<CryptoMarketCap[]>("/api/crypto-market/market-caps/latest", { limit: 20 })
        ),
        loadOutcome(
          t("crypto.market.taiwanSpread"),
          fetchJson<CryptoSpread[]>("/api/crypto-market/spreads", { limit: 20 })
        ),
        loadOutcome(
          t("crypto.market.trends"),
          fetchJson<CryptoTickerHistory[]>("/api/crypto-market/quotes/history", {
            symbols: historySymbolsForBase(selectedBase),
            limit: 500,
            ascending: true,
          })
        ),
        loadOutcome(
          t("crypto.market.microstructure"),
          fetchJson<CryptoLiquidityHistory[]>("/api/crypto-market/order-books/history", {
            symbols: historySymbolsForBase(selectedBase),
            limit: 500,
            ascending: true,
          })
        ),
        loadOutcome(
          t("crypto.market.trendFunding"),
          selectedBase === "USDT"
            ? Promise.resolve([] as CryptoDerivativesHistory[])
            : fetchJson<CryptoDerivativesHistory[]>("/api/crypto-market/derivatives/history", {
                symbols: `${selectedBase}-USDT`,
                limit: 500,
                ascending: true,
              })
        ),
        loadOutcome(
          t("crypto.market.taiwanSpread"),
          fetchJson<CryptoSpreadHistory[]>("/api/crypto-market/spreads/history", {
            base: selectedBase,
            limit: 500,
            ascending: true,
          })
        ),
        loadOutcome(
          t("crypto.market.longShortRatio"),
          selectedBase === "USDT"
            ? Promise.resolve([] as CryptoLongShortRatioHistory[])
            : fetchJson<CryptoLongShortRatioHistory[]>("/api/crypto-market/long-short-ratios/history", {
                symbols: `${selectedBase}-USDT`,
                limit: 500,
                ascending: true,
              })
        ),
        loadOutcome(
          t("crypto.market.liquidationHeatmap"),
          selectedBase === "USDT"
            ? Promise.resolve([] as CryptoLiquidationHeatmapCell[])
            : fetchJson<CryptoLiquidationHeatmapCell[]>("/api/crypto-market/liquidations/heatmap", {
                symbols: `${selectedBase}-USDT`,
                limit: 500,
                ascending: true,
              })
        ),
        loadOutcome(
          t("crypto.market.sourceHealth"),
          fetchJson<CryptoSourceHealth>("/api/crypto-market/source-health", {
            base: selectedBase,
            include_events: false,
            max_entries: 80,
          })
        ),
        loadOutcome(
          t("crypto.market.providerContract"),
          fetchJson<CryptoProviderContract>("/api/crypto-market/provider-contract")
        ),
        loadOutcome(
          t("crypto.market.subscriptionLabel"),
          loadMarketDataSubscriptionSettingsForPanel()
        ),
        loadRealtime(),
      ]);

      const loadFailures = loadFailureList([
        quotesResult,
        orderBooksResult,
        derivativesResult,
        marketCapsResult,
        spreadsResult,
        quoteHistoryResult,
        liquidityHistoryResult,
        derivativesHistoryResult,
        spreadHistoryResult,
        longShortRatioHistoryResult,
        liquidationHeatmapResult,
        sourceHealthResult,
        providerContractResult,
        subscriptionSettingsResult,
      ]);
      const userFacingLoadFailures = loadFailureList([
        quotesResult,
        orderBooksResult,
        derivativesResult,
        marketCapsResult,
        spreadsResult,
        quoteHistoryResult,
        derivativesHistoryResult,
        spreadHistoryResult,
        longShortRatioHistoryResult,
        sourceHealthResult,
        providerContractResult,
        subscriptionSettingsResult,
      ]);

      const criticalOutcomes = [
        quotesResult,
        orderBooksResult,
        derivativesResult,
        marketCapsResult,
        spreadsResult,
        quoteHistoryResult,
        liquidityHistoryResult,
        spreadHistoryResult,
        sourceHealthResult,
        providerContractResult,
      ];

      if (criticalOutcomes.every((outcome) => !outcome.ok)) {
        throw loadFailures[0].error;
      }

      if (quotesResult.ok) setQuotes(quotesResult.value);
      if (orderBooksResult.ok) setOrderBooks(orderBooksResult.value);
      if (derivativesResult.ok) setDerivatives(derivativesResult.value);
      if (marketCapsResult.ok) setMarketCaps(marketCapsResult.value);
      if (spreadsResult.ok) setSpreads(spreadsResult.value);
      setTrendHistory((current) => ({
        quote: quoteHistoryResult.ok ? quoteHistoryResult.value : current.quote,
        liquidity: liquidityHistoryResult.ok ? liquidityHistoryResult.value : current.liquidity,
        derivatives: derivativesHistoryResult.ok
          ? derivativesHistoryResult.value
          : current.derivatives,
        spreads: spreadHistoryResult.ok ? spreadHistoryResult.value : current.spreads,
        longShortRatios: longShortRatioHistoryResult.ok
          ? longShortRatioHistoryResult.value
          : current.longShortRatios,
      }));
      if (liquidationHeatmapResult.ok) {
        setLiquidationHeatmapRows(liquidationHeatmapResult.value);
      }
      if (sourceHealthResult.ok) {
        setSourceHealth(sourceHealthResult.value);
      }
      if (providerContractResult.ok) {
        setProviderContract(providerContractResult.value);
        setProviderAssets(providerContractResult.value.assets ?? null);
        setProviderOhlcvIntervals(providerContractResult.value.ohlcv_intervals ?? null);
      }
      if (subscriptionSettingsResult.ok) {
        setSubscriptionSettings(subscriptionSettingsResult.value);
      }
      if (!silent && userFacingLoadFailures.length) {
        emitDataStatusEvent({
          market: "crypto",
          level: "warning",
          title: t("crypto.market.loadPartial"),
          message: loadFailureMessage(t, "crypto.market.loadPartialMessage", userFacingLoadFailures),
          source: t("crypto.market.eyebrow"),
        });
      }
    } catch (error) {
      if (!silent) {
        emitDataStatusEvent({
          market: "crypto",
          level: "error",
          title: t("crypto.market.loadFailed"),
          message: error instanceof Error ? error.message : "Failed to load crypto data",
          source: t("crypto.market.eyebrow"),
        });
      }
    }
  }, [loadRealtime, selectedBase, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadData();
    }, 0);

    return () => window.clearTimeout(timer);
  }, [loadData]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void loadRealtime().catch(() => {
        // Full load errors are shown elsewhere; realtime polling should not replace the page state.
      });
    }, 5000);

    return () => window.clearInterval(interval);
  }, [loadRealtime]);

  useEffect(() => {
    const issue = summarizeCryptoAutoRefreshIssue(autoRefreshStatus, t);
    if (!issue) {
      lastAutoRefreshIssueRef.current = null;
      return;
    }
    if (lastAutoRefreshIssueRef.current === issue.signature) return;

    lastAutoRefreshIssueRef.current = issue.signature;
    emitDataStatusEvent({
      market: "crypto",
      level: issue.level,
      title: issue.title,
      message: issue.message,
      source: t("crypto.market.eyebrow"),
    });
  }, [autoRefreshStatus, t]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadData({ silent: true });
    }, CRYPTO_PANEL_REFRESH_INTERVAL_MS);

    return () => window.clearInterval(interval);
  }, [loadData]);

  const refreshCoreData = useCallback(async (options?: { emitStatus?: boolean }) => {
    try {
      const policy =
        subscriptionSettings ?? (await loadMarketDataSubscriptionSettingsForPanel());
      setSubscriptionSettings(policy);
      const results: CryptoRefreshResult[] = [];

      const quoteBatches = spotProviderSymbolBatches(
        refreshBasesForResource(policy, selectedBase, "quote", cryptoBaseOptions),
        cryptoKlineInstruments
      );
      const orderBookBatches = spotProviderSymbolBatches(
        refreshBasesForResource(policy, selectedBase, "order_book", cryptoBaseOptions),
        cryptoKlineInstruments
      );
      const ohlcvBatches = spotProviderSymbolBatches(
        refreshBasesForResource(policy, selectedBase, "ohlcv", cryptoBaseOptions),
        cryptoKlineInstruments
      );
      const derivativeBatches = derivativeProviderSymbolBatches(
        refreshBasesForResource(policy, selectedBase, "derivatives", cryptoBaseOptions),
        providerAssets
      );
      const marketCapAssets = refreshBasesForResource(
        policy,
        selectedBase,
        "market_cap",
        cryptoBaseOptions
      );
      const spreadBases = refreshBasesForResource(
        policy,
        selectedBase,
        "taiwan_spread",
        cryptoBaseOptions
      ).filter((base) => supportsTaiwanSpread(base, providerAssets));
      const liquidationSymbols = liquidationSymbolsForBases(
        refreshBasesForResource(policy, selectedBase, "liquidation_event", cryptoBaseOptions),
        providerAssets
      );
      const longShortSymbols = liquidationSymbolsForBases(
        refreshBasesForResource(policy, selectedBase, "long_short_ratio", cryptoBaseOptions),
        providerAssets
      );

      for (const batch of quoteBatches) {
        if (!batch.symbols.length) continue;
        results.push(
          await requestJson<CryptoRefreshResult>(
            "/api/crypto-market/quotes/refresh",
            { method: "POST" },
            { providers: batch.providers, symbols: batch.symbols.join(",") }
          )
        );
      }
      for (const batch of orderBookBatches) {
        if (!batch.symbols.length) continue;
        results.push(
          await requestJson<CryptoRefreshResult>(
            "/api/crypto-market/order-books/refresh",
            { method: "POST" },
            { providers: batch.providers, symbols: batch.symbols.join(","), depth_limit: 5 }
          )
        );
      }
      for (const batch of ohlcvBatches) {
        if (!batch.symbols.length) continue;
        results.push(
          await requestJson<CryptoRefreshResult>(
            "/api/crypto-market/ohlcv/refresh-bundle",
            { method: "POST" },
            {
              providers: batch.providers,
              symbols: batch.symbols.join(","),
            }
          )
        );
      }
      for (const batch of derivativeBatches) {
        if (!batch.symbols.length) continue;
        results.push(
          await requestJson<CryptoRefreshResult>(
            "/api/crypto-market/derivatives/refresh",
            { method: "POST" },
            { providers: batch.providers, symbols: batch.symbols.join(",") }
          )
        );
      }
      if (marketCapAssets.length) {
        results.push(
          await requestJson<CryptoRefreshResult>(
            "/api/crypto-market/market-caps/refresh",
            { method: "POST" },
            { assets: marketCapAssets.join(","), vs_currency: "usd" }
          )
        );
      }
      if (spreadBases.length) {
        results.push(
          await requestJson<CryptoRefreshResult>(
            "/api/crypto-market/spreads/refresh",
            { method: "POST" },
            { bases: spreadBases.join(","), global_providers: "binance,okx" }
          )
        );
      }
      if (liquidationSymbols.length) {
        results.push(
          await requestJson<CryptoRefreshResult>(
            "/api/crypto-market/liquidations/refresh",
            { method: "POST" },
            {
              providers: "coinglass",
              symbols: liquidationSymbols.join(","),
              range: "24h",
              allow_local_fallback: true,
            }
          )
        );
      }
      if (longShortSymbols.length) {
        results.push(
          await requestJson<CryptoRefreshResult>(
            "/api/crypto-market/long-short-ratios/refresh",
            { method: "POST" },
            { providers: "binance", symbols: longShortSymbols.join(",") }
          )
        );
      }

      if (results.length === 0) {
        results.push({
          status: "empty",
          resource: "subscription",
          requested_count: 0,
          refreshed_count: 0,
          error_count: 0,
          skipped_count: 1,
        });
      }
      if (options?.emitStatus !== false || results.some((result) => result.error_count > 0)) {
        emitCryptoRefreshStatus(results, t);
      }
      await loadData({ silent: options?.emitStatus === false });
      if (results.some((result) => result.resource === "ohlcv_bundle" && result.refreshed_count > 0)) {
        setKlineRefreshRevision((value) => value + 1);
      }
    } catch (error) {
      emitDataStatusEvent({
        market: "crypto",
        level: "error",
        title: t("crypto.market.refreshFailed"),
        message: error instanceof Error ? error.message : "Failed to refresh crypto data",
        source: t("crypto.market.eyebrow"),
      });
    }
  }, [
    cryptoBaseOptions,
    cryptoKlineInstruments,
    loadData,
    providerAssets,
    selectedBase,
    subscriptionSettings,
    t,
  ]);

  const selectedGlobalQuote = useMemo(
    () => firstBySymbol(quotes, "binance", `${selectedBase}-USDT`),
    [quotes, selectedBase]
  );
  const selectedOkxQuote = useMemo(
    () => firstBySymbol(quotes, "okx", `${selectedBase}-USDT`),
    [quotes, selectedBase]
  );
  const selectedUsdtTwdQuote = useMemo(
    () => firstBySymbol(quotes, "bitopro", "USDT-TWD"),
    [quotes]
  );
  const selectedSpreadRows = useMemo(
    () => spreads.filter((row) => row.base_asset === selectedBase),
    [spreads, selectedBase]
  );
  const selectedOrderBooks = useMemo(
    () =>
      orderBooks.filter((row) =>
        selectedBase === "USDT" ? row.symbol === "USDT-TWD" : row.symbol.startsWith(`${selectedBase}-`)
      ),
    [orderBooks, selectedBase]
  );
  const selectedQuotes = useMemo(
    () =>
      quotes.filter((row) =>
        selectedBase === "USDT"
          ? row.symbol === "USDT-TWD"
          : row.symbol === `${selectedBase}-TWD` || row.symbol === `${selectedBase}-USDT`
      ),
    [quotes, selectedBase]
  );
  const selectedDerivatives = useMemo(
    () => derivatives.filter((row) => row.symbol.startsWith(`${selectedBase}-`)),
    [derivatives, selectedBase]
  );
  const selectedMarketCaps = useMemo(
    () => marketCaps.filter((row) => row.symbol.toUpperCase() === selectedBase),
    [marketCaps, selectedBase]
  );
  const selectedTrendHistory = useMemo(() => ({
    quote: trendHistory.quote.filter((row) =>
      selectedBase === "USDT" ? row.symbol === "USDT-TWD" : row.symbol === `${selectedBase}-USDT`
    ),
    liquidity: trendHistory.liquidity.filter((row) =>
      selectedBase === "USDT"
        ? row.symbol === "USDT-TWD"
        : row.symbol === `${selectedBase}-USDT` || row.symbol === `${selectedBase}-TWD`
    ),
    derivatives: trendHistory.derivatives.filter((row) => row.symbol === `${selectedBase}-USDT`),
    spreads: trendHistory.spreads.filter((row) => row.base_asset === selectedBase),
    longShortRatios: trendHistory.longShortRatios.filter((row) => row.symbol === `${selectedBase}-USDT`),
  }), [selectedBase, trendHistory]);
  const selectedLiquidityHeatmap = useMemo(
    () => buildLiquidityHeatmap(selectedTrendHistory.liquidity),
    [selectedTrendHistory.liquidity]
  );
  const selectedLiquidationHeatmapRows = useMemo(
    () => liquidationHeatmapRows.filter((row) => row.symbol === `${selectedBase}-USDT`),
    [liquidationHeatmapRows, selectedBase]
  );
  const selectedLiquidationHeatmap = useMemo(
    () => buildLiquidationHeatmap(selectedLiquidationHeatmapRows),
    [selectedLiquidationHeatmapRows]
  );
  const selectedTrendSeries = useMemo(() => {
    return {
      volume: buildTrendSeries(selectedTrendHistory.quote, {
        getKey: (row) => `${row.provider}:${row.symbol}`,
        getLabel: (row) => `${compactProvider(row.provider)} ${row.symbol}`,
        getTime: (row) => row.sampled_at,
        getValue: (row) => row.quote_volume_24h,
        colors: [omiChartColors.neutralLine, omiChartColors.sky],
      }),
      funding: buildTrendSeries(selectedTrendHistory.derivatives, {
        getKey: (row) => `${row.provider}:${row.symbol}`,
        getLabel: (row) => compactProvider(row.provider),
        getTime: (row) => row.sampled_at,
        getValue: (row) => {
          const value = finiteNumber(row.funding_rate);
          return value === null ? null : value * 100;
        },
        colors: [omiChartColors.warning, omiChartColors.purple],
      }),
      openInterest: buildTrendSeries(selectedTrendHistory.derivatives, {
        getKey: (row) => `${row.provider}:${row.symbol}`,
        getLabel: (row) => compactProvider(row.provider),
        getTime: (row) => row.sampled_at,
        getValue: (row) => row.open_interest,
        colors: [omiChartColors.info, omiChartColors.teal],
      }),
      taiwanSpread: buildTrendSeries(selectedTrendHistory.spreads, {
        getKey: (row) => row.global_provider,
        getLabel: (row) => compactProvider(row.global_provider),
        getTime: (row) => row.sampled_at,
        getValue: (row) => row.spread_pct,
        colors: [omiChartColors.marketUp, omiChartColors.marketDown],
      }),
      liquiditySpread: buildTrendSeries(selectedTrendHistory.liquidity, {
        getKey: (row) => `${row.provider}:${row.symbol}`,
        getLabel: (row) => `${compactProvider(row.provider)} ${row.symbol}`,
        getTime: (row) => row.sampled_at,
        getValue: (row) => row.spread_pct,
        colors: [omiChartColors.cyan, omiChartColors.pink, omiChartColors.lime],
      }),
      liquidityDepth: buildTrendSeries(selectedTrendHistory.liquidity, {
        getKey: (row) => `${row.provider}:${row.symbol}`,
        getLabel: (row) => `${compactProvider(row.provider)} ${row.symbol}`,
        getTime: (row) => row.sampled_at,
        getValue: (row) => sumFiniteValues(row.best_bid_size, row.best_ask_size),
        colors: [omiChartColors.green, omiChartColors.heat, omiChartColors.indigo],
      }),
      longShortRatio: buildTrendSeries(selectedTrendHistory.longShortRatios, {
        getKey: (row) => `${row.provider}:${row.symbol}:${row.ratio_scope}`,
        getLabel: (row) => `${compactProvider(row.provider)} ${row.ratio_scope}`,
        getTime: (row) => row.sampled_at,
        getValue: (row) => row.long_short_ratio,
        colors: [omiChartColors.lime, omiChartColors.purple],
      }),
    };
  }, [selectedTrendHistory]);
  const selectedSubscription = useMemo(
    () => cryptoSubscriptionItem(subscriptionSettings, selectedBase),
    [selectedBase, subscriptionSettings]
  );
  useEffect(() => {
    if (!subscriptionSettings || selectedSubscription?.mode !== "on_select") return;

    const refreshKey = [
      selectedBase,
      selectedSubscription.mode,
      subscriptionSettings.source,
      subscriptionSettings.version,
    ].join(":");
    if (onSelectRefreshKeyRef.current === refreshKey) return;

    onSelectRefreshKeyRef.current = refreshKey;
    void refreshCoreData({ emitStatus: false });
  }, [
    refreshCoreData,
    selectedBase,
    selectedSubscription?.mode,
    subscriptionSettings,
  ]);
  const healthEntries = useMemo(
    () => sourceHealth?.entries ?? [],
    [sourceHealth]
  );
  const visibleHealthEntries = useMemo(
    () => healthDisplayEntries(healthEntries).slice(0, 12),
    [healthEntries]
  );
  const healthIssueCount = healthEntries.filter((entry) => !entry.ok).length;
  const visibleRealtimeRows = realtimeLatest
    .filter((row) => row.symbol.startsWith(`${selectedBase}-`))
    .slice(0, 8);
  const dataViewTabs: Array<{
    key: CryptoDataView;
    label: string;
    detail: string;
    badge?: string | null;
  }> = [
    {
      key: "overview",
      label: t("crypto.market.views.overview"),
      detail: t("crypto.market.views.overviewHint"),
    },
    {
      key: "risk",
      label: t("crypto.market.views.risk"),
      detail: t("crypto.market.views.riskHint"),
      badge: selectedLiquidationHeatmapRows.length
        ? String(selectedLiquidationHeatmapRows.length)
        : null,
    },
    {
      key: "signals",
      label: t("crypto.market.views.signals"),
      detail: t("crypto.market.views.signalsHint"),
    },
    {
      key: "raw",
      label: t("crypto.market.views.raw"),
      detail: t("crypto.market.views.rawHint"),
    },
    {
      key: "health",
      label: t("crypto.market.views.health"),
      detail: t("crypto.market.views.healthHint"),
      badge: healthIssueCount ? String(healthIssueCount) : null,
    },
  ];
  const activeDataViewDetail =
    dataViewTabs.find((tab) => tab.key === activeDataView)?.detail ?? "";

  return (
    <section className="space-y-4">
      {!chartProfessionalMode ? (
        <header className="border border-omi-border-subtle bg-omi-surface px-5 py-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("crypto.market.eyebrow")}
              </div>
              <h1 className="mt-1 text-2xl font-bold text-omi-text-strong">
                {t("crypto.market.title")}
              </h1>
            </div>
          </div>

          <div className="mt-3 text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("crypto.market.selectedAsset", { asset: selectedBase })} /{" "}
            {t("crypto.market.subscription", {
              mode: subscriptionModeLabel(selectedSubscription, t),
            })}
          </div>
        </header>
      ) : null}

      <div
        className={
          chartProfessionalMode
            ? "grid gap-4"
            : "grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]"
        }
      >
        <div className="min-w-0">
          <CryptoKLinePanel
            selectedBase={selectedBase}
            selectedInstrumentKey={selectedInstrumentKey}
            subscriptionSettings={subscriptionSettings}
            klineInstruments={cryptoKlineInstruments}
            professionalMode={chartProfessionalMode}
            onProfessionalModeChange={setChartProfessionalMode}
            refreshRevision={klineRefreshRevision}
          />
        </div>

        {!chartProfessionalMode ? (
        <aside className="min-w-0 space-y-4">
          <section className="border border-omi-border-subtle bg-omi-surface">
            <div className="grid grid-cols-5 border-b border-omi-border-subtle">
              {dataViewTabs.map((tab) => {
                const active = tab.key === activeDataView;
                return (
                  <button
                    key={tab.key}
                    type="button"
                    className={[
                      "omi-data-tab flex min-h-12 min-w-0 items-center justify-center gap-2 border-r border-omi-border-subtle px-2 py-2 text-sm font-semibold transition last:border-r-0",
                      active
                        ? "omi-data-tab-active bg-omi-surface-subtle text-omi-text-strong"
                        : "text-omi-text-muted hover:bg-omi-surface-subtle hover:text-omi-text",
                    ].join(" ")}
                    onClick={() => setActiveDataView(tab.key)}
                  >
                    <span className="truncate">{tab.label}</span>
                    {tab.badge ? (
                      <span className="shrink-0 border border-omi-warning/40 px-1.5 py-0.5 text-[10px] tabular-nums text-omi-warning">
                        {tab.badge}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
            <div className="px-4 py-2 text-xs text-omi-text-muted">
              {activeDataViewDetail}
            </div>
          </section>

          {activeDataView === "overview" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.marketData")}
              subtitle={`${selectedBase} / ${subscriptionSourceLabel(subscriptionSettings, t)}`}
            />
            <div className="grid border-b border-omi-border-subtle sm:grid-cols-2">
              <DataMetric
                label={selectedBase === "USDT" ? t("crypto.market.usdtReference") : `${selectedBase}/USDT Binance`}
                value={selectedBase === "USDT" ? "1.00" : formatNumber(selectedGlobalQuote?.last_price)}
              />
              <DataMetric
                label={selectedBase === "USDT" ? "USDT/TWD BitoPro" : `${selectedBase}/USDT OKX`}
                value={
                  selectedBase === "USDT"
                    ? formatNumber(selectedUsdtTwdQuote?.last_price)
                    : formatNumber(selectedOkxQuote?.last_price)
                }
              />
              <DataMetric
                label={t("crypto.market.taiwanSpreadMetric")}
                value={
                  selectedSpreadRows[0]
                    ? `${formatNumber(selectedSpreadRows[0].spread)} TWD`
                    : "-"
                }
                detail={selectedSpreadRows[0] ? formatPct(selectedSpreadRows[0].spread_pct) : null}
              />
              <DataMetric
                label={t("crypto.market.realtimeRows")}
                value={String(realtimeStatus?.latest_count ?? 0)}
                detail={
                  realtimeStatus?.last_error ??
                  t("crypto.market.taskStatus", {
                    active: realtimeStatus?.active_task_count ?? 0,
                    total: realtimeStatus?.task_count ?? 0,
                    state: autoRefreshStatus?.running
                      ? t("crypto.market.autoStates.running")
                      : t("crypto.market.autoStates.stopped"),
                    plans: autoRefreshStatus?.active_plan_count ?? 0,
                  })
                }
              />
            </div>
            <div className="px-4 py-3 text-xs text-omi-text-muted">
              {t("crypto.market.subscriptionLabel")}: {subscriptionModeLabel(selectedSubscription, t)}
              {realtimeStatus?.subscription_policy
                ? ` / ${t("crypto.market.realtimePolicy", {
                    policy: realtimeStatus.subscription_policy,
                  })}`
                : ""}
              {autoRefreshStatus?.subscription_policy
                ? ` / ${t("crypto.market.autoPolicy", {
                    state: autoRefreshStatus.running
                      ? t("crypto.market.autoStates.running")
                      : t("crypto.market.autoStates.stopped"),
                    count: autoRefreshStatus.active_resource_count,
                    plans: autoRefreshStatus.active_plan_count ?? autoRefreshStatus.active_resource_count,
                  })}`
                : ""}
            </div>
          </section>
          ) : null}

          {activeDataView === "risk" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.riskMap")}
              subtitle={t("crypto.market.riskMapSubtitle", { asset: selectedBase })}
            />
            <div className="grid gap-3 p-3 2xl:grid-cols-[minmax(0,3fr)_minmax(280px,2fr)]">
              <LiquidityHeatmapCard
                title={t("crypto.market.liquidityHeatmap")}
                subtitle={t("crypto.market.liquidityHeatmapSubtitle")}
                heatmap={selectedLiquidityHeatmap}
                emptyLabel={t("crypto.market.noHeatmapData")}
                bidLabel={t("crypto.market.bidLiquidity")}
                askLabel={t("crypto.market.askLiquidity")}
                locale={locale}
              />
              <LiquidationHeatmapCard
                title={t("crypto.market.liquidationHeatmap")}
                subtitle={t("crypto.market.liquidationHeatmapSubtitle")}
                heatmap={selectedLiquidationHeatmap}
                emptyLabel={t("crypto.market.noLiquidationHeatmapData")}
                emptyBody={t("crypto.market.liquidationHeatmapPending")}
                tags={[
                  "CoinGlass",
                  "Binance forceOrder",
                  selectedLiquidationHeatmap
                    ? t("crypto.market.status.live")
                    : t("crypto.market.status.pending"),
                ]}
                longLabel={t("crypto.market.longLiquidations")}
                shortLabel={t("crypto.market.shortLiquidations")}
                allLabel={t("crypto.market.allLiquidations")}
                locale={locale}
              />
            </div>
          </section>
          ) : null}

          {activeDataView === "signals" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.confirmationSignals")}
              subtitle={t("crypto.market.confirmationSignalsSubtitle")}
            />
            <div className="grid gap-3 p-3 2xl:grid-cols-2">
              <TrendChartCard
                title={t("crypto.market.trendFunding")}
                subtitle={t("crypto.market.trendFundingSubtitle")}
                series={selectedTrendSeries.funding}
                emptyLabel={t("crypto.market.noTrendData")}
                yFormatter={(value) => formatPct(value, 4)}
                locale={locale}
              />
              <TrendChartCard
                title={t("crypto.market.trendOpenInterest")}
                subtitle={t("crypto.market.trendOpenInterestSubtitle")}
                series={selectedTrendSeries.openInterest}
                emptyLabel={t("crypto.market.noTrendData")}
                yFormatter={(value) => formatCompactNumber(value, 2)}
                locale={locale}
              />
              <TrendChartCard
                title={t("crypto.market.longShortRatio")}
                subtitle={t("crypto.market.longShortRatioSubtitle")}
                series={selectedTrendSeries.longShortRatio}
                emptyLabel={t("crypto.market.longShortRatioPending")}
                yFormatter={(value) => formatNumber(value, 3)}
                locale={locale}
              />
            </div>
          </section>
          ) : null}

          {activeDataView === "risk" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.microstructure")}
              subtitle={t("crypto.market.microstructureSubtitle")}
            />
            <div className="grid gap-3 p-3 2xl:grid-cols-2">
              <TrendChartCard
                title={t("crypto.market.trendVolume")}
                subtitle={t("crypto.market.trendQuoteVolume")}
                series={selectedTrendSeries.volume}
                emptyLabel={t("crypto.market.noTrendData")}
                yFormatter={(value) => formatCompactNumber(value, 2)}
                locale={locale}
              />
              <TrendChartCard
                title={t("crypto.market.trendTaiwanSpread")}
                subtitle={t("crypto.market.trendTaiwanSpreadSubtitle")}
                series={selectedTrendSeries.taiwanSpread}
                emptyLabel={t("crypto.market.noTrendData")}
                yFormatter={(value) => formatPct(value, 4)}
                locale={locale}
              />
              <TrendChartCard
                title={t("crypto.market.trendLiquiditySpread")}
                subtitle={t("crypto.market.trendLiquiditySpreadSubtitle")}
                series={selectedTrendSeries.liquiditySpread}
                emptyLabel={t("crypto.market.noTrendData")}
                yFormatter={(value) => formatPct(value, 4)}
                locale={locale}
              />
              <TrendChartCard
                title={t("crypto.market.trendLiquidityDepth")}
                subtitle={t("crypto.market.trendLiquidityDepthSubtitle")}
                series={selectedTrendSeries.liquidityDepth}
                emptyLabel={t("crypto.market.noTrendData")}
                yFormatter={(value) => formatCompactNumber(value, 4)}
                locale={locale}
              />
            </div>
          </section>
          ) : null}

          {activeDataView === "health" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.sourceHealth")}
              subtitle={sourceHealth ? formatTime(sourceHealth.generated_at, locale) : "-"}
            />
            <div className="grid grid-cols-3 border-b border-omi-border-subtle text-center text-xs">
              <HealthStat label={t("crypto.market.status.ok")} value={sourceHealth?.summary.ok_count ?? 0} />
              <HealthStat label={t("crypto.market.status.stale")} value={sourceHealth?.summary.stale_count ?? 0} />
              <HealthStat label={t("crypto.market.healthIssues")} value={healthIssueCount} />
            </div>
            <div className="max-h-[280px] overflow-y-auto">
              {visibleHealthEntries.length ? (
                visibleHealthEntries.map((entry, index) => {
                  const maturity = contractResourceStatus(providerContract, entry);
                  const category = healthEntryCategory(entry, maturity, t);

                  return (
                    <div
                      key={`${entry.resource}-${entry.provider}-${entry.target}-${entry.status}-${index}`}
                      className="grid grid-cols-[minmax(0,1fr)_minmax(84px,auto)_64px] gap-2 border-b border-omi-border-subtle px-3 py-2 text-xs last:border-b-0"
                    >
                      <div className="min-w-0">
                        <div className="flex min-w-0 items-center gap-2">
                          <span className="shrink-0 border border-omi-border-subtle px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-omi-text-subtle">
                            {category}
                          </span>
                          <span className="truncate font-semibold text-omi-text">
                            {normalizedContractResource(entry.resource).replaceAll("_", " ")}
                          </span>
                        </div>
                        <div className="mt-1 truncate text-omi-text-muted">
                          {compactProvider(entry.provider)} {entry.target}
                        </div>
                        {entry.reason ? (
                          <div className="mt-1 max-h-8 overflow-hidden text-omi-text-subtle">{entry.reason}</div>
                        ) : null}
                      </div>
                      <div className={`self-start border px-2 py-1 text-center font-semibold ${statusClass(entry.status, entry.ok)}`}>
                        {healthStatusLabel(entry, maturity, t)}
                      </div>
                      <div className="self-start text-right tabular-nums text-omi-text-muted">{entry.row_count}</div>
                    </div>
                  );
                })
              ) : (
                <div className="px-3 py-4 text-center text-xs text-omi-text-muted">
                  {t("crypto.market.healthNoEntries")}
                </div>
              )}
            </div>
          </section>
          ) : null}

          {activeDataView === "raw" ? (
          <>
          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader title={t("crypto.market.quotes")} subtitle={t("crypto.market.quotesSubtitle")} />
            <DataTable
              emptyLabel={t("crypto.market.noData")}
              columns={[
                t("crypto.market.tables.provider"),
                t("crypto.market.tables.symbol"),
                t("crypto.market.tables.last"),
                t("crypto.market.tables.bid"),
                t("crypto.market.tables.ask"),
                t("crypto.market.tables.change24h"),
                t("crypto.market.tables.fetched"),
              ]}
              rows={selectedQuotes.map((row) => [
                compactProvider(row.provider),
                row.symbol,
                formatNumber(row.last_price),
                formatNumber(row.bid_price),
                formatNumber(row.ask_price),
                formatPct(row.price_change_pct_24h),
                formatTime(row.fetched_at, locale),
              ])}
            />
          </section>

          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.orderBook")}
              subtitle={t("crypto.market.orderBookSubtitle", { asset: selectedBase })}
            />
            <DataTable
              emptyLabel={t("crypto.market.noData")}
              columns={[
                t("crypto.market.tables.provider"),
                t("crypto.market.tables.symbol"),
                t("crypto.market.tables.bid"),
                t("crypto.market.tables.bidSize"),
                t("crypto.market.tables.ask"),
                t("crypto.market.tables.askSize"),
                t("crypto.market.tables.spread"),
              ]}
              rows={selectedOrderBooks.map((row) => [
                compactProvider(row.provider),
                row.symbol,
                formatNumber(row.best_bid_price),
                formatNumber(row.best_bid_size, 6),
                formatNumber(row.best_ask_price),
                formatNumber(row.best_ask_size, 6),
                formatPct(row.spread_pct, 4),
              ])}
            />
          </section>

          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.taiwanSpread")}
              subtitle={t("crypto.market.taiwanSpreadSubtitle")}
            />
            <DataTable
              emptyLabel={t("crypto.market.noData")}
              columns={[
                t("crypto.market.tables.base"),
                t("crypto.market.tables.global"),
                t("crypto.market.tables.local"),
                t("crypto.market.tables.implied"),
                t("crypto.market.tables.spread"),
                t("crypto.market.tables.spreadPct"),
                t("crypto.market.tables.time"),
              ]}
              rows={selectedSpreadRows.map((row) => [
                row.base_asset,
                compactProvider(row.global_provider),
                formatNumber(row.local_price),
                formatNumber(row.implied_twd_price),
                formatNumber(row.spread),
                formatPct(row.spread_pct, 4),
                formatTime(row.observed_at, locale),
              ])}
            />
          </section>

          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader title={t("crypto.market.perpetuals")} subtitle={t("crypto.market.perpetualsSubtitle")} />
            <DataTable
              emptyLabel={t("crypto.market.noData")}
              columns={[
                t("crypto.market.tables.provider"),
                t("crypto.market.tables.symbol"),
                t("crypto.market.tables.funding"),
                t("crypto.market.tables.mark"),
                t("crypto.market.tables.oi"),
                t("crypto.market.tables.next"),
              ]}
              rows={selectedDerivatives.map((row) => [
                compactProvider(row.provider),
                row.symbol,
                formatPct(row.funding_rate !== null && row.funding_rate !== undefined ? row.funding_rate * 100 : null, 4),
                formatNumber(row.mark_price),
                formatNumber(row.open_interest, 2),
                formatTime(row.next_funding_time, locale),
              ])}
            />
          </section>

          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader title={t("crypto.market.marketCap")} subtitle={t("crypto.market.marketCapSubtitle")} />
            <DataTable
              emptyLabel={t("crypto.market.noData")}
              columns={[
                t("crypto.market.tables.rank"),
                t("crypto.market.tables.asset"),
                t("crypto.market.tables.price"),
                t("crypto.market.tables.mcap"),
                t("crypto.market.tables.change24h"),
              ]}
              rows={selectedMarketCaps.map((row) => [
                String(row.market_cap_rank ?? "-"),
                row.symbol.toUpperCase(),
                formatNumber(row.current_price),
                formatNumber(row.market_cap, 0),
                formatPct(row.price_change_pct_24h),
              ])}
            />
          </section>
          </>
          ) : null}

          {activeDataView === "health" ? (
          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.realtimeLatest")}
              subtitle={realtimeStatus?.running
                ? t("crypto.market.collectorRunning")
                : t("crypto.market.collectorDisabled")}
            />
            <DataTable
              emptyLabel={t("crypto.market.noData")}
              columns={[
                t("crypto.market.tables.provider"),
                t("crypto.market.tables.resource"),
                t("crypto.market.tables.symbol"),
                t("crypto.market.tables.age"),
                t("crypto.market.tables.lag"),
                t("crypto.market.tables.state"),
              ]}
              rows={visibleRealtimeRows.map((row) => [
                compactProvider(row.provider),
                row.resource,
                row.symbol,
                formatAge(row.last_message_age_ms),
                formatAge(row.feed_lag_ms),
                row.stale ? t("crypto.market.status.stale") : t("crypto.market.status.live"),
              ])}
            />
          </section>
          ) : null}
        </aside>
        ) : null}
      </div>
    </section>
  );
}

function DataMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string | null;
}) {
  return (
    <div className="border-b border-r border-omi-border-subtle px-4 py-3 even:border-r-0 sm:[&:nth-last-child(-n+2)]:border-b-0">
      <div className="text-xs font-semibold uppercase text-omi-text-muted">{label}</div>
      <div className="mt-1 truncate text-xl font-bold tabular-nums text-omi-text-strong">{value}</div>
      {detail ? <div className="mt-1 truncate text-xs text-omi-text-muted">{detail}</div> : null}
    </div>
  );
}

function LiquidityHeatmapCard({
  title,
  subtitle,
  heatmap,
  emptyLabel,
  bidLabel,
  askLabel,
  locale,
}: {
  title: string;
  subtitle: string;
  heatmap: LiquidityHeatmap | null;
  emptyLabel: string;
  bidLabel: string;
  askLabel: string;
  locale: string;
}) {
  const width = 640;
  const height = 300;
  const left = 64;
  const right = 22;
  const top = 28;
  const bottom = 38;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;

  if (!heatmap || !heatmap.cells.length) {
    return (
      <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3">
        <div className="text-sm font-bold text-omi-text-strong">{title}</div>
        <div className="mt-0.5 text-xs text-omi-text-muted">{subtitle}</div>
        <StateSurface title={emptyLabel} tone="empty" compact className="mt-3 h-64" />
      </div>
    );
  }

  const priceRange = heatmap.maxPrice - heatmap.minPrice || Math.max(heatmap.maxPrice * 0.01, 1);
  const yMin = heatmap.minPrice - priceRange * 0.04;
  const yMax = heatmap.maxPrice + priceRange * 0.04;
  const yRange = yMax - yMin || 1;
  const timeRange = heatmap.maxTime - heatmap.minTime || 1;
  const uniqueTimes = new Set(heatmap.cells.map((cell) => cell.time)).size;
  const cellWidth = Math.max(2.2, Math.min(10, (plotWidth / Math.max(uniqueTimes, 1)) * 0.82));
  const cellHeight = Math.max(2.8, Math.min(12, plotHeight / 56));
  const xFor = (time: string) => left + ((Date.parse(time) - heatmap.minTime) / timeRange) * plotWidth;
  const yFor = (price: number) => top + ((yMax - price) / yRange) * plotHeight;
  const latestMidY = heatmap.latestMid === null ? null : yFor(heatmap.latestMid);

  return (
    <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-omi-text-strong">{title}</div>
          <div className="mt-0.5 truncate text-xs text-omi-text-muted">{subtitle}</div>
        </div>
        <div className="shrink-0 text-right text-[11px] tabular-nums text-omi-text-muted">
          <div>{heatmap.cells.length}</div>
          <div>{heatmap.latestMid === null ? "-" : formatNumber(heatmap.latestMid, 2)}</div>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-2 h-72 w-full" aria-label={title}>
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
          const y = top + tick * plotHeight;
          return (
            <line
              key={tick}
              x1={left}
              x2={left + plotWidth}
              y1={y}
              y2={y}
              stroke={omiChartColors.grid}
            />
          );
        })}
        {heatmap.cells.map((cell) => (
          <rect
            key={cell.key}
            x={xFor(cell.time) - cellWidth / 2}
            y={yFor(cell.price) - cellHeight / 2}
            width={cellWidth}
            height={cellHeight}
            fill={cell.side === "bid" ? omiChartColors.marketDown : omiChartColors.marketUp}
            opacity={0.12 + cell.intensity * 0.78}
          />
        ))}
        {latestMidY !== null ? (
          <line
            x1={left}
            x2={left + plotWidth}
            y1={latestMidY}
            y2={latestMidY}
            stroke={omiChartColors.crosshair}
            strokeDasharray="4 4"
          />
        ) : null}
        <text x={left - 8} y={top + 4} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatNumber(yMax, 2)}
        </text>
        <text x={left - 8} y={top + plotHeight} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatNumber(yMin, 2)}
        </text>
        <text x={left} y={height - 8} className="fill-omi-text-muted text-[10px]">
          {formatDateTimeShort(new Date(heatmap.minTime).toISOString(), locale)}
        </text>
        <text x={left + plotWidth} y={height - 8} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatDateTimeShort(new Date(heatmap.maxTime).toISOString(), locale)}
        </text>
      </svg>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-omi-text-muted">
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-4" style={{ backgroundColor: omiChartColors.marketDown }} />
          {bidLabel}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-4" style={{ backgroundColor: omiChartColors.marketUp }} />
          {askLabel}
        </span>
        <span>{formatNumber(yMin, 2)} - {formatNumber(yMax, 2)}</span>
      </div>
    </div>
  );
}

function liquidationColor(side: string) {
  const normalizedSide = side.toLowerCase();
  if (normalizedSide === "long") return omiChartColors.marketDown;
  if (normalizedSide === "short") return omiChartColors.marketUp;
  if (normalizedSide === "all") return omiChartColors.warning;
  return omiChartColors.info;
}

function LiquidationHeatmapCard({
  title,
  subtitle,
  heatmap,
  emptyLabel,
  emptyBody,
  tags,
  longLabel,
  shortLabel,
  allLabel,
  locale,
}: {
  title: string;
  subtitle: string;
  heatmap: LiquidationHeatmap | null;
  emptyLabel: string;
  emptyBody: string;
  tags: string[];
  longLabel: string;
  shortLabel: string;
  allLabel: string;
  locale: string;
}) {
  const width = 640;
  const height = 300;
  const left = 64;
  const right = 22;
  const top = 28;
  const bottom = 38;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;

  if (!heatmap || !heatmap.cells.length) {
    return (
      <div className="border border-dashed border-omi-border bg-omi-surface-subtle px-3 py-3">
        <div className="text-sm font-bold text-omi-text-strong">{title}</div>
        <div className="mt-0.5 text-xs text-omi-text-muted">{subtitle}</div>
        <StateSurface
          title={emptyLabel}
          description={emptyBody}
          tone="empty"
          compact
          className="mt-3 h-48"
        />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <span key={tag} className="border border-omi-border-subtle px-2 py-1 text-[11px] font-semibold text-omi-text-muted">
              {tag}
            </span>
          ))}
        </div>
      </div>
    );
  }

  const priceRange = heatmap.maxPrice - heatmap.minPrice || Math.max(heatmap.maxPrice * 0.01, 1);
  const yMin = heatmap.minPrice - priceRange * 0.04;
  const yMax = heatmap.maxPrice + priceRange * 0.04;
  const yRange = yMax - yMin || 1;
  const timeRange = heatmap.maxTime - heatmap.minTime || 1;
  const uniqueTimes = new Set(heatmap.cells.map((cell) => cell.time)).size;
  const cellWidth = Math.max(3, Math.min(12, (plotWidth / Math.max(uniqueTimes, 1)) * 0.82));
  const cellHeight = Math.max(4, Math.min(14, plotHeight / 48));
  const xFor = (time: string) => left + ((Date.parse(time) - heatmap.minTime) / timeRange) * plotWidth;
  const yFor = (price: number) => top + ((yMax - price) / yRange) * plotHeight;

  return (
    <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-omi-text-strong">{title}</div>
          <div className="mt-0.5 truncate text-xs text-omi-text-muted">{subtitle}</div>
        </div>
        <div className="shrink-0 text-right text-[11px] tabular-nums text-omi-text-muted">
          <div>{formatCompactNumber(heatmap.totalNotional, 2)}</div>
          <div>{heatmap.totalEvents}</div>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-2 h-72 w-full" aria-label={title}>
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
          const y = top + tick * plotHeight;
          return (
            <line
              key={tick}
              x1={left}
              x2={left + plotWidth}
              y1={y}
              y2={y}
              stroke={omiChartColors.grid}
            />
          );
        })}
        {heatmap.cells.map((cell) => (
          <rect
            key={cell.key}
            x={xFor(cell.time) - cellWidth / 2}
            y={yFor(cell.price) - cellHeight / 2}
            width={cellWidth}
            height={cellHeight}
            fill={liquidationColor(cell.side)}
            opacity={0.14 + cell.intensity * 0.76}
          />
        ))}
        <text x={left - 8} y={top + 4} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatNumber(yMax, 2)}
        </text>
        <text x={left - 8} y={top + plotHeight} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatNumber(yMin, 2)}
        </text>
        <text x={left} y={height - 8} className="fill-omi-text-muted text-[10px]">
          {formatDateTimeShort(new Date(heatmap.minTime).toISOString(), locale)}
        </text>
        <text x={left + plotWidth} y={height - 8} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatDateTimeShort(new Date(heatmap.maxTime).toISOString(), locale)}
        </text>
      </svg>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-omi-text-muted">
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-4" style={{ backgroundColor: omiChartColors.marketDown }} />
          {longLabel}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-4" style={{ backgroundColor: omiChartColors.marketUp }} />
          {shortLabel}
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-4" style={{ backgroundColor: omiChartColors.warning }} />
          {allLabel}
        </span>
        <span>{heatmap.providers.map(compactProvider).join(" / ")}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {tags.map((tag) => (
          <span key={tag} className="border border-omi-border-subtle px-2 py-1 text-[11px] font-semibold text-omi-text-muted">
            {tag}
          </span>
        ))}
      </div>
    </div>
  );
}

function TrendChartCard({
  title,
  subtitle,
  series,
  emptyLabel,
  yFormatter,
  locale,
}: {
  title: string;
  subtitle: string;
  series: TrendSeries[];
  emptyLabel: string;
  yFormatter: (value: number) => string;
  locale: string;
}) {
  const width = 420;
  const height = 160;
  const left = 48;
  const right = 14;
  const top = 18;
  const bottom = 28;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const validSeries = series
    .map((item) => ({
      ...item,
      points: item.points.filter((point) => Number.isFinite(Date.parse(point.time))),
    }))
    .filter((item) => item.points.length >= 2);
  const allPoints = validSeries.flatMap((item) => item.points);
  const pointCount = allPoints.length;

  if (pointCount < 2) {
    return (
      <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-bold text-omi-text-strong">{title}</div>
            <div className="mt-0.5 truncate text-xs text-omi-text-muted">{subtitle}</div>
          </div>
        </div>
        <StateSurface title={emptyLabel} tone="empty" compact className="mt-3 h-32" />
      </div>
    );
  }

  const values = allPoints.map((point) => point.value);
  const times = allPoints.map((point) => Date.parse(point.time));
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const rawRange = maxValue - minValue;
  const padding = rawRange === 0 ? Math.max(Math.abs(maxValue) * 0.08, 1) : rawRange * 0.1;
  const yMin = minValue - padding;
  const yMax = maxValue + padding;
  const yRange = yMax - yMin || 1;
  const timeRange = maxTime - minTime || 1;
  const xFor = (time: string) => left + ((Date.parse(time) - minTime) / timeRange) * plotWidth;
  const yFor = (value: number) => top + ((yMax - value) / yRange) * plotHeight;
  const zeroY = yMin < 0 && yMax > 0 ? yFor(0) : null;
  const latestPoint = allPoints
    .slice()
    .sort((a, b) => Date.parse(b.time) - Date.parse(a.time))[0];

  return (
    <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-bold text-omi-text-strong">{title}</div>
          <div className="mt-0.5 truncate text-xs text-omi-text-muted">{subtitle}</div>
        </div>
        <div className="shrink-0 text-right text-[11px] tabular-nums text-omi-text-muted">
          <div>{pointCount}</div>
          <div>{latestPoint ? yFormatter(latestPoint.value) : "-"}</div>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-2 h-40 w-full" aria-label={title}>
        {[0, 0.5, 1].map((tick) => {
          const y = top + tick * plotHeight;
          return (
            <line
              key={tick}
              x1={left}
              x2={left + plotWidth}
              y1={y}
              y2={y}
              stroke={omiChartColors.grid}
            />
          );
        })}
        {zeroY !== null ? (
          <line
            x1={left}
            x2={left + plotWidth}
            y1={zeroY}
            y2={zeroY}
            stroke={omiChartColors.crosshair}
            strokeDasharray="4 4"
          />
        ) : null}
        <text x={left - 6} y={top + 4} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {yFormatter(yMax)}
        </text>
        <text x={left - 6} y={top + plotHeight} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {yFormatter(yMin)}
        </text>
        {validSeries.map((item) => {
          const path = item.points
            .map((point, index) => {
              const x = xFor(point.time);
              const y = yFor(point.value);
              return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
            })
            .join(" ");
          const lastPoint = item.points[item.points.length - 1];

          return (
            <g key={item.key}>
              <path
                d={path}
                fill="none"
                stroke={item.color}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {lastPoint ? (
                <circle
                  cx={xFor(lastPoint.time)}
                  cy={yFor(lastPoint.value)}
                  r="3"
                  fill={omiChartColors.surface}
                  stroke={item.color}
                  strokeWidth="2"
                />
              ) : null}
            </g>
          );
        })}
        <text x={left} y={height - 6} className="fill-omi-text-muted text-[10px]">
          {formatDateTimeShort(new Date(minTime).toISOString(), locale)}
        </text>
        <text x={left + plotWidth} y={height - 6} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatDateTimeShort(new Date(maxTime).toISOString(), locale)}
        </text>
      </svg>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-omi-text-muted">
        {validSeries.map((item) => (
          <span key={item.key} className="inline-flex min-w-0 items-center gap-1">
            <span className="h-2 w-4 shrink-0" style={{ backgroundColor: item.color }} />
            <span className="truncate">{item.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function PanelHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 border-b border-omi-border-subtle px-4 py-3">
      <h2 className="shrink-0 text-sm font-bold text-omi-text-strong">{title}</h2>
      <span className="min-w-0 truncate text-right text-xs text-omi-text-muted">{subtitle}</span>
    </div>
  );
}

function HealthStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="border-r border-omi-border-subtle px-3 py-2 last:border-r-0">
      <div className="text-[11px] uppercase text-omi-text-muted">{label}</div>
      <div className="text-lg font-bold tabular-nums text-omi-text-strong">{value}</div>
    </div>
  );
}

function DataTable({
  columns,
  rows,
  emptyLabel,
}: {
  columns: string[];
  rows: string[][];
  emptyLabel: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-xs">
        <thead className="border-b border-omi-border-subtle text-omi-text-muted">
          <tr>
            {columns.map((column) => (
              <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="px-3 py-4" colSpan={columns.length}>
                <StateSurface
                  title={emptyLabel}
                  tone="empty"
                  compact
                  className="mx-auto max-w-sm"
                />
              </td>
            </tr>
          ) : (
            rows.map((row, rowIndex) => (
              <tr key={rowIndex} className="border-b border-omi-border-subtle last:border-b-0">
                {row.map((cell, cellIndex) => (
                  <td
                    key={`${rowIndex}-${cellIndex}`}
                    className="whitespace-nowrap px-3 py-2 tabular-nums text-omi-text"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

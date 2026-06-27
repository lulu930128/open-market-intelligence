"use client";

import { fetchJson, requestJson } from "@/lib/api";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import {
  cryptoSubscriptionItem,
  cryptoSubscriptionResourceEnabled,
  loadMarketDataSubscriptionSettings,
  type MarketDataSubscriptionItem,
  type MarketDataSubscriptionSettingsRead,
} from "@/lib/marketDataSubscriptions";
import { useI18n, type TranslationFunction } from "@/i18n";
import {
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

type LoadState = "idle" | "loading" | "success" | "error";

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
  fetched_at: string;
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
};

const FALLBACK_MARKET_DATA_SUBSCRIPTION_SETTINGS: MarketDataSubscriptionSettingsRead = {
  kind: "market_data_subscription_settings",
  version: "frontend_fallback.v1",
  source: "frontend_fallback",
  items: [
    {
      key: "crypto:BTC",
      market: "crypto",
      group: "crypto",
      label: "BTC",
      mode: "always_on",
      resources: {
        quote: true,
        order_book: true,
        ohlcv: true,
        derivatives: true,
        taiwan_spread: true,
        market_cap: true,
      },
      intervals: {
        quote_seconds: 5,
        order_book_seconds: 5,
        ohlcv_seconds: 30,
        derivatives_seconds: 120,
        market_cap_seconds: 900,
      },
      note: "Frontend fallback used only when the settings API is unavailable.",
    },
    {
      key: "crypto:ETH",
      market: "crypto",
      group: "crypto",
      label: "ETH",
      mode: "on_select",
      resources: {
        quote: true,
        order_book: true,
        ohlcv: true,
        derivatives: true,
        taiwan_spread: true,
        market_cap: true,
      },
      intervals: {
        quote_seconds: 15,
        order_book_seconds: 30,
        ohlcv_seconds: 60,
        derivatives_seconds: 300,
        market_cap_seconds: 900,
      },
      note: "Frontend fallback used only when the settings API is unavailable.",
    },
    {
      key: "crypto:USDT",
      market: "crypto",
      group: "crypto",
      label: "USDT",
      mode: "on_select",
      resources: {
        quote: true,
        order_book: true,
        ohlcv: true,
        twd_reference: true,
        market_cap: true,
      },
      intervals: {
        quote_seconds: 15,
        order_book_seconds: 30,
        ohlcv_seconds: 120,
        market_cap_seconds: 900,
      },
      note: "Frontend fallback used only when the settings API is unavailable.",
    },
  ],
};

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("en-US", {
    maximumFractionDigits: digits,
  });
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
  return provider;
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

function firstBySymbol(rows: CryptoTicker[], provider: string, symbol: string) {
  return rows.find((row) => row.provider === provider && row.symbol === symbol) ?? null;
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
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [refreshing, setRefreshing] = useState(false);
  const [quotes, setQuotes] = useState<CryptoTicker[]>([]);
  const [orderBooks, setOrderBooks] = useState<CryptoOrderBook[]>([]);
  const [derivatives, setDerivatives] = useState<CryptoDerivatives[]>([]);
  const [marketCaps, setMarketCaps] = useState<CryptoMarketCap[]>([]);
  const [spreads, setSpreads] = useState<CryptoSpread[]>([]);
  const [realtimeStatus, setRealtimeStatus] = useState<CryptoRealtimeStatus | null>(null);
  const [realtimeLatest, setRealtimeLatest] = useState<CryptoRealtimeLatest[]>([]);
  const [autoRefreshStatus, setAutoRefreshStatus] = useState<CryptoAutoRefreshStatus | null>(null);
  const [sourceHealth, setSourceHealth] = useState<CryptoSourceHealth | null>(null);
  const [providerAssets, setProviderAssets] = useState<CryptoAssetDefinition[] | null>(null);
  const [subscriptionSettings, setSubscriptionSettings] =
    useState<MarketDataSubscriptionSettingsRead | null>(null);
  const [chartProfessionalMode, setChartProfessionalMode] = useState(false);
  const onSelectRefreshKeyRef = useRef<string | null>(null);
  const lastAutoRefreshIssueRef = useRef<string | null>(null);
  const cryptoBaseOptions = useMemo(
    () => cryptoBaseOptionsFromAssets(providerAssets),
    [providerAssets]
  );
  const cryptoKlineInstruments = useMemo(
    () => buildCryptoKlineInstruments(cryptoBaseOptions, providerAssets),
    [cryptoBaseOptions, providerAssets]
  );

  const loadRealtime = useCallback(async () => {
    const [status, latest, autoStatus] = await Promise.all([
      fetchJson<CryptoRealtimeStatus>("/api/crypto-market/realtime/status"),
      fetchJson<CryptoRealtimeLatest[]>("/api/crypto-market/realtime/latest"),
      fetchJson<CryptoAutoRefreshStatus>("/api/crypto-market/auto-refresh/status").catch(() => null),
    ]);

    setRealtimeStatus(status);
    setRealtimeLatest(latest);
    setAutoRefreshStatus(autoStatus);
  }, []);

  const loadData = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setLoadState("loading");
    }

    try {
      const [
        nextQuotes,
        nextOrderBooks,
        nextDerivatives,
        nextMarketCaps,
        nextSpreads,
        nextSourceHealth,
        nextProviderContract,
        nextSubscriptionSettings,
      ] = await Promise.all([
        fetchJson<CryptoTicker[]>("/api/crypto-market/quotes/latest", { limit: 50 }),
        fetchJson<CryptoOrderBook[]>("/api/crypto-market/order-books/latest", { limit: 50 }),
        fetchJson<CryptoDerivatives[]>("/api/crypto-market/derivatives/latest", { limit: 50 }),
        fetchJson<CryptoMarketCap[]>("/api/crypto-market/market-caps/latest", { limit: 20 }),
        fetchJson<CryptoSpread[]>("/api/crypto-market/spreads", { limit: 20 }),
        fetchJson<CryptoSourceHealth>("/api/crypto-market/source-health"),
        fetchJson<CryptoProviderContract>("/api/crypto-market/provider-contract").catch(() => null),
        loadMarketDataSubscriptionSettingsForPanel(),
        loadRealtime(),
      ]);

      setQuotes(nextQuotes);
      setOrderBooks(nextOrderBooks);
      setDerivatives(nextDerivatives);
      setMarketCaps(nextMarketCaps);
      setSpreads(nextSpreads);
      setSourceHealth(nextSourceHealth);
      if (nextProviderContract) {
        setProviderAssets(nextProviderContract.assets ?? null);
      }
      setSubscriptionSettings(nextSubscriptionSettings);
      setLoadState("success");
    } catch (error) {
      if (!silent) {
        emitDataStatusEvent({
          market: "crypto",
          level: "error",
          title: t("crypto.market.loadFailed"),
          message: error instanceof Error ? error.message : "Failed to load crypto data",
          source: t("crypto.market.eyebrow"),
        });
        setLoadState("error");
      }
    }
  }, [loadRealtime, t]);

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
    }, 10000);

    return () => window.clearInterval(interval);
  }, [loadData]);

  const refreshCoreData = useCallback(async (options?: { emitStatus?: boolean }) => {
    setRefreshing(true);

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
            "/api/crypto-market/ohlcv/refresh",
            { method: "POST" },
            {
              providers: batch.providers,
              symbols: batch.symbols.join(","),
              interval: "1m",
              limit: 10,
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
    } catch (error) {
      emitDataStatusEvent({
        market: "crypto",
        level: "error",
        title: t("crypto.market.refreshFailed"),
        message: error instanceof Error ? error.message : "Failed to refresh crypto data",
        source: t("crypto.market.eyebrow"),
      });
    } finally {
      setRefreshing(false);
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
  const healthEntries = sourceHealth?.entries ?? [];
  const visibleRealtimeRows = realtimeLatest
    .filter((row) => row.symbol.startsWith(`${selectedBase}-`))
    .slice(0, 8);

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
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text-muted transition hover:border-omi-accent hover:text-omi-accent disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => void loadData()}
                disabled={loadState === "loading" || refreshing}
              >
                {loadState === "loading" ? t("crypto.market.loading") : t("crypto.market.reload")}
              </button>
              <button
                type="button"
                className="h-9 border border-omi-accent-border bg-omi-accent-soft px-3 text-sm font-semibold text-omi-accent transition hover:border-omi-accent hover:bg-omi-surface-subtle disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => void refreshCoreData()}
                disabled={refreshing || !subscriptionSettings}
              >
                {refreshing ? t("crypto.market.refreshing") : t("crypto.market.refreshCoreData")}
              </button>
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
          />
        </div>

        {!chartProfessionalMode ? (
        <aside className="min-w-0 space-y-4">
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

          <section className="border border-omi-border-subtle bg-omi-surface">
            <PanelHeader
              title={t("crypto.market.sourceHealth")}
              subtitle={sourceHealth ? formatTime(sourceHealth.generated_at, locale) : "-"}
            />
            <div className="grid grid-cols-3 border-b border-omi-border-subtle text-center text-xs">
              <HealthStat label={t("crypto.market.status.ok")} value={sourceHealth?.summary.ok_count ?? 0} />
              <HealthStat label={t("crypto.market.status.stale")} value={sourceHealth?.summary.stale_count ?? 0} />
              <HealthStat label={t("crypto.market.status.disabled")} value={sourceHealth?.summary.disabled_count ?? 0} />
            </div>
            <div className="max-h-[280px] overflow-y-auto">
              {healthEntries.slice(0, 12).map((entry) => (
                <div
                  key={`${entry.resource}-${entry.provider}-${entry.target}`}
                  className="grid grid-cols-[minmax(110px,1fr)_80px_72px] gap-2 border-b border-omi-border-subtle px-3 py-2 text-xs last:border-b-0"
                >
                  <div className="min-w-0">
                    <div className="truncate font-semibold text-omi-text">{entry.resource}</div>
                    <div className="truncate text-omi-text-muted">
                      {compactProvider(entry.provider)} {entry.target}
                    </div>
                  </div>
                  <div className={`self-center border px-2 py-1 text-center font-semibold ${statusClass(entry.status, entry.ok)}`}>
                    {entry.ok
                      ? t("crypto.market.status.ok")
                      : entry.status === "stale"
                        ? t("crypto.market.status.stale")
                        : entry.status === "disabled"
                          ? t("crypto.market.status.disabled")
                          : entry.status}
                  </div>
                  <div className="self-center text-right tabular-nums text-omi-text-muted">{entry.row_count}</div>
                </div>
              ))}
            </div>
          </section>

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
              <td className="px-3 py-6 text-center text-omi-text-muted" colSpan={columns.length}>
                {emptyLabel}
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

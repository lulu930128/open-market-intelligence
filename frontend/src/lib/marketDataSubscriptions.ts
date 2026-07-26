import { fetchJson, requestJson } from "@/lib/api";

export type MarketDataSubscriptionMode =
  | "always_on"
  | "on_select"
  | "manual"
  | "disabled";

export type MarketDataSubscriptionItem = {
  key: string;
  market: string;
  group: string;
  label: string;
  mode: MarketDataSubscriptionMode;
  resources: Record<string, boolean>;
  intervals: Record<string, number>;
  provider_status?: string | null;
  note?: string | null;
};

export type MarketDataSubscriptionSettingsRead = {
  kind: string;
  version: string;
  source: string;
  items: MarketDataSubscriptionItem[];
  runtime?: {
    crypto_realtime_reload?: {
      status?: string;
      message?: string;
      enabled_stream_count?: number;
      reload_count?: number;
      last_reload_at?: string | null;
    };
    crypto_auto_refresh_reload?: {
      status?: string;
      message?: string;
      active_resource_count?: number;
      reload_count?: number;
      last_reload_at?: string | null;
    };
  };
};

export type MarketDataSubscriptionItemWrite = Pick<
  MarketDataSubscriptionItem,
  "key" | "mode" | "resources" | "intervals"
>;

export type MarketDataSubscriptionSettingsWrite = {
  items: MarketDataSubscriptionItemWrite[];
};

export const MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT =
  "omi:market-data-subscriptions-updated";
export const RESOURCE_SELECTED_QUOTE_SECONDS_KEY = "selected_quote_seconds";
export const RESOURCE_BACKGROUND_QUOTE_SECONDS_KEY = "background_quote_seconds";
export const RESOURCE_SELECTED_QUOTE_DEFAULT_SECONDS = 5;
export const RESOURCE_BACKGROUND_QUOTE_DEFAULT_SECONDS = 300;
export const RESOURCE_SELECTED_QUOTE_MIN_SECONDS = 1;
export const RESOURCE_SELECTED_QUOTE_MAX_SECONDS = 60;
export const RESOURCE_BACKGROUND_QUOTE_MIN_SECONDS = 60;
export const RESOURCE_BACKGROUND_QUOTE_MAX_SECONDS = 300;

const manualRefreshModes = new Set<MarketDataSubscriptionMode>([
  "always_on",
  "on_select",
  "manual",
]);

const quotePollingModes = new Set<MarketDataSubscriptionMode>([
  "always_on",
  "on_select",
]);

const autoRefreshModes = new Set<MarketDataSubscriptionMode>([
  "always_on",
  "on_select",
]);

const missingDataRepairModes = new Set<MarketDataSubscriptionMode>([
  "always_on",
  "on_select",
  "manual",
]);

export function loadMarketDataSubscriptionSettings() {
  return fetchJson<MarketDataSubscriptionSettingsRead>(
    "/api/settings/market-data-subscriptions"
  );
}

export function saveMarketDataSubscriptionSettings(
  payload: MarketDataSubscriptionSettingsWrite
) {
  return requestJson<MarketDataSubscriptionSettingsRead>(
    "/api/settings/market-data-subscriptions",
    {
      method: "PUT",
      body: JSON.stringify(payload),
    }
  ).then((settings) => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent<MarketDataSubscriptionSettingsRead>(
          MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
          { detail: settings }
        )
      );
    }
    return settings;
  });
}

export function marketDataSubscriptionItem(
  settings: MarketDataSubscriptionSettingsRead | null | undefined,
  key: string
) {
  return settings?.items.find((item) => item.key === key) ?? null;
}

export function cryptoSubscriptionItem(
  settings: MarketDataSubscriptionSettingsRead | null | undefined,
  baseAsset: string
) {
  return marketDataSubscriptionItem(settings, `crypto:${baseAsset.toUpperCase()}`);
}

export function subscriptionModeAllowsManualRefresh(
  mode: MarketDataSubscriptionMode | null | undefined
) {
  return Boolean(mode && manualRefreshModes.has(mode));
}

export function resourceSubscriptionAllowsQuotePolling(
  item: MarketDataSubscriptionItem | null | undefined
) {
  return Boolean(
    item &&
      item.market === "resource" &&
      item.resources.quote === true &&
      quotePollingModes.has(item.mode)
  );
}

export function resourceSubscriptionAllowsManualRefresh(
  item: MarketDataSubscriptionItem | null | undefined,
  resource = "ohlcv"
) {
  return Boolean(
    item &&
      item.market === "resource" &&
      item.resources[resource] === true &&
      manualRefreshModes.has(item.mode)
  );
}

export function resourceSubscriptionAllowsAutoRefresh(
  item: MarketDataSubscriptionItem | null | undefined,
  resource = "ohlcv"
) {
  return Boolean(
    item &&
      item.market === "resource" &&
      item.resources[resource] === true &&
      autoRefreshModes.has(item.mode)
  );
}

export function resourceSubscriptionAllowsMissingDataRepair(
  item: MarketDataSubscriptionItem | null | undefined,
  resource = "ohlcv"
) {
  return Boolean(
    item &&
      item.market === "resource" &&
      item.resources[resource] === true &&
      missingDataRepairModes.has(item.mode)
  );
}

export function subscriptionIntervalSeconds(
  item: MarketDataSubscriptionItem | null | undefined,
  key: string,
  fallback: number,
  bounds: { min?: number; max?: number } = {}
) {
  const value = item?.intervals[key];
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;

  const min = bounds.min ?? 1;
  const max = bounds.max ?? Number.MAX_SAFE_INTEGER;
  return Math.min(Math.max(value, min), max);
}

export function resourceSelectedQuoteIntervalSeconds(
  item: MarketDataSubscriptionItem | null | undefined
) {
  return subscriptionIntervalSeconds(
    item,
    RESOURCE_SELECTED_QUOTE_SECONDS_KEY,
    RESOURCE_SELECTED_QUOTE_DEFAULT_SECONDS,
    {
      min: RESOURCE_SELECTED_QUOTE_MIN_SECONDS,
      max: RESOURCE_SELECTED_QUOTE_MAX_SECONDS,
    }
  );
}

export function resourceBackgroundQuoteIntervalSeconds(
  item: MarketDataSubscriptionItem | null | undefined
) {
  return subscriptionIntervalSeconds(
    item,
    RESOURCE_BACKGROUND_QUOTE_SECONDS_KEY,
    RESOURCE_BACKGROUND_QUOTE_DEFAULT_SECONDS,
    {
      min: RESOURCE_BACKGROUND_QUOTE_MIN_SECONDS,
      max: RESOURCE_BACKGROUND_QUOTE_MAX_SECONDS,
    }
  );
}

export function cryptoSubscriptionResourceEnabled(
  settings: MarketDataSubscriptionSettingsRead | null | undefined,
  baseAsset: string,
  resource: string
) {
  const item = cryptoSubscriptionItem(settings, baseAsset);
  if (!item) return false;
  return subscriptionModeAllowsManualRefresh(item.mode) && item.resources[resource] === true;
}

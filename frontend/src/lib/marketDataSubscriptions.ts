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

const manualRefreshModes = new Set<MarketDataSubscriptionMode>([
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
  );
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

export function cryptoSubscriptionResourceEnabled(
  settings: MarketDataSubscriptionSettingsRead | null | undefined,
  baseAsset: string,
  resource: string
) {
  const item = cryptoSubscriptionItem(settings, baseAsset);
  if (!item) return false;
  return subscriptionModeAllowsManualRefresh(item.mode) && item.resources[resource] === true;
}

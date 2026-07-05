import { useEffect, useState } from "react";

import { fetchJson } from "@/lib/api";

export type RefreshExecutionMarket = "tw" | "us" | "jp" | "kr";

export type RefreshExecutionField =
  | "observed_stock_refresh_interval_seconds"
  | "subresource_refresh_interval_seconds"
  | "market_refresh_interval_seconds";

export type RefreshExecutionMarketPolicy = Record<RefreshExecutionField, number>;

export type RefreshExecutionSettingsRead = {
  kind: string;
  version: string;
  source: string;
  markets: Record<RefreshExecutionMarket, RefreshExecutionMarketPolicy>;
};

export type RefreshExecutionSettingsWrite = Pick<RefreshExecutionSettingsRead, "markets">;

let cachedRefreshExecutionSettings: RefreshExecutionSettingsRead | null = null;
let refreshExecutionSettingsPromise: Promise<RefreshExecutionSettingsRead> | null = null;
const refreshExecutionSettingsListeners = new Set<
  (settings: RefreshExecutionSettingsRead | null) => void
>();

function notifyRefreshExecutionSettingsListeners() {
  refreshExecutionSettingsListeners.forEach((listener) =>
    listener(cachedRefreshExecutionSettings)
  );
}

export function setCachedRefreshExecutionSettings(
  settings: RefreshExecutionSettingsRead
) {
  cachedRefreshExecutionSettings = settings;
  refreshExecutionSettingsPromise = null;
  notifyRefreshExecutionSettingsListeners();
}

export async function loadRefreshExecutionSettings() {
  if (cachedRefreshExecutionSettings) return cachedRefreshExecutionSettings;

  refreshExecutionSettingsPromise ??= fetchJson<RefreshExecutionSettingsRead>(
    "/api/settings/refresh-execution"
  )
    .then((settings) => {
      setCachedRefreshExecutionSettings(settings);
      return settings;
    })
    .catch((error) => {
      refreshExecutionSettingsPromise = null;
      throw error;
    });

  return refreshExecutionSettingsPromise;
}

export function useRefreshExecutionSettings() {
  const [settings, setSettings] = useState<RefreshExecutionSettingsRead | null>(
    cachedRefreshExecutionSettings
  );

  useEffect(() => {
    let active = true;
    const listener = (nextSettings: RefreshExecutionSettingsRead | null) => {
      if (active) setSettings(nextSettings);
    };

    refreshExecutionSettingsListeners.add(listener);
    void loadRefreshExecutionSettings().catch(() => {
      if (active) setSettings(cachedRefreshExecutionSettings);
    });

    return () => {
      active = false;
      refreshExecutionSettingsListeners.delete(listener);
    };
  }, []);

  return settings;
}

export function getRefreshExecutionSeconds(
  settings: RefreshExecutionSettingsRead | null,
  market: RefreshExecutionMarket,
  field: RefreshExecutionField,
  fallbackSeconds: number
) {
  const value = settings?.markets?.[market]?.[field];
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallbackSeconds;
}

"use client";

import { requestJson } from "@/lib/api";
import { refreshMarketCalendarStatus } from "@/lib/marketCalendarStatus";
import {
  MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
  loadMarketDataSubscriptionSettings,
  resourceBackgroundQuoteIntervalSeconds,
  resourceSubscriptionAllowsQuotePolling,
  type MarketDataSubscriptionSettingsRead,
} from "@/lib/marketDataSubscriptions";
import {
  resourceSymbolFromKey,
  type ResourceRefreshResult,
} from "@/types/resourceMarket";
import { useEffect, useMemo, useRef, useState } from "react";

import type { MarketRegion } from "@/components/market-dashboard/selection/dashboardRoutes";

type ResourceBackgroundPollingGroup = {
  intervalSeconds: number;
  symbols: string[];
  key: string;
};

function resourceBackgroundQuotePollingGroups(
  settings: MarketDataSubscriptionSettingsRead | null,
  selectedResourceInstrumentKey: string | null
) {
  if (!settings) return [];

  const groups = new Map<number, Set<string>>();
  for (const item of settings.items) {
    if (!resourceSubscriptionAllowsQuotePolling(item)) continue;
    if (item.key === selectedResourceInstrumentKey) continue;

    const symbol = resourceSymbolFromKey(item.key);
    if (!symbol) continue;

    const intervalSeconds = resourceBackgroundQuoteIntervalSeconds(item);
    if (!groups.has(intervalSeconds)) {
      groups.set(intervalSeconds, new Set());
    }
    groups.get(intervalSeconds)?.add(symbol);
  }

  return Array.from(groups.entries())
    .map<ResourceBackgroundPollingGroup>(([intervalSeconds, symbols]) => ({
      intervalSeconds,
      symbols: Array.from(symbols).sort(),
      key: `${intervalSeconds}:${Array.from(symbols).sort().join(",")}`,
    }))
    .sort((left, right) => left.intervalSeconds - right.intervalSeconds);
}

function useMarketCalendarPolling() {
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function loadCalendarStatus() {
      try {
        await refreshMarketCalendarStatus("all");
      } catch (error) {
        console.warn("Market calendar status refresh failed.", error);
      } finally {
        if (!cancelled) {
          timer = window.setTimeout(loadCalendarStatus, 60_000);
        }
      }
    }

    void loadCalendarStatus();

    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, []);
}

function useResourceBackgroundQuotePolling({
  activeMarket,
  selectedResourceInstrumentKey,
}: {
  activeMarket: MarketRegion;
  selectedResourceInstrumentKey: string | null;
}) {
  const [subscriptionSettings, setSubscriptionSettings] =
    useState<MarketDataSubscriptionSettingsRead | null>(null);
  const requestKeysRef = useRef(new Set<string>());
  const pollingGroups = useMemo(
    () =>
      activeMarket === "crypto"
        ? resourceBackgroundQuotePollingGroups(
            subscriptionSettings,
            selectedResourceInstrumentKey
          )
        : [],
    [activeMarket, selectedResourceInstrumentKey, subscriptionSettings]
  );

  useEffect(() => {
    if (activeMarket !== "crypto") return;

    let cancelled = false;

    async function loadSubscriptionSettings() {
      try {
        const settings = await loadMarketDataSubscriptionSettings();
        if (!cancelled) {
          setSubscriptionSettings(settings);
        }
      } catch {
        if (!cancelled) {
          setSubscriptionSettings(null);
        }
      }
    }

    function handleSubscriptionSettingsUpdated(event: Event) {
      const nextSettings = (
        event as CustomEvent<MarketDataSubscriptionSettingsRead>
      ).detail;
      if (nextSettings) {
        setSubscriptionSettings(nextSettings);
      } else {
        void loadSubscriptionSettings();
      }
    }

    void loadSubscriptionSettings();
    window.addEventListener(
      MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
      handleSubscriptionSettingsUpdated
    );

    return () => {
      cancelled = true;
      window.removeEventListener(
        MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
        handleSubscriptionSettingsUpdated
      );
    };
  }, [activeMarket]);

  useEffect(() => {
    if (activeMarket !== "crypto" || !pollingGroups.length) return;

    const timers = pollingGroups.map((group) => {
      const run = async () => {
        if (document.visibilityState !== "visible") return;
        if (requestKeysRef.current.has(group.key)) return;

        requestKeysRef.current.add(group.key);
        try {
          await requestJson<ResourceRefreshResult>(
            "/api/resource-market/quotes/refresh",
            { method: "POST" },
            { symbols: group.symbols.join(",") }
          );
        } catch {
          // Background quote polling must not replace visible panel state.
        } finally {
          requestKeysRef.current.delete(group.key);
        }
      };

      return window.setInterval(run, group.intervalSeconds * 1000);
    });

    return () => {
      timers.forEach((timer) => window.clearInterval(timer));
    };
  }, [activeMarket, pollingGroups]);
}

export function useDashboardRuntime({
  activeMarket,
  selectedResourceInstrumentKey,
}: {
  activeMarket: MarketRegion;
  selectedResourceInstrumentKey: string | null;
}) {
  useMarketCalendarPolling();
  useResourceBackgroundQuotePolling({
    activeMarket,
    selectedResourceInstrumentKey,
  });
}

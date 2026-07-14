"use client";

import { fetchJson } from "@/lib/api";
import { getJobResultStatus, requestBackfillJob } from "@/lib/jobs";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  getTaiwanMarketChipRefreshState,
  getTaiwanMarketRefreshState,
} from "@/lib/taiwanMarketTime";
import type { MarketIndexSummary } from "@/types/market";
import { useCallback, useEffect, useRef, useState } from "react";

import type { DashboardLoadState } from "@/components/market-dashboard/dashboardFormatters";

export type TaiwanMarketTapeErrorKind = "summary" | "chip-refresh";

type UseTaiwanMarketTapeStateOptions = {
  active: boolean;
  initialSummary: MarketIndexSummary | null;
  onError: (
    kind: TaiwanMarketTapeErrorKind,
    error: unknown,
    context?: { dateKey: string }
  ) => void;
};

const MARKET_CHIP_REFRESH_STORAGE_PREFIX = "omi:market-chip-refresh";

function marketChipRefreshStorageKey(dateKey: string) {
  return `${MARKET_CHIP_REFRESH_STORAGE_PREFIX}:${dateKey}`;
}

function isStoredMarketChipRefreshDone(dateKey: string) {
  try {
    return window.localStorage.getItem(marketChipRefreshStorageKey(dateKey)) === "done";
  } catch {
    return false;
  }
}

function markStoredMarketChipRefreshDone(dateKey: string) {
  try {
    window.localStorage.setItem(marketChipRefreshStorageKey(dateKey), "done");
  } catch {
    // Job dedupe still prevents identical active refreshes if storage is unavailable.
  }
}

export function useTaiwanMarketTapeState({
  active,
  initialSummary,
  onError,
}: UseTaiwanMarketTapeStateOptions) {
  const [summary, setSummary] = useState<MarketIndexSummary | null>(initialSummary);
  const [loadState, setLoadState] = useState<DashboardLoadState>(
    initialSummary ? "success" : "idle"
  );
  const requestSeqRef = useRef(0);
  const chipRefreshRequestKeysRef = useRef(new Set<string>());
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const load = useCallback(async (options?: { silent?: boolean }) => {
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;

    if (!options?.silent) {
      setLoadState("loading");
    }

    try {
      const summaryData = await fetchJson<MarketIndexSummary>(
        "/api/market/indices/summary"
      );

      if (requestSeqRef.current !== requestSeq) return null;

      setSummary(summaryData);
      setLoadState("success");
      return summaryData;
    } catch (error) {
      if (requestSeqRef.current !== requestSeq) return null;

      setLoadState("error");
      onErrorRef.current("summary", error);
      return null;
    }
  }, []);

  const refreshMarketChipsForFreshness = useCallback(
    async (dateKey: string) => {
      if (isStoredMarketChipRefreshDone(dateKey)) return;
      if (chipRefreshRequestKeysRef.current.has(dateKey)) return;

      chipRefreshRequestKeysRef.current.add(dateKey);

      try {
        const job = await requestBackfillJob(
          "/api/market/market-chips/refresh",
          { method: "POST" },
          {
            include_today: true,
            force: false,
          },
          {
            intervalMs: 1500,
            timeoutMs: 600_000,
          }
        );

        if (getJobResultStatus(job) === "success") {
          markStoredMarketChipRefreshDone(dateKey);
        }

        await load({ silent: true });
      } catch (error) {
        console.warn("Market chip daily refresh failed.", error);
        onErrorRef.current("chip-refresh", error, { dateKey });
      }
    },
    [load]
  );

  useEffect(() => {
    if (!active) return;

    let disposed = false;
    let refreshTimer: number | undefined;

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getTaiwanMarketRefreshState();
      const delay = marketState.isPollingWindow
        ? TAIWAN_INTRADAY_REFRESH_MS
        : Math.min(marketState.msUntilNextPollingStart, 300_000);

      refreshTimer = window.setTimeout(() => {
        void load({ silent: true }).finally(scheduleRefresh);
      }, delay);
    }

    const initialTimer = window.setTimeout(() => {
      void load().finally(scheduleRefresh);
    }, 0);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, [active, load]);

  useEffect(() => {
    if (!active) return;

    let disposed = false;
    let refreshTimer: number | undefined;

    function clearRefreshTimer() {
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
    }

    function scheduleRefresh() {
      if (disposed) return;

      const state = getTaiwanMarketChipRefreshState();
      const alreadyQueued =
        chipRefreshRequestKeysRef.current.has(state.dateKey) ||
        isStoredMarketChipRefreshDone(state.dateKey);
      const delay =
        state.shouldRefreshNow && !alreadyQueued ? 0 : state.msUntilNextRefresh;

      refreshTimer = window.setTimeout(() => {
        const nextState = getTaiwanMarketChipRefreshState();
        const nextAlreadyQueued =
          chipRefreshRequestKeysRef.current.has(nextState.dateKey) ||
          isStoredMarketChipRefreshDone(nextState.dateKey);

        if (nextState.shouldRefreshNow && !nextAlreadyQueued) {
          void refreshMarketChipsForFreshness(nextState.dateKey).finally(
            scheduleRefresh
          );
          return;
        }

        scheduleRefresh();
      }, delay);
    }

    scheduleRefresh();

    return () => {
      disposed = true;
      clearRefreshTimer();
    };
  }, [active, refreshMarketChipsForFreshness]);

  useEffect(() => {
    return () => {
      requestSeqRef.current += 1;
    };
  }, []);

  return {
    state: {
      summary,
      loadState,
    },
    actions: {
      load,
    },
  };
}

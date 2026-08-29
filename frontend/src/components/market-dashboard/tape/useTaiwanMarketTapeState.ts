"use client";

import { fetchJson } from "@/lib/api";
import { getJobResultStatus, requestBackfillJob } from "@/lib/jobs";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  TAIWAN_MARKET_CHIP_REFRESH_EVENT,
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

function marketChipRefreshStorageKey(refreshKey: string) {
  return `${MARKET_CHIP_REFRESH_STORAGE_PREFIX}:${refreshKey}`;
}

function isStoredMarketChipRefreshDone(refreshKey: string) {
  try {
    return window.localStorage.getItem(marketChipRefreshStorageKey(refreshKey)) === "done";
  } catch {
    return false;
  }
}

function markStoredMarketChipRefreshDone(refreshKey: string) {
  try {
    window.localStorage.setItem(marketChipRefreshStorageKey(refreshKey), "done");
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
  const hasHydratedSummaryRef = useRef(initialSummary !== null);
  const indexSummaryRefreshKeysRef = useRef(new Set<string>());
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
    async (refreshKey: string, dateKey: string) => {
      if (isStoredMarketChipRefreshDone(refreshKey)) return;
      if (chipRefreshRequestKeysRef.current.has(refreshKey)) return;

      chipRefreshRequestKeysRef.current.add(refreshKey);

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

        const resultStatus = getJobResultStatus(job);
        if (resultStatus === "success") {
          markStoredMarketChipRefreshDone(refreshKey);
        }
        if (resultStatus === "success" || resultStatus === "partial_success") {
          window.dispatchEvent(
            new CustomEvent(TAIWAN_MARKET_CHIP_REFRESH_EVENT, {
              detail: { refreshKey },
            })
          );
        }

        await load({ silent: true });
      } catch (error) {
        console.warn("Market chip daily refresh failed.", error);
        onErrorRef.current("chip-refresh", error, { dateKey });
      }
    },
    [load]
  );

  const refreshIndexSummary = useCallback(
    async (refreshKey: string) => {
      if (indexSummaryRefreshKeysRef.current.has(refreshKey)) return;
      indexSummaryRefreshKeysRef.current.add(refreshKey);

      try {
        await requestBackfillJob(
          "/api/market/indices/summary/refresh-job",
          { method: "POST" },
          undefined,
          { intervalMs: 1_000, timeoutMs: 120_000 }
        );
        await load({ silent: true });
      } catch (error) {
        indexSummaryRefreshKeysRef.current.delete(refreshKey);
        onErrorRef.current("summary", error);
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

    let initialTimer: number | undefined;
    if (hasHydratedSummaryRef.current) {
      scheduleRefresh();
    } else {
      initialTimer = window.setTimeout(() => {
        void load().finally(scheduleRefresh);
      }, 0);
    }

    return () => {
      disposed = true;
      if (initialTimer !== undefined) {
        window.clearTimeout(initialTimer);
      }
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, [active, load]);

  useEffect(() => {
    if (!active || !summary) return;
    if (
      summary.refresh_recommended !== true &&
      summary.cache_status !== "local_cache" &&
      summary.cache_status !== "stale_memory_cache"
    ) {
      return;
    }

    const refreshKey = `${summary.cache_status ?? "unknown"}:${summary.as_of}`;
    const timer = window.setTimeout(() => {
      void refreshIndexSummary(refreshKey);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [active, refreshIndexSummary, summary]);

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
        chipRefreshRequestKeysRef.current.has(state.refreshKey) ||
        isStoredMarketChipRefreshDone(state.refreshKey);
      const delay =
        state.shouldRefreshNow && !alreadyQueued ? 0 : state.msUntilNextRefresh;

      refreshTimer = window.setTimeout(() => {
        const nextState = getTaiwanMarketChipRefreshState();
        const nextAlreadyQueued =
          chipRefreshRequestKeysRef.current.has(nextState.refreshKey) ||
          isStoredMarketChipRefreshDone(nextState.refreshKey);

        if (nextState.shouldRefreshNow && !nextAlreadyQueued) {
          void refreshMarketChipsForFreshness(
            nextState.refreshKey,
            nextState.dateKey
          ).finally(scheduleRefresh);
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

"use client";

import { fetchJson } from "@/lib/api";
import { requestBackfillJob } from "@/lib/jobs";
import {
  getRefreshExecutionSeconds,
  type RefreshExecutionSettingsRead,
} from "@/lib/refreshExecutionSettings";
import {
  US_INTRADAY_REFRESH_MS,
  getUsMarketRefreshState,
} from "@/lib/usMarketTime";
import type { USWatchlistRankingRead } from "@/types/market";
import { useCallback, useEffect, useRef, useState } from "react";

export type UsRankBy = "none" | "change_pct" | "volume" | "close";
export type UsRankingErrorKind = "ranking" | "daily-refresh";
export type UsRankingLoadState = "idle" | "loading" | "success" | "error";

type UseUsRankingStateOptions = {
  active: boolean;
  groupId: number | null;
  refreshExecutionSettings: RefreshExecutionSettingsRead | null;
  startCompanionLoad: (input: { groupId: number; silent: boolean }) => void;
  onError: (kind: UsRankingErrorKind, error: unknown, groupId: number) => void;
};

const WATCHLIST_INTRADAY_LIMIT = 30;

function formatDashboardTime(value: Date) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })
      .formatToParts(value)
      .map((part) => [part.type, part.value])
  );

  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function useUsRankingState({
  active,
  groupId,
  refreshExecutionSettings,
  startCompanionLoad,
  onError,
}: UseUsRankingStateOptions) {
  const [rankBy, setRankBy] = useState<UsRankBy>("none");
  const [ranking, setRanking] = useState<USWatchlistRankingRead | null>(null);
  const [loadState, setLoadState] = useState<UsRankingLoadState>("idle");
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [watchlistVersion, setWatchlistVersion] = useState(0);
  const requestSeqRef = useRef(0);
  const finalRefreshDateRef = useRef<string | null>(null);
  const freshnessRequestKeysRef = useRef(new Set<string>());
  const initialPreloadQueuedRef = useRef(false);
  const selectedGroupIdRef = useRef(groupId);
  const rankByRef = useRef(rankBy);
  const refreshExecutionSettingsRef = useRef(refreshExecutionSettings);
  const startCompanionLoadRef = useRef(startCompanionLoad);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    selectedGroupIdRef.current = groupId;
    rankByRef.current = rankBy;
    refreshExecutionSettingsRef.current = refreshExecutionSettings;
    startCompanionLoadRef.current = startCompanionLoad;
    onErrorRef.current = onError;
  }, [groupId, onError, rankBy, refreshExecutionSettings, startCompanionLoad]);

  const load = useCallback(
    async (
      currentGroupId: number,
      currentRankBy = rankByRef.current,
      options?: { silent?: boolean }
    ): Promise<USWatchlistRankingRead | null> => {
      const requestSeq = requestSeqRef.current + 1;
      requestSeqRef.current = requestSeq;

      if (!options?.silent) {
        setLoadState("loading");
      }
      startCompanionLoadRef.current({
        groupId: currentGroupId,
        silent: Boolean(options?.silent),
      });

      try {
        const marketState = getUsMarketRefreshState();
        const rankingData = await fetchJson<USWatchlistRankingRead>(
          "/api/us-market/watchlists/ranking",
          {
            group_id: currentGroupId,
            include_children: true,
            enabled_only: true,
            rank_by: currentRankBy,
            sort_order: currentRankBy === "none" ? "asc" : "desc",
            use_intraday: marketState.isPollingWindow,
            intraday_limit: WATCHLIST_INTRADAY_LIMIT,
          }
        );

        if (requestSeqRef.current !== requestSeq) return null;

        setRanking(rankingData);
        setLastUpdatedAt(formatDashboardTime(new Date()));
        setLoadState("success");
        return rankingData;
      } catch (error) {
        if (requestSeqRef.current !== requestSeq) return null;

        setLoadState("error");
        onErrorRef.current("ranking", error, currentGroupId);
        return null;
      }
    },
    []
  );

  const refreshDailyPrices = useCallback(
    async (
      currentGroupId: number,
      currentRankBy = rankByRef.current,
      targetTradeDate: string | null
    ) => {
      const requestKey = `${currentGroupId}:${targetTradeDate ?? "unknown"}:daily`;

      if (freshnessRequestKeysRef.current.has(requestKey)) return;
      freshnessRequestKeysRef.current.add(requestKey);

      try {
        await requestBackfillJob(
          `/api/us-market/watchlists/groups/${currentGroupId}/refresh-daily`,
          { method: "POST" },
          {
            include_children: true,
            enabled_only: true,
            outputsize: "compact",
            adjusted: false,
            sleep_seconds: getRefreshExecutionSeconds(
              refreshExecutionSettingsRef.current,
              "us",
              "observed_stock_refresh_interval_seconds",
              12
            ),
          },
          {
            intervalMs: 1500,
            timeoutMs: 1_800_000,
          }
        );

        if (selectedGroupIdRef.current === currentGroupId) {
          await load(currentGroupId, currentRankBy, { silent: true });
        }
      } catch (error) {
        onErrorRef.current("daily-refresh", error, currentGroupId);
      }
    },
    [load]
  );

  const changeRankBy = useCallback((value: UsRankBy) => {
    requestSeqRef.current += 1;
    rankByRef.current = value;
    setRankBy(value);
    setRanking(null);
    setLoadState("idle");
  }, []);

  const reset = useCallback(() => {
    requestSeqRef.current += 1;
    setRanking(null);
    setLoadState("idle");
  }, []);

  const notifyWatchlistChanged = useCallback(() => {
    requestSeqRef.current += 1;
    setWatchlistVersion((version) => version + 1);
  }, []);

  useEffect(() => {
    return () => {
      requestSeqRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (groupId === null || active || initialPreloadQueuedRef.current) return;

    initialPreloadQueuedRef.current = true;
    const currentGroupId = groupId;
    const refreshTimer = window.setTimeout(() => {
      void load(currentGroupId, rankBy, { silent: true }).then((rankingData) => {
        if (selectedGroupIdRef.current !== currentGroupId) return;
        if (rankingData?.is_current !== false) return;

        void refreshDailyPrices(
          currentGroupId,
          rankBy,
          rankingData.target_trade_date
        );
      });
    }, 0);

    return () => {
      window.clearTimeout(refreshTimer);
    };
  }, [active, groupId, load, rankBy, refreshDailyPrices]);

  useEffect(() => {
    if (!active || groupId === null) return;

    const currentGroupId = groupId;
    let disposed = false;
    let refreshTimer: number | undefined;

    function clearRefreshTimer() {
      if (refreshTimer === undefined) return;
      window.clearTimeout(refreshTimer);
      refreshTimer = undefined;
    }

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getUsMarketRefreshState();

      if (marketState.isPollingWindow) {
        refreshTimer = window.setTimeout(() => {
          void load(currentGroupId, rankBy, { silent: true }).finally(scheduleRefresh);
        }, US_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalRefreshDateRef.current !== marketState.dateKey
      ) {
        finalRefreshDateRef.current = marketState.dateKey;
        refreshTimer = window.setTimeout(() => {
          void load(currentGroupId, rankBy, { silent: true }).finally(scheduleRefresh);
        }, 0);
        return;
      }

      refreshTimer = window.setTimeout(
        scheduleRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    const initialTimer = window.setTimeout(() => {
      void load(currentGroupId, rankBy).finally(() => {
        const marketState = getUsMarketRefreshState();

        if (marketState.isAfterClose) {
          finalRefreshDateRef.current = marketState.dateKey;
        }
        scheduleRefresh();
      });
    }, 120);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      clearRefreshTimer();
    };
  }, [active, groupId, load, rankBy, watchlistVersion]);

  useEffect(() => {
    if (!active || groupId === null || ranking?.is_current !== false) return;

    const refreshTimer = window.setTimeout(() => {
      void refreshDailyPrices(groupId, rankBy, ranking.target_trade_date);
    }, 0);

    return () => {
      window.clearTimeout(refreshTimer);
    };
  }, [active, groupId, rankBy, ranking?.is_current, ranking?.target_trade_date, refreshDailyPrices]);

  return {
    state: {
      rankBy,
      ranking,
      loadState,
      lastUpdatedAt,
    },
    actions: {
      changeRankBy,
      load,
      notifyWatchlistChanged,
      refreshDailyPrices,
      reset,
    },
  };
}

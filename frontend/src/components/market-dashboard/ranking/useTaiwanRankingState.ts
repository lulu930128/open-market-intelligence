"use client";

import {
  buildProgressiveRankingResponse,
  mergeRankingBatchRows,
} from "@/components/market-dashboard/watchlistRankingRows";
import { fetchJson } from "@/lib/api";
import { requestBackfillJob } from "@/lib/jobs";
import {
  getMarketCalendarStatusSnapshot,
  msUntilIsoTime,
  refreshMarketCalendarStatus,
} from "@/lib/marketCalendarStatus";
import {
  getRefreshExecutionSeconds,
  type RefreshExecutionSettingsRead,
} from "@/lib/refreshExecutionSettings";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  getTaiwanMarketRefreshState,
} from "@/lib/taiwanMarketTime";
import type {
  RankingBatchResponse,
  RankingItem,
  RankingResponse,
} from "@/types/market";
import { useCallback, useEffect, useRef, useState } from "react";

export type TaiwanRankingLoadState = "idle" | "loading" | "success" | "error";
export type TaiwanRankBy = "none" | "change_pct" | "score" | "volume";
export type TaiwanRankingErrorKind = "ranking" | "daily-refresh";

type PrepareCompanionLoad = (input: {
  groupId: number;
  silent: boolean;
  useIntraday: boolean;
}) => () => void;

type UseTaiwanRankingStateOptions = {
  active: boolean;
  groupId: number | null;
  initialRanking: RankingResponse | null;
  refreshExecutionSettings: RefreshExecutionSettingsRead | null;
  prepareCompanionLoad: PrepareCompanionLoad;
  onError: (
    kind: TaiwanRankingErrorKind,
    error: unknown,
    groupId: number
  ) => void;
};

const WATCHLIST_INTRADAY_LIMIT = 30;
const WATCHLIST_RANKING_BATCH_SIZE = 3;
const WATCHLIST_DAILY_RELEASE_CHECK_MIN_MS = 5_000;
const WATCHLIST_DAILY_RELEASE_CHECK_MAX_MS = 300_000;
const WATCHLIST_ANALYSIS_PARAMS = {
  include_children: true,
  enabled_only: true,
  ma_windows: "5,20,60",
  volume_ma_windows: "5,20",
  volume_ratio_threshold: 1.5,
};

type TaiwanMarketRefreshState = ReturnType<typeof getTaiwanMarketRefreshState>;

function shouldUseIntraday(marketState: TaiwanMarketRefreshState) {
  return (
    marketState.isPollingWindow ||
    (marketState.isAfterClose && !marketState.isDailyPriceReleased)
  );
}

function getDailyReleaseCheckDelay() {
  const marketState = getTaiwanMarketRefreshState();
  const dailyRelease =
    getMarketCalendarStatusSnapshot("tw")?.release_windows.market_daily_price;
  const releaseDelay = marketState.isDailyPriceReleased
    ? msUntilIsoTime(dailyRelease?.next_release_at)
    : msUntilIsoTime(dailyRelease?.release_at);
  const fallbackDelay = marketState.isDailyPriceReleased
    ? marketState.msUntilNextPollingStart
    : 60_000;
  const delay = releaseDelay ?? fallbackDelay;

  return Math.min(
    Math.max(delay, WATCHLIST_DAILY_RELEASE_CHECK_MIN_MS),
    WATCHLIST_DAILY_RELEASE_CHECK_MAX_MS
  );
}

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

export function useTaiwanRankingState({
  active,
  groupId,
  initialRanking,
  refreshExecutionSettings,
  prepareCompanionLoad,
  onError,
}: UseTaiwanRankingStateOptions) {
  const [rankBy, setRankBy] = useState<TaiwanRankBy>("none");
  const [ranking, setRanking] = useState<RankingResponse | null>(initialRanking);
  const [loadState, setLoadState] = useState<TaiwanRankingLoadState>(
    initialRanking ? "success" : "idle"
  );
  const [trendPending, setTrendPending] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const requestSeqRef = useRef(0);
  const trendTimerRef = useRef<number | undefined>(undefined);
  const finalRefreshDateRef = useRef<string | null>(null);
  const freshnessRequestKeysRef = useRef(new Set<string>());
  const activeGroupIdRef = useRef(groupId);
  const rankByRef = useRef(rankBy);
  const refreshExecutionSettingsRef = useRef(refreshExecutionSettings);
  const prepareCompanionLoadRef = useRef(prepareCompanionLoad);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    activeGroupIdRef.current = groupId;
    rankByRef.current = rankBy;
    refreshExecutionSettingsRef.current = refreshExecutionSettings;
    prepareCompanionLoadRef.current = prepareCompanionLoad;
    onErrorRef.current = onError;
  }, [groupId, onError, prepareCompanionLoad, rankBy, refreshExecutionSettings]);

  const clearTrendTimer = useCallback(() => {
    if (trendTimerRef.current === undefined) return;

    window.clearTimeout(trendTimerRef.current);
    trendTimerRef.current = undefined;
  }, []);

  const scheduleTrendData = useCallback(
    (requestSeq: number, rankingData: RankingResponse) => {
      clearTrendTimer();

      trendTimerRef.current = window.setTimeout(() => {
        trendTimerRef.current = undefined;
        if (requestSeqRef.current !== requestSeq) return;

        setRanking(rankingData);
        setTrendPending(false);
      }, 0);
    },
    [clearTrendTimer]
  );

  const load = useCallback(
    async (
      currentGroupId: number,
      currentRankBy = rankByRef.current,
      options?: { silent?: boolean }
    ) => {
      const requestSeq = requestSeqRef.current + 1;
      requestSeqRef.current = requestSeq;
      const marketState = getTaiwanMarketRefreshState();
      const useIntraday = shouldUseIntraday(marketState);
      const queueCompanionLoad = prepareCompanionLoadRef.current({
        groupId: currentGroupId,
        silent: Boolean(options?.silent),
        useIntraday,
      });
      let companionLoadQueued = false;

      function ensureCompanionLoadQueued() {
        if (companionLoadQueued) return;
        companionLoadQueued = true;
        queueCompanionLoad();
      }

      if (!options?.silent) {
        setLoadState("loading");
      }

      try {
        const deferTrendData =
          !options?.silent && currentRankBy === "none" && useIntraday;

        clearTrendTimer();
        setTrendPending(deferTrendData);

        if (currentRankBy === "none") {
          let offset = 0;
          let loadedRows: RankingItem[] = [];
          let currentStockCount = 0;
          let staleStockCount = 0;
          let noDataCount = 0;
          let errorCount = 0;

          while (true) {
            const batch = await fetchJson<RankingBatchResponse>(
              `/api/watchlists/groups/${currentGroupId}/rankings/latest-batch`,
              {
                ...WATCHLIST_ANALYSIS_PARAMS,
                rank_by: "watchlist",
                sort_order: "asc",
                limit: 100,
                use_intraday: useIntraday,
                intraday_limit: WATCHLIST_INTRADAY_LIMIT,
                offset,
                batch_size: WATCHLIST_RANKING_BATCH_SIZE,
              }
            );

            if (requestSeqRef.current !== requestSeq) return null;

            loadedRows = mergeRankingBatchRows(loadedRows, batch.results);
            currentStockCount += batch.current_stock_count;
            staleStockCount += batch.stale_stock_count;
            noDataCount += batch.no_data_count;
            errorCount += batch.error_count;

            const nextRanking = buildProgressiveRankingResponse({
              batch,
              rows: loadedRows,
              currentStockCount,
              staleStockCount,
              noDataCount,
              errorCount,
              complete: !batch.has_more,
              deferTrendData,
            });

            setRanking(nextRanking);
            ensureCompanionLoadQueued();

            if (!batch.has_more || batch.requested_stock_count === 0) {
              const completeRanking = buildProgressiveRankingResponse({
                batch,
                rows: loadedRows,
                currentStockCount,
                staleStockCount,
                noDataCount,
                errorCount,
                complete: true,
              });

              setLastUpdatedAt(formatDashboardTime(new Date()));
              setLoadState("success");
              if (deferTrendData) {
                scheduleTrendData(requestSeq, completeRanking);
              }
              return completeRanking;
            }

            offset += batch.requested_stock_count;
          }
        }

        const rankingData = await fetchJson<RankingResponse>(
          `/api/watchlists/groups/${currentGroupId}/rankings/latest`,
          {
            ...WATCHLIST_ANALYSIS_PARAMS,
            rank_by: currentRankBy,
            sort_order: "desc",
            limit: 100,
            use_intraday: useIntraday,
            intraday_limit: WATCHLIST_INTRADAY_LIMIT,
          }
        );

        if (requestSeqRef.current !== requestSeq) return null;

        setRanking(rankingData);
        setTrendPending(false);
        setLastUpdatedAt(formatDashboardTime(new Date()));
        setLoadState("success");
        ensureCompanionLoadQueued();
        return rankingData;
      } catch (error) {
        if (requestSeqRef.current !== requestSeq) return null;

        clearTrendTimer();
        setTrendPending(false);
        setLoadState("error");
        onErrorRef.current("ranking", error, currentGroupId);
        return null;
      }
    },
    [clearTrendTimer, scheduleTrendData]
  );

  const refreshDailyPrices = useCallback(
    async (currentGroupId: number, currentRankBy = rankByRef.current) => {
      const marketState = getTaiwanMarketRefreshState();
      const includeToday = marketState.isDailyPriceReleased;
      const requestKey = `${currentGroupId}:${marketState.dateKey}:${
        includeToday ? "today" : "latest"
      }`;

      if (freshnessRequestKeysRef.current.has(requestKey)) return;
      freshnessRequestKeysRef.current.add(requestKey);

      try {
        await requestBackfillJob(
          `/api/watchlists/groups/${currentGroupId}/refresh-latest`,
          { method: "POST" },
          {
            lookback_days: 14,
            include_today: includeToday,
            include_children: true,
            enabled_only: true,
            sleep_seconds: getRefreshExecutionSeconds(
              refreshExecutionSettingsRef.current,
              "tw",
              "observed_stock_refresh_interval_seconds",
              0.3
            ),
            skip_existing_months: true,
          },
          {
            intervalMs: 1500,
            timeoutMs: 600_000,
          }
        );

        if (activeGroupIdRef.current === currentGroupId) {
          await load(currentGroupId, currentRankBy, { silent: true });
        }
      } catch (error) {
        freshnessRequestKeysRef.current.delete(requestKey);
        onErrorRef.current("daily-refresh", error, currentGroupId);
      }
    },
    [load]
  );

  const changeRankBy = useCallback(
    (value: TaiwanRankBy) => {
      requestSeqRef.current += 1;
      clearTrendTimer();
      rankByRef.current = value;
      setRankBy(value);
      setRanking(null);
      setLoadState("idle");
      setTrendPending(false);
    },
    [clearTrendTimer]
  );

  const reset = useCallback(() => {
    requestSeqRef.current += 1;
    clearTrendTimer();
    setRanking(null);
    setLoadState("idle");
    setTrendPending(false);
  }, [clearTrendTimer]);

  useEffect(() => {
    return () => {
      clearTrendTimer();
      requestSeqRef.current += 1;
    };
  }, [clearTrendTimer]);

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

      const marketState = getTaiwanMarketRefreshState();

      if (marketState.isPollingWindow) {
        refreshTimer = window.setTimeout(() => {
          void load(currentGroupId, rankBy, { silent: true }).finally(scheduleRefresh);
        }, TAIWAN_INTRADAY_REFRESH_MS);
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
        const marketState = getTaiwanMarketRefreshState();

        if (marketState.isAfterClose) {
          finalRefreshDateRef.current = marketState.dateKey;
        }

        scheduleRefresh();
        void refreshDailyPrices(currentGroupId, rankBy);
      });
    }, 120);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      clearRefreshTimer();
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

    function scheduleReleaseCheck(delay = getDailyReleaseCheckDelay()) {
      if (disposed) return;

      refreshTimer = window.setTimeout(() => {
        void checkDailyPriceRelease().finally(() => {
          if (!disposed) scheduleReleaseCheck();
        });
      }, delay);
    }

    async function checkDailyPriceRelease() {
      try {
        await refreshMarketCalendarStatus("tw");
      } catch (error) {
        console.warn("Taiwan calendar status refresh failed.", error);
      }

      if (disposed) return;

      if (getTaiwanMarketRefreshState().isDailyPriceReleased) {
        await refreshDailyPrices(currentGroupId, rankBy);
      }
    }

    scheduleReleaseCheck(0);

    return () => {
      disposed = true;
      clearRefreshTimer();
    };
  }, [active, groupId, rankBy, refreshDailyPrices]);

  useEffect(() => {
    if (!active || groupId === null || ranking?.is_current !== false) return;

    const refreshTimer = window.setTimeout(() => {
      void refreshDailyPrices(groupId, rankBy);
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
      trendPending,
      lastUpdatedAt,
    },
    actions: {
      changeRankBy,
      load,
      reset,
      refreshDailyPrices,
    },
  };
}

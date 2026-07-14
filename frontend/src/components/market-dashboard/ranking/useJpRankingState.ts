"use client";

import { fetchJson } from "@/lib/api";
import { requestBackfillJob } from "@/lib/jobs";
import {
  getRefreshExecutionSeconds,
  type RefreshExecutionSettingsRead,
} from "@/lib/refreshExecutionSettings";
import type { JPWatchlistRankingRead } from "@/types/market";
import { useCallback, useEffect, useRef, useState } from "react";

export type JpRankBy = "none" | "change_pct" | "volume" | "close";
export type JpRankingErrorKind = "ranking" | "daily-refresh";
export type JpRankingLoadState = "idle" | "loading" | "success" | "error";

type UseJpRankingStateOptions = {
  active: boolean;
  groupId: number | null;
  refreshExecutionSettings: RefreshExecutionSettingsRead | null;
  startCompanionLoad: (input: { groupId: number; silent: boolean }) => void;
  onError: (kind: JpRankingErrorKind, error: unknown, groupId: number) => void;
};

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

export function useJpRankingState({
  active,
  groupId,
  refreshExecutionSettings,
  startCompanionLoad,
  onError,
}: UseJpRankingStateOptions) {
  const [rankBy, setRankBy] = useState<JpRankBy>("none");
  const [ranking, setRanking] = useState<JPWatchlistRankingRead | null>(null);
  const [loadState, setLoadState] = useState<JpRankingLoadState>("idle");
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [dataRefreshNonce, setDataRefreshNonce] = useState(0);
  const requestSeqRef = useRef(0);
  const freshnessRequestKeysRef = useRef(new Set<string>());
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
    ): Promise<JPWatchlistRankingRead | null> => {
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
        const rankingData = await fetchJson<JPWatchlistRankingRead>(
          "/api/jp-market/watchlists/ranking",
          {
            group_id: currentGroupId,
            include_children: true,
            enabled_only: true,
            rank_by: currentRankBy,
            sort_order: currentRankBy === "none" ? "asc" : "desc",
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
      const requestKey = `${currentGroupId}:${targetTradeDate ?? "missing"}:daily`;

      if (freshnessRequestKeysRef.current.has(requestKey)) return;
      freshnessRequestKeysRef.current.add(requestKey);

      try {
        await requestBackfillJob(
          `/api/jp-market/watchlists/groups/${currentGroupId}/refresh-daily`,
          { method: "POST" },
          {
            include_children: true,
            enabled_only: true,
            outputsize: "compact",
            provider: "auto",
            sleep_seconds: getRefreshExecutionSeconds(
              refreshExecutionSettingsRef.current,
              "jp",
              "observed_stock_refresh_interval_seconds",
              1
            ),
          },
          {
            intervalMs: 1500,
            timeoutMs: 1_800_000,
          }
        );

        if (selectedGroupIdRef.current === currentGroupId) {
          setDataRefreshNonce((value) => value + 1);
          await load(currentGroupId, currentRankBy, { silent: true });
        }
      } catch (error) {
        onErrorRef.current("daily-refresh", error, currentGroupId);
      }
    },
    [load]
  );

  const changeRankBy = useCallback((value: JpRankBy) => {
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

  const notifyDataChanged = useCallback(() => {
    requestSeqRef.current += 1;
    setDataRefreshNonce((value) => value + 1);
  }, []);

  useEffect(() => {
    return () => {
      requestSeqRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!active || groupId === null) return;

    const refreshTimer = window.setTimeout(() => {
      void load(groupId, rankBy);
    }, 120);

    return () => {
      window.clearTimeout(refreshTimer);
    };
  }, [active, dataRefreshNonce, groupId, load, rankBy]);

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
      dataRefreshNonce,
    },
    actions: {
      changeRankBy,
      load,
      notifyDataChanged,
      refreshDailyPrices,
      reset,
    },
  };
}

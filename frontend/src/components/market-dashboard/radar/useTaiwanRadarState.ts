"use client";

import { fetchJson } from "@/lib/api";
import { getTaiwanMarketRefreshState } from "@/lib/taiwanMarketTime";
import type {
  WatchlistGroupRadarRead,
  WatchlistRadarMode,
  WatchlistRadarV2OutcomeSummaryRead,
} from "@/types/market";
import { useCallback, useEffect, useRef, useState } from "react";

export type TaiwanRadarLoadState = "idle" | "loading" | "success" | "error";
export type TaiwanRadarErrorKind = "radar" | "outcome" | "history";

type UseTaiwanRadarStateOptions = {
  active: boolean;
  groupId: number | null;
  initialMode: WatchlistRadarMode;
  initialRadar: WatchlistGroupRadarRead | null;
  routeMode: WatchlistRadarMode | null;
  onError: (kind: TaiwanRadarErrorKind, error: unknown, groupId: number) => void;
};

const WATCHLIST_INTRADAY_LIMIT = 30;
const WATCHLIST_RADAR_MAX_RESULTS = 20;
const WATCHLIST_RADAR_OUTCOME_ITEM_LIMIT = 200;
const WATCHLIST_RADAR_TIMEOUT_MS = 60_000;
const WATCHLIST_ANALYSIS_PARAMS = {
  include_children: true,
  enabled_only: true,
  ma_windows: "5,20,60",
  volume_ma_windows: "5,20",
  volume_ratio_threshold: 1.5,
};

function shouldUseIntraday() {
  const marketState = getTaiwanMarketRefreshState();
  return (
    marketState.isPollingWindow ||
    (marketState.isAfterClose && !marketState.isDailyPriceReleased)
  );
}

function radarParams(
  mode: WatchlistRadarMode,
  useIntraday: boolean,
  preferSnapshot = true
) {
  return {
    // Closed-session reads should match the backend's default calculation contract so
    // the saved daily snapshot can satisfy the request without recomputing the group.
    ...(useIntraday ? WATCHLIST_ANALYSIS_PARAMS : {}),
    mode,
    max_results: WATCHLIST_RADAR_MAX_RESULTS,
    calculation_limit: 100,
    use_intraday: useIntraday,
    intraday_limit: WATCHLIST_INTRADAY_LIMIT,
    prefer_snapshot: preferSnapshot,
    version: "v2",
  };
}

export function useTaiwanRadarState({
  active,
  groupId,
  initialMode,
  initialRadar,
  routeMode,
  onError,
}: UseTaiwanRadarStateOptions) {
  const [mode, setMode] = useState<WatchlistRadarMode>(initialMode);
  const [radar, setRadar] = useState<WatchlistGroupRadarRead | null>(initialRadar);
  const [loadState, setLoadState] = useState<TaiwanRadarLoadState>(
    initialRadar ? "success" : "idle"
  );
  const [outcomeSummary, setOutcomeSummary] =
    useState<WatchlistRadarV2OutcomeSummaryRead | null>(null);
  const [outcomeLoadState, setOutcomeLoadState] =
    useState<TaiwanRadarLoadState>("idle");
  const [outcomeHistory, setOutcomeHistory] =
    useState<WatchlistRadarV2OutcomeSummaryRead[]>([]);
  const [outcomeHistoryOpen, setOutcomeHistoryOpen] = useState(false);
  const [outcomeHistoryLoadState, setOutcomeHistoryLoadState] =
    useState<TaiwanRadarLoadState>("idle");
  const [outcomeDetailLoadState, setOutcomeDetailLoadState] =
    useState<TaiwanRadarLoadState>("idle");
  const [selectedOutcomeSnapshotId, setSelectedOutcomeSnapshotId] =
    useState<string | null>(null);
  const radarRequestSeqRef = useRef(0);
  const outcomeRequestSeqRef = useRef(0);
  const historyRequestSeqRef = useRef(0);
  const outcomeDetailRequestSeqRef = useRef(0);
  const modeRef = useRef(mode);
  const groupIdRef = useRef(groupId);
  const onErrorRef = useRef(onError);
  const selectedOutcomeSnapshotIdRef = useRef(selectedOutcomeSnapshotId);
  const previousGroupIdRef = useRef(groupId);

  useEffect(() => {
    groupIdRef.current = groupId;
    onErrorRef.current = onError;
    selectedOutcomeSnapshotIdRef.current = selectedOutcomeSnapshotId;
  }, [
    groupId,
    onError,
    selectedOutcomeSnapshotId,
  ]);

  const clearOutcomeHistory = useCallback(() => {
    historyRequestSeqRef.current += 1;
    outcomeDetailRequestSeqRef.current += 1;
    setOutcomeHistory([]);
    setOutcomeHistoryLoadState("idle");
    setOutcomeDetailLoadState("idle");
    setOutcomeHistoryOpen(false);
    setSelectedOutcomeSnapshotId(null);
    selectedOutcomeSnapshotIdRef.current = null;
  }, []);

  const reset = useCallback(() => {
    radarRequestSeqRef.current += 1;
    outcomeRequestSeqRef.current += 1;
    historyRequestSeqRef.current += 1;
    outcomeDetailRequestSeqRef.current += 1;
    setRadar(null);
    setLoadState("idle");
    setOutcomeSummary(null);
    setOutcomeLoadState("idle");
    setOutcomeHistory([]);
    setOutcomeHistoryLoadState("idle");
    setOutcomeDetailLoadState("idle");
    setOutcomeHistoryOpen(false);
    setSelectedOutcomeSnapshotId(null);
    selectedOutcomeSnapshotIdRef.current = null;
  }, []);

  const loadOutcome = useCallback(
    async (
      currentGroupId: number,
      options?: { mode?: WatchlistRadarMode; silent?: boolean }
    ): Promise<WatchlistRadarV2OutcomeSummaryRead | null> => {
      const requestSeq = outcomeRequestSeqRef.current + 1;
      outcomeRequestSeqRef.current = requestSeq;
      const currentMode = options?.mode ?? modeRef.current;

      if (!options?.silent) {
        setOutcomeLoadState("loading");
        setOutcomeSummary(null);
      }

      try {
        const outcomeData = await fetchJson<WatchlistRadarV2OutcomeSummaryRead>(
          `/api/watchlists/groups/${currentGroupId}/radar/v2/outcomes/latest`,
          {
            mode: currentMode,
            horizon_trading_days: 1,
            item_limit: WATCHLIST_RADAR_OUTCOME_ITEM_LIMIT,
          }
        );

        if (outcomeRequestSeqRef.current !== requestSeq) return null;

        setOutcomeSummary(outcomeData);
        setOutcomeLoadState("success");
        return outcomeData;
      } catch (error) {
        if (outcomeRequestSeqRef.current !== requestSeq) return null;

        if (!options?.silent) {
          setOutcomeSummary(null);
        }
        setOutcomeLoadState("error");
        onErrorRef.current("outcome", error, currentGroupId);
        return null;
      }
    },
    []
  );

  const loadOutcomeSnapshotDetails = useCallback(
    async (
      currentGroupId: number,
      snapshotDate: string,
      currentMode: WatchlistRadarMode
    ): Promise<WatchlistRadarV2OutcomeSummaryRead | null> => {
      const requestSeq = outcomeDetailRequestSeqRef.current + 1;
      outcomeDetailRequestSeqRef.current = requestSeq;
      setOutcomeDetailLoadState("loading");

      try {
        const outcomeData = await fetchJson<WatchlistRadarV2OutcomeSummaryRead>(
          `/api/watchlists/groups/${currentGroupId}/radar/v2/outcomes/latest`,
          {
            mode: currentMode,
            snapshot_date: snapshotDate,
            horizon_trading_days: 1,
            item_limit: WATCHLIST_RADAR_OUTCOME_ITEM_LIMIT,
          }
        );

        if (outcomeDetailRequestSeqRef.current !== requestSeq) return null;

        setOutcomeHistory((current) =>
          current.map((row) =>
            row.snapshot_date === outcomeData.snapshot_date ? outcomeData : row
          )
        );
        setOutcomeDetailLoadState("success");
        return outcomeData;
      } catch (error) {
        if (outcomeDetailRequestSeqRef.current !== requestSeq) return null;

        setOutcomeDetailLoadState("error");
        onErrorRef.current("history", error, currentGroupId);
        return null;
      }
    },
    []
  );

  const loadOutcomeHistory = useCallback(
    async (
      currentGroupId: number,
      options?: { mode?: WatchlistRadarMode; silent?: boolean }
    ): Promise<WatchlistRadarV2OutcomeSummaryRead[] | null> => {
      const requestSeq = historyRequestSeqRef.current + 1;
      historyRequestSeqRef.current = requestSeq;
      const currentMode = options?.mode ?? modeRef.current;

      if (!options?.silent) {
        setOutcomeHistoryLoadState("loading");
      }

      try {
        const historyData = await fetchJson<WatchlistRadarV2OutcomeSummaryRead[]>(
          `/api/watchlists/groups/${currentGroupId}/radar/v2/outcomes/history`,
          { mode: currentMode, horizon_trading_days: 1, limit: 60 }
        );

        if (historyRequestSeqRef.current !== requestSeq) return null;

        setOutcomeHistory(historyData);
        const currentSnapshotId = selectedOutcomeSnapshotIdRef.current;
        const nextSnapshotId =
          currentSnapshotId &&
          historyData.some((row) => row.snapshot_date === currentSnapshotId)
            ? currentSnapshotId
            : (historyData[0]?.snapshot_date ?? null);
        setSelectedOutcomeSnapshotId(nextSnapshotId);
        selectedOutcomeSnapshotIdRef.current = nextSnapshotId;
        setOutcomeHistoryLoadState("success");
        if (nextSnapshotId !== null) {
          void loadOutcomeSnapshotDetails(
            currentGroupId,
            nextSnapshotId,
            currentMode
          );
        } else {
          setOutcomeDetailLoadState("idle");
        }
        return historyData;
      } catch (error) {
        if (historyRequestSeqRef.current !== requestSeq) return null;

        if (!options?.silent) {
          setOutcomeHistory([]);
        }
        setOutcomeHistoryLoadState("error");
        onErrorRef.current("history", error, currentGroupId);
        return null;
      }
    },
    [loadOutcomeSnapshotDetails]
  );

  const load = useCallback(
    async (
      currentGroupId: number,
      options?: {
        mode?: WatchlistRadarMode;
        silent?: boolean;
        useIntraday?: boolean;
        preferSnapshot?: boolean;
        reservedRequestSeq?: number;
        statePrepared?: boolean;
      }
    ): Promise<WatchlistGroupRadarRead | null> => {
      const requestSeq =
        options?.reservedRequestSeq ?? radarRequestSeqRef.current + 1;
      if (
        options?.reservedRequestSeq !== undefined &&
        radarRequestSeqRef.current !== options.reservedRequestSeq
      ) {
        return null;
      }
      radarRequestSeqRef.current = requestSeq;
      const currentMode = options?.mode ?? modeRef.current;

      if (!options?.silent && !options?.statePrepared) {
        outcomeRequestSeqRef.current += 1;
        setLoadState("loading");
        setRadar(null);
        setOutcomeLoadState("loading");
        setOutcomeSummary(null);
      }

      try {
        const radarData = await fetchJson<WatchlistGroupRadarRead>(
          `/api/watchlists/groups/${currentGroupId}/radar`,
          radarParams(
            currentMode,
            options?.useIntraday ?? shouldUseIntraday(),
            options?.preferSnapshot ?? true
          ),
          { timeoutMs: WATCHLIST_RADAR_TIMEOUT_MS }
        );

        if (radarRequestSeqRef.current !== requestSeq) return null;

        if (
          radarData.radar_engine?.active_version !== "radar_v2.0" ||
          radarData.radar_engine?.mode !== "active"
        ) {
          throw new Error(
            "Taiwan Radar requires the active radar_v2.0 backend contract."
          );
        }

        setRadar(radarData);
        setLoadState("success");
        void loadOutcome(currentGroupId, {
          mode: currentMode,
          silent: true,
        });
        return radarData;
      } catch (error) {
        if (radarRequestSeqRef.current !== requestSeq) return null;

        if (!options?.silent) {
          setRadar(null);
          setOutcomeSummary(null);
          setOutcomeLoadState("idle");
        }
        setLoadState("error");
        onErrorRef.current("radar", error, currentGroupId);
        return null;
      }
    },
    [loadOutcome]
  );

  const prepareCompanionLoad = useCallback(
    ({
      groupId: currentGroupId,
      silent,
      useIntraday,
      preferSnapshot,
    }: {
      groupId: number;
      silent: boolean;
      useIntraday: boolean;
      preferSnapshot?: boolean;
    }) => {
      const reservedRequestSeq = radarRequestSeqRef.current + 1;
      radarRequestSeqRef.current = reservedRequestSeq;
      let loadPromise: Promise<WatchlistGroupRadarRead | null> | null = null;

      if (!silent) {
        outcomeRequestSeqRef.current += 1;
        setLoadState("loading");
        setOutcomeLoadState("loading");
        setOutcomeSummary(null);
      }

      return () => {
        if (loadPromise) return;
        loadPromise = load(currentGroupId, {
          mode: modeRef.current,
          silent,
          useIntraday,
          preferSnapshot,
          reservedRequestSeq,
          statePrepared: true,
        });
      };
    },
    [load]
  );

  const changeMode = useCallback(
    (value: WatchlistRadarMode) => {
      radarRequestSeqRef.current += 1;
      outcomeRequestSeqRef.current += 1;
      modeRef.current = value;
      setMode(value);
      clearOutcomeHistory();

      const currentGroupId = groupIdRef.current;
      if (currentGroupId !== null) {
        void load(currentGroupId, { mode: value });
      }
    },
    [clearOutcomeHistory, load]
  );

  const openOutcomeHistory = useCallback(() => {
    setOutcomeHistoryOpen(true);
    const currentGroupId = groupIdRef.current;
    if (currentGroupId !== null) {
      void loadOutcomeHistory(currentGroupId);
    }
  }, [loadOutcomeHistory]);

  const closeOutcomeHistory = useCallback(() => {
    setOutcomeHistoryOpen(false);
  }, []);

  const reloadOutcomeHistory = useCallback(() => {
    const currentGroupId = groupIdRef.current;
    if (currentGroupId !== null) {
      void loadOutcomeHistory(currentGroupId);
    }
  }, [loadOutcomeHistory]);

  const selectOutcomeSnapshot = useCallback(
    (snapshotDate: string) => {
      setSelectedOutcomeSnapshotId(snapshotDate);
      selectedOutcomeSnapshotIdRef.current = snapshotDate;
      const currentGroupId = groupIdRef.current;
      if (currentGroupId !== null) {
        void loadOutcomeSnapshotDetails(
          currentGroupId,
          snapshotDate,
          modeRef.current
        );
      }
    },
    [loadOutcomeSnapshotDetails]
  );

  useEffect(() => {
    if (!active || routeMode === null || routeMode === modeRef.current) return;

    const groupChanged = previousGroupIdRef.current !== groupId;
    radarRequestSeqRef.current += 1;
    outcomeRequestSeqRef.current += 1;
    const syncTimer = window.setTimeout(() => {
      modeRef.current = routeMode;
      setMode(routeMode);
      clearOutcomeHistory();

      if (!groupChanged && groupId !== null) {
        void load(groupId, { mode: routeMode });
      }
    }, 0);

    return () => window.clearTimeout(syncTimer);
  }, [active, clearOutcomeHistory, groupId, load, routeMode]);

  useEffect(() => {
    if (previousGroupIdRef.current === groupId) return;

    const resetTimer = window.setTimeout(() => {
      previousGroupIdRef.current = groupId;
      reset();
    }, 0);

    return () => window.clearTimeout(resetTimer);
  }, [groupId, reset]);

  useEffect(() => {
    return () => {
      radarRequestSeqRef.current += 1;
      outcomeRequestSeqRef.current += 1;
      outcomeDetailRequestSeqRef.current += 1;
      historyRequestSeqRef.current += 1;
    };
  }, []);

  return {
    state: {
      mode,
      radar,
      loadState,
      outcomeSummary,
      outcomeLoadState,
      outcomeHistory,
      outcomeHistoryOpen,
      outcomeHistoryLoadState,
      outcomeDetailLoadState,
      selectedOutcomeSnapshotId,
    },
    actions: {
      changeMode,
      closeOutcomeHistory,
      load,
      openOutcomeHistory,
      prepareCompanionLoad,
      reloadOutcomeHistory,
      reset,
      selectOutcomeSnapshot,
    },
  };
}

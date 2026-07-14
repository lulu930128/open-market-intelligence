"use client";

import { fetchJson, requestJson } from "@/lib/api";
import { getTaiwanMarketRefreshState } from "@/lib/taiwanMarketTime";
import type {
  WatchlistGroupRadarRead,
  WatchlistRadarMode,
  WatchlistRadarOutcomeSummaryRead,
} from "@/types/market";
import { useCallback, useEffect, useRef, useState } from "react";

export type TaiwanRadarLoadState = "idle" | "loading" | "success" | "error";
export type TaiwanRadarErrorKind = "radar" | "outcome" | "history" | "evaluate";

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

function radarParams(mode: WatchlistRadarMode, useIntraday: boolean) {
  return {
    ...WATCHLIST_ANALYSIS_PARAMS,
    mode,
    max_results: WATCHLIST_RADAR_MAX_RESULTS,
    calculation_limit: 100,
    use_intraday: useIntraday,
    intraday_limit: WATCHLIST_INTRADAY_LIMIT,
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
    useState<WatchlistRadarOutcomeSummaryRead | null>(null);
  const [outcomeLoadState, setOutcomeLoadState] =
    useState<TaiwanRadarLoadState>("idle");
  const [outcomeHistory, setOutcomeHistory] =
    useState<WatchlistRadarOutcomeSummaryRead[]>([]);
  const [outcomeHistoryOpen, setOutcomeHistoryOpen] = useState(false);
  const [outcomeHistoryLoadState, setOutcomeHistoryLoadState] =
    useState<TaiwanRadarLoadState>("idle");
  const [selectedOutcomeSnapshotId, setSelectedOutcomeSnapshotId] =
    useState<number | null>(null);
  const radarRequestSeqRef = useRef(0);
  const outcomeRequestSeqRef = useRef(0);
  const historyRequestSeqRef = useRef(0);
  const modeRef = useRef(mode);
  const groupIdRef = useRef(groupId);
  const onErrorRef = useRef(onError);
  const outcomeSummaryRef = useRef(outcomeSummary);
  const outcomeHistoryRef = useRef(outcomeHistory);
  const previousGroupIdRef = useRef(groupId);

  useEffect(() => {
    groupIdRef.current = groupId;
    onErrorRef.current = onError;
    outcomeSummaryRef.current = outcomeSummary;
    outcomeHistoryRef.current = outcomeHistory;
  }, [groupId, onError, outcomeHistory, outcomeSummary]);

  const clearOutcomeHistory = useCallback(() => {
    historyRequestSeqRef.current += 1;
    setOutcomeHistory([]);
    setOutcomeHistoryLoadState("idle");
    setOutcomeHistoryOpen(false);
    setSelectedOutcomeSnapshotId(null);
  }, []);

  const reset = useCallback(() => {
    radarRequestSeqRef.current += 1;
    outcomeRequestSeqRef.current += 1;
    historyRequestSeqRef.current += 1;
    setRadar(null);
    setLoadState("idle");
    setOutcomeSummary(null);
    setOutcomeLoadState("idle");
    setOutcomeHistory([]);
    setOutcomeHistoryLoadState("idle");
    setOutcomeHistoryOpen(false);
    setSelectedOutcomeSnapshotId(null);
  }, []);

  const loadOutcome = useCallback(
    async (
      currentGroupId: number,
      options?: { mode?: WatchlistRadarMode; silent?: boolean }
    ): Promise<WatchlistRadarOutcomeSummaryRead | null> => {
      const requestSeq = outcomeRequestSeqRef.current + 1;
      outcomeRequestSeqRef.current = requestSeq;
      const currentMode = options?.mode ?? modeRef.current;

      if (!options?.silent) {
        setOutcomeLoadState("loading");
        setOutcomeSummary(null);
      }

      try {
        const outcomeData = await fetchJson<WatchlistRadarOutcomeSummaryRead>(
          `/api/watchlists/groups/${currentGroupId}/radar/outcomes/latest`,
          { mode: currentMode }
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

  const loadOutcomeHistory = useCallback(
    async (
      currentGroupId: number,
      options?: { mode?: WatchlistRadarMode; silent?: boolean }
    ): Promise<WatchlistRadarOutcomeSummaryRead[] | null> => {
      const requestSeq = historyRequestSeqRef.current + 1;
      historyRequestSeqRef.current = requestSeq;
      const currentMode = options?.mode ?? modeRef.current;

      if (!options?.silent) {
        setOutcomeHistoryLoadState("loading");
      }

      try {
        const historyData = await fetchJson<WatchlistRadarOutcomeSummaryRead[]>(
          `/api/watchlists/groups/${currentGroupId}/radar/outcomes/history`,
          { mode: currentMode, limit: 60, item_limit: 12 }
        );

        if (historyRequestSeqRef.current !== requestSeq) return null;

        setOutcomeHistory(historyData);
        setSelectedOutcomeSnapshotId((current) => {
          if (current && historyData.some((row) => row.snapshot?.id === current)) {
            return current;
          }
          return historyData[0]?.snapshot?.id ?? null;
        });
        setOutcomeHistoryLoadState("success");
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
    []
  );

  const load = useCallback(
    async (
      currentGroupId: number,
      options?: {
        mode?: WatchlistRadarMode;
        silent?: boolean;
        useIntraday?: boolean;
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
          radarParams(currentMode, options?.useIntraday ?? shouldUseIntraday()),
          { timeoutMs: WATCHLIST_RADAR_TIMEOUT_MS }
        );

        if (radarRequestSeqRef.current !== requestSeq) return null;

        setRadar(radarData);
        setLoadState("success");
        void loadOutcome(currentGroupId, { mode: currentMode, silent: true });
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
    }: {
      groupId: number;
      silent: boolean;
      useIntraday: boolean;
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

  const evaluateOutcome = useCallback(async (snapshotRunId: number) => {
    const currentGroupId = groupIdRef.current;
    if (currentGroupId === null) return null;

    const currentMode = modeRef.current;
    const requestSeq = outcomeRequestSeqRef.current + 1;
    outcomeRequestSeqRef.current = requestSeq;
    setOutcomeLoadState("loading");

    try {
      const outcomeData = await requestJson<WatchlistRadarOutcomeSummaryRead>(
        `/api/watchlists/groups/${currentGroupId}/radar/outcomes/evaluate`,
        { method: "POST" },
        { mode: currentMode, snapshot_run_id: snapshotRunId }
      );

      if (outcomeRequestSeqRef.current !== requestSeq) return null;

      setOutcomeHistory((current) =>
        current.map((row) =>
          row.snapshot?.id === outcomeData.snapshot?.id ? outcomeData : row
        )
      );
      const latestSnapshotId =
        outcomeHistoryRef.current[0]?.snapshot?.id ??
        outcomeSummaryRef.current?.snapshot?.id ??
        null;
      if (outcomeData.snapshot?.id === latestSnapshotId) {
        setOutcomeSummary(outcomeData);
      }
      setSelectedOutcomeSnapshotId(outcomeData.snapshot?.id ?? snapshotRunId);
      setOutcomeLoadState("success");
      return outcomeData;
    } catch (error) {
      if (outcomeRequestSeqRef.current !== requestSeq) return null;

      setOutcomeLoadState("error");
      onErrorRef.current("evaluate", error, currentGroupId);
      return null;
    }
  }, []);

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
      selectedOutcomeSnapshotId,
    },
    actions: {
      changeMode,
      closeOutcomeHistory,
      evaluateOutcome,
      load,
      openOutcomeHistory,
      prepareCompanionLoad,
      reloadOutcomeHistory,
      reset,
      selectOutcomeSnapshot: setSelectedOutcomeSnapshotId,
    },
  };
}

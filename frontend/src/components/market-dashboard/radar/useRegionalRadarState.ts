"use client";

import { fetchJson } from "@/lib/api";
import { getUsMarketRefreshState } from "@/lib/usMarketTime";
import type {
  WatchlistGroupRadarRead,
  WatchlistRadarMode,
} from "@/types/market";
import { useCallback, useEffect, useRef, useState } from "react";

export type RegionalRadarMarket = "us" | "jp" | "kr";
export type RegionalRadarLoadState = "idle" | "loading" | "success" | "error";

type UseRegionalRadarStateOptions = {
  active: boolean;
  enabled: boolean;
  market: RegionalRadarMarket;
  groupId: number | null;
  initialMode: WatchlistRadarMode;
  routeMode: WatchlistRadarMode | null;
  onError: (error: unknown, groupId: number) => void;
};

const WATCHLIST_RADAR_MAX_RESULTS = 20;
const WATCHLIST_INTRADAY_LIMIT = 30;

function radarPath(market: RegionalRadarMarket, groupId: number) {
  return `/api/${market}-market/watchlists/groups/${groupId}/radar`;
}

function radarParams(market: RegionalRadarMarket, mode: WatchlistRadarMode) {
  return {
    mode,
    max_results: WATCHLIST_RADAR_MAX_RESULTS,
    calculation_limit: 100,
    use_intraday: market === "us" ? getUsMarketRefreshState().isPollingWindow : false,
    intraday_limit: WATCHLIST_INTRADAY_LIMIT,
  };
}

export function useRegionalRadarState({
  active,
  enabled,
  market,
  groupId,
  initialMode,
  routeMode,
  onError,
}: UseRegionalRadarStateOptions) {
  const [mode, setMode] = useState<WatchlistRadarMode>(initialMode);
  const [radar, setRadar] = useState<WatchlistGroupRadarRead | null>(null);
  const [loadState, setLoadState] = useState<RegionalRadarLoadState>("idle");
  const requestSeqRef = useRef(0);
  const modeRef = useRef(mode);
  const groupIdRef = useRef(groupId);
  const enabledRef = useRef(enabled);
  const onErrorRef = useRef(onError);
  const previousGroupIdRef = useRef(groupId);

  useEffect(() => {
    groupIdRef.current = groupId;
    enabledRef.current = enabled;
    onErrorRef.current = onError;
  }, [enabled, groupId, onError]);

  const reset = useCallback(() => {
    requestSeqRef.current += 1;
    setRadar(null);
    setLoadState("idle");
  }, []);

  const load = useCallback(
    async (
      currentGroupId: number,
      options?: { mode?: WatchlistRadarMode; silent?: boolean }
    ): Promise<WatchlistGroupRadarRead | null> => {
      if (!enabledRef.current) {
        reset();
        return null;
      }

      const requestSeq = requestSeqRef.current + 1;
      requestSeqRef.current = requestSeq;
      const currentMode = options?.mode ?? modeRef.current;

      if (!options?.silent) {
        setLoadState("loading");
        setRadar(null);
      }

      try {
        const radarData = await fetchJson<WatchlistGroupRadarRead>(
          radarPath(market, currentGroupId),
          radarParams(market, currentMode)
        );

        if (requestSeqRef.current !== requestSeq) return null;

        setRadar(radarData);
        setLoadState("success");
        return radarData;
      } catch (error) {
        if (requestSeqRef.current !== requestSeq) return null;

        if (!options?.silent) {
          setRadar(null);
        }
        setLoadState("error");
        onErrorRef.current(error, currentGroupId);
        return null;
      }
    },
    [market, reset]
  );

  const changeMode = useCallback(
    (value: WatchlistRadarMode) => {
      requestSeqRef.current += 1;
      modeRef.current = value;
      setMode(value);

      const currentGroupId = groupIdRef.current;
      if (enabledRef.current && currentGroupId !== null) {
        void load(currentGroupId, { mode: value });
      }
    },
    [load]
  );

  const startCompanionLoad = useCallback(
    ({ groupId: currentGroupId, silent }: { groupId: number; silent: boolean }) => {
      if (!enabledRef.current) {
        reset();
        return;
      }
      void load(currentGroupId, { silent });
    },
    [load, reset]
  );

  useEffect(() => {
    if (!active || routeMode === null || routeMode === modeRef.current) return;

    const groupChanged = previousGroupIdRef.current !== groupId;
    requestSeqRef.current += 1;
    const syncTimer = window.setTimeout(() => {
      modeRef.current = routeMode;
      setMode(routeMode);

      if (!groupChanged && enabled && groupId !== null) {
        void load(groupId, { mode: routeMode });
      }
    }, 0);

    return () => window.clearTimeout(syncTimer);
  }, [active, enabled, groupId, load, routeMode]);

  useEffect(() => {
    if (previousGroupIdRef.current === groupId) return;

    const resetTimer = window.setTimeout(() => {
      previousGroupIdRef.current = groupId;
      reset();
    }, 0);

    return () => window.clearTimeout(resetTimer);
  }, [groupId, reset]);

  useEffect(() => {
    if (enabled) return;

    const resetTimer = window.setTimeout(reset, 0);
    return () => window.clearTimeout(resetTimer);
  }, [enabled, reset]);

  useEffect(() => {
    return () => {
      requestSeqRef.current += 1;
    };
  }, []);

  return {
    state: {
      mode,
      radar,
      loadState,
    },
    actions: {
      changeMode,
      load,
      reset,
      startCompanionLoad,
    },
  };
}

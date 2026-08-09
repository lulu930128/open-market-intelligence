"use client";

import { fetchJson } from "@/lib/api";
import { msUntilIsoTime } from "@/lib/marketCalendarStatus";
import { TAIWAN_INTRADAY_REFRESH_MS } from "@/lib/taiwanMarketTime";
import type {
  TaiwanQuoteContractReplayRead,
  TaiwanStockQuoteDepthRead,
} from "@/types/market";
import { useEffect, useRef, useState } from "react";

type QuoteDepthLoadState = "idle" | "loading" | "success" | "error";
type QuoteReplayLoadState = "idle" | "loading" | "success" | "error";

const quoteDepthLivePhases = new Set([
  "preopen_auction",
  "regular_live",
  "closing_auction",
]);

export function quoteDepthRefreshDelayMs(
  quoteDepth: TaiwanStockQuoteDepthRead | null,
  now = new Date()
) {
  const regularDelay = quoteDepth && quoteDepthLivePhases.has(quoteDepth.session_phase)
    ? TAIWAN_INTRADAY_REFRESH_MS
    : 60_000;
  const transitionAt = quoteDepth?.presentation_session_transition_at;
  const transitionAtMs = transitionAt ? Date.parse(transitionAt) : Number.NaN;
  const transitionDelay = msUntilIsoTime(transitionAt, now);

  return Number.isFinite(transitionAtMs) &&
    transitionAtMs > now.getTime() &&
    transitionDelay !== null
    ? Math.min(regularDelay, transitionDelay)
    : regularDelay;
}

export function useTaiwanQuoteDepth({
  enabled,
  stockId,
}: {
  enabled: boolean;
  stockId: string | null;
}) {
  const [quoteDepth, setQuoteDepth] = useState<TaiwanStockQuoteDepthRead | null>(null);
  const [loadState, setLoadState] = useState<QuoteDepthLoadState>("idle");
  const [quoteReplay, setQuoteReplay] =
    useState<TaiwanQuoteContractReplayRead | null>(null);
  const [replayLoadState, setReplayLoadState] =
    useState<QuoteReplayLoadState>("idle");
  const activeStockIdRef = useRef(stockId);

  useEffect(() => {
    activeStockIdRef.current = stockId;
  }, [stockId]);

  useEffect(() => {
    if (!enabled || !stockId) {
      const timer = window.setTimeout(() => {
        setQuoteDepth(null);
        setLoadState("idle");
        setQuoteReplay(null);
        setReplayLoadState("idle");
      }, 0);
      return () => window.clearTimeout(timer);
    }

    let cancelled = false;
    let refreshTimer: number | undefined;
    let requestInFlight = false;
    let latestQuoteDepth: TaiwanStockQuoteDepthRead | null = null;
    const requestedStockId = stockId;

    async function loadReplay() {
      setQuoteReplay(null);
      setReplayLoadState("loading");
      try {
        const replay = await fetchJson<TaiwanQuoteContractReplayRead>(
          `/api/market/quote-depth/${requestedStockId}/replay`
        );
        if (cancelled || activeStockIdRef.current !== requestedStockId) return;
        setQuoteReplay(replay);
        setReplayLoadState("success");
      } catch {
        if (cancelled || activeStockIdRef.current !== requestedStockId) return;
        setQuoteReplay(null);
        setReplayLoadState("error");
      }
    }

    function clearRefreshTimer() {
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
    }

    async function load(showLoading: boolean) {
      if (requestInFlight) return latestQuoteDepth;
      requestInFlight = true;

      if (showLoading) {
        setQuoteDepth(null);
        setLoadState("loading");
      }

      try {
        const depth = await fetchJson<TaiwanStockQuoteDepthRead>(
          `/api/market/quote-depth/${requestedStockId}`,
          { refresh: true }
        );

        if (cancelled || activeStockIdRef.current !== requestedStockId) {
          return latestQuoteDepth;
        }

        latestQuoteDepth = depth;
        setQuoteDepth(depth);
        setLoadState("success");
        return depth;
      } catch {
        if (cancelled || activeStockIdRef.current !== requestedStockId) {
          return latestQuoteDepth;
        }

        setLoadState("error");
        if (latestQuoteDepth === null) setQuoteDepth(null);
        return latestQuoteDepth;
      } finally {
        requestInFlight = false;
      }
    }

    function scheduleRefresh(depth: TaiwanStockQuoteDepthRead | null) {
      if (cancelled) return;
      refreshTimer = window.setTimeout(() => {
        void load(false).then(scheduleRefresh);
      }, quoteDepthRefreshDelayMs(depth));
    }

    void load(true).then(scheduleRefresh);
    void loadReplay();

    return () => {
      cancelled = true;
      clearRefreshTimer();
    };
  }, [enabled, stockId]);

  return {
    quoteDepth,
    quoteReplay,
    loadState,
    replayLoadState,
  };
}

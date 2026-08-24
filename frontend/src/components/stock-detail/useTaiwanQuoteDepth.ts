"use client";

import { buildApiUrl, deleteRequest, fetchJson, requestJson } from "@/lib/api";
import { msUntilIsoTime } from "@/lib/marketCalendarStatus";
import { TAIWAN_INTRADAY_REFRESH_MS } from "@/lib/taiwanMarketTime";
import type {
  TaiwanQuoteContractReplayRead,
  TaiwanRealtimeMarketStreamRead,
  TaiwanRealtimeQuoteLeaseRead,
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
  const [quoteStream, setQuoteStream] =
    useState<TaiwanRealtimeMarketStreamRead | null>(null);
  const [quoteStreamLoadState, setQuoteStreamLoadState] =
    useState<QuoteDepthLoadState>("idle");
  const [replayLoadState, setReplayLoadState] =
    useState<QuoteReplayLoadState>("idle");
  const activeStockIdRef = useRef(stockId);

  useEffect(() => {
    activeStockIdRef.current = stockId;
  }, [stockId]);

  useEffect(() => {
    if (!enabled || !stockId) return;

    let cancelled = false;
    let pageActive = true;
    let leaseId: string | null = null;
    let leaseExpiresInSeconds = 60;
    let heartbeatTimer: number | undefined;
    let lifecycle = Promise.resolve();

    function shouldHoldLease() {
      return !cancelled && pageActive && document.visibilityState === "visible";
    }

    function clearHeartbeat() {
      if (heartbeatTimer !== undefined) {
        window.clearTimeout(heartbeatTimer);
        heartbeatTimer = undefined;
      }
    }

    function scheduleHeartbeat(expiresInSeconds = leaseExpiresInSeconds) {
      clearHeartbeat();
      if (!leaseId || !shouldHoldLease()) return;
      leaseExpiresInSeconds = expiresInSeconds;
      const heartbeatMs = Math.max(
        5_000,
        Math.floor((leaseExpiresInSeconds * 1_000) / 3)
      );
      heartbeatTimer = window.setTimeout(() => {
        void enqueueLifecycle(false, true);
      }, heartbeatMs);
    }

    async function releaseLease(keepalive: boolean) {
      clearHeartbeat();
      const releasingLeaseId = leaseId;
      leaseId = null;
      if (!releasingLeaseId) return true;

      try {
        if (keepalive) {
          await requestJson<void>(
            `/api/market/realtime-quote-leases/${releasingLeaseId}`,
            { method: "DELETE", keepalive: true },
            undefined,
            { timeoutMs: 5_000 }
          );
        } else {
          await deleteRequest(
            `/api/market/realtime-quote-leases/${releasingLeaseId}`,
            undefined,
            { timeoutMs: 5_000 }
          );
        }
        return true;
      } catch {
        // Keep the capability token while visible so a later heartbeat can
        // distinguish a transient release failure from an expired lease.
        if (leaseId === null) {
          leaseId = releasingLeaseId;
        }
        if (shouldHoldLease()) {
          scheduleHeartbeat(15);
        }
        return false;
      }
    }

    async function acquireLease() {
      if (!shouldHoldLease()) return;
      if (leaseId) {
        scheduleHeartbeat(15);
        return;
      }
      try {
        const lease = await requestJson<TaiwanRealtimeQuoteLeaseRead>(
          "/api/market/realtime-quote-leases",
          {
            method: "POST",
            body: JSON.stringify({
              stock_id: stockId,
              owner_kind: "frontend_viewer",
            }),
          }
        );
        if (!lease.lease_id) return;
        if (!shouldHoldLease()) {
          leaseId = lease.lease_id;
          await releaseLease(true);
          return;
        }

        leaseId = lease.lease_id;
        scheduleHeartbeat(lease.expires_in_seconds ?? 60);
      } catch {
        // Quote-depth polling remains on the existing fallback source. The
        // backend contract exposes primary-source status when a lease exists.
      }
    }

    async function heartbeatLease() {
      const activeLeaseId = leaseId;
      if (!activeLeaseId || !shouldHoldLease()) return;
      try {
        const lease = await requestJson<TaiwanRealtimeQuoteLeaseRead>(
          `/api/market/realtime-quote-leases/${activeLeaseId}`,
          { method: "PATCH" },
          undefined,
          { timeoutMs: 5_000 }
        );
        if (leaseId === activeLeaseId) {
          scheduleHeartbeat(lease.expires_in_seconds ?? leaseExpiresInSeconds);
        }
      } catch {
        if (leaseId !== activeLeaseId) return;
        const released = await releaseLease(false);
        if (released && shouldHoldLease()) await acquireLease();
      }
    }

    function enqueueLifecycle(keepalive: boolean, heartbeat = false) {
      lifecycle = lifecycle
        .catch(() => undefined)
        .then(async () => {
          if (!shouldHoldLease()) {
            await releaseLease(keepalive);
          } else if (heartbeat) {
            await heartbeatLease();
          } else {
            await acquireLease();
          }
        });
      return lifecycle;
    }

    function handleVisibilityChange() {
      void enqueueLifecycle(false);
    }

    function handlePageHide() {
      pageActive = false;
      void enqueueLifecycle(true);
    }

    function handlePageShow() {
      pageActive = true;
      void enqueueLifecycle(false);
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", handlePageShow);
    void enqueueLifecycle(false);

    return () => {
      cancelled = true;
      clearHeartbeat();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", handlePageShow);
      void enqueueLifecycle(true);
    };
  }, [enabled, stockId]);

  useEffect(() => {
    if (!enabled || !stockId) {
      const timer = window.setTimeout(() => {
        setQuoteStream(null);
        setQuoteStreamLoadState("idle");
      }, 0);
      return () => window.clearTimeout(timer);
    }

    let cancelled = false;
    let eventSource: EventSource | null = null;
    let fallbackTimer: number | undefined;
    let fallbackRequestInFlight = false;
    const requestedStockId = stockId;
    const initialStateTimer = window.setTimeout(() => {
      if (cancelled) return;
      setQuoteStream(null);
      setQuoteStreamLoadState("loading");
    }, 0);

    function applySnapshot(snapshot: TaiwanRealtimeMarketStreamRead) {
      if (cancelled || activeStockIdRef.current !== requestedStockId) return;
      if (snapshot.stock_id !== requestedStockId) return;
      setQuoteStream(snapshot);
      setQuoteStreamLoadState("success");
    }

    function scheduleFallback(delayMs = 1_000) {
      if (cancelled) return;
      fallbackTimer = window.setTimeout(() => {
        void pollSnapshot();
      }, delayMs);
    }

    async function pollSnapshot() {
      if (cancelled || fallbackRequestInFlight) return;
      if (document.visibilityState !== "visible") {
        scheduleFallback(2_000);
        return;
      }
      fallbackRequestInFlight = true;
      try {
        const snapshot = await fetchJson<TaiwanRealtimeMarketStreamRead>(
          `/api/market/realtime-quotes/${requestedStockId}`
        );
        applySnapshot(snapshot);
      } catch {
        if (!cancelled) setQuoteStreamLoadState("error");
      } finally {
        fallbackRequestInFlight = false;
        scheduleFallback(1_000);
      }
    }

    function startFallbackPolling() {
      eventSource?.close();
      eventSource = null;
      if (fallbackTimer !== undefined) window.clearTimeout(fallbackTimer);
      fallbackTimer = undefined;
      scheduleFallback(0);
    }

    if (typeof EventSource !== "undefined") {
      eventSource = new EventSource(
        buildApiUrl(`/api/market/realtime-quotes/${requestedStockId}/stream`, {
          interval_ms: 500,
        })
      );
      eventSource.addEventListener("snapshot", (event) => {
        try {
          applySnapshot(JSON.parse(event.data) as TaiwanRealtimeMarketStreamRead);
        } catch {
          if (!cancelled) setQuoteStreamLoadState("error");
        }
      });
      eventSource.onerror = () => {
        if (!cancelled) startFallbackPolling();
      };
    } else {
      startFallbackPolling();
    }

    return () => {
      cancelled = true;
      window.clearTimeout(initialStateTimer);
      eventSource?.close();
      if (fallbackTimer !== undefined) window.clearTimeout(fallbackTimer);
    };
  }, [enabled, stockId]);

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

  const currentQuoteDepth =
    stockId !== null && quoteDepth?.stock_id === stockId ? quoteDepth : null;
  const currentQuoteReplay =
    stockId !== null && quoteReplay?.stock_id === stockId ? quoteReplay : null;
  const currentQuoteStream =
    stockId !== null && quoteStream?.stock_id === stockId ? quoteStream : null;
  const scopedLoadState: QuoteDepthLoadState =
    !enabled || !stockId
      ? "idle"
      : currentQuoteDepth
        ? loadState
        : loadState === "error"
          ? "error"
          : "loading";
  const scopedReplayLoadState: QuoteReplayLoadState =
    !enabled || !stockId
      ? "idle"
      : currentQuoteReplay
        ? replayLoadState
        : replayLoadState === "error"
          ? "error"
          : "loading";
  const scopedQuoteStreamLoadState: QuoteDepthLoadState =
    !enabled || !stockId
      ? "idle"
      : currentQuoteStream
        ? quoteStreamLoadState
        : quoteStreamLoadState === "error"
          ? "error"
          : "loading";

  return {
    quoteDepth: currentQuoteDepth,
    quoteReplay: currentQuoteReplay,
    quoteStream: currentQuoteStream,
    loadState: scopedLoadState,
    replayLoadState: scopedReplayLoadState,
    quoteStreamLoadState: scopedQuoteStreamLoadState,
  };
}

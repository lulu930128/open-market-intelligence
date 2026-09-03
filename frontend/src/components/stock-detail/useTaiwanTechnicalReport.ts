"use client";

import type {
  LoadState,
  Timeframe,
} from "@/components/stock-detail/StockDetailDataViews";
import { fetchJson } from "@/lib/api";
import type { StockTechnicalReportRead } from "@/types/market";
import { useEffect, useRef, useState } from "react";

export const TAIWAN_TECHNICAL_REPORT_REFRESH_MS = 60_000;
export const TAIWAN_TECHNICAL_REPORT_INITIAL_DELAY_MS = 1_500;

export function useTaiwanTechnicalReport({
  enabled,
  effectiveTimeframe,
  isIndexProduct,
  stockId,
}: {
  enabled: boolean;
  effectiveTimeframe: Timeframe;
  isIndexProduct: boolean;
  stockId: string | null;
}) {
  const [report, setReport] = useState<StockTechnicalReportRead | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const activeStockIdRef = useRef(stockId);

  useEffect(() => {
    activeStockIdRef.current = stockId;
  }, [stockId]);

  useEffect(() => {
    if (
      !enabled ||
      !stockId ||
      isIndexProduct ||
      !["today", "daily"].includes(effectiveTimeframe)
    ) {
      const resetTimer = window.setTimeout(() => setLoadState("idle"), 0);
      return () => window.clearTimeout(resetTimer);
    }

    let cancelled = false;
    let initialTimer: number | undefined;
    let refreshTimer: number | undefined;
    let requestInFlight = false;
    const requestedStockId = stockId;
    const requestedTimeframe = effectiveTimeframe as "today" | "daily";

    async function loadTechnicalReport() {
      if (requestInFlight) return;
      requestInFlight = true;
      setLoadState("loading");
      try {
        const nextReport = await fetchJson<StockTechnicalReportRead>(
          `/api/market/technical/${requestedStockId}`,
          {
            timeframe: requestedTimeframe,
            include_intraday: true,
            include_volume_pace: false,
          }
        );

        if (cancelled || activeStockIdRef.current !== requestedStockId) return;
        setReport(nextReport);
        setLoadState("success");
      } catch {
        // Keep the last matching cache projection on a transient request failure.
        // The next bounded read will replace it when backend evidence advances.
        if (!cancelled) setLoadState("error");
      } finally {
        requestInFlight = false;
      }
    }

    function scheduleRefresh() {
      if (cancelled) return;
      refreshTimer = window.setTimeout(() => {
        void loadTechnicalReport().finally(scheduleRefresh);
      }, TAIWAN_TECHNICAL_REPORT_REFRESH_MS);
    }

    // The report is an independent secondary surface, but its synchronous
    // backend calculation must not contend with the primary Bars request that
    // owns first-chart paint during a stock switch.
    initialTimer = window.setTimeout(() => {
      initialTimer = undefined;
      void loadTechnicalReport().finally(scheduleRefresh);
    }, TAIWAN_TECHNICAL_REPORT_INITIAL_DELAY_MS);

    return () => {
      cancelled = true;
      if (initialTimer !== undefined) window.clearTimeout(initialTimer);
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
    };
  }, [effectiveTimeframe, enabled, isIndexProduct, stockId]);

  const currentReport =
    report?.stock_id === stockId && report.timeframe === effectiveTimeframe
      ? report
      : null;
  const scopedLoadState: LoadState =
    !enabled || !stockId || isIndexProduct
      ? "idle"
      : currentReport
        ? loadState
        : loadState === "error"
          ? "error"
          : "loading";

  return { loadState: scopedLoadState, report: currentReport };
}

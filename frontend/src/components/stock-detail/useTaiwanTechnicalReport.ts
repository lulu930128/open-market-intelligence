"use client";

import type { Timeframe } from "@/components/stock-detail/StockDetailDataViews";
import { fetchJson } from "@/lib/api";
import type { StockTechnicalReportRead } from "@/types/market";
import { useEffect, useRef, useState } from "react";

export const TAIWAN_TECHNICAL_REPORT_REFRESH_MS = 60_000;

export function useTaiwanTechnicalReport({
  effectiveTimeframe,
  isIndexProduct,
  stockId,
}: {
  effectiveTimeframe: Timeframe;
  isIndexProduct: boolean;
  stockId: string | null;
}) {
  const [report, setReport] = useState<StockTechnicalReportRead | null>(null);
  const activeStockIdRef = useRef(stockId);

  useEffect(() => {
    activeStockIdRef.current = stockId;
  }, [stockId]);

  useEffect(() => {
    if (!stockId || isIndexProduct || !["today", "daily"].includes(effectiveTimeframe)) {
      return;
    }

    let cancelled = false;
    let refreshTimer: number | undefined;
    let requestInFlight = false;
    const requestedStockId = stockId;
    const requestedTimeframe = effectiveTimeframe as "today" | "daily";

    async function loadTechnicalReport() {
      if (requestInFlight) return;
      requestInFlight = true;
      try {
        const nextReport = await fetchJson<StockTechnicalReportRead>(
          `/api/market/technical/${requestedStockId}`,
          {
            timeframe: requestedTimeframe,
            include_intraday: true,
          }
        );

        if (cancelled || activeStockIdRef.current !== requestedStockId) return;
        setReport(nextReport);
      } catch {
        // Keep the last matching cache projection on a transient request failure.
        // The next bounded read will replace it when backend evidence advances.
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

    void loadTechnicalReport().finally(scheduleRefresh);

    return () => {
      cancelled = true;
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
    };
  }, [effectiveTimeframe, isIndexProduct, stockId]);

  return report;
}

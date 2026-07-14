"use client";

import type { Timeframe } from "@/components/stock-detail/StockDetailDataViews";
import { fetchJson } from "@/lib/api";
import type { StockTechnicalReportRead } from "@/types/market";
import { useEffect, useRef, useState } from "react";

export function useTaiwanTechnicalReport({
  effectiveTimeframe,
  isIndexProduct,
  stockId,
  todayUpdatedAt,
}: {
  effectiveTimeframe: Timeframe;
  isIndexProduct: boolean;
  stockId: string | null;
  todayUpdatedAt: string | null;
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
    const requestedStockId = stockId;
    const requestedTimeframe = effectiveTimeframe as "today" | "daily";

    async function loadTechnicalReport() {
      try {
        const nextReport = await fetchJson<StockTechnicalReportRead>(
          `/api/market/technical/${requestedStockId}`,
          {
            timeframe: requestedTimeframe,
            include_intraday: requestedTimeframe === "today",
          }
        );

        if (cancelled || activeStockIdRef.current !== requestedStockId) return;
        setReport(nextReport);
      } catch {
        if (cancelled || activeStockIdRef.current !== requestedStockId) return;
        setReport(null);
      }
    }

    void loadTechnicalReport();

    return () => {
      cancelled = true;
    };
  }, [effectiveTimeframe, isIndexProduct, stockId, todayUpdatedAt]);

  return report;
}

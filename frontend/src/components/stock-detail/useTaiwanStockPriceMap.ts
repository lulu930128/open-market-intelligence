"use client";

import type { LoadState, Timeframe } from "@/components/stock-detail/stockDetailTypes";
import { fetchJson } from "@/lib/api";
import { useTechnicalSettingsRevision } from "@/lib/technicalSettingsRevision";
import type { StockPriceMapRead } from "@/types/market";
import { useEffect, useState } from "react";

export function useTaiwanStockPriceMap({
  candidateClose,
  enabled,
  stockId,
  timeframe = "daily",
}: {
  candidateClose: number | null;
  enabled: boolean;
  stockId: string | null;
  timeframe?: Timeframe;
}) {
  const settingsRevision = useTechnicalSettingsRevision();
  const requestKey = JSON.stringify([stockId, timeframe, candidateClose, settingsRevision]);
  const [result, setResult] = useState<{
    key: string;
    candidateClose: number | null;
    loadState: LoadState;
    map: StockPriceMapRead | null;
    stockId: string;
  } | null>(null);

  useEffect(() => {
    if (!enabled || !stockId) return;

    const controller = new AbortController();
    const requestedStockId = stockId;
    const requestedCandidate = candidateClose;
    const timer = window.setTimeout(async () => {
      setResult(() => ({
        key: requestKey,
        candidateClose: requestedCandidate,
        loadState: "loading",
        map: null,
        stockId: requestedStockId,
      }));
      try {
        const response = await fetchJson<StockPriceMapRead>(
          `/api/market/technical/${encodeURIComponent(requestedStockId)}/price-map`,
          { timeframe, ...(requestedCandidate === null ? {} : { candidate_close: requestedCandidate }) },
          // Period geometry shares the technical report's bounded read budget.
          { signal: controller.signal, timeoutMs: 60_000 }
        );
        if (controller.signal.aborted) return;
        if (
          response.stock_id !== requestedStockId ||
          response.version !== "tw.stock.price_map.v4" || response.requested_timeframe !== timeframe
        ) {
          throw new Error("Price Map contract mismatch");
        }
        setResult({
          key: requestKey,
          candidateClose: requestedCandidate,
          loadState: "success",
          map: response,
          stockId: requestedStockId,
        });
      } catch {
        if (controller.signal.aborted) return;
        setResult(() => ({
          key: requestKey,
          candidateClose: requestedCandidate,
          loadState: "error",
          map: null,
          stockId: requestedStockId,
        }));
      }
    }, requestedCandidate === null ? 0 : 250);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [candidateClose, enabled, stockId, settingsRevision, timeframe, requestKey]);

  if (!enabled || !stockId) {
    return { loadState: "idle" as LoadState, map: null };
  }
  if (result?.key !== requestKey) {
    return { loadState: "loading" as LoadState, map: null };
  }
  return { loadState: result.loadState, map: result.map };
}

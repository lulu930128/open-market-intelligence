"use client";

import type { LoadState } from "@/components/stock-detail/stockDetailTypes";
import { fetchJson } from "@/lib/api";
import type { StockPriceMapRead } from "@/types/market";
import { useEffect, useState } from "react";

export function useTaiwanStockPriceMap({
  candidateClose,
  enabled,
  stockId,
}: {
  candidateClose: number | null;
  enabled: boolean;
  stockId: string | null;
}) {
  const [result, setResult] = useState<{
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
      setResult((current) => ({
        candidateClose: requestedCandidate,
        loadState: "loading",
        map: current?.stockId === requestedStockId ? current.map : null,
        stockId: requestedStockId,
      }));
      try {
        const response = await fetchJson<StockPriceMapRead>(
          `/api/market/technical/${encodeURIComponent(requestedStockId)}/price-map`,
          requestedCandidate === null
            ? undefined
            : { candidate_close: requestedCandidate },
          { signal: controller.signal }
        );
        if (controller.signal.aborted) return;
        if (
          response.stock_id !== requestedStockId ||
          response.version !== "tw.stock.price_map.v3"
        ) {
          throw new Error("Price Map contract mismatch");
        }
        setResult({
          candidateClose: requestedCandidate,
          loadState: "success",
          map: response,
          stockId: requestedStockId,
        });
      } catch {
        if (controller.signal.aborted) return;
        setResult((current) => ({
          candidateClose: requestedCandidate,
          loadState: "error",
          map: current?.stockId === requestedStockId ? current.map : null,
          stockId: requestedStockId,
        }));
      }
    }, requestedCandidate === null ? 0 : 250);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [candidateClose, enabled, stockId]);

  if (!enabled || !stockId) {
    return { loadState: "idle" as LoadState, map: null };
  }
  if (result?.stockId !== stockId || result.candidateClose !== candidateClose) {
    return { loadState: "loading" as LoadState, map: result?.stockId === stockId ? result.map : null };
  }
  return { loadState: result.loadState, map: result.map };
}

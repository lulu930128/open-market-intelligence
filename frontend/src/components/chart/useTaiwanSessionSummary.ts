"use client";

import { useEffect, useState } from "react";
import { fetchJson } from "@/lib/api";
import type { ChartSessionSummary } from "@/types/chartSessionSummary";
export type { SessionMetric } from "@/types/chartSessionSummary";

export type TaiwanSessionSummary = ChartSessionSummary & {
  contract_version: "tw.chart.session_summary.v1";
  trade_date: string;
  presentation_session_state: string | null;
  official_close_status: string | null;
};

export function sessionSummaryMatches(data: TaiwanSessionSummary, stockId: string, tradeDate: string) {
  return data?.contract_version === "tw.chart.session_summary.v1" && data.instrument_id === stockId &&
    data.trade_date === tradeDate && data.base_interval === "1m" && data.metrics != null &&
    ["open", "high", "low", "reference", "average", "volume", "turnover", "last_volume", "previous_volume", "bid", "ask", "range_pct", "relative_volume", "vwap_distance_pct"].every(key => {
      const item = data.metrics[key];
      return item && ["available", "partial", "unavailable"].includes(item.status) &&
        (item.value === null || (typeof item.value === "number" && Number.isFinite(item.value))) &&
        Array.isArray(item.limitations);
    });
}

export function useTaiwanSessionSummary(stockId: string | null, tradeDate: string | null, enabled: boolean) {
  const [state, setState] = useState<{ key: string; data: TaiwanSessionSummary | null; status: "ready" | "error" } | null>(null);
  const key = `${stockId}:${tradeDate}`;
  useEffect(() => {
    if (!enabled || !stockId || !tradeDate) return;
    let cancelled = false;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const data = await fetchJson<TaiwanSessionSummary>(`/api/market/technical/${encodeURIComponent(stockId!)}/session-summary?trade_date=${encodeURIComponent(tradeDate!)}`, undefined, { signal: controller.signal });
        if (!sessionSummaryMatches(data, stockId!, tradeDate!)) throw new Error("SESSION_SUMMARY_IDENTITY_MISMATCH");
        if (!cancelled) setState({ key, data, status: "ready" });
      } catch {
        if (!cancelled) setState({ key, data: null, status: "error" });
      } finally {
        if (!cancelled) timer = setTimeout(read, 15_000);
      }
    }
    void read();
    return () => { cancelled = true; controller.abort(); clearTimeout(timer); };
  }, [enabled, stockId, tradeDate, key]);
  return enabled && state?.key === key ? state : { data: null, status: "loading" as const };
}

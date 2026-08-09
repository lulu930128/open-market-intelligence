"use client";

import type { LoadState } from "@/components/stock-detail/stockDetailTypes";
import { useT } from "@/i18n";
import { fetchJson } from "@/lib/api";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import type { TaiwanNextSessionPlanRead } from "@/types/market";
import { useEffect, useRef, useState } from "react";

export function useTaiwanNextSessionPlan({
  enabled,
  stockId,
  stockName,
}: {
  enabled: boolean;
  stockId: string | null;
  stockName: string | null;
}) {
  const t = useT();
  const [result, setResult] = useState<{
    stockId: string;
    loadState: LoadState;
    plan: TaiwanNextSessionPlanRead | null;
  } | null>(null);
  const stocksWithPublishedIssue = useRef(new Set<string>());

  useEffect(() => {
    if (!enabled || !stockId) {
      return;
    }

    const controller = new AbortController();
    const requestedStockId = stockId;
    const contextKey = `tw:stock:${requestedStockId}`;
    const contextLabel = `${requestedStockId}${stockName ? ` ${stockName}` : ""}`;
    const dedupeKey = `${contextKey}:next-session-plan`;

    async function loadPlan() {
      try {
        const response = await fetchJson<TaiwanNextSessionPlanRead>(
          `/api/market/technical/${encodeURIComponent(requestedStockId)}/next-session-plan`,
          undefined,
          { signal: controller.signal }
        );
        if (controller.signal.aborted) return;
        if (response.stock_id !== requestedStockId) {
          throw new Error(
            t("stockDetail.dataViews.nextSessionPlan.contractMismatch", {
              expected: requestedStockId,
              received: response.stock_id,
            })
          );
        }

        setResult({
          stockId: requestedStockId,
          loadState: "success",
          plan: response,
        });

        if (response.warnings.length || response.warning_codes.length) {
          stocksWithPublishedIssue.current.add(requestedStockId);
          emitDataStatusEvent({
            market: "tw",
            level: "warning",
            title: t("stockDetail.dataViews.nextSessionPlan.warningTitle"),
            message:
              response.warnings.join("；") ||
              response.warning_codes.join("、") ||
              t("stockDetail.dataViews.nextSessionPlan.warningFallback"),
            source: t("stockDetail.dataViews.nextSessionPlan.source"),
            contextKey,
            contextLabel,
            dedupeKey,
          });
        } else if (stocksWithPublishedIssue.current.delete(requestedStockId)) {
          emitDataStatusEvent({
            market: "tw",
            level: "success",
            title: t("stockDetail.dataViews.nextSessionPlan.recoveredTitle"),
            message: t("stockDetail.dataViews.nextSessionPlan.recoveredMessage"),
            source: t("stockDetail.dataViews.nextSessionPlan.source"),
            contextKey,
            contextLabel,
            dedupeKey,
          });
        }
      } catch (error) {
        if (controller.signal.aborted) return;

        setResult({
          stockId: requestedStockId,
          loadState: "error",
          plan: null,
        });
        stocksWithPublishedIssue.current.add(requestedStockId);
        emitDataStatusEvent({
          market: "tw",
          level: "error",
          title: t("stockDetail.dataViews.nextSessionPlan.loadErrorTitle"),
          message:
            error instanceof Error
              ? error.message
              : t("stockDetail.dataViews.nextSessionPlan.loadErrorMessage"),
          source: t("stockDetail.dataViews.nextSessionPlan.source"),
          contextKey,
          contextLabel,
          dedupeKey,
        });
      }
    }

    void loadPlan();
    return () => controller.abort();
  }, [enabled, stockId, stockName, t]);

  if (!enabled || !stockId) {
    return { loadState: "idle" as LoadState, plan: null };
  }
  if (result?.stockId !== stockId) {
    return { loadState: "loading" as LoadState, plan: null };
  }
  return { loadState: result.loadState, plan: result.plan };
}

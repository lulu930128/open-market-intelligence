"use client";

import { useEffect, useMemo, useState } from "react";

import { useT } from "@/i18n";
import { fetchJson } from "@/lib/api";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import type { TaiwanStockEventHistoryRead } from "@/types/market";

type StoredHistory = {
  key: string;
  payload: TaiwanStockEventHistoryRead;
};

export function useTaiwanCorporateEventChartHistory({
  contextKey,
  contextLabel,
  enabled,
  fallback,
  market,
  stockId,
}: {
  contextKey: string;
  contextLabel: string;
  enabled: boolean;
  fallback: TaiwanStockEventHistoryRead | null | undefined;
  market: string | null;
  stockId: string | null;
}) {
  const t = useT();
  const [storedHistory, setStoredHistory] = useState<StoredHistory | null>(null);
  const normalizedMarket = market?.toUpperCase() ?? null;
  const requestKey =
    stockId && (normalizedMarket === "TWSE" || normalizedMarket === "TPEX")
      ? `${normalizedMarket}:${stockId}`
      : null;
  const fallbackMatches = Boolean(fallback && fallback.stock_id === stockId);
  const fallbackComplete = Boolean(
    fallbackMatches && fallback && fallback.result_count >= fallback.total_count
  );
  const loadedPayload = storedHistory?.key === requestKey ? storedHistory.payload : null;
  const payload = loadedPayload ?? (fallbackMatches ? fallback ?? null : null);

  useEffect(() => {
    if (
      !enabled ||
      !requestKey ||
      !stockId ||
      !normalizedMarket ||
      fallbackComplete ||
      loadedPayload
    ) {
      return;
    }

    const controller = new AbortController();
    const query = new URLSearchParams({
      market: normalizedMarket,
      years: "5",
      limit: "200",
    });

    void fetchJson<TaiwanStockEventHistoryRead>(
      `/api/market/tw-corporate-events/history/${encodeURIComponent(stockId)}?${query.toString()}`,
      undefined,
      { signal: controller.signal }
    )
      .then((nextPayload) => {
        setStoredHistory({ key: requestKey, payload: nextPayload });
        emitDataStatusEvent({
          market: "tw",
          level: nextPayload.warning ? "warning" : "success",
          title: nextPayload.warning
            ? t("stockDetail.corporateEvents.chartMarkers.warningTitle")
            : t("stockDetail.corporateEvents.chartMarkers.successTitle"),
          message:
            nextPayload.warning ??
            t("stockDetail.corporateEvents.chartMarkers.successMessage", {
              count: nextPayload.result_count,
              stock: contextLabel,
            }),
          source: t("stockDetail.corporateEvents.chartMarkers.source"),
          contextKey,
          contextLabel,
          dedupeKey: `${contextKey}:corporate-event-chart-history`,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;

        emitDataStatusEvent({
          market: "tw",
          level: "error",
          title: t("stockDetail.corporateEvents.chartMarkers.loadErrorTitle"),
          message:
            error instanceof Error
              ? error.message
              : t("stockDetail.corporateEvents.chartMarkers.loadErrorMessage"),
          source: t("stockDetail.corporateEvents.chartMarkers.source"),
          contextKey,
          contextLabel,
          dedupeKey: `${contextKey}:corporate-event-chart-history`,
        });
      });

    return () => controller.abort();
  }, [
    contextKey,
    contextLabel,
    enabled,
    fallbackComplete,
    loadedPayload,
    normalizedMarket,
    requestKey,
    stockId,
    t,
  ]);

  return useMemo(
    () => ({
      payload,
      events: payload?.results ?? [],
    }),
    [payload]
  );
}

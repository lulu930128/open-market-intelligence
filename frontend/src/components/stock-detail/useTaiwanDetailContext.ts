"use client";

import { fetchJson } from "@/lib/api";
import { useT } from "@/i18n";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import { TAIWAN_MARKET_CHIP_REFRESH_EVENT } from "@/lib/taiwanMarketTime";
import type {
  MarketChipDaily,
  MarketIndexContributionResponse,
  MarketIndexListItem,
  MarketIndexListResponse,
  OvernightImpactRead,
} from "@/types/market";
import { useEffect, useRef, useState } from "react";

type DetailContextLoadState = "idle" | "loading" | "success" | "error";

export function useTaiwanDetailContext({
  indexId,
  indexMarket,
  isIndexProduct,
  overnightEnabled,
  stockId,
}: {
  indexId: string | null;
  indexMarket: string | null;
  isIndexProduct: boolean;
  overnightEnabled: boolean;
  stockId: string | null;
}) {
  const t = useT();
  const [overnightImpact, setOvernightImpact] = useState<OvernightImpactRead | null>(null);
  const [overnightImpactLoadState, setOvernightImpactLoadState] =
    useState<DetailContextLoadState>("idle");
  const [indexList, setIndexList] = useState<MarketIndexListItem[]>([]);
  const [indexListLoadState, setIndexListLoadState] =
    useState<DetailContextLoadState>("idle");
  const [indexContributions, setIndexContributions] =
    useState<MarketIndexContributionResponse | null>(null);
  const [indexContributionLoadState, setIndexContributionLoadState] =
    useState<DetailContextLoadState>("idle");
  const [marketChip, setMarketChip] = useState<MarketChipDaily | null>(null);
  const [marketChipLoadState, setMarketChipLoadState] =
    useState<DetailContextLoadState>("idle");
  const stocksWithPublishedOvernightIssue = useRef(new Set<string>());

  useEffect(() => {
    if (!overnightEnabled || !stockId || isIndexProduct) return;

    const controller = new AbortController();
    const requestedStockId = stockId;
    const contextKey = `tw:stock:${requestedStockId}`;
    const dedupeKey = `${contextKey}:cross-market-context`;

    function publishStatus(
      level: "success" | "warning" | "error",
      title: string,
      message: string,
      contextLabel: string
    ) {
      emitDataStatusEvent({
        market: "tw",
        level,
        title,
        message,
        source: t("stockDetail.dataViews.overnight.source"),
        contextKey,
        contextLabel,
        dedupeKey,
      });
    }

    async function loadOvernightImpact() {
      setOvernightImpact(null);
      setOvernightImpactLoadState("loading");

      try {
        const initial = await fetchJson<OvernightImpactRead | null>(
          `/api/market/overnight-impact/${requestedStockId}`,
          { refresh: false },
          { signal: controller.signal }
        );
        if (controller.signal.aborted) return;

        setOvernightImpact(initial);
        setOvernightImpactLoadState("success");
        if (!initial) return;
        const contextLabel = `${requestedStockId}${
          initial.stock_name ? ` ${initial.stock_name}` : ""
        }`;
        const decision = initial.refresh_decision;
        if (decision?.should_execute || (decision?.cooldown_source_count ?? 0) > 0) {
          stocksWithPublishedOvernightIssue.current.add(requestedStockId);
          publishStatus(
            "warning",
            t("stockDetail.dataViews.overnight.refreshWarningTitle"),
            t("stockDetail.dataViews.overnight.refreshDeferredMessage"),
            contextLabel
          );
        } else if (stocksWithPublishedOvernightIssue.current.delete(requestedStockId)) {
          publishStatus(
            "success",
            t("stockDetail.dataViews.overnight.refreshRecoveredTitle"),
            t("stockDetail.dataViews.overnight.refreshRecoveredMessage"),
            contextLabel
          );
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setOvernightImpact(null);
        setOvernightImpactLoadState("error");
        stocksWithPublishedOvernightIssue.current.add(requestedStockId);
        publishStatus(
          "error",
          t("stockDetail.dataViews.overnight.loadErrorTitle"),
          error instanceof Error
            ? error.message
            : t("stockDetail.dataViews.overnight.loadErrorMessage"),
          requestedStockId
        );
      }
    }

    void loadOvernightImpact();
    return () => controller.abort();
  }, [isIndexProduct, overnightEnabled, stockId, t]);

  useEffect(() => {
    if (!isIndexProduct || !indexMarket) return;

    let cancelled = false;
    const requestedMarket = indexMarket;

    async function loadIndexList() {
      setIndexList([]);
      setIndexListLoadState("loading");

      try {
        const response = await fetchJson<MarketIndexListResponse>(
          "/api/market/indices/list",
          { market: requestedMarket, limit: 80 }
        );
        if (cancelled) return;

        setIndexList(response.items);
        setIndexListLoadState("success");
      } catch {
        if (cancelled) return;
        setIndexList([]);
        setIndexListLoadState("error");
      }
    }

    void loadIndexList();
    return () => {
      cancelled = true;
    };
  }, [indexMarket, isIndexProduct]);

  useEffect(() => {
    if (!isIndexProduct || !indexId) return;

    let cancelled = false;
    const requestedIndexId = indexId;

    async function loadIndexContributions() {
      setIndexContributions(null);
      setIndexContributionLoadState("loading");

      try {
        const response = await fetchJson<MarketIndexContributionResponse>(
          `/api/market/indices/${requestedIndexId}/contributions`,
          { limit: 20 }
        );
        if (cancelled) return;

        setIndexContributions(response);
        setIndexContributionLoadState("success");
      } catch {
        if (cancelled) return;
        setIndexContributions(null);
        setIndexContributionLoadState("error");
      }
    }

    void loadIndexContributions();
    return () => {
      cancelled = true;
    };
  }, [indexId, isIndexProduct]);

  useEffect(() => {
    if (!isIndexProduct || !indexId) return;

    let cancelled = false;
    const requestedIndexId = indexId;

    async function loadMarketChip({ silent = false }: { silent?: boolean } = {}) {
      if (!silent) {
        setMarketChip(null);
        setMarketChipLoadState("loading");
      }

      try {
        const response = await fetchJson<MarketChipDaily>(
          "/api/market/market-chips/latest",
          { index_id: requestedIndexId, ensure_latest: false }
        );
        if (cancelled) return;

        setMarketChip(response);
        setMarketChipLoadState("success");
      } catch {
        if (cancelled) return;
        if (!silent) {
          setMarketChip(null);
          setMarketChipLoadState("error");
        }
      }
    }

    function handleMarketChipRefresh() {
      void loadMarketChip({ silent: true });
    }

    window.addEventListener(
      TAIWAN_MARKET_CHIP_REFRESH_EVENT,
      handleMarketChipRefresh
    );
    void loadMarketChip();
    return () => {
      cancelled = true;
      window.removeEventListener(
        TAIWAN_MARKET_CHIP_REFRESH_EVENT,
        handleMarketChipRefresh
      );
    };
  }, [indexId, isIndexProduct]);

  return {
    indexContributionLoadState,
    indexContributions,
    indexList,
    indexListLoadState,
    marketChip,
    marketChipLoadState,
    overnightImpact,
    overnightImpactLoadState,
  };
}

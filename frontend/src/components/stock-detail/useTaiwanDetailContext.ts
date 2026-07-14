"use client";

import { fetchJson } from "@/lib/api";
import type {
  MarketChipDaily,
  MarketIndexContributionResponse,
  MarketIndexListItem,
  MarketIndexListResponse,
  OvernightImpactRead,
} from "@/types/market";
import { useEffect, useState } from "react";

type DetailContextLoadState = "idle" | "loading" | "success" | "error";

export function useTaiwanDetailContext({
  indexId,
  indexMarket,
  isIndexProduct,
  stockId,
}: {
  indexId: string | null;
  indexMarket: string | null;
  isIndexProduct: boolean;
  stockId: string | null;
}) {
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

  useEffect(() => {
    if (!stockId || isIndexProduct) return;

    let cancelled = false;
    const requestedStockId = stockId;

    async function loadOvernightImpact() {
      setOvernightImpact(null);
      setOvernightImpactLoadState("loading");

      try {
        const response = await fetchJson<OvernightImpactRead>(
          `/api/market/overnight-impact/${requestedStockId}`
        );
        if (cancelled) return;

        setOvernightImpact(response);
        setOvernightImpactLoadState("success");
      } catch {
        if (cancelled) return;
        setOvernightImpact(null);
        setOvernightImpactLoadState("error");
      }
    }

    void loadOvernightImpact();
    return () => {
      cancelled = true;
    };
  }, [isIndexProduct, stockId]);

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

    async function loadMarketChip() {
      setMarketChip(null);
      setMarketChipLoadState("loading");

      try {
        const response = await fetchJson<MarketChipDaily>(
          "/api/market/market-chips/latest",
          { index_id: requestedIndexId, ensure_latest: true }
        );
        if (cancelled) return;

        setMarketChip(response);
        setMarketChipLoadState("success");
      } catch {
        if (cancelled) return;
        setMarketChip(null);
        setMarketChipLoadState("error");
      }
    }

    void loadMarketChip();
    return () => {
      cancelled = true;
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

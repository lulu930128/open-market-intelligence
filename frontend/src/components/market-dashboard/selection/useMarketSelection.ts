"use client";

import {
  buildDashboardHref,
  parseDashboardSearch,
  type DashboardHrefParams,
  type DashboardRoute,
  type MarketRegion,
} from "@/components/market-dashboard/selection/dashboardRoutes";
import {
  applyDashboardRoute,
  createInitialMarketSelection,
  jpStockForSelection as buildJpSelectionStock,
  krStockForSelection as buildKrSelectionStock,
  normalizeSelectionSymbol,
  reconcileJpExplorerSelection,
  reconcileKrExplorerSelection,
  reconcileTaiwanExplorerSelection,
  reconcileUsExplorerSelection,
  resolveInitialGroup as resolveInitialSelectionGroup,
  type InitialMarketSelectionOptions,
  type MarketSelectionState,
} from "@/components/market-dashboard/selection/marketSelectionState";
import { getKrMarketIndexConfig } from "@/lib/krMarketIndices";
import { getUsMarketIndexConfig } from "@/lib/usMarketIndices";
import type { CryptoBaseAsset } from "@/types/cryptoMarket";
import type {
  JPStockMasterRead,
  JPWatchlistGroupNode,
  JPWatchlistItemRead,
  KRStockMasterRead,
  KRWatchlistGroupNode,
  KRWatchlistItemRead,
  TaiwanStockQuoteDepthPreviewMode,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  WatchlistGroupNode,
  WatchlistRadarMode,
} from "@/types/market";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

type UseMarketSelectionOptions = InitialMarketSelectionOptions & {
  radarMode: WatchlistRadarMode;
  quoteDepthPreviewMode: TaiwanStockQuoteDepthPreviewMode | null;
  onHistoryNavigation?: (route: DashboardRoute) => void;
};

export function useMarketSelection(options: UseMarketSelectionOptions) {
  const searchParams = useSearchParams();
  const routeOptionsRef = useRef(options);
  const [selection, setSelection] = useState<MarketSelectionState>(() =>
    createInitialMarketSelection(options)
  );

  useEffect(() => {
    routeOptionsRef.current = options;
  }, [options]);

  const dashboardHref = useCallback(
    (params: DashboardHrefParams) =>
      buildDashboardHref(
        options.quoteDepthPreviewMode &&
          (params.market === "tw" || (!params.market && selection.activeMarket === "tw"))
          ? { ...params, quoteDepthPreviewMode: options.quoteDepthPreviewMode }
          : params
      ),
    [options.quoteDepthPreviewMode, selection.activeMarket]
  );

  const pushDashboardUrl = useCallback(
    (params: DashboardHrefParams) => {
      if (typeof window === "undefined") return;

      const href = dashboardHref(params);
      const currentHref = `${window.location.pathname}${window.location.search}`;
      if (currentHref === href) return;

      window.history.pushState(null, "", href);
    },
    [dashboardHref]
  );

  const routeSearch = searchParams.toString();
  useEffect(() => {
    const currentOptions = routeOptionsRef.current;
    const route = parseDashboardSearch(routeSearch);
    setSelection((current) => applyDashboardRoute(current, route, currentOptions));
    currentOptions.onHistoryNavigation?.(route);
  }, [routeSearch]);

  const changeMarket = useCallback(
    (market: MarketRegion) => {
      const usGroup =
        selection.us.group ??
        resolveInitialSelectionGroup(options.usTree, selection.us.groupId);
      const jpGroup =
        selection.jp.group ??
        resolveInitialSelectionGroup(options.jpTree, selection.jp.groupId);
      const krGroup =
        selection.kr.group ??
        resolveInitialSelectionGroup(options.krTree, selection.kr.groupId);

      setSelection((current) => ({
        ...current,
        activeMarket: market,
        taiwan:
          market === "tw" ? current.taiwan : { ...current.taiwan, futuresSymbol: null },
        us:
          market === "us"
            ? {
                ...current.us,
                group: usGroup,
                groupId: usGroup?.id ?? null,
                groupName: usGroup?.group_name ?? null,
              }
            : current.us,
        jp:
          market === "jp"
            ? {
                ...current.jp,
                group: jpGroup,
                groupId: jpGroup?.id ?? null,
                groupName: jpGroup?.group_name ?? null,
              }
            : current.jp,
        kr:
          market === "kr"
            ? {
                ...current.kr,
                group: krGroup,
                groupId: krGroup?.id ?? null,
                groupName: krGroup?.group_name ?? null,
              }
            : current.kr,
      }));

      if (market === "tw") {
        if (selection.taiwan.futuresSymbol) {
          pushDashboardUrl({ market: "tw", futuresSymbol: selection.taiwan.futuresSymbol });
        } else {
          pushDashboardUrl({
            market: "tw",
            groupId: selection.taiwan.groupId,
            stockId: selection.taiwan.stockId,
            radarMode: options.radarMode,
          });
        }
      } else if (market === "us") {
        pushDashboardUrl({
          market: "us",
          groupId: usGroup?.id ?? null,
          symbol: selection.us.symbol,
        });
      } else if (market === "jp") {
        pushDashboardUrl({
          market: "jp",
          groupId: jpGroup?.id ?? null,
          jpSymbol: selection.jp.symbol,
        });
      } else if (market === "kr") {
        pushDashboardUrl({
          market: "kr",
          groupId: krGroup?.id ?? null,
          krSymbol: selection.kr.symbol,
        });
      } else {
        pushDashboardUrl({ market: "crypto" });
      }
    },
    [options.jpTree, options.krTree, options.radarMode, options.usTree, pushDashboardUrl, selection]
  );

  const selectTaiwanGroup = useCallback(
    (group: WatchlistGroupNode | null, radarMode: WatchlistRadarMode) => {
      setSelection((current) => ({
        ...current,
        taiwan: {
          groupId: group?.id ?? null,
          group,
          stockId: group ? null : current.taiwan.stockId,
          stockName: group ? null : current.taiwan.stockName,
          futuresSymbol: null,
        },
      }));
      pushDashboardUrl(
        group ? { market: "tw", groupId: group.id, radarMode } : { market: "tw" }
      );
    },
    [pushDashboardUrl]
  );

  const selectTaiwanStock = useCallback(
    (stockId: string, stockName: string | null, radarMode: WatchlistRadarMode) => {
      const normalizedStockId = stockId.trim();
      if (!normalizedStockId) return;

      setSelection((current) => ({
        ...current,
        taiwan: {
          ...current.taiwan,
          stockId: normalizedStockId,
          stockName,
          futuresSymbol: null,
        },
      }));
      pushDashboardUrl({
        market: "tw",
        groupId: selection.taiwan.groupId,
        stockId: normalizedStockId,
        radarMode,
      });
    },
    [pushDashboardUrl, selection.taiwan.groupId]
  );

  const selectTaiwanFutures = useCallback(
    (symbol: string) => {
      const normalized = normalizeSelectionSymbol(symbol);
      if (!normalized) return;

      setSelection((current) => ({
        ...current,
        taiwan: {
          ...current.taiwan,
          stockId: null,
          stockName: null,
          futuresSymbol: normalized,
        },
      }));
      pushDashboardUrl({ market: "tw", futuresSymbol: normalized });
    },
    [pushDashboardUrl]
  );

  const selectUsGroup = useCallback(
    (group: USWatchlistGroupNode | null) => {
      setSelection((current) => ({
        ...current,
        us: {
          groupId: group?.id ?? null,
          group,
          groupName: group?.group_name ?? null,
          symbol: null,
          securityName: null,
        },
      }));
      pushDashboardUrl({ market: "us", groupId: group?.id ?? null });
    },
    [pushDashboardUrl]
  );

  const selectUsSymbol = useCallback(
    (symbol: string, securityName: string | null) => {
      const normalized = normalizeSelectionSymbol(symbol);
      if (!normalized) return;

      setSelection((current) => ({
        ...current,
        us: {
          ...current.us,
          symbol: normalized,
          securityName: getUsMarketIndexConfig(normalized)?.name ?? securityName,
        },
      }));
      pushDashboardUrl({ market: "us", symbol: normalized });
    },
    [pushDashboardUrl]
  );

  const selectJpGroup = useCallback(
    (group: JPWatchlistGroupNode | null) => {
      setSelection((current) => ({
        ...current,
        jp: {
          groupId: group?.id ?? null,
          group,
          groupName: group?.group_name ?? null,
          symbol: null,
          stock: null,
        },
      }));
      pushDashboardUrl({ market: "jp", groupId: group?.id ?? null });
    },
    [pushDashboardUrl]
  );

  const selectJpSymbol = useCallback(
    (symbol: string, securityName: string | null) => {
      const normalized = normalizeSelectionSymbol(symbol);
      if (!normalized) return;

      setSelection((current) => ({
        ...current,
        jp: {
          ...current.jp,
          symbol: normalized,
          stock: buildJpSelectionStock(normalized, securityName, current.jp.stock),
        },
      }));
      pushDashboardUrl({
        market: "jp",
        groupId: selection.jp.groupId,
        jpSymbol: normalized,
      });
    },
    [pushDashboardUrl, selection.jp.groupId]
  );

  const selectJpStock = useCallback(
    (stock: JPStockMasterRead | null) => {
      if (!stock) return;

      setSelection((current) =>
        current.jp.symbol === stock.symbol
          ? { ...current, jp: { ...current.jp, stock } }
          : current
      );
    },
    []
  );

  const selectKrGroup = useCallback(
    (group: KRWatchlistGroupNode | null) => {
      setSelection((current) => ({
        ...current,
        kr: {
          groupId: group?.id ?? null,
          group,
          groupName: group?.group_name ?? null,
          symbol: null,
          stock: null,
        },
      }));
      pushDashboardUrl({ market: "kr", groupId: group?.id ?? null });
    },
    [pushDashboardUrl]
  );

  const selectKrSymbol = useCallback(
    (symbol: string, securityName: string | null) => {
      const normalized = normalizeSelectionSymbol(symbol);
      if (!normalized) return;

      const indexConfig = getKrMarketIndexConfig(normalized);
      const resolvedSymbol = indexConfig?.symbol ?? normalized;
      setSelection((current) => ({
        ...current,
        kr: {
          ...current.kr,
          symbol: resolvedSymbol,
          stock: buildKrSelectionStock(resolvedSymbol, securityName, current.kr.stock),
        },
      }));
      pushDashboardUrl({
        market: "kr",
        groupId: selection.kr.groupId,
        krSymbol: resolvedSymbol,
      });
    },
    [pushDashboardUrl, selection.kr.groupId]
  );

  const selectKrStock = useCallback(
    (stock: KRStockMasterRead | null) => {
      if (!stock) return;

      setSelection((current) =>
        current.kr.symbol === stock.symbol
          ? { ...current, kr: { ...current.kr, stock } }
          : current
      );
    },
    []
  );

  const selectCryptoInstrument = useCallback(
    (base: CryptoBaseAsset, instrumentKey: string | null) => {
      setSelection((current) => ({
        ...current,
        crypto: { base, instrumentKey, resourceInstrumentKey: null },
      }));
    },
    []
  );

  const selectResourceInstrument = useCallback((resourceInstrumentKey: string | null) => {
    setSelection((current) => ({
      ...current,
      crypto: { ...current.crypto, resourceInstrumentKey },
    }));
  }, []);

  const reconcileTaiwanExplorer = useCallback((tree: WatchlistGroupNode[]) => {
    setSelection((current) => reconcileTaiwanExplorerSelection(current, tree));
  }, []);

  const reconcileUsExplorer = useCallback(
    (tree: USWatchlistGroupNode[], items: USWatchlistItemRead[]) => {
      setSelection((current) => reconcileUsExplorerSelection(current, tree, items));
    },
    []
  );

  const reconcileJpExplorer = useCallback(
    (tree: JPWatchlistGroupNode[], items: JPWatchlistItemRead[]) => {
      setSelection((current) => reconcileJpExplorerSelection(current, tree, items));
    },
    []
  );

  const reconcileKrExplorer = useCallback(
    (tree: KRWatchlistGroupNode[], items: KRWatchlistItemRead[]) => {
      setSelection((current) => reconcileKrExplorerSelection(current, tree, items));
    },
    []
  );

  return {
    activeMarket: selection.activeMarket,
    selectedGroupId: selection.taiwan.groupId,
    selectedGroup: selection.taiwan.group,
    selectedStockId: selection.taiwan.stockId,
    selectedStockName: selection.taiwan.stockName,
    selectedFuturesSymbol: selection.taiwan.futuresSymbol,
    selectedUsGroupId: selection.us.groupId,
    selectedUsGroup: selection.us.group,
    selectedUsGroupName: selection.us.groupName,
    selectedUsSymbol: selection.us.symbol,
    selectedUsSecurityName: selection.us.securityName,
    selectedJpGroupId: selection.jp.groupId,
    selectedJpGroup: selection.jp.group,
    selectedJpGroupName: selection.jp.groupName,
    selectedJpSymbol: selection.jp.symbol,
    selectedJpStock: selection.jp.stock,
    selectedKrGroupId: selection.kr.groupId,
    selectedKrGroup: selection.kr.group,
    selectedKrGroupName: selection.kr.groupName,
    selectedKrSymbol: selection.kr.symbol,
    selectedKrStock: selection.kr.stock,
    selectedCryptoBase: selection.crypto.base,
    selectedCryptoInstrumentKey: selection.crypto.instrumentKey,
    selectedResourceInstrumentKey: selection.crypto.resourceInstrumentKey,
    dashboardHref,
    pushDashboardUrl,
    changeMarket,
    selectTaiwanGroup,
    selectTaiwanStock,
    selectTaiwanFutures,
    selectUsGroup,
    selectUsSymbol,
    selectJpGroup,
    selectJpSymbol,
    selectJpStock,
    selectKrGroup,
    selectKrSymbol,
    selectKrStock,
    selectCryptoInstrument,
    selectResourceInstrument,
    reconcileTaiwanExplorer,
    reconcileUsExplorer,
    reconcileJpExplorer,
    reconcileKrExplorer,
  };
}

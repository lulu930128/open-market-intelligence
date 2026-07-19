"use client";

import SidebarWatchlistExplorer from "@/components/SidebarWatchlistExplorer";
import BackendConnectionBanner from "@/components/BackendConnectionBanner";
import CryptoMarketPanel from "@/components/CryptoMarketPanel";
import JPMarketPanel from "@/components/JPMarketPanel";
import JPMarketSidebar from "@/components/JPMarketSidebar";
import KRMarketPanel from "@/components/KRMarketPanel";
import KRMarketSidebar from "@/components/KRMarketSidebar";
import {
  LoadingDots,
  StateSurface,
} from "@/components/LoadingPlaceholders";
import OmiAskDock from "@/components/OmiAskDock";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import ResourceMarketPanel from "@/components/ResourceMarketPanel";
import StockDetailPanel from "@/components/StockDetailPanel";
import TaiwanFuturesDetailPanel from "@/components/TaiwanFuturesDetailPanel";
import USStockDetailPanel from "@/components/USStockDetailPanel";
import USWatchlistSidebar from "@/components/USWatchlistSidebar";
import WatchlistRadarPanel from "@/components/WatchlistRadarPanel";
import {
  RankingCellSkeleton,
  RankingLoadingRows,
  WatchlistRankingPanel,
  type RankingDisplayRow,
} from "@/components/market-dashboard/WatchlistRankingPanel";
import {
  formatPct,
  formatPrice,
  formatRowTime,
  formatWholeNumber,
  valueTone,
} from "@/components/market-dashboard/dashboardFormatters";
import { buildOmiAskContext } from "@/components/market-dashboard/omi/buildOmiAskContext";
import {
  RankingSparkline,
  USRankingSparkline,
  formatLots,
  formatWatchlistFreshnessLabel,
  rankLabel,
  statusLabel,
  trendClass,
  trendLabel,
} from "@/components/market-dashboard/ranking/rankingPresentation";
import {
  buildJpWatchlistRows,
  buildKrWatchlistRows,
  buildUsWatchlistRows,
  buildWatchlistRows,
  mergeJpWatchlistRows,
  mergeKrWatchlistRows,
  mergeUsWatchlistRows,
  mergeWatchlistRows,
} from "@/components/market-dashboard/watchlistRankingRows";
import {
  useTaiwanRankingState,
  type TaiwanRankBy,
  type TaiwanRankingErrorKind,
} from "@/components/market-dashboard/ranking/useTaiwanRankingState";
import {
  useUsRankingState,
  type UsRankBy,
  type UsRankingErrorKind,
} from "@/components/market-dashboard/ranking/useUsRankingState";
import {
  useJpRankingState,
  type JpRankBy,
  type JpRankingErrorKind,
} from "@/components/market-dashboard/ranking/useJpRankingState";
import {
  useKrRankingState,
  type KrRankBy,
  type KrRankingErrorKind,
} from "@/components/market-dashboard/ranking/useKrRankingState";
import {
  useRegionalRadarState,
  type RegionalRadarMarket,
} from "@/components/market-dashboard/radar/useRegionalRadarState";
import {
  useTaiwanRadarState,
  type TaiwanRadarErrorKind,
} from "@/components/market-dashboard/radar/useTaiwanRadarState";
import { useDashboardRuntime } from "@/components/market-dashboard/runtime/useDashboardRuntime";
import {
  normalizeDashboardRadarMode,
  type MarketRegion,
} from "@/components/market-dashboard/selection/dashboardRoutes";
import { useMarketSelection } from "@/components/market-dashboard/selection/useMarketSelection";
import {
  JPMarketTape,
  KRMarketTape,
  TaiwanMarketTape,
  USMarketTape,
} from "@/components/market-dashboard/tape/MarketTapePanels";
import {
  useTaiwanMarketTapeState,
  type TaiwanMarketTapeErrorKind,
} from "@/components/market-dashboard/tape/useTaiwanMarketTapeState";
import {
  emitDataStatusEvent,
  type DataStatusLevel,
  type DataStatusMarket,
} from "@/lib/dataStatusEvents";
import { useRefreshExecutionSettings } from "@/lib/refreshExecutionSettings";
import { getUsMarketIndexConfig } from "@/lib/usMarketIndices";
import { getJpMarketIndexConfig } from "@/lib/jpMarketIndices";
import { usAssetTypeLabel, useT } from "@/i18n";
import type {
  ChartPoint,
  JPStockMasterRead,
  JPWatchlistGroupNode,
  JPWatchlistItemRead,
  JPWatchlistRankingItemRead,
  KRStockMasterRead,
  KRWatchlistGroupNode,
  KRWatchlistItemRead,
  KRWatchlistRankingItemRead,
  MarketIndexSummary,
  OhlcIntradayOverlay,
  RankingItem,
  RankingResponse,
  StockIndicatorPoint,
  TaiwanStockQuoteDepthPreviewMode,
  USCompanyProfileRead,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  USWatchlistRankingItemRead,
  WatchlistGroupRadarRead,
  WatchlistGroupNode,
  WatchlistItemRead,
  WatchlistRadarMode,
} from "@/types/market";
import type { BackendConnectionIssueCode } from "@/types/runtime";
import { useMemo, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type RankBy = TaiwanRankBy;
type USRankBy = UsRankBy;
type JPRankBy = JpRankBy;
type KRRankBy = KrRankBy;

function regionalRadarRouteMode(mode: WatchlistRadarMode) {
  return mode === "action" ? null : mode;
}

function apiErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

type DashboardDataStatusMarket = Exclude<DataStatusMarket, "all">;

function emitDashboardDataStatus({
  market,
  level = "error",
  title,
  message,
  source,
  contextKey,
  contextLabel,
  dedupeKey,
}: {
  market: DashboardDataStatusMarket;
  level?: DataStatusLevel;
  title: string;
  message: string;
  source: string;
  contextKey?: string;
  contextLabel?: string;
  dedupeKey?: string;
}) {
  emitDataStatusEvent({
    market,
    level,
    title,
    message,
    source,
    contextKey,
    contextLabel,
    dedupeKey:
      dedupeKey ??
      `${market}:${contextKey ?? contextLabel ?? source}:${title}:${level}`,
  });
}

type Props = {
  initialMarket: MarketRegion;
  initialTree: WatchlistGroupNode[];
  initialItems: WatchlistItemRead[];
  initialSelectedGroupId: number | null;
  initialSelectedStockId: string | null;
  initialSelectedStockName: string | null;
  initialSelectedFuturesSymbol: string | null;
  initialSelectedUsSymbol: string | null;
  initialSelectedUsSecurityName: string | null;
  initialSelectedJpSymbol: string | null;
  initialSelectedKrSymbol: string | null;
  initialChartData: ChartPoint[];
  initialChartIntradayOverlay: OhlcIntradayOverlay | null;
  initialIndicatorData: StockIndicatorPoint[];
  initialRankingData: RankingResponse | null;
  initialRadarMode: WatchlistRadarMode;
  initialRadarData: WatchlistGroupRadarRead | null;
  initialMarketIndexSummary: MarketIndexSummary | null;
  initialUsWatchlistTree: USWatchlistGroupNode[];
  initialUsWatchlistItems: USWatchlistItemRead[];
  initialJpWatchlistTree: JPWatchlistGroupNode[];
  initialJpWatchlistItems: JPWatchlistItemRead[];
  initialKrWatchlistTree: KRWatchlistGroupNode[];
  initialKrWatchlistItems: KRWatchlistItemRead[];
  quoteDepthPreviewMode: TaiwanStockQuoteDepthPreviewMode | null;
  initialBackendIssueCount: number;
  initialBackendIssueCode: BackendConnectionIssueCode | null;
  formBackendIssueCode: BackendConnectionIssueCode | null;
};

function isRankingItemPending(row: RankingItem) {
  return row.status === "pending";
}

function isUsRankingItemPending(row: USWatchlistRankingItemRead) {
  return row.status === "pending";
}

function isJpRankingItemPending(row: JPWatchlistRankingItemRead) {
  return row.status === "pending";
}

function isKrRankingItemPending(row: KRWatchlistRankingItemRead) {
  return row.status === "pending";
}

export default function MarketDashboardClient({
  initialMarket,
  initialTree,
  initialItems,
  initialSelectedGroupId,
  initialSelectedStockId,
  initialSelectedStockName,
  initialSelectedFuturesSymbol,
  initialSelectedUsSymbol,
  initialSelectedUsSecurityName,
  initialSelectedJpSymbol,
  initialSelectedKrSymbol,
  initialChartData,
  initialChartIntradayOverlay,
  initialIndicatorData,
  initialRankingData,
  initialRadarMode,
  initialRadarData,
  initialMarketIndexSummary,
  initialUsWatchlistTree,
  initialUsWatchlistItems,
  initialJpWatchlistTree,
  initialJpWatchlistItems,
  initialKrWatchlistTree,
  initialKrWatchlistItems,
  quoteDepthPreviewMode,
  initialBackendIssueCount,
  initialBackendIssueCode,
  formBackendIssueCode,
}: Props) {
  const t = useT();
  const refreshExecutionSettings = useRefreshExecutionSettings();
  const [watchlistTree, setWatchlistTree] = useState<WatchlistGroupNode[]>(initialTree);
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItemRead[]>(initialItems);
  const [usWatchlistTree, setUsWatchlistTree] =
    useState<USWatchlistGroupNode[]>(initialUsWatchlistTree);
  const [usWatchlistItems, setUsWatchlistItems] =
    useState<USWatchlistItemRead[]>(initialUsWatchlistItems);
  const [jpWatchlistTree, setJpWatchlistTree] =
    useState<JPWatchlistGroupNode[]>(initialJpWatchlistTree);
  const [jpWatchlistItems, setJpWatchlistItems] =
    useState<JPWatchlistItemRead[]>(initialJpWatchlistItems);
  const [krWatchlistTree, setKrWatchlistTree] =
    useState<KRWatchlistGroupNode[]>(initialKrWatchlistTree);
  const [krWatchlistItems, setKrWatchlistItems] =
    useState<KRWatchlistItemRead[]>(initialKrWatchlistItems);
  const [twChartFocusMode, setTwChartFocusMode] = useState(false);
  const [usChartFocusMode, setUsChartFocusMode] = useState(false);
  const [jpChartFocusMode, setJpChartFocusMode] = useState(false);
  const [krChartFocusMode, setKrChartFocusMode] = useState(false);
  const [selectedUsCompanyProfile, setSelectedUsCompanyProfile] =
    useState<USCompanyProfileRead | null>(null);
  const marketSelection = useMarketSelection({
    initialMarket,
    initialSelectedGroupId,
    initialSelectedStockId,
    initialSelectedStockName,
    initialSelectedFuturesSymbol,
    initialSelectedUsSymbol,
    initialSelectedUsSecurityName,
    initialSelectedJpSymbol,
    initialSelectedKrSymbol,
    quoteDepthPreviewMode,
    taiwanTree: watchlistTree,
    taiwanItems: watchlistItems,
    usTree: usWatchlistTree,
    usItems: usWatchlistItems,
    jpTree: jpWatchlistTree,
    jpItems: jpWatchlistItems,
    krTree: krWatchlistTree,
    krItems: krWatchlistItems,
    onHistoryNavigation: (route) => {
      if (route.market !== "tw") setTwChartFocusMode(false);
      if (route.market !== "us") setUsChartFocusMode(false);
      if (route.market !== "jp") setJpChartFocusMode(false);
    },
  });
  const {
    dashboardRoute,
    activeMarket,
    selectedGroupId,
    selectedGroup,
    selectedStockId,
    selectedStockName,
    selectedFuturesSymbol,
    selectedUsGroupId,
    selectedUsGroup,
    selectedUsGroupName,
    selectedUsSymbol,
    selectedUsSecurityName,
    selectedJpGroupId,
    selectedJpGroup,
    selectedJpGroupName,
    selectedJpSymbol,
    selectedJpStock,
    selectedKrGroupId,
    selectedKrGroup,
    selectedKrGroupName,
    selectedKrSymbol,
    selectedKrStock,
    selectedCryptoBase,
    selectedCryptoInstrumentKey,
    selectedResourceInstrumentKey,
    dashboardHref,
    pushDashboardUrl,
  } = marketSelection;
  useDashboardRuntime({
    activeMarket,
    selectedResourceInstrumentKey,
  });
  const {
    state: {
      summary: marketIndexSummary,
      loadState: marketIndexLoadState,
    },
    actions: taiwanMarketTapeActions,
  } = useTaiwanMarketTapeState({
    active: activeMarket === "tw",
    initialSummary: initialMarketIndexSummary,
    onError: handleTaiwanMarketTapeError,
  });
  const loadMarketIndices = taiwanMarketTapeActions.load;
  const activeGroupId = selectedGroupId ?? selectedGroup?.id ?? null;
  const twWatchlistContextLabel =
    selectedGroup?.group_name ??
    (activeGroupId !== null ? String(activeGroupId) : t("watchlist.noGroupSelected"));
  const usWatchlistContextLabel =
    selectedUsGroupName ??
    (selectedUsGroupId !== null ? String(selectedUsGroupId) : t("watchlist.noGroupSelected"));
  const jpWatchlistContextLabel =
    selectedJpGroupName ??
    (selectedJpGroupId !== null ? String(selectedJpGroupId) : t("watchlist.noGroupSelected"));
  const krWatchlistContextLabel =
    selectedKrGroupName ??
    (selectedKrGroupId !== null ? String(selectedKrGroupId) : t("watchlist.noGroupSelected"));
  const selectedUsIndexConfig = getUsMarketIndexConfig(selectedUsSymbol);
  const isSelectedUsIndex = selectedUsIndexConfig !== null;
  const selectedJpIndexConfig = getJpMarketIndexConfig(selectedJpSymbol);
  const isSelectedJpIndex = selectedJpIndexConfig !== null;
  const {
    state: {
      mode: radarMode,
      radar,
      loadState: radarLoadState,
      outcomeSummary: radarOutcomeSummary,
      outcomeLoadState: radarOutcomeLoadState,
      outcomeHistory: radarOutcomeHistory,
      outcomeHistoryOpen: radarOutcomeHistoryOpen,
      outcomeHistoryLoadState: radarOutcomeHistoryLoadState,
      selectedOutcomeSnapshotId: selectedRadarOutcomeSnapshotId,
    },
    actions: taiwanRadarActions,
  } = useTaiwanRadarState({
    active: activeMarket === "tw",
    groupId: activeGroupId,
    initialMode: initialRadarMode,
    initialRadar: initialRadarData,
    routeMode:
      dashboardRoute.market === "tw"
        ? normalizeDashboardRadarMode(dashboardRoute.radarMode)
        : null,
    onError: handleTaiwanRadarError,
  });
  const {
    state: {
      mode: usRadarMode,
      radar: usRadar,
      loadState: usRadarLoadState,
    },
    actions: usRadarActions,
  } = useRegionalRadarState({
    active: activeMarket === "us",
    enabled: !isSelectedUsIndex,
    market: "us",
    groupId: selectedUsGroupId,
    initialMode: initialRadarMode,
    routeMode:
      dashboardRoute.market === "us"
        ? normalizeDashboardRadarMode(dashboardRoute.radarMode)
        : null,
    onError: handleUsRadarError,
  });
  const {
    state: {
      mode: jpRadarMode,
      radar: jpRadar,
      loadState: jpRadarLoadState,
    },
    actions: jpRadarActions,
  } = useRegionalRadarState({
    active: activeMarket === "jp",
    enabled: !isSelectedJpIndex,
    market: "jp",
    groupId: selectedJpGroupId,
    initialMode: initialRadarMode,
    routeMode:
      dashboardRoute.market === "jp"
        ? normalizeDashboardRadarMode(dashboardRoute.radarMode)
        : null,
    onError: handleJpRadarError,
  });
  const {
    state: {
      mode: krRadarMode,
      radar: krRadar,
      loadState: krRadarLoadState,
    },
    actions: krRadarActions,
  } = useRegionalRadarState({
    active: activeMarket === "kr",
    enabled: true,
    market: "kr",
    groupId: selectedKrGroupId,
    initialMode: initialRadarMode,
    routeMode:
      dashboardRoute.market === "kr"
        ? normalizeDashboardRadarMode(dashboardRoute.radarMode)
        : null,
    onError: handleKrRadarError,
  });
  const {
    state: {
      rankBy,
      ranking,
      loadState,
      trendPending: rankingTrendPending,
      lastUpdatedAt,
    },
    actions: taiwanRankingActions,
  } = useTaiwanRankingState({
    active: activeMarket === "tw",
    groupId: activeGroupId,
    initialRanking: initialRankingData,
    refreshExecutionSettings,
    prepareCompanionLoad: taiwanRadarActions.prepareCompanionLoad,
    onError: handleTaiwanRankingError,
  });
  const loadDashboard = taiwanRankingActions.load;
  const {
    state: {
      rankBy: usRankBy,
      ranking: usRanking,
      loadState: usLoadState,
      lastUpdatedAt: usLastUpdatedAt,
    },
    actions: usRankingActions,
  } = useUsRankingState({
    active: activeMarket === "us",
    groupId: selectedUsGroupId,
    refreshExecutionSettings,
    startCompanionLoad: usRadarActions.startCompanionLoad,
    onError: handleUsRankingError,
  });
  const loadUsDashboard = usRankingActions.load;
  const {
    state: {
      rankBy: jpRankBy,
      ranking: jpRanking,
      loadState: jpLoadState,
      lastUpdatedAt: jpLastUpdatedAt,
      dataRefreshNonce: jpDataRefreshNonce,
    },
    actions: jpRankingActions,
  } = useJpRankingState({
    active: activeMarket === "jp",
    groupId: selectedJpGroupId,
    refreshExecutionSettings,
    startCompanionLoad: jpRadarActions.startCompanionLoad,
    onError: handleJpRankingError,
  });
  const loadJpDashboard = jpRankingActions.load;
  const {
    state: {
      rankBy: krRankBy,
      ranking: krRanking,
      loadState: krLoadState,
      lastUpdatedAt: krLastUpdatedAt,
      dataRefreshNonce: krDataRefreshNonce,
    },
    actions: krRankingActions,
  } = useKrRankingState({
    active: activeMarket === "kr",
    groupId: selectedKrGroupId,
    refreshExecutionSettings,
    startCompanionLoad: krRadarActions.startCompanionLoad,
    onError: handleKrRankingError,
  });
  const loadKrDashboard = krRankingActions.load;
  const baseRows = useMemo(
    () => buildWatchlistRows(selectedGroup, watchlistItems),
    [selectedGroup, watchlistItems]
  );
  const rows = useMemo(() => {
    if (rankBy === "none" || ranking?.is_current === false) {
      return mergeWatchlistRows(baseRows, ranking);
    }

    return ranking?.results ?? baseRows;
  }, [baseRows, rankBy, ranking]);
  const rankingFreshnessPending = ranking?.is_current === false;
  const displayRows = rows;
  const rankingLoadState: LoadState = loadState;
  const hasPendingDisplayRows = displayRows.some(isRankingItemPending);
  const rankingListLoading =
    displayRows.length === 0 && (rankingLoadState === "loading" || hasPendingDisplayRows);
  const rankingStatusLoading = rankingLoadState === "loading" || hasPendingDisplayRows;
  const loadedRankingCount = ranking?.results.length ?? 0;
  const rankingProgressLabel =
    rankingStatusLoading && baseRows.length > 0
      ? t("dashboard.ranking.loadingCount", {
          loaded: Math.min(loadedRankingCount, baseRows.length),
          total: baseRows.length,
        })
      : t("common.loading");
  const rankingPendingLabel =
    rankingFreshnessPending
      ? formatWatchlistFreshnessLabel(
          t,
          t("dashboard.ranking.twData"),
          ranking?.target_trade_date,
          ranking?.stale_stock_count,
          ranking?.requested_stock_count
        )
      : rankingProgressLabel;
  const summary = useMemo(() => {
    const upCount = displayRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct > 0;
    }).length;
    const downCount = displayRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct < 0;
    }).length;

    return {
      stockCount: baseRows.length,
      upCount,
      downCount,
    };
  }, [baseRows.length, displayRows]);
  const usBaseRows = useMemo(
    () => buildUsWatchlistRows(selectedUsGroup, usWatchlistItems),
    [selectedUsGroup, usWatchlistItems]
  );
  const usRows = useMemo(() => {
    if (usRankBy === "none" || usRanking?.is_current === false) {
      return mergeUsWatchlistRows(usBaseRows, usRanking);
    }

    return usRanking?.results ?? usBaseRows;
  }, [usBaseRows, usRankBy, usRanking]);
  const usRankingFreshnessPending = usRanking?.is_current === false;
  const usVisibleRows = usRows;
  const usRankingLoadState: LoadState = usLoadState;
  const usRankingPendingLabel =
    usRankingFreshnessPending
      ? formatWatchlistFreshnessLabel(
          t,
          t("dashboard.ranking.usData"),
          usRanking?.target_trade_date,
          usRanking?.stale_symbol_count,
          usRanking?.requested_symbol_count
        )
      : t("common.loading");
  const usSummary = useMemo(() => {
    const upCount = usVisibleRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct > 0;
    }).length;
    const downCount = usVisibleRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct < 0;
    }).length;

    return {
      stockCount: usBaseRows.length,
      upCount,
      downCount,
    };
  }, [usBaseRows.length, usVisibleRows]);
  const jpBaseRows = useMemo(
    () => buildJpWatchlistRows(selectedJpGroup, jpWatchlistItems),
    [selectedJpGroup, jpWatchlistItems]
  );
  const jpRows = useMemo(() => {
    if (jpRankBy === "none" || jpRanking?.is_current === false) {
      return mergeJpWatchlistRows(jpBaseRows, jpRanking);
    }

    return jpRanking?.results ?? jpBaseRows;
  }, [jpBaseRows, jpRankBy, jpRanking]);
  const jpRankingFreshnessPending = jpRanking?.is_current === false;
  const jpVisibleRows = jpRows;
  const jpRankingLoadState: LoadState = jpLoadState;
  const jpRankingPendingLabel =
    jpRankingFreshnessPending
      ? formatWatchlistFreshnessLabel(
          t,
          t("dashboard.ranking.jpData"),
          jpRanking?.target_trade_date,
          jpRanking?.stale_symbol_count,
          jpRanking?.requested_symbol_count
        )
      : t("common.loading");
  const jpSummary = useMemo(() => {
    const upCount = jpVisibleRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct > 0;
    }).length;
    const downCount = jpVisibleRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct < 0;
    }).length;

    return {
      stockCount: jpBaseRows.length,
      upCount,
      downCount,
    };
  }, [jpBaseRows.length, jpVisibleRows]);
  const krBaseRows = useMemo(
    () => buildKrWatchlistRows(selectedKrGroup, krWatchlistItems),
    [selectedKrGroup, krWatchlistItems]
  );
  const krRows = useMemo(() => {
    if (krRankBy === "none" || krRanking?.is_current === false) {
      return mergeKrWatchlistRows(krBaseRows, krRanking);
    }

    return krRanking?.results ?? krBaseRows;
  }, [krBaseRows, krRankBy, krRanking]);
  const krRankingFreshnessPending = krRanking?.is_current === false;
  const krVisibleRows = krRows;
  const krRankingLoadState: LoadState = krLoadState;
  const krRankingPendingLabel =
    krRankingFreshnessPending
      ? formatWatchlistFreshnessLabel(
          t,
          t("dashboard.ranking.krData"),
          krRanking?.target_trade_date,
          krRanking?.stale_symbol_count,
          krRanking?.requested_symbol_count
        )
      : t("common.loading");
  const krSummary = useMemo(() => {
    const upCount = krVisibleRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct > 0;
    }).length;
    const downCount = krVisibleRows.filter((row) => {
      return row.change_pct !== null && row.change_pct !== undefined && row.change_pct < 0;
    }).length;

    return {
      stockCount: krBaseRows.length,
      upCount,
      downCount,
    };
  }, [krBaseRows.length, krVisibleRows]);
  const selectedUsContextProfile =
    selectedUsCompanyProfile?.symbol.toUpperCase() === selectedUsSymbol?.toUpperCase()
      ? selectedUsCompanyProfile
      : null;

  function handleTaiwanRadarError(
    kind: TaiwanRadarErrorKind,
    error: unknown,
    groupId: number
  ) {
    const title =
      kind === "radar"
        ? t("radar.loadError")
        : kind === "evaluate"
          ? t("radar.outcome.evaluateError")
          : t("radar.outcome.loadError");
    const source =
      kind === "radar"
        ? t("radar.title")
        : kind === "history"
          ? t("radar.outcome.history")
          : t("radar.outcome.title");
    const contextSuffix =
      kind === "radar"
        ? "radar"
        : kind === "history"
          ? "radar-outcome-history"
          : "radar-outcome";

    emitDashboardDataStatus({
      market: "tw",
      title,
      message: apiErrorMessage(error, title),
      source,
      contextKey: `tw:watchlist:${groupId}:${contextSuffix}`,
      contextLabel: twWatchlistContextLabel,
    });
  }

  function handleRegionalRadarError(
    market: RegionalRadarMarket,
    error: unknown,
    groupId: number,
    contextLabel: string
  ) {
    const title = t("radar.loadError");
    emitDashboardDataStatus({
      market,
      title,
      message: apiErrorMessage(error, title),
      source: t("radar.title"),
      contextKey: `${market}:watchlist:${groupId}:radar`,
      contextLabel,
    });
  }

  function handleUsRadarError(error: unknown, groupId: number) {
    handleRegionalRadarError("us", error, groupId, usWatchlistContextLabel);
  }

  function handleJpRadarError(error: unknown, groupId: number) {
    handleRegionalRadarError("jp", error, groupId, jpWatchlistContextLabel);
  }

  function handleKrRadarError(error: unknown, groupId: number) {
    handleRegionalRadarError("kr", error, groupId, krWatchlistContextLabel);
  }

  function handleTaiwanRankingError(
    kind: TaiwanRankingErrorKind,
    error: unknown,
    groupId: number
  ) {
    const title =
      kind === "ranking"
        ? t("dashboard.ranking.readError")
        : "自選股日線補齊失敗";
    const source =
      kind === "ranking"
        ? t("dashboard.ranking.listTitle")
        : "自選股資料";

    if (kind === "daily-refresh") {
      console.warn("Watchlist daily price refresh failed.", error);
    }

    emitDashboardDataStatus({
      market: "tw",
      title,
      message: apiErrorMessage(error, title),
      source,
      contextKey: `tw:watchlist:${groupId}:${kind}`,
      contextLabel: twWatchlistContextLabel,
    });
  }

  function handleUsRankingError(
    kind: UsRankingErrorKind,
    error: unknown,
    groupId: number
  ) {
    const title =
      kind === "ranking"
        ? t("dashboard.ranking.usReadError")
        : "美股自選日線補齊失敗";
    emitDashboardDataStatus({
      market: "us",
      title,
      message: apiErrorMessage(error, title),
      source: kind === "ranking" ? t("dashboard.ranking.listTitle") : "美股自選資料",
      contextKey: `us:watchlist:${groupId}:${kind}`,
      contextLabel: usWatchlistContextLabel,
    });
  }

  function handleJpRankingError(
    kind: JpRankingErrorKind,
    error: unknown,
    groupId: number
  ) {
    const title =
      kind === "ranking"
        ? t("dashboard.ranking.jpReadError")
        : "日股自選日線補齊失敗";
    emitDashboardDataStatus({
      market: "jp",
      title,
      message: apiErrorMessage(error, title),
      source: kind === "ranking" ? t("dashboard.ranking.listTitle") : "日股自選資料",
      contextKey: `jp:watchlist:${groupId}:${kind}`,
      contextLabel: jpWatchlistContextLabel,
    });
  }

  function handleKrRankingError(
    kind: KrRankingErrorKind,
    error: unknown,
    groupId: number,
  ) {
    const title =
      kind === "ranking"
        ? t("dashboard.ranking.krReadError")
        : "韓股自選日線補齊失敗";
    emitDashboardDataStatus({
      market: "kr",
      title,
      message: apiErrorMessage(error, title),
      source: kind === "ranking" ? t("dashboard.ranking.listTitle") : "韓股自選資料",
      contextKey: `kr:watchlist:${groupId}:${kind}`,
      contextLabel: krWatchlistContextLabel,
    });
  }

  function handleTaiwanMarketTapeError(
    kind: TaiwanMarketTapeErrorKind,
    error: unknown,
    context?: { dateKey: string }
  ) {
    const isSummaryError = kind === "summary";
    const title = isSummaryError ? "市場指數載入失敗" : "大盤資料更新失敗";
    emitDashboardDataStatus({
      market: "tw",
      title,
      message: apiErrorMessage(error, title),
      source: "市場環境",
      contextKey: isSummaryError
        ? "tw:market-index-summary"
        : `tw:market-chip:${context?.dateKey ?? "unknown"}`,
      contextLabel: isSummaryError ? "台股市場環境" : context?.dateKey ?? "-",
    });
  }

  function handleUsMarketTapeError(error: unknown) {
    const title = t("dashboard.marketIndex.usLoadError");
    emitDashboardDataStatus({
      market: "us",
      title,
      message: apiErrorMessage(error, title),
      source: t("dashboard.marketIndex.market"),
      contextKey: "us:market-index-tape",
      contextLabel: t("dashboard.marketIndex.market"),
    });
  }

  function handleJpMarketTapeError(error: unknown) {
    const title = t("dashboard.marketIndex.jpLoadError");
    emitDashboardDataStatus({
      market: "jp",
      title,
      message: apiErrorMessage(error, title),
      source: t("dashboard.marketIndex.market"),
      contextKey: "jp:market-index-tape",
      contextLabel: t("dashboard.marketIndex.market"),
    });
  }

  function handleKrMarketTapeError(error: unknown) {
    const title = t("dashboard.marketIndex.krLoadError");
    emitDashboardDataStatus({
      market: "kr",
      title,
      message: apiErrorMessage(error, title),
      source: t("dashboard.marketIndex.market"),
      contextKey: "kr:market-index-tape",
      contextLabel: t("dashboard.marketIndex.market"),
    });
  }

  function handleMarketChange(market: MarketRegion) {
    setTwChartFocusMode(false);
    setUsChartFocusMode(false);
    setJpChartFocusMode(false);
    const nextRadarMode =
      market === "tw"
        ? radarMode
        : market === "us"
          ? regionalRadarRouteMode(usRadarMode)
          : market === "jp"
            ? regionalRadarRouteMode(jpRadarMode)
            : market === "kr"
              ? regionalRadarRouteMode(krRadarMode)
              : null;
    marketSelection.changeMarket(market, nextRadarMode);
  }

  function resetTaiwanGroupAnalysis() {
    taiwanRankingActions.reset();
    taiwanRadarActions.reset();
  }

  function onTaiwanGroupChange(group: WatchlistGroupNode | null) {
    marketSelection.selectTaiwanGroup(group, radarMode);
    setTwChartFocusMode(false);
    resetTaiwanGroupAnalysis();
  }

  function onTaiwanStockChange(stockId: string, stockName: string | null) {
    marketSelection.selectTaiwanStock(stockId, stockName, radarMode);
  }

  function onTaiwanFuturesChange(symbol: string) {
    marketSelection.selectTaiwanFutures(symbol);
    setTwChartFocusMode(false);
  }

  function onUsGroupChange(group: USWatchlistGroupNode | null) {
    const groupChanged = (group?.id ?? null) !== selectedUsGroupId;

    marketSelection.selectUsGroup(group, regionalRadarRouteMode(usRadarMode));
    if (groupChanged) {
      usRankingActions.reset();
      usRadarActions.reset();
    }
    setUsChartFocusMode(false);
  }

  function onUsSymbolChange(symbol: string, securityName: string | null) {
    marketSelection.selectUsSymbol(
      symbol,
      securityName,
      regionalRadarRouteMode(usRadarMode)
    );
    setUsChartFocusMode(false);
  }

  function onJpGroupChange(group: JPWatchlistGroupNode | null) {
    const groupChanged = (group?.id ?? null) !== selectedJpGroupId;

    marketSelection.selectJpGroup(group, regionalRadarRouteMode(jpRadarMode));
    if (groupChanged) {
      jpRankingActions.reset();
      jpRadarActions.reset();
    }
    setJpChartFocusMode(false);
  }

  function onJpSymbolChange(symbol: string, securityName: string | null) {
    marketSelection.selectJpSymbol(
      symbol,
      securityName,
      regionalRadarRouteMode(jpRadarMode)
    );
    setJpChartFocusMode(false);
  }

  function onJpStockChange(stock: JPStockMasterRead | null) {
    if (!stock || stock.symbol !== selectedJpSymbol) return;

    marketSelection.selectJpStock(stock);
    setJpChartFocusMode(false);
  }

  function onKrGroupChange(group: KRWatchlistGroupNode | null) {
    const groupChanged = (group?.id ?? null) !== selectedKrGroupId;

    marketSelection.selectKrGroup(group, regionalRadarRouteMode(krRadarMode));
    if (groupChanged) {
      krRankingActions.reset();
      krRadarActions.reset();
    }
  }

  function onKrSymbolChange(symbol: string, securityName: string | null) {
    marketSelection.selectKrSymbol(
      symbol,
      securityName,
      regionalRadarRouteMode(krRadarMode)
    );
  }

  function onKrStockChange(stock: KRStockMasterRead | null) {
    if (!stock || stock.symbol !== selectedKrSymbol) return;

    marketSelection.selectKrStock(stock);
  }

  function handleRankByChange(value: RankBy) {
    taiwanRankingActions.changeRankBy(value);
  }

  function handleRadarModeChange(value: WatchlistRadarMode) {
    pushDashboardUrl({
      market: "tw",
      groupId: activeGroupId,
      stockId: selectedStockId,
      radarMode: value,
    });
    taiwanRadarActions.changeMode(value);
  }

  function handleUsRadarModeChange(value: WatchlistRadarMode) {
    pushDashboardUrl({
      market: "us",
      groupId: selectedUsGroupId,
      symbol: selectedUsSymbol,
      radarMode: value,
    });
    usRadarActions.changeMode(value);
  }

  function handleJpRadarModeChange(value: WatchlistRadarMode) {
    pushDashboardUrl({
      market: "jp",
      groupId: selectedJpGroupId,
      jpSymbol: selectedJpSymbol,
      radarMode: value,
    });
    jpRadarActions.changeMode(value);
  }

  function handleKrRadarModeChange(value: WatchlistRadarMode) {
    pushDashboardUrl({
      market: "kr",
      groupId: selectedKrGroupId,
      krSymbol: selectedKrSymbol,
      radarMode: value,
    });
    krRadarActions.changeMode(value);
  }

  function handleUsRankByChange(value: string) {
    usRankingActions.changeRankBy(value as USRankBy);
  }

  function handleJpRankByChange(value: string) {
    jpRankingActions.changeRankBy(value as JPRankBy);
  }

  function handleKrRankByChange(value: string) {
    krRankingActions.changeRankBy(value as KRRankBy);
  }

  function renderRankingRow(row: RankingItem) {
    const selected = row.stock_id === selectedStockId;
    const loading = isRankingItemPending(row);
    const trendLoading = loading || rankingTrendPending;

    return (
      <a
        key={row.stock_id}
        href={dashboardHref({
          market: "tw",
          groupId: activeGroupId,
          stockId: row.stock_id,
        })}
        data-ranking-stock-id={row.stock_id}
        onPointerUp={(event) => {
          if (event.button !== 0) return;
          onTaiwanStockChange(row.stock_id, row.stock_name);
        }}
        onMouseDown={(event) => {
          if (event.button !== 0) return;
          onTaiwanStockChange(row.stock_id, row.stock_name);
        }}
        onClick={(event) => {
          event.preventDefault();
          onTaiwanStockChange(row.stock_id, row.stock_name);
        }}
        className={[
          "omi-ranking-row grid w-full grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] items-center border-t border-omi-border-subtle px-4 py-2 text-left text-sm",
          selected
            ? "omi-ranking-row-selected relative z-10 bg-omi-surface text-omi-text ring-1 ring-omi-market-up-border"
            : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
        ].join(" ")}
      >
        <span className={selected ? "font-semibold text-omi-market-up" : "text-omi-text-muted"}>#{row.rank}</span>
        <span className="min-w-0">
          <span className="block truncate font-semibold">
            {row.stock_id} {row.stock_name ?? ""}
          </span>
          <span className={selected ? "block truncate text-xs font-medium text-omi-text" : "block truncate text-xs text-omi-text-muted"}>
            {loading ? (
              <RankingCellSkeleton className="h-2.5 w-16" />
            ) : (
              formatRowTime(row.time) ?? row.primary_signal_label ?? statusLabel(t, row.status)
            )}
          </span>
        </span>
        <span className="flex justify-center">
          {trendLoading ? (
            <RankingCellSkeleton className="h-5 w-16" />
          ) : (
            <RankingSparkline row={row} selected={selected} />
          )}
        </span>
        <span className="text-right font-semibold">
          {loading ? (
            <RankingCellSkeleton />
          ) : (
            <PriceUpdatePulse
              value={row.close}
              direction={row.change_pct}
              resetKey={`${activeGroupId ?? "all"}:${row.stock_id}`}
              className="justify-end tabular-nums"
            >
              {formatPrice(row.close)}
            </PriceUpdatePulse>
          )}
        </span>
        <span className={`text-right font-semibold ${valueTone(row.change_pct)}`}>
          {loading ? (
            <RankingCellSkeleton className="h-3 w-12" />
          ) : (
            <PriceUpdatePulse
              value={row.change_pct}
              direction={row.change_pct}
              resetKey={`${activeGroupId ?? "all"}:${row.stock_id}`}
              className="justify-end tabular-nums"
            >
              {formatPct(row.change_pct)}
            </PriceUpdatePulse>
          )}
        </span>
        <span className="text-right">
          {loading ? (
            <RankingCellSkeleton className="h-6 w-12" />
          ) : (
            <span
              className={[
                "omi-ranking-trend-chip px-2 py-1 text-xs font-semibold",
                selected
                  ? `omi-ranking-trend-chip-selected ${trendClass(row.change_pct, row.limit_status)}`
                  : trendClass(row.change_pct, row.limit_status),
              ].join(" ")}
            >
              {trendLabel(t, row.change_pct, row.limit_status)}
            </span>
          )}
        </span>
        <span className="text-right">
          {loading ? (
            <RankingCellSkeleton className="h-3 w-16" />
          ) : (
            <PriceUpdatePulse
              value={row.volume}
              direction={null}
              resetKey={`${activeGroupId ?? "all"}:${row.stock_id}`}
              className="justify-end tabular-nums"
            >
              {formatLots(row.volume)}
            </PriceUpdatePulse>
          )}
        </span>
      </a>
    );
  }

  const groupSummaryPanel = (
    <section className="border border-omi-border-subtle bg-omi-surface">
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("dashboard.ranking.selectedGroup")}
          </div>
          <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
            {selectedGroup?.group_name ?? t("dashboard.ranking.selectedGroupPlaceholder")}
          </h2>
          <div className="mt-1 text-sm text-omi-text-muted">
            {rankingStatusLoading
              ? rankingPendingLabel
              : ranking?.is_current === false
              ? rankingPendingLabel
              : lastUpdatedAt
                ? t("dashboard.ranking.updateTime", { time: lastUpdatedAt })
                : ranking?.trade_date
                  ? t("dashboard.ranking.dataDate", { date: ranking.trade_date })
                  : t("dashboard.ranking.selectGroupToLoad")}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={rankBy}
            onChange={(event) => handleRankByChange(event.target.value as RankBy)}
            className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text-muted outline-none focus:border-omi-accent"
          >
            <option value="none">{t("rank.none")}</option>
            <option value="change_pct">{t("rank.changePct")}</option>
            <option value="score">{t("rank.score")}</option>
            <option value="volume">{t("rank.volume")}</option>
          </select>
          <button
            type="button"
            data-testid="watchlist-ranking-reload"
            onClick={() => {
              void loadMarketIndices({ silent: true });
              if (activeGroupId !== null) void loadDashboard(activeGroupId);
            }}
            className="h-9 bg-omi-control px-4 text-sm font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-surface-strong"
            disabled={activeGroupId === null || loadState === "loading"}
          >
            {t("common.reload")}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 border-t border-omi-border-subtle md:grid-cols-4">
        <div className="px-5 py-3">
          <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.stockCount")}</div>
          <div className="mt-1 text-xl font-bold">{summary.stockCount}</div>
        </div>
        <div className="border-l border-omi-border-subtle px-5 py-3">
          <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.upCount")}</div>
          <div className="mt-1 text-xl font-bold text-omi-market-up">
            {rankingListLoading ? (
              <span className="omi-skeleton block h-6 w-8" />
            ) : (
              summary.upCount
            )}
          </div>
        </div>
        <div className="border-l border-omi-border-subtle px-5 py-3">
          <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.downCount")}</div>
          <div className="mt-1 text-xl font-bold text-omi-market-down">
            {rankingListLoading ? (
              <span className="omi-skeleton block h-6 w-8" />
            ) : (
              summary.downCount
            )}
          </div>
        </div>
        <div className="border-l border-omi-border-subtle px-5 py-3">
          <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.sort")}</div>
          <div className="mt-1 text-xl font-bold">
            {rankLabel(t, ranking?.rank_by ?? rankBy)}
          </div>
        </div>
      </div>
    </section>
  );

  const rankingPanel = (
    <div className="space-y-4">
      {groupSummaryPanel}
      <WatchlistRadarPanel
        radar={radar}
        loadState={radarLoadState}
        mode={radarMode}
        selectedStockId={selectedStockId}
        disabled={activeGroupId === null}
        outcomeSummary={radarOutcomeSummary}
        outcomeLoadState={radarOutcomeLoadState}
        outcomeHistory={radarOutcomeHistory}
        outcomeHistoryOpen={radarOutcomeHistoryOpen}
        outcomeHistoryLoadState={radarOutcomeHistoryLoadState}
        selectedOutcomeSnapshotId={selectedRadarOutcomeSnapshotId}
        getModeHref={(nextMode) =>
          dashboardHref({
            market: "tw",
            groupId: activeGroupId,
            stockId: selectedStockId,
            radarMode: nextMode,
          })
        }
        onModeChange={handleRadarModeChange}
        onReload={() => {
          if (activeGroupId !== null) {
            void taiwanRadarActions.load(activeGroupId);
          }
        }}
        onOpenOutcomeHistory={taiwanRadarActions.openOutcomeHistory}
        onCloseOutcomeHistory={taiwanRadarActions.closeOutcomeHistory}
        onReloadOutcomeHistory={taiwanRadarActions.reloadOutcomeHistory}
        onSelectOutcomeSnapshot={taiwanRadarActions.selectOutcomeSnapshot}
        onEvaluateOutcomeSnapshot={(snapshotRunId) => {
          void taiwanRadarActions.evaluateOutcome(snapshotRunId);
        }}
        onSelectStock={onTaiwanStockChange}
      />
      <section className="border border-omi-border-subtle bg-omi-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-omi-border-subtle px-5 py-3">
          <h3 className="text-sm font-bold text-omi-text-strong">{t("dashboard.ranking.listTitle")}</h3>
          {rankingStatusLoading ? (
            <span className="inline-flex items-center gap-2 text-xs text-omi-text-muted">
              {rankingPendingLabel}
              <LoadingDots label={t("dashboard.ranking.loadingWatchlistRanking")} />
            </span>
          ) : (
            <span className="text-xs text-omi-text-muted">
              {rankBy === "none"
                ? t("dashboard.ranking.rowSummaryNormal", { count: displayRows.length })
                : t("dashboard.ranking.rowSummaryRanked", {
                    count: displayRows.length,
                    rankLabel: rankLabel(t, ranking?.rank_by ?? rankBy),
                  })}
            </span>
          )}
        </div>

        <div className="grid grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] bg-omi-surface-subtle px-4 py-2 text-xs font-bold uppercase tracking-wide text-omi-text-muted">
          <span>{t("dashboard.ranking.rank")}</span>
          <span>{t("dashboard.ranking.stock")}</span>
          <span className="text-center">{t("dashboard.ranking.trend")}</span>
          <span className="text-right">{t("dashboard.ranking.close")}</span>
          <span className="text-right">{t("dashboard.ranking.changePct")}</span>
          <span className="text-right">{t("dashboard.ranking.status")}</span>
          <span className="text-right">{t("dashboard.ranking.volumeLots")}</span>
        </div>
        {displayRows.length > 0 ? (
          displayRows.map(renderRankingRow)
        ) : rankingListLoading ? (
          <RankingLoadingRows />
        ) : (
          <div className="border-t border-omi-border-subtle p-3">
            <StateSurface title={t("dashboard.ranking.empty")} tone="empty" compact />
          </div>
        )}
      </section>
    </div>
  );

  const usDisplayRows: RankingDisplayRow[] = usVisibleRows.map((row) => {
    const selected = row.symbol === selectedUsSymbol;
    const loading = isUsRankingItemPending(row);

    return {
      key: `${row.group_id}-${row.symbol}`,
      rank: row.rank,
      symbol: row.symbol,
      name: row.security_name,
      meta: [
        row.time ? formatRowTime(row.time) : row.trade_date?.slice(0, 10),
        row.exchange,
        row.asset_type ? usAssetTypeLabel(t, row.asset_type) : null,
      ]
        .filter(Boolean)
        .join(" · ") || statusLabel(t, row.status),
      visual: (
        <USRankingSparkline row={row} selected={selected} />
      ),
      close: formatPrice(row.close),
      closeValue: row.close,
      change: formatPct(row.change_pct),
      changePct: row.change_pct,
      trend: trendLabel(t, row.change_pct),
      volume: formatWholeNumber(row.volume),
      volumeValue: row.volume,
      selected,
      loading,
      href: dashboardHref({ market: "us", symbol: row.symbol }),
      onSelect: () => onUsSymbolChange(row.symbol, row.security_name),
    };
  });
  const usRankingPanel = (
    <div className="space-y-4">
      {isSelectedUsIndex ? null : (
        <WatchlistRadarPanel
          radar={usRadar}
          loadState={usRadarLoadState}
          mode={usRadarMode}
          selectedStockId={selectedUsSymbol}
          disabled={selectedUsGroupId === null}
          scopeLabel={t("radar.technicalOnly.usScope")}
          notice={t("radar.technicalOnly.notice")}
          getModeHref={(nextMode) =>
            dashboardHref({
              market: "us",
              groupId: selectedUsGroupId,
              symbol: selectedUsSymbol,
              radarMode: nextMode,
            })
          }
          onModeChange={handleUsRadarModeChange}
          onReload={() => {
            if (selectedUsGroupId !== null) {
              void usRadarActions.load(selectedUsGroupId);
            }
          }}
          onSelectStock={onUsSymbolChange}
        />
      )}
      <WatchlistRankingPanel
        groupName={selectedUsGroupName}
        lastUpdatedAt={usLastUpdatedAt}
        statusLabel={
          usRanking?.is_current === false ? usRankingPendingLabel : undefined
        }
        rankBy={usRanking?.rank_by ?? usRankBy}
        rankOptions={[
          { value: "none", label: t("rank.none") },
          { value: "change_pct", label: t("rank.changePct") },
          { value: "volume", label: t("rank.volume") },
          { value: "close", label: t("rank.close") },
        ]}
        onRankByChange={handleUsRankByChange}
        onReload={() => {
          if (selectedUsGroupId !== null) void loadUsDashboard(selectedUsGroupId);
        }}
        reloadDisabled={selectedUsGroupId === null || usLoadState === "loading"}
        loadState={usRankingLoadState}
        loadingLabel={usRankingPendingLabel}
        rows={usDisplayRows}
        summary={usSummary}
        volumeHeader={t("dashboard.ranking.volume")}
        emptyMessage={t("dashboard.ranking.usEmpty")}
      />
    </div>
  );

  const jpDisplayRows: RankingDisplayRow[] = jpVisibleRows.map((row) => {
    const selected = row.symbol === selectedJpSymbol;
    const loading = isJpRankingItemPending(row);

    return {
      key: `${row.group_id}-${row.symbol}`,
      rank: row.rank,
      symbol: row.symbol,
      name: row.security_name,
      meta: [
        row.trade_date?.slice(0, 10),
        row.market_segment,
        row.sector_33_name,
        row.source,
      ]
        .filter(Boolean)
        .join(" · ") || statusLabel(t, row.status),
      visual: (
        <span className="text-center text-xs text-omi-text-subtle">
          -
        </span>
      ),
      close: formatPrice(row.close),
      closeValue: row.close,
      change: formatPct(row.change_pct),
      changePct: row.change_pct,
      trend: trendLabel(t, row.change_pct),
      volume: formatWholeNumber(row.volume),
      volumeValue: row.volume,
      selected,
      loading,
      href: dashboardHref({
        market: "jp",
        groupId: selectedJpGroupId,
        jpSymbol: row.symbol,
      }),
      onSelect: () => onJpSymbolChange(row.symbol, row.security_name),
    };
  });
  const jpRankingPanel = (
    <div className="space-y-4">
      {isSelectedJpIndex ? null : (
        <WatchlistRadarPanel
          radar={jpRadar}
          loadState={jpRadarLoadState}
          mode={jpRadarMode}
          selectedStockId={selectedJpSymbol}
          disabled={selectedJpGroupId === null}
          scopeLabel={t("radar.technicalOnly.jpScope")}
          notice={t("radar.technicalOnly.notice")}
          getModeHref={(nextMode) =>
            dashboardHref({
              market: "jp",
              groupId: selectedJpGroupId,
              jpSymbol: selectedJpSymbol,
              radarMode: nextMode,
            })
          }
          onModeChange={handleJpRadarModeChange}
          onReload={() => {
            if (selectedJpGroupId !== null) {
              void jpRadarActions.load(selectedJpGroupId);
            }
          }}
          onSelectStock={onJpSymbolChange}
        />
      )}
      <WatchlistRankingPanel
        groupName={selectedJpGroupName}
        lastUpdatedAt={jpLastUpdatedAt}
        statusLabel={
          jpRanking?.is_current === false ? jpRankingPendingLabel : undefined
        }
        rankBy={jpRanking?.rank_by ?? jpRankBy}
        rankOptions={[
          { value: "none", label: t("rank.none") },
          { value: "change_pct", label: t("rank.changePct") },
          { value: "volume", label: t("rank.volume") },
          { value: "close", label: t("rank.close") },
        ]}
        onRankByChange={handleJpRankByChange}
        onReload={() => {
          if (selectedJpGroupId !== null) void loadJpDashboard(selectedJpGroupId);
        }}
        reloadDisabled={selectedJpGroupId === null || jpLoadState === "loading"}
        loadState={jpRankingLoadState}
        loadingLabel={jpRankingPendingLabel}
        rows={jpDisplayRows}
        summary={jpSummary}
        volumeHeader={t("dashboard.ranking.volume")}
        emptyMessage={t("dashboard.ranking.jpEmpty")}
      />
    </div>
  );

  const krDisplayRows: RankingDisplayRow[] = krVisibleRows.map((row) => {
    const selected = row.symbol === selectedKrSymbol;
    const loading = isKrRankingItemPending(row);

    return {
      key: `${row.group_id}-${row.symbol}`,
      rank: row.rank,
      symbol: row.symbol,
      name: row.security_name,
      meta:
        [
          row.trade_date?.slice(0, 10),
          row.market_segment,
          row.sector,
          row.source,
        ]
          .filter(Boolean)
          .join(" · ") || statusLabel(t, row.status),
      visual: (
        <span className="text-center text-xs text-omi-text-subtle">
          -
        </span>
      ),
      close: formatPrice(row.close),
      closeValue: row.close,
      change: formatPct(row.change_pct),
      changePct: row.change_pct,
      trend: trendLabel(t, row.change_pct),
      volume: formatWholeNumber(row.volume),
      volumeValue: row.volume,
      selected,
      loading,
      href: dashboardHref({
        market: "kr",
        groupId: selectedKrGroupId,
        krSymbol: row.symbol,
      }),
      onSelect: () => onKrSymbolChange(row.symbol, row.security_name),
    };
  });
  const krRankingPanel = (
    <div className="space-y-4">
      <WatchlistRadarPanel
        radar={krRadar}
        loadState={krRadarLoadState}
        mode={krRadarMode}
        selectedStockId={selectedKrSymbol}
        disabled={selectedKrGroupId === null}
        scopeLabel={t("radar.technicalOnly.krScope")}
        notice={t("radar.technicalOnly.notice")}
        getModeHref={(nextMode) =>
          dashboardHref({
            market: "kr",
            groupId: selectedKrGroupId,
            krSymbol: selectedKrSymbol,
            radarMode: nextMode,
          })
        }
        onModeChange={handleKrRadarModeChange}
        onReload={() => {
          if (selectedKrGroupId !== null) {
            void krRadarActions.load(selectedKrGroupId);
          }
        }}
        onSelectStock={onKrSymbolChange}
      />
      <WatchlistRankingPanel
        groupName={selectedKrGroupName}
        lastUpdatedAt={krLastUpdatedAt}
        statusLabel={
          krRanking?.is_current === false ? krRankingPendingLabel : undefined
        }
        rankBy={krRanking?.rank_by ?? krRankBy}
        rankOptions={[
          { value: "none", label: t("rank.none") },
          { value: "change_pct", label: t("rank.changePct") },
          { value: "volume", label: t("rank.volume") },
          { value: "close", label: t("rank.close") },
        ]}
        onRankByChange={handleKrRankByChange}
        onReload={() => {
          if (selectedKrGroupId !== null) void loadKrDashboard(selectedKrGroupId);
        }}
        reloadDisabled={selectedKrGroupId === null || krLoadState === "loading"}
        loadState={krRankingLoadState}
        loadingLabel={krRankingPendingLabel}
        rows={krDisplayRows}
        summary={krSummary}
        volumeHeader={t("dashboard.ranking.volume")}
        emptyMessage={t("dashboard.ranking.krEmpty")}
      />
    </div>
  );

  const omiAskContext = buildOmiAskContext({
    activeMarket,
    activeGroupId,
    selectedGroupName: selectedGroup?.group_name ?? null,
    selectedStockId,
    selectedStockName,
    selectedFuturesSymbol,
    selectedUsGroupId,
    selectedUsGroupName,
    selectedUsSymbol,
    selectedUsSecurityName,
    selectedJpGroupId,
    selectedJpGroupName,
    selectedJpSymbol,
    selectedJpStock,
    selectedKrGroupId,
    selectedKrGroupName,
    selectedKrSymbol,
    selectedKrStock,
    t,
  });

  return (
    <main className="h-screen overflow-hidden bg-omi-canvas text-omi-text-strong">
      <div className="flex h-full w-full flex-col lg:min-w-[1180px]">
        <BackendConnectionBanner
          initialIssueCount={initialBackendIssueCount}
          initialIssueCode={initialBackendIssueCode}
          formIssueCode={formBackendIssueCode}
        />
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          {activeMarket === "us" ? (
            <USWatchlistSidebar
              initialTree={usWatchlistTree}
              initialItems={usWatchlistItems}
              selectedMarket={activeMarket}
              selectedSymbol={selectedUsSymbol}
              onMarketChange={handleMarketChange}
              onSelectGroup={onUsGroupChange}
              onSelectSymbol={onUsSymbolChange}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setUsWatchlistTree(nextTree);
                setUsWatchlistItems(nextItems);
                marketSelection.reconcileUsExplorer(nextTree, nextItems);
              }}
              onChanged={() => {
                usRadarActions.reset();
                usRankingActions.notifyWatchlistChanged();
              }}
            />
          ) : activeMarket === "jp" ? (
            <JPMarketSidebar
              initialTree={jpWatchlistTree}
              initialItems={jpWatchlistItems}
              selectedMarket={activeMarket}
              selectedGroupId={selectedJpGroupId}
              selectedSymbol={selectedJpSymbol}
              selectedStock={selectedJpStock}
              onMarketChange={handleMarketChange}
              onSelectGroup={onJpGroupChange}
              onSelectSymbol={onJpSymbolChange}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setJpWatchlistTree(nextTree);
                setJpWatchlistItems(nextItems);
                marketSelection.reconcileJpExplorer(nextTree, nextItems);
                jpRadarActions.reset();
                jpRankingActions.notifyDataChanged();
              }}
            />
          ) : activeMarket === "kr" ? (
            <KRMarketSidebar
              initialTree={krWatchlistTree}
              initialItems={krWatchlistItems}
              selectedMarket={activeMarket}
              selectedGroupId={selectedKrGroupId}
              selectedSymbol={selectedKrSymbol}
              selectedStock={selectedKrStock}
              onMarketChange={handleMarketChange}
              onSelectGroup={onKrGroupChange}
              onSelectSymbol={onKrSymbolChange}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setKrWatchlistTree(nextTree);
                setKrWatchlistItems(nextItems);
                marketSelection.reconcileKrExplorer(nextTree, nextItems);
                krRadarActions.reset();
                krRankingActions.notifyDataChanged();
              }}
            />
          ) : (
            <SidebarWatchlistExplorer
              initialTree={watchlistTree}
              initialItems={watchlistItems}
              selectedGroupId={
                activeMarket === "tw" && !selectedFuturesSymbol ? activeGroupId : null
              }
              selectedStockId={activeMarket === "tw" ? selectedStockId : null}
              selectedFuturesSymbol={activeMarket === "tw" ? selectedFuturesSymbol : null}
              selectedMarket={activeMarket}
              selectedCryptoBase={selectedCryptoBase}
              selectedCryptoInstrumentKey={selectedCryptoInstrumentKey}
              selectedResourceInstrumentKey={selectedResourceInstrumentKey}
              onSelectGroup={(group) => {
                if (activeMarket !== "tw") return;
                onTaiwanGroupChange(group);
              }}
              onSelectStock={(stockId, stockName) => {
                if (activeMarket !== "tw") return;
                onTaiwanStockChange(stockId, stockName);
              }}
              onSelectFutures={(symbol) => {
                if (activeMarket !== "tw") return;
                onTaiwanFuturesChange(symbol);
              }}
              onSelectCryptoInstrument={(base, instrumentKey) => {
                marketSelection.selectCryptoInstrument(base, instrumentKey);
              }}
              onSelectResourceInstrument={(instrument) => {
                marketSelection.selectResourceInstrument(instrument.key);
              }}
              onMarketChange={handleMarketChange}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setWatchlistTree(nextTree);
                setWatchlistItems(nextItems);
                marketSelection.reconcileTaiwanExplorer(nextTree);
              }}
              onChanged={(nextGroupId) => {
                if (activeMarket !== "tw") return;

                const groupId = nextGroupId === undefined ? activeGroupId : nextGroupId;
                if (groupId !== null) {
                  void loadDashboard(groupId);
                } else {
                  resetTaiwanGroupAnalysis();
                }
              }}
            />
          )}

          <section className="min-w-0 flex-1 overflow-y-auto p-4">
            {activeMarket === "tw" ? (
              <>
                <div className={twChartFocusMode ? "hidden" : ""}>
                  <TaiwanMarketTape
                    summary={marketIndexSummary}
                    loadState={marketIndexLoadState}
                  />
                </div>

                {selectedFuturesSymbol ? (
                  <TaiwanFuturesDetailPanel
                    marketIndexSummary={marketIndexSummary}
                    onChartFocusModeChange={setTwChartFocusMode}
                    symbol={selectedFuturesSymbol}
                  />
                ) : (
                  <StockDetailPanel
                    stockId={selectedStockId}
                    stockName={selectedStockName}
                    initialChartData={initialChartData}
                    initialChartIntradayOverlay={initialChartIntradayOverlay}
                    initialIndicatorData={initialIndicatorData}
                    watchlistRankingPanel={rankingPanel}
                    marketIndexSummary={marketIndexSummary}
                    onChartFocusModeChange={setTwChartFocusMode}
                    quoteDepthPreviewMode={quoteDepthPreviewMode}
                  />
                )}
              </>
            ) : activeMarket === "us" ? (
              <>
                <div className={usChartFocusMode ? "hidden" : ""}>
                  <USMarketTape
                    selectedSymbol={selectedUsSymbol}
                    selectedSecurityName={selectedUsSecurityName}
                    selectedGroupName={selectedUsGroupName}
                    companyProfile={selectedUsContextProfile}
                    onError={handleUsMarketTapeError}
                  />
                </div>

                <USStockDetailPanel
                  selectedSymbol={selectedUsSymbol}
                  selectedSecurityName={selectedUsSecurityName}
                  watchlistRankingPanel={isSelectedUsIndex ? undefined : usRankingPanel}
                  onCompanyProfileChange={setSelectedUsCompanyProfile}
                  onChartFocusModeChange={setUsChartFocusMode}
                />
              </>
            ) : activeMarket === "jp" ? (
              <>
                <div className={jpChartFocusMode ? "hidden" : ""}>
                  <JPMarketTape
                    selectedSymbol={selectedJpSymbol}
                    selectedStock={selectedJpStock}
                    selectedGroupName={selectedJpGroupName}
                    onError={handleJpMarketTapeError}
                  />
                </div>
                <JPMarketPanel
                  initialSymbol={selectedJpSymbol}
                  refreshNonce={jpDataRefreshNonce}
                  watchlistRankingPanel={isSelectedJpIndex ? undefined : jpRankingPanel}
                  onChartFocusModeChange={setJpChartFocusMode}
                  onSelectStock={onJpStockChange}
                />
              </>
            ) : activeMarket === "kr" ? (
              <>
                <div className={krChartFocusMode ? "hidden" : ""}>
                  <KRMarketTape
                    selectedSymbol={selectedKrSymbol}
                    selectedStock={selectedKrStock}
                    selectedGroupName={selectedKrGroupName}
                    onError={handleKrMarketTapeError}
                  />
                </div>
                <KRMarketPanel
                  initialSymbol={selectedKrSymbol}
                  selectedGroupId={selectedKrGroupId}
                  refreshNonce={krDataRefreshNonce}
                  watchlistRankingPanel={krRankingPanel}
                  onChartFocusModeChange={setKrChartFocusMode}
                  onSelectStock={onKrStockChange}
                />
              </>
            ) : activeMarket === "crypto" && selectedResourceInstrumentKey ? (
              <ResourceMarketPanel selectedInstrumentKey={selectedResourceInstrumentKey} />
            ) : activeMarket === "crypto" ? (
              <CryptoMarketPanel
                selectedBase={selectedCryptoBase}
                selectedInstrumentKey={selectedCryptoInstrumentKey}
              />
            ) : (
              <section className="border border-omi-border-subtle bg-omi-surface px-5 py-10 text-sm text-omi-text-muted">
                {t("dashboard.ranking.notEnabled")}
              </section>
            )}
          </section>
        </div>
      </div>
      {activeMarket !== "crypto" ? <OmiAskDock context={omiAskContext} /> : null}
    </main>
  );
}

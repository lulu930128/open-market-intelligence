"use client";

import SidebarWatchlistExplorer from "@/components/SidebarWatchlistExplorer";
import CryptoMarketPanel from "@/components/CryptoMarketPanel";
import JPMarketPanel from "@/components/JPMarketPanel";
import JPMarketSidebar from "@/components/JPMarketSidebar";
import KRMarketPanel from "@/components/KRMarketPanel";
import KRMarketSidebar from "@/components/KRMarketSidebar";
import {
  LoadingDots,
  StateSurface,
} from "@/components/LoadingPlaceholders";
import OmiAskDock, { type OmiAskDockContext } from "@/components/OmiAskDock";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import ResourceMarketPanel from "@/components/ResourceMarketPanel";
import StockDetailPanel from "@/components/StockDetailPanel";
import TaiwanFuturesDetailPanel from "@/components/TaiwanFuturesDetailPanel";
import USStockDetailPanel from "@/components/USStockDetailPanel";
import USWatchlistSidebar from "@/components/USWatchlistSidebar";
import WatchlistRadarPanel from "@/components/WatchlistRadarPanel";
import { fetchJson, requestJson } from "@/lib/api";
import {
  buildDashboardHref,
  type DashboardHrefParams,
  type MarketRegion,
} from "@/lib/dashboardNavigation";
import {
  emitDataStatusEvent,
  type DataStatusLevel,
  type DataStatusMarket,
} from "@/lib/dataStatusEvents";
import { getJobResultStatus, requestBackfillJob } from "@/lib/jobs";
import {
  MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
  loadMarketDataSubscriptionSettings,
  resourceBackgroundQuoteIntervalSeconds,
  resourceSubscriptionAllowsQuotePolling,
  type MarketDataSubscriptionSettingsRead,
} from "@/lib/marketDataSubscriptions";
import {
  getMarketCalendarStatusSnapshot,
  msUntilIsoTime,
  refreshMarketCalendarStatus,
} from "@/lib/marketCalendarStatus";
import {
  getRefreshExecutionSeconds,
  useRefreshExecutionSettings,
} from "@/lib/refreshExecutionSettings";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  getTaiwanIntradayXRatio,
  getTaiwanMarketChipRefreshState,
  getTaiwanMarketRefreshState,
  isTaiwanRegularSessionPoint,
} from "@/lib/taiwanMarketTime";
import {
  US_INTRADAY_REFRESH_MS,
  getUsIntradayXRatio,
  getUsMarketRefreshState,
  isUsRegularSessionPoint,
} from "@/lib/usMarketTime";
import {
  getUsPrimaryMarketIndexConfig,
  resolveUsContextIndexConfig,
  getUsMarketIndexConfig,
  type USMarketIndexConfig,
} from "@/lib/usMarketIndices";
import {
  getJpMarketIndexConfig,
  getJpPrimaryMarketIndexConfig,
  resolveJpContextIndexConfig,
  type JPMarketIndexConfig,
} from "@/lib/jpMarketIndices";
import {
  getKrMarketIndexConfig,
  getKrPrimaryMarketIndexConfig,
  resolveKrContextIndexConfig,
  type KRMarketIndexConfig,
} from "@/lib/krMarketIndices";
import {
  rankByLabel,
  rowStatusLabel,
  trendDirectionLabel,
  usAssetTypeLabel,
  useT,
  type TranslationFunction,
} from "@/i18n";
import type { CryptoBaseAsset } from "@/types/cryptoMarket";
import {
  resourceSymbolFromKey,
  type ResourceRefreshResult,
} from "@/types/resourceMarket";
import type {
  ChartPoint,
  IntradayTrendResponse,
  JPStockMasterRead,
  JPOhlcChartRead,
  JPWatchlistGroupNode,
  JPWatchlistItemRead,
  JPWatchlistRankingItemRead,
  JPWatchlistRankingRead,
  KRIndexOhlcChartRead,
  KRMarketBreadthRead,
  KRStockMasterRead,
  KRWatchlistGroupNode,
  KRWatchlistItemRead,
  KRWatchlistRankingItemRead,
  KRWatchlistRankingRead,
  MarketIndexSnapshot,
  MarketIndexSummary,
  OhlcIntradayOverlay,
  RankingBatchResponse,
  RankingItem,
  RankingResponse,
  StockIndicatorPoint,
  TaiwanStockQuoteDepthPreviewMode,
  USCompanyProfileRead,
  USOhlcChartRead,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  USWatchlistRankingItemRead,
  USWatchlistRankingRead,
  WatchlistGroupRadarRead,
  WatchlistGroupNode,
  WatchlistItemRead,
  WatchlistRadarMode,
  WatchlistRadarOutcomeSummaryRead,
  WatchlistRadarSnapshotRead,
} from "@/types/market";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type JPStatusMessage = { type: "success" | "warning" | "error"; text: string } | null;
type RankBy = "none" | "change_pct" | "score" | "volume";
type USRankBy = "none" | "change_pct" | "volume" | "close";
type JPRankBy = "none" | "change_pct" | "volume" | "close";
type KRRankBy = "none" | "change_pct" | "volume" | "close";
const WATCHLIST_INTRADAY_LIMIT = 30;
const WATCHLIST_RADAR_MAX_RESULTS = 20;
const WATCHLIST_RANKING_BATCH_SIZE = 3;
const WATCHLIST_DAILY_RELEASE_CHECK_MIN_MS = 5_000;
const WATCHLIST_DAILY_RELEASE_CHECK_MAX_MS = 300_000;
const MARKET_CHIP_REFRESH_STORAGE_PREFIX = "omi:market-chip-refresh";
const TAIWAN_INDEX_TARGET_IDS = new Set(["TAIEX", "TPEX"]);
const WATCHLIST_ANALYSIS_PARAMS = {
  include_children: true,
  enabled_only: true,
  ma_windows: "5,20,60",
  volume_ma_windows: "5,20",
  volume_ratio_threshold: 1.5,
};
type RankingDisplayRow = {
  key: string;
  rank: number;
  symbol: string;
  name: string | null;
  meta: string | null;
  visual: ReactNode;
  close: string;
  closeValue: number | null | undefined;
  change: string;
  changePct: number | null | undefined;
  trend: string;
  volume: string;
  volumeValue: number | null | undefined;
  selected: boolean;
  loading?: boolean;
  href?: string;
  onSelect: () => void;
};
type TaiwanMarketRefreshState = ReturnType<typeof getTaiwanMarketRefreshState>;

function shouldUseTaiwanWatchlistIntraday(marketState: TaiwanMarketRefreshState) {
  return (
    marketState.isPollingWindow ||
    (marketState.isAfterClose && !marketState.isDailyPriceReleased)
  );
}

function getTaiwanWatchlistDailyReleaseCheckDelay() {
  const marketState = getTaiwanMarketRefreshState();
  const dailyRelease =
    getMarketCalendarStatusSnapshot("tw")?.release_windows.market_daily_price;
  const releaseDelay = marketState.isDailyPriceReleased
    ? msUntilIsoTime(dailyRelease?.next_release_at)
    : msUntilIsoTime(dailyRelease?.release_at);
  const fallbackDelay = marketState.isDailyPriceReleased
    ? marketState.msUntilNextPollingStart
    : 60_000;
  const delay = releaseDelay ?? fallbackDelay;

  return Math.min(
    Math.max(delay, WATCHLIST_DAILY_RELEASE_CHECK_MIN_MS),
    WATCHLIST_DAILY_RELEASE_CHECK_MAX_MS
  );
}

function marketChipRefreshStorageKey(dateKey: string) {
  return `${MARKET_CHIP_REFRESH_STORAGE_PREFIX}:${dateKey}`;
}

function isStoredMarketChipRefreshDone(dateKey: string) {
  try {
    return window.localStorage.getItem(marketChipRefreshStorageKey(dateKey)) === "done";
  } catch {
    return false;
  }
}

function markStoredMarketChipRefreshDone(dateKey: string) {
  try {
    window.localStorage.setItem(marketChipRefreshStorageKey(dateKey), "done");
  } catch {
    // Ignore storage failures; job dedupe still prevents active duplicates.
  }
}

type ResourceBackgroundPollingGroup = {
  intervalSeconds: number;
  symbols: string[];
  key: string;
};

function resourceBackgroundQuotePollingGroups(
  settings: MarketDataSubscriptionSettingsRead | null,
  selectedResourceInstrumentKey: string | null
) {
  if (!settings) return [];

  const groups = new Map<number, Set<string>>();
  for (const item of settings.items) {
    if (!resourceSubscriptionAllowsQuotePolling(item)) continue;
    if (item.key === selectedResourceInstrumentKey) continue;

    const symbol = resourceSymbolFromKey(item.key);
    if (!symbol) continue;

    const intervalSeconds = resourceBackgroundQuoteIntervalSeconds(item);
    if (!groups.has(intervalSeconds)) {
      groups.set(intervalSeconds, new Set());
    }
    groups.get(intervalSeconds)?.add(symbol);
  }

  return Array.from(groups.entries())
    .map<ResourceBackgroundPollingGroup>(([intervalSeconds, symbols]) => ({
      intervalSeconds,
      symbols: Array.from(symbols).sort(),
      key: `${intervalSeconds}:${Array.from(symbols).sort().join(",")}`,
    }))
    .sort((left, right) => left.intervalSeconds - right.intervalSeconds);
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

type RankingPanelOption = {
  value: string;
  label: string;
};

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
};

function RankingLoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="omi-loading-surface border-t border-omi-border-subtle" aria-hidden="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="omi-ranking-loading-row grid w-full grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] items-center border-t border-omi-border-subtle px-4 py-2 text-sm first:border-t-0"
        >
          <div className="omi-skeleton h-3 w-7" />
          <div className="min-w-0 space-y-2">
            <div className="omi-skeleton h-3 w-28" />
            <div className="omi-skeleton h-2.5 w-16" />
          </div>
          <div className="mx-auto h-6 w-16">
            <div className="omi-skeleton h-full w-full" />
          </div>
          <div className="ml-auto omi-skeleton h-3 w-14" />
          <div className="ml-auto omi-skeleton h-3 w-12" />
          <div className="ml-auto omi-skeleton h-6 w-12" />
          <div className="ml-auto omi-skeleton h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

function RankingCellSkeleton({
  className = "h-3 w-14",
}: {
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block align-middle omi-skeleton ${className}`}
    />
  );
}

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

function formatWatchlistFreshnessLabel(
  t: TranslationFunction,
  marketLabel: string,
  targetDate: string | null | undefined,
  staleCount: number | null | undefined,
  requestedCount: number | null | undefined
) {
  const dateText = targetDate
    ? t("dashboard.freshness.waitingMarketDate", { targetDate, marketLabel })
    : t("dashboard.freshness.waitingMarket", { marketLabel });

  if (
    staleCount !== null &&
    staleCount !== undefined &&
    requestedCount !== null &&
    requestedCount !== undefined &&
    requestedCount > 0
  ) {
    return t("dashboard.freshness.pendingBackfill", {
      dateText,
      staleCount,
      requestedCount,
    });
  }

  return dateText;
}

function formatLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value / 1000));
}

function formatWholeNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatSignedNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";

  return `${sign}${value.toLocaleString("zh-TW", {
    maximumFractionDigits: 2,
  })}`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatTradeValueYi(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return (value / 100_000_000).toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-omi-text-muted";
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text";
}

function statusLabel(t: TranslationFunction, status: string) {
  if (status === "pending") return "-";
  return rowStatusLabel(t, status);
}

function rankLabel(t: TranslationFunction, rankBy: string) {
  return rankByLabel(t, rankBy);
}

function trendLabel(
  t: TranslationFunction,
  value: number | null | undefined,
  limitStatus?: RankingItem["limit_status"]
) {
  if (limitStatus === "limit_up") return t("statusLabels.limitUp");
  if (limitStatus === "limit_down") return t("statusLabels.limitDown");
  return trendDirectionLabel(t, value);
}

function trendClass(
  value: number | null | undefined,
  limitStatus?: RankingItem["limit_status"]
) {
  if (limitStatus === "limit_up") return "omi-ranking-trend-limit-up";
  if (limitStatus === "limit_down") return "omi-ranking-trend-limit-down";
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "omi-ranking-trend-neutral";
  }
  if (value > 0) return "omi-ranking-trend-up";
  if (value < 0) return "omi-ranking-trend-down";
  return "omi-ranking-trend-neutral";
}

function sparklineTone(
  latestPrice: number | null,
  previousClose: number | null,
  selected: boolean
) {
  if (latestPrice === null || previousClose === null || previousClose === 0) {
    return selected ? "stroke-omi-text-inverse-muted" : "stroke-omi-text-subtle";
  }

  if (latestPrice > previousClose) return "stroke-omi-market-up";
  if (latestPrice < previousClose) return "stroke-omi-market-down";
  return selected ? "stroke-omi-text-inverse-muted" : "stroke-omi-text-subtle";
}

function formatRowTime(value: string | null | undefined) {
  if (!value) return null;

  const date = new Date(value);

  if (Number.isNaN(date.getTime()) || !value.includes("T")) return value;

  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Taipei",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value])
  );

  return `${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`;
}

function formatDashboardTime(value: Date) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })
      .formatToParts(value)
      .map((part) => [part.type, part.value])
  );

  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function buildSparklinePath(
  points: Array<{ time: string; price: number }>,
  previousClose: number | null,
  getXRatio: (value: string | Date) => number = getTaiwanIntradayXRatio
) {
  const width = 92;
  const height = 28;
  const paddingX = 2;
  const paddingY = 4;
  const usableWidth = width - paddingX * 2;
  const usableHeight = height - paddingY * 2;
  const prices = [
    ...points.map((point) => point.price),
    ...(previousClose !== null ? [previousClose] : []),
  ];
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const range = maxPrice - minPrice || Math.max(maxPrice * 0.01, 1);
  const yMin = minPrice - range * 0.08;
  const yMax = maxPrice + range * 0.08;
  const yRange = yMax - yMin || 1;
  const path = points
    .map((point, index) => {
      const x = paddingX + getXRatio(point.time) * usableWidth;
      const y = paddingY + ((yMax - point.price) / yRange) * usableHeight;

      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const previousCloseY =
    previousClose === null
      ? null
      : paddingY + ((yMax - previousClose) / yRange) * usableHeight;
  const latestPoint = points[points.length - 1];
  const latestPointX = paddingX + getXRatio(latestPoint.time) * usableWidth;
  const latestPointY = paddingY + ((yMax - latestPoint.price) / yRange) * usableHeight;

  return { path, previousCloseY, latestPointX, latestPointY, width, height };
}

function sparklinePointTone(
  latestPrice: number | null,
  previousClose: number | null,
  selected: boolean
) {
  if (latestPrice !== null && previousClose !== null && previousClose !== 0) {
    if (latestPrice > previousClose) {
      return {
        core: selected ? "fill-omi-market-up-border" : "fill-omi-market-up",
        ring: selected ? "stroke-omi-market-up-border" : "stroke-omi-market-up",
      };
    }

    if (latestPrice < previousClose) {
      return {
        core: selected ? "fill-omi-market-down-border" : "fill-omi-market-down",
        ring: selected ? "stroke-omi-market-down-border" : "stroke-omi-market-down",
      };
    }
  }

  return {
    core: selected ? "fill-omi-text-inverse-muted" : "fill-omi-text-subtle",
    ring: selected ? "stroke-omi-text-inverse-muted" : "stroke-omi-text-inverse-muted",
  };
}

function RankingSparkline({
  row,
  selected,
}: {
  row: RankingItem;
  selected: boolean;
}) {
  const t = useT();
  const points = (row.intraday_points ?? []).filter((point) => {
    return (
      point.time &&
      point.price !== null &&
      point.price !== undefined &&
      !Number.isNaN(point.price) &&
      isTaiwanRegularSessionPoint(point.time)
    );
  });

  if (points.length < 2) {
    return (
      <span className="text-center text-xs text-omi-text-subtle">
        -
      </span>
    );
  }

  const previousClose = row.intraday_previous_close ?? null;
  const latestPrice = points[points.length - 1]?.price ?? null;
  const chart = buildSparklinePath(points, previousClose);
  const latestPoint = points[points.length - 1];
  const pointTone = sparklinePointTone(latestPrice, previousClose, selected);

  return (
    <svg
      viewBox={`0 0 ${chart.width} ${chart.height}`}
      className="h-8 w-[92px]"
      aria-label={t("dashboard.marketIndex.intradayTrend")}
    >
      <rect width={chart.width} height={chart.height} fill="transparent" />
      {chart.previousCloseY !== null ? (
        <line
          x1="2"
          x2={chart.width - 2}
          y1={chart.previousCloseY}
          y2={chart.previousCloseY}
          className={selected ? "stroke-omi-text-inverse-subtle" : "stroke-omi-border-subtle"}
          strokeDasharray="3 3"
        />
      ) : null}
      <path
        d={chart.path}
        fill="none"
        strokeWidth="1.8"
        className={sparklineTone(latestPrice, previousClose, selected)}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g
        key={`${latestPoint.time}-${latestPoint.price}`}
        className="omi-live-sparkline-point"
        pointerEvents="none"
      >
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="5.5"
          className={`omi-live-point-ring ${pointTone.ring}`}
        />
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="2.2"
          className={`omi-live-point-core ${pointTone.core}`}
        />
      </g>
    </svg>
  );
}

function USRankingSparkline({
  row,
  selected,
}: {
  row: USWatchlistRankingItemRead;
  selected: boolean;
}) {
  const t = useT();
  const points = (row.intraday_points ?? []).filter((point) => {
    return (
      point.time &&
      point.price !== null &&
      point.price !== undefined &&
      !Number.isNaN(point.price) &&
      isUsRegularSessionPoint(point.time)
    );
  });

  if (points.length < 2) {
    return (
      <span className="text-center text-xs text-omi-text-subtle">
        {row.time ? t("statusLabels.intraday") : "-"}
      </span>
    );
  }

  const previousClose = row.intraday_previous_close ?? null;
  const latestPrice = points[points.length - 1]?.price ?? null;
  const chart = buildSparklinePath(points, previousClose, getUsIntradayXRatio);
  const latestPoint = points[points.length - 1];
  const pointTone = sparklinePointTone(latestPrice, previousClose, selected);

  return (
    <svg
      viewBox={`0 0 ${chart.width} ${chart.height}`}
      className="h-8 w-[92px]"
      aria-label="US intraday trend"
    >
      <rect width={chart.width} height={chart.height} fill="transparent" />
      {chart.previousCloseY !== null ? (
        <line
          x1="2"
          x2={chart.width - 2}
          y1={chart.previousCloseY}
          y2={chart.previousCloseY}
          className={selected ? "stroke-omi-text-inverse-subtle" : "stroke-omi-border-subtle"}
          strokeDasharray="3 3"
        />
      ) : null}
      <path
        d={chart.path}
        fill="none"
        strokeWidth="1.8"
        className={sparklineTone(latestPrice, previousClose, selected)}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g
        key={`${latestPoint.time}-${latestPoint.price}`}
        className="omi-live-sparkline-point"
        pointerEvents="none"
      >
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="5.5"
          className={`omi-live-point-ring ${pointTone.ring}`}
        />
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="2.2"
          className={`omi-live-point-core ${pointTone.core}`}
        />
      </g>
    </svg>
  );
}

function marketRegimeLabel(t: TranslationFunction, index: MarketIndexSnapshot) {
  if (index.close === null || index.close === undefined) return t("dashboard.marketIndex.insufficient");
  if (index.price_vs_ma20 !== null && index.price_vs_ma20 !== undefined) {
    if (index.price_vs_ma20 > 1) return t("dashboard.marketIndex.aboveMa20");
    if (index.price_vs_ma20 < -1) return t("dashboard.marketIndex.belowMa20");
  }

  if (index.change_pct !== null && index.change_pct !== undefined) {
    if (index.change_pct > 0) return t("dashboard.marketIndex.bullishShort");
    if (index.change_pct < 0) return t("dashboard.marketIndex.weakShort");
  }

  return t("dashboard.marketIndex.neutral");
}

function MarketTape({
  summary,
  loadState,
}: {
  summary: MarketIndexSummary | null;
  loadState: LoadState;
}) {
  const t = useT();
  const indices = summary?.indices ?? [];
  const asOf = summary?.as_of ? formatDashboardTime(new Date(summary.as_of)) : null;

  return (
    <section className="mb-3 border border-omi-border-subtle bg-omi-surface">
      <div className="grid gap-px bg-omi-surface-strong lg:grid-cols-2">
        {indices.length > 0 ? (
          indices.map((index) => {
            const breadth = index.breadth;
            const advanceRatio =
              breadth && breadth.total_count > 0
                ? (breadth.advance_count / breadth.total_count) * 100
                : null;

            return (
              <div key={index.index_id} className="bg-omi-surface px-4 py-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
                      {t("app.market")}
                    </div>
                    <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="text-lg font-bold text-omi-text-strong">{index.label}</span>
                      <span className="text-2xl font-black text-omi-text-strong">
                        {formatPrice(index.close)}
                      </span>
                      <span className={`text-sm font-bold ${valueTone(index.change_pct)}`}>
                        {formatSignedNumber(index.change)} / {formatPct(index.change_pct)}
                      </span>
                    </div>
                  </div>
                  <div className="text-right text-xs">
                    <div className="font-semibold text-omi-text">{marketRegimeLabel(t, index)}</div>
                    <div className={valueTone(index.price_vs_ma20)}>
                      {formatPct(index.price_vs_ma20)} vs MA20
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
                    <div className="text-omi-text-muted">{t("dashboard.marketIndex.tradeValueYi")}</div>
                    <div className="mt-1 font-semibold text-omi-text">
                      {formatTradeValueYi(index.trade_value)}
                    </div>
                  </div>
                  <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
                    <div className="text-omi-text-muted">{t("dashboard.marketIndex.advanceDecline")}</div>
                    <div className="mt-1 font-semibold">
                      <span className="text-omi-market-up">{breadth?.advance_count ?? "-"}</span>
                      <span className="px-1 text-omi-text-subtle">/</span>
                      <span className="text-omi-market-down">{breadth?.decline_count ?? "-"}</span>
                    </div>
                  </div>
                  <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
                    <div className="text-omi-text-muted">{t("dashboard.marketIndex.breadth")}</div>
                    <div className={`mt-1 font-semibold ${valueTone((advanceRatio ?? 50) - 50)}`}>
                      {advanceRatio === null
                        ? "-"
                        : t("dashboard.marketIndex.advancePct", {
                            value: advanceRatio.toFixed(0),
                          })}
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        ) : (
          <StateSurface
            title={
              loadState === "loading"
                ? t("dashboard.marketIndex.loading")
                : t("dashboard.marketIndex.empty")
            }
            tone={loadState === "loading" ? "loading" : "empty"}
            busy={loadState === "loading"}
            compact
            className="m-3 lg:col-span-2"
          />
        )}
      </div>
      <div className="border-t border-omi-border-subtle px-4 py-2 text-xs text-omi-text-muted">
        {asOf
          ? t("dashboard.marketIndex.updated", { asOf })
          : t("dashboard.marketIndex.waiting")}
      </div>
    </section>
  );
}

type USMarketTapeSnapshot = {
  symbol: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
  close: number | null;
  change: number | null;
  changePct: number | null;
  priceVsMa20: number | null;
  volume: number | null;
  pointCount: number;
  asOf: string | null;
  source: "intraday" | "daily";
};

function averageLastNumbers(values: Array<number | null | undefined>, windowSize: number) {
  const validValues = values
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value);
    })
    .slice(-windowSize);

  if (!validValues.length) return null;

  return validValues.reduce((total, value) => total + value, 0) / validValues.length;
}

function sumUsIntradayVolume(points: IntradayTrendResponse["points"]) {
  const regularVolumes = points
    .filter((point) => isUsRegularSessionPoint(point.time))
    .map((point) => point.volume)
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value) && value > 0;
    });

  if (!regularVolumes.length) return null;

  return regularVolumes.reduce((total, value) => total + value, 0);
}

function usMarketRegimeLabel(
  t: TranslationFunction,
  snapshot:
    | {
        close: number | null;
        priceVsMa20: number | null;
        changePct: number | null;
      }
    | null
    | undefined
) {
  if (!snapshot || snapshot.close === null) return t("dashboard.marketIndex.insufficient");
  if (snapshot.priceVsMa20 !== null) {
    if (snapshot.priceVsMa20 > 1) return t("dashboard.marketIndex.aboveMa20");
    if (snapshot.priceVsMa20 < -1) return t("dashboard.marketIndex.belowMa20");
  }

  if (snapshot.changePct !== null) {
    if (snapshot.changePct > 0) return t("dashboard.marketIndex.bullishShort");
    if (snapshot.changePct < 0) return t("dashboard.marketIndex.weakShort");
  }

  return t("dashboard.marketIndex.neutral");
}

async function fetchUsMarketTapeSnapshot(config: USMarketIndexConfig) {
  const [chart, intraday] = await Promise.all([
    fetchJson<USOhlcChartRead>(
      `/api/us-market/ohlc/${encodeURIComponent(config.symbol)}`,
      {
        timeframe: "daily",
        bars: 60,
        ensure_history: true,
        outputsize: "compact",
        provider: "yahoo_chart",
      }
    ),
    fetchJson<IntradayTrendResponse>(
      `/api/us-market/intraday/${encodeURIComponent(config.symbol)}`
    ).catch(() => null),
  ]);
  const chartPoints = chart.points ?? [];
  const latestDaily = chartPoints[chartPoints.length - 1] ?? null;
  const previousDaily = chartPoints[chartPoints.length - 2] ?? null;
  const latestIntraday = intraday?.points[intraday.points.length - 1] ?? null;
  const close = latestIntraday?.price ?? latestDaily?.close ?? null;
  const previousClose =
    latestIntraday && intraday?.previous_close !== null && intraday?.previous_close !== undefined
      ? intraday.previous_close
      : previousDaily?.close ?? null;
  const change =
    close !== null && previousClose !== null ? close - previousClose : null;
  const changePct =
    change !== null && previousClose !== null && previousClose !== 0
      ? (change / previousClose) * 100
      : null;
  const ma20 = averageLastNumbers(
    chartPoints.map((point) => point.close),
    20
  );
  const priceVsMa20 =
    close !== null && ma20 !== null && ma20 !== 0
      ? ((close - ma20) / ma20) * 100
      : null;

  return {
    symbol: config.symbol,
    displaySymbol: config.displaySymbol,
    name: config.name,
    exchange: config.exchange,
    note: config.note,
    close,
    change,
    changePct,
    priceVsMa20,
    volume: latestIntraday
      ? sumUsIntradayVolume(intraday?.points ?? []) ?? latestDaily?.volume ?? null
      : latestDaily?.volume ?? null,
    pointCount: chart.point_count,
    asOf: latestIntraday?.time ?? latestDaily?.time ?? null,
    source: latestIntraday ? "intraday" : "daily",
  } satisfies USMarketTapeSnapshot;
}

function USMarketTapeCard({
  title,
  snapshot,
  loadState,
}: {
  title: string;
  snapshot: USMarketTapeSnapshot | null;
  loadState: LoadState;
}) {
  const t = useT();

  return (
    <div className="bg-omi-surface px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            {title}
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-bold text-omi-text-strong">
              {snapshot ? snapshot.name : loadState === "loading" ? t("common.loading") : "-"}
            </span>
            <span className="text-2xl font-black text-omi-text-strong">
              {formatPrice(snapshot?.close)}
            </span>
            <span className={`text-sm font-bold ${valueTone(snapshot?.changePct)}`}>
              {formatSignedNumber(snapshot?.change)} / {formatPct(snapshot?.changePct)}
            </span>
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {snapshot
              ? `${snapshot.displaySymbol} · ${snapshot.exchange} · ${
                  snapshot.source === "intraday"
                    ? t("statusLabels.intraday")
                    : t("dashboard.marketIndex.daily")
                }`
              : t("dashboard.marketIndex.waitingData")}
          </div>
        </div>
        <div className="text-right text-xs">
          <div className="font-semibold text-omi-text">
            {usMarketRegimeLabel(t, snapshot)}
          </div>
          <div className={valueTone(snapshot?.priceVsMa20)}>
            {formatPct(snapshot?.priceVsMa20)} vs MA20
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.volume")}</div>
          <div className="mt-1 font-semibold text-omi-text">
            {formatWholeNumber(snapshot?.volume)}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.candleCount")}</div>
          <div className="mt-1 font-semibold text-omi-text">
            {snapshot?.pointCount ?? "-"}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("common.update")}</div>
          <div className="mt-1 truncate font-semibold text-omi-text">
            {snapshot?.asOf ? formatRowTime(snapshot.asOf) ?? snapshot.asOf.slice(0, 10) : "-"}
          </div>
        </div>
      </div>
    </div>
  );
}

function USMarketTape({
  selectedSymbol,
  selectedSecurityName,
  selectedGroupName,
  companyProfile,
}: {
  selectedSymbol: string | null;
  selectedSecurityName: string | null;
  selectedGroupName: string | null;
  companyProfile: USCompanyProfileRead | null;
}) {
  const t = useT();
  const primaryIndex = useMemo(() => getUsPrimaryMarketIndexConfig(), []);
  const contextIndex = useMemo(
    () =>
      resolveUsContextIndexConfig({
        symbol: selectedSymbol,
        securityName: selectedSecurityName,
        groupName: selectedGroupName,
        profile: companyProfile,
      }),
    [companyProfile, selectedGroupName, selectedSecurityName, selectedSymbol]
  );
  const [snapshots, setSnapshots] = useState<Record<string, USMarketTapeSnapshot>>({});
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const primarySnapshot = snapshots[primaryIndex.symbol] ?? null;
  const contextSnapshot = snapshots[contextIndex.symbol] ?? null;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let requestInFlight = false;
    const configs = [primaryIndex, contextIndex].filter(
      (config, index, items) => {
        return items.findIndex((item) => item.symbol === config.symbol) === index;
      }
    );

    function clearTimer() {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
    }

    async function loadSnapshots(silent = false) {
      if (requestInFlight) return;
      requestInFlight = true;

      if (!silent) {
        setLoadState("loading");
      }

      try {
        const nextSnapshots = await Promise.all(
          configs.map((config) => fetchUsMarketTapeSnapshot(config))
        );

        if (cancelled) return;

        setSnapshots((current) => {
          const updated = { ...current };
          nextSnapshots.forEach((snapshot) => {
            updated[snapshot.symbol] = snapshot;
          });
          return updated;
        });
        setLoadState("success");
      } catch (error) {
        if (cancelled) return;

        setLoadState("error");
        emitDashboardDataStatus({
          market: "us",
          title: t("dashboard.marketIndex.usLoadError"),
          message: apiErrorMessage(error, t("dashboard.marketIndex.usLoadError")),
          source: t("dashboard.marketIndex.market"),
          contextKey: "us:market-index-tape",
          contextLabel: t("dashboard.marketIndex.market"),
        });
      } finally {
        requestInFlight = false;
      }
    }

    function scheduleRefresh() {
      if (cancelled) return;

      const marketState = getUsMarketRefreshState();
      const delay = marketState.isPollingWindow
        ? US_INTRADAY_REFRESH_MS
        : Math.min(marketState.msUntilNextPollingStart, 60_000);

      timer = window.setTimeout(() => {
        void loadSnapshots(true).finally(scheduleRefresh);
      }, delay);
    }

    void loadSnapshots().finally(scheduleRefresh);

    return () => {
      cancelled = true;
      clearTimer();
    };
  }, [contextIndex, primaryIndex, t]);

  const asOf = [primarySnapshot?.asOf, contextSnapshot?.asOf]
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => left.localeCompare(right))
    .at(-1);

  return (
    <section className="mb-3 border border-omi-border-subtle bg-omi-surface">
      <div className="grid gap-px bg-omi-surface-strong lg:grid-cols-2">
        <USMarketTapeCard
          title={t("dashboard.marketIndex.market")}
          snapshot={primarySnapshot}
          loadState={loadState}
        />
        <USMarketTapeCard
          title={t("dashboard.marketIndex.context")}
          snapshot={contextSnapshot}
          loadState={loadState}
        />
      </div>
      <div className="border-t border-omi-border-subtle px-4 py-2 text-xs text-omi-text-muted">
        {asOf
          ? t("dashboard.marketIndex.usUpdated", {
              asOf: formatRowTime(asOf) ?? asOf.slice(0, 10),
            })
          : t("dashboard.marketIndex.usWaiting")}
      </div>
    </section>
  );
}

type JPMarketTapeSnapshot = {
  symbol: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
  close: number | null;
  change: number | null;
  changePct: number | null;
  priceVsMa20: number | null;
  volume: number | null;
  pointCount: number;
  asOf: string | null;
};

async function fetchJpMarketTapeSnapshot(config: JPMarketIndexConfig) {
  const chart = await fetchJson<JPOhlcChartRead>(
    `/api/jp-market/ohlc/${encodeURIComponent(config.symbol)}`,
    {
      timeframe: "daily",
      bars: 60,
      ensure_history: true,
      outputsize: "compact",
      provider: "auto",
    }
  );
  const chartPoints = chart.points ?? [];
  const latestDaily = chartPoints[chartPoints.length - 1] ?? null;
  const previousDaily = chartPoints[chartPoints.length - 2] ?? null;
  const close = latestDaily?.close ?? null;
  const previousClose = previousDaily?.close ?? null;
  const change =
    close !== null && previousClose !== null ? close - previousClose : null;
  const changePct =
    change !== null && previousClose !== null && previousClose !== 0
      ? (change / previousClose) * 100
      : null;
  const ma20 = averageLastNumbers(
    chartPoints.map((point) => point.close),
    20
  );
  const priceVsMa20 =
    close !== null && ma20 !== null && ma20 !== 0
      ? ((close - ma20) / ma20) * 100
      : null;

  return {
    symbol: config.symbol,
    displaySymbol: config.displaySymbol,
    name: config.name,
    exchange: config.exchange,
    note: config.note,
    close,
    change,
    changePct,
    priceVsMa20,
    volume: latestDaily?.volume ?? null,
    pointCount: chart.point_count,
    asOf: latestDaily?.time ?? null,
  } satisfies JPMarketTapeSnapshot;
}

function JPMarketTapeCard({
  title,
  snapshot,
  loadState,
}: {
  title: string;
  snapshot: JPMarketTapeSnapshot | null;
  loadState: LoadState;
}) {
  const t = useT();

  return (
    <div className="bg-omi-surface px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            {title}
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-bold text-omi-text-strong">
              {snapshot ? snapshot.name : loadState === "loading" ? t("common.loading") : "-"}
            </span>
            <span className="text-2xl font-black text-omi-text-strong">
              {formatPrice(snapshot?.close)}
            </span>
            <span className={`text-sm font-bold ${valueTone(snapshot?.changePct)}`}>
              {formatSignedNumber(snapshot?.change)} / {formatPct(snapshot?.changePct)}
            </span>
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {snapshot
              ? `${snapshot.displaySymbol} · ${snapshot.exchange} · ${t("dashboard.marketIndex.daily")}`
              : t("dashboard.marketIndex.waitingData")}
          </div>
        </div>
        <div className="text-right text-xs">
          <div className="font-semibold text-omi-text">
            {usMarketRegimeLabel(t, snapshot)}
          </div>
          <div className={valueTone(snapshot?.priceVsMa20)}>
            {formatPct(snapshot?.priceVsMa20)} vs MA20
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.volume")}</div>
          <div className="mt-1 font-semibold text-omi-text">
            {formatWholeNumber(snapshot?.volume)}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.candleCount")}</div>
          <div className="mt-1 font-semibold text-omi-text">
            {snapshot?.pointCount ?? "-"}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("common.update")}</div>
          <div className="mt-1 truncate font-semibold text-omi-text">
            {snapshot?.asOf ? snapshot.asOf.slice(0, 10) : "-"}
          </div>
        </div>
      </div>
    </div>
  );
}

function JPMarketTape({
  selectedSymbol,
  selectedStock,
  selectedGroupName,
}: {
  selectedSymbol: string | null;
  selectedStock: JPStockMasterRead | null;
  selectedGroupName: string | null;
}) {
  const t = useT();
  const primaryIndex = useMemo(() => getJpPrimaryMarketIndexConfig(), []);
  const contextIndex = useMemo(
    () =>
      resolveJpContextIndexConfig({
        symbol: selectedSymbol,
        securityName: selectedStock?.security_name ?? null,
        groupName: selectedGroupName,
        stock: selectedStock,
      }),
    [selectedGroupName, selectedStock, selectedSymbol]
  );
  const [snapshots, setSnapshots] = useState<Record<string, JPMarketTapeSnapshot>>({});
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const primarySnapshot = snapshots[primaryIndex.symbol] ?? null;
  const contextSnapshot = snapshots[contextIndex.symbol] ?? null;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let requestInFlight = false;
    const configs = [primaryIndex, contextIndex].filter(
      (config, index, items) => {
        return items.findIndex((item) => item.symbol === config.symbol) === index;
      }
    );

    function clearTimer() {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
    }

    async function loadSnapshots(silent = false) {
      if (requestInFlight) return;
      requestInFlight = true;

      if (!silent) {
        setLoadState("loading");
      }

      try {
        const results = await Promise.all(
          configs.map((config) => fetchJpMarketTapeSnapshot(config))
        );

        if (cancelled) return;

        setSnapshots((current) => {
          const next = { ...current };
          results.forEach((snapshot) => {
            next[snapshot.symbol] = snapshot;
          });
          return next;
        });
        setLoadState("success");
      } catch (error) {
        if (!cancelled) {
          setLoadState("error");
          emitDashboardDataStatus({
            market: "jp",
            title: t("dashboard.marketIndex.jpLoadError"),
            message: apiErrorMessage(error, t("dashboard.marketIndex.jpLoadError")),
            source: t("dashboard.marketIndex.market"),
            contextKey: "jp:market-index-tape",
            contextLabel: t("dashboard.marketIndex.market"),
          });
        }
      } finally {
        requestInFlight = false;
      }
    }

    function scheduleRefresh() {
      if (cancelled) return;

      timer = window.setTimeout(() => {
        void loadSnapshots(true).finally(scheduleRefresh);
      }, 300_000);
    }

    void loadSnapshots().finally(scheduleRefresh);

    return () => {
      cancelled = true;
      clearTimer();
    };
  }, [contextIndex, primaryIndex, t]);

  const asOf = [primarySnapshot?.asOf, contextSnapshot?.asOf]
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => left.localeCompare(right))
    .at(-1);

  return (
    <section className="mb-3 border border-omi-border-subtle bg-omi-surface">
      <div className="grid gap-px bg-omi-surface-strong lg:grid-cols-2">
        <JPMarketTapeCard
          title={t("dashboard.marketIndex.market")}
          snapshot={primarySnapshot}
          loadState={loadState}
        />
        <JPMarketTapeCard
          title={t("dashboard.marketIndex.context")}
          snapshot={contextSnapshot}
          loadState={loadState}
        />
      </div>
      <div className="border-t border-omi-border-subtle px-4 py-2 text-xs text-omi-text-muted">
        {asOf
          ? t("dashboard.marketIndex.jpUpdated", {
              asOf: asOf.slice(0, 10),
            })
          : t("dashboard.marketIndex.jpWaiting")}
      </div>
    </section>
  );
}

type KRMarketTapeSnapshot = {
  symbol: string;
  indexId: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
  close: number | null;
  change: number | null;
  changePct: number | null;
  priceVsMa20: number | null;
  volume: number | null;
  pointCount: number;
  asOf: string | null;
  breadth: KRMarketBreadthRead | null;
};

async function fetchKrMarketTapeSnapshot(config: KRMarketIndexConfig) {
  const [chart, breadth] = await Promise.all([
    fetchJson<KRIndexOhlcChartRead>(
      `/api/kr-market/indices/${encodeURIComponent(config.indexId)}/ohlc`,
      {
        timeframe: "daily",
        bars: 60,
        ensure_history: false,
      }
    ),
    fetchJson<KRMarketBreadthRead>(
      `/api/kr-market/indices/${encodeURIComponent(config.indexId)}/breadth`
    ),
  ]);
  const chartPoints = chart.points ?? [];
  const latestDaily = chartPoints[chartPoints.length - 1] ?? null;
  const previousDaily = chartPoints[chartPoints.length - 2] ?? null;
  const close = latestDaily?.close ?? null;
  const previousClose = previousDaily?.close ?? null;
  const change =
    close !== null && previousClose !== null ? close - previousClose : null;
  const changePct =
    change !== null && previousClose !== null && previousClose !== 0
      ? (change / previousClose) * 100
      : null;
  const ma20 = averageLastNumbers(
    chartPoints.map((point) => point.close),
    20
  );
  const priceVsMa20 =
    close !== null && ma20 !== null && ma20 !== 0
      ? ((close - ma20) / ma20) * 100
      : null;

  return {
    symbol: config.symbol,
    indexId: config.indexId,
    displaySymbol: config.displaySymbol,
    name: config.name,
    exchange: config.exchange,
    note: config.note,
    close,
    change,
    changePct,
    priceVsMa20,
    volume: latestDaily?.volume ?? null,
    pointCount: chart.point_count,
    asOf: latestDaily?.time ?? null,
    breadth,
  } satisfies KRMarketTapeSnapshot;
}

function KRMarketTapeCard({
  title,
  snapshot,
  loadState,
}: {
  title: string;
  snapshot: KRMarketTapeSnapshot | null;
  loadState: LoadState;
}) {
  const t = useT();
  const breadth = snapshot?.breadth ?? null;
  const advanceRatio =
    breadth && breadth.total_count > 0
      ? (breadth.advance_count / breadth.total_count) * 100
      : null;

  return (
    <div className="bg-omi-surface px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
            {title}
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-lg font-bold text-omi-text-strong">
              {snapshot ? snapshot.name : loadState === "loading" ? t("common.loading") : "-"}
            </span>
            <span className="text-2xl font-black text-omi-text-strong">
              {formatPrice(snapshot?.close)}
            </span>
            <span className={`text-sm font-bold ${valueTone(snapshot?.changePct)}`}>
              {formatSignedNumber(snapshot?.change)} / {formatPct(snapshot?.changePct)}
            </span>
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {snapshot
              ? `${snapshot.displaySymbol} · ${snapshot.exchange} · ${t("dashboard.marketIndex.daily")}`
              : t("dashboard.marketIndex.waitingData")}
          </div>
        </div>
        <div className="text-right text-xs">
          <div className="font-semibold text-omi-text">
            {usMarketRegimeLabel(t, snapshot)}
          </div>
          <div className={valueTone(snapshot?.priceVsMa20)}>
            {formatPct(snapshot?.priceVsMa20)} vs MA20
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.tradeValueYi")}</div>
          <div className="mt-1 font-semibold text-omi-text">
            {formatTradeValueYi(breadth?.trade_value)}
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.advanceDecline")}</div>
          <div className="mt-1 font-semibold">
            <span className="text-omi-market-up">{breadth?.advance_count ?? "-"}</span>
            <span className="px-1 text-omi-text-subtle">/</span>
            <span className="text-omi-market-down">{breadth?.decline_count ?? "-"}</span>
          </div>
        </div>
        <div className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-2">
          <div className="text-omi-text-muted">{t("dashboard.marketIndex.breadth")}</div>
          <div className={`mt-1 font-semibold ${valueTone((advanceRatio ?? 50) - 50)}`}>
            {advanceRatio === null
              ? "-"
              : t("dashboard.marketIndex.advancePct", {
                  value: advanceRatio.toFixed(0),
                })}
          </div>
        </div>
      </div>
    </div>
  );
}

function KRMarketTape({
  selectedSymbol,
  selectedStock,
  selectedGroupName,
}: {
  selectedSymbol: string | null;
  selectedStock: KRStockMasterRead | null;
  selectedGroupName: string | null;
}) {
  const t = useT();
  const primaryIndex = useMemo(() => getKrPrimaryMarketIndexConfig(), []);
  const contextIndex = useMemo(
    () =>
      resolveKrContextIndexConfig({
        symbol: selectedSymbol,
        securityName: selectedStock?.security_name ?? selectedStock?.security_name_kr ?? null,
        groupName: selectedGroupName,
        stock: selectedStock,
      }),
    [selectedGroupName, selectedStock, selectedSymbol]
  );
  const [snapshots, setSnapshots] = useState<Record<string, KRMarketTapeSnapshot>>({});
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const primarySnapshot = snapshots[primaryIndex.symbol] ?? null;
  const contextSnapshot = snapshots[contextIndex.symbol] ?? null;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let requestInFlight = false;
    const configs = [primaryIndex, contextIndex].filter(
      (config, index, items) => {
        return items.findIndex((item) => item.symbol === config.symbol) === index;
      }
    );

    function clearTimer() {
      if (timer !== undefined) {
        window.clearTimeout(timer);
        timer = undefined;
      }
    }

    async function loadSnapshots(silent = false) {
      if (requestInFlight) return;
      requestInFlight = true;

      if (!silent) {
        setLoadState("loading");
      }

      try {
        const results = await Promise.all(
          configs.map((config) => fetchKrMarketTapeSnapshot(config))
        );

        if (cancelled) return;

        setSnapshots((current) => {
          const next = { ...current };
          results.forEach((snapshot) => {
            next[snapshot.symbol] = snapshot;
          });
          return next;
        });
        setLoadState("success");
      } catch (error) {
        if (!cancelled) {
          setLoadState("error");
          emitDashboardDataStatus({
            market: "kr",
            title: t("dashboard.marketIndex.krLoadError"),
            message: apiErrorMessage(error, t("dashboard.marketIndex.krLoadError")),
            source: t("dashboard.marketIndex.market"),
            contextKey: "kr:market-index-tape",
            contextLabel: t("dashboard.marketIndex.market"),
          });
        }
      } finally {
        requestInFlight = false;
      }
    }

    function scheduleRefresh() {
      if (cancelled) return;

      timer = window.setTimeout(() => {
        void loadSnapshots(true).finally(scheduleRefresh);
      }, 300_000);
    }

    void loadSnapshots().finally(scheduleRefresh);

    return () => {
      cancelled = true;
      clearTimer();
    };
  }, [contextIndex, primaryIndex, t]);

  const asOf = [primarySnapshot?.asOf, contextSnapshot?.asOf]
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => left.localeCompare(right))
    .at(-1);

  return (
    <section className="mb-3 border border-omi-border-subtle bg-omi-surface">
      <div className="grid gap-px bg-omi-surface-strong lg:grid-cols-2">
        <KRMarketTapeCard
          title={t("dashboard.marketIndex.market")}
          snapshot={primarySnapshot}
          loadState={loadState}
        />
        <KRMarketTapeCard
          title={t("dashboard.marketIndex.context")}
          snapshot={contextSnapshot}
          loadState={loadState}
        />
      </div>
      <div className="border-t border-omi-border-subtle px-4 py-2 text-xs text-omi-text-muted">
        {asOf
          ? t("dashboard.marketIndex.krUpdated", {
              asOf: asOf.slice(0, 10),
            })
          : t("dashboard.marketIndex.krWaiting")}
      </div>
    </section>
  );
}

function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
}

function flattenUsGroups(nodes: USWatchlistGroupNode[]): USWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenUsGroups(node.children)]);
}

function flattenJpGroups(nodes: JPWatchlistGroupNode[]): JPWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenJpGroups(node.children)]);
}

function flattenKrGroups(nodes: KRWatchlistGroupNode[]): KRWatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenKrGroups(node.children)]);
}

function buildWatchlistRows(
  group: WatchlistGroupNode | null,
  items: WatchlistItemRead[]
): RankingItem[] {
  if (!group) return [];

  const itemsByGroupId = new Map<number, WatchlistItemRead[]>();
  const seenStockIds = new Set<string>();
  const rows: RankingItem[] = [];

  items.forEach((item) => {
    if (!item.enabled) return;

    const groupItems = itemsByGroupId.get(item.group_id) ?? [];
    groupItems.push(item);
    itemsByGroupId.set(item.group_id, groupItems);
  });

  function appendGroupRows(currentGroup: WatchlistGroupNode) {
    (itemsByGroupId.get(currentGroup.id) ?? []).forEach((item) => {
      if (seenStockIds.has(item.stock_id)) return;

      seenStockIds.add(item.stock_id);
      rows.push({
        rank: rows.length + 1,
        stock_id: item.stock_id,
        stock_name: item.stock_name,
        time: null,
        close: null,
        volume: null,
        change: null,
        previous_close: null,
        change_pct: null,
        limit_status: null,
        score: null,
        status: "pending",
        signal_count: 0,
        signal_keys: [],
        primary_signal_key: null,
        primary_signal_label: null,
        indicator_snapshot: {},
        context_snapshot: {},
        intraday_previous_close: null,
        intraday_points: [],
        error_message: null,
      });
    });

    currentGroup.children.forEach(appendGroupRows);
  }

  appendGroupRows(group);
  return rows;
}

function mergeWatchlistRows(
  baseRows: RankingItem[],
  ranking: RankingResponse | null
) {
  if (!ranking) return baseRows;

  const rankingByStockId = new Map(
    ranking.results.map((row) => [row.stock_id, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingByStockId.get(row.stock_id) ?? {}),
    rank: index + 1,
  }));
}

function rankingRowDateKey(value: string | null | undefined) {
  return value?.slice(0, 10) ?? null;
}

function latestRankingTradeDate(rows: RankingItem[]) {
  return rows.reduce<string | null>((latest, row) => {
    const value = rankingRowDateKey(row.time);
    if (!value) return latest;
    return latest === null || value > latest ? value : latest;
  }, null);
}

function mergeRankingBatchRows(
  currentRows: RankingItem[],
  batchRows: RankingItem[]
) {
  const rowsByStockId = new Map(currentRows.map((row) => [row.stock_id, row]));

  batchRows.forEach((row) => {
    rowsByStockId.set(row.stock_id, row);
  });

  return Array.from(rowsByStockId.values()).sort((a, b) => a.rank - b.rank);
}

function deferRankingTrendData(row: RankingItem): RankingItem {
  const intradayPoints = Array.isArray(row.intraday_points) ? row.intraday_points : [];

  if (intradayPoints.length === 0 && row.intraday_previous_close === null) {
    return row;
  }

  return {
    ...row,
    intraday_previous_close: null,
    intraday_points: [],
  };
}

function buildProgressiveRankingResponse({
  batch,
  rows,
  currentStockCount,
  staleStockCount,
  noDataCount,
  errorCount,
  complete,
  deferTrendData,
}: {
  batch: RankingBatchResponse;
  rows: RankingItem[];
  currentStockCount: number;
  staleStockCount: number;
  noDataCount: number;
  errorCount: number;
  complete: boolean;
  deferTrendData?: boolean;
}): RankingResponse {
  return {
    group_id: batch.group_id,
    include_children: batch.include_children,
    rank_by: batch.rank_by,
    sort_order: batch.sort_order,
    requested_stock_count: batch.total_stock_count,
    ranked_count: rows.length,
    no_data_count: noDataCount,
    error_count: errorCount,
    trade_date: latestRankingTradeDate(rows),
    target_trade_date: batch.target_trade_date,
    is_current: complete ? staleStockCount === 0 : true,
    current_stock_count: currentStockCount,
    stale_stock_count: complete ? staleStockCount : 0,
    results: deferTrendData ? rows.map(deferRankingTrendData) : rows,
  };
}

function buildUsWatchlistRows(
  group: USWatchlistGroupNode | null,
  items: USWatchlistItemRead[]
): USWatchlistRankingItemRead[] {
  if (!group) return [];

  const itemsByGroupId = new Map<number, USWatchlistItemRead[]>();
  const seenSymbols = new Set<string>();
  const rows: USWatchlistRankingItemRead[] = [];

  items.forEach((item) => {
    if (!item.enabled) return;

    const groupItems = itemsByGroupId.get(item.group_id) ?? [];
    groupItems.push(item);
    itemsByGroupId.set(item.group_id, groupItems);
  });

  function appendGroupRows(currentGroup: USWatchlistGroupNode) {
    (itemsByGroupId.get(currentGroup.id) ?? []).forEach((item) => {
      const symbol = item.symbol.toUpperCase();
      if (seenSymbols.has(symbol)) return;

      seenSymbols.add(symbol);
      rows.push({
        rank: rows.length + 1,
        symbol,
        security_name: item.security_name,
        exchange: item.exchange,
        asset_type: item.asset_type,
        group_id: item.group_id,
        trade_date: null,
        time: null,
        close: null,
        previous_close: null,
        change: null,
        change_pct: null,
        volume: null,
        status: "pending",
        session: "regular",
        has_extended_hours: false,
        source: null,
        intraday_previous_close: null,
        intraday_points: [],
        error_message: null,
      });
    });

    currentGroup.children.forEach(appendGroupRows);
  }

  appendGroupRows(group);
  return rows;
}

function mergeUsWatchlistRows(
  baseRows: USWatchlistRankingItemRead[],
  ranking: USWatchlistRankingRead | null
) {
  if (!ranking) return baseRows;

  const rankingResults = Array.isArray(ranking.results) ? ranking.results : [];
  const rankingBySymbol = new Map(
    rankingResults.map((row) => [row.symbol, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingBySymbol.get(row.symbol) ?? {}),
    rank: index + 1,
  }));
}

function buildJpWatchlistRows(
  group: JPWatchlistGroupNode | null,
  items: JPWatchlistItemRead[]
): JPWatchlistRankingItemRead[] {
  if (!group) return [];

  const itemsByGroupId = new Map<number, JPWatchlistItemRead[]>();
  const seenSymbols = new Set<string>();
  const rows: JPWatchlistRankingItemRead[] = [];

  items.forEach((item) => {
    if (!item.enabled) return;

    const groupItems = itemsByGroupId.get(item.group_id) ?? [];
    groupItems.push(item);
    itemsByGroupId.set(item.group_id, groupItems);
  });

  function appendGroupRows(currentGroup: JPWatchlistGroupNode) {
    (itemsByGroupId.get(currentGroup.id) ?? []).forEach((item) => {
      const symbol = item.symbol.toUpperCase();
      if (seenSymbols.has(symbol)) return;

      seenSymbols.add(symbol);
      rows.push({
        rank: rows.length + 1,
        symbol,
        security_name: item.security_name,
        exchange: item.exchange,
        market_segment: item.market_segment,
        sector_33_name: item.sector_33_name,
        asset_type: item.asset_type,
        group_id: item.group_id,
        trade_date: null,
        close: null,
        previous_close: null,
        change: null,
        change_pct: null,
        volume: null,
        status: "pending",
        source: null,
        error_message: null,
      });
    });

    currentGroup.children.forEach(appendGroupRows);
  }

  appendGroupRows(group);
  return rows;
}

function mergeJpWatchlistRows(
  baseRows: JPWatchlistRankingItemRead[],
  ranking: JPWatchlistRankingRead | null
) {
  if (!ranking) return baseRows;

  const rankingResults = Array.isArray(ranking.results) ? ranking.results : [];
  const rankingBySymbol = new Map(
    rankingResults.map((row) => [row.symbol, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingBySymbol.get(row.symbol) ?? {}),
    rank: index + 1,
  }));
}

function buildKrWatchlistRows(
  group: KRWatchlistGroupNode | null,
  items: KRWatchlistItemRead[]
): KRWatchlistRankingItemRead[] {
  if (!group) return [];

  const itemsByGroupId = new Map<number, KRWatchlistItemRead[]>();
  const seenSymbols = new Set<string>();
  const rows: KRWatchlistRankingItemRead[] = [];

  items.forEach((item) => {
    if (!item.enabled) return;

    const groupItems = itemsByGroupId.get(item.group_id) ?? [];
    groupItems.push(item);
    itemsByGroupId.set(item.group_id, groupItems);
  });

  function appendGroupRows(currentGroup: KRWatchlistGroupNode) {
    (itemsByGroupId.get(currentGroup.id) ?? []).forEach((item) => {
      const symbol = item.symbol.toUpperCase();
      if (seenSymbols.has(symbol)) return;

      seenSymbols.add(symbol);
      rows.push({
        rank: rows.length + 1,
        symbol,
        security_name: item.security_name ?? item.security_name_kr,
        exchange: item.exchange,
        market_segment: item.market_segment,
        sector: item.sector,
        industry: item.industry,
        asset_type: item.asset_type,
        group_id: item.group_id,
        trade_date: null,
        close: null,
        previous_close: null,
        change: null,
        change_pct: null,
        volume: null,
        status: "pending",
        source: null,
        error_message: null,
      });
    });

    currentGroup.children.forEach(appendGroupRows);
  }

  appendGroupRows(group);
  return rows;
}

function mergeKrWatchlistRows(
  baseRows: KRWatchlistRankingItemRead[],
  ranking: KRWatchlistRankingRead | null
) {
  if (!ranking) return baseRows;

  const rankingResults = Array.isArray(ranking.results) ? ranking.results : [];
  const rankingBySymbol = new Map(
    rankingResults.map((row) => [row.symbol, row])
  );

  return baseRows.map((row, index) => ({
    ...row,
    ...(rankingBySymbol.get(row.symbol) ?? {}),
    rank: index + 1,
  }));
}

function WatchlistRankingPanel({
  groupName,
  lastUpdatedAt,
  statusLabel,
  rankBy,
  rankOptions,
  onRankByChange,
  onReload,
  reloadDisabled,
  secondaryAction,
  loadState,
  loadingLabel,
  rows,
  summary,
  volumeHeader,
  emptyMessage,
}: {
  groupName: string | null;
  lastUpdatedAt: string | null;
  statusLabel?: string;
  rankBy: string;
  rankOptions: RankingPanelOption[];
  onRankByChange: (value: string) => void;
  onReload: () => void;
  reloadDisabled: boolean;
  secondaryAction?: ReactNode;
  loadState: LoadState;
  loadingLabel?: string;
  rows: RankingDisplayRow[];
  summary: {
    stockCount: number;
    upCount: number;
    downCount: number;
  };
  volumeHeader: string;
  emptyMessage: string;
}) {
  const t = useT();
  const hasRows = rows.length > 0;
  const hasLoadingRows = rows.some((row) => row.loading);
  const isLoadingRows = (loadState === "loading" && !hasRows) || hasLoadingRows;
  const showLoadingStatus = loadState === "loading" || hasLoadingRows;

  return (
    <div className="space-y-4">
      <section className="border border-omi-border-subtle bg-omi-surface">
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              {t("dashboard.ranking.selectedGroup")}
            </div>
            <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
              {groupName ?? t("dashboard.ranking.selectedGroupPlaceholder")}
            </h2>
            <div className="mt-1 text-sm text-omi-text-muted">
              {statusLabel ??
                (lastUpdatedAt
                  ? t("dashboard.ranking.updateTime", { time: lastUpdatedAt })
                  : t("dashboard.ranking.groupDataNotLoaded"))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={rankBy}
              onChange={(event) => onRankByChange(event.target.value)}
              className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text-muted outline-none focus:border-omi-accent"
            >
              {rankOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {secondaryAction}
            <button
              type="button"
              onClick={onReload}
              className="h-9 bg-omi-control px-4 text-sm font-semibold text-omi-text-inverse hover:bg-omi-control-border disabled:bg-omi-surface-strong"
              disabled={reloadDisabled}
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
              {isLoadingRows ? (
                <span className="omi-skeleton block h-6 w-8" />
              ) : (
                summary.upCount
              )}
            </div>
          </div>
          <div className="border-l border-omi-border-subtle px-5 py-3">
            <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.downCount")}</div>
            <div className="mt-1 text-xl font-bold text-omi-market-down">
              {isLoadingRows ? (
                <span className="omi-skeleton block h-6 w-8" />
              ) : (
                summary.downCount
              )}
            </div>
          </div>
          <div className="border-l border-omi-border-subtle px-5 py-3">
            <div className="text-xs text-omi-text-muted">{t("dashboard.ranking.sort")}</div>
            <div className="mt-1 text-xl font-bold">{rankLabel(t, rankBy)}</div>
          </div>
        </div>
      </section>

      <section className="border border-omi-border-subtle bg-omi-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-omi-border-subtle px-5 py-3">
          <h3 className="text-sm font-bold text-omi-text-strong">{t("dashboard.ranking.listTitle")}</h3>
          {showLoadingStatus ? (
            <span className="inline-flex items-center gap-2 text-xs text-omi-text-muted">
              {loadingLabel ?? t("common.loading")}
              <LoadingDots label={t("dashboard.ranking.loadingRanking")} />
            </span>
          ) : (
            <span className="text-xs text-omi-text-muted">
              {rankBy === "none"
                ? t("dashboard.ranking.rowSummaryNormal", { count: rows.length })
                : t("dashboard.ranking.rowSummaryRanked", {
                    count: rows.length,
                    rankLabel: rankLabel(t, rankBy),
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
          <span className="text-right">{volumeHeader}</span>
        </div>
        {rows.length > 0 ? (
          rows.map((row) => (
            <a
              key={row.key}
              href={row.href ?? "#"}
              data-ranking-symbol={row.symbol}
              onPointerUp={(event) => {
                if (event.button !== 0) return;
                row.onSelect();
              }}
              onMouseDown={(event) => {
                if (event.button !== 0) return;
                row.onSelect();
              }}
              onClick={(event) => {
                event.preventDefault();
                row.onSelect();
              }}
              className={[
                "omi-ranking-row grid w-full grid-cols-[46px_minmax(120px,1fr)_104px_80px_82px_72px_90px] items-center border-t border-omi-border-subtle px-4 py-2 text-left text-sm",
                row.selected
                  ? "omi-ranking-row-selected relative z-10 bg-omi-surface text-omi-text ring-1 ring-omi-market-up-border"
                  : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
              ].join(" ")}
            >
              <span className={row.selected ? "font-semibold text-omi-market-up" : "text-omi-text-muted"}>
                #{row.rank}
              </span>
              <span className="min-w-0">
                <span className="block truncate font-semibold">
                  {row.symbol} {row.name ?? ""}
                </span>
                <span className={row.selected ? "block truncate text-xs font-medium text-omi-text" : "block truncate text-xs text-omi-text-muted"}>
                  {row.loading ? <RankingCellSkeleton className="h-2.5 w-16" /> : row.meta ?? "-"}
                </span>
              </span>
              <span className="flex justify-center">
                {row.loading ? <RankingCellSkeleton className="h-5 w-16" /> : row.visual}
              </span>
              <span className="text-right font-semibold">
                {row.loading ? (
                  <RankingCellSkeleton />
                ) : (
                  <PriceUpdatePulse
                    value={row.closeValue}
                    direction={row.changePct}
                    resetKey={row.key}
                    className="justify-end tabular-nums"
                  >
                    {row.close}
                  </PriceUpdatePulse>
                )}
              </span>
              <span className={`text-right font-semibold ${valueTone(row.changePct)}`}>
                {row.loading ? (
                  <RankingCellSkeleton className="h-3 w-12" />
                ) : (
                  <PriceUpdatePulse
                    value={row.change}
                    direction={row.changePct}
                    resetKey={row.key}
                    className="justify-end tabular-nums"
                  >
                    {row.change}
                  </PriceUpdatePulse>
                )}
              </span>
              <span className="text-right">
                {row.loading ? (
                  <RankingCellSkeleton className="h-6 w-12" />
                ) : (
                  <span
                    className={[
                      "omi-ranking-trend-chip px-2 py-1 text-xs font-semibold",
                      row.selected
                        ? `omi-ranking-trend-chip-selected ${trendClass(row.changePct)}`
                        : trendClass(row.changePct),
                    ].join(" ")}
                  >
                    {row.trend}
                  </span>
                )}
              </span>
              <span className="text-right">
                {row.loading ? (
                  <RankingCellSkeleton className="h-3 w-16" />
                ) : (
                  <PriceUpdatePulse
                    value={row.volumeValue ?? row.volume}
                    direction={null}
                    resetKey={row.key}
                    className="justify-end tabular-nums"
                  >
                    {row.volume}
                  </PriceUpdatePulse>
                )}
              </span>
            </a>
          ))
        ) : isLoadingRows ? (
          <RankingLoadingRows />
        ) : (
          <div className="border-t border-omi-border-subtle p-3">
            <StateSurface title={emptyMessage} tone="empty" compact />
          </div>
        )}
      </section>
    </div>
  );
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
}: Props) {
  const t = useT();
  const refreshExecutionSettings = useRefreshExecutionSettings();
  const initialSelectedGroup = useMemo(() => {
    const groups = flattenGroups(initialTree);
    return (
      groups.find((group) => group.id === initialSelectedGroupId) ??
      groups[0] ??
      null
    );
  }, [initialTree, initialSelectedGroupId]);
  const initialSelectedUsGroup = useMemo(() => {
    const groups = flattenUsGroups(initialUsWatchlistTree);
    return (
      groups.find((group) => group.id === initialSelectedGroupId) ??
      groups[0] ??
      null
    );
  }, [initialUsWatchlistTree, initialSelectedGroupId]);
  const initialSelectedJpGroup = useMemo(() => {
    const groups = flattenJpGroups(initialJpWatchlistTree);
    return (
      groups.find((group) => group.id === initialSelectedGroupId) ??
      groups[0] ??
      null
    );
  }, [initialJpWatchlistTree, initialSelectedGroupId]);
  const initialSelectedKrGroup = useMemo(() => {
    const groups = flattenKrGroups(initialKrWatchlistTree);
    return (
      groups.find((group) => group.id === initialSelectedGroupId) ??
      groups[0] ??
      null
    );
  }, [initialKrWatchlistTree, initialSelectedGroupId]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(
    initialSelectedGroup?.id ?? null
  );
  const [selectedGroup, setSelectedGroup] = useState<WatchlistGroupNode | null>(
    initialSelectedGroup
  );
  const [selectedStockId, setSelectedStockId] = useState<string | null>(
    initialSelectedStockId
  );
  const [selectedStockName, setSelectedStockName] = useState<string | null>(
    initialSelectedStockName
  );
  const [selectedFuturesSymbol, setSelectedFuturesSymbol] = useState<string | null>(
    initialSelectedFuturesSymbol
  );
  const [watchlistTree, setWatchlistTree] = useState<WatchlistGroupNode[]>(initialTree);
  const [watchlistItems, setWatchlistItems] = useState<WatchlistItemRead[]>(initialItems);
  const [activeMarket, setActiveMarket] = useState<MarketRegion>(initialMarket);
  const [selectedCryptoBase, setSelectedCryptoBase] = useState<CryptoBaseAsset>("BTC");
  const [selectedCryptoInstrumentKey, setSelectedCryptoInstrumentKey] = useState<string | null>(null);
  const [selectedResourceInstrumentKey, setSelectedResourceInstrumentKey] = useState<string | null>(null);
  const [resourceSubscriptionSettings, setResourceSubscriptionSettings] =
    useState<MarketDataSubscriptionSettingsRead | null>(null);
  const [twChartFocusMode, setTwChartFocusMode] = useState(false);
  const [usChartFocusMode, setUsChartFocusMode] = useState(false);
  const [jpChartFocusMode, setJpChartFocusMode] = useState(false);
  const [selectedUsSymbol, setSelectedUsSymbol] = useState<string | null>(
    initialSelectedUsSymbol
  );
  const [selectedUsSecurityName, setSelectedUsSecurityName] = useState<string | null>(
    initialSelectedUsSecurityName
  );
  const [selectedUsCompanyProfile, setSelectedUsCompanyProfile] =
    useState<USCompanyProfileRead | null>(null);
  const [selectedJpSymbol, setSelectedJpSymbol] = useState<string | null>(
    initialSelectedJpSymbol
  );
  const [selectedJpStock, setSelectedJpStock] = useState<JPStockMasterRead | null>(
    null
  );
  const [selectedJpGroupId, setSelectedJpGroupId] = useState<number | null>(
    initialSelectedJpGroup?.id ?? null
  );
  const [selectedJpGroup, setSelectedJpGroup] = useState<JPWatchlistGroupNode | null>(
    initialSelectedJpGroup
  );
  const [selectedJpGroupName, setSelectedJpGroupName] = useState<string | null>(
    initialSelectedJpGroup?.group_name ?? null
  );
  const [jpWatchlistTree, setJpWatchlistTree] =
    useState<JPWatchlistGroupNode[]>(initialJpWatchlistTree);
  const [jpWatchlistItems, setJpWatchlistItems] =
    useState<JPWatchlistItemRead[]>(initialJpWatchlistItems);
  const [jpDataRefreshNonce, setJpDataRefreshNonce] = useState(0);
  const [jpRankBy, setJpRankBy] = useState<JPRankBy>("none");
  const [jpRanking, setJpRanking] = useState<JPWatchlistRankingRead | null>(null);
  const [jpLoadState, setJpLoadState] = useState<LoadState>("idle");
  const [, setJpUniverseRefreshState] =
    useState<LoadState>("idle");
  const [, setJpErrorMessage] = useState<string | null>(null);
  const [jpStatusMessage, setJpStatusMessage] = useState<JPStatusMessage>(null);
  const [jpLastUpdatedAt, setJpLastUpdatedAt] = useState<string | null>(null);
  const [selectedKrSymbol, setSelectedKrSymbol] = useState<string | null>(
    initialSelectedKrSymbol
  );
  const [selectedKrStock, setSelectedKrStock] = useState<KRStockMasterRead | null>(
    null
  );
  const [selectedKrGroupId, setSelectedKrGroupId] = useState<number | null>(
    initialSelectedKrGroup?.id ?? null
  );
  const [selectedKrGroup, setSelectedKrGroup] = useState<KRWatchlistGroupNode | null>(
    initialSelectedKrGroup
  );
  const [selectedKrGroupName, setSelectedKrGroupName] = useState<string | null>(
    initialSelectedKrGroup?.group_name ?? null
  );
  const [krWatchlistTree, setKrWatchlistTree] =
    useState<KRWatchlistGroupNode[]>(initialKrWatchlistTree);
  const [krWatchlistItems, setKrWatchlistItems] =
    useState<KRWatchlistItemRead[]>(initialKrWatchlistItems);
  const [krDataRefreshNonce, setKrDataRefreshNonce] = useState(0);
  const [krRankBy, setKrRankBy] = useState<KRRankBy>("none");
  const [krRanking, setKrRanking] = useState<KRWatchlistRankingRead | null>(null);
  const [krLoadState, setKrLoadState] = useState<LoadState>("idle");
  const [, setKrUniverseRefreshState] =
    useState<LoadState>("idle");
  const [, setKrErrorMessage] = useState<string | null>(null);
  const [krLastUpdatedAt, setKrLastUpdatedAt] = useState<string | null>(null);
  const [selectedUsGroupId, setSelectedUsGroupId] = useState<number | null>(
    initialSelectedUsGroup?.id ?? null
  );
  const [selectedUsGroup, setSelectedUsGroup] = useState<USWatchlistGroupNode | null>(
    initialSelectedUsGroup
  );
  const [selectedUsGroupName, setSelectedUsGroupName] = useState<string | null>(
    initialSelectedUsGroup?.group_name ?? null
  );
  const [usWatchlistTree, setUsWatchlistTree] =
    useState<USWatchlistGroupNode[]>(initialUsWatchlistTree);
  const [usWatchlistItems, setUsWatchlistItems] =
    useState<USWatchlistItemRead[]>(initialUsWatchlistItems);
  const [usWatchlistVersion, setUsWatchlistVersion] = useState(0);
  const [rankBy, setRankBy] = useState<RankBy>("none");
  const [ranking, setRanking] = useState<RankingResponse | null>(initialRankingData);
  const [radarMode, setRadarMode] = useState<WatchlistRadarMode>(initialRadarMode);
  const [radar, setRadar] = useState<WatchlistGroupRadarRead | null>(initialRadarData);
  const [radarOutcomeSummary, setRadarOutcomeSummary] =
    useState<WatchlistRadarOutcomeSummaryRead | null>(null);
  const [radarOutcomeHistory, setRadarOutcomeHistory] =
    useState<WatchlistRadarOutcomeSummaryRead[]>([]);
  const [radarOutcomeHistoryOpen, setRadarOutcomeHistoryOpen] = useState(false);
  const [selectedRadarOutcomeSnapshotId, setSelectedRadarOutcomeSnapshotId] =
    useState<number | null>(null);
  const [usRadarMode, setUsRadarMode] = useState<WatchlistRadarMode>(initialRadarMode);
  const [usRadar, setUsRadar] = useState<WatchlistGroupRadarRead | null>(null);
  const [jpRadarMode, setJpRadarMode] = useState<WatchlistRadarMode>(initialRadarMode);
  const [jpRadar, setJpRadar] = useState<WatchlistGroupRadarRead | null>(null);
  const [krRadarMode, setKrRadarMode] = useState<WatchlistRadarMode>(initialRadarMode);
  const [krRadar, setKrRadar] = useState<WatchlistGroupRadarRead | null>(null);
  const [usRankBy, setUsRankBy] = useState<USRankBy>("none");
  const [usRanking, setUsRanking] = useState<USWatchlistRankingRead | null>(null);
  const [marketIndexSummary, setMarketIndexSummary] =
    useState<MarketIndexSummary | null>(initialMarketIndexSummary);
  const [marketIndexLoadState, setMarketIndexLoadState] =
    useState<LoadState>(initialMarketIndexSummary ? "success" : "idle");
  const [loadState, setLoadState] = useState<LoadState>(
    initialRankingData ? "success" : "idle"
  );
  const [rankingTrendPending, setRankingTrendPending] = useState(false);
  const [radarLoadState, setRadarLoadState] = useState<LoadState>(
    initialRadarData ? "success" : "idle"
  );
  const [radarOutcomeLoadState, setRadarOutcomeLoadState] =
    useState<LoadState>("idle");
  const [radarOutcomeHistoryLoadState, setRadarOutcomeHistoryLoadState] =
    useState<LoadState>("idle");
  const [usRadarLoadState, setUsRadarLoadState] = useState<LoadState>("idle");
  const [jpRadarLoadState, setJpRadarLoadState] = useState<LoadState>("idle");
  const [krRadarLoadState, setKrRadarLoadState] = useState<LoadState>("idle");
  const [usLoadState, setUsLoadState] = useState<LoadState>("idle");
  const [, setUsUniverseRefreshState] =
    useState<LoadState>("idle");
  const [, setRadarErrorMessage] = useState<string | null>(null);
  const [, setRadarOutcomeErrorMessage] =
    useState<string | null>(null);
  const [, setRadarOutcomeHistoryErrorMessage] =
    useState<string | null>(null);
  const [, setUsRadarErrorMessage] = useState<string | null>(null);
  const [, setJpRadarErrorMessage] = useState<string | null>(null);
  const [, setKrRadarErrorMessage] = useState<string | null>(null);
  const [, setUsErrorMessage] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [usLastUpdatedAt, setUsLastUpdatedAt] = useState<string | null>(null);
  const dashboardRequestSeq = useRef(0);
  const radarRequestSeq = useRef(0);
  const radarOutcomeRequestSeq = useRef(0);
  const radarOutcomeHistoryRequestSeq = useRef(0);
  const usRadarRequestSeq = useRef(0);
  const jpRadarRequestSeq = useRef(0);
  const krRadarRequestSeq = useRef(0);
  const radarModeRef = useRef<WatchlistRadarMode>(radarMode);
  const usRadarModeRef = useRef<WatchlistRadarMode>(usRadarMode);
  const jpRadarModeRef = useRef<WatchlistRadarMode>(jpRadarMode);
  const krRadarModeRef = useRef<WatchlistRadarMode>(krRadarMode);
  const usDashboardRequestSeq = useRef(0);
  const jpDashboardRequestSeq = useRef(0);
  const krDashboardRequestSeq = useRef(0);
  const resourceBackgroundPollingRef = useRef(new Set<string>());
  const marketIndexRequestSeq = useRef(0);
  const rankingTrendTimer = useRef<number | undefined>(undefined);
  const finalDashboardRefreshDate = useRef<string | null>(null);
  const finalUsDashboardRefreshDate = useRef<string | null>(null);
  const initialUsWatchlistPreloadQueued = useRef(false);
  const resourceBackgroundPollingGroupsForCurrentView = useMemo(
    () =>
      activeMarket === "crypto"
        ? resourceBackgroundQuotePollingGroups(
            resourceSubscriptionSettings,
            selectedResourceInstrumentKey
          )
        : [],
    [activeMarket, resourceSubscriptionSettings, selectedResourceInstrumentKey]
  );

  useEffect(() => {
    if (activeMarket !== "crypto") return;

    let cancelled = false;

    async function loadResourceSubscriptionSettings() {
      try {
        const settings = await loadMarketDataSubscriptionSettings();
        if (!cancelled) {
          setResourceSubscriptionSettings(settings);
        }
      } catch {
        if (!cancelled) {
          setResourceSubscriptionSettings(null);
        }
      }
    }

    function handleSubscriptionSettingsUpdated(event: Event) {
      const nextSettings = (event as CustomEvent<MarketDataSubscriptionSettingsRead>).detail;
      if (nextSettings) {
        setResourceSubscriptionSettings(nextSettings);
      } else {
        void loadResourceSubscriptionSettings();
      }
    }

    void loadResourceSubscriptionSettings();
    window.addEventListener(
      MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
      handleSubscriptionSettingsUpdated
    );

    return () => {
      cancelled = true;
      window.removeEventListener(
        MARKET_DATA_SUBSCRIPTIONS_UPDATED_EVENT,
        handleSubscriptionSettingsUpdated
      );
    };
  }, [activeMarket]);

  useEffect(() => {
    if (activeMarket !== "crypto" || !resourceBackgroundPollingGroupsForCurrentView.length) {
      return;
    }

    const timers = resourceBackgroundPollingGroupsForCurrentView.map((group) => {
      const run = async () => {
        if (document.visibilityState !== "visible") return;
        if (resourceBackgroundPollingRef.current.has(group.key)) return;

        resourceBackgroundPollingRef.current.add(group.key);
        try {
          await requestJson<ResourceRefreshResult>(
            "/api/resource-market/quotes/refresh",
            { method: "POST" },
            { symbols: group.symbols.join(",") }
          );
        } catch {
          // Background quote polling should not replace the visible panel state.
        } finally {
          resourceBackgroundPollingRef.current.delete(group.key);
        }
      };

      return window.setInterval(run, group.intervalSeconds * 1000);
    });

    return () => {
      timers.forEach((timer) => window.clearInterval(timer));
    };
  }, [activeMarket, resourceBackgroundPollingGroupsForCurrentView]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function loadCalendarStatus() {
      try {
        await refreshMarketCalendarStatus("all");
      } catch (error) {
        console.warn("Market calendar status refresh failed.", error);
      } finally {
        if (!cancelled) {
          timer = window.setTimeout(loadCalendarStatus, 60_000);
        }
      }
    }

    void loadCalendarStatus();

    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, []);

  useEffect(() => {
    return () => {
      if (rankingTrendTimer.current !== undefined) {
        window.clearTimeout(rankingTrendTimer.current);
      }
    };
  }, []);

  const activeGroupId = selectedGroupId ?? selectedGroup?.id ?? null;
  const activeGroupIdRef = useRef<number | null>(activeGroupId);
  const selectedUsGroupIdRef = useRef<number | null>(selectedUsGroupId);
  const selectedJpGroupIdRef = useRef<number | null>(selectedJpGroupId);
  const selectedKrGroupIdRef = useRef<number | null>(selectedKrGroupId);
  const watchlistFreshnessRequestKeys = useRef<Set<string>>(new Set());
  const usWatchlistFreshnessRequestKeys = useRef<Set<string>>(new Set());
  const jpWatchlistFreshnessRequestKeys = useRef<Set<string>>(new Set());
  const krWatchlistFreshnessRequestKeys = useRef<Set<string>>(new Set());
  const marketChipRefreshRequestKeys = useRef<Set<string>>(new Set());
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
  const selectedUsIndexConfig = getUsMarketIndexConfig(selectedUsSymbol);
  const isSelectedUsIndex = selectedUsIndexConfig !== null;
  const selectedJpIndexConfig = getJpMarketIndexConfig(selectedJpSymbol);
  const isSelectedJpIndex = selectedJpIndexConfig !== null;

  function watchlistRadarParams(
    mode: WatchlistRadarMode,
    useIntraday: boolean
  ) {
    return {
      ...WATCHLIST_ANALYSIS_PARAMS,
      mode,
      max_results: WATCHLIST_RADAR_MAX_RESULTS,
      calculation_limit: 100,
      use_intraday: useIntraday,
      intraday_limit: WATCHLIST_INTRADAY_LIMIT,
    };
  }

  function watchlistTechnicalRadarParams(
    mode: WatchlistRadarMode,
    useIntraday = false
  ) {
    return {
      mode,
      max_results: WATCHLIST_RADAR_MAX_RESULTS,
      calculation_limit: 100,
      use_intraday: useIntraday,
      intraday_limit: WATCHLIST_INTRADAY_LIMIT,
    };
  }

  async function loadWatchlistRadarOutcome(
    groupId: number,
    options?: { mode?: WatchlistRadarMode; silent?: boolean }
  ) {
    const requestSeq = radarOutcomeRequestSeq.current + 1;
    radarOutcomeRequestSeq.current = requestSeq;
    const currentMode = options?.mode ?? radarModeRef.current;

    if (!options?.silent) {
      setRadarOutcomeLoadState("loading");
      setRadarOutcomeErrorMessage(null);
      setRadarOutcomeSummary(null);
    }

    try {
      const outcomeData = await fetchJson<WatchlistRadarOutcomeSummaryRead>(
        `/api/watchlists/groups/${groupId}/radar/outcomes/latest`,
        { mode: currentMode }
      );

      if (radarOutcomeRequestSeq.current !== requestSeq) return;

      setRadarOutcomeSummary(outcomeData);
      setRadarOutcomeLoadState("success");
      setRadarOutcomeErrorMessage(null);
    } catch (error) {
      if (radarOutcomeRequestSeq.current !== requestSeq) return;

      if (!options?.silent) {
        setRadarOutcomeSummary(null);
      }
      setRadarOutcomeLoadState("error");
      const message = apiErrorMessage(error, t("radar.outcome.loadError"));
      setRadarOutcomeErrorMessage(message);
      emitDashboardDataStatus({
        market: "tw",
        title: t("radar.outcome.loadError"),
        message,
        source: t("radar.outcome.title"),
        contextKey: `tw:watchlist:${groupId}:radar-outcome`,
        contextLabel: twWatchlistContextLabel,
      });
    }
  }

  async function loadWatchlistRadarOutcomeHistory(
    groupId: number,
    options?: { mode?: WatchlistRadarMode; silent?: boolean }
  ) {
    const requestSeq = radarOutcomeHistoryRequestSeq.current + 1;
    radarOutcomeHistoryRequestSeq.current = requestSeq;
    const currentMode = options?.mode ?? radarModeRef.current;

    if (!options?.silent) {
      setRadarOutcomeHistoryLoadState("loading");
      setRadarOutcomeHistoryErrorMessage(null);
    }

    try {
      const historyData = await fetchJson<WatchlistRadarOutcomeSummaryRead[]>(
        `/api/watchlists/groups/${groupId}/radar/outcomes/history`,
        { mode: currentMode, limit: 60, item_limit: 12 }
      );

      if (radarOutcomeHistoryRequestSeq.current !== requestSeq) return;

      setRadarOutcomeHistory(historyData);
      setSelectedRadarOutcomeSnapshotId((current) => {
        if (current && historyData.some((row) => row.snapshot?.id === current)) {
          return current;
        }
        return historyData[0]?.snapshot?.id ?? null;
      });
      setRadarOutcomeHistoryLoadState("success");
      setRadarOutcomeHistoryErrorMessage(null);
    } catch (error) {
      if (radarOutcomeHistoryRequestSeq.current !== requestSeq) return;

      if (!options?.silent) {
        setRadarOutcomeHistory([]);
      }
      setRadarOutcomeHistoryLoadState("error");
      const message = apiErrorMessage(error, t("radar.outcome.loadError"));
      setRadarOutcomeHistoryErrorMessage(message);
      emitDashboardDataStatus({
        market: "tw",
        title: t("radar.outcome.loadError"),
        message,
        source: t("radar.outcome.history"),
        contextKey: `tw:watchlist:${groupId}:radar-outcome-history`,
        contextLabel: twWatchlistContextLabel,
      });
    }
  }

  function openWatchlistRadarOutcomeHistory() {
    setRadarOutcomeHistoryOpen(true);
    if (activeGroupId !== null) {
      void loadWatchlistRadarOutcomeHistory(activeGroupId);
    }
  }

  async function saveWatchlistRadarSnapshot() {
    if (activeGroupId === null) return;

    const groupId = activeGroupId;
    const currentMode = radarModeRef.current;
    const marketState = getTaiwanMarketRefreshState();
    const requestSeq = radarOutcomeRequestSeq.current + 1;

    radarOutcomeRequestSeq.current = requestSeq;
    setRadarOutcomeLoadState("loading");
    setRadarOutcomeErrorMessage(null);

    try {
      const snapshot = await requestJson<WatchlistRadarSnapshotRead>(
        `/api/watchlists/groups/${groupId}/radar/snapshots`,
        { method: "POST" },
        watchlistRadarParams(
          currentMode,
          shouldUseTaiwanWatchlistIntraday(marketState)
        )
      );
      setSelectedRadarOutcomeSnapshotId(snapshot.id);
      await loadWatchlistRadarOutcome(groupId, { mode: currentMode, silent: true });
      if (radarOutcomeHistoryOpen) {
        await loadWatchlistRadarOutcomeHistory(groupId, {
          mode: currentMode,
          silent: true,
        });
      }
    } catch (error) {
      if (radarOutcomeRequestSeq.current !== requestSeq) return;

      setRadarOutcomeLoadState("error");
      const message = apiErrorMessage(error, t("radar.outcome.snapshotError"));
      setRadarOutcomeErrorMessage(message);
      emitDashboardDataStatus({
        market: "tw",
        title: t("radar.outcome.snapshotError"),
        message,
        source: t("radar.outcome.title"),
        contextKey: `tw:watchlist:${groupId}:radar-outcome`,
        contextLabel: twWatchlistContextLabel,
      });
    }
  }

  async function evaluateWatchlistRadarOutcome(snapshotRunId?: number) {
    if (activeGroupId === null) return;

    const groupId = activeGroupId;
    const currentMode = radarModeRef.current;
    const requestSeq = radarOutcomeRequestSeq.current + 1;
    radarOutcomeRequestSeq.current = requestSeq;

    setRadarOutcomeLoadState("loading");
    setRadarOutcomeErrorMessage(null);

    try {
      const outcomeData = await requestJson<WatchlistRadarOutcomeSummaryRead>(
        `/api/watchlists/groups/${groupId}/radar/outcomes/evaluate`,
        { method: "POST" },
        snapshotRunId
          ? { mode: currentMode, snapshot_run_id: snapshotRunId }
          : { mode: currentMode }
      );

      if (radarOutcomeRequestSeq.current !== requestSeq) return;

      setRadarOutcomeHistory((current) =>
        current.map((row) =>
          row.snapshot?.id === outcomeData.snapshot?.id ? outcomeData : row
        )
      );
      const latestSnapshotId =
        radarOutcomeHistory[0]?.snapshot?.id ?? radarOutcomeSummary?.snapshot?.id ?? null;
      if (!snapshotRunId || outcomeData.snapshot?.id === latestSnapshotId) {
        setRadarOutcomeSummary(outcomeData);
      }
      setSelectedRadarOutcomeSnapshotId(outcomeData.snapshot?.id ?? snapshotRunId ?? null);
      setRadarOutcomeLoadState("success");
      setRadarOutcomeErrorMessage(null);
    } catch (error) {
      if (radarOutcomeRequestSeq.current !== requestSeq) return;

      setRadarOutcomeLoadState("error");
      const message = apiErrorMessage(error, t("radar.outcome.evaluateError"));
      setRadarOutcomeErrorMessage(message);
      emitDashboardDataStatus({
        market: "tw",
        title: t("radar.outcome.evaluateError"),
        message,
        source: t("radar.outcome.title"),
        contextKey: `tw:watchlist:${groupId}:radar-outcome`,
        contextLabel: twWatchlistContextLabel,
      });
    }
  }

  function clearRankingTrendTimer() {
    if (rankingTrendTimer.current === undefined) return;

    window.clearTimeout(rankingTrendTimer.current);
    rankingTrendTimer.current = undefined;
  }

  function scheduleRankingTrendData(
    requestSeq: number,
    rankingData: RankingResponse
  ) {
    clearRankingTrendTimer();

    rankingTrendTimer.current = window.setTimeout(() => {
      rankingTrendTimer.current = undefined;

      if (dashboardRequestSeq.current !== requestSeq) return;

      setRanking(rankingData);
      setRankingTrendPending(false);
    }, 0);
  }

  async function loadWatchlistRadar(
    groupId: number,
    options?: { mode?: WatchlistRadarMode; silent?: boolean }
  ) {
    const requestSeq = radarRequestSeq.current + 1;
    radarRequestSeq.current = requestSeq;
    const currentMode = options?.mode ?? radarModeRef.current;

    if (!options?.silent) {
      setRadarLoadState("loading");
      setRadarErrorMessage(null);
      setRadar(null);
      setRadarOutcomeLoadState("loading");
      setRadarOutcomeErrorMessage(null);
      setRadarOutcomeSummary(null);
    }

    try {
      const marketState = getTaiwanMarketRefreshState();
      const radarData = await fetchJson<WatchlistGroupRadarRead>(
        `/api/watchlists/groups/${groupId}/radar`,
        watchlistRadarParams(
          currentMode,
          shouldUseTaiwanWatchlistIntraday(marketState)
        )
      );

      if (radarRequestSeq.current !== requestSeq) return;

      setRadar(radarData);
      setRadarLoadState("success");
      setRadarErrorMessage(null);
      void loadWatchlistRadarOutcome(groupId, { mode: currentMode, silent: true });
    } catch (error) {
      if (radarRequestSeq.current !== requestSeq) return;

      if (!options?.silent) {
        setRadar(null);
        setRadarOutcomeSummary(null);
        setRadarOutcomeLoadState("idle");
      }
      setRadarLoadState("error");
      const message = apiErrorMessage(error, t("radar.loadError"));
      setRadarErrorMessage(message);
      emitDashboardDataStatus({
        market: "tw",
        title: t("radar.loadError"),
        message,
        source: t("radar.title"),
        contextKey: `tw:watchlist:${groupId}:radar`,
        contextLabel: twWatchlistContextLabel,
      });
    }
  }

  async function loadUsWatchlistRadar(
    groupId: number,
    options?: { mode?: WatchlistRadarMode; silent?: boolean }
  ) {
    const requestSeq = usRadarRequestSeq.current + 1;
    usRadarRequestSeq.current = requestSeq;
    const currentMode = options?.mode ?? usRadarModeRef.current;

    if (!options?.silent) {
      setUsRadarLoadState("loading");
      setUsRadarErrorMessage(null);
      setUsRadar(null);
    }

    try {
      const marketState = getUsMarketRefreshState();
      const radarData = await fetchJson<WatchlistGroupRadarRead>(
        `/api/us-market/watchlists/groups/${groupId}/radar`,
        watchlistTechnicalRadarParams(currentMode, marketState.isPollingWindow)
      );

      if (usRadarRequestSeq.current !== requestSeq) return;

      setUsRadar(radarData);
      setUsRadarLoadState("success");
      setUsRadarErrorMessage(null);
    } catch (error) {
      if (usRadarRequestSeq.current !== requestSeq) return;

      if (!options?.silent) {
        setUsRadar(null);
      }
      setUsRadarLoadState("error");
      const message = apiErrorMessage(error, t("radar.loadError"));
      setUsRadarErrorMessage(message);
      emitDashboardDataStatus({
        market: "us",
        title: t("radar.loadError"),
        message,
        source: t("radar.title"),
        contextKey: `us:watchlist:${groupId}:radar`,
        contextLabel: usWatchlistContextLabel,
      });
    }
  }

  async function loadJpWatchlistRadar(
    groupId: number,
    options?: { mode?: WatchlistRadarMode; silent?: boolean }
  ) {
    const requestSeq = jpRadarRequestSeq.current + 1;
    jpRadarRequestSeq.current = requestSeq;
    const currentMode = options?.mode ?? jpRadarModeRef.current;

    if (!options?.silent) {
      setJpRadarLoadState("loading");
      setJpRadarErrorMessage(null);
      setJpRadar(null);
    }

    try {
      const radarData = await fetchJson<WatchlistGroupRadarRead>(
        `/api/jp-market/watchlists/groups/${groupId}/radar`,
        watchlistTechnicalRadarParams(currentMode)
      );

      if (jpRadarRequestSeq.current !== requestSeq) return;

      setJpRadar(radarData);
      setJpRadarLoadState("success");
      setJpRadarErrorMessage(null);
    } catch (error) {
      if (jpRadarRequestSeq.current !== requestSeq) return;

      if (!options?.silent) {
        setJpRadar(null);
      }
      setJpRadarLoadState("error");
      const message = apiErrorMessage(error, t("radar.loadError"));
      setJpRadarErrorMessage(message);
      emitDashboardDataStatus({
        market: "jp",
        title: t("radar.loadError"),
        message,
        source: t("radar.title"),
        contextKey: `jp:watchlist:${groupId}:radar`,
        contextLabel: jpWatchlistContextLabel,
      });
    }
  }

  async function loadKrWatchlistRadar(
    groupId: number,
    options?: { mode?: WatchlistRadarMode; silent?: boolean }
  ) {
    const requestSeq = krRadarRequestSeq.current + 1;
    krRadarRequestSeq.current = requestSeq;
    const currentMode = options?.mode ?? krRadarModeRef.current;

    if (!options?.silent) {
      setKrRadarLoadState("loading");
      setKrRadarErrorMessage(null);
      setKrRadar(null);
    }

    try {
      const radarData = await fetchJson<WatchlistGroupRadarRead>(
        `/api/kr-market/watchlists/groups/${groupId}/radar`,
        watchlistTechnicalRadarParams(currentMode)
      );

      if (krRadarRequestSeq.current !== requestSeq) return;

      setKrRadar(radarData);
      setKrRadarLoadState("success");
      setKrRadarErrorMessage(null);
    } catch (error) {
      if (krRadarRequestSeq.current !== requestSeq) return;

      if (!options?.silent) {
        setKrRadar(null);
      }
      setKrRadarLoadState("error");
      const message = apiErrorMessage(error, t("radar.loadError"));
      setKrRadarErrorMessage(message);
      emitDashboardDataStatus({
        market: "kr",
        title: t("radar.loadError"),
        message,
        source: t("radar.title"),
        contextKey: `kr:watchlist:${groupId}:radar`,
        contextLabel: krWatchlistContextLabel,
      });
    }
  }

  async function loadDashboard(
    groupId: number,
    currentRankBy = rankBy,
    options?: { silent?: boolean }
  ) {
    const requestSeq = dashboardRequestSeq.current + 1;
    dashboardRequestSeq.current = requestSeq;
    const radarSeq = radarRequestSeq.current + 1;
    radarRequestSeq.current = radarSeq;

    if (!options?.silent) {
      setLoadState("loading");
      setRadarLoadState("loading");
      setRadarErrorMessage(null);
      setRadarOutcomeLoadState("loading");
      setRadarOutcomeErrorMessage(null);
      setRadarOutcomeSummary(null);
    }

    try {
      const marketState = getTaiwanMarketRefreshState();
      const useIntraday = shouldUseTaiwanWatchlistIntraday(marketState);
      const deferTrendData = !options?.silent && currentRankBy === "none" && useIntraday;
      let radarPromise: Promise<void> | null = null;

      clearRankingTrendTimer();
      setRankingTrendPending(deferTrendData);

      function queueRadarLoad() {
        if (radarPromise) return radarPromise;

        radarPromise = fetchJson<WatchlistGroupRadarRead>(
          `/api/watchlists/groups/${groupId}/radar`,
          watchlistRadarParams(radarModeRef.current, useIntraday)
        )
          .then((data) => {
            if (radarRequestSeq.current !== radarSeq) return;

            setRadar(data);
            setRadarLoadState("success");
            setRadarErrorMessage(null);
            void loadWatchlistRadarOutcome(groupId, {
              mode: radarModeRef.current,
              silent: true,
            });
          })
          .catch((error: unknown) => {
            if (radarRequestSeq.current !== radarSeq) return;

            if (!options?.silent) {
              setRadar(null);
              setRadarOutcomeSummary(null);
              setRadarOutcomeLoadState("idle");
            }
            setRadarLoadState("error");
            const message = apiErrorMessage(error, t("radar.loadError"));
            setRadarErrorMessage(message);
            emitDashboardDataStatus({
              market: "tw",
              title: t("radar.loadError"),
              message,
              source: t("radar.title"),
              contextKey: `tw:watchlist:${groupId}:radar`,
              contextLabel: twWatchlistContextLabel,
            });
          });

        return radarPromise;
      }

      function markRadarLoadQueued() {
        if (radarPromise) return;

        void queueRadarLoad();
      }

      if (currentRankBy === "none") {
        let offset = 0;
        let loadedRows: RankingItem[] = [];
        let currentStockCount = 0;
        let staleStockCount = 0;
        let noDataCount = 0;
        let errorCount = 0;

        while (true) {
          const batch = await fetchJson<RankingBatchResponse>(
            `/api/watchlists/groups/${groupId}/rankings/latest-batch`,
            {
              ...WATCHLIST_ANALYSIS_PARAMS,
              rank_by: "watchlist",
              sort_order: "asc",
              limit: 100,
              use_intraday: useIntraday,
              intraday_limit: WATCHLIST_INTRADAY_LIMIT,
              offset,
              batch_size: WATCHLIST_RANKING_BATCH_SIZE,
            }
          );

          if (dashboardRequestSeq.current !== requestSeq) return;

          loadedRows = mergeRankingBatchRows(loadedRows, batch.results);
          currentStockCount += batch.current_stock_count;
          staleStockCount += batch.stale_stock_count;
          noDataCount += batch.no_data_count;
          errorCount += batch.error_count;

          const nextRanking = buildProgressiveRankingResponse({
            batch,
            rows: loadedRows,
            currentStockCount,
            staleStockCount,
            noDataCount,
            errorCount,
            complete: !batch.has_more,
            deferTrendData,
          });

          setRanking(nextRanking);
          markRadarLoadQueued();

          if (!batch.has_more || batch.requested_stock_count === 0) {
            setLastUpdatedAt(formatDashboardTime(new Date()));
            setLoadState("success");
            if (deferTrendData) {
              scheduleRankingTrendData(
                requestSeq,
                buildProgressiveRankingResponse({
                  batch,
                  rows: loadedRows,
                  currentStockCount,
                  staleStockCount,
                  noDataCount,
                  errorCount,
                  complete: true,
                })
              );
            }
            void radarPromise;
            return;
          }

          offset += batch.requested_stock_count;
        }
      }

      const rankingPromise = fetchJson<RankingResponse>(
        `/api/watchlists/groups/${groupId}/rankings/latest`,
        {
          ...WATCHLIST_ANALYSIS_PARAMS,
          rank_by: currentRankBy,
          sort_order: "desc",
          limit: 100,
          use_intraday: useIntraday,
          intraday_limit: WATCHLIST_INTRADAY_LIMIT,
        }
      );
      const rankingData = await rankingPromise;

      if (dashboardRequestSeq.current !== requestSeq) return;

      setRanking(rankingData);
      setRankingTrendPending(false);
      setLastUpdatedAt(formatDashboardTime(new Date()));
      setLoadState("success");
      void queueRadarLoad();
    } catch (error) {
      if (dashboardRequestSeq.current !== requestSeq) return;

      clearRankingTrendTimer();
      setRankingTrendPending(false);
      setLoadState("error");
      const message = apiErrorMessage(error, t("dashboard.ranking.readError"));
      emitDashboardDataStatus({
        market: "tw",
        title: t("dashboard.ranking.readError"),
        message,
        source: t("dashboard.ranking.listTitle"),
        contextKey: `tw:watchlist:${groupId}:ranking`,
        contextLabel: twWatchlistContextLabel,
      });
    }
  }

  async function loadUsDashboard(
    groupId: number,
    currentRankBy = usRankBy,
    options?: { silent?: boolean }
  ): Promise<USWatchlistRankingRead | null> {
    const requestSeq = usDashboardRequestSeq.current + 1;
    usDashboardRequestSeq.current = requestSeq;

    if (!options?.silent) {
      setUsLoadState("loading");
      setUsErrorMessage(null);
    }

    if (isSelectedUsIndex) {
      setUsRadar(null);
      setUsRadarLoadState("idle");
      setUsRadarErrorMessage(null);
    } else {
      void loadUsWatchlistRadar(groupId, { silent: options?.silent });
    }

    try {
      const marketState = getUsMarketRefreshState();
      const rankingData = await fetchJson<USWatchlistRankingRead>(
        "/api/us-market/watchlists/ranking",
        {
          group_id: groupId,
          include_children: true,
          enabled_only: true,
          rank_by: currentRankBy,
          sort_order: currentRankBy === "none" ? "asc" : "desc",
          use_intraday: marketState.isPollingWindow,
          intraday_limit: WATCHLIST_INTRADAY_LIMIT,
        }
      );

      if (usDashboardRequestSeq.current !== requestSeq) return null;

      setUsRanking(rankingData);
      setUsLastUpdatedAt(formatDashboardTime(new Date()));
      setUsLoadState("success");
      return rankingData;
    } catch (error) {
      if (usDashboardRequestSeq.current !== requestSeq) return null;

      setUsLoadState("error");
      const message = apiErrorMessage(error, t("dashboard.ranking.usReadError"));
      setUsErrorMessage(message);
      emitDashboardDataStatus({
        market: "us",
        title: t("dashboard.ranking.usReadError"),
        message,
        source: t("dashboard.ranking.listTitle"),
        contextKey: `us:watchlist:${groupId}:ranking`,
        contextLabel: usWatchlistContextLabel,
      });
      return null;
    }
  }

  async function loadJpDashboard(
    groupId: number,
    currentRankBy = jpRankBy,
    options?: { silent?: boolean }
  ): Promise<JPWatchlistRankingRead | null> {
    const requestSeq = jpDashboardRequestSeq.current + 1;
    jpDashboardRequestSeq.current = requestSeq;

    if (!options?.silent) {
      setJpLoadState("loading");
      setJpErrorMessage(null);
    }

    if (isSelectedJpIndex) {
      setJpRadar(null);
      setJpRadarLoadState("idle");
      setJpRadarErrorMessage(null);
    } else {
      void loadJpWatchlistRadar(groupId, { silent: options?.silent });
    }

    try {
      const rankingData = await fetchJson<JPWatchlistRankingRead>(
        "/api/jp-market/watchlists/ranking",
        {
          group_id: groupId,
          include_children: true,
          enabled_only: true,
          rank_by: currentRankBy,
          sort_order: currentRankBy === "none" ? "asc" : "desc",
        }
      );

      if (jpDashboardRequestSeq.current !== requestSeq) return null;

      setJpRanking(rankingData);
      setJpLastUpdatedAt(formatDashboardTime(new Date()));
      setJpLoadState("success");
      return rankingData;
    } catch (error) {
      if (jpDashboardRequestSeq.current !== requestSeq) return null;

      setJpLoadState("error");
      const message = apiErrorMessage(error, t("dashboard.ranking.jpReadError"));
      setJpErrorMessage(message);
      emitDashboardDataStatus({
        market: "jp",
        title: t("dashboard.ranking.jpReadError"),
        message,
        source: t("dashboard.ranking.listTitle"),
        contextKey: `jp:watchlist:${groupId}:ranking`,
        contextLabel: jpWatchlistContextLabel,
      });
      return null;
    }
  }

  async function loadKrDashboard(
    groupId: number,
    currentRankBy = krRankBy,
    options?: { silent?: boolean }
  ): Promise<KRWatchlistRankingRead | null> {
    const requestSeq = krDashboardRequestSeq.current + 1;
    krDashboardRequestSeq.current = requestSeq;

    if (!options?.silent) {
      setKrLoadState("loading");
      setKrErrorMessage(null);
    }

    void loadKrWatchlistRadar(groupId, { silent: options?.silent });

    try {
      const rankingData = await fetchJson<KRWatchlistRankingRead>(
        "/api/kr-market/watchlists/ranking",
        {
          group_id: groupId,
          include_children: true,
          enabled_only: true,
          rank_by: currentRankBy,
          sort_order: currentRankBy === "none" ? "asc" : "desc",
        }
      );

      if (krDashboardRequestSeq.current !== requestSeq) return null;

      setKrRanking(rankingData);
      setKrLastUpdatedAt(formatDashboardTime(new Date()));
      setKrLoadState("success");
      return rankingData;
    } catch (error) {
      if (krDashboardRequestSeq.current !== requestSeq) return null;

      setKrLoadState("error");
      const message = apiErrorMessage(error, t("dashboard.ranking.krReadError"));
      setKrErrorMessage(message);
      emitDashboardDataStatus({
        market: "kr",
        title: t("dashboard.ranking.krReadError"),
        message,
        source: t("dashboard.ranking.listTitle"),
        contextKey: `kr:watchlist:${groupId}:ranking`,
        contextLabel: krWatchlistContextLabel,
      });
      return null;
    }
  }

  async function loadMarketIndices(options?: { silent?: boolean }) {
    const requestSeq = marketIndexRequestSeq.current + 1;
    marketIndexRequestSeq.current = requestSeq;

    if (!options?.silent) {
      setMarketIndexLoadState("loading");
    }

    try {
      const summaryData = await fetchJson<MarketIndexSummary>("/api/market/indices/summary");

      if (marketIndexRequestSeq.current !== requestSeq) return;

      setMarketIndexSummary(summaryData);
      setMarketIndexLoadState("success");
    } catch (error) {
      if (marketIndexRequestSeq.current !== requestSeq) return;

      setMarketIndexLoadState("error");
      emitDashboardDataStatus({
        market: "tw",
        title: "市場指數載入失敗",
        message: apiErrorMessage(error, "市場指數載入失敗"),
        source: "市場環境",
        contextKey: "tw:market-index-summary",
        contextLabel: "台股市場環境",
      });
    }
  }

  async function refreshMarketChipsForFreshness(dateKey: string) {
    if (isStoredMarketChipRefreshDone(dateKey)) return;
    if (marketChipRefreshRequestKeys.current.has(dateKey)) return;

    marketChipRefreshRequestKeys.current.add(dateKey);

    try {
      const job = await requestBackfillJob(
        "/api/market/market-chips/refresh",
        { method: "POST" },
        {
          include_today: true,
          force: false,
        },
        {
          intervalMs: 1500,
          timeoutMs: 600_000,
        }
      );

      if (getJobResultStatus(job) === "success") {
        markStoredMarketChipRefreshDone(dateKey);
      }

      await loadMarketIndices({ silent: true });
    } catch (error) {
      console.warn("Market chip daily refresh failed.", error);
      emitDashboardDataStatus({
        market: "tw",
        title: "大盤資料更新失敗",
        message: apiErrorMessage(error, "大盤資料更新失敗"),
        source: "市場環境",
        contextKey: `tw:market-chip:${dateKey}`,
        contextLabel: dateKey,
      });
    }
  }

  async function refreshWatchlistDailyPricesOnOpen(groupId: number, currentRankBy: RankBy) {
    const marketState = getTaiwanMarketRefreshState();
    const includeToday = marketState.isDailyPriceReleased;
    const requestKey = `${groupId}:${marketState.dateKey}:${includeToday ? "today" : "latest"}`;

    if (watchlistFreshnessRequestKeys.current.has(requestKey)) return;

    watchlistFreshnessRequestKeys.current.add(requestKey);

    try {
      await requestBackfillJob(
        `/api/watchlists/groups/${groupId}/refresh-latest`,
        { method: "POST" },
        {
          lookback_days: 14,
          include_today: includeToday,
          include_children: true,
          enabled_only: true,
          sleep_seconds: getRefreshExecutionSeconds(
            refreshExecutionSettings,
            "tw",
            "observed_stock_refresh_interval_seconds",
            0.3
          ),
          skip_existing_months: true,
        },
        {
          intervalMs: 1500,
          timeoutMs: 600000,
        }
      );

      if (activeGroupIdRef.current === groupId) {
        await loadDashboard(groupId, currentRankBy, { silent: true });
      }
    } catch (error) {
      watchlistFreshnessRequestKeys.current.delete(requestKey);
      console.warn("Watchlist daily price refresh failed.", error);
      emitDashboardDataStatus({
        market: "tw",
        title: "自選股日線補齊失敗",
        message: apiErrorMessage(error, "自選股日線補齊失敗"),
        source: "自選股資料",
        contextKey: `tw:watchlist:${groupId}:daily-refresh`,
        contextLabel: twWatchlistContextLabel,
      });
    }
  }

  async function refreshUsWatchlistDailyPricesForFreshness(
    groupId: number,
    currentRankBy: USRankBy,
    targetTradeDate: string | null
  ) {
    const requestKey = `${groupId}:${targetTradeDate ?? "unknown"}:daily`;

    if (usWatchlistFreshnessRequestKeys.current.has(requestKey)) return;

    usWatchlistFreshnessRequestKeys.current.add(requestKey);
    setUsUniverseRefreshState("loading");

    try {
      const job = await requestBackfillJob(
        `/api/us-market/watchlists/groups/${groupId}/refresh-daily`,
        { method: "POST" },
        {
          include_children: true,
          enabled_only: true,
          outputsize: "compact",
          adjusted: false,
          sleep_seconds: getRefreshExecutionSeconds(
            refreshExecutionSettings,
            "us",
            "observed_stock_refresh_interval_seconds",
            12
          ),
        },
        {
          intervalMs: 1500,
          timeoutMs: 1_800_000,
        }
      );
      const result =
        job.result && typeof job.result === "object" && !Array.isArray(job.result)
          ? (job.result as Record<string, unknown>)
          : null;
      const errors = Array.isArray(result?.errors) ? result.errors : [];

      setUsUniverseRefreshState(errors.length > 0 ? "error" : "success");

      if (selectedUsGroupIdRef.current === groupId) {
        await loadUsDashboard(groupId, currentRankBy, { silent: true });
      }
    } catch (error) {
      setUsUniverseRefreshState("error");
      emitDashboardDataStatus({
        market: "us",
        title: "美股自選日線補齊失敗",
        message: apiErrorMessage(error, "美股自選日線補齊失敗"),
        source: "美股自選資料",
        contextKey: `us:watchlist:${groupId}:daily-refresh`,
        contextLabel: usWatchlistContextLabel,
      });
    }
  }

  async function refreshJpWatchlistDailyPricesForFreshness(
    groupId: number,
    currentRankBy: JPRankBy,
    targetTradeDate: string | null
  ) {
    const requestKey = `${groupId}:${targetTradeDate ?? "missing"}:daily`;

    if (jpWatchlistFreshnessRequestKeys.current.has(requestKey)) return;

    jpWatchlistFreshnessRequestKeys.current.add(requestKey);
    setJpUniverseRefreshState("loading");

    try {
      const job = await requestBackfillJob(
        `/api/jp-market/watchlists/groups/${groupId}/refresh-daily`,
        { method: "POST" },
        {
          include_children: true,
          enabled_only: true,
          outputsize: "compact",
          provider: "auto",
          sleep_seconds: getRefreshExecutionSeconds(
            refreshExecutionSettings,
            "jp",
            "observed_stock_refresh_interval_seconds",
            1
          ),
        },
        {
          intervalMs: 1500,
          timeoutMs: 1_800_000,
        }
      );
      const result =
        job.result && typeof job.result === "object" && !Array.isArray(job.result)
          ? (job.result as Record<string, unknown>)
          : null;
      const errors = Array.isArray(result?.errors) ? result.errors : [];

      setJpUniverseRefreshState(errors.length > 0 ? "error" : "success");

      if (selectedJpGroupIdRef.current === groupId) {
        setJpDataRefreshNonce((value) => value + 1);
        await loadJpDashboard(groupId, currentRankBy, { silent: true });
      }
    } catch (error) {
      setJpUniverseRefreshState("error");
      emitDashboardDataStatus({
        market: "jp",
        title: "日股自選日線補齊失敗",
        message: apiErrorMessage(error, "日股自選日線補齊失敗"),
        source: "日股自選資料",
        contextKey: `jp:watchlist:${groupId}:daily-refresh`,
        contextLabel: jpWatchlistContextLabel,
      });
    }
  }

  async function refreshKrWatchlistDailyPricesForFreshness(
    groupId: number,
    currentRankBy: KRRankBy,
    targetTradeDate: string | null
  ) {
    const requestKey = `${groupId}:${targetTradeDate ?? "missing"}:daily`;

    if (krWatchlistFreshnessRequestKeys.current.has(requestKey)) return;

    krWatchlistFreshnessRequestKeys.current.add(requestKey);
    setKrUniverseRefreshState("loading");

    try {
      const job = await requestBackfillJob(
        `/api/kr-market/watchlists/groups/${groupId}/refresh-daily`,
        { method: "POST" },
        {
          include_children: true,
          enabled_only: true,
          outputsize: "compact",
          provider: "auto",
          sleep_seconds: getRefreshExecutionSeconds(
            refreshExecutionSettings,
            "kr",
            "observed_stock_refresh_interval_seconds",
            1
          ),
        },
        {
          intervalMs: 1500,
          timeoutMs: 1_800_000,
        }
      );
      const result =
        job.result && typeof job.result === "object" && !Array.isArray(job.result)
          ? (job.result as Record<string, unknown>)
          : null;
      const errors = Array.isArray(result?.errors) ? result.errors : [];

      setKrUniverseRefreshState(errors.length > 0 ? "error" : "success");

      if (selectedKrGroupIdRef.current === groupId) {
        setKrDataRefreshNonce((value) => value + 1);
        await loadKrDashboard(groupId, currentRankBy, { silent: true });
      }
    } catch (error) {
      setKrUniverseRefreshState("error");
      emitDashboardDataStatus({
        market: "kr",
        title: "韓股自選日線補齊失敗",
        message: apiErrorMessage(error, "韓股自選日線補齊失敗"),
        source: "韓股自選資料",
        contextKey: `kr:watchlist:${groupId}:daily-refresh`,
        contextLabel: krWatchlistContextLabel,
      });
    }
  }

  useEffect(() => {
    activeGroupIdRef.current = activeGroupId;
  }, [activeGroupId]);

  useEffect(() => {
    radarModeRef.current = radarMode;
  }, [radarMode]);

  useEffect(() => {
    usRadarModeRef.current = usRadarMode;
  }, [usRadarMode]);

  useEffect(() => {
    jpRadarModeRef.current = jpRadarMode;
  }, [jpRadarMode]);

  useEffect(() => {
    krRadarModeRef.current = krRadarMode;
  }, [krRadarMode]);

  useEffect(() => {
    selectedUsGroupIdRef.current = selectedUsGroupId;
  }, [selectedUsGroupId]);

  useEffect(() => {
    selectedJpGroupIdRef.current = selectedJpGroupId;
  }, [selectedJpGroupId]);

  useEffect(() => {
    selectedKrGroupIdRef.current = selectedKrGroupId;
  }, [selectedKrGroupId]);

  useEffect(() => {
    if (selectedUsGroupId === null) return;
    if (activeMarket === "us") return;
    if (initialUsWatchlistPreloadQueued.current) return;

    initialUsWatchlistPreloadQueued.current = true;
    const groupId = selectedUsGroupId;
    const refreshTimer = window.setTimeout(() => {
      void loadUsDashboard(groupId, usRankBy, { silent: true }).then(
        (rankingData) => {
          if (selectedUsGroupIdRef.current !== groupId) return;
          if (rankingData?.is_current !== false) return;

          void refreshUsWatchlistDailyPricesForFreshness(
            groupId,
            usRankBy,
            rankingData.target_trade_date
          );
        }
      );
    }, 0);

    return () => {
      window.clearTimeout(refreshTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMarket, selectedUsGroupId]);

  useEffect(() => {
    if (activeMarket !== "tw") return;

    let disposed = false;
    let refreshTimer: number | undefined;

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getTaiwanMarketRefreshState();
      const delay = marketState.isPollingWindow
        ? TAIWAN_INTRADAY_REFRESH_MS
        : Math.min(marketState.msUntilNextPollingStart, 300_000);

      refreshTimer = window.setTimeout(() => {
        void loadMarketIndices({ silent: true }).finally(scheduleRefresh);
      }, delay);
    }

    const initialTimer = window.setTimeout(() => {
      void loadMarketIndices().finally(scheduleRefresh);
    }, 0);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, [activeMarket]);

  useEffect(() => {
    if (activeMarket !== "tw") return;

    let disposed = false;
    let refreshTimer: number | undefined;

    function clearRefreshTimer() {
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
    }

    function scheduleRefresh() {
      if (disposed) return;

      const state = getTaiwanMarketChipRefreshState();
      const alreadyQueued =
        marketChipRefreshRequestKeys.current.has(state.dateKey) ||
        isStoredMarketChipRefreshDone(state.dateKey);
      const delay =
        state.shouldRefreshNow && !alreadyQueued ? 0 : state.msUntilNextRefresh;

      refreshTimer = window.setTimeout(() => {
        const nextState = getTaiwanMarketChipRefreshState();
        const nextAlreadyQueued =
          marketChipRefreshRequestKeys.current.has(nextState.dateKey) ||
          isStoredMarketChipRefreshDone(nextState.dateKey);

        if (nextState.shouldRefreshNow && !nextAlreadyQueued) {
          void refreshMarketChipsForFreshness(nextState.dateKey).finally(
            scheduleRefresh
          );
          return;
        }

        scheduleRefresh();
      }, delay);
    }

    scheduleRefresh();

    return () => {
      disposed = true;
      clearRefreshTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMarket]);

  useEffect(() => {
    if (activeMarket !== "tw") return;
    if (activeGroupId === null) return;

    const groupId = activeGroupId;
    let disposed = false;
    let refreshTimer: number | undefined;

    function clearRefreshTimer() {
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
    }

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getTaiwanMarketRefreshState();

      if (marketState.isPollingWindow) {
        refreshTimer = window.setTimeout(() => {
          void loadDashboard(groupId, rankBy, { silent: true }).finally(scheduleRefresh);
        }, TAIWAN_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalDashboardRefreshDate.current !== marketState.dateKey
      ) {
        finalDashboardRefreshDate.current = marketState.dateKey;
        refreshTimer = window.setTimeout(() => {
          void loadDashboard(groupId, rankBy, { silent: true }).finally(scheduleRefresh);
        }, 0);
        return;
      }

      refreshTimer = window.setTimeout(
        scheduleRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    const initialTimer = window.setTimeout(() => {
      void loadDashboard(groupId, rankBy).finally(() => {
        const marketState = getTaiwanMarketRefreshState();

        if (marketState.isAfterClose) {
          finalDashboardRefreshDate.current = marketState.dateKey;
        }

        scheduleRefresh();
        void refreshWatchlistDailyPricesOnOpen(groupId, rankBy);
      });
    }, 120);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      clearRefreshTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeGroupId, activeMarket, rankBy]);

  useEffect(() => {
    if (activeMarket !== "tw") return;
    if (activeGroupId === null) return;

    const groupId = activeGroupId;
    let disposed = false;
    let refreshTimer: number | undefined;

    function clearRefreshTimer() {
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
    }

    function scheduleReleaseCheck(delay = getTaiwanWatchlistDailyReleaseCheckDelay()) {
      if (disposed) return;

      refreshTimer = window.setTimeout(() => {
        void checkDailyPriceRelease().finally(() => {
          if (!disposed) {
            scheduleReleaseCheck();
          }
        });
      }, delay);
    }

    async function checkDailyPriceRelease() {
      try {
        await refreshMarketCalendarStatus("tw");
      } catch (error) {
        console.warn("Taiwan calendar status refresh failed.", error);
      }

      if (disposed) return;

      const marketState = getTaiwanMarketRefreshState();

      if (marketState.isDailyPriceReleased) {
        await refreshWatchlistDailyPricesOnOpen(groupId, rankBy);
      }
    }

    scheduleReleaseCheck(0);

    return () => {
      disposed = true;
      clearRefreshTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeGroupId, activeMarket, rankBy]);

  useEffect(() => {
    if (activeMarket !== "tw") return;
    if (activeGroupId === null) return;
    if (!rankingFreshnessPending) return;

    const refreshTimer = window.setTimeout(() => {
      void refreshWatchlistDailyPricesOnOpen(activeGroupId, rankBy);
    }, 0);

    return () => {
      window.clearTimeout(refreshTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeGroupId,
    activeMarket,
    rankBy,
    ranking?.target_trade_date,
    rankingFreshnessPending,
  ]);

  useEffect(() => {
    if (activeMarket !== "us") return;
    if (selectedUsGroupId === null) return;

    const groupId = selectedUsGroupId;
    let disposed = false;
    let refreshTimer: number | undefined;

    function clearRefreshTimer() {
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
        refreshTimer = undefined;
      }
    }

    function scheduleRefresh() {
      if (disposed) return;

      const marketState = getUsMarketRefreshState();

      if (marketState.isPollingWindow) {
        refreshTimer = window.setTimeout(() => {
          void loadUsDashboard(groupId, usRankBy, { silent: true }).finally(scheduleRefresh);
        }, US_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalUsDashboardRefreshDate.current !== marketState.dateKey
      ) {
        finalUsDashboardRefreshDate.current = marketState.dateKey;
        refreshTimer = window.setTimeout(() => {
          void loadUsDashboard(groupId, usRankBy, { silent: true }).finally(scheduleRefresh);
        }, 0);
        return;
      }

      refreshTimer = window.setTimeout(
        scheduleRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    const initialTimer = window.setTimeout(() => {
      void loadUsDashboard(groupId, usRankBy).finally(() => {
        const marketState = getUsMarketRefreshState();

        if (marketState.isAfterClose) {
          finalUsDashboardRefreshDate.current = marketState.dateKey;
        }

        scheduleRefresh();
      });
    }, 120);

    return () => {
      disposed = true;
      window.clearTimeout(initialTimer);
      clearRefreshTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMarket, selectedUsGroupId, usRankBy, usWatchlistVersion]);

  useEffect(() => {
    if (activeMarket !== "us") return;
    if (selectedUsGroupId === null) return;
    if (usRanking?.is_current !== false) return;

    const refreshTimer = window.setTimeout(() => {
      void refreshUsWatchlistDailyPricesForFreshness(
        selectedUsGroupId,
        usRankBy,
        usRanking.target_trade_date
      );
    }, 0);

    return () => {
      window.clearTimeout(refreshTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeMarket,
    selectedUsGroupId,
    usRankBy,
    usRanking?.is_current,
    usRanking?.target_trade_date,
  ]);

  useEffect(() => {
    if (activeMarket !== "jp") return;
    if (selectedJpGroupId === null) return;

    const groupId = selectedJpGroupId;
    const refreshTimer = window.setTimeout(() => {
      void loadJpDashboard(groupId, jpRankBy);
    }, 120);

    return () => {
      window.clearTimeout(refreshTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMarket, selectedJpGroupId, jpRankBy, jpDataRefreshNonce]);

  useEffect(() => {
    if (activeMarket !== "jp") return;
    if (selectedJpGroupId === null) return;
    if (jpRanking?.is_current !== false) return;

    const refreshTimer = window.setTimeout(() => {
      void refreshJpWatchlistDailyPricesForFreshness(
        selectedJpGroupId,
        jpRankBy,
        jpRanking.target_trade_date
      );
    }, 0);

    return () => {
      window.clearTimeout(refreshTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeMarket,
    selectedJpGroupId,
    jpRankBy,
    jpRanking?.is_current,
    jpRanking?.target_trade_date,
  ]);

  useEffect(() => {
    if (activeMarket !== "kr") return;
    if (selectedKrGroupId === null) return;

    const groupId = selectedKrGroupId;
    const refreshTimer = window.setTimeout(() => {
      void loadKrDashboard(groupId, krRankBy);
    }, 120);

    return () => {
      window.clearTimeout(refreshTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMarket, selectedKrGroupId, krRankBy, krDataRefreshNonce]);

  useEffect(() => {
    if (activeMarket !== "kr") return;
    if (selectedKrGroupId === null) return;
    if (krRanking?.is_current !== false) return;

    const refreshTimer = window.setTimeout(() => {
      void refreshKrWatchlistDailyPricesForFreshness(
        selectedKrGroupId,
        krRankBy,
        krRanking.target_trade_date
      );
    }, 0);

    return () => {
      window.clearTimeout(refreshTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeMarket,
    selectedKrGroupId,
    krRankBy,
    krRanking?.is_current,
    krRanking?.target_trade_date,
  ]);

  function addDashboardPreviewParam(params: DashboardHrefParams) {
    if (
      quoteDepthPreviewMode &&
      (params.market === "tw" || (!params.market && activeMarket === "tw"))
    ) {
      return { ...params, quoteDepthPreviewMode };
    }

    return params;
  }

  function dashboardHref(params: DashboardHrefParams) {
    return buildDashboardHref(addDashboardPreviewParam(params));
  }

  function pushDashboardUrl(params: DashboardHrefParams) {
    if (typeof window === "undefined") return;

    window.history.pushState(null, "", dashboardHref(params));
  }

  function handleMarketChange(market: MarketRegion) {
    setActiveMarket(market);
    setUsErrorMessage(null);
    setTwChartFocusMode(false);
    setUsChartFocusMode(false);
    setJpChartFocusMode(false);
    setJpStatusMessage(null);

    if (market !== "tw") {
      setSelectedFuturesSymbol(null);
    }

    if (market === "tw") {
      if (selectedFuturesSymbol) {
        pushDashboardUrl({ market: "tw", futuresSymbol: selectedFuturesSymbol });
      } else {
        pushDashboardUrl({
          market: "tw",
          groupId: activeGroupId,
          stockId: selectedStockId,
          radarMode,
        });
      }
      return;
    }

    if (market === "us") {
      const fallbackGroup = selectedUsGroup ?? flattenUsGroups(usWatchlistTree)[0] ?? null;
      ensureSelectedUsGroup();
      pushDashboardUrl({
        market: "us",
        groupId: fallbackGroup?.id ?? null,
        symbol: selectedUsSymbol,
      });
      return;
    }

    if (market === "jp") {
      const fallbackGroup = selectedJpGroup ?? flattenJpGroups(jpWatchlistTree)[0] ?? null;
      ensureSelectedJpGroup();
      pushDashboardUrl({
        market: "jp",
        groupId: fallbackGroup?.id ?? null,
        jpSymbol: selectedJpSymbol,
      });
      return;
    }

    if (market === "kr") {
      const fallbackGroup = selectedKrGroup ?? flattenKrGroups(krWatchlistTree)[0] ?? null;
      ensureSelectedKrGroup();
      pushDashboardUrl({
        market: "kr",
        groupId: fallbackGroup?.id ?? null,
        krSymbol: selectedKrSymbol,
      });
      return;
    }

    if (market === "crypto") {
      pushDashboardUrl({ market: "crypto" });
    }
  }

  function handleSelectGroup(group: WatchlistGroupNode | null) {
    setSelectedGroup(group);
    setSelectedGroupId(group?.id ?? null);
    setSelectedFuturesSymbol(null);
    setTwChartFocusMode(false);

    if (group !== null) {
      setSelectedStockId(null);
      setSelectedStockName(null);
      setRanking(null);
      setRadar(null);
      setLoadState("idle");
      setRadarLoadState("idle");
      setRadarErrorMessage(null);
      setRadarOutcomeSummary(null);
      setRadarOutcomeLoadState("idle");
      setRadarOutcomeErrorMessage(null);
      setRadarOutcomeHistory([]);
      setRadarOutcomeHistoryLoadState("idle");
      setRadarOutcomeHistoryErrorMessage(null);
      setRadarOutcomeHistoryOpen(false);
      setSelectedRadarOutcomeSnapshotId(null);
      pushDashboardUrl({ market: "tw", groupId: group.id, radarMode });
    } else {
      setRanking(null);
      setRadar(null);
      setRadarLoadState("idle");
      setRadarErrorMessage(null);
      setRadarOutcomeSummary(null);
      setRadarOutcomeLoadState("idle");
      setRadarOutcomeErrorMessage(null);
      setRadarOutcomeHistory([]);
      setRadarOutcomeHistoryLoadState("idle");
      setRadarOutcomeHistoryErrorMessage(null);
      setRadarOutcomeHistoryOpen(false);
      setSelectedRadarOutcomeSnapshotId(null);
      pushDashboardUrl({ market: "tw" });
    }
  }

  function handleSelectStock(stockId: string, stockName: string | null) {
    setSelectedStockId(stockId);
    setSelectedStockName(stockName);
    setSelectedFuturesSymbol(null);
    setTwChartFocusMode(false);
    pushDashboardUrl({ market: "tw", groupId: activeGroupId, stockId, radarMode });
  }

  function handleSelectTaiwanFutures(symbol: string) {
    const normalizedSymbol = symbol.trim().toUpperCase();

    if (!normalizedSymbol) return;

    setSelectedStockId(null);
    setSelectedStockName(null);
    setSelectedFuturesSymbol(normalizedSymbol);
    setTwChartFocusMode(false);
    pushDashboardUrl({
      market: "tw",
      futuresSymbol: normalizedSymbol,
    });
  }

  function handleSelectUsGroup(group: USWatchlistGroupNode | null) {
    setSelectedUsGroupId(group?.id ?? null);
    setSelectedUsGroup(group);
    setSelectedUsGroupName(group?.group_name ?? null);
    setSelectedUsSymbol(null);
    setSelectedUsSecurityName(null);
    setUsRanking(null);
    setUsRadar(null);
    setUsLoadState("idle");
    setUsRadarLoadState("idle");
    setUsErrorMessage(null);
    setUsRadarErrorMessage(null);
    setUsChartFocusMode(false);
    pushDashboardUrl({ market: "us", groupId: group?.id ?? null });
  }

  function handleSelectUsSymbol(symbol: string, securityName: string | null) {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!normalizedSymbol) return;

    setSelectedUsSymbol(normalizedSymbol);
    setSelectedUsSecurityName(securityName);
    setUsErrorMessage(null);
    setUsChartFocusMode(false);
    pushDashboardUrl({ market: "us", symbol: normalizedSymbol });
  }

  function handleSelectJpGroup(group: JPWatchlistGroupNode | null) {
    setSelectedJpGroupId(group?.id ?? null);
    setSelectedJpGroup(group);
    setSelectedJpGroupName(group?.group_name ?? null);
    setSelectedJpSymbol(null);
    setSelectedJpStock(null);
    setJpRanking(null);
    setJpRadar(null);
    setJpLoadState("idle");
    setJpRadarLoadState("idle");
    setJpErrorMessage(null);
    setJpRadarErrorMessage(null);
    setJpChartFocusMode(false);
    setJpStatusMessage(null);
    pushDashboardUrl({ market: "jp", groupId: group?.id ?? null });
  }

  function handleSelectJpSymbol(symbol: string, securityName: string | null) {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!normalizedSymbol) return;

    const indexConfig = getJpMarketIndexConfig(normalizedSymbol);
    setJpChartFocusMode(false);
    setJpStatusMessage(null);
    setSelectedJpSymbol(normalizedSymbol);
    setSelectedJpStock((current) =>
      current?.symbol === normalizedSymbol
        ? current
        : ({
            id: 0,
            symbol: normalizedSymbol,
            local_code: null,
            security_name: indexConfig?.name ?? securityName,
            exchange: indexConfig?.exchange ?? null,
            market_segment: null,
            sector_33_code: null,
            sector_33_name: null,
            sector_17_code: null,
            sector_17_name: null,
            size_code: null,
            size_name: null,
            asset_type: indexConfig ? "index" : "stock",
            listing_source: indexConfig ? "market_index_config" : "watchlist",
            currency: "JPY",
            exchange_timezone_name: null,
            is_active: true,
            first_seen_at: "",
            last_seen_at: "",
            created_at: "",
            updated_at: "",
          } satisfies JPStockMasterRead)
    );
    pushDashboardUrl({
      market: "jp",
      groupId: selectedJpGroupId,
      jpSymbol: normalizedSymbol,
    });
  }

  function handleSelectJpStock(stock: JPStockMasterRead | null) {
    setSelectedJpStock(stock);
    setSelectedJpSymbol(stock?.symbol ?? null);
    setJpChartFocusMode(false);
    setJpStatusMessage(null);

    if (stock) {
      pushDashboardUrl({ market: "jp", groupId: selectedJpGroupId, jpSymbol: stock.symbol });
    } else {
      pushDashboardUrl({ market: "jp", groupId: selectedJpGroupId });
    }
  }

  function ensureSelectedJpGroup() {
    const fallbackGroup = selectedJpGroup ?? flattenJpGroups(jpWatchlistTree)[0] ?? null;

    if (fallbackGroup !== selectedJpGroup) {
      setSelectedJpGroup(fallbackGroup);
      setSelectedJpGroupId(fallbackGroup?.id ?? null);
      setSelectedJpGroupName(fallbackGroup?.group_name ?? null);
    }
  }

  function handleSelectKrGroup(group: KRWatchlistGroupNode | null) {
    setSelectedKrGroupId(group?.id ?? null);
    setSelectedKrGroup(group);
    setSelectedKrGroupName(group?.group_name ?? null);
    setSelectedKrSymbol(null);
    setSelectedKrStock(null);
    setKrRanking(null);
    setKrRadar(null);
    setKrLoadState("idle");
    setKrRadarLoadState("idle");
    setKrErrorMessage(null);
    setKrRadarErrorMessage(null);
    pushDashboardUrl({ market: "kr", groupId: group?.id ?? null });
  }

  function handleSelectKrSymbol(symbol: string, securityName: string | null) {
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!normalizedSymbol) return;

    const indexConfig = getKrMarketIndexConfig(normalizedSymbol);
    const resolvedSymbol = indexConfig?.symbol ?? normalizedSymbol;
    setSelectedKrSymbol(resolvedSymbol);
    setSelectedKrStock((current) =>
      current?.symbol === resolvedSymbol
        ? current
        : ({
            id: 0,
            symbol: resolvedSymbol,
            local_code: indexConfig?.indexId ?? null,
            security_name: indexConfig?.name ?? securityName,
            security_name_kr: indexConfig?.nameKr ?? null,
            exchange: indexConfig?.exchange ?? null,
            market_segment: indexConfig?.marketSegment ?? null,
            sector: null,
            industry: null,
            asset_type: indexConfig ? "index" : "stock",
            listing_source: indexConfig ? "market_index_config" : "watchlist",
            currency: "KRW",
            exchange_timezone_name: "Asia/Seoul",
            is_active: true,
            first_seen_at: "",
            last_seen_at: "",
            created_at: "",
            updated_at: "",
          } satisfies KRStockMasterRead)
    );
    pushDashboardUrl({
      market: "kr",
      groupId: selectedKrGroupId,
      krSymbol: resolvedSymbol,
    });
  }

  function handleSelectKrStock(stock: KRStockMasterRead | null) {
    setSelectedKrStock(stock);
    setSelectedKrSymbol(stock?.symbol ?? null);

    if (stock) {
      pushDashboardUrl({ market: "kr", groupId: selectedKrGroupId, krSymbol: stock.symbol });
    } else {
      pushDashboardUrl({ market: "kr", groupId: selectedKrGroupId });
    }
  }

  function ensureSelectedKrGroup() {
    const fallbackGroup = selectedKrGroup ?? flattenKrGroups(krWatchlistTree)[0] ?? null;

    if (fallbackGroup !== selectedKrGroup) {
      setSelectedKrGroup(fallbackGroup);
      setSelectedKrGroupId(fallbackGroup?.id ?? null);
      setSelectedKrGroupName(fallbackGroup?.group_name ?? null);
    }
  }

  function ensureSelectedUsGroup() {
    const fallbackGroup = selectedUsGroup ?? flattenUsGroups(usWatchlistTree)[0] ?? null;

    if (fallbackGroup !== selectedUsGroup) {
      setSelectedUsGroup(fallbackGroup);
      setSelectedUsGroupId(fallbackGroup?.id ?? null);
      setSelectedUsGroupName(fallbackGroup?.group_name ?? null);
    }
  }

  function handleRankByChange(value: RankBy) {
    setRankBy(value);
    setRanking(null);
    setLoadState("idle");
  }

  function handleRadarModeChange(value: WatchlistRadarMode) {
    radarModeRef.current = value;
    setRadarMode(value);
    setRadarOutcomeHistory([]);
    setRadarOutcomeHistoryLoadState("idle");
    setRadarOutcomeHistoryErrorMessage(null);
    setRadarOutcomeHistoryOpen(false);
    setSelectedRadarOutcomeSnapshotId(null);
    pushDashboardUrl({
      market: "tw",
      groupId: activeGroupId,
      stockId: selectedStockId,
      radarMode: value,
    });
    if (activeGroupId !== null) {
      void loadWatchlistRadar(activeGroupId, { mode: value });
    }
  }

  function handleUsRadarModeChange(value: WatchlistRadarMode) {
    usRadarModeRef.current = value;
    setUsRadarMode(value);
    pushDashboardUrl({
      market: "us",
      groupId: selectedUsGroupId,
      symbol: selectedUsSymbol,
    });
    if (selectedUsGroupId !== null) {
      void loadUsWatchlistRadar(selectedUsGroupId, { mode: value });
    }
  }

  function handleJpRadarModeChange(value: WatchlistRadarMode) {
    jpRadarModeRef.current = value;
    setJpRadarMode(value);
    pushDashboardUrl({
      market: "jp",
      groupId: selectedJpGroupId,
      jpSymbol: selectedJpSymbol,
    });
    if (selectedJpGroupId !== null) {
      void loadJpWatchlistRadar(selectedJpGroupId, { mode: value });
    }
  }

  function handleKrRadarModeChange(value: WatchlistRadarMode) {
    krRadarModeRef.current = value;
    setKrRadarMode(value);
    pushDashboardUrl({
      market: "kr",
      groupId: selectedKrGroupId,
      krSymbol: selectedKrSymbol,
    });
    if (selectedKrGroupId !== null) {
      void loadKrWatchlistRadar(selectedKrGroupId, { mode: value });
    }
  }

  function handleUsRankByChange(value: string) {
    setUsRankBy(value as USRankBy);
    setUsRanking(null);
    setUsLoadState("idle");
    setUsErrorMessage(null);
  }

  function handleJpRankByChange(value: string) {
    setJpRankBy(value as JPRankBy);
    setJpRanking(null);
    setJpLoadState("idle");
    setJpErrorMessage(null);
  }

  function handleKrRankByChange(value: string) {
    setKrRankBy(value as KRRankBy);
    setKrRanking(null);
    setKrLoadState("idle");
    setKrErrorMessage(null);
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
          handleSelectStock(row.stock_id, row.stock_name);
        }}
        onMouseDown={(event) => {
          if (event.button !== 0) return;
          handleSelectStock(row.stock_id, row.stock_name);
        }}
        onClick={(event) => {
          event.preventDefault();
          handleSelectStock(row.stock_id, row.stock_name);
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
            void loadWatchlistRadar(activeGroupId);
          }
        }}
        onSaveSnapshot={() => {
          void saveWatchlistRadarSnapshot();
        }}
        onEvaluateOutcome={() => {
          void evaluateWatchlistRadarOutcome();
        }}
        onReloadOutcome={() => {
          if (activeGroupId !== null) {
            void loadWatchlistRadarOutcome(activeGroupId);
          }
        }}
        onOpenOutcomeHistory={openWatchlistRadarOutcomeHistory}
        onCloseOutcomeHistory={() => {
          setRadarOutcomeHistoryOpen(false);
        }}
        onReloadOutcomeHistory={() => {
          if (activeGroupId !== null) {
            void loadWatchlistRadarOutcomeHistory(activeGroupId);
          }
        }}
        onSelectOutcomeSnapshot={setSelectedRadarOutcomeSnapshotId}
        onEvaluateOutcomeSnapshot={(snapshotRunId) => {
          void evaluateWatchlistRadarOutcome(snapshotRunId);
        }}
        onSelectStock={handleSelectStock}
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
      onSelect: () => handleSelectUsSymbol(row.symbol, row.security_name),
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
              void loadUsWatchlistRadar(selectedUsGroupId);
            }
          }}
          onSelectStock={handleSelectUsSymbol}
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
      onSelect: () => handleSelectJpSymbol(row.symbol, row.security_name),
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
              void loadJpWatchlistRadar(selectedJpGroupId);
            }
          }}
          onSelectStock={handleSelectJpSymbol}
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
      onSelect: () => handleSelectKrSymbol(row.symbol, row.security_name),
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
            void loadKrWatchlistRadar(selectedKrGroupId);
          }
        }}
        onSelectStock={handleSelectKrSymbol}
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

  const omiAskContext = useMemo<OmiAskDockContext>(() => {
    if (activeMarket === "us") {
      if (selectedUsSymbol) {
        return {
          market: "us",
          label: `${selectedUsSymbol}${selectedUsSecurityName ? ` ${selectedUsSecurityName}` : ""}`,
          target: {
            type: "us_stock",
            id: selectedUsSymbol,
            label: selectedUsSecurityName ?? selectedUsSymbol,
            market: "US",
          },
          uiContext: {
            market: "us",
            selected_symbol: selectedUsSymbol,
            selected_security_name: selectedUsSecurityName,
            selected_group_id: selectedUsGroupId,
            selected_group_name: selectedUsGroupName,
          },
        };
      }

      return {
        market: "us",
        label: selectedUsGroupName
          ? t("dashboard.ranking.usLabel", { groupName: selectedUsGroupName })
          : t("dashboard.ranking.usMarket"),
        target: {
          type: "auto",
          market: "US",
          label: selectedUsGroupName ?? t("dashboard.ranking.usMarket"),
        },
        uiContext: {
          market: "us",
          selected_group_id: selectedUsGroupId,
          selected_group_name: selectedUsGroupName,
        },
      };
    }

    if (activeMarket === "jp") {
      if (selectedJpSymbol) {
        const selectedJpIndexConfig = getJpMarketIndexConfig(selectedJpSymbol);

        return {
          market: "jp",
          label: `${selectedJpSymbol}${
            selectedJpStock?.security_name ? ` ${selectedJpStock.security_name}` : ""
          }`,
          target: {
            type: selectedJpIndexConfig ? "jp_index" : "jp_stock",
            id: selectedJpSymbol,
            label: selectedJpIndexConfig?.name ?? selectedJpStock?.security_name ?? selectedJpSymbol,
            market: "JP",
          },
          uiContext: {
            market: "jp",
            selected_symbol: selectedJpSymbol,
            selected_security_name: selectedJpStock?.security_name ?? null,
            selected_market_segment: selectedJpStock?.market_segment ?? null,
            selected_sector: selectedJpStock?.sector_33_name ?? null,
            selected_group_id: selectedJpGroupId,
            selected_group_name: selectedJpGroupName,
          },
        };
      }

      return {
        market: "jp",
        label: t("jpMarket.askMarketLabel"),
        target: {
          type: "market",
          market: "JP",
          label: t("jpMarket.askMarketLabel"),
        },
        uiContext: {
          market: "jp",
          selected_group_id: selectedJpGroupId,
          selected_group_name: selectedJpGroupName,
        },
      };
    }

    if (activeMarket === "kr") {
      if (selectedKrSymbol) {
        const selectedKrIndexConfig = getKrMarketIndexConfig(selectedKrSymbol);
        return {
          market: "kr",
          label: `${selectedKrSymbol}${
            selectedKrStock?.security_name ? ` ${selectedKrStock.security_name}` : ""
          }`,
          target: {
            type: selectedKrIndexConfig ? "kr_index" : "kr_stock",
            id: selectedKrSymbol,
            label: selectedKrIndexConfig?.name ?? selectedKrStock?.security_name ?? selectedKrSymbol,
            market: "KR",
          },
          uiContext: {
            market: "kr",
            selected_symbol: selectedKrSymbol,
            selected_security_name: selectedKrStock?.security_name ?? null,
            selected_market_segment: selectedKrStock?.market_segment ?? null,
            selected_sector: selectedKrStock?.sector ?? null,
            selected_group_id: selectedKrGroupId,
            selected_group_name: selectedKrGroupName,
          },
        };
      }

      return {
        market: "kr",
        label: t("krMarket.askMarketLabel"),
        target: {
          type: "market",
          market: "KR",
          label: t("krMarket.askMarketLabel"),
        },
        uiContext: {
          market: "kr",
          selected_group_id: selectedKrGroupId,
          selected_group_name: selectedKrGroupName,
        },
      };
    }

    if (selectedFuturesSymbol) {
      const futuresLabel = `${selectedFuturesSymbol} ${t("futures.productTitle")}`;

      return {
        market: "tw",
        label: futuresLabel,
        target: {
          type: "tw_futures",
          id: selectedFuturesSymbol,
          label: futuresLabel,
          market: "TW",
        },
        uiContext: {
          market: "tw",
          selected_futures_symbol: selectedFuturesSymbol,
          selected_group_id: activeGroupId,
          selected_group_name: selectedGroup?.group_name ?? null,
        },
      };
    }

    if (selectedStockId) {
      const isIndexTarget = TAIWAN_INDEX_TARGET_IDS.has(selectedStockId);
      return {
        market: "tw",
        label: `${selectedStockId}${selectedStockName ? ` ${selectedStockName}` : ""}`,
        target: {
          type: isIndexTarget ? "tw_index" : "tw_stock",
          id: selectedStockId,
          label: selectedStockName ?? selectedStockId,
          market: "TW",
        },
        uiContext: {
          market: "tw",
          [isIndexTarget ? "selected_index_id" : "selected_stock_id"]: selectedStockId,
          [isIndexTarget ? "selected_index_name" : "selected_stock_name"]: selectedStockName,
          selected_group_id: activeGroupId,
          selected_group_name: selectedGroup?.group_name ?? null,
        },
      };
    }

    if (activeGroupId !== null) {
      const groupLabel = selectedGroup?.group_name ?? String(activeGroupId);

      return {
        market: "tw",
        label: t("dashboard.ranking.twLabel", { groupName: groupLabel }),
        target: {
          type: "tw_watchlist",
          id: String(activeGroupId),
          label: groupLabel,
          market: "TW",
        },
        uiContext: {
          market: "tw",
          selected_group_id: activeGroupId,
          selected_group_name: selectedGroup?.group_name ?? null,
        },
      };
    }

    return {
      market: activeMarket,
      label:
        activeMarket === "tw"
          ? t("dashboard.ranking.twMarket")
          : t("dashboard.ranking.genericMarket", {
              market: activeMarket.toUpperCase(),
            }),
      target: {
        type: "auto",
        market: activeMarket.toUpperCase(),
      },
      uiContext: {
        market: activeMarket,
      },
    };
  }, [
    activeGroupId,
    activeMarket,
    selectedGroup?.group_name,
    selectedFuturesSymbol,
    selectedJpGroupId,
    selectedJpGroupName,
    selectedJpStock,
    selectedJpSymbol,
    selectedKrGroupId,
    selectedKrGroupName,
    selectedKrStock,
    selectedKrSymbol,
    selectedStockId,
    selectedStockName,
    selectedUsGroupId,
    selectedUsGroupName,
    selectedUsSecurityName,
    selectedUsSymbol,
    t,
  ]);

  return (
    <main className="h-screen overflow-hidden bg-omi-canvas text-omi-text-strong">
      <div className="flex h-full w-full flex-col lg:min-w-[1180px]">
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          {activeMarket === "us" ? (
            <USWatchlistSidebar
              initialTree={usWatchlistTree}
              initialItems={usWatchlistItems}
              selectedMarket={activeMarket}
              selectedSymbol={selectedUsSymbol}
              onMarketChange={handleMarketChange}
              onSelectGroup={handleSelectUsGroup}
              onSelectSymbol={(symbol, securityName) => {
                handleSelectUsSymbol(symbol, securityName);
              }}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setUsWatchlistTree(nextTree);
                setUsWatchlistItems(nextItems);

                const nextSelectedGroup =
                  flattenUsGroups(nextTree).find((group) => group.id === selectedUsGroupId) ??
                  flattenUsGroups(nextTree)[0] ??
                  null;
                const rowsForNextGroup = buildUsWatchlistRows(nextSelectedGroup, nextItems);
                const selectedSymbolKey = selectedUsSymbol?.toUpperCase() ?? null;
                const nextSelectedRow =
                  selectedSymbolKey === null
                    ? null
                    : rowsForNextGroup.find((row) => row.symbol === selectedSymbolKey) ?? null;
                const selectedIndexConfig = getUsMarketIndexConfig(selectedUsSymbol);

                setSelectedUsGroup(nextSelectedGroup);
                setSelectedUsGroupId(nextSelectedGroup?.id ?? null);
                setSelectedUsGroupName(nextSelectedGroup?.group_name ?? null);

                if (selectedIndexConfig) {
                  setSelectedUsSymbol(selectedIndexConfig.symbol);
                  setSelectedUsSecurityName(selectedIndexConfig.name);
                } else if (selectedSymbolKey !== null && nextSelectedRow === null) {
                  setSelectedUsSymbol(null);
                  setSelectedUsSecurityName(null);
                } else if (
                  nextSelectedRow !== null &&
                  nextSelectedRow.security_name !== selectedUsSecurityName
                ) {
                  setSelectedUsSecurityName(nextSelectedRow.security_name);
                }
              }}
              onChanged={() => {
                setUsRadar(null);
                setUsRadarLoadState("idle");
                setUsRadarErrorMessage(null);
                setUsWatchlistVersion((version) => version + 1);
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
              externalStatusMessage={jpStatusMessage}
              onMarketChange={handleMarketChange}
              onSelectGroup={handleSelectJpGroup}
              onSelectSymbol={handleSelectJpSymbol}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setJpWatchlistTree(nextTree);
                setJpWatchlistItems(nextItems);
                setJpRadar(null);
                setJpRadarLoadState("idle");
                setJpRadarErrorMessage(null);
                setJpDataRefreshNonce((value) => value + 1);

                const nextSelectedGroup =
                  flattenJpGroups(nextTree).find((group) => group.id === selectedJpGroupId) ??
                  flattenJpGroups(nextTree)[0] ??
                  null;
                const selectedSymbolKey = selectedJpSymbol?.toUpperCase() ?? null;
                const nextSelectedRow =
                  selectedSymbolKey === null
                    ? null
                    : nextItems.find((item) => item.symbol === selectedSymbolKey) ?? null;

                setSelectedJpGroup(nextSelectedGroup);
                setSelectedJpGroupId(nextSelectedGroup?.id ?? null);
                setSelectedJpGroupName(nextSelectedGroup?.group_name ?? null);

                if (selectedSymbolKey !== null && nextSelectedRow === null) {
                  setSelectedJpSymbol(null);
                  setSelectedJpStock(null);
                } else if (
                  nextSelectedRow !== null &&
                  nextSelectedRow.security_name !== selectedJpStock?.security_name
                ) {
                  handleSelectJpSymbol(nextSelectedRow.symbol, nextSelectedRow.security_name);
                }
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
              onSelectGroup={handleSelectKrGroup}
              onSelectSymbol={handleSelectKrSymbol}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setKrWatchlistTree(nextTree);
                setKrWatchlistItems(nextItems);
                setKrRadar(null);
                setKrRadarLoadState("idle");
                setKrRadarErrorMessage(null);
                setKrDataRefreshNonce((value) => value + 1);

                const nextSelectedGroup =
                  flattenKrGroups(nextTree).find((group) => group.id === selectedKrGroupId) ??
                  flattenKrGroups(nextTree)[0] ??
                  null;
                const selectedSymbolKey = selectedKrSymbol?.toUpperCase() ?? null;
                const nextSelectedRow =
                  selectedSymbolKey === null
                    ? null
                    : nextItems.find((item) => item.symbol === selectedSymbolKey) ?? null;
                const selectedIndexConfig = getKrMarketIndexConfig(selectedKrSymbol);

                setSelectedKrGroup(nextSelectedGroup);
                setSelectedKrGroupId(nextSelectedGroup?.id ?? null);
                setSelectedKrGroupName(nextSelectedGroup?.group_name ?? null);

                if (selectedIndexConfig) {
                  setSelectedKrSymbol(selectedIndexConfig.symbol);
                  setSelectedKrStock((current) =>
                    current?.symbol === selectedIndexConfig.symbol
                      ? current
                      : ({
                          id: 0,
                          symbol: selectedIndexConfig.symbol,
                          local_code: selectedIndexConfig.indexId,
                          security_name: selectedIndexConfig.name,
                          security_name_kr: selectedIndexConfig.nameKr,
                          exchange: selectedIndexConfig.exchange,
                          market_segment: selectedIndexConfig.marketSegment,
                          sector: null,
                          industry: null,
                          asset_type: "index",
                          listing_source: "market_index_config",
                          currency: "KRW",
                          exchange_timezone_name: "Asia/Seoul",
                          is_active: true,
                          first_seen_at: "",
                          last_seen_at: "",
                          created_at: "",
                          updated_at: "",
                        } satisfies KRStockMasterRead)
                  );
                } else if (selectedSymbolKey !== null && nextSelectedRow === null) {
                  setSelectedKrSymbol(null);
                  setSelectedKrStock(null);
                } else if (
                  nextSelectedRow !== null &&
                  (nextSelectedRow.security_name ?? nextSelectedRow.security_name_kr) !==
                    selectedKrStock?.security_name
                ) {
                  handleSelectKrSymbol(
                    nextSelectedRow.symbol,
                    nextSelectedRow.security_name ?? nextSelectedRow.security_name_kr
                  );
                }
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
                handleSelectGroup(group);
              }}
              onSelectStock={(stockId, stockName) => {
                if (activeMarket !== "tw") return;
                handleSelectStock(stockId, stockName);
              }}
              onSelectFutures={(symbol) => {
                if (activeMarket !== "tw") return;
                handleSelectTaiwanFutures(symbol);
              }}
              onSelectCryptoInstrument={(base, instrumentKey) => {
                setSelectedCryptoBase(base);
                setSelectedCryptoInstrumentKey(instrumentKey);
                setSelectedResourceInstrumentKey(null);
              }}
              onSelectResourceInstrument={(instrument) => {
                setSelectedResourceInstrumentKey(instrument.key);
              }}
              onMarketChange={handleMarketChange}
              onExplorerDataChanged={(nextTree, nextItems) => {
                setWatchlistTree(nextTree);
                setWatchlistItems(nextItems);

                const nextSelectedGroup =
                  flattenGroups(nextTree).find((group) => group.id === activeGroupId) ?? null;

                if (activeMarket === "tw" && nextSelectedGroup) {
                  setSelectedGroup(nextSelectedGroup);
                }
              }}
              onChanged={(nextGroupId) => {
                if (activeMarket !== "tw") return;

                const groupId = nextGroupId === undefined ? activeGroupId : nextGroupId;
                if (groupId !== null) {
                  void loadDashboard(groupId);
                } else {
                  setRanking(null);
                  setRadar(null);
                  setRadarLoadState("idle");
                  setRadarErrorMessage(null);
                  setRadarOutcomeSummary(null);
                  setRadarOutcomeLoadState("idle");
                  setRadarOutcomeErrorMessage(null);
                  setRadarOutcomeHistory([]);
                  setRadarOutcomeHistoryLoadState("idle");
                  setRadarOutcomeHistoryErrorMessage(null);
                  setRadarOutcomeHistoryOpen(false);
                  setSelectedRadarOutcomeSnapshotId(null);
                }
              }}
            />
          )}

          <section className="min-w-0 flex-1 overflow-y-auto p-4">
            {activeMarket === "tw" ? (
              <>
                <div className={twChartFocusMode ? "hidden" : ""}>
                  <MarketTape summary={marketIndexSummary} loadState={marketIndexLoadState} />
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
                  />
                </div>
                <JPMarketPanel
                  initialSymbol={selectedJpSymbol}
                  refreshNonce={jpDataRefreshNonce}
                  watchlistRankingPanel={isSelectedJpIndex ? undefined : jpRankingPanel}
                  onChartFocusModeChange={setJpChartFocusMode}
                  onSelectStock={handleSelectJpStock}
                  onStatusMessage={setJpStatusMessage}
                />
              </>
            ) : activeMarket === "kr" ? (
              <>
                <KRMarketTape
                  selectedSymbol={selectedKrSymbol}
                  selectedStock={selectedKrStock}
                  selectedGroupName={selectedKrGroupName}
                />
                <KRMarketPanel
                  initialSymbol={selectedKrSymbol}
                  selectedGroupId={selectedKrGroupId}
                  refreshNonce={krDataRefreshNonce}
                  watchlistRankingPanel={krRankingPanel}
                  onSelectStock={handleSelectKrStock}
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

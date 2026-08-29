import MarketDashboardClient from "@/components/MarketDashboardClient";
import { normalizeDashboardRadarMode } from "@/components/market-dashboard/selection/dashboardRoutes";
import {
  backendConnectionIssueCode,
  fetchServerBackendJson,
} from "@/lib/serverBackend";
import type {
  ChartPoint,
  JPWatchlistGroupNode,
  JPWatchlistItemRead,
  KRWatchlistGroupNode,
  KRWatchlistItemRead,
  MarketIndexSummary,
  OhlcChartResponse,
  OhlcIntradayOverlay,
  StockIndicatorPoint,
  TaiwanStockQuoteDepthPreviewMode,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  WatchlistGroupRadarRead,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";
import type { BackendConnectionIssueCode } from "@/types/runtime";

const indexProductIds = new Set(["TAIEX", "TPEX"]);
const futuresProductIds = new Set(["TXF", "MXF", "TMF"]);

type MarketCalendarStatusEnvelope = {
  markets?: {
    tw?: {
      session?: {
        is_polling_window?: boolean;
        is_after_close?: boolean;
      };
      release_windows?: {
        market_daily_price?: {
          is_released?: boolean;
        };
      };
    } | null;
  };
};

function firstSearchParam(
  params: Record<string, string | string[] | undefined> | undefined,
  key: string
) {
  const value = params?.[key];

  return Array.isArray(value) ? value[0] : value;
}

function normalizeQuoteDepthPreviewMode(
  value: string | undefined
): TaiwanStockQuoteDepthPreviewMode | null {
  if (value === "preopen" || value === "live") return value;

  return null;
}

function shouldUseTaiwanOhlcIntraday(calendarStatus: MarketCalendarStatusEnvelope | null) {
  const twStatus = calendarStatus?.markets?.tw;
  const dailyRelease = twStatus?.release_windows?.market_daily_price;

  return Boolean(
    twStatus?.session?.is_polling_window ||
      (twStatus?.session?.is_after_close && !dailyRelease?.is_released)
  );
}

function stockOhlcPath(stockId: string, includeIntraday: boolean) {
  const params = new URLSearchParams({
    timeframe: "daily",
    bars: "260",
    ensure_history: "false",
  });

  if (includeIntraday) {
    params.set("include_intraday", "true");
  }

  return `/api/market/ohlc/${encodeURIComponent(stockId)}?${params.toString()}`;
}

function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
}

type InitialBackendIssue = {
  code: BackendConnectionIssueCode;
  path: string;
};

function normalizeBackendIssueCode(
  value: string | undefined
): BackendConnectionIssueCode | null {
  if (
    value === "timeout" ||
    value === "unavailable" ||
    value === "request_failed" ||
    value === "invalid_response"
  ) {
    return value;
  }
  return null;
}

async function fetchInitialBackendJson<T>(
  path: string,
  fallback: T,
  issues: InitialBackendIssue[]
): Promise<T> {
  try {
    return await fetchServerBackendJson<T>(path, {
      cache: "no-store",
    });
  } catch (error) {
    const code = backendConnectionIssueCode(error);
    issues.push({ code, path });
    console.error(
      `[initial-backend] path=${path} code=${code}`,
      error instanceof Error ? error.message : error
    );
    return fallback;
  }
}

export default async function Page({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = await searchParams;
  const initialBackendIssues: InitialBackendIssue[] = [];
  const fetchInitial = <T,>(path: string, fallback: T) =>
    fetchInitialBackendJson(path, fallback, initialBackendIssues);
  const [
    initialTree,
    initialItems,
    initialMarketIndexSummary,
    initialUsWatchlistTree,
    initialUsWatchlistItems,
    initialJpWatchlistTree,
    initialJpWatchlistItems,
    initialKrWatchlistTree,
    initialKrWatchlistItems,
    initialCalendarStatus,
  ] = await Promise.all([
    fetchInitial<WatchlistGroupNode[]>("/api/watchlists/tree", []),
    fetchInitial<WatchlistItemRead[]>("/api/watchlists/items?limit=5000&offset=0", []),
    fetchInitial<MarketIndexSummary | null>("/api/market/indices/summary", null),
    fetchInitial<USWatchlistGroupNode[]>("/api/us-market/watchlists/tree", []),
    fetchInitial<USWatchlistItemRead[]>(
      "/api/us-market/watchlists/items?limit=5000&offset=0",
      []
    ),
    fetchInitial<JPWatchlistGroupNode[]>("/api/jp-market/watchlists/tree", []),
    fetchInitial<JPWatchlistItemRead[]>(
      "/api/jp-market/watchlists/items?limit=5000&offset=0",
      []
    ),
    fetchInitial<KRWatchlistGroupNode[]>("/api/kr-market/watchlists/tree", []),
    fetchInitial<KRWatchlistItemRead[]>(
      "/api/kr-market/watchlists/items?limit=5000&offset=0",
      []
    ),
    fetchInitial<MarketCalendarStatusEnvelope | null>(
      "/api/market/calendar-status?market=tw",
      null
    ),
  ]);

  const marketParam = firstSearchParam(resolvedSearchParams, "market");
  const stockIdParam =
    firstSearchParam(resolvedSearchParams, "stock_id") ??
    firstSearchParam(resolvedSearchParams, "stock");
  const symbolParam = firstSearchParam(resolvedSearchParams, "symbol");
  const jpSymbolParam = firstSearchParam(resolvedSearchParams, "jp_symbol");
  const krSymbolParam = firstSearchParam(resolvedSearchParams, "kr_symbol");
  const futuresParam =
    firstSearchParam(resolvedSearchParams, "futures") ??
    firstSearchParam(resolvedSearchParams, "futures_symbol");
  const groupIdParam = firstSearchParam(resolvedSearchParams, "group_id");
  const initialRadarMode = normalizeDashboardRadarMode(
    firstSearchParam(resolvedSearchParams, "radar_mode")
  );
  const quoteDepthPreviewMode = normalizeQuoteDepthPreviewMode(
    firstSearchParam(resolvedSearchParams, "quote_depth_preview")
  );
  const formBackendIssueCode = normalizeBackendIssueCode(
    firstSearchParam(resolvedSearchParams, "omi_error")
  );
  const requestedGroupId = Number(groupIdParam);
  const requestedFuturesSymbol = futuresParam?.trim().toUpperCase() || null;
  const initialSelectedFuturesSymbol =
    requestedFuturesSymbol && futuresProductIds.has(requestedFuturesSymbol)
      ? requestedFuturesSymbol
      : null;
  const initialSelectedStockId =
    initialSelectedFuturesSymbol === null ? stockIdParam?.trim() || null : null;
  const initialSelectedJpSymbol =
    (jpSymbolParam ?? (marketParam === "jp" ? symbolParam : undefined))
      ?.trim()
      .toUpperCase() || null;
  const initialSelectedKrSymbol =
    (krSymbolParam ?? (marketParam === "kr" ? symbolParam : undefined))
      ?.trim()
      .toUpperCase() || null;
  const initialSelectedUsSymbol =
    marketParam === "jp" || marketParam === "kr" || marketParam === "crypto"
      ? null
      : symbolParam?.trim().toUpperCase() || null;
  const initialMarket =
    marketParam === "crypto"
      ? "crypto"
      : marketParam === "kr" || initialSelectedKrSymbol
      ? "kr"
      : marketParam === "jp" || initialSelectedJpSymbol
      ? "jp"
      : marketParam === "us" || initialSelectedUsSymbol
        ? "us"
        : "tw";
  const selectedStockItem =
    initialSelectedStockId === null
      ? null
      : initialItems.find((item) => item.stock_id === initialSelectedStockId) ?? null;
  const selectedUsItem =
    initialSelectedUsSymbol === null
      ? null
      : initialUsWatchlistItems.find(
          (item) => item.symbol.toUpperCase() === initialSelectedUsSymbol
        ) ?? null;
  const hasRequestedGroupId = Number.isFinite(requestedGroupId);
  const defaultSelectedGroup =
    initialMarket === "tw" ? flattenGroups(initialTree)[0] ?? null : null;
  const initialSelectedGroupId = hasRequestedGroupId
    ? requestedGroupId
    : initialMarket === "tw"
      ? selectedStockItem?.group_id ?? defaultSelectedGroup?.id ?? null
      : null;
  const isIndexProduct =
    initialSelectedStockId !== null && indexProductIds.has(initialSelectedStockId);
  const includeInitialStockIntraday =
    !isIndexProduct && shouldUseTaiwanOhlcIntraday(initialCalendarStatus);
  // Radar can require a full watchlist calculation when no persisted snapshot
  // exists. Keep it out of the server-rendered critical path; the client loads
  // the latest snapshot first and progressively computes only as a fallback.
  const initialRadarPromise = Promise.resolve<WatchlistGroupRadarRead | null>(null);
  const initialOhlcPromise =
    initialMarket === "tw" && initialSelectedStockId
      ? fetchInitial<OhlcChartResponse | null>(
          isIndexProduct
            ? `/api/market/indices/${encodeURIComponent(
                initialSelectedStockId
              )}/ohlc?timeframe=daily&bars=260&ensure_history=false`
            : stockOhlcPath(initialSelectedStockId, includeInitialStockIntraday),
          null
        )
      : Promise.resolve<OhlcChartResponse | null>(null);
  const initialIndicatorDataPromise =
    initialMarket === "tw" && initialSelectedStockId && !isIndexProduct
      ? fetchInitial<StockIndicatorPoint[]>(
          `/api/market/indicators/${encodeURIComponent(
            initialSelectedStockId
          )}/daily?limit=240&ma_windows=5,20,60&volume_ma_windows=5,20`,
          []
        )
      : Promise.resolve<StockIndicatorPoint[]>([]);
  const [
    initialRadarData,
    initialOhlc,
    initialIndicatorData,
  ] = await Promise.all([
    initialRadarPromise,
    initialOhlcPromise,
    initialIndicatorDataPromise,
  ]);
  const initialChartData: ChartPoint[] = initialOhlc?.points ?? [];
  const initialChartIntradayOverlay: OhlcIntradayOverlay | null =
    initialOhlc?.intraday_overlay ?? null;
  const initialChartStockId = initialOhlc?.stock_id ?? null;
  const initialChartVolumeUnit = initialOhlc?.volume_unit ?? null;

  return (
    <MarketDashboardClient
      initialMarket={initialMarket}
      initialTree={initialTree}
      initialItems={initialItems}
      initialSelectedGroupId={initialSelectedGroupId}
      initialSelectedStockId={initialSelectedStockId}
      initialSelectedStockName={selectedStockItem?.stock_name ?? null}
      initialSelectedFuturesSymbol={initialSelectedFuturesSymbol}
      initialSelectedUsSymbol={initialSelectedUsSymbol}
      initialSelectedUsSecurityName={selectedUsItem?.security_name ?? null}
      initialSelectedJpSymbol={initialSelectedJpSymbol}
      initialSelectedKrSymbol={initialSelectedKrSymbol}
      initialChartData={initialChartData}
      initialChartIntradayOverlay={initialChartIntradayOverlay}
      initialChartStockId={initialChartStockId}
      initialChartVolumeUnit={initialChartVolumeUnit}
      initialIndicatorData={initialIndicatorData}
      initialRankingData={null}
      initialRadarMode={initialRadarMode}
      initialRadarData={initialRadarData}
      initialMarketIndexSummary={initialMarketIndexSummary}
      initialUsWatchlistTree={initialUsWatchlistTree}
      initialUsWatchlistItems={initialUsWatchlistItems}
      initialJpWatchlistTree={initialJpWatchlistTree}
      initialJpWatchlistItems={initialJpWatchlistItems}
      initialKrWatchlistTree={initialKrWatchlistTree}
      initialKrWatchlistItems={initialKrWatchlistItems}
      quoteDepthPreviewMode={quoteDepthPreviewMode}
      initialBackendIssueCount={initialBackendIssues.length}
      initialBackendIssueCode={initialBackendIssues[0]?.code ?? null}
      formBackendIssueCode={formBackendIssueCode}
    />
  );
}

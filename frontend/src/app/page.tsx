import MarketDashboardClient from "@/components/MarketDashboardClient";
import { normalizeDashboardRadarMode } from "@/components/market-dashboard/selection/dashboardRoutes";
import { getApiProxyTarget } from "@/lib/serverApiConfig";
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
  WatchlistRadarMode,
} from "@/types/market";

const apiProxyTarget = getApiProxyTarget();
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

function watchlistRadarPath(groupId: number, mode: WatchlistRadarMode) {
  const params = new URLSearchParams({
    include_children: "true",
    enabled_only: "true",
    mode,
    max_results: "20",
    ma_windows: "5,20,60",
    volume_ma_windows: "5,20",
    calculation_limit: "100",
    volume_ratio_threshold: "1.5",
    use_intraday: "false",
    intraday_limit: "30",
  });

  return `/api/watchlists/groups/${groupId}/radar?${params.toString()}`;
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
    bars: "180",
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

async function fetchBackendJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const response = await fetch(`${apiProxyTarget}${path}`, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) return fallback;

    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

export default async function Page({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = await searchParams;
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
    fetchBackendJson<WatchlistGroupNode[]>("/api/watchlists/tree", []),
    fetchBackendJson<WatchlistItemRead[]>("/api/watchlists/items?limit=5000&offset=0", []),
    fetchBackendJson<MarketIndexSummary | null>("/api/market/indices/summary", null),
    fetchBackendJson<USWatchlistGroupNode[]>("/api/us-market/watchlists/tree", []),
    fetchBackendJson<USWatchlistItemRead[]>(
      "/api/us-market/watchlists/items?limit=5000&offset=0",
      []
    ),
    fetchBackendJson<JPWatchlistGroupNode[]>("/api/jp-market/watchlists/tree", []),
    fetchBackendJson<JPWatchlistItemRead[]>(
      "/api/jp-market/watchlists/items?limit=5000&offset=0",
      []
    ),
    fetchBackendJson<KRWatchlistGroupNode[]>("/api/kr-market/watchlists/tree", []),
    fetchBackendJson<KRWatchlistItemRead[]>(
      "/api/kr-market/watchlists/items?limit=5000&offset=0",
      []
    ),
    fetchBackendJson<MarketCalendarStatusEnvelope | null>(
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
  const initialRadarPromise =
    initialMarket === "tw" && initialSelectedGroupId !== null
      ? fetchBackendJson<WatchlistGroupRadarRead | null>(
          watchlistRadarPath(initialSelectedGroupId, initialRadarMode),
          null
        )
      : Promise.resolve<WatchlistGroupRadarRead | null>(null);
  const initialOhlcPromise =
    initialMarket === "tw" && initialSelectedStockId
      ? fetchBackendJson<OhlcChartResponse | null>(
          isIndexProduct
            ? `/api/market/indices/${encodeURIComponent(
                initialSelectedStockId
              )}/ohlc?timeframe=daily&bars=180&ensure_history=false`
            : stockOhlcPath(initialSelectedStockId, includeInitialStockIntraday),
          null
        )
      : Promise.resolve<OhlcChartResponse | null>(null);
  const initialIndicatorDataPromise =
    initialMarket === "tw" && initialSelectedStockId && !isIndexProduct
      ? fetchBackendJson<StockIndicatorPoint[]>(
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
    />
  );
}

import MarketDashboardClient from "@/components/MarketDashboardClient";
import { getApiProxyTarget } from "@/lib/serverApiConfig";
import type {
  ChartPoint,
  JPWatchlistGroupNode,
  JPWatchlistItemRead,
  MarketIndexSummary,
  OhlcChartResponse,
  StockIndicatorPoint,
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

function firstSearchParam(
  params: Record<string, string | string[] | undefined> | undefined,
  key: string
) {
  const value = params?.[key];

  return Array.isArray(value) ? value[0] : value;
}

function normalizeRadarMode(value: string | undefined): WatchlistRadarMode {
  if (
    value === "surge" ||
    value === "breakout" ||
    value === "volume" ||
    value === "overheat" ||
    value === "weakness" ||
    value === "risk" ||
    value === "momentum"
  ) {
    return value;
  }

  return "action";
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
  ]);

  const marketParam = firstSearchParam(resolvedSearchParams, "market");
  const stockIdParam =
    firstSearchParam(resolvedSearchParams, "stock_id") ??
    firstSearchParam(resolvedSearchParams, "stock");
  const symbolParam = firstSearchParam(resolvedSearchParams, "symbol");
  const jpSymbolParam = firstSearchParam(resolvedSearchParams, "jp_symbol");
  const futuresParam =
    firstSearchParam(resolvedSearchParams, "futures") ??
    firstSearchParam(resolvedSearchParams, "futures_symbol");
  const groupIdParam = firstSearchParam(resolvedSearchParams, "group_id");
  const initialRadarMode = normalizeRadarMode(
    firstSearchParam(resolvedSearchParams, "radar_mode")
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
  const initialSelectedUsSymbol =
    marketParam === "jp" ? null : symbolParam?.trim().toUpperCase() || null;
  const initialMarket =
    marketParam === "jp" || initialSelectedJpSymbol
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
  const defaultSelectedGroup = flattenGroups(initialTree)[0] ?? null;
  const initialSelectedGroupId = Number.isFinite(requestedGroupId)
    ? requestedGroupId
    : selectedStockItem?.group_id ?? defaultSelectedGroup?.id ?? null;
  const isIndexProduct =
    initialSelectedStockId !== null && indexProductIds.has(initialSelectedStockId);
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
            : `/api/market/ohlc/${encodeURIComponent(
                initialSelectedStockId
              )}?timeframe=daily&bars=180&ensure_history=false`,
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
      initialChartData={initialChartData}
      initialIndicatorData={initialIndicatorData}
      initialRankingData={null}
      initialRadarMode={initialRadarMode}
      initialRadarData={initialRadarData}
      initialMarketIndexSummary={initialMarketIndexSummary}
      initialUsWatchlistTree={initialUsWatchlistTree}
      initialUsWatchlistItems={initialUsWatchlistItems}
      initialJpWatchlistTree={initialJpWatchlistTree}
      initialJpWatchlistItems={initialJpWatchlistItems}
    />
  );
}

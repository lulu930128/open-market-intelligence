import MarketDashboardClient from "@/components/MarketDashboardClient";
import type {
  ChartPoint,
  MarketIndexSummary,
  OhlcChartResponse,
  StockIndicatorPoint,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";

const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8300";
const indexProductIds = new Set(["TAIEX", "TPEX"]);

function firstSearchParam(
  params: Record<string, string | string[] | undefined> | undefined,
  key: string
) {
  const value = params?.[key];

  return Array.isArray(value) ? value[0] : value;
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
  ] = await Promise.all([
    fetchBackendJson<WatchlistGroupNode[]>("/api/watchlists/tree", []),
    fetchBackendJson<WatchlistItemRead[]>("/api/watchlists/items?limit=5000&offset=0", []),
    fetchBackendJson<MarketIndexSummary | null>("/api/market/indices/summary", null),
    fetchBackendJson<USWatchlistGroupNode[]>("/api/us-market/watchlists/tree", []),
    fetchBackendJson<USWatchlistItemRead[]>(
      "/api/us-market/watchlists/items?limit=5000&offset=0",
      []
    ),
  ]);

  const marketParam = firstSearchParam(resolvedSearchParams, "market");
  const stockIdParam =
    firstSearchParam(resolvedSearchParams, "stock_id") ??
    firstSearchParam(resolvedSearchParams, "stock");
  const symbolParam = firstSearchParam(resolvedSearchParams, "symbol");
  const groupIdParam = firstSearchParam(resolvedSearchParams, "group_id");
  const requestedGroupId = Number(groupIdParam);
  const initialSelectedStockId = stockIdParam?.trim() || null;
  const initialSelectedUsSymbol = symbolParam?.trim().toUpperCase() || null;
  const initialMarket = marketParam === "us" || initialSelectedUsSymbol ? "us" : "tw";
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
  const initialSelectedGroupId = Number.isFinite(requestedGroupId)
    ? requestedGroupId
    : selectedStockItem?.group_id ?? null;
  const isIndexProduct =
    initialSelectedStockId !== null && indexProductIds.has(initialSelectedStockId);
  const [initialOhlc, initialIndicatorData] =
    initialMarket === "tw" && initialSelectedStockId
      ? await Promise.all([
          fetchBackendJson<OhlcChartResponse | null>(
            isIndexProduct
              ? `/api/market/indices/${encodeURIComponent(
                  initialSelectedStockId
                )}/ohlc?timeframe=daily&bars=180&ensure_history=false`
              : `/api/market/ohlc/${encodeURIComponent(
                  initialSelectedStockId
                )}?timeframe=daily&bars=180&ensure_history=false`,
            null
          ),
          isIndexProduct
            ? Promise.resolve<StockIndicatorPoint[]>([])
            : fetchBackendJson<StockIndicatorPoint[]>(
                `/api/market/indicators/${encodeURIComponent(
                  initialSelectedStockId
                )}/daily?limit=240&ma_windows=5,20,60&volume_ma_windows=5,20`,
                []
              ),
        ])
      : [null, [] as StockIndicatorPoint[]];
  const initialChartData: ChartPoint[] = initialOhlc?.points ?? [];

  return (
    <MarketDashboardClient
      initialMarket={initialMarket}
      initialTree={initialTree}
      initialItems={initialItems}
      initialSelectedGroupId={initialSelectedGroupId}
      initialSelectedStockId={initialSelectedStockId}
      initialSelectedStockName={selectedStockItem?.stock_name ?? null}
      initialSelectedUsSymbol={initialSelectedUsSymbol}
      initialSelectedUsSecurityName={selectedUsItem?.security_name ?? null}
      initialChartData={initialChartData}
      initialIndicatorData={initialIndicatorData}
      initialRankingData={null}
      initialMarketIndexSummary={initialMarketIndexSummary}
      initialUsWatchlistTree={initialUsWatchlistTree}
      initialUsWatchlistItems={initialUsWatchlistItems}
    />
  );
}

import MarketDashboardClient from "@/components/MarketDashboardClient";
import type {
  ChartPoint,
  OhlcChartResponse,
  StockIndicatorPoint,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";

const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

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

function flattenGroups(nodes: WatchlistGroupNode[]): WatchlistGroupNode[] {
  return nodes.flatMap((node) => [node, ...flattenGroups(node.children)]);
}

export default async function Page({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolvedSearchParams = await searchParams;
  const [initialTree, initialItems] = await Promise.all([
    fetchBackendJson<WatchlistGroupNode[]>("/api/watchlists/tree", []),
    fetchBackendJson<WatchlistItemRead[]>("/api/watchlists/items?limit=1000&offset=0", []),
  ]);

  const groupIdParam = resolvedSearchParams?.group_id;
  const requestedGroupId = Array.isArray(groupIdParam)
    ? Number(groupIdParam[0])
    : Number(groupIdParam);
  const flattened = flattenGroups(initialTree);
  const initialSelectedGroupId = Number.isFinite(requestedGroupId)
    ? requestedGroupId
    : flattened[0]?.id ?? null;
  const initialSelectedItem =
    initialItems.find((item) => {
      return initialSelectedGroupId === null || item.group_id === initialSelectedGroupId;
    }) ??
    initialItems[0] ??
    null;
  let initialChartData: ChartPoint[] = [];
  let initialIndicatorData: StockIndicatorPoint[] = [];

  if (initialSelectedItem) {
    const initialOhlc = await fetchBackendJson<OhlcChartResponse>(
      `/api/market/ohlc/${initialSelectedItem.stock_id}?timeframe=daily&bars=90&ensure_history=true`,
      {
        stock_id: initialSelectedItem.stock_id,
        timeframe: "daily",
        bars: 90,
        lookback_days: 90,
        from_date: "",
        to_date: "",
        point_count: 0,
        points: [],
        backfill: null,
      }
    );

    initialChartData = initialOhlc.points;
    initialIndicatorData = await fetchBackendJson<StockIndicatorPoint[]>(
      `/api/market/indicators/${initialSelectedItem.stock_id}/daily?limit=520&ma_windows=5,20,60&volume_ma_windows=5,20`,
      []
    );
  }

  return (
    <MarketDashboardClient
      initialTree={initialTree}
      initialItems={initialItems}
      initialSelectedGroupId={initialSelectedGroupId}
      initialChartData={initialChartData}
      initialIndicatorData={initialIndicatorData}
    />
  );
}

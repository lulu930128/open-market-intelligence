import MarketDashboardClient from "@/components/MarketDashboardClient";
import type {
  ChartPoint,
  RankingResponse,
  SignalsResponse,
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
  const initialChartData: ChartPoint[] = [];
  const initialIndicatorData: StockIndicatorPoint[] = [];
  let initialRankingData: RankingResponse | null = null;
  let initialSignalsData: SignalsResponse | null = null;

  if (initialSelectedGroupId !== null) {
    [initialRankingData, initialSignalsData] = await Promise.all([
      fetchBackendJson<RankingResponse | null>(
        `/api/watchlists/groups/${initialSelectedGroupId}/rankings/latest?include_children=true&enabled_only=true&rank_by=change_pct&sort_order=desc&limit=100&volume_ratio_threshold=1.5&ma_windows=5,20,60&volume_ma_windows=5,20`,
        null
      ),
      fetchBackendJson<SignalsResponse | null>(
        `/api/watchlists/groups/${initialSelectedGroupId}/signals/latest?include_children=true&enabled_only=true&limit=100&volume_ratio_threshold=1.5&ma_windows=5,20,60&volume_ma_windows=5,20`,
        null
      ),
    ]);
  }

  return (
    <MarketDashboardClient
      initialTree={initialTree}
      initialItems={initialItems}
      initialSelectedGroupId={initialSelectedGroupId}
      initialChartData={initialChartData}
      initialIndicatorData={initialIndicatorData}
      initialRankingData={initialRankingData}
      initialSignalsData={initialSignalsData}
    />
  );
}

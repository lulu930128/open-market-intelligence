import MarketDashboardClient from "@/components/MarketDashboardClient";
import type {
  ChartPoint,
  StockIndicatorPoint,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";

const apiProxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8300";

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
    fetchBackendJson<WatchlistItemRead[]>("/api/watchlists/items?limit=5000&offset=0", []),
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

  return (
    <MarketDashboardClient
      initialTree={initialTree}
      initialItems={initialItems}
      initialSelectedGroupId={initialSelectedGroupId}
      initialChartData={initialChartData}
      initialIndicatorData={initialIndicatorData}
      initialRankingData={null}
    />
  );
}

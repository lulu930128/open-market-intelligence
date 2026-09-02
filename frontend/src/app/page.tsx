import MarketDashboardClient from "@/components/MarketDashboardClient";
import { normalizeDashboardRadarMode } from "@/components/market-dashboard/selection/dashboardRoutes";
import {
  backendConnectionIssueCode,
  fetchServerBackendJson,
} from "@/lib/serverBackend";
import type {
  JPWatchlistGroupNode,
  JPWatchlistItemRead,
  KRWatchlistGroupNode,
  KRWatchlistItemRead,
  MarketIndexSummary,
  TaiwanChartBundleRead,
  TaiwanStockQuoteDepthPreviewMode,
  USWatchlistGroupNode,
  USWatchlistItemRead,
  WatchlistGroupRadarRead,
  WatchlistGroupNode,
  WatchlistItemRead,
} from "@/types/market";
import type { BackendConnectionIssueCode } from "@/types/runtime";

const futuresProductIds = new Set(["TXF", "MXF", "TMF"]);
const taiwanIndexProductIds = new Set(["TAIEX", "TPEX"]);

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

function taiwanChartPath(stockId: string) {
  const params = new URLSearchParams({
    interval: "1d",
    limit: taiwanIndexProductIds.has(stockId.toUpperCase()) ? "300" : "260",
    include_partial: "true",
    ma_windows: "5,20,60",
    volume_ma_windows: "5,20",
  });
  return `/api/market/chart/${encodeURIComponent(stockId)}?${params.toString()}`;
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
    initialChartBundle,
  ] = await Promise.all([
    initialMarket === "tw"
      ? fetchInitial<WatchlistGroupNode[]>("/api/watchlists/tree", [])
      : Promise.resolve<WatchlistGroupNode[]>([]),
    initialMarket === "tw"
      ? fetchInitial<WatchlistItemRead[]>("/api/watchlists/items?limit=5000&offset=0", [])
      : Promise.resolve<WatchlistItemRead[]>([]),
    initialMarket === "tw"
      ? fetchInitial<MarketIndexSummary | null>("/api/market/indices/summary", null)
      : Promise.resolve<MarketIndexSummary | null>(null),
    initialMarket === "us"
      ? fetchInitial<USWatchlistGroupNode[]>("/api/us-market/watchlists/tree", [])
      : Promise.resolve<USWatchlistGroupNode[]>([]),
    initialMarket === "us"
      ? fetchInitial<USWatchlistItemRead[]>(
          "/api/us-market/watchlists/items?limit=5000&offset=0",
          []
        )
      : Promise.resolve<USWatchlistItemRead[]>([]),
    initialMarket === "jp"
      ? fetchInitial<JPWatchlistGroupNode[]>("/api/jp-market/watchlists/tree", [])
      : Promise.resolve<JPWatchlistGroupNode[]>([]),
    initialMarket === "jp"
      ? fetchInitial<JPWatchlistItemRead[]>(
          "/api/jp-market/watchlists/items?limit=5000&offset=0",
          []
        )
      : Promise.resolve<JPWatchlistItemRead[]>([]),
    initialMarket === "kr"
      ? fetchInitial<KRWatchlistGroupNode[]>("/api/kr-market/watchlists/tree", [])
      : Promise.resolve<KRWatchlistGroupNode[]>([]),
    initialMarket === "kr"
      ? fetchInitial<KRWatchlistItemRead[]>(
          "/api/kr-market/watchlists/items?limit=5000&offset=0",
          []
        )
      : Promise.resolve<KRWatchlistItemRead[]>([]),
    initialMarket === "tw" && initialSelectedStockId
      ? fetchInitial<TaiwanChartBundleRead | null>(
          taiwanChartPath(initialSelectedStockId),
          null
        )
      : Promise.resolve<TaiwanChartBundleRead | null>(null),
  ]);
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
  // Radar can require a full watchlist calculation when no persisted snapshot
  // exists. Keep it out of the server-rendered critical path; the client loads
  // the latest snapshot first and progressively computes only as a fallback.
  const initialRadarPromise = Promise.resolve<WatchlistGroupRadarRead | null>(null);
  const initialRadarData = await initialRadarPromise;

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
      initialChartBundle={initialChartBundle}
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

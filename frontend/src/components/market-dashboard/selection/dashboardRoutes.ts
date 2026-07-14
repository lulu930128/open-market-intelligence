import type {
  TaiwanStockQuoteDepthPreviewMode,
  WatchlistRadarMode,
} from "@/types/market";

export type MarketRegion = "tw" | "us" | "jp" | "kr" | "crypto";

export type DashboardHrefParams = {
  market?: MarketRegion;
  groupId?: number | null;
  stockId?: string | null;
  futuresSymbol?: string | null;
  symbol?: string | null;
  jpSymbol?: string | null;
  krSymbol?: string | null;
  radarMode?: WatchlistRadarMode | null;
  quoteDepthPreviewMode?: TaiwanStockQuoteDepthPreviewMode | null;
};

export type DashboardRoute = {
  market: MarketRegion;
  groupId: number | null;
  stockId: string | null;
  futuresSymbol: string | null;
  symbol: string | null;
  jpSymbol: string | null;
  krSymbol: string | null;
  radarMode: WatchlistRadarMode | null;
  quoteDepthPreviewMode: TaiwanStockQuoteDepthPreviewMode | null;
};

const marketRegions = new Set<MarketRegion>(["tw", "us", "jp", "kr", "crypto"]);
const radarModes = new Set<WatchlistRadarMode>([
  "action",
  "surge",
  "breakout",
  "volume",
  "overheat",
  "weakness",
  "risk",
  "momentum",
]);
const visibleRadarModes = new Set<WatchlistRadarMode>([
  "action",
  "surge",
  "breakout",
  "overheat",
  "risk",
  "momentum",
]);

function normalizedValue(value: string | null) {
  return value?.trim() || null;
}

function normalizedSymbol(value: string | null) {
  return normalizedValue(value)?.toUpperCase() ?? null;
}

function parsedGroupId(value: string | null) {
  if (value === null || value.trim() === "") return null;

  const groupId = Number(value);
  return Number.isFinite(groupId) ? groupId : null;
}

function parsedRadarMode(value: string | null): WatchlistRadarMode | null {
  return value !== null && radarModes.has(value as WatchlistRadarMode)
    ? (value as WatchlistRadarMode)
    : null;
}

export function normalizeDashboardRadarMode(
  value: WatchlistRadarMode | string | null | undefined
): WatchlistRadarMode {
  if (value === "volume") return "momentum";
  if (value === "weakness") return "risk";
  return visibleRadarModes.has(value as WatchlistRadarMode)
    ? (value as WatchlistRadarMode)
    : "action";
}

function parsedPreviewMode(
  value: string | null
): TaiwanStockQuoteDepthPreviewMode | null {
  return value === "preopen" || value === "live" ? value : null;
}

export function parseDashboardSearch(search: string): DashboardRoute {
  const searchParams = new URLSearchParams(search);
  const marketParam = normalizedValue(searchParams.get("market"));
  const jpSymbol = normalizedSymbol(
    searchParams.get("jp_symbol") ?? (marketParam === "jp" ? searchParams.get("symbol") : null)
  );
  const krSymbol = normalizedSymbol(
    searchParams.get("kr_symbol") ?? (marketParam === "kr" ? searchParams.get("symbol") : null)
  );
  const symbol =
    marketParam === "jp" || marketParam === "kr" || marketParam === "crypto"
      ? null
      : normalizedSymbol(searchParams.get("symbol"));
  const market = marketRegions.has(marketParam as MarketRegion)
    ? (marketParam as MarketRegion)
    : krSymbol
      ? "kr"
      : jpSymbol
        ? "jp"
        : symbol
          ? "us"
          : "tw";

  return {
    market,
    groupId: parsedGroupId(searchParams.get("group_id")),
    stockId: normalizedValue(
      searchParams.get("stock_id") ?? searchParams.get("stock")
    ),
    futuresSymbol: normalizedSymbol(
      searchParams.get("futures") ?? searchParams.get("futures_symbol")
    ),
    symbol,
    jpSymbol,
    krSymbol,
    radarMode: parsedRadarMode(searchParams.get("radar_mode")),
    quoteDepthPreviewMode: parsedPreviewMode(searchParams.get("quote_depth_preview")),
  };
}

export function buildDashboardHref(params: DashboardHrefParams) {
  const searchParams = new URLSearchParams();

  if (params.market) searchParams.set("market", params.market);
  if (params.groupId !== null && params.groupId !== undefined) {
    searchParams.set("group_id", String(params.groupId));
  }
  if (params.stockId) searchParams.set("stock_id", params.stockId);
  if (params.futuresSymbol) searchParams.set("futures", params.futuresSymbol);
  if (params.symbol) searchParams.set("symbol", params.symbol);
  if (params.jpSymbol) searchParams.set("jp_symbol", params.jpSymbol);
  if (params.krSymbol) searchParams.set("kr_symbol", params.krSymbol);
  if (params.radarMode) searchParams.set("radar_mode", params.radarMode);
  if (params.quoteDepthPreviewMode) {
    searchParams.set("quote_depth_preview", params.quoteDepthPreviewMode);
  }

  const query = searchParams.toString();
  return query ? `/?${query}` : "/";
}

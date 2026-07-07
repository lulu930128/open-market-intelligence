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

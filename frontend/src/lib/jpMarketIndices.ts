import type { JPStockMasterRead } from "@/types/market";

export type JPMarketIndexConfig = {
  symbol: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
};

export const JP_MARKET_INDEX_GROUP_NAME = "日股指數";

export const JP_MARKET_INDEX_ITEMS: JPMarketIndexConfig[] = [
  {
    symbol: "^N225",
    displaySymbol: "N225",
    name: "日経平均",
    exchange: "Nikkei",
    note: "Japan blue-chip benchmark",
  },
  {
    symbol: "1306.T",
    displaySymbol: "TOPIX ETF",
    name: "TOPIX ETF",
    exchange: "Tokyo Stock Exchange",
    note: "TOPIX proxy via 1306.T",
  },
];

export const JP_PRIMARY_MARKET_INDEX_SYMBOL = "^N225";
export const JP_DEFAULT_CONTEXT_INDEX_SYMBOL = "1306.T";

const JP_MARKET_INDEX_BY_SYMBOL = new Map(
  JP_MARKET_INDEX_ITEMS.map((item) => [item.symbol.toUpperCase(), item])
);

function includesAnyKeyword(value: string | null | undefined, keywords: string[]) {
  if (!value) return false;
  const normalized = value.toLowerCase();
  return keywords.some((keyword) => normalized.includes(keyword));
}

export function getJpMarketIndexConfig(symbol: string | null | undefined) {
  if (!symbol) return null;
  return JP_MARKET_INDEX_BY_SYMBOL.get(symbol.toUpperCase()) ?? null;
}

export function isJpMarketIndexSymbol(symbol: string | null | undefined) {
  return getJpMarketIndexConfig(symbol) !== null;
}

export function getJpPrimaryMarketIndexConfig() {
  return getJpMarketIndexConfig(JP_PRIMARY_MARKET_INDEX_SYMBOL) ?? JP_MARKET_INDEX_ITEMS[0];
}

export function resolveJpContextIndexConfig({
  symbol,
  securityName,
  groupName,
  stock,
}: {
  symbol: string | null | undefined;
  securityName?: string | null;
  groupName?: string | null;
  stock?: JPStockMasterRead | null;
}) {
  const selectedIndex = getJpMarketIndexConfig(symbol);
  if (selectedIndex && selectedIndex.symbol !== JP_PRIMARY_MARKET_INDEX_SYMBOL) {
    return selectedIndex;
  }

  const profileText = [
    stock?.market_segment,
    stock?.sector_33_name,
    stock?.sector_17_name,
    stock?.size_name,
    stock?.security_name,
    securityName,
    groupName,
  ].join(" ");

  if (
    includesAnyKeyword(profileText, [
      "topix",
      "prime",
      "standard",
      "growth",
      "etf",
      "reit",
      "東証",
      "プライム",
      "スタンダード",
      "グロース",
    ])
  ) {
    return getJpMarketIndexConfig(JP_DEFAULT_CONTEXT_INDEX_SYMBOL) ?? getJpPrimaryMarketIndexConfig();
  }

  return getJpMarketIndexConfig(JP_DEFAULT_CONTEXT_INDEX_SYMBOL) ?? getJpPrimaryMarketIndexConfig();
}

import type { KRStockMasterRead } from "@/types/market";

export type KRMarketIndexConfig = {
  symbol: string;
  indexId: string;
  displaySymbol: string;
  name: string;
  nameKr: string | null;
  exchange: string;
  marketSegment: string;
  note: string;
};

export const KR_MARKET_INDEX_GROUP_NAME = "韓股指數";

export const KR_MARKET_INDEX_ITEMS: KRMarketIndexConfig[] = [
  {
    symbol: "KOSPI",
    indexId: "KOSPI",
    displaySymbol: "KOSPI",
    name: "KOSPI 綜合指數",
    nameKr: "코스피",
    exchange: "KRX",
    marketSegment: "KOSPI",
    note: "Korea Composite Stock Price Index",
  },
  {
    symbol: "KOSDAQ",
    indexId: "KOSDAQ",
    displaySymbol: "KOSDAQ",
    name: "KOSDAQ 綜合指數",
    nameKr: "코스닥",
    exchange: "KRX",
    marketSegment: "KOSDAQ",
    note: "Korea tech and growth market benchmark",
  },
  {
    symbol: "KOSPI200",
    indexId: "KOSPI200",
    displaySymbol: "KOSPI 200",
    name: "KOSPI 200",
    nameKr: "코스피 200",
    exchange: "KRX",
    marketSegment: "KOSPI",
    note: "KOSPI large-cap benchmark",
  },
];

export const KR_PRIMARY_MARKET_INDEX_SYMBOL = "KOSPI";
export const KR_DEFAULT_CONTEXT_INDEX_SYMBOL = "KOSPI200";

const KR_MARKET_INDEX_BY_SYMBOL = new Map(
  KR_MARKET_INDEX_ITEMS.flatMap((item) => [
    [item.symbol.toUpperCase(), item],
    [item.indexId.toUpperCase(), item],
  ])
);

function includesAnyKeyword(value: string | null | undefined, keywords: string[]) {
  if (!value) return false;
  const normalized = value.toLowerCase();
  return keywords.some((keyword) => normalized.includes(keyword));
}

export function getKrMarketIndexConfig(symbol: string | null | undefined) {
  if (!symbol) return null;
  return KR_MARKET_INDEX_BY_SYMBOL.get(symbol.toUpperCase()) ?? null;
}

export function isKrMarketIndexSymbol(symbol: string | null | undefined) {
  return getKrMarketIndexConfig(symbol) !== null;
}

export function getKrPrimaryMarketIndexConfig() {
  return getKrMarketIndexConfig(KR_PRIMARY_MARKET_INDEX_SYMBOL) ?? KR_MARKET_INDEX_ITEMS[0];
}

export function resolveKrContextIndexConfig({
  symbol,
  securityName,
  groupName,
  stock,
}: {
  symbol: string | null | undefined;
  securityName?: string | null;
  groupName?: string | null;
  stock?: KRStockMasterRead | null;
}) {
  const selectedIndex = getKrMarketIndexConfig(symbol);
  if (selectedIndex && selectedIndex.symbol !== KR_PRIMARY_MARKET_INDEX_SYMBOL) {
    return selectedIndex;
  }

  const profileText = [
    stock?.market_segment,
    stock?.sector,
    stock?.industry,
    stock?.security_name,
    stock?.security_name_kr,
    securityName,
    groupName,
  ].join(" ");

  if (
    includesAnyKeyword(profileText, [
      "kosdaq",
      "konex",
      "growth",
      "venture",
      "코스닥",
      "코넥스",
    ])
  ) {
    return getKrMarketIndexConfig(KR_DEFAULT_CONTEXT_INDEX_SYMBOL) ?? getKrPrimaryMarketIndexConfig();
  }

  return getKrMarketIndexConfig(KR_DEFAULT_CONTEXT_INDEX_SYMBOL) ?? getKrPrimaryMarketIndexConfig();
}

import type { USCompanyProfileRead } from "@/types/market";

export type USMarketIndexConfig = {
  symbol: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  note: string;
};

export const US_MARKET_INDEX_GROUP_NAME = "美股指數";

export const US_MARKET_INDEX_ITEMS: USMarketIndexConfig[] = [
  {
    symbol: "^GSPC",
    displaySymbol: "SPX",
    name: "S&P 500",
    exchange: "CBOE",
    note: "Large-cap benchmark",
  },
  {
    symbol: "^DJI",
    displaySymbol: "DJI",
    name: "道瓊指數",
    exchange: "DJI",
    note: "Dow Jones Industrial Average",
  },
  {
    symbol: "^IXIC",
    displaySymbol: "IXIC",
    name: "Nasdaq Composite",
    exchange: "NASDAQ",
    note: "Nasdaq broad market",
  },
  {
    symbol: "^SOX",
    displaySymbol: "SOX",
    name: "費城半導體",
    exchange: "PHLX",
    note: "Philadelphia Semiconductor Index",
  },
];

export const US_PRIMARY_MARKET_INDEX_SYMBOL = "^GSPC";
export const US_DEFAULT_CONTEXT_INDEX_SYMBOL = "^IXIC";
export const US_SEMICONDUCTOR_INDEX_SYMBOL = "^SOX";
export const US_DOW_INDEX_SYMBOL = "^DJI";

const US_MARKET_INDEX_BY_SYMBOL = new Map(
  US_MARKET_INDEX_ITEMS.map((item) => [item.symbol.toUpperCase(), item])
);

const semiconductorSymbols = new Set([
  "ADI",
  "AMD",
  "AMAT",
  "ARM",
  "ASML",
  "AVGO",
  "COHR",
  "ENTG",
  "GFS",
  "INTC",
  "KLAC",
  "LRCX",
  "MCHP",
  "MPWR",
  "MRVL",
  "MU",
  "NVDA",
  "NXPI",
  "ON",
  "QCOM",
  "SMCI",
  "STM",
  "SWKS",
  "TER",
  "TSM",
  "TXN",
  "UMC",
]);

const dowSymbols = new Set([
  "AMGN",
  "AMZN",
  "AXP",
  "BA",
  "CAT",
  "CRM",
  "CSCO",
  "CVX",
  "DIS",
  "GS",
  "HD",
  "HON",
  "IBM",
  "JNJ",
  "JPM",
  "KO",
  "MCD",
  "MMM",
  "MRK",
  "NKE",
  "PG",
  "SHW",
  "TRV",
  "UNH",
  "V",
  "VZ",
  "WMT",
]);

function includesAnyKeyword(value: string | null | undefined, keywords: string[]) {
  if (!value) return false;
  const normalized = value.toLowerCase();
  return keywords.some((keyword) => normalized.includes(keyword));
}

function normalizeUsTicker(symbol: string | null | undefined) {
  if (!symbol) return "";
  return symbol.trim().toUpperCase();
}

export function getUsMarketIndexConfig(symbol: string | null | undefined) {
  if (!symbol) return null;
  return US_MARKET_INDEX_BY_SYMBOL.get(symbol.toUpperCase()) ?? null;
}

export function isUsMarketIndexSymbol(symbol: string | null | undefined) {
  return getUsMarketIndexConfig(symbol) !== null;
}

export function getUsPrimaryMarketIndexConfig() {
  return getUsMarketIndexConfig(US_PRIMARY_MARKET_INDEX_SYMBOL) ?? US_MARKET_INDEX_ITEMS[0];
}

export function resolveUsContextIndexConfig({
  symbol,
  securityName,
  groupName,
  profile,
}: {
  symbol: string | null | undefined;
  securityName?: string | null;
  groupName?: string | null;
  profile?: USCompanyProfileRead | null;
}) {
  const selectedIndex = getUsMarketIndexConfig(symbol);
  if (selectedIndex && selectedIndex.symbol !== US_PRIMARY_MARKET_INDEX_SYMBOL) {
    return selectedIndex;
  }

  const ticker = normalizeUsTicker(symbol);
  const profileText = [
    profile?.sector,
    profile?.industry,
    profile?.company_name,
    securityName,
    groupName,
  ].join(" ");

  if (
    semiconductorSymbols.has(ticker) ||
    includesAnyKeyword(profileText, [
      "semiconductor",
      "semiconductors",
      "chip",
      "晶片",
      "半導體",
      "半导体",
    ])
  ) {
    return getUsMarketIndexConfig(US_SEMICONDUCTOR_INDEX_SYMBOL) ?? getUsPrimaryMarketIndexConfig();
  }

  if (
    includesAnyKeyword(profileText, [
      "technology",
      "software",
      "computer",
      "internet",
      "cloud",
      "科技",
      "軟體",
      "软件",
    ])
  ) {
    return getUsMarketIndexConfig(US_DEFAULT_CONTEXT_INDEX_SYMBOL) ?? getUsPrimaryMarketIndexConfig();
  }

  if (
    dowSymbols.has(ticker) ||
    includesAnyKeyword(profileText, ["dow", "道瓊", "道琼", "藍籌", "蓝筹"])
  ) {
    return getUsMarketIndexConfig(US_DOW_INDEX_SYMBOL) ?? getUsPrimaryMarketIndexConfig();
  }

  return getUsMarketIndexConfig(US_DEFAULT_CONTEXT_INDEX_SYMBOL) ?? getUsPrimaryMarketIndexConfig();
}

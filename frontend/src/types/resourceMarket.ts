export type ResourceCommodityGroupKey = "metals" | "energy";

export type ResourceCommodityInstrument = {
  key: string;
  group: ResourceCommodityGroupKey;
  displayName: string;
  symbol: string;
  exchange: string;
  providerSymbol: string;
  quoteAsset: string;
  providerStatus: "provider_pending";
  role: string;
};

export const RESOURCE_COMMODITY_GROUPS: {
  key: ResourceCommodityGroupKey;
  label: string;
}[] = [
  { key: "metals", label: "金屬" },
  { key: "energy", label: "能源" },
];

export const RESOURCE_COMMODITY_INSTRUMENTS: ResourceCommodityInstrument[] = [
  {
    key: "commodity:metals:GC",
    group: "metals",
    displayName: "黃金",
    symbol: "GC",
    exchange: "COMEX",
    providerSymbol: "GC",
    quoteAsset: "USDT",
    providerStatus: "provider_pending",
    role: "Gold futures watch-only context",
  },
  {
    key: "commodity:metals:SI",
    group: "metals",
    displayName: "白銀",
    symbol: "SI",
    exchange: "COMEX",
    providerSymbol: "SI",
    quoteAsset: "USDT",
    providerStatus: "provider_pending",
    role: "Silver futures watch-only context",
  },
  {
    key: "commodity:metals:HG",
    group: "metals",
    displayName: "銅",
    symbol: "HG",
    exchange: "COMEX",
    providerSymbol: "HG",
    quoteAsset: "USDT",
    providerStatus: "provider_pending",
    role: "Copper futures watch-only context",
  },
  {
    key: "commodity:energy:CL",
    group: "energy",
    displayName: "WTI 原油",
    symbol: "CL",
    exchange: "NYMEX",
    providerSymbol: "CL",
    quoteAsset: "USDT",
    providerStatus: "provider_pending",
    role: "WTI crude oil futures watch-only context",
  },
  {
    key: "commodity:energy:BZ",
    group: "energy",
    displayName: "Brent 原油",
    symbol: "BZ",
    exchange: "NYMEX",
    providerSymbol: "BZ",
    quoteAsset: "USDT",
    providerStatus: "provider_pending",
    role: "Brent crude oil futures watch-only context",
  },
  {
    key: "commodity:energy:NG",
    group: "energy",
    displayName: "天然氣",
    symbol: "NG",
    exchange: "NYMEX",
    providerSymbol: "NG",
    quoteAsset: "USDT",
    providerStatus: "provider_pending",
    role: "Natural gas futures watch-only context",
  },
];

export function resourceInstrumentsForGroup(group: ResourceCommodityGroupKey) {
  return RESOURCE_COMMODITY_INSTRUMENTS.filter((instrument) => instrument.group === group);
}

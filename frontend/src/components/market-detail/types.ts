export type MarketDataSlotKey =
  | "price"
  | "technical"
  | "chips"
  | "institutional"
  | "branch"
  | "revenue"
  | "earnings"
  | "actions";

export type MarketResourceSlotStatus =
  | "available"
  | "empty"
  | "planned"
  | "error"
  | "stale"
  | "loading";

export type MarketResourceSlotStatusValue =
  | MarketResourceSlotStatus
  | (string & {});

export type ResourceSlotTabItem<TSlotKey extends string = string> = {
  key: TSlotKey;
  label: string;
  title: string;
  description: string;
  status: MarketResourceSlotStatusValue;
  source: string;
  latestDate: string;
  rowCount: string;
};


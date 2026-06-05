export type TaiwanRefreshProfile = "basic" | "chips" | "branch" | "fundamental" | "full";
export type TaiwanDataPanelTab = "chips" | "institutional" | "branch" | "revenue" | "earnings";
export type TaiwanChartTimeframe = "daily" | "weekly" | "monthly";

type TaiwanChartHistoryRequirement = {
  label: string;
  minPoints: number;
  lookbackDays: number;
};

const dataPanelRefreshProfiles: Record<TaiwanDataPanelTab, TaiwanRefreshProfile> = {
  chips: "chips",
  institutional: "basic",
  branch: "branch",
  revenue: "fundamental",
  earnings: "fundamental",
};

const dataPanelRefreshLabels: Record<TaiwanDataPanelTab, string> = {
  chips: "籌碼",
  institutional: "法人",
  branch: "分點",
  revenue: "營收",
  earnings: "盈餘",
};

const chartHistoryRequirements: Record<TaiwanChartTimeframe, TaiwanChartHistoryRequirement> = {
  daily: {
    label: "日K",
    minPoints: 180,
    lookbackDays: 420,
  },
  weekly: {
    label: "週K",
    minPoints: 104,
    lookbackDays: 900,
  },
  monthly: {
    label: "月K",
    minPoints: 60,
    lookbackDays: 2100,
  },
};

export function getTaiwanDataPanelRefreshProfile(tab: TaiwanDataPanelTab) {
  return dataPanelRefreshProfiles[tab];
}

export function getTaiwanDataPanelRefreshLabel(tab: TaiwanDataPanelTab) {
  return dataPanelRefreshLabels[tab];
}

export function taiwanSelectionRefreshPath(stockId: string) {
  return `/api/market/selection-refresh/${stockId}`;
}

export function getTaiwanChartHistoryRequirement(timeframe: TaiwanChartTimeframe) {
  return chartHistoryRequirements[timeframe];
}

export function taiwanDailyPriceBackfillPath(stockId: string, market: string | null | undefined) {
  const normalizedMarket = (market ?? "").trim().toUpperCase();

  if (normalizedMarket === "TWSE") {
    return `/api/market/backfill/twse/${stockId}`;
  }

  if (normalizedMarket === "TPEX") {
    return `/api/market/backfill/tpex/${stockId}`;
  }

  return null;
}

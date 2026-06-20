import type { BranchTableSide, DataPanelTab } from "@/components/stock-detail/StockDetailDataViews";

export const dataPanelTabs: Array<{ key: DataPanelTab; label: string }> = [
  { key: "chips", label: "Chip flow" },
  { key: "institutional", label: "Institutions" },
  { key: "branch", label: "Branches" },
  { key: "revenue", label: "Revenue" },
  { key: "earnings", label: "Earnings" },
];

export const branchDayOptions: Array<{ label: string; days: number | null }> = [
  { label: "1", days: 1 },
  { label: "3", days: 3 },
  { label: "5", days: 5 },
  { label: "10", days: 10 },
  { label: "20", days: 20 },
  { label: "60", days: 60 },
  { label: "120", days: 120 },
  { label: "More", days: null },
];

export const branchTableSideOptions: Array<{ key: BranchTableSide; label: string }> = [
  { key: "buy", label: "Buy" },
  { key: "sell", label: "Sell" },
];

export const largeHolderLotOptions = [100, 200, 400, 600, 800, 1000];
export const smallHolderLotOptions = [10, 20, 30, 40, 50, 100];
export const institutionalDisplayMonths = 3;
export const minimumUsableRevenueRows = 2;
export const minimumUsableFinancialRows = 2;

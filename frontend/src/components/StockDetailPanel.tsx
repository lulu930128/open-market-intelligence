"use client";

import IntradayTrendChart from "@/components/IntradayTrendChart";
import StockKLineChart, {
  defaultIndicators,
  indicatorOptions,
  type IndicatorKey,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import { fetchJson, requestJson } from "@/lib/api";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  getTaiwanMarketRefreshState,
} from "@/lib/taiwanMarketTime";
import type {
  ChartPoint,
  FinancialMetricQuarterlyRead,
  IntradayTrendPoint,
  IntradayTrendResponse,
  InstitutionalTradeDailyRead,
  MarginTradingDailyRead,
  MonthlyRevenueRead,
  OhlcChartResponse,
  ShareholdingDistributionWeeklyRead,
  StockIndicatorPoint,
  StockMasterRead,
} from "@/types/market";
import {
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type Props = {
  stockId: string | null;
  stockName: string | null;
  initialChartData?: ChartPoint[];
  initialIndicatorData?: StockIndicatorPoint[];
  watchlistRankingPanel?: ReactNode;
};

type Timeframe = "today" | "daily" | "weekly" | "monthly";
type LoadState = "idle" | "loading" | "success" | "error";
type DataPanelTab = "chips" | "institutional" | "branch" | "revenue" | "earnings";
type RevenueView = "monthly" | "quarterly" | "yearly";
type EarningsView = "quarterly" | "yearly";
type ShareholdingSeriesPoint = {
  date: string;
  largeRatio: number | null;
  largeRatioChange: number | null;
  largeHolders: number | null;
  smallRatio: number | null;
  close: number | null;
};
type InstitutionalSeriesPoint = {
  date: string;
  foreignNet: number | null;
  investmentTrustNet: number | null;
  dealerNet: number | null;
  totalNet: number | null;
  foreignCumulative: number | null;
  investmentTrustCumulative: number | null;
  dealerCumulative: number | null;
  totalCumulative: number | null;
};
type InstitutionalNetKey = "foreignNet" | "investmentTrustNet" | "dealerNet";
type InstitutionalCumulativeKey =
  | "foreignCumulative"
  | "investmentTrustCumulative"
  | "dealerCumulative";
type RevenueSeriesPoint = {
  period: string;
  label: string;
  year: number;
  revenue: number | null;
  previousRevenue: number | null;
  growthPct: number | null;
  cumulativeRevenue: number | null;
  cumulativeGrowthPct: number | null;
  monthCount: number;
};
type EarningsSeriesPoint = {
  period: string;
  label: string;
  fiscalYear: number;
  quarter: number | null;
  eps: number | null;
  previousEps: number | null;
  growthPct: number | null;
  roe: number | null;
  roa: number | null;
  periodCount: number;
};

const dataPanelTabs: Array<{ key: DataPanelTab; label: string }> = [
  { key: "chips", label: "籌碼" },
  { key: "institutional", label: "法人" },
  { key: "branch", label: "分點" },
  { key: "revenue", label: "營收" },
  { key: "earnings", label: "盈餘" },
];

const largeHolderLotOptions = [100, 200, 400, 600, 800, 1000];
const smallHolderLotOptions = [10, 20, 30, 40, 50, 100];
const institutionalLookbackDays = 100;
const institutionalHistoryLimit = 120;
const institutionalDisplayMonths = 3;
const revenueHistoryLimit = 120;
const financialHistoryLimit = 40;
const shareholdingLevelRanges: Record<number, { minLots: number; maxLots: number | null }> = {
  1: { minLots: 0, maxLots: 1 },
  2: { minLots: 1, maxLots: 5 },
  3: { minLots: 5, maxLots: 10 },
  4: { minLots: 10, maxLots: 15 },
  5: { minLots: 15, maxLots: 20 },
  6: { minLots: 20, maxLots: 30 },
  7: { minLots: 30, maxLots: 40 },
  8: { minLots: 40, maxLots: 50 },
  9: { minLots: 50, maxLots: 100 },
  10: { minLots: 100, maxLots: 200 },
  11: { minLots: 200, maxLots: 400 },
  12: { minLots: 400, maxLots: 600 },
  13: { minLots: 600, maxLots: 800 },
  14: { minLots: 800, maxLots: 1000 },
  15: { minLots: 1000, maxLots: null },
};

const timeframeLabels: Record<Timeframe, string> = {
  today: "今日",
  daily: "日K",
  weekly: "週K",
  monthly: "月K",
};

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value));
}

function formatSignedNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value)}`;
}

function formatLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value / 1000));
}

function formatSignedLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatLots(value)}`;
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatRatioPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(2)}%`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";

  const date = new Date(value);

  if (Number.isNaN(date.getTime()) || !value.includes("T")) return value;

  return new Intl.DateTimeFormat("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Taipei",
  }).format(date);
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function formatMonth(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 7);
}

function toRevenueYi(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return value / 100000;
}

function formatRevenueYiValue(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatCompactDate(value: string | null | undefined) {
  if (!value) return "-";
  const digits = value.replace(/\D/g, "");
  if (digits.length >= 8) return digits.slice(0, 8);
  return value;
}

function formatPeriodLabel(value: string | null | undefined) {
  return formatMonth(value);
}

function formatMonthDay(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(5, 10).replace("-", "/");
}

function addMonthsToDateText(value: string, months: number) {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCMonth(date.getUTCMonth() + months);
  return date.toISOString().slice(0, 10);
}

function rebuildInstitutionalCumulative(points: InstitutionalSeriesPoint[]) {
  return points.reduce<{
    rows: InstitutionalSeriesPoint[];
    foreignCumulative: number;
    investmentTrustCumulative: number;
    dealerCumulative: number;
    totalCumulative: number;
  }>(
    (accumulator, point) => {
      const nextForeignCumulative = accumulator.foreignCumulative + (point.foreignNet ?? 0);
      const nextInvestmentTrustCumulative =
        accumulator.investmentTrustCumulative + (point.investmentTrustNet ?? 0);
      const nextDealerCumulative = accumulator.dealerCumulative + (point.dealerNet ?? 0);
      const nextTotalCumulative = accumulator.totalCumulative + (point.totalNet ?? 0);

      return {
        rows: [
          ...accumulator.rows,
          {
            ...point,
            foreignCumulative: nextForeignCumulative,
            investmentTrustCumulative: nextInvestmentTrustCumulative,
            dealerCumulative: nextDealerCumulative,
            totalCumulative: nextTotalCumulative,
          },
        ],
        foreignCumulative: nextForeignCumulative,
        investmentTrustCumulative: nextInvestmentTrustCumulative,
        dealerCumulative: nextDealerCumulative,
        totalCumulative: nextTotalCumulative,
      };
    },
    {
      rows: [],
      foreignCumulative: 0,
      investmentTrustCumulative: 0,
      dealerCumulative: 0,
      totalCumulative: 0,
    }
  ).rows;
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-slate-500";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
}

function safeRatio(numerator: number | null | undefined, denominator: number | null | undefined) {
  if (
    numerator === null ||
    numerator === undefined ||
    denominator === null ||
    denominator === undefined ||
    denominator === 0
  ) {
    return null;
  }

  return numerator / denominator;
}

async function fetchOptional<T>(
  path: string,
  params?: Record<string, string | number | boolean>
): Promise<T | null> {
  try {
    return await fetchJson<T>(path, params);
  } catch {
    return null;
  }
}

function TechnicalBar({ label, value }: { label: string; value: number | null }) {
  const displayValue = value === null ? 0 : Math.max(-12, Math.min(12, value));
  const width = `${Math.abs(displayValue / 12) * 50}%`;
  const isPositive = displayValue >= 0;

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className={valueTone(value)}>{value === null ? "-" : formatPct(value)}</span>
      </div>
      <div className="relative h-2 bg-slate-100">
        <div className="absolute left-1/2 top-0 h-2 w-px bg-slate-300" />
        <div
          className={[
            "absolute top-0 h-2",
            isPositive ? "left-1/2 bg-red-500" : "right-1/2 bg-emerald-500",
          ].join(" ")}
          style={{ width }}
        />
      </div>
    </div>
  );
}

function MetricRow({
  label,
  value,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-slate-100 py-2 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className={`font-semibold ${tone}`}>{value}</span>
    </div>
  );
}

function ChipMetricBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs font-bold text-slate-900">{title}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function DataTabIcon({ type }: { type: DataPanelTab }) {
  if (type === "institutional") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M3 8h14v2H3V8Zm1 3h2v5H4v-5Zm5 0h2v5H9v-5Zm5 0h2v5h-2v-5ZM2 17h16v1H2v-1ZM10 2l7 4H3l7-4Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "branch") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M3 8.5 10 4l7 4.5V17H3V8.5Zm2 1.1V15h10V9.6L10 6.4 5 9.6ZM7 11h2v4H7v-4Zm4 0h2v4h-2v-4Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "revenue") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M10.8 2v2.1c1.9.3 3.2 1.4 3.2 3.1h-2c0-.8-.8-1.3-2-1.3-1.3 0-2 .5-2 1.2 0 .8.8 1.1 2.6 1.5 2 .5 3.8 1.2 3.8 3.4 0 1.8-1.4 3-3.6 3.3V18H8.9v-2.6c-2.2-.3-3.7-1.5-3.7-3.4h2c0 1 1 1.6 2.4 1.6 1.6 0 2.5-.6 2.5-1.5 0-.8-.7-1.2-2.8-1.7-1.9-.5-3.5-1.2-3.5-3.2 0-1.7 1.3-2.8 3.1-3.1V2h1.9Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "earnings") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M11 2v4h4v2h-4v2h3.5a2.5 2.5 0 0 1 0 5H11v3H9v-3H5v-2h4v-3H5V8h4V6H5V4h4V2h2Zm0 10v1h3.5a.5.5 0 0 0 0-1H11Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
      <path
        d="M10 2c3.3 0 6 1 6 2.3S13.3 6.6 10 6.6 4 5.6 4 4.3 6.7 2 10 2Zm-6 4.2c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3V6.2Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-2.1Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v1.5c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-1.5Z"
        fill="currentColor"
      />
    </svg>
  );
}

function DataTabButton({
  tab,
  active,
  onClick,
}: {
  tab: { key: DataPanelTab; label: string };
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex h-11 min-w-0 flex-1 items-center justify-center gap-2 border-r border-slate-200 text-sm font-semibold transition last:border-r-0",
        active
          ? "bg-white text-slate-950 shadow-[inset_0_-2px_0_#b91c1c]"
          : "bg-slate-50 text-slate-500 hover:bg-white hover:text-slate-900",
      ].join(" ")}
    >
      <DataTabIcon type={tab.key} />
      <span>{tab.label}</span>
    </button>
  );
}

function EmptyDataState({ message }: { message: string }) {
  return (
    <div className="border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
      {message}
    </div>
  );
}

function SegmentedNumberButtons({
  label,
  suffix,
  options,
  value,
  onChange,
}: {
  label: string;
  suffix: string;
  options: number[];
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 text-right font-semibold text-slate-600">{label}</span>
      <div className="grid flex-1 grid-cols-6 overflow-hidden border border-slate-400">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={[
              "h-7 border-r border-slate-400 text-xs font-semibold last:border-r-0",
              value === option
                ? "bg-slate-700 text-white"
                : "bg-white text-slate-700 hover:bg-slate-50",
            ].join(" ")}
          >
            {option}
          </button>
        ))}
      </div>
      <span className="w-4 shrink-0 text-slate-500">{suffix}</span>
    </div>
  );
}

function minMax(values: Array<number | null | undefined>) {
  const validValues = values.filter(
    (value): value is number =>
      value !== null && value !== undefined && !Number.isNaN(value)
  );

  if (!validValues.length) return null;

  const min = Math.min(...validValues);
  const max = Math.max(...validValues);
  const padding = Math.max((max - min) * 0.12, max === min ? Math.max(Math.abs(max) * 0.08, 1) : 0);

  return {
    min: min - padding,
    max: max + padding,
  };
}

function chartX(index: number, count: number, left: number, width: number) {
  if (count <= 1) return left + width / 2;
  return left + (index / (count - 1)) * width;
}

function chartY(value: number, min: number, max: number, top: number, height: number) {
  if (max === min) return top + height / 2;
  return top + ((max - value) / (max - min)) * height;
}

function buildLinePath(
  points: ShareholdingSeriesPoint[],
  valueKey: keyof Pick<ShareholdingSeriesPoint, "largeRatio" | "smallRatio" | "close">,
  scale: { min: number; max: number },
  left: number,
  top: number,
  width: number,
  height: number
) {
  return points
    .map((point, index) => {
      const value = point[valueKey];
      if (value === null || value === undefined || Number.isNaN(value)) return null;

      const x = chartX(index, points.length, left, width);
      const y = chartY(value, scale.min, scale.max, top, height);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

function buildNumericLinePath<T>(
  points: T[],
  getValue: (point: T) => number | null | undefined,
  scale: { min: number; max: number },
  left: number,
  top: number,
  width: number,
  height: number
) {
  return points
    .map((point, index) => {
      const value = getValue(point);
      if (value === null || value === undefined || Number.isNaN(value)) return null;

      const x = chartX(index, points.length, left, width);
      const y = chartY(value, scale.min, scale.max, top, height);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

function nearestChartIndex(
  event: ReactMouseEvent<SVGSVGElement>,
  pointCount: number,
  left: number,
  width: number,
  viewWidth: number
) {
  if (pointCount <= 1) return 0;

  const rect = event.currentTarget.getBoundingClientRect();
  const viewX = ((event.clientX - rect.left) / rect.width) * viewWidth;
  const clampedX = Math.max(left, Math.min(left + width, viewX));
  const ratio = (clampedX - left) / width;
  return Math.max(0, Math.min(pointCount - 1, Math.round(ratio * (pointCount - 1))));
}

function tooltipX(x: number, tooltipWidth: number, viewWidth: number) {
  return Math.max(8, Math.min(viewWidth - tooltipWidth - 8, x + 16));
}

function tooltipY(y: number, tooltipHeight: number, top: number, height: number) {
  return Math.max(8, Math.min(top + height - tooltipHeight - 8, y - tooltipHeight / 2));
}

function quarterFromMonth(month: number) {
  return Math.floor((month - 1) / 3) + 1;
}

function revenueGrowth(current: number | null, previous: number | null) {
  if (
    current === null ||
    previous === null ||
    previous === 0 ||
    Number.isNaN(current) ||
    Number.isNaN(previous)
  ) {
    return null;
  }

  return ((current - previous) / previous) * 100;
}

function buildRevenueSeries(rows: MonthlyRevenueRead[], view: RevenueView) {
  const sortedRows = rows
    .slice()
    .sort((a, b) => a.period.localeCompare(b.period));

  if (view === "monthly") {
    return sortedRows.map<RevenueSeriesPoint>((row) => ({
      period: row.period,
      label: formatPeriodLabel(row.period),
      year: Number(row.period.slice(0, 4)),
      revenue: toRevenueYi(row.monthly_revenue),
      previousRevenue: toRevenueYi(row.previous_year_month_revenue),
      growthPct: row.year_over_year_pct,
      cumulativeRevenue: toRevenueYi(row.cumulative_revenue),
      cumulativeGrowthPct: row.cumulative_year_over_year_pct,
      monthCount: 1,
    }));
  }

  const groups = new Map<
    string,
    {
      year: number;
      quarter: number | null;
      revenue: number;
      previousRevenue: number;
      monthCount: number;
      lastPeriod: string;
    }
  >();

  sortedRows.forEach((row) => {
    const year = Number(row.period.slice(0, 4));
    const month = Number(row.period.slice(5, 7));
    const quarter = quarterFromMonth(month);
    const key = view === "quarterly" ? `${year}-Q${quarter}` : String(year);
    const current = groups.get(key) ?? {
      year,
      quarter: view === "quarterly" ? quarter : null,
      revenue: 0,
      previousRevenue: 0,
      monthCount: 0,
      lastPeriod: row.period,
    };

    current.revenue += toRevenueYi(row.monthly_revenue) ?? 0;
    current.previousRevenue += toRevenueYi(row.previous_year_month_revenue) ?? 0;
    current.monthCount += row.monthly_revenue === null || row.monthly_revenue === undefined ? 0 : 1;
    current.lastPeriod = row.period;
    groups.set(key, current);
  });

  return Array.from(groups.entries()).map<RevenueSeriesPoint>(([key, group]) => {
    const previousRevenue = group.previousRevenue || null;
    const revenue = group.monthCount ? group.revenue : null;

    return {
      period: key,
      label: key,
      year: group.year,
      revenue,
      previousRevenue,
      growthPct: revenueGrowth(revenue, previousRevenue),
      cumulativeRevenue: null,
      cumulativeGrowthPct: null,
      monthCount: group.monthCount,
    };
  });
}

function buildEarningsSeries(rows: FinancialMetricQuarterlyRead[], view: EarningsView) {
  const sortedRows = rows
    .slice()
    .sort((a, b) => a.fiscal_year - b.fiscal_year || a.quarter - b.quarter);

  if (view === "quarterly") {
    const byPeriod = new Map(sortedRows.map((row) => [row.period, row]));

    return sortedRows.map<EarningsSeriesPoint>((row) => {
      const previous = byPeriod.get(`${row.fiscal_year - 1}Q${row.quarter}`);

      return {
        period: row.period,
        label: row.period,
        fiscalYear: row.fiscal_year,
        quarter: row.quarter,
        eps: row.eps,
        previousEps: previous?.eps ?? null,
        growthPct: revenueGrowth(row.eps, previous?.eps ?? null),
        roe: row.roe,
        roa: row.roa,
        periodCount: 1,
      };
    });
  }

  const groups = new Map<
    number,
    {
      eps: number;
      previousEps: number;
      periodCount: number;
      roe: number | null;
      roa: number | null;
    }
  >();
  const rowsByYear = new Map<number, FinancialMetricQuarterlyRead[]>();

  sortedRows.forEach((row) => {
    const list = rowsByYear.get(row.fiscal_year) ?? [];
    list.push(row);
    rowsByYear.set(row.fiscal_year, list);
  });

  Array.from(rowsByYear.entries()).forEach(([year, yearRows]) => {
    const previousRows = rowsByYear.get(year - 1) ?? [];
    const quarterSet = new Set(yearRows.map((row) => row.quarter));
    const previousComparableRows = previousRows.filter((row) => quarterSet.has(row.quarter));
    const latestRow = yearRows[yearRows.length - 1];

    groups.set(year, {
      eps: yearRows.reduce((sum, row) => sum + (row.eps ?? 0), 0),
      previousEps: previousComparableRows.reduce((sum, row) => sum + (row.eps ?? 0), 0),
      periodCount: yearRows.filter((row) => row.eps !== null && row.eps !== undefined).length,
      roe: latestRow?.roe ?? null,
      roa: latestRow?.roa ?? null,
    });
  });

  return Array.from(groups.entries()).map<EarningsSeriesPoint>(([year, group]) => {
    const eps = group.periodCount ? group.eps : null;
    const previousEps = group.previousEps || null;

    return {
      period: String(year),
      label: String(year),
      fiscalYear: year,
      quarter: null,
      eps,
      previousEps,
      growthPct: revenueGrowth(eps, previousEps),
      roe: group.roe,
      roa: group.roa,
      periodCount: group.periodCount,
    };
  });
}

function RevenueTrendChart({
  points,
  view,
}: {
  points: RevenueSeriesPoint[];
  view: RevenueView;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const chartPoints = points.slice(-36);
  const viewWidth = 860;
  const viewHeight = 360;
  const left = 64;
  const right = 82;
  const top = 54;
  const height = 240;
  const width = viewWidth - left - right;
  const revenueScale = minMax(chartPoints.map((point) => point.revenue));
  const growthScale = minMax(chartPoints.map((point) => point.growthPct));

  if (!chartPoints.length || revenueScale === null) {
    return <EmptyDataState message="尚無營收圖表資料" />;
  }

  const lineScale = growthScale ?? { min: -1, max: 1 };
  const growthPath = buildNumericLinePath(
    chartPoints,
    (point) => point.growthPct,
    lineScale,
    left,
    top,
    width,
    height
  );
  const barWidth = Math.max(4, Math.min(18, width / Math.max(chartPoints.length, 1) - 4));
  const hoverPoint = hoverIndex === null ? null : chartPoints[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, chartPoints.length, left, width);
  const hoverRevenueY =
    hoverPoint?.revenue === null || hoverPoint?.revenue === undefined
      ? null
      : chartY(hoverPoint.revenue, revenueScale.min, revenueScale.max, top, height);
  const hoverGrowthY =
    hoverPoint?.growthPct === null || hoverPoint?.growthPct === undefined
      ? null
      : chartY(hoverPoint.growthPct, lineScale.min, lineScale.max, top, height);
  const hoverTipWidth = 190;
  const hoverTipHeight = 96;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverGrowthY ?? hoverRevenueY ?? top + height / 2, hoverTipHeight, top, height);

  return (
    <div className="border border-slate-200 bg-white px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-3 w-5 rounded-sm bg-orange-300" />
          {view === "monthly" ? "單月營收(億)" : view === "quarterly" ? "單季營收(億)" : "年度營收(億)"}
        </span>
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-red-400" />
          年增(%)
        </span>
      </div>

      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[360px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, chartPoints.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2, 3].map((tick) => {
          const y = top + (tick / 3) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <text x={left} y={20} className="fill-slate-500 text-[10px]">
          營收(億)
        </text>
        <text x={left + width + right} y={20} textAnchor="end" className="fill-slate-500 text-[10px]">
          年增(%)
        </text>
        {chartPoints.map((point, index) => {
          const value = point.revenue ?? revenueScale.min;
          const x = chartX(index, chartPoints.length, left, width) - barWidth / 2;
          const y = chartY(value, revenueScale.min, revenueScale.max, top, height);

          return (
            <rect
              key={point.period}
              x={x}
              y={y}
              width={barWidth}
              height={top + height - y}
              fill="#fdba74"
              opacity="0.76"
            />
          );
        })}
        {growthPath ? (
          <path d={growthPath} fill="none" stroke="#ff5b5b" strokeWidth="2.4" strokeLinecap="round" />
        ) : null}
        {chartPoints.map((point, index) => {
          if (point.growthPct === null || point.growthPct === undefined) return null;
          const x = chartX(index, chartPoints.length, left, width);
          const y = chartY(point.growthPct, lineScale.min, lineScale.max, top, height);
          return <circle key={`${point.period}-growth`} cx={x} cy={y} r={3} fill="white" stroke="#ff5b5b" strokeWidth="2" />;
        })}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatRevenueYiValue(revenueScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatRevenueYiValue(revenueScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
          {formatPct(lineScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
          {formatPct(lineScale.min)}
        </text>
        <text x={left} y={top + height + 28} className="fill-slate-500 text-[10px]">
          {chartPoints[0]?.label}
        </text>
        <text x={left + width} y={top + height + 28} textAnchor="end" className="fill-slate-500 text-[10px]">
          {chartPoints[chartPoints.length - 1]?.label}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            <rect x={hoverX - 34} y={top + height + 34} width={68} height={22} rx={3} fill="#6b7280" />
            <text x={hoverX} y={top + height + 49} textAnchor="middle" className="fill-white text-[11px] font-semibold">
              {hoverPoint.label}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {hoverPoint.label}
              </text>
              <rect x={12} y={34} width={10} height={10} fill="#fdba74" />
              <text x={30} y={43} className="fill-slate-600 text-[12px]">
                營收(億)
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatRevenueYiValue(hoverPoint.revenue)}
              </text>
              <circle cx={17} cy={62} r={4} fill="#ff5b5b" />
              <text x={30} y={66} className="fill-slate-600 text-[12px]">
                年增
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className={`text-[12px] font-semibold ${valueTone(hoverPoint.growthPct).replace("text-", "fill-")}`}>
                {formatPct(hoverPoint.growthPct)}
              </text>
              <text x={30} y={86} className="fill-slate-500 text-[11px]">
                月數 {hoverPoint.monthCount}
              </text>
            </g>
          </g>
        ) : null}
        <rect x={left} y={top} width={width} height={height + 60} fill="transparent" pointerEvents="all" />
      </svg>
    </div>
  );
}

function EarningsTrendChart({
  points,
  view,
}: {
  points: EarningsSeriesPoint[];
  view: EarningsView;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const chartPoints = points.slice(-36);
  const viewWidth = 860;
  const viewHeight = 360;
  const left = 64;
  const right = 82;
  const top = 54;
  const height = 240;
  const width = viewWidth - left - right;
  const epsScale = minMax(chartPoints.map((point) => point.eps));
  const growthScale = minMax(chartPoints.map((point) => point.growthPct));

  if (!chartPoints.length || epsScale === null) {
    return <EmptyDataState message="尚無盈餘圖表資料" />;
  }

  const lineScale = growthScale ?? { min: -1, max: 1 };
  const growthPath = buildNumericLinePath(
    chartPoints,
    (point) => point.growthPct,
    lineScale,
    left,
    top,
    width,
    height
  );
  const barWidth = Math.max(4, Math.min(18, width / Math.max(chartPoints.length, 1) - 4));
  const hoverPoint = hoverIndex === null ? null : chartPoints[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, chartPoints.length, left, width);
  const hoverEpsY =
    hoverPoint?.eps === null || hoverPoint?.eps === undefined
      ? null
      : chartY(hoverPoint.eps, epsScale.min, epsScale.max, top, height);
  const hoverGrowthY =
    hoverPoint?.growthPct === null || hoverPoint?.growthPct === undefined
      ? null
      : chartY(hoverPoint.growthPct, lineScale.min, lineScale.max, top, height);
  const hoverTipWidth = 190;
  const hoverTipHeight = 112;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverGrowthY ?? hoverEpsY ?? top + height / 2, hoverTipHeight, top, height);

  return (
    <div className="border border-slate-200 bg-white px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-3 w-5 rounded-sm bg-orange-300" />
          {view === "quarterly" ? "每股盈餘" : "年度EPS"}
        </span>
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-red-400" />
          年增(%)
        </span>
      </div>

      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[360px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, chartPoints.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2, 3].map((tick) => {
          const y = top + (tick / 3) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <text x={left} y={20} className="fill-slate-500 text-[10px]">
          EPS(元)
        </text>
        <text x={left + width + right} y={20} textAnchor="end" className="fill-slate-500 text-[10px]">
          年增(%)
        </text>
        {chartPoints.map((point, index) => {
          const value = point.eps ?? epsScale.min;
          const x = chartX(index, chartPoints.length, left, width) - barWidth / 2;
          const y = chartY(value, epsScale.min, epsScale.max, top, height);

          return (
            <rect
              key={point.period}
              x={x}
              y={y}
              width={barWidth}
              height={top + height - y}
              fill="#fdba74"
              opacity="0.78"
            />
          );
        })}
        {growthPath ? (
          <path d={growthPath} fill="none" stroke="#ff5b5b" strokeWidth="2.4" strokeLinecap="round" />
        ) : null}
        {chartPoints.map((point, index) => {
          if (point.growthPct === null || point.growthPct === undefined) return null;
          const x = chartX(index, chartPoints.length, left, width);
          const y = chartY(point.growthPct, lineScale.min, lineScale.max, top, height);
          return <circle key={`${point.period}-growth`} cx={x} cy={y} r={3} fill="white" stroke="#ff5b5b" strokeWidth="2" />;
        })}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatPrice(epsScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatPrice(epsScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
          {formatPct(lineScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
          {formatPct(lineScale.min)}
        </text>
        <text x={left} y={top + height + 28} className="fill-slate-500 text-[10px]">
          {chartPoints[0]?.label}
        </text>
        <text x={left + width} y={top + height + 28} textAnchor="end" className="fill-slate-500 text-[10px]">
          {chartPoints[chartPoints.length - 1]?.label}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            <rect x={hoverX - 34} y={top + height + 34} width={68} height={22} rx={3} fill="#6b7280" />
            <text x={hoverX} y={top + height + 49} textAnchor="middle" className="fill-white text-[11px] font-semibold">
              {hoverPoint.label}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {hoverPoint.label}
              </text>
              <rect x={12} y={34} width={10} height={10} fill="#fdba74" />
              <text x={30} y={43} className="fill-slate-600 text-[12px]">
                EPS
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatPrice(hoverPoint.eps)}
              </text>
              <circle cx={17} cy={62} r={4} fill="#ff5b5b" />
              <text x={30} y={66} className="fill-slate-600 text-[12px]">
                年增
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className={`text-[12px] font-semibold ${valueTone(hoverPoint.growthPct).replace("text-", "fill-")}`}>
                {formatPct(hoverPoint.growthPct)}
              </text>
              <text x={30} y={86} className="fill-slate-500 text-[11px]">
                ROE {formatRatioPct(hoverPoint.roe)}
              </text>
              <text x={hoverTipWidth - 12} y={86} textAnchor="end" className="fill-slate-500 text-[11px]">
                ROA {formatRatioPct(hoverPoint.roa)}
              </text>
            </g>
          </g>
        ) : null}
        <rect x={left} y={top} width={width} height={height + 60} fill="transparent" pointerEvents="all" />
      </svg>
    </div>
  );
}

function ShareholdingMixedChart({ points }: { points: ShareholdingSeriesPoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const viewWidth = 860;
  const viewHeight = 330;
  const left = 64;
  const right = 86;
  const top = 50;
  const height = 220;
  const width = viewWidth - left - right;
  const largeScale = minMax(points.map((point) => point.largeRatio));
  const closeScale = minMax(points.map((point) => point.close));
  const showClose = closeScale !== null && points.some((point) => point.close !== null);

  if (points.length === 0 || largeScale === null) {
    return <EmptyDataState message="尚無股權分散趨勢資料" />;
  }

  const closePath =
    showClose && closeScale
      ? buildLinePath(points, "close", closeScale, left, top, width, height)
      : "";
  const barWidth = Math.max(2, Math.min(10, width / Math.max(points.length, 1) - 2));
  const hoverPoint = hoverIndex === null ? null : points[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, points.length, left, width);
  const hoverLargeY =
    hoverPoint?.largeRatio === null || hoverPoint?.largeRatio === undefined
      ? null
      : chartY(hoverPoint.largeRatio, largeScale.min, largeScale.max, top, height);
  const hoverCloseY =
    hoverPoint?.close === null || hoverPoint?.close === undefined || closeScale === null
      ? null
      : chartY(hoverPoint.close, closeScale.min, closeScale.max, top, height);
  const hoverPrimaryY = hoverCloseY ?? hoverLargeY ?? top + height / 2;
  const hoverTipWidth = 168;
  const hoverTipHeight = 82;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverPrimaryY, hoverTipHeight, top, height);

  return (
    <div className="border border-slate-200 bg-white px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-3 w-5 rounded-sm bg-orange-300" />
          大股東持股(%)
        </span>
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-red-400" />
          收盤價
        </span>
      </div>
      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[330px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, points.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2, 3].map((tick) => {
          const y = top + (tick / 3) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <text x={left} y={18} className="fill-slate-500 text-[10px]">
          大股東持股(%)
        </text>
        <text x={left + width + right} y={18} textAnchor="end" className="fill-slate-500 text-[10px]">
          收盤價
        </text>
        {points.map((point, index) => {
          const value = point.largeRatio ?? largeScale.min;
          const x = chartX(index, points.length, left, width) - barWidth / 2;
          const y = chartY(value, largeScale.min, largeScale.max, top, height);
          return (
            <rect
              key={point.date}
              x={x}
              y={y}
              width={barWidth}
              height={top + height - y}
              fill="#fdba74"
              opacity="0.72"
            />
          );
        })}
        {closePath ? (
          <path d={closePath} fill="none" stroke="#ff5b5b" strokeWidth="2" strokeLinecap="round" />
        ) : null}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {largeScale.max.toFixed(2)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {largeScale.min.toFixed(2)}
        </text>
        {closeScale ? (
          <>
            <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
              {formatPrice(closeScale.max)}
            </text>
            <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
              {formatPrice(closeScale.min)}
            </text>
          </>
        ) : null}
        <text x={left} y={top + height + 24} className="fill-slate-500 text-[10px]">
          {formatCompactDate(points[0]?.date)}
        </text>
        <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatCompactDate(points[points.length - 1]?.date)}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            {hoverLargeY !== null ? (
              <g>
                <rect x={8} y={hoverLargeY - 12} width={48} height={22} rx={3} fill="#6b7280" />
                <text
                  x={32}
                  y={hoverLargeY + 3}
                  textAnchor="middle"
                  className="fill-white text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.largeRatio)}
                </text>
                <line
                  x1={left}
                  x2={left + width}
                  y1={hoverLargeY}
                  y2={hoverLargeY}
                  stroke="#94a3b8"
                  strokeDasharray="4 4"
                />
              </g>
            ) : null}
            {hoverCloseY !== null ? (
              <g>
                <rect
                  x={viewWidth - 58}
                  y={hoverCloseY - 12}
                  width={50}
                  height={22}
                  rx={3}
                  fill="#6b7280"
                />
                <text
                  x={viewWidth - 33}
                  y={hoverCloseY + 3}
                  textAnchor="middle"
                  className="fill-white text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.close)}
                </text>
              </g>
            ) : null}
            <rect x={hoverX - 34} y={top + height + 28} width={68} height={22} rx={3} fill="#6b7280" />
            <text
              x={hoverX}
              y={top + height + 43}
              textAnchor="middle"
              className="fill-white text-[11px] font-semibold"
            >
              {formatCompactDate(hoverPoint.date)}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {formatCompactDate(hoverPoint.date)}
              </text>
              <circle cx={16} cy={40} r={4} fill="#fdba74" />
              <text x={28} y={44} className="fill-slate-600 text-[12px]">
                大股東持股(%)
              </text>
              <text x={hoverTipWidth - 12} y={44} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatPrice(hoverPoint.largeRatio)}
              </text>
              <circle cx={16} cy={62} r={4} fill="#ff5b5b" />
              <text x={28} y={66} className="fill-slate-600 text-[12px]">
                收盤價
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatPrice(hoverPoint.close)}
              </text>
            </g>
          </g>
        ) : null}
        <rect
          x={left}
          y={top}
          width={width}
          height={height + 54}
          fill="transparent"
          pointerEvents="all"
        />
      </svg>
    </div>
  );
}

function ShareholdingRatioChart({ points }: { points: ShareholdingSeriesPoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const viewWidth = 860;
  const viewHeight = 300;
  const left = 64;
  const right = 72;
  const top = 44;
  const height = 196;
  const width = viewWidth - left - right;
  const largeScale = minMax(points.map((point) => point.largeRatio));
  const smallScale = minMax(points.map((point) => point.smallRatio));

  if (points.length === 0 || largeScale === null || smallScale === null) {
    return <EmptyDataState message="尚無大戶/小股東持股比例資料" />;
  }

  const largePath = buildLinePath(points, "largeRatio", largeScale, left, top, width, height);
  const smallPath = buildLinePath(points, "smallRatio", smallScale, left, top, width, height);
  const hoverPoint = hoverIndex === null ? null : points[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, points.length, left, width);
  const hoverLargeY =
    hoverPoint?.largeRatio === null || hoverPoint?.largeRatio === undefined
      ? null
      : chartY(hoverPoint.largeRatio, largeScale.min, largeScale.max, top, height);
  const hoverSmallY =
    hoverPoint?.smallRatio === null || hoverPoint?.smallRatio === undefined
      ? null
      : chartY(hoverPoint.smallRatio, smallScale.min, smallScale.max, top, height);
  const hoverPrimaryY = hoverLargeY ?? hoverSmallY ?? top + height / 2;
  const hoverTipWidth = 182;
  const hoverTipHeight = 82;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverPrimaryY, hoverTipHeight, top, height);

  return (
    <div className="border border-slate-200 bg-white px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-orange-300" />
          大股東持股(%)
        </span>
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-red-400" />
          小股東持股(%)
        </span>
      </div>
      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[300px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, points.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2, 3].map((tick) => {
          const y = top + (tick / 3) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <path d={largePath} fill="none" stroke="#fdba74" strokeWidth="2" strokeLinecap="round" />
        <path d={smallPath} fill="none" stroke="#ff5b5b" strokeWidth="2" strokeLinecap="round" />
        <text x={left} y={18} className="fill-slate-500 text-[10px]">
          大股東持股(%)
        </text>
        <text x={left + width + right} y={18} textAnchor="end" className="fill-slate-500 text-[10px]">
          小股東持股(%)
        </text>
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {largeScale.max.toFixed(2)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {largeScale.min.toFixed(2)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
          {smallScale.max.toFixed(2)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
          {smallScale.min.toFixed(2)}
        </text>
        <text x={left} y={top + height + 24} className="fill-slate-500 text-[10px]">
          {formatCompactDate(points[0]?.date)}
        </text>
        <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatCompactDate(points[points.length - 1]?.date)}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            {hoverLargeY !== null ? (
              <g>
                <rect x={8} y={hoverLargeY - 12} width={48} height={22} rx={3} fill="#6b7280" />
                <text
                  x={32}
                  y={hoverLargeY + 3}
                  textAnchor="middle"
                  className="fill-white text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.largeRatio)}
                </text>
                <line
                  x1={left}
                  x2={left + width}
                  y1={hoverLargeY}
                  y2={hoverLargeY}
                  stroke="#94a3b8"
                  strokeDasharray="4 4"
                />
              </g>
            ) : null}
            {hoverSmallY !== null ? (
              <g>
                <rect
                  x={viewWidth - 58}
                  y={hoverSmallY - 12}
                  width={50}
                  height={22}
                  rx={3}
                  fill="#6b7280"
                />
                <text
                  x={viewWidth - 33}
                  y={hoverSmallY + 3}
                  textAnchor="middle"
                  className="fill-white text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.smallRatio)}
                </text>
              </g>
            ) : null}
            <rect x={hoverX - 34} y={top + height + 28} width={68} height={22} rx={3} fill="#6b7280" />
            <text
              x={hoverX}
              y={top + height + 43}
              textAnchor="middle"
              className="fill-white text-[11px] font-semibold"
            >
              {formatCompactDate(hoverPoint.date)}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {formatCompactDate(hoverPoint.date)}
              </text>
              <circle cx={16} cy={40} r={4} fill="#fdba74" />
              <text x={28} y={44} className="fill-slate-600 text-[12px]">
                大股東持股(%)
              </text>
              <text x={hoverTipWidth - 12} y={44} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatPrice(hoverPoint.largeRatio)}
              </text>
              <circle cx={16} cy={62} r={4} fill="#ff5b5b" />
              <text x={28} y={66} className="fill-slate-600 text-[12px]">
                小股東持股(%)
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatPrice(hoverPoint.smallRatio)}
              </text>
            </g>
          </g>
        ) : null}
        <rect
          x={left}
          y={top}
          width={width}
          height={height + 54}
          fill="transparent"
          pointerEvents="all"
        />
      </svg>
    </div>
  );
}

function InstitutionalFlowChart({
  points,
  title,
  netKey,
  cumulativeKey,
}: {
  points: InstitutionalSeriesPoint[];
  title: string;
  netKey: InstitutionalNetKey;
  cumulativeKey: InstitutionalCumulativeKey;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const chartPoints = points;
  const viewWidth = 860;
  const viewHeight = 150;
  const left = 64;
  const right = 72;
  const top = 24;
  const height = 88;
  const width = viewWidth - left - right;
  const netValues = chartPoints
    .map((point) => point[netKey])
    .filter((value): value is number => value !== null && value !== undefined);
  const cumulativeScale = minMax(chartPoints.map((point) => point[cumulativeKey])) ?? {
    min: -1,
    max: 1,
  };
  const netMax = Math.max(...netValues.map((value) => Math.abs(value)), 1);
  const netScale = { min: -netMax, max: netMax };
  const zeroY = chartY(0, netScale.min, netScale.max, top, height);
  const barWidth = Math.max(2, Math.min(9, width / Math.max(chartPoints.length, 1) - 2));
  const cumulativePath = buildNumericLinePath(
    chartPoints,
    (point) => point[cumulativeKey],
    cumulativeScale,
    left,
    top,
    width,
    height
  );
  const latestPoint = chartPoints[chartPoints.length - 1] ?? null;
  const hoverPoint = hoverIndex === null ? null : chartPoints[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, chartPoints.length, left, width);
  const hoverNetY =
    hoverPoint?.[netKey] === null || hoverPoint?.[netKey] === undefined
      ? null
      : chartY(hoverPoint[netKey], netScale.min, netScale.max, top, height);
  const hoverCumY =
    hoverPoint?.[cumulativeKey] === null || hoverPoint?.[cumulativeKey] === undefined
      ? null
      : chartY(hoverPoint[cumulativeKey], cumulativeScale.min, cumulativeScale.max, top, height);
  const hoverTipWidth = 182;
  const hoverTipHeight = 82;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverCumY ?? hoverNetY ?? top + height / 2, hoverTipHeight, top, height);

  if (!chartPoints.length) {
    return <EmptyDataState message={`${title} 尚無歷史資料`} />;
  }

  return (
    <div className="border-t border-slate-200 py-3 first:border-t-0">
      <div className="mb-2 flex items-center justify-between gap-4 text-xs">
        <div className="font-semibold text-slate-900">
          {title}
          <span className={`ml-2 ${valueTone(latestPoint?.[cumulativeKey])}`}>
            累計 {formatSignedLots(latestPoint?.[cumulativeKey])}張
          </span>
        </div>
        <div>
          <span className="text-slate-500">買賣超：</span>
          <span className={valueTone(latestPoint?.[netKey])}>
            {formatSignedLots(latestPoint?.[netKey])}張
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[150px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, chartPoints.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2].map((tick) => {
          const y = top + (tick / 2) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <line x1={left} x2={left + width} y1={zeroY} y2={zeroY} stroke="#94a3b8" />
        {chartPoints.map((point, index) => {
          const value = point[netKey] ?? 0;
          const x = chartX(index, chartPoints.length, left, width) - barWidth / 2;
          const y = chartY(value, netScale.min, netScale.max, top, height);
          return (
            <rect
              key={point.date}
              x={x}
              y={Math.min(y, zeroY)}
              width={barWidth}
              height={Math.max(1, Math.abs(zeroY - y))}
              fill={value >= 0 ? "#ef4444" : "#10b981"}
              opacity="0.78"
            />
          );
        })}
        {cumulativePath ? (
          <path d={cumulativePath} fill="none" stroke="#93c5fd" strokeWidth="2" strokeLinecap="round" />
        ) : null}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatLots(netScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatSignedLots(netScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
          {formatLots(cumulativeScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
          {formatSignedLots(cumulativeScale.min)}
        </text>
        <text x={left} y={top + height + 24} className="fill-slate-500 text-[10px]">
          {formatMonthDay(chartPoints[0]?.date)}
        </text>
        <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatMonthDay(chartPoints[chartPoints.length - 1]?.date)}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            {hoverNetY !== null ? (
              <g>
                <rect x={8} y={hoverNetY - 12} width={52} height={22} rx={3} fill="#6b7280" />
                <text x={34} y={hoverNetY + 3} textAnchor="middle" className="fill-white text-[11px] font-semibold">
                  {formatSignedLots(hoverPoint[netKey])}
                </text>
              </g>
            ) : null}
            {hoverCumY !== null ? (
              <g>
                <rect x={viewWidth - 62} y={hoverCumY - 12} width={54} height={22} rx={3} fill="#6b7280" />
                <text x={viewWidth - 35} y={hoverCumY + 3} textAnchor="middle" className="fill-white text-[11px] font-semibold">
                  {formatSignedLots(hoverPoint[cumulativeKey])}
                </text>
              </g>
            ) : null}
            <rect x={hoverX - 28} y={top + height + 28} width={56} height={20} rx={3} fill="#6b7280" />
            <text x={hoverX} y={top + height + 42} textAnchor="middle" className="fill-white text-[11px] font-semibold">
              {formatMonthDay(hoverPoint.date)}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {formatDate(hoverPoint.date)}
              </text>
              <rect x={12} y={34} width={8} height={8} fill={(hoverPoint[netKey] ?? 0) >= 0 ? "#ef4444" : "#10b981"} />
              <text x={28} y={43} className="fill-slate-600 text-[12px]">
                買賣超(張)
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatSignedLots(hoverPoint[netKey])}
              </text>
              <circle cx={16} cy={62} r={4} fill="#93c5fd" />
              <text x={28} y={66} className="fill-slate-600 text-[12px]">
                累計(張)
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatSignedLots(hoverPoint[cumulativeKey])}
              </text>
            </g>
          </g>
        ) : null}
        <rect x={left} y={top} width={width} height={height + 48} fill="transparent" pointerEvents="all" />
      </svg>
    </div>
  );
}

export default function StockDetailPanel({
  stockId,
  stockName,
  initialChartData = [],
  initialIndicatorData = [],
  watchlistRankingPanel,
}: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("daily");
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [chartIndicators, setChartIndicators] =
    useState<IndicatorSettings>(defaultIndicators);
  const [chartData, setChartData] = useState<ChartPoint[]>(initialChartData);
  const [todayTrend, setTodayTrend] = useState<IntradayTrendPoint[]>([]);
  const [todayPreviousClose, setTodayPreviousClose] = useState<number | null>(null);
  const [todaySource, setTodaySource] = useState("unavailable");
  const [todayUpdatedAt, setTodayUpdatedAt] = useState<string | null>(null);
  const [indicatorData, setIndicatorData] =
    useState<StockIndicatorPoint[]>(initialIndicatorData);
  const [institutional, setInstitutional] = useState<InstitutionalTradeDailyRead | null>(null);
  const [institutionalHistory, setInstitutionalHistory] = useState<InstitutionalTradeDailyRead[]>([]);
  const [margin, setMargin] = useState<MarginTradingDailyRead | null>(null);
  const [shareholding, setShareholding] = useState<ShareholdingDistributionWeeklyRead[]>([]);
  const [monthlyRevenue, setMonthlyRevenue] = useState<MonthlyRevenueRead | null>(null);
  const [monthlyRevenueHistory, setMonthlyRevenueHistory] = useState<MonthlyRevenueRead[]>([]);
  const [financialMetric, setFinancialMetric] =
    useState<FinancialMetricQuarterlyRead | null>(null);
  const [financialMetricHistory, setFinancialMetricHistory] = useState<FinancialMetricQuarterlyRead[]>([]);
  const [stockInfo, setStockInfo] = useState<StockMasterRead | null>(null);
  const [activeDataTab, setActiveDataTab] = useState<DataPanelTab>("chips");
  const [dataPanelLoading, setDataPanelLoading] = useState<DataPanelTab | null>(null);
  const [dataPanelMessage, setDataPanelMessage] = useState<string | null>(null);
  const [largeHolderLots, setLargeHolderLots] = useState(1000);
  const [smallHolderLots, setSmallHolderLots] = useState(100);
  const [revenueView, setRevenueView] = useState<RevenueView>("monthly");
  const [earningsView, setEarningsView] = useState<EarningsView>("quarterly");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const finalIntradayRefreshDate = useRef<string | null>(null);
  const activeStockIdRef = useRef<string | null>(stockId);
  const activeDataTabRef = useRef<DataPanelTab>(activeDataTab);
  const dataPanelRequestKeyRef = useRef<string | null>(null);

  useEffect(() => {
    activeStockIdRef.current = stockId;
  }, [stockId]);

  useEffect(() => {
    activeDataTabRef.current = activeDataTab;
  }, [activeDataTab]);

  function toggleChartIndicator(key: IndicatorKey) {
    setChartIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  useEffect(() => {
    if (!stockId) {
      const timer = window.setTimeout(() => {
        setChartData([]);
        setTodayTrend([]);
        setTodayPreviousClose(null);
        setTodaySource("unavailable");
        setTodayUpdatedAt(null);
        setIndicatorData([]);
        setInstitutional(null);
        setInstitutionalHistory([]);
        setMargin(null);
        setShareholding([]);
        setMonthlyRevenue(null);
        setMonthlyRevenueHistory([]);
        setFinancialMetric(null);
        setFinancialMetricHistory([]);
        setStockInfo(null);
        setActiveDataTab("chips");
        setDataPanelLoading(null);
        setDataPanelMessage(null);
        setLoadState("idle");
        setErrorMessage(null);
      }, 0);

      return () => window.clearTimeout(timer);
    }

    let cancelled = false;

    async function loadStaticDetail() {
      try {
        const [
          institutionalData,
          institutionalHistoryData,
          marginData,
          shareholdingData,
          revenueData,
          revenueHistoryData,
          financialData,
          financialHistoryData,
          stockData,
        ] = await Promise.all([
          fetchOptional<InstitutionalTradeDailyRead>(
            `/api/market/institutional/${stockId}/latest`,
            { ensure_daily: false }
          ),
          fetchOptional<InstitutionalTradeDailyRead[]>(
            `/api/market/institutional/${stockId}/history`,
            { limit: institutionalHistoryLimit, ensure_history: false }
          ),
          fetchOptional<MarginTradingDailyRead>(`/api/market/margin/${stockId}/latest`, {
            ensure_daily: false,
          }),
          fetchOptional<ShareholdingDistributionWeeklyRead[]>(
            `/api/market/shareholding/${stockId}/history`,
            { limit: 12000, ensure_history: false }
          ),
          fetchOptional<MonthlyRevenueRead>(`/api/market/revenue/${stockId}/latest`, {
            ensure_latest: false,
          }),
          fetchOptional<MonthlyRevenueRead[]>(`/api/market/revenue/${stockId}/history`, {
            limit: revenueHistoryLimit,
            ensure_history: false,
          }),
          fetchOptional<FinancialMetricQuarterlyRead>(
            `/api/market/financials/${stockId}/latest`,
            { ensure_latest: false }
          ),
          fetchOptional<FinancialMetricQuarterlyRead[]>(
            `/api/market/financials/${stockId}/history`,
            { limit: financialHistoryLimit, ensure_history: false }
          ),
          fetchOptional<StockMasterRead>(`/api/stocks/${stockId}`),
        ]);

        if (cancelled) return;

        const currentActiveTab = activeDataTabRef.current;

        if (currentActiveTab !== "institutional") {
          setInstitutional(institutionalData);
          setInstitutionalHistory(institutionalHistoryData ?? []);
        }

        if (currentActiveTab !== "chips") {
          setMargin(marginData);
          setShareholding(shareholdingData ?? []);
        }

        if (currentActiveTab !== "revenue") {
          setMonthlyRevenue(revenueData);
          setMonthlyRevenueHistory(revenueHistoryData ?? []);
        }

        if (currentActiveTab !== "earnings") {
          setFinancialMetric(financialData);
          setFinancialMetricHistory(financialHistoryData ?? []);
        }

        setStockInfo(stockData);
      } catch {
        if (!cancelled) {
          const currentActiveTab = activeDataTabRef.current;

          if (currentActiveTab !== "institutional") {
            setInstitutional(null);
            setInstitutionalHistory([]);
          }

          if (currentActiveTab !== "chips") {
            setMargin(null);
            setShareholding([]);
          }

          if (currentActiveTab !== "revenue") {
            setMonthlyRevenue(null);
            setMonthlyRevenueHistory([]);
          }

          if (currentActiveTab !== "earnings") {
            setFinancialMetric(null);
            setFinancialMetricHistory([]);
          }

          setStockInfo(null);
        }
      }
    }

    void loadStaticDetail();

    return () => {
      cancelled = true;
    };
  }, [stockId]);

  useEffect(() => {
    if (!stockId) return;

    let cancelled = false;
    let intradayTimer: number | undefined;
    let intradayRequestInFlight = false;

    function clearIntradayTimer() {
      if (intradayTimer !== undefined) {
        window.clearTimeout(intradayTimer);
        intradayTimer = undefined;
      }
    }

    async function loadTodayTrend(showLoading: boolean) {
      if (intradayRequestInFlight) return;
      intradayRequestInFlight = true;

      if (showLoading) {
        setLoadState("loading");
        setErrorMessage(null);
        setTodayUpdatedAt(null);
      }

      try {
        const today = await fetchJson<IntradayTrendResponse>(
          `/api/market/intraday/${stockId}`
        );

        if (cancelled) return;

        setTodayTrend(today.points);
        setTodayPreviousClose(today.previous_close);
        setTodaySource(today.source);
        const latestPoint = today.points[today.points.length - 1] ?? null;
        setTodayUpdatedAt(latestPoint ? formatDateTime(latestPoint.time) : null);
        setLoadState("success");
        setErrorMessage(null);
      } catch (error) {
        if (cancelled) return;
        setLoadState("error");
        setErrorMessage(error instanceof Error ? error.message : "資料讀取失敗");
      } finally {
        intradayRequestInFlight = false;
      }
    }

    function scheduleTodayRefresh() {
      if (cancelled) return;

      const marketState = getTaiwanMarketRefreshState();

      if (marketState.isPollingWindow) {
        intradayTimer = window.setTimeout(() => {
          void loadTodayTrend(false).finally(scheduleTodayRefresh);
        }, TAIWAN_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalIntradayRefreshDate.current !== marketState.dateKey
      ) {
        finalIntradayRefreshDate.current = marketState.dateKey;
        intradayTimer = window.setTimeout(() => {
          void loadTodayTrend(false).finally(scheduleTodayRefresh);
        }, 0);
        return;
      }

      intradayTimer = window.setTimeout(
        scheduleTodayRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    async function loadChart() {
      if (timeframe === "today") {
        await loadTodayTrend(true);

        if (!cancelled) {
          const marketState = getTaiwanMarketRefreshState();

          if (marketState.isAfterClose) {
            finalIntradayRefreshDate.current = marketState.dateKey;
          }

          scheduleTodayRefresh();
        }

        return;
      }

      setLoadState("loading");
      setErrorMessage(null);

      try {
        const ohlc = await fetchJson<OhlcChartResponse>(`/api/market/ohlc/${stockId}`, {
          timeframe,
          bars: 90,
          ensure_history: true,
        });
        const indicators = await fetchJson<StockIndicatorPoint[]>(
          `/api/market/indicators/${stockId}/daily`,
          {
            limit: 520,
            ma_windows: "5,20,60",
            volume_ma_windows: "5,20",
          }
        );

        if (cancelled) return;

        setChartData(ohlc.points);
        setIndicatorData(indicators);
        setLoadState("success");
      } catch (error) {
        if (cancelled) return;
        setLoadState("error");
        setErrorMessage(error instanceof Error ? error.message : "資料讀取失敗");
      }
    }

    void loadChart();

    return () => {
      cancelled = true;
      clearIntradayTimer();
    };
  }, [stockId, timeframe]);

  const indicatorForTimeframe = useMemo(() => {
    if (timeframe === "daily") return indicatorData.slice(-180);
    return [];
  }, [indicatorData, timeframe]);

  const latestIndicator = indicatorData[indicatorData.length - 1] ?? null;
  const latestChart = chartData[chartData.length - 1] ?? null;
  const latestToday = todayTrend[todayTrend.length - 1] ?? null;
  const latestClose =
    timeframe === "today"
      ? latestToday?.price ?? latestIndicator?.close ?? latestChart?.close ?? null
      : latestIndicator?.close ?? latestChart?.close ?? null;
  const latestChangePct =
    timeframe === "today" && latestToday && todayPreviousClose
      ? ((latestToday.price - todayPreviousClose) / todayPreviousClose) * 100
      : latestIndicator?.change_pct ?? null;
  const ma5 = latestIndicator?.ma?.ma5 ?? null;
  const ma20 = latestIndicator?.ma?.ma20 ?? null;
  const ma60 = latestIndicator?.ma?.ma60 ?? null;
  const volumeMa20 = latestIndicator?.volume_ma?.volume_ma20 ?? null;
  const priceVsMa20 =
    latestClose !== null && ma20 !== null && ma20 !== 0
      ? ((latestClose - ma20) / ma20) * 100
      : null;
  const volumeRatio = safeRatio(latestIndicator?.volume, volumeMa20);
  const volumeRatioPct = volumeRatio === null ? null : (volumeRatio - 1) * 100;
  const totalInstitutionalNet = institutional?.total_institutional_net ?? null;
  const displayTime =
    timeframe === "today" && latestToday
      ? formatDateTime(latestToday.time)
      : latestIndicator?.time ?? latestChart?.time ?? "-";

  const technicalStatus = useMemo(() => {
    if (latestClose === null) return "資料不足";
    if (ma20 !== null && ma60 !== null && latestClose > ma20 && ma20 > ma60) {
      return "多方排列";
    }
    if (ma20 !== null && ma60 !== null && latestClose < ma20 && ma20 < ma60) {
      return "空方排列";
    }
    if (ma20 !== null && latestClose > ma20) return "偏多整理";
    if (ma20 !== null && latestClose < ma20) return "偏弱整理";
    return "中性";
  }, [latestClose, ma20, ma60]);

  const signals = useMemo(() => {
    const result: { label: string; tone: string }[] = [];

    if (latestClose !== null && ma20 !== null) {
      result.push({
        label: latestClose >= ma20 ? "收盤站上 MA20" : "收盤跌破 MA20",
        tone: latestClose >= ma20 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50",
      });
    }

    if (ma5 !== null && ma20 !== null) {
      result.push({
        label: ma5 >= ma20 ? "短均線偏多" : "短均線偏弱",
        tone: ma5 >= ma20 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50",
      });
    }

    if (volumeRatio !== null) {
      result.push({
        label: volumeRatio >= 1.5 ? "量能放大" : "量能一般",
        tone: volumeRatio >= 1.5 ? "text-amber-700 bg-amber-50" : "text-slate-600 bg-slate-100",
      });
    }

    if (totalInstitutionalNet !== null) {
      result.push({
        label: totalInstitutionalNet >= 0 ? "法人買超" : "法人賣超",
        tone:
          totalInstitutionalNet >= 0
            ? "text-red-700 bg-red-50"
            : "text-emerald-700 bg-emerald-50",
      });
    }

    return result;
  }, [latestClose, ma5, ma20, totalInstitutionalNet, volumeRatio]);

  const shareholdingSeries = useMemo<ShareholdingSeriesPoint[]>(() => {
    const closeByDate = new Map(
      indicatorData
        .filter((row) => row.time && row.close !== null && row.close !== undefined)
        .map((row) => [row.time.slice(0, 10), row.close])
    );
    const groups = new Map<string, ShareholdingDistributionWeeklyRead[]>();

    shareholding.forEach((row) => {
      groups.set(row.data_date, [...(groups.get(row.data_date) ?? []), row]);
    });

    const rows = Array.from(groups.entries())
      .sort(([leftDate], [rightDate]) => leftDate.localeCompare(rightDate))
      .map(([dataDate, groupRows]) => {
        const largeRows = groupRows.filter((row) => {
          const range = shareholdingLevelRanges[row.holding_level_order ?? -1];
          return range ? range.minLots >= largeHolderLots : false;
        });
        const smallRows = groupRows.filter((row) => {
          const range = shareholdingLevelRanges[row.holding_level_order ?? -1];
          return range?.maxLots !== null && range?.maxLots !== undefined
            ? range.maxLots <= smallHolderLots
            : false;
        });
        const largeRatio = largeRows.reduce((total, row) => total + (row.share_ratio ?? 0), 0);
        const smallRatio = smallRows.reduce((total, row) => total + (row.share_ratio ?? 0), 0);
        const largeHolders = largeRows.reduce((total, row) => total + (row.holder_count ?? 0), 0);

        return {
          date: dataDate,
          largeRatio: largeRows.length ? largeRatio : null,
          largeRatioChange: null,
          largeHolders: largeRows.length ? largeHolders : null,
          smallRatio: smallRows.length ? smallRatio : null,
          close: closeByDate.get(dataDate.slice(0, 10)) ?? null,
        };
      });

    return rows.map((row, index) => {
      const previous = rows[index - 1];
      const largeRatioChange =
        previous?.largeRatio !== null &&
        previous?.largeRatio !== undefined &&
        row.largeRatio !== null
          ? row.largeRatio - previous.largeRatio
          : null;

      return {
        ...row,
        largeRatioChange,
      };
    });
  }, [indicatorData, largeHolderLots, shareholding, smallHolderLots]);

  const institutionalSeries = useMemo<InstitutionalSeriesPoint[]>(() => {
    return institutionalHistory
      .slice()
      .sort((leftRow, rightRow) => leftRow.trade_date.localeCompare(rightRow.trade_date))
      .reduce<{
        rows: InstitutionalSeriesPoint[];
        foreignCumulative: number;
        investmentTrustCumulative: number;
        dealerCumulative: number;
        totalCumulative: number;
      }>(
        (accumulator, row) => {
          const foreignNet = row.foreign_investor_net;
          const investmentTrustNet = row.investment_trust_net;
          const dealerNet = row.dealer_net;
          const totalNet = row.total_institutional_net;
          const nextForeignCumulative = accumulator.foreignCumulative + (foreignNet ?? 0);
          const nextInvestmentTrustCumulative =
            accumulator.investmentTrustCumulative + (investmentTrustNet ?? 0);
          const nextDealerCumulative = accumulator.dealerCumulative + (dealerNet ?? 0);
          const nextTotalCumulative = accumulator.totalCumulative + (totalNet ?? 0);

          return {
            rows: [
              ...accumulator.rows,
              {
                date: row.trade_date,
                foreignNet,
                investmentTrustNet,
                dealerNet,
                totalNet,
                foreignCumulative: nextForeignCumulative,
                investmentTrustCumulative: nextInvestmentTrustCumulative,
                dealerCumulative: nextDealerCumulative,
                totalCumulative: nextTotalCumulative,
              },
            ],
            foreignCumulative: nextForeignCumulative,
            investmentTrustCumulative: nextInvestmentTrustCumulative,
            dealerCumulative: nextDealerCumulative,
            totalCumulative: nextTotalCumulative,
          };
        },
        {
          rows: [],
          foreignCumulative: 0,
          investmentTrustCumulative: 0,
          dealerCumulative: 0,
          totalCumulative: 0,
        }
      ).rows;
  }, [institutionalHistory]);

  const chipDateGroups = useMemo(() => {
    const groups = new Map<
      string,
      {
        tradeDate: string;
        institutional: InstitutionalTradeDailyRead | null;
        margin: MarginTradingDailyRead | null;
      }
    >();

    if (institutional?.trade_date) {
      groups.set(institutional.trade_date, {
        tradeDate: institutional.trade_date,
        institutional,
        margin: null,
      });
    }

    if (margin?.trade_date) {
      const current = groups.get(margin.trade_date);

      groups.set(margin.trade_date, {
        tradeDate: margin.trade_date,
        institutional: current?.institutional ?? null,
        margin,
      });
    }

    return Array.from(groups.values()).sort((a, b) =>
      b.tradeDate.localeCompare(a.tradeDate)
    );
  }, [institutional, margin]);

  const revenueSeries = useMemo(
    () => buildRevenueSeries(monthlyRevenueHistory, revenueView),
    [monthlyRevenueHistory, revenueView]
  );
  const earningsSeries = useMemo(
    () => buildEarningsSeries(financialMetricHistory, earningsView),
    [financialMetricHistory, earningsView]
  );

  async function refreshDataTab(tab: DataPanelTab) {
    if (!stockId) return;

    if (tab === "branch") {
      setDataPanelMessage("分點資料後端尚未接入，版面先保留");
      return;
    }

    const targetStockId = stockId;
    const requestKey = `${targetStockId}:${tab}`;

    if (dataPanelRequestKeyRef.current === requestKey) return;

    dataPanelRequestKeyRef.current = requestKey;
    setDataPanelLoading(tab);
    setDataPanelMessage(null);

    try {
      if (tab === "chips") {
        await requestJson<Record<string, unknown>>(
          `/api/market/backfill/shareholding/${targetStockId}/history`,
          { method: "POST" },
          {
            lookback_weeks: 52,
            sleep_seconds: 0.05,
            skip_existing: true,
          }
        );

        const [shareholdingRows, marginRows] = await Promise.all([
          fetchJson<ShareholdingDistributionWeeklyRead[]>(
            `/api/market/shareholding/${targetStockId}/history`,
            { limit: 12000, ensure_history: false }
          ),
          fetchJson<MarginTradingDailyRead[]>(`/api/market/margin/${targetStockId}/history`, {
            lookback_days: 365,
            limit: 365,
            ensure_history: true,
            sleep_seconds: 0.05,
          }),
        ]);

        if (activeStockIdRef.current !== targetStockId) return;

        setShareholding(shareholdingRows);
        setMargin(marginRows[marginRows.length - 1] ?? null);
        setDataPanelMessage("籌碼與融資融券資料已補齊");
        return;
      }

      if (tab === "institutional") {
        const institutionalRows = await fetchJson<InstitutionalTradeDailyRead[]>(
          `/api/market/institutional/${targetStockId}/history`,
          {
            lookback_days: institutionalLookbackDays,
            limit: institutionalHistoryLimit,
            ensure_history: true,
            sleep_seconds: 0.05,
          }
        );

        if (activeStockIdRef.current !== targetStockId) return;

        setInstitutional(institutionalRows[institutionalRows.length - 1] ?? null);
        setInstitutionalHistory(institutionalRows);
        setDataPanelMessage("法人資料已補齊");
        return;
      }

      if (tab === "revenue") {
        const revenueRows = await fetchJson<MonthlyRevenueRead[]>(
          `/api/market/revenue/${targetStockId}/history`,
          {
            limit: revenueHistoryLimit,
            ensure_history: true,
            backfill_months: revenueHistoryLimit,
            sleep_seconds: 0.05,
          }
        );

        if (activeStockIdRef.current !== targetStockId) return;

        setMonthlyRevenue(revenueRows[revenueRows.length - 1] ?? null);
        setMonthlyRevenueHistory(revenueRows);
        setDataPanelMessage("營收資料已補齊");
        return;
      }

      if (tab === "earnings") {
        const financialRows = await fetchJson<FinancialMetricQuarterlyRead[]>(
          `/api/market/financials/${targetStockId}/history`,
          {
            limit: financialHistoryLimit,
            ensure_history: true,
            backfill_quarters: financialHistoryLimit,
            sleep_seconds: 0.05,
          }
        );

        if (activeStockIdRef.current !== targetStockId) return;

        setFinancialMetric(financialRows[financialRows.length - 1] ?? null);
        setFinancialMetricHistory(financialRows);
        setDataPanelMessage("盈餘資料已補齊");
      }
    } catch (error) {
      if (activeStockIdRef.current !== targetStockId) return;

      const message = error instanceof Error ? error.message : "Unknown error";
      setDataPanelMessage(`補資料失敗：${message}`);
    } finally {
      if (dataPanelRequestKeyRef.current === requestKey) {
        dataPanelRequestKeyRef.current = null;
        setDataPanelLoading(null);
      }
    }
  }

  function handleDataTabClick(tab: DataPanelTab) {
    setActiveDataTab(tab);
  }

  useEffect(() => {
    if (!stockId) return;

    const timer = window.setTimeout(() => {
      void refreshDataTab(activeDataTab);
    }, 0);

    return () => window.clearTimeout(timer);
    // Populate the visible right-panel tab whenever the selected stock or tab changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stockId, activeDataTab]);

  if (!stockId) {
    return watchlistRankingPanel ? (
      <section className="min-w-0">{watchlistRankingPanel}</section>
    ) : null;
  }

  function renderChipTab() {
    const hasShareholding = shareholdingSeries.length > 0;
    const hasMargin = margin !== null;

    if (!hasShareholding && !hasMargin) {
      return <EmptyDataState message="尚無籌碼或融資融券資料" />;
    }

    return (
      <div className="space-y-5">
        <div className="space-y-2">
          <SegmentedNumberButtons
            label="大股東張數 >"
            suffix=""
            options={largeHolderLotOptions}
            value={largeHolderLots}
            onChange={setLargeHolderLots}
          />
          <SegmentedNumberButtons
            label="小股東張數 <"
            suffix=""
            options={smallHolderLotOptions}
            value={smallHolderLots}
            onChange={setSmallHolderLots}
          />
        </div>

        <ShareholdingMixedChart points={shareholdingSeries} />
        <ShareholdingRatioChart points={shareholdingSeries} />

        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-[1.1fr_1fr_1fr_1fr_1fr] bg-slate-50 text-center text-xs font-semibold text-slate-600">
            <div className="px-2 py-2 text-left">日期</div>
            <div className="border-l border-slate-200 px-2 py-2">大股東持股比例(%)</div>
            <div className="border-l border-slate-200 px-2 py-2">大股東持股變動(%)</div>
            <div className="border-l border-slate-200 px-2 py-2">大股東持股人數</div>
            <div className="border-l border-slate-200 px-2 py-2">小股東持股比例(%)</div>
          </div>
          {shareholdingSeries
            .slice()
            .reverse()
            .slice(0, 12)
            .map((row) => (
              <div
                key={row.date}
                className="grid grid-cols-[1.1fr_1fr_1fr_1fr_1fr] border-t border-slate-200 text-center text-xs"
              >
                <div className="bg-slate-50 px-2 py-2 text-left font-semibold text-slate-600">
                  {formatCompactDate(row.date)}
                </div>
                <div className="border-l border-slate-200 px-2 py-2 text-slate-950">
                  {formatPrice(row.largeRatio)}
                </div>
                <div className={`border-l border-slate-200 px-2 py-2 ${valueTone(row.largeRatioChange)}`}>
                  {formatPct(row.largeRatioChange)}
                </div>
                <div className="border-l border-slate-200 px-2 py-2 text-slate-950">
                  {formatNumber(row.largeHolders)}
                </div>
                <div className="border-l border-slate-200 px-2 py-2 text-slate-950">
                  {formatPrice(row.smallRatio)}
                </div>
              </div>
            ))}
        </div>

        {margin ? (
          <ChipMetricBlock title="融資融券">
            <MetricRow label="融資餘額" value={formatNumber(margin.margin_today_balance)} />
            <MetricRow label="融券餘額" value={formatNumber(margin.short_today_balance)} />
            <MetricRow label="資券相抵" value={formatNumber(margin.offset)} />
            <MetricRow
              label="融資買 / 賣"
              value={`${formatNumber(margin.margin_buy)} / ${formatNumber(margin.margin_sell)}`}
            />
          </ChipMetricBlock>
        ) : null}
      </div>
    );
  }

  function renderInstitutionalTab() {
    if (!institutionalSeries.length) {
      return <EmptyDataState message="尚無法人買賣超資料" />;
    }

    const latestPoint = institutionalSeries[institutionalSeries.length - 1];
    const displayStartDate = addMonthsToDateText(latestPoint.date, -institutionalDisplayMonths);
    const recentPoints = rebuildInstitutionalCumulative(
      institutionalSeries.filter((point) => point.date >= displayStartDate)
    );
    const displayLatestPoint = recentPoints[recentPoints.length - 1] ?? latestPoint;
    const tableRows = recentPoints.slice().reverse();

    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between border-b border-slate-200 pb-2">
          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Date
          </span>
          <span className="text-sm font-bold text-slate-900">
            {formatDate(latestPoint.date)}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          {[
            { label: "外資", value: displayLatestPoint.foreignCumulative },
            { label: "投信", value: displayLatestPoint.investmentTrustCumulative },
            { label: "自營商", value: displayLatestPoint.dealerCumulative },
          ].map((item) => (
            <div key={item.label} className="border border-slate-200 px-3 py-3">
              <div className="font-semibold text-slate-700">{item.label}</div>
              <div className={`mt-2 text-base font-bold ${valueTone(item.value)}`}>
                {formatSignedLots(item.value)}張
              </div>
              <div className="mt-1 text-[11px] text-slate-500">近3個月累計</div>
            </div>
          ))}
        </div>

        <div className="border border-slate-200 bg-white px-4 py-3">
          <div className="mb-2 text-sm font-bold text-slate-950">三大法人動向</div>
          <InstitutionalFlowChart
            points={recentPoints}
            title="外資"
            netKey="foreignNet"
            cumulativeKey="foreignCumulative"
          />
          <InstitutionalFlowChart
            points={recentPoints}
            title="投信"
            netKey="investmentTrustNet"
            cumulativeKey="investmentTrustCumulative"
          />
          <InstitutionalFlowChart
            points={recentPoints}
            title="自營商"
            netKey="dealerNet"
            cumulativeKey="dealerCumulative"
          />
        </div>

        <div className="overflow-hidden border border-slate-200">
          <div className="border-b border-slate-200 bg-slate-50 px-3 py-2 text-center text-sm font-bold text-slate-900">
            近3個月三大法人買賣超明細
          </div>
          <div className="grid grid-cols-[0.9fr_1fr_1fr_1fr_1fr] border-b border-slate-200 bg-white text-center text-xs font-semibold text-slate-600">
            <div className="px-2 py-2">日期</div>
            <div className="px-2 py-2">外資(張)</div>
            <div className="px-2 py-2">投信(張)</div>
            <div className="px-2 py-2">自營商(張)</div>
            <div className="px-2 py-2">合計(張)</div>
          </div>
          {tableRows.map((row) => (
            <div
              key={row.date}
              className="grid grid-cols-[0.9fr_1fr_1fr_1fr_1fr] border-b border-slate-100 text-center text-xs last:border-b-0"
            >
              <div className="px-2 py-2 text-slate-700">{formatMonthDay(row.date)}</div>
              <div className={`px-2 py-2 ${valueTone(row.foreignNet)}`}>
                {formatSignedLots(row.foreignNet)}
              </div>
              <div className={`px-2 py-2 ${valueTone(row.investmentTrustNet)}`}>
                {formatSignedLots(row.investmentTrustNet)}
              </div>
              <div className={`px-2 py-2 ${valueTone(row.dealerNet)}`}>
                {formatSignedLots(row.dealerNet)}
              </div>
              <div className={`px-2 py-2 ${valueTone(row.totalNet)}`}>
                {formatSignedLots(row.totalNet)}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  function renderBranchTab() {
    return <EmptyDataState message="分點資料後端尚未接入，版位已先保留" />;
  }

  function renderRevenueTab() {
    return renderRevenueAnalyticsTab();
  }

  function renderRevenueAnalyticsTab() {
    const activeRows = revenueSeries;
    const latestRevenue = monthlyRevenueHistory[monthlyRevenueHistory.length - 1] ?? monthlyRevenue;

    if (!activeRows.length || !latestRevenue) {
      return <EmptyDataState message="尚無營收資料" />;
    }

    const latestYear = Number(latestRevenue.period.slice(0, 4));
    const monthlyRowsByMonth = new Map(
      monthlyRevenueHistory
        .filter((row) => Number(row.period.slice(0, 4)) === latestYear)
        .map((row) => [Number(row.period.slice(5, 7)), row])
    );
    const latestRows = activeRows.slice().reverse().slice(0, 12);

    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between border-b border-slate-200 pb-2">
          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Revenue
          </span>
          <div className="flex overflow-hidden border border-slate-900 text-sm font-semibold">
            {[
              { key: "monthly", label: "月" },
              { key: "quarterly", label: "季" },
              { key: "yearly", label: "年" },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setRevenueView(item.key as RevenueView)}
                className={[
                  "h-8 w-12 border-r border-slate-900 last:border-r-0",
                  revenueView === item.key
                    ? "bg-slate-800 text-white"
                    : "bg-white text-slate-900 hover:bg-slate-50",
                ].join(" ")}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <RevenueTrendChart points={activeRows} view={revenueView} />

        {revenueView === "monthly" ? (
          <div className="overflow-hidden border border-slate-200">
            <div className="grid grid-cols-[0.7fr_1fr_1fr_1fr_1fr_1fr] border-b border-slate-200 bg-slate-50 text-center text-xs font-semibold text-slate-600">
              <div className="px-2 py-2 text-lg font-normal text-slate-700">{latestYear}</div>
              <div className="border-l border-slate-200 px-2 py-2">營收(億)</div>
              <div className="border-l border-slate-200 px-2 py-2">年增</div>
              <div className="border-l border-slate-200 px-2 py-2">年累(億)</div>
              <div className="border-l border-slate-200 px-2 py-2">累積年增</div>
              <div className="border-l border-slate-200 px-2 py-2">去年營收(億)</div>
            </div>
            {Array.from({ length: 12 }, (_, index) => 12 - index).map((month) => {
              const row = monthlyRowsByMonth.get(month);

              return (
                <div
                  key={month}
                  className="grid grid-cols-[0.7fr_1fr_1fr_1fr_1fr_1fr] border-b border-slate-100 text-center text-xs last:border-b-0"
                >
                  <div className="bg-slate-50 px-2 py-2 font-semibold text-slate-700">
                    {month}月
                  </div>
                  <div className="border-l border-slate-100 px-2 py-2 text-slate-950">
                    {formatRevenueYiValue(toRevenueYi(row?.monthly_revenue))}
                  </div>
                  <div className={`border-l border-slate-100 px-2 py-2 ${valueTone(row?.year_over_year_pct)}`}>
                    {formatPct(row?.year_over_year_pct)}
                  </div>
                  <div className="border-l border-slate-100 px-2 py-2 text-slate-950">
                    {formatRevenueYiValue(toRevenueYi(row?.cumulative_revenue))}
                  </div>
                  <div className={`border-l border-slate-100 px-2 py-2 ${valueTone(row?.cumulative_year_over_year_pct)}`}>
                    {formatPct(row?.cumulative_year_over_year_pct)}
                  </div>
                  <div className="border-l border-slate-100 px-2 py-2 text-slate-950">
                    {formatRevenueYiValue(toRevenueYi(row?.previous_year_month_revenue))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="overflow-hidden border border-slate-200">
            <div className="grid grid-cols-[1fr_1fr_1fr_1fr_0.7fr] border-b border-slate-200 bg-slate-50 text-center text-xs font-semibold text-slate-600">
              <div className="px-2 py-2 text-left">期間</div>
              <div className="border-l border-slate-200 px-2 py-2">營收(億)</div>
              <div className="border-l border-slate-200 px-2 py-2">年增</div>
              <div className="border-l border-slate-200 px-2 py-2">去年同期(億)</div>
              <div className="border-l border-slate-200 px-2 py-2">月數</div>
            </div>
            {latestRows.map((row) => (
              <div
                key={row.period}
                className="grid grid-cols-[1fr_1fr_1fr_1fr_0.7fr] border-b border-slate-100 text-center text-xs last:border-b-0"
              >
                <div className="bg-slate-50 px-2 py-2 text-left font-semibold text-slate-700">
                  {row.label}
                </div>
                <div className="border-l border-slate-100 px-2 py-2 text-slate-950">
                  {formatRevenueYiValue(row.revenue)}
                </div>
                <div className={`border-l border-slate-100 px-2 py-2 ${valueTone(row.growthPct)}`}>
                  {formatPct(row.growthPct)}
                </div>
                <div className="border-l border-slate-100 px-2 py-2 text-slate-950">
                  {formatRevenueYiValue(row.previousRevenue)}
                </div>
                <div className="border-l border-slate-100 px-2 py-2 text-slate-600">
                  {row.monthCount}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  function renderEarningsTab() {
    const activeRows = earningsSeries.length
      ? earningsSeries
      : financialMetric
        ? buildEarningsSeries([financialMetric], earningsView)
        : [];

    if (!activeRows.length) {
      return <EmptyDataState message="尚無季度盈餘資料" />;
    }

    const latestRows = activeRows.slice().reverse().slice(0, earningsView === "quarterly" ? 16 : 10);

    return (
      <div className="space-y-5">
        <div className="flex items-center justify-between border-b border-slate-200 pb-2">
          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
            Earnings
          </span>
          <div className="flex overflow-hidden border border-slate-900 text-sm font-semibold">
            {[
              { key: "quarterly", label: "季" },
              { key: "yearly", label: "年" },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setEarningsView(item.key as EarningsView)}
                className={[
                  "h-8 w-12 border-r border-slate-900 last:border-r-0",
                  earningsView === item.key
                    ? "bg-slate-800 text-white"
                    : "bg-white text-slate-900 hover:bg-slate-50",
                ].join(" ")}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <EarningsTrendChart points={activeRows} view={earningsView} />

        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr] border-b border-slate-200 bg-slate-50 text-center text-xs font-semibold text-slate-600">
            <div className="px-2 py-2 text-left">期間</div>
            <div className="border-l border-slate-200 px-2 py-2">EPS(元)</div>
            <div className="border-l border-slate-200 px-2 py-2">年增率</div>
            <div className="border-l border-slate-200 px-2 py-2">ROE</div>
            <div className="border-l border-slate-200 px-2 py-2">ROA</div>
          </div>
          {latestRows.map((row) => (
            <div
              key={row.period}
              className="grid grid-cols-[1fr_1fr_1fr_1fr_1fr] border-b border-slate-100 text-center text-xs last:border-b-0"
            >
              <div className="bg-slate-50 px-2 py-2 text-left font-semibold text-slate-700">
                {row.label}
              </div>
              <div className="border-l border-slate-100 px-2 py-2 text-slate-950">
                {formatPrice(row.eps)}
              </div>
              <div className={`border-l border-slate-100 px-2 py-2 ${valueTone(row.growthPct)}`}>
                {formatPct(row.growthPct)}
              </div>
              <div className={`border-l border-slate-100 px-2 py-2 ${valueTone(row.roe)}`}>
                {formatRatioPct(row.roe)}
              </div>
              <div className={`border-l border-slate-100 px-2 py-2 ${valueTone(row.roa)}`}>
                {formatRatioPct(row.roa)}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  function renderActiveDataTab() {
    if (activeDataTab === "institutional") return renderInstitutionalTab();
    if (activeDataTab === "branch") return renderBranchTab();
    if (activeDataTab === "revenue") return renderRevenueTab();
    if (activeDataTab === "earnings") return renderEarningsTab();
    return renderChipTab();
  }

  return (
    <section className="grid w-full grid-cols-1 items-start justify-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]">
      <div className="min-w-0 space-y-4 self-start">
        <div className="min-w-0 border border-slate-200 bg-white">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                Stock
              </div>
              <h2 className="mt-1 text-2xl font-bold text-slate-950">
                {stockId} {stockName ?? stockInfo?.stock_name ?? ""}
              </h2>
              <div className="mt-1 text-sm text-slate-500">
                {stockInfo?.market ?? "-"} · {stockInfo?.industry ?? "未分類"} ·{" "}
                {displayTime}
              </div>
            </div>

            <div className="flex items-start gap-5">
              <div className="text-right">
                <div className="text-3xl font-bold text-slate-950">
                  {formatPrice(latestClose)}
                </div>
                <div className={`mt-1 text-sm font-semibold ${valueTone(latestChangePct)}`}>
                  {formatPct(latestChangePct)}
                </div>
              </div>

              <div className="flex flex-col items-end gap-2">
                <div className="flex border border-slate-200 bg-slate-50 p-1">
                  {(Object.keys(timeframeLabels) as Timeframe[]).map((item) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => setTimeframe(item)}
                      className={[
                        "h-8 min-w-12 px-3 text-sm font-semibold transition",
                        timeframe === item
                          ? "bg-red-700 text-white"
                          : "text-slate-600 hover:bg-white",
                      ].join(" ")}
                    >
                      {timeframeLabels[item]}
                    </button>
                  ))}
                </div>

                {timeframe !== "today" ? (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className="h-8 border border-slate-900 bg-white px-3 text-sm font-semibold text-slate-900 hover:border-red-700 hover:text-red-700"
                    >
                      指標
                    </button>
                    {indicatorMenuOpen ? (
                      <div className="absolute right-0 z-20 mt-2 w-48 border border-slate-200 bg-white p-2 text-left shadow-lg">
                        {indicatorOptions.map((option) => (
                          <label
                            key={option.key}
                            className="flex cursor-pointer items-start gap-2 px-2 py-2 text-xs hover:bg-slate-50"
                          >
                            <input
                              type="checkbox"
                              checked={chartIndicators[option.key]}
                              onChange={() => toggleChartIndicator(option.key)}
                              className="mt-0.5"
                            />
                            <span>
                              <span className="block font-semibold text-slate-800">
                                {option.label}
                              </span>
                              <span className="block text-slate-500">
                                {option.description}
                              </span>
                            </span>
                          </label>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {errorMessage ? (
            <div className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700">
              {errorMessage}
            </div>
          ) : null}

          {timeframe === "today" ? (
            <IntradayTrendChart
              points={todayTrend}
              previousClose={todayPreviousClose}
              label={timeframeLabels[timeframe]}
              source={todaySource}
              refreshIntervalMs={TAIWAN_INTRADAY_REFRESH_MS}
              updatedAt={todayUpdatedAt}
            />
          ) : (
            <StockKLineChart
              chartData={chartData}
              indicatorData={indicatorForTimeframe}
              label={timeframeLabels[timeframe]}
              indicators={chartIndicators}
            />
          )}
        </div>

        {watchlistRankingPanel ? <div className="min-w-0">{watchlistRankingPanel}</div> : null}
      </div>

      <aside
        className="flex min-w-0 flex-col border border-slate-200 bg-white"
      >
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Technical
            </div>
            <div className="mt-2 flex items-end justify-between gap-4">
              <div>
                <div className="text-xl font-bold text-slate-950">{technicalStatus}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {loadState === "loading" ? "讀取中" : "均線、量能、法人綜合判讀"}
                </div>
              </div>
              <div className={`text-right text-lg font-bold ${valueTone(priceVsMa20)}`}>
                {formatPct(priceVsMa20)}
                <div className="text-xs font-medium text-slate-500">vs MA20</div>
              </div>
            </div>
          </div>

          <div className="space-y-4 px-5 py-4">
            <TechnicalBar label="價格相對 MA20" value={priceVsMa20} />
            <TechnicalBar label="量能相對 20 日均量" value={volumeRatioPct} />
            <TechnicalBar
              label="三大法人淨買賣"
              value={
                totalInstitutionalNet === null
                  ? null
                  : Math.max(-12, Math.min(12, totalInstitutionalNet / 1_000_000))
              }
            />

            <div className="grid grid-cols-3 border border-slate-200 text-center text-xs">
              <div className="px-2 py-3">
                <div className="text-slate-500">MA5</div>
                <div className="mt-1 font-semibold text-slate-900">{formatPrice(ma5)}</div>
              </div>
              <div className="border-x border-slate-200 px-2 py-3">
                <div className="text-slate-500">MA20</div>
                <div className="mt-1 font-semibold text-slate-900">{formatPrice(ma20)}</div>
              </div>
              <div className="px-2 py-3">
                <div className="text-slate-500">MA60</div>
                <div className="mt-1 font-semibold text-slate-900">{formatPrice(ma60)}</div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {signals.map((signal) => (
                <span key={signal.label} className={`px-2.5 py-1 text-xs font-semibold ${signal.tone}`}>
                  {signal.label}
                </span>
              ))}
            </div>
          </div>

          <div className="border-t border-slate-200">
            <div className="flex border-b border-slate-200">
              {dataPanelTabs.map((tab) => (
                <DataTabButton
                  key={tab.key}
                  tab={tab}
                  active={activeDataTab === tab.key}
                  onClick={() => handleDataTabClick(tab.key)}
                />
              ))}
            </div>

            <div className="px-5 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                Data
              </div>
              <div className="mt-1 flex items-end justify-between gap-4">
                <div>
                  <div className="text-lg font-bold text-slate-950">
                    {dataPanelTabs.find((tab) => tab.key === activeDataTab)?.label ?? "資料"}
                    資料
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {dataPanelLoading === activeDataTab
                      ? "補齊資料中..."
                      : dataPanelMessage ?? "依目前選取股票載入對應公開資料"}
                  </div>
                </div>
              </div>

              <div className="mt-4">{renderActiveDataTab()}</div>
            </div>
          </div>

          <div className="hidden">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Data
            </div>
            <div className="mt-1 flex items-end justify-between gap-4">
              <div>
                <div className="text-lg font-bold text-slate-950">籌碼資料</div>
                <div className="mt-1 text-xs text-slate-500">依資料日期分類</div>
              </div>
            </div>

            <div className="mt-4 space-y-4">
              {chipDateGroups.length ? (
                chipDateGroups.map((group) => (
                  <div key={group.tradeDate} className="space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                        Date
                      </span>
                      <span className="text-sm font-bold text-slate-900">
                        {group.tradeDate}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
                      <ChipMetricBlock title="三大法人">
                        <MetricRow
                          label="外資買賣超"
                          value={formatSignedNumber(group.institutional?.foreign_investor_net)}
                          tone={valueTone(group.institutional?.foreign_investor_net)}
                        />
                        <MetricRow
                          label="投信買賣超"
                          value={formatSignedNumber(group.institutional?.investment_trust_net)}
                          tone={valueTone(group.institutional?.investment_trust_net)}
                        />
                        <MetricRow
                          label="自營商買賣超"
                          value={formatSignedNumber(group.institutional?.dealer_net)}
                          tone={valueTone(group.institutional?.dealer_net)}
                        />
                        <MetricRow
                          label="三大法人合計"
                          value={formatSignedNumber(group.institutional?.total_institutional_net)}
                          tone={valueTone(group.institutional?.total_institutional_net)}
                        />
                      </ChipMetricBlock>

                      <ChipMetricBlock title="融資融券">
                        <MetricRow
                          label="融資餘額"
                          value={formatNumber(group.margin?.margin_today_balance)}
                        />
                        <MetricRow
                          label="融券餘額"
                          value={formatNumber(group.margin?.short_today_balance)}
                        />
                        <MetricRow
                          label="資券相抵"
                          value={formatNumber(group.margin?.offset)}
                        />
                        <MetricRow
                          label="融資買 / 賣"
                          value={`${formatNumber(group.margin?.margin_buy)} / ${formatNumber(
                            group.margin?.margin_sell
                          )}`}
                        />
                      </ChipMetricBlock>
                    </div>
                  </div>
                ))
              ) : (
                <div className="border border-dashed border-slate-200 px-4 py-6 text-center text-sm text-slate-500">
                  尚無三大法人或融資融券資料
                </div>
              )}
            </div>
          </div>
      </aside>

    </section>
  );
}

"use client";

import IntradayTrendChart, {
  defaultIntradayIndicators,
  intradayIndicatorOptions,
  type IntradayIndicatorKey,
  type IntradayIndicatorSettings,
  type IntradaySessionConfig,
} from "@/components/IntradayTrendChart";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
} from "@/components/StockKLineChart";
import { fetchJson, requestJson } from "@/lib/api";
import {
  US_INTRADAY_REFRESH_MS,
  US_SESSION_END_MINUTES,
  US_SESSION_START_MINUTES,
  getNewYorkMinutesOfDay,
  getUsIntradayXRatio,
  getUsMarketRefreshState,
  isUsRegularSessionPoint,
} from "@/lib/usMarketTime";
import { getUsMarketIndexConfig } from "@/lib/usMarketIndices";
import type {
  ChartPoint,
  IntradayTrendPoint,
  IntradayTrendResponse,
  USCompanyProfileRead,
  USCorporateActionRead,
  USDailyPriceRefreshResultRead,
  USOhlcChartRead,
  USResourceRefreshResultRead,
  USSecCompanyFactRead,
  USSecFactRefreshResultRead,
  USSecFundamentalMetricRead,
  USSecFundamentalSummaryRead,
  USShortVolumeDailyRead,
  USStockMasterRead,
} from "@/types/market";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type Message = { type: "success" | "error"; text: string } | null;
type USChartTimeframe = "today" | "daily" | "weekly" | "monthly";
type USHistoricalTimeframe = Exclude<USChartTimeframe, "today">;
type USDataPanelTab = "ownership" | "insider" | "short" | "filings";
type CoverageStatus = "ready" | "missing" | "loading" | "stale";

type Props = {
  selectedSymbol: string | null;
  selectedSecurityName: string | null;
  watchlistRankingPanel?: ReactNode;
  onCompanyProfileChange?: (profile: USCompanyProfileRead | null) => void;
};

const timeframeOptions: Array<{ value: USChartTimeframe; label: string }> = [
  { value: "today", label: "今日" },
  { value: "daily", label: "日K" },
  { value: "weekly", label: "週K" },
  { value: "monthly", label: "月K" },
];

const usDataPanelTabs: Array<{
  key: USDataPanelTab;
  label: string;
  title: string;
  description: string;
}> = [
  {
    key: "ownership",
    label: "持倉",
    title: "持倉資料",
    description: "SEC 13F、主檔與估值欄位",
  },
  {
    key: "insider",
    label: "內部人",
    title: "內部人交易",
    description: "SEC Form 4 交易申報",
  },
  {
    key: "short",
    label: "空方",
    title: "空方資料",
    description: "FINRA short volume 與 short interest",
  },
  {
    key: "filings",
    label: "申報",
    title: "公司申報",
    description: "SEC facts、股利與拆股事件",
  },
];

const secFundamentalCards: Array<{ label: string; metric: string }> = [
  { label: "Revenue", metric: "revenue" },
  { label: "Gross Profit", metric: "gross_profit" },
  { label: "Operating Income", metric: "operating_income" },
  { label: "Net Income", metric: "net_income" },
  { label: "EPS Diluted", metric: "eps_diluted" },
  { label: "EPS Basic", metric: "eps_basic" },
  { label: "Assets", metric: "assets" },
  { label: "Liabilities", metric: "liabilities" },
  { label: "Equity", metric: "equity" },
  { label: "Cash", metric: "cash" },
  { label: "Debt Total", metric: "debt_total" },
  { label: "Operating CF", metric: "operating_cash_flow" },
  { label: "Capex", metric: "capex" },
  { label: "Shares", metric: "shares_outstanding" },
];

const barsByTimeframe: Record<USHistoricalTimeframe, number> = {
  daily: 180,
  weekly: 104,
  monthly: 72,
};

const usChartIndicators = {
  ...defaultIndicators,
  signals: false,
  ma: true,
  volume: true,
};

function formatNumber(value: number | null | undefined, maximumFractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("en-US", {
    maximumFractionDigits,
  });
}

function formatVolume(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("en-US");
}

function formatCompactCurrency(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const absValue = Math.abs(value);
  if (absValue >= 1_000_000_000_000) return `$${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (absValue >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (absValue >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  return `$${formatNumber(value, 0)}`;
}

function formatRatioAsPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  const normalized = Math.abs(value) <= 1 ? value * 100 : value;
  return `${normalized.toFixed(2)}%`;
}

function formatActionValue(action: USCorporateActionRead) {
  if (action.action_type === "dividend") {
    return action.amount !== null && action.amount !== undefined
      ? `$${formatNumber(action.amount, 4)}`
      : "-";
  }

  if (action.action_type === "split") {
    if (action.split_from !== null && action.split_to !== null) {
      return `${formatNumber(action.split_to, 2)}:${formatNumber(action.split_from, 2)}`;
    }
    return action.split_ratio !== null && action.split_ratio !== undefined
      ? `${formatNumber(action.split_ratio, 4)}x`
      : "-";
  }

  return "-";
}

async function fetchOptionalJson<T>(
  path: string,
  params?: Record<string, string | number | boolean>
) {
  try {
    return await fetchJson<T>(path, params);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("API 404:")) {
      return null;
    }

    throw error;
  }
}

const usIntradaySession: IntradaySessionConfig = {
  startMinutes: US_SESSION_START_MINUTES,
  endMinutes: US_SESSION_END_MINUTES,
  timeTicks: [
    { label: "09:30", minutes: 9 * 60 + 30 },
    { label: "11:00", minutes: 11 * 60 },
    { label: "12:30", minutes: 12 * 60 + 30 },
    { label: "14:00", minutes: 14 * 60 },
    { label: "15:30", minutes: 15 * 60 + 30 },
    { label: "16:00", minutes: 16 * 60 },
  ],
  getMinutesOfDay: getNewYorkMinutesOfDay,
  getXRatio: getUsIntradayXRatio,
  isRegularSessionPoint: isUsRegularSessionPoint,
  volumeFormatter: formatVolume,
};

function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

function latestDate(values: Array<string | null | undefined>) {
  const validDates = values.filter((value): value is string => Boolean(value));
  if (!validDates.length) return "-";

  const sortedDates = validDates.sort((left, right) => left.localeCompare(right));
  return formatDate(sortedDates[sortedDates.length - 1]);
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
    timeZone: "America/New_York",
  }).format(date);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-slate-500";
  }
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
}

function assetTypeLabel(stock: USStockMasterRead | null) {
  if (!stock) return "-";
  if (stock.asset_type === "ETF") return "ETF";
  if (stock.asset_type === "stock") return "Stock";
  return stock.asset_type || "-";
}

function stockName(stock: USStockMasterRead | null, fallback: string | null) {
  return stock?.security_name ?? stock?.sec_company_name ?? fallback ?? "";
}

function toChartPoint(point: USOhlcChartRead["points"][number]): ChartPoint {
  return {
    time: String(point.time).slice(0, 10),
    open: point.open,
    high: point.high,
    low: point.low,
    close: point.close,
    volume: point.volume,
    trade_value: null,
    transaction_count: null,
  };
}

function averageLast(values: Array<number | null | undefined>, windowSize: number) {
  const validValues = values
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value);
    })
    .slice(-windowSize);

  if (!validValues.length) return null;

  return validValues.reduce((total, value) => total + value, 0) / validValues.length;
}

function summarizeUsIntradayPoints(points: IntradayTrendPoint[]) {
  const regularPoints = points.filter((point) => isUsRegularSessionPoint(point.time));
  const usablePoints = regularPoints.length > 0 ? regularPoints : points;
  const firstPoint = usablePoints[0] ?? null;
  const priceValues = usablePoints
    .flatMap((point) => [point.high ?? point.price, point.low ?? point.price])
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value);
    });
  const volumeValues = usablePoints
    .map((point) => point.volume)
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value) && value > 0;
    });

  return {
    open: firstPoint?.open ?? firstPoint?.price ?? null,
    high: priceValues.length > 0 ? Math.max(...priceValues) : null,
    low: priceValues.length > 0 ? Math.min(...priceValues) : null,
    volume:
      volumeValues.length > 0
        ? volumeValues.reduce((total, value) => total + value, 0)
        : null,
  };
}

function formatFactValue(fact: USSecCompanyFactRead) {
  if (fact.value_numeric !== null && fact.value_numeric !== undefined) {
    return formatNumber(fact.value_numeric, 0);
  }

  return fact.value_text ?? "-";
}

function formatFundamentalValue(metric: USSecFundamentalMetricRead | null | undefined) {
  if (!metric) return "-";

  const value = metric.value_numeric;
  if (value === null || value === undefined || Number.isNaN(value)) {
    return metric.value_text ?? "-";
  }

  const unit = metric.unit.toLowerCase();
  if (unit.includes("usd/shares")) return `$${formatNumber(value, 2)}`;
  if (unit === "usd") return formatCompactCurrency(value);
  if (unit.includes("shares")) return formatVolume(value);

  return formatNumber(value, 2);
}

function formatFundamentalPeriod(metric: USSecFundamentalMetricRead | null | undefined) {
  if (!metric) return "-";

  const fiscal = [metric.fiscal_year, metric.fiscal_period].filter(Boolean).join(" ");
  const periodEnd = formatDate(metric.period_end_date);
  if (fiscal && periodEnd !== "-") return `${fiscal} · ${periodEnd}`;
  if (fiscal) return fiscal;
  return periodEnd;
}

function messageClass(message: Message) {
  if (!message) return "";

  return message.type === "success"
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : "border-red-200 bg-red-50 text-red-700";
}

function daysSince(value: string | null | undefined) {
  if (!value || value === "-") return null;

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;

  const today = new Date();
  const todayDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const parsedDate = new Date(
    parsed.getFullYear(),
    parsed.getMonth(),
    parsed.getDate()
  );

  return Math.floor((todayDate.getTime() - parsedDate.getTime()) / 86_400_000);
}

function coverageStatus(
  hasData: boolean,
  loadState: LoadState,
  latestDateValue?: string | null,
  staleAfterDays?: number
): CoverageStatus {
  if (loadState === "loading") return "loading";
  if (!hasData) return "missing";

  const age = daysSince(latestDateValue);
  if (
    staleAfterDays !== undefined &&
    age !== null &&
    age > staleAfterDays
  ) {
    return "stale";
  }

  return "ready";
}

function coverageClass(status: CoverageStatus) {
  const classes: Record<CoverageStatus, string> = {
    ready: "border-emerald-200 bg-emerald-50 text-emerald-700",
    missing: "border-slate-200 bg-slate-50 text-slate-500",
    loading: "border-sky-200 bg-sky-50 text-sky-700",
    stale: "border-amber-200 bg-amber-50 text-amber-700",
  };

  return classes[status];
}

function coverageLabel(status: CoverageStatus) {
  const labels: Record<CoverageStatus, string> = {
    ready: "Ready",
    missing: "Missing",
    loading: "Loading",
    stale: "Stale",
  };

  return labels[status];
}

function DataCoverageChip({
  label,
  status,
  detail,
}: {
  label: string;
  status: CoverageStatus;
  detail: string;
}) {
  return (
    <div className={`border px-3 py-2 ${coverageClass(status)}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-wide">{label}</span>
        <span className="text-[11px] font-black">{coverageLabel(status)}</span>
      </div>
      <div className="mt-1 truncate text-[11px] font-medium opacity-80">{detail}</div>
    </div>
  );
}

function metricBarWidth(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "0%";
  return `${Math.max(0, Math.min(100, Math.abs(value)))}%`;
}

function metricBarClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "bg-slate-300";
  if (value > 0) return "bg-red-500";
  if (value < 0) return "bg-emerald-500";
  return "bg-slate-300";
}

function safeDivide(
  numerator: number | null | undefined,
  denominator: number | null | undefined
) {
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

function EmptyDataState({ message }: { message: string }) {
  return (
    <div className="border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
      {message}
    </div>
  );
}

function USDataTabIcon({ type }: { type: USDataPanelTab }) {
  if (type === "ownership") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M10 2c3.3 0 6 1 6 2.3S13.3 6.6 10 6.6 4 5.6 4 4.3 6.7 2 10 2Zm-6 4.2c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3V6.2Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-2.1Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v1.5c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-1.5Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "insider") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M10 2a4 4 0 0 1 2.8 6.8A7 7 0 0 1 17 15.2V18H3v-2.8a7 7 0 0 1 4.2-6.4A4 4 0 0 1 10 2Zm0 2a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm0 6c-2.8 0-5 2.2-5 5v1h10v-1c0-2.8-2.2-5-5-5Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "short") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M10 17 3 10l1.4-1.4L9 13.2V3h2v10.2l4.6-4.6L17 10l-7 7Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
      <path
        d="M5 2h7l3 3v13H5V2Zm2 2v12h6V6h-3V4H7Zm1 5h4v1.5H8V9Zm0 3h4v1.5H8V12Z"
        fill="currentColor"
      />
    </svg>
  );
}

function USDataTabButton({
  tab,
  active,
  onClick,
}: {
  tab: { key: USDataPanelTab; label: string };
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
      <USDataTabIcon type={tab.key} />
      <span>{tab.label}</span>
    </button>
  );
}

function MetricCell({
  label,
  value,
  tone = "text-slate-950",
}: {
  label: string;
  value: ReactNode;
  tone?: string;
}) {
  return (
    <div className="bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-1 break-words text-sm font-bold ${tone}`}>{value}</div>
    </div>
  );
}

function FundamentalMetricCell({
  label,
  metric,
}: {
  label: string;
  metric: USSecFundamentalMetricRead | null | undefined;
}) {
  return (
    <div className="bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm font-bold text-slate-950">
        {formatFundamentalValue(metric)}
      </div>
      <div className="mt-1 truncate text-[11px] font-semibold text-slate-400">
        {formatFundamentalPeriod(metric)}
      </div>
    </div>
  );
}

export default function USStockDetailPanel({
  selectedSymbol,
  selectedSecurityName,
  watchlistRankingPanel,
  onCompanyProfileChange,
}: Props) {
  const [timeframe, setTimeframe] = useState<USChartTimeframe>("daily");
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [activeDataTab, setActiveDataTab] = useState<USDataPanelTab>("ownership");
  const [selectedStock, setSelectedStock] = useState<USStockMasterRead | null>(null);
  const [chart, setChart] = useState<USOhlcChartRead | null>(null);
  const [companyProfile, setCompanyProfile] = useState<USCompanyProfileRead | null>(null);
  const [corporateActions, setCorporateActions] = useState<USCorporateActionRead[]>([]);
  const [shortVolumeRows, setShortVolumeRows] = useState<USShortVolumeDailyRead[]>([]);
  const [todayTrend, setTodayTrend] = useState<IntradayTrendPoint[]>([]);
  const [todayPreviousClose, setTodayPreviousClose] = useState<number | null>(null);
  const [todaySource, setTodaySource] = useState("unavailable");
  const [todayUpdatedAt, setTodayUpdatedAt] = useState<string | null>(null);
  const [intradayIndicators, setIntradayIndicators] =
    useState<IntradayIndicatorSettings>(defaultIntradayIndicators);
  const [factRows, setFactRows] = useState<USSecCompanyFactRead[]>([]);
  const [fundamentalSummary, setFundamentalSummary] =
    useState<USSecFundamentalSummaryRead | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [factLoadState, setFactLoadState] = useState<LoadState>("idle");
  const [refreshingDaily, setRefreshingDaily] = useState(false);
  const [refreshingFacts, setRefreshingFacts] = useState(false);
  const [refreshingProfile, setRefreshingProfile] = useState(false);
  const [refreshingActions, setRefreshingActions] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const requestSeq = useRef(0);
  const finalIntradayRefreshDate = useRef<string | null>(null);

  const chartData = useMemo(() => {
    return chart?.points.map(toChartPoint) ?? [];
  }, [chart]);
  const latestToday = todayTrend[todayTrend.length - 1] ?? null;
  const todayStats = useMemo(() => summarizeUsIntradayPoints(todayTrend), [todayTrend]);
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const previousPoint = chartData[chartData.length - 2] ?? null;
  const displayDate =
    timeframe === "today" ? latestToday?.time ?? latestPoint?.time ?? null : latestPoint?.time ?? null;
  const latestClose =
    timeframe === "today" ? latestToday?.price ?? latestPoint?.close ?? null : latestPoint?.close ?? null;
  const latestVolume =
    timeframe === "today" ? todayStats.volume ?? latestPoint?.volume ?? null : latestPoint?.volume ?? null;
  const previousClose =
    timeframe === "today" ? todayPreviousClose ?? previousPoint?.close ?? null : previousPoint?.close ?? null;
  const displayedPointCount = timeframe === "today" ? todayTrend.length : chart?.point_count ?? 0;
  const change =
    latestClose !== null && previousClose !== null
      ? latestClose - previousClose
      : null;
  const changePct =
    change !== null && previousClose !== null && previousClose !== 0
      ? (change / previousClose) * 100
      : null;
  const closeValues = chartData.map((point) => point.close);
  const volumeValues = chartData.map((point) => point.volume);
  const ma5 = averageLast(closeValues, 5);
  const ma20 = averageLast(closeValues, 20);
  const ma60 = averageLast(closeValues, 60);
  const volumeMa20 = averageLast(volumeValues, 20);
  const priceVsMa20 =
    latestClose !== null && ma20 !== null && ma20 !== 0
      ? ((latestClose - ma20) / ma20) * 100
      : null;
  const volumeVsMa20 =
    latestVolume !== null && volumeMa20 !== null && volumeMa20 !== 0
      ? ((latestVolume - volumeMa20) / volumeMa20) * 100
      : null;
  const technicalTitle =
    latestClose === null || ma20 === null
      ? "資料不足"
      : latestClose > ma20 && ma5 !== null && ma5 >= ma20
        ? "多方排列"
        : latestClose < ma20
          ? "弱於 MA20"
          : "均線整理";
  const latestShortVolume = shortVolumeRows[0] ?? null;
  const latestFactFiledDate = latestDate(factRows.map((fact) => fact.filed_date));
  const latestActionDate = latestDate(corporateActions.map((action) => action.event_date));
  const fundamentalMetrics = useMemo(() => {
    return fundamentalSummary?.metrics ?? [];
  }, [fundamentalSummary]);
  const fundamentalMetricMap = useMemo(() => {
    return new Map(fundamentalMetrics.map((metric) => [metric.metric, metric]));
  }, [fundamentalMetrics]);
  const revenueMetric = fundamentalMetricMap.get("revenue") ?? null;
  const grossProfitMetric = fundamentalMetricMap.get("gross_profit") ?? null;
  const netIncomeMetric = fundamentalMetricMap.get("net_income") ?? null;
  const debtTotalMetric = fundamentalMetricMap.get("debt_total") ?? null;
  const equityMetric = fundamentalMetricMap.get("equity") ?? null;
  const epsDilutedMetric = fundamentalMetricMap.get("eps_diluted") ?? null;
  const sharesOutstandingMetric = fundamentalMetricMap.get("shares_outstanding") ?? null;
  const sharesOutstanding = sharesOutstandingMetric?.value_numeric ?? null;
  const estimatedMarketCap =
    latestClose !== null && sharesOutstanding !== null ? latestClose * sharesOutstanding : null;
  const grossMargin = safeDivide(grossProfitMetric?.value_numeric, revenueMetric?.value_numeric);
  const netMargin = safeDivide(netIncomeMetric?.value_numeric, revenueMetric?.value_numeric);
  const debtToEquity = safeDivide(debtTotalMetric?.value_numeric, equityMetric?.value_numeric);
  const latestFundamentalFiledDate = latestDate(
    fundamentalMetrics.map((metric) => metric.filed_date)
  );
  const latestFundamentalPeriodEnd = latestDate(
    fundamentalMetrics.map((metric) => metric.period_end_date)
  );
  const activeDataTabMeta =
    usDataPanelTabs.find((tab) => tab.key === activeDataTab) ?? usDataPanelTabs[0];
  const selectedIndexConfig = getUsMarketIndexConfig(selectedSymbol);
  const selectedDisplaySymbol = selectedIndexConfig?.displaySymbol ?? selectedSymbol ?? "-";
  const selectedDisplayName =
    selectedIndexConfig?.name ?? stockName(selectedStock, selectedSecurityName);
  const selectedSubtitle = selectedIndexConfig
    ? `${selectedIndexConfig.exchange} · Index · ${formatDate(displayDate)}`
    : selectedStock
      ? `${selectedStock.exchange ?? "-"} · ${assetTypeLabel(selectedStock)} · ${formatDate(displayDate)}`
      : selectedSymbol
        ? "讀取美股主檔中"
        : "請從左側自選或上方搜尋選擇股票";
  const headerMetrics =
    timeframe === "today"
      ? [
          { label: "日期", value: formatDate(displayDate) },
          { label: "今日成交量", value: formatVolume(todayStats.volume) },
          {
            label: "最高 / 最低",
            value: `${formatNumber(todayStats.high)} / ${formatNumber(todayStats.low)}`,
          },
          {
            label: "更新 / 筆數",
            value: `${todayUpdatedAt ?? "-"} / ${displayedPointCount}`,
          },
        ]
      : [
          { label: "日期", value: formatDate(displayDate) },
          { label: "成交量", value: formatVolume(latestVolume) },
          {
            label: "MA5 / 20 / 60",
            value: `${formatNumber(ma5)} / ${formatNumber(ma20)} / ${formatNumber(ma60)}`,
          },
          {
            label: "資料筆數",
            value: loadState === "loading" ? "Loading" : String(displayedPointCount),
          },
        ];

  const dataCoverageItems: Array<{
    label: string;
    status: CoverageStatus;
    detail: string;
  }> = selectedIndexConfig
    ? [
        {
          label: "OHLC",
          status: coverageStatus(chartData.length > 0, loadState, latestPoint?.time, 10),
          detail:
            chartData.length > 0
              ? `${chartData.length} bars / ${formatDate(latestPoint?.time)}`
              : "No index bars",
        },
        {
          label: "Intraday",
          status:
            timeframe === "today"
              ? coverageStatus(todayTrend.length > 0, loadState, latestToday?.time, 2)
              : "ready",
          detail:
            timeframe === "today"
              ? `${todayTrend.length} points / ${todayUpdatedAt ?? "-"}`
              : "Available on Today tab",
        },
        {
          label: "Source",
          status: "ready",
          detail: "Yahoo chart index",
        },
      ]
    : [
        {
          label: "Price",
          status: coverageStatus(chartData.length > 0, loadState, latestPoint?.time, 10),
          detail:
            chartData.length > 0
              ? `${chartData.length} bars / ${formatDate(latestPoint?.time)}`
              : "No OHLC rows",
        },
        {
          label: "Profile",
          status: coverageStatus(Boolean(companyProfile), loadState, companyProfile?.fetched_at, 45),
          detail: companyProfile
            ? `${companyProfile.provider} / ${formatDate(companyProfile.fetched_at)}`
            : "Alpha Vantage overview",
        },
        {
          label: "SEC",
          status: coverageStatus(
            factRows.length > 0 || fundamentalMetrics.length > 0,
            factLoadState,
            latestFundamentalFiledDate !== "-" ? latestFundamentalFiledDate : latestFactFiledDate,
            210
          ),
          detail:
            factRows.length > 0 || fundamentalMetrics.length > 0
              ? `${fundamentalMetrics.length} metrics / ${
                  latestFundamentalFiledDate !== "-" ? latestFundamentalFiledDate : latestFactFiledDate
                }`
              : "No SEC facts",
        },
        {
          label: "Actions",
          status: coverageStatus(corporateActions.length > 0, loadState),
          detail:
            corporateActions.length > 0
              ? `${corporateActions.length} events / ${latestActionDate}`
              : "No dividend/split rows",
        },
        {
          label: "Short",
          status: coverageStatus(
            shortVolumeRows.length > 0,
            loadState,
            latestShortVolume?.trade_date,
            10
          ),
          detail: latestShortVolume
            ? `${formatRatioAsPct(latestShortVolume.short_ratio)} / ${formatDate(latestShortVolume.trade_date)}`
            : "No FINRA rows",
        },
      ];
  const readyCoverageCount = dataCoverageItems.filter(
    (item) => item.status === "ready"
  ).length;

  const loadSymbolData = useCallback(
    async (symbol: string, nextTimeframe: USChartTimeframe) => {
      const requestId = requestSeq.current + 1;
      requestSeq.current = requestId;
      setLoadState("loading");
      setFactLoadState("loading");
      setMessage(null);

      try {
        const indexConfig = getUsMarketIndexConfig(symbol);

        if (indexConfig) {
          if (nextTimeframe === "today") {
            const [todayData, dailyChartData] = await Promise.all([
              fetchJson<IntradayTrendResponse>(
                `/api/us-market/intraday/${encodeURIComponent(symbol)}`
              ),
              fetchJson<USOhlcChartRead>(
                `/api/us-market/ohlc/${encodeURIComponent(symbol)}`,
                {
                  timeframe: "daily",
                  bars: 90,
                  ensure_history: true,
                  outputsize: "compact",
                  provider: "yahoo_chart",
                }
              ),
            ]);

            if (requestSeq.current !== requestId) return;

            const latestIntradayPoint = todayData.points[todayData.points.length - 1] ?? null;
            const marketState = getUsMarketRefreshState();

            if (marketState.isAfterClose) {
              finalIntradayRefreshDate.current = marketState.dateKey;
            }

            setSelectedStock(null);
            setChart(dailyChartData);
            setTodayTrend(todayData.points);
            setTodayPreviousClose(todayData.previous_close);
            setTodaySource(todayData.source);
            setTodayUpdatedAt(
              latestIntradayPoint ? formatDateTime(latestIntradayPoint.time) : null
            );
            setFactRows([]);
            setFundamentalSummary(null);
            setCompanyProfile(null);
            onCompanyProfileChange?.(null);
            setCorporateActions([]);
            setShortVolumeRows([]);
            setLoadState("success");
            setFactLoadState("success");
            return;
          }

          const chartDataResponse = await fetchJson<USOhlcChartRead>(
            `/api/us-market/ohlc/${encodeURIComponent(symbol)}`,
            {
              timeframe: nextTimeframe,
              bars: barsByTimeframe[nextTimeframe],
              ensure_history: true,
              outputsize: "full",
              provider: "yahoo_chart",
            }
          );

          if (requestSeq.current !== requestId) return;

          setSelectedStock(null);
          setChart(chartDataResponse);
          setTodayTrend([]);
          setTodayPreviousClose(null);
          setTodaySource("unavailable");
          setTodayUpdatedAt(null);
          setFactRows([]);
          setFundamentalSummary(null);
          setCompanyProfile(null);
          onCompanyProfileChange?.(null);
          setCorporateActions([]);
          setShortVolumeRows([]);
          setLoadState("success");
          setFactLoadState("success");
          return;
        }

        if (nextTimeframe === "today") {
          const [
            stockData,
            todayData,
            dailyChartData,
            factData,
            fundamentalData,
            profileData,
            actionData,
            shortVolumeData,
          ] = await Promise.all([
            fetchJson<USStockMasterRead>(
              `/api/us-market/stocks/${encodeURIComponent(symbol)}`
            ),
            fetchJson<IntradayTrendResponse>(
              `/api/us-market/intraday/${encodeURIComponent(symbol)}`
            ),
            fetchJson<USOhlcChartRead>(
              `/api/us-market/ohlc/${encodeURIComponent(symbol)}`,
              {
                timeframe: "daily",
                bars: barsByTimeframe.daily,
                ensure_history: true,
                outputsize: "compact",
              }
            ),
            fetchJson<USSecCompanyFactRead[]>(
              `/api/us-market/sec/${encodeURIComponent(symbol)}/facts`,
              {
                limit: 24,
                offset: 0,
              }
            ),
            fetchOptionalJson<USSecFundamentalSummaryRead>(
              `/api/us-market/sec/${encodeURIComponent(symbol)}/fundamentals`
            ),
            fetchOptionalJson<USCompanyProfileRead>(
              `/api/us-market/profiles/${encodeURIComponent(symbol)}`
            ),
            fetchJson<USCorporateActionRead[]>(
              `/api/us-market/corporate-actions/${encodeURIComponent(symbol)}`,
              {
                limit: 8,
                offset: 0,
              }
            ),
            fetchJson<USShortVolumeDailyRead[]>(
              `/api/us-market/short-volume/${encodeURIComponent(symbol)}/history`,
              {
                limit: 8,
                offset: 0,
              }
            ),
          ]);

          if (requestSeq.current !== requestId) return;

          const latestIntradayPoint = todayData.points[todayData.points.length - 1] ?? null;
          const marketState = getUsMarketRefreshState();

          if (marketState.isAfterClose) {
            finalIntradayRefreshDate.current = marketState.dateKey;
          }

          setSelectedStock(stockData);
          setChart(dailyChartData);
          setTodayTrend(todayData.points);
          setTodayPreviousClose(todayData.previous_close);
          setTodaySource(todayData.source);
          setTodayUpdatedAt(
            latestIntradayPoint ? formatDateTime(latestIntradayPoint.time) : null
          );
          setFactRows(factData);
          setFundamentalSummary(fundamentalData);
          setCompanyProfile(profileData);
          onCompanyProfileChange?.(profileData);
          setCorporateActions(actionData);
          setShortVolumeRows(shortVolumeData);
          setLoadState("success");
          setFactLoadState("success");
          return;
        }

        const [
          stockData,
          chartDataResponse,
          factData,
          fundamentalData,
          profileData,
          actionData,
          shortVolumeData,
        ] = await Promise.all([
          fetchJson<USStockMasterRead>(
            `/api/us-market/stocks/${encodeURIComponent(symbol)}`
          ),
          fetchJson<USOhlcChartRead>(
            `/api/us-market/ohlc/${encodeURIComponent(symbol)}`,
            {
              timeframe: nextTimeframe,
              bars: barsByTimeframe[nextTimeframe],
              ensure_history: true,
              outputsize: nextTimeframe === "monthly" ? "full" : "compact",
            }
          ),
          fetchJson<USSecCompanyFactRead[]>(
            `/api/us-market/sec/${encodeURIComponent(symbol)}/facts`,
            {
              limit: 24,
              offset: 0,
            }
          ),
          fetchOptionalJson<USSecFundamentalSummaryRead>(
            `/api/us-market/sec/${encodeURIComponent(symbol)}/fundamentals`
          ),
          fetchOptionalJson<USCompanyProfileRead>(
            `/api/us-market/profiles/${encodeURIComponent(symbol)}`
          ),
          fetchJson<USCorporateActionRead[]>(
            `/api/us-market/corporate-actions/${encodeURIComponent(symbol)}`,
            {
              limit: 8,
              offset: 0,
            }
          ),
          fetchJson<USShortVolumeDailyRead[]>(
            `/api/us-market/short-volume/${encodeURIComponent(symbol)}/history`,
            {
              limit: 8,
              offset: 0,
            }
          ),
        ]);

        if (requestSeq.current !== requestId) return;

        setSelectedStock(stockData);
        setChart(chartDataResponse);
        setTodayTrend([]);
        setTodayPreviousClose(null);
        setTodaySource("unavailable");
        setTodayUpdatedAt(null);
        setFactRows(factData);
        setFundamentalSummary(fundamentalData);
        setCompanyProfile(profileData);
        onCompanyProfileChange?.(profileData);
        setCorporateActions(actionData);
        setShortVolumeRows(shortVolumeData);
        setLoadState("success");
        setFactLoadState("success");
      } catch (error) {
        if (requestSeq.current !== requestId) return;

        setSelectedStock(null);
        setChart(null);
        setTodayTrend([]);
        setTodayPreviousClose(null);
        setTodaySource("unavailable");
        setTodayUpdatedAt(null);
        setFactRows([]);
        setFundamentalSummary(null);
        setCompanyProfile(null);
        onCompanyProfileChange?.(null);
        setCorporateActions([]);
        setShortVolumeRows([]);
        setLoadState("error");
        setFactLoadState("error");
        setMessage({
          type: "error",
          text: error instanceof Error ? error.message : "讀取美股資料失敗",
        });
      }
    },
    [onCompanyProfileChange]
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!selectedSymbol) {
        setSelectedStock(null);
        setChart(null);
        setCompanyProfile(null);
        onCompanyProfileChange?.(null);
        setCorporateActions([]);
        setShortVolumeRows([]);
        setTodayTrend([]);
        setTodayPreviousClose(null);
        setTodaySource("unavailable");
        setTodayUpdatedAt(null);
        setFactRows([]);
        setFundamentalSummary(null);
        setLoadState("idle");
        setFactLoadState("idle");
        return;
      }

      void loadSymbolData(selectedSymbol, timeframe);
    }, 0);

    return () => window.clearTimeout(timer);
  }, [loadSymbolData, onCompanyProfileChange, selectedSymbol, timeframe]);

  useEffect(() => {
    if (!selectedSymbol || timeframe !== "today") return;

    let cancelled = false;
    let intradayTimer: number | undefined;
    let intradayRequestInFlight = false;
    const symbol = selectedSymbol;

    function clearIntradayTimer() {
      if (intradayTimer !== undefined) {
        window.clearTimeout(intradayTimer);
        intradayTimer = undefined;
      }
    }

    async function refreshTodayTrend() {
      if (intradayRequestInFlight) return;
      intradayRequestInFlight = true;

      try {
        const today = await fetchJson<IntradayTrendResponse>(
          `/api/us-market/intraday/${encodeURIComponent(symbol)}`
        );

        if (cancelled) return;

        const latestIntradayPoint = today.points[today.points.length - 1] ?? null;

        setTodayTrend(today.points);
        setTodayPreviousClose(today.previous_close);
        setTodaySource(today.source);
        setTodayUpdatedAt(
          latestIntradayPoint ? formatDateTime(latestIntradayPoint.time) : null
        );
        setLoadState("success");
      } catch (error) {
        if (cancelled) return;

        setLoadState("error");
        setMessage({
          type: "error",
          text: error instanceof Error ? error.message : "更新美股盤中資料失敗",
        });
      } finally {
        intradayRequestInFlight = false;
      }
    }

    function scheduleTodayRefresh() {
      if (cancelled) return;

      const marketState = getUsMarketRefreshState();

      if (marketState.isPollingWindow) {
        intradayTimer = window.setTimeout(() => {
          void refreshTodayTrend().finally(scheduleTodayRefresh);
        }, US_INTRADAY_REFRESH_MS);
        return;
      }

      if (
        marketState.isAfterClose &&
        finalIntradayRefreshDate.current !== marketState.dateKey
      ) {
        finalIntradayRefreshDate.current = marketState.dateKey;
        intradayTimer = window.setTimeout(() => {
          void refreshTodayTrend().finally(scheduleTodayRefresh);
        }, 0);
        return;
      }

      intradayTimer = window.setTimeout(
        scheduleTodayRefresh,
        Math.min(marketState.msUntilNextPollingStart, 60_000)
      );
    }

    scheduleTodayRefresh();

    return () => {
      cancelled = true;
      clearIntradayTimer();
    };
  }, [selectedSymbol, timeframe]);

  function toggleIntradayIndicator(key: IntradayIndicatorKey) {
    setIntradayIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  async function refreshDailyRows() {
    if (!selectedSymbol) return;

    const indexConfig = getUsMarketIndexConfig(selectedSymbol);
    const outputsize = indexConfig ? "full" : "compact";

    setRefreshingDaily(true);
    setMessage(null);

    try {
      const result = await requestJson<USDailyPriceRefreshResultRead>(
        `/api/us-market/daily/${encodeURIComponent(selectedSymbol)}/refresh`,
        { method: "POST" },
        {
          outputsize,
          adjusted: false,
          provider: indexConfig ? "yahoo_chart" : "auto",
        }
      );

      setMessage({
        type: "success",
        text: `已更新 ${result.symbol} 日線 ${result.fetched_count} 筆，新增 ${result.inserted_count}，更新 ${result.updated_count}`,
      });
      await loadSymbolData(selectedSymbol, timeframe);
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "更新美股日線失敗",
      });
    } finally {
      setRefreshingDaily(false);
    }
  }

  async function refreshFacts() {
    if (!selectedSymbol) return;

    setRefreshingFacts(true);
    setMessage(null);

    try {
      const result = await requestJson<USSecFactRefreshResultRead>(
        `/api/us-market/sec/${encodeURIComponent(selectedSymbol)}/refresh-facts`,
        { method: "POST" }
      );

      setMessage({
        type: "success",
        text: `已更新 ${result.symbol} SEC facts ${result.fetched_count} 筆`,
      });
      await loadSymbolData(selectedSymbol, timeframe);
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "更新 SEC facts 失敗",
      });
    } finally {
      setRefreshingFacts(false);
    }
  }

  async function refreshProfile() {
    if (!selectedSymbol) return;

    setRefreshingProfile(true);
    setMessage(null);

    try {
      const result = await requestJson<USResourceRefreshResultRead>(
        `/api/us-market/profiles/${encodeURIComponent(selectedSymbol)}/refresh`,
        { method: "POST" }
      );

      setMessage({
        type: "success",
        text: `已更新 ${result.symbol ?? selectedSymbol} Profile ${result.fetched_count} 筆`,
      });
      await loadSymbolData(selectedSymbol, timeframe);
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "更新 Profile 失敗",
      });
    } finally {
      setRefreshingProfile(false);
    }
  }

  async function refreshActions() {
    if (!selectedSymbol) return;

    setRefreshingActions(true);
    setMessage(null);

    try {
      const result = await requestJson<USResourceRefreshResultRead>(
        `/api/us-market/corporate-actions/${encodeURIComponent(selectedSymbol)}/refresh`,
        { method: "POST" }
      );

      setMessage({
        type: "success",
        text: `已更新 ${result.symbol ?? selectedSymbol} Actions ${result.fetched_count} 筆`,
      });
      await loadSymbolData(selectedSymbol, timeframe);
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "更新 Actions 失敗",
      });
    } finally {
      setRefreshingActions(false);
    }
  }

  function renderDataPanelAction() {
    if (activeDataTab === "ownership") {
      return (
        <button
          type="button"
          onClick={() => void refreshProfile()}
          className="h-8 bg-slate-900 px-3 text-xs font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300"
          disabled={!selectedSymbol || refreshingProfile}
        >
          {refreshingProfile ? "Updating" : "Profile"}
        </button>
      );
    }

    if (activeDataTab === "filings") {
      return (
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={() => void refreshFacts()}
            className="h-8 bg-slate-900 px-3 text-xs font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300"
            disabled={!selectedSymbol || refreshingFacts}
          >
            {refreshingFacts ? "Updating" : "SEC Facts"}
          </button>
          <button
            type="button"
            onClick={() => void refreshActions()}
            className="h-8 border border-slate-900 bg-white px-3 text-xs font-semibold text-slate-900 hover:border-red-700 hover:text-red-700 disabled:border-slate-200 disabled:text-slate-400"
            disabled={!selectedSymbol || refreshingActions}
          >
            {refreshingActions ? "Updating" : "Actions"}
          </button>
        </div>
      );
    }

    if (activeDataTab === "short") {
      return (
        <div className="border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-500">
          FINRA
        </div>
      );
    }

    return (
      <div className="border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-500">
        Form 4
      </div>
    );
  }

  function renderOwnershipTab() {
    return (
      <div className="space-y-4">
        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-2 gap-px bg-slate-200 text-sm">
            <MetricCell label="Exchange" value={selectedStock?.exchange ?? "-"} />
            <MetricCell label="Type" value={assetTypeLabel(selectedStock)} />
            <MetricCell label="CIK" value={selectedStock?.cik ?? "-"} />
            <MetricCell
              label={
                companyProfile?.market_cap !== null && companyProfile?.market_cap !== undefined
                  ? "Market Cap"
                  : "Mkt Cap Est."
              }
              value={formatCompactCurrency(companyProfile?.market_cap ?? estimatedMarketCap)}
            />
            <MetricCell label="Shares" value={formatFundamentalValue(sharesOutstandingMetric)} />
            <MetricCell label="P/E" value={formatNumber(companyProfile?.pe_ratio)} />
            <MetricCell
              label="EPS"
              value={
                companyProfile?.eps !== null && companyProfile?.eps !== undefined
                  ? formatNumber(companyProfile.eps)
                  : formatFundamentalValue(epsDilutedMetric)
              }
            />
            <MetricCell
              label={
                companyProfile?.revenue_ttm !== null && companyProfile?.revenue_ttm !== undefined
                  ? "Revenue TTM"
                  : "SEC Revenue"
              }
              value={
                companyProfile?.revenue_ttm !== null && companyProfile?.revenue_ttm !== undefined
                  ? formatCompactCurrency(companyProfile.revenue_ttm)
                  : formatFundamentalValue(revenueMetric)
              }
            />
            <MetricCell
              label={
                companyProfile?.profit_margin !== null &&
                companyProfile?.profit_margin !== undefined
                  ? "Profit Margin"
                  : "Net Margin"
              }
              value={
                companyProfile?.profit_margin !== null &&
                companyProfile?.profit_margin !== undefined
                  ? formatRatioAsPct(companyProfile.profit_margin)
                  : formatRatioAsPct(netMargin)
              }
            />
            <MetricCell label="SEC Period" value={latestFundamentalPeriodEnd} />
            <MetricCell label="Latest Filed" value={latestFundamentalFiledDate} />
          </div>
        </div>

        <div className="border border-slate-200 px-4 py-3 text-xs leading-5 text-slate-500">
          {companyProfile ? (
            <>
              <span className="font-semibold text-slate-700">
                {companyProfile.sector ?? "-"}
              </span>
              {" / "}
              {companyProfile.industry ?? "-"}
              {" · Latest Quarter "}
              {formatDate(companyProfile.latest_quarter)}
              {" · "}
              {companyProfile.provider}
            </>
          ) : (
            fundamentalSummary ? (
              <>
                <span className="font-semibold text-slate-700">
                  {fundamentalSummary.entity_name ?? selectedStock?.sec_company_name ?? "-"}
                </span>
                {" · SEC fundamentals "}
                {fundamentalSummary.metric_count}
                {" metrics · "}
                {latestFundamentalFiledDate}
              </>
            ) : (
              "尚無 Company Profile；若已更新 SEC facts，會改用 SEC fundamentals 補基本欄位。"
            )
          )}
        </div>

        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-[1fr_96px_96px] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
            <span>13F Holder</span>
            <span className="text-right">Shares</span>
            <span className="text-right">QoQ</span>
          </div>
          <div className="border-t border-slate-200 p-4">
            <EmptyDataState message="尚未接入 SEC 13F 機構持倉資料" />
          </div>
        </div>
      </div>
    );
  }

  function renderInsiderTab() {
    return (
      <div className="space-y-4">
        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-3 gap-px bg-slate-200 text-center text-sm">
            <MetricCell label="Latest Filing" value="-" />
            <MetricCell label="Transactions" value="-" />
            <MetricCell label="Net Shares" value="-" />
          </div>
        </div>

        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-[88px_1fr_88px_92px] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
            <span>Date</span>
            <span>Insider</span>
            <span className="text-right">Type</span>
            <span className="text-right">Shares</span>
          </div>
          <div className="border-t border-slate-200 p-4">
            <EmptyDataState message="尚未接入 SEC Form 4 內部人交易資料" />
          </div>
        </div>
      </div>
    );
  }

  function renderShortTab() {
    return (
      <div className="space-y-4">
        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-2 gap-px bg-slate-200 text-sm md:grid-cols-4">
            <MetricCell label="Date" value={formatDate(latestShortVolume?.trade_date)} />
            <MetricCell label="Short Ratio" value={formatRatioAsPct(latestShortVolume?.short_ratio)} />
            <MetricCell label="Short Volume" value={formatVolume(latestShortVolume?.short_volume)} />
            <MetricCell label="Total Volume" value={formatVolume(latestShortVolume?.total_volume)} />
          </div>
        </div>

        <div className="border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800">
          目前為 FINRA daily short sale volume，非 short interest 部位資料。
        </div>

        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-[88px_1fr_92px] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
            <span>Date</span>
            <span>Short / Total</span>
            <span className="text-right">Ratio</span>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {shortVolumeRows.length > 0 ? (
              shortVolumeRows.slice(0, 8).map((row) => (
                <div
                  key={`${row.trade_date}-${row.market_center}-${row.id}`}
                  className="grid grid-cols-[88px_1fr_92px] border-t border-slate-200 px-4 py-2 text-sm"
                >
                  <span className="text-slate-500">{formatDate(row.trade_date)}</span>
                  <span className="min-w-0">
                    <span className="block font-semibold text-slate-800">
                      {formatVolume(row.short_volume)} / {formatVolume(row.total_volume)}
                    </span>
                    <span className="block truncate text-xs text-slate-500">
                      {row.market_center || row.provider}
                    </span>
                  </span>
                  <span className="text-right font-bold text-slate-950">
                    {formatRatioAsPct(row.short_ratio)}
                  </span>
                </div>
              ))
            ) : (
              <div className="border-t border-slate-200 px-5 py-8 text-center text-sm text-slate-500">
                尚無 short volume 資料
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderFilingsTab() {
    return (
      <div className="space-y-4">
        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-2 gap-px bg-slate-200 text-sm md:grid-cols-3">
            <MetricCell label="CIK" value={selectedStock?.cik ?? "-"} />
            <MetricCell label="SEC Facts" value={factRows.length} />
            <MetricCell label="Fundamentals" value={fundamentalSummary?.metric_count ?? 0} />
            <MetricCell
              label="Latest Filed"
              value={
                latestFundamentalFiledDate !== "-"
                  ? latestFundamentalFiledDate
                  : latestFactFiledDate
              }
            />
            <MetricCell label="Period End" value={latestFundamentalPeriodEnd} />
            <MetricCell label="Actions" value={corporateActions.length} />
            <MetricCell label="Latest Action" value={latestActionDate} />
          </div>
        </div>

        <div className="overflow-hidden border border-slate-200">
          <div className="border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
            SEC Fundamentals
          </div>
          {fundamentalMetrics.length > 0 ? (
            <>
              <div className="grid grid-cols-2 gap-px bg-slate-200 text-sm md:grid-cols-3">
                <MetricCell label="Gross Margin" value={formatRatioAsPct(grossMargin)} />
                <MetricCell label="Net Margin" value={formatRatioAsPct(netMargin)} />
                <MetricCell label="Debt / Equity" value={formatNumber(debtToEquity, 2)} />
              </div>
              <div className="grid grid-cols-2 gap-px bg-slate-200 text-sm md:grid-cols-3">
                {secFundamentalCards.map((card) => (
                  <FundamentalMetricCell
                    key={card.metric}
                    label={card.label}
                    metric={fundamentalMetricMap.get(card.metric)}
                  />
                ))}
              </div>
            </>
          ) : (
            <div className="p-4">
              <EmptyDataState message="尚無 SEC fundamentals 摘要，可先更新 SEC facts。" />
            </div>
          )}
        </div>

        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-[minmax(120px,1fr)_56px_88px_minmax(86px,0.8fr)] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
            <span>Tag</span>
            <span>FY</span>
            <span>End</span>
            <span className="text-right">Value</span>
          </div>
          <div className="max-h-72 overflow-y-auto">
            {factRows.length > 0 ? (
              factRows.slice(0, 12).map((fact) => (
                <div
                  key={fact.fact_key}
                  className="grid grid-cols-[minmax(120px,1fr)_56px_88px_minmax(86px,0.8fr)] border-t border-slate-200 px-4 py-2 text-sm text-slate-800"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{fact.tag}</span>
                    <span className="block truncate text-xs text-slate-500">{fact.unit}</span>
                  </span>
                  <span>{fact.fiscal_year ?? "-"}</span>
                  <span>{formatDate(fact.period_end_date)}</span>
                  <span className="truncate text-right font-semibold">{formatFactValue(fact)}</span>
                </div>
              ))
            ) : (
              <div className="border-t border-slate-200 px-5 py-8 text-center text-sm text-slate-500">
                {factLoadState === "loading" ? "Loading" : "尚無 SEC facts"}
              </div>
            )}
          </div>
        </div>

        <div className="overflow-hidden border border-slate-200">
          <div className="grid grid-cols-[88px_1fr_88px] bg-slate-50 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-500">
            <span>Date</span>
            <span>Action</span>
            <span className="text-right">Value</span>
          </div>
          <div className="max-h-52 overflow-y-auto">
            {corporateActions.length > 0 ? (
              corporateActions.slice(0, 8).map((action) => (
                <div
                  key={`${action.action_type}-${action.event_date}-${action.id}`}
                  className="grid grid-cols-[88px_1fr_88px] border-t border-slate-200 px-4 py-2 text-sm"
                >
                  <span className="text-slate-500">{formatDate(action.event_date)}</span>
                  <span className="font-semibold text-slate-800">
                    {action.action_type === "dividend" ? "Dividend" : "Split"}
                  </span>
                  <span className="text-right font-bold text-slate-950">
                    {formatActionValue(action)}
                  </span>
                </div>
              ))
            ) : (
              <div className="border-t border-slate-200 px-5 py-8 text-center text-sm text-slate-500">
                尚無股利 / 拆股資料
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderActiveDataTab() {
    if (activeDataTab === "insider") return renderInsiderTab();
    if (activeDataTab === "short") return renderShortTab();
    if (activeDataTab === "filings") return renderFilingsTab();
    return renderOwnershipTab();
  }

  if (!selectedSymbol) {
    return watchlistRankingPanel ? (
      <section className="min-w-0">{watchlistRankingPanel}</section>
    ) : (
      <section className="border border-slate-200 bg-white px-5 py-10 text-sm text-slate-500">
        尚未選擇股票
      </section>
    );
  }

  return (
    <section className="grid w-full grid-cols-1 items-start justify-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]">
      <div className="min-w-0 space-y-4 self-start">
        <section className="border border-slate-200 bg-white">
          <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                {selectedIndexConfig ? "Index" : "Stock"}
              </div>
              <h2 className="mt-1 text-2xl font-bold text-slate-950">
                {selectedDisplaySymbol} {selectedDisplayName}
              </h2>
              <div className="mt-1 text-sm text-slate-500">
                {selectedSubtitle}
              </div>
            </div>

            <div className="text-right">
              <PriceUpdatePulse
                value={latestClose}
                direction={change}
                resetKey={`${selectedSymbol ?? "empty"}:${timeframe}`}
                className="text-3xl font-black text-slate-950"
              >
                {formatNumber(latestClose)}
              </PriceUpdatePulse>
              <div className={`text-sm font-bold ${valueTone(changePct)}`}>
                {formatNumber(change)} / {formatPct(changePct)}
              </div>
              <div className="mt-3 flex flex-wrap justify-end gap-2">
                {timeframeOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setTimeframe(option.value)}
                    className={[
                      "h-8 border px-3 text-sm font-semibold",
                      timeframe === option.value
                        ? "border-red-700 bg-red-700 text-white"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
                    ].join(" ")}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {message ? (
            <div className={`border-t px-5 py-3 text-sm ${messageClass(message)}`}>
              {message.text}
            </div>
          ) : null}

          <div className="grid grid-cols-2 border-t border-slate-200 md:grid-cols-4">
            {headerMetrics.map((item, index) => (
              <div
                key={item.label}
                className={[
                  "px-5 py-3",
                  index % 2 === 1 ? "border-l border-slate-200" : "",
                  index >= 2 ? "border-t border-slate-200 md:border-t-0" : "",
                  index > 0 ? "md:border-l md:border-slate-200" : "",
                ].join(" ")}
              >
                <div className="text-xs text-slate-500">{item.label}</div>
                <div className="mt-1 break-words text-sm font-bold">{item.value}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
            <div>
              <h3 className="text-sm font-bold text-slate-950">K 線 / 技術指標</h3>
              <div className="mt-1 text-xs text-slate-500">
                {timeframeOptions.find((option) => option.value === timeframe)?.label} · {displayedPointCount} 筆資料
              </div>
            </div>
            <div className="flex items-center gap-2">
              {timeframe === "today" ? (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setIndicatorMenuOpen((value) => !value)}
                    className="h-8 border border-slate-900 bg-white px-3 text-xs font-semibold text-slate-900 hover:border-red-700 hover:text-red-700"
                  >
                    指標
                  </button>
                  {indicatorMenuOpen ? (
                    <div className="absolute right-0 z-20 mt-2 w-56 border border-slate-200 bg-white p-3 text-left shadow-lg">
                      <div className="mb-2 text-xs font-bold text-slate-500">顯示項目</div>
                      {intradayIndicatorOptions.map((option) => (
                        <label
                          key={option.key}
                          className="flex cursor-pointer items-start gap-2 px-2 py-2 text-xs hover:bg-slate-50"
                        >
                          <input
                            type="checkbox"
                            checked={intradayIndicators[option.key]}
                            onChange={() => toggleIntradayIndicator(option.key)}
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
              <button
                type="button"
                onClick={() => {
                  if (!selectedSymbol) return;

                  if (timeframe === "today") {
                    void loadSymbolData(selectedSymbol, timeframe);
                    return;
                  }

                  void refreshDailyRows();
                }}
                className="h-8 bg-slate-900 px-3 text-xs font-semibold text-white hover:bg-slate-700 disabled:bg-slate-300"
                disabled={
                  !selectedSymbol ||
                  refreshingDaily ||
                  (timeframe === "today" && loadState === "loading")
                }
              >
                {timeframe === "today"
                  ? loadState === "loading"
                    ? "Loading"
                    : "Reload"
                  : refreshingDaily
                    ? "Updating"
                    : "更新"}
              </button>
            </div>
          </div>

          {timeframe === "today" ? (
            <IntradayTrendChart
              points={todayTrend}
              previousClose={todayPreviousClose}
              label={
                selectedIndexConfig
                  ? `${selectedDisplaySymbol} 今日`
                  : timeframeOptions.find((option) => option.value === timeframe)?.label ?? "今日"
              }
              source={todaySource}
              indicators={intradayIndicators}
              session={usIntradaySession}
              revealKey={`${selectedSymbol ?? "empty"}-${timeframe}-${todayTrend.length}`}
              refreshIntervalMs={US_INTRADAY_REFRESH_MS}
              updatedAt={todayUpdatedAt}
            />
          ) : chartData.length > 0 ? (
            <StockKLineChart
              chartData={chartData}
              label={selectedDisplaySymbol}
              indicators={usChartIndicators}
              indicatorParameters={defaultIndicatorParameters}
              revealKey={`${selectedSymbol ?? "empty"}-${timeframe}-${chartData.length}`}
              volumePanelLabel="Volume"
              volumeTooltipLabel="Volume"
              volumeValueFormatter={formatVolume}
            />
          ) : (
            <div className="flex h-[460px] items-center justify-center border-t border-slate-200 text-sm text-slate-500">
              {loadState === "loading"
                ? "讀取 K 線中"
                : selectedSymbol
                  ? selectedIndexConfig
                    ? "尚無指數 K 線資料，請先按 Reload 或更新。"
                    : "尚無 K 線資料，請先更新日線。"
                  : "尚未選擇股票"}
            </div>
          )}
        </section>

        {watchlistRankingPanel ? (
          <div className="min-w-0">{watchlistRankingPanel}</div>
        ) : null}
      </div>

      <aside className="flex min-w-0 flex-col border border-slate-200 bg-white">
        <section>
          <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                Technical
              </div>
              <h3 className="mt-1 text-xl font-bold text-slate-950">{technicalTitle}</h3>
              <div className="mt-1 text-sm text-slate-500">均線、量能、價格相對位置</div>
            </div>
            <div className={`text-right text-lg font-black ${valueTone(priceVsMa20)}`}>
              <PriceUpdatePulse
                value={priceVsMa20}
                direction={priceVsMa20}
                resetKey={`${selectedSymbol ?? "empty"}:technical-ma20`}
                className="justify-end tabular-nums"
              >
                {formatPct(priceVsMa20)}
              </PriceUpdatePulse>
              <div className="text-xs font-semibold text-slate-500">vs MA20</div>
            </div>
          </div>

          <div className="space-y-3 px-5 py-4 text-sm">
            <div>
              <div className="mb-1 flex justify-between text-xs text-slate-500">
                <span>價格相對 MA20</span>
                <span className={valueTone(priceVsMa20)}>
                  <PriceUpdatePulse
                    value={priceVsMa20}
                    direction={priceVsMa20}
                    resetKey={`${selectedSymbol ?? "empty"}:technical-price`}
                    className="justify-end tabular-nums"
                  >
                    {formatPct(priceVsMa20)}
                  </PriceUpdatePulse>
                </span>
              </div>
              <div className="h-2 bg-slate-100">
                <div
                  className={`omi-technical-bar h-2 ${metricBarClass(priceVsMa20)}`}
                  style={{ width: metricBarWidth(priceVsMa20) }}
                />
              </div>
            </div>
            <div>
              <div className="mb-1 flex justify-between text-xs text-slate-500">
                <span>量能相對 20 日均量</span>
                <span className={valueTone(volumeVsMa20)}>
                  <PriceUpdatePulse
                    value={volumeVsMa20}
                    direction={volumeVsMa20}
                    resetKey={`${selectedSymbol ?? "empty"}:technical-volume`}
                    className="justify-end tabular-nums"
                  >
                    {formatPct(volumeVsMa20)}
                  </PriceUpdatePulse>
                </span>
              </div>
              <div className="h-2 bg-slate-100">
                <div
                  className={`omi-technical-bar h-2 ${metricBarClass(volumeVsMa20)}`}
                  style={{ width: metricBarWidth(volumeVsMa20) }}
                />
              </div>
            </div>
            <div>
              <div className="mb-1 flex justify-between text-xs text-slate-500">
                <span>日漲跌幅</span>
                <span className={valueTone(changePct)}>
                  <PriceUpdatePulse
                    value={changePct}
                    direction={changePct}
                    resetKey={`${selectedSymbol ?? "empty"}:technical-change`}
                    className="justify-end tabular-nums"
                  >
                    {formatPct(changePct)}
                  </PriceUpdatePulse>
                </span>
              </div>
              <div className="h-2 bg-slate-100">
                <div
                  className={`omi-technical-bar h-2 ${metricBarClass(changePct)}`}
                  style={{ width: metricBarWidth(changePct) }}
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 border-t border-slate-200 text-center text-sm">
            <div className="px-4 py-3">
              <div className="text-xs text-slate-500">MA5</div>
              <div className="mt-1 font-bold">{formatNumber(ma5)}</div>
            </div>
            <div className="border-l border-slate-200 px-4 py-3">
              <div className="text-xs text-slate-500">MA20</div>
              <div className="mt-1 font-bold">{formatNumber(ma20)}</div>
            </div>
            <div className="border-l border-slate-200 px-4 py-3">
              <div className="text-xs text-slate-500">MA60</div>
              <div className="mt-1 font-bold">{formatNumber(ma60)}</div>
            </div>
          </div>
        </section>

        <section className="border-t border-slate-200 px-5 py-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                Coverage
              </div>
              <div className="mt-1 text-sm font-bold text-slate-950">
                Right-side data readiness
              </div>
            </div>
            <div className="text-right text-[11px] font-semibold text-slate-500">
              {readyCoverageCount}/{dataCoverageItems.length} ready
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {dataCoverageItems.map((item) => (
              <DataCoverageChip
                key={item.label}
                label={item.label}
                status={item.status}
                detail={item.detail}
              />
            ))}
          </div>
        </section>

        {selectedIndexConfig ? (
          <section className="border-t border-slate-200 px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
              Data
            </div>
            <h3 className="mt-1 text-lg font-bold text-slate-950">
              {selectedDisplayName}
            </h3>
            <div className="mt-1 text-sm leading-6 text-slate-500">
              目前接入 Yahoo chart 的日K、週K、月K與盤中 1 分 K。成分股廣度、權重貢獻與產業分解待下一版補上。
            </div>
            <div className="mt-4 grid grid-cols-2 gap-px bg-slate-200 text-sm">
              <MetricCell label="Symbol" value={selectedIndexConfig.symbol} />
              <MetricCell label="Display" value={selectedIndexConfig.displaySymbol} />
              <MetricCell label="Exchange" value={selectedIndexConfig.exchange} />
              <MetricCell label="Source" value="Yahoo chart" />
            </div>
          </section>
        ) : (
          <section className="border-t border-slate-200">
            <div className="grid grid-cols-4 border-b border-slate-200">
              {usDataPanelTabs.map((tab) => (
                <USDataTabButton
                  key={tab.key}
                  tab={tab}
                  active={activeDataTab === tab.key}
                  onClick={() => setActiveDataTab(tab.key)}
                />
              ))}
            </div>

            <div className="px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                    Data
                  </div>
                  <h3 className="mt-1 text-lg font-bold text-slate-950">
                    {activeDataTabMeta.title}
                  </h3>
                  <div className="mt-1 text-xs text-slate-500">
                    {activeDataTabMeta.description}
                  </div>
                </div>
                {renderDataPanelAction()}
              </div>

              <div className="mt-4">{renderActiveDataTab()}</div>
            </div>
          </section>
        )}
      </aside>
    </section>
  );
}

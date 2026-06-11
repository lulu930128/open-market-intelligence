"use client";

import IntradayTrendChart, {
  defaultIntradayIndicators,
  intradayIndicatorOptions,
  type IntradayIndicatorKey,
  type IntradayIndicatorSettings,
} from "@/components/IntradayTrendChart";
import { LoadingDots } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  indicatorCategoryGroups,
  type IndicatorParameters,
  type IndicatorKey,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import type { ChartDrawing, ChartDrawingTool } from "@/components/LightweightKLineChart";
import { fetchJson } from "@/lib/api";
import { getJobResultStatus, requestBackfillJob } from "@/lib/jobs";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  TAIWAN_SESSION_START_MINUTES,
  getTaipeiMinutesOfDay,
  getTaiwanMarketRefreshState,
  isTaiwanRegularSessionPoint,
} from "@/lib/taiwanMarketTime";
import {
  getTaiwanChartHistoryRequirement,
  getTaiwanDataPanelRefreshLabel,
  getTaiwanDataPanelRefreshProfile,
  taiwanDailyPriceBackfillPath,
  taiwanSelectionRefreshPath,
  type TaiwanChartTimeframe,
  type TaiwanRefreshProfile,
  type TaiwanDataPanelTab,
} from "@/lib/taiwanMarketRules";
import type {
  BrokerBranchTradeDailyRead,
  BrokerBranchTradeDailySummaryRead,
  ChartPoint,
  FinancialMetricQuarterlyRead,
  IntradayHistoryResponse,
  IntradayTrendPoint,
  IntradayTrendResponse,
  InstitutionalHoldingRatioRead,
  InstitutionalTradeDailyRead,
  JobRunRead,
  MarginTradingDailyRead,
  MarketChipDaily,
  MarketIndexContributionItem,
  MarketIndexContributionResponse,
  MarketIndexListItem,
  MarketIndexListResponse,
  MarketIndexSnapshot,
  MarketIndexSummary,
  MonthlyRevenueRead,
  OhlcChartResponse,
  OvernightImpactRead,
  ShareholdingDistributionWeeklyRead,
  StockChipCoverageRead,
  StockIndicatorPoint,
  StockMasterRead,
  StockTechnicalReportRead,
} from "@/types/market";
import {
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import dynamic from "next/dynamic";

const LightweightKLineChart = dynamic(
  () => import("@/components/LightweightKLineChart"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[640px] items-center justify-center border-t border-slate-200 bg-white text-sm text-slate-500">
        K 線引擎載入中...
      </div>
    ),
  }
);

type Props = {
  stockId: string | null;
  stockName: string | null;
  initialChartData?: ChartPoint[];
  initialIndicatorData?: StockIndicatorPoint[];
  watchlistRankingPanel?: ReactNode;
  marketIndexSummary?: MarketIndexSummary | null;
  onChartFocusModeChange?: (active: boolean) => void;
};

type Timeframe = "today" | "daily" | "weekly" | "monthly";
type ChartTimeframe = Exclude<Timeframe, "today">;
type ProfessionalIntradayTimeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h";
type ProfessionalTimeframe = ProfessionalIntradayTimeframe | ChartTimeframe;
type ProfessionalChartStyle = "candlestick" | "line";
type LoadState = "idle" | "loading" | "success" | "error";
type DataPanelTab = TaiwanDataPanelTab;
type BranchTableSide = "buy" | "sell";
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

function dataPanelCacheKey(stockId: string, tab: DataPanelTab, branchDays = 1) {
  return tab === "branch" ? `${stockId}:${tab}:${branchDays}` : `${stockId}:${tab}`;
}

const branchDayOptions = [
  { label: "1", days: 1 },
  { label: "3", days: 3 },
  { label: "5", days: 5 },
  { label: "10", days: 10 },
  { label: "20", days: 20 },
  { label: "60", days: 60 },
  { label: "120", days: 120 },
  { label: "更多", days: null },
];
const largeHolderLotOptions = [100, 200, 400, 600, 800, 1000];
const smallHolderLotOptions = [10, 20, 30, 40, 50, 100];
const institutionalLookbackDays = 100;
const institutionalHistoryLimit = 120;
const institutionalDisplayMonths = 3;
const revenueHistoryLimit = 120;
const financialHistoryLimit = 40;
const minimumUsableRevenueRows = 2;
const minimumUsableFinancialRows = 2;
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
const professionalTimeframeOptions: Array<{
  key: ProfessionalTimeframe;
  label: string;
}> = [
  { key: "1m", label: "1分" },
  { key: "5m", label: "5分" },
  { key: "15m", label: "15分" },
  { key: "30m", label: "30分" },
  { key: "1h", label: "1小時" },
  { key: "4h", label: "4小時" },
  { key: "daily", label: "天" },
  { key: "weekly", label: "週" },
  { key: "monthly", label: "月" },
];
const chartDrawingToolOptions: Array<{
  key: ChartDrawingTool;
  label: string;
}> = [
  { key: "cursor", label: "游標" },
  { key: "horizontal", label: "水平" },
  { key: "trend", label: "趨勢" },
  { key: "ray", label: "射線" },
  { key: "rectangle", label: "區間" },
  { key: "fibonacci", label: "Fib" },
  { key: "measure", label: "量測" },
  { key: "priceRange", label: "價幅%" },
];
const chartDrawingToolOptionMap = new Map(
  chartDrawingToolOptions.map((option) => [option.key, option])
);
const chartDrawingToolGroups: Array<{
  key: string;
  tools: ChartDrawingTool[];
}> = [
  { key: "base", tools: ["cursor"] },
  { key: "line", tools: ["horizontal", "trend", "ray"] },
  { key: "area", tools: ["rectangle", "fibonacci"] },
  { key: "measure", tools: ["measure", "priceRange"] },
];
const professionalIntradayMinutes: Record<ProfessionalIntradayTimeframe, number> = {
  "1m": 1,
  "5m": 5,
  "15m": 15,
  "30m": 30,
  "1h": 60,
  "4h": 240,
};
const chartBarsByTimeframe: Record<ChartTimeframe, number> = {
  daily: 2600,
  weekly: 520,
  monthly: 132,
};
const dailyIndicatorLimit = 220;
const openingObservationMinutes = 5;
const openingObservationMinPoints = 5;
const allTimeframes = Object.keys(timeframeLabels) as Timeframe[];
const indexTimeframes: Timeframe[] = ["today", "daily", "weekly", "monthly"];
const indexProducts = new Map([
  [
    "TAIEX",
    {
      indexId: "TAIEX",
      stockId: "TAIEX",
      stockName: "加權指數",
      market: "TWSE",
      symbol: "^TWII",
    },
  ],
  [
    "TPEX",
    {
      indexId: "TPEX",
      stockId: "TPEX",
      stockName: "櫃買指數",
      market: "TPEX",
      symbol: "^TWOII",
    },
  ],
]);

type IndicatorTemplateKey = "basic" | "short" | "trend" | "swing" | "flow";

const indicatorTemplates: Array<{
  key: IndicatorTemplateKey;
  label: string;
  indicators: IndicatorSettings;
  parameters?: Partial<IndicatorParameters>;
}> = [
  {
    key: "basic",
    label: "基本",
    indicators: defaultIndicators,
  },
  {
    key: "short",
    label: "短線",
    indicators: {
      ...defaultIndicators,
      ma: false,
      ema: true,
      vwap: true,
      kd: true,
      mfi: true,
      signals: true,
    },
    parameters: {
      emaFast: 5,
      emaSlow: 20,
      kdPeriod: 9,
      mfiPeriod: 14,
    },
  },
  {
    key: "trend",
    label: "趨勢",
    indicators: {
      ...defaultIndicators,
      ema: true,
      psar: true,
      donchian: true,
      ichimoku: true,
      supertrend: true,
      atr: true,
      adx: true,
      signals: true,
    },
    parameters: {
      emaFast: 12,
      emaSlow: 26,
      donchianPeriod: 20,
      ichimokuConversionPeriod: 9,
      ichimokuBasePeriod: 26,
      ichimokuSpanBPeriod: 52,
      ichimokuDisplacement: 26,
      supertrendAtrPeriod: 10,
      supertrendMultiplier: 3,
      atrPeriod: 14,
      adxPeriod: 14,
    },
  },
  {
    key: "swing",
    label: "波段",
    indicators: {
      ...defaultIndicators,
      bollinger: true,
      keltner: true,
      rsi: true,
      macd: true,
      aroon: true,
      roc: true,
      trix: true,
      cci: true,
      signals: true,
    },
    parameters: {
      bollingerPeriod: 20,
      bollingerStdDev: 2,
      keltnerPeriod: 20,
      keltnerAtrPeriod: 10,
      keltnerMultiplier: 2,
      rsiPeriod: 14,
      aroonPeriod: 25,
      rocPeriod: 12,
      trixPeriod: 15,
      trixSignal: 9,
      cciPeriod: 20,
    },
  },
  {
    key: "flow",
    label: "量價",
    indicators: {
      ...defaultIndicators,
      ma: false,
      vwap: true,
      obv: true,
      mfi: true,
      volume: true,
      signals: true,
    },
    parameters: {
      volumeMa: 20,
      obvMa: 10,
      mfiPeriod: 14,
    },
  },
];

type ChartDrawingStorageState = {
  key: string;
  drawings: ChartDrawing[];
};

type ChartDrawingHistoryState = {
  key: string;
  past: ChartDrawing[][];
  future: ChartDrawing[][];
};

function chartDrawingStorageKey(stockId: string | null, timeframe: ProfessionalTimeframe) {
  return `omi:tw:chart-drawings:v1:${stockId ?? "empty"}:${timeframe}`;
}

function isChartDrawingType(value: unknown): value is ChartDrawing["type"] {
  return (
    value === "horizontal" ||
    value === "trend" ||
    value === "ray" ||
    value === "rectangle" ||
    value === "fibonacci" ||
    value === "measure" ||
    value === "priceRange"
  );
}

function normalizeStoredChartDrawings(value: unknown): ChartDrawing[] {
  if (!Array.isArray(value)) return [];

  return value
    .flatMap((item): ChartDrawing[] => {
      if (!item || typeof item !== "object") return [];

      const candidate = item as Partial<ChartDrawing>;
      const type = candidate.type;
      const points = Array.isArray(candidate.points)
        ? candidate.points.filter(
            (point): point is ChartDrawing["points"][number] =>
              Boolean(point) &&
              typeof point.time === "string" &&
              typeof point.price === "number" &&
              Number.isFinite(point.price)
          )
        : [];

      if (
        typeof candidate.id !== "string" ||
        !isChartDrawingType(type) ||
        typeof candidate.color !== "string" ||
        typeof candidate.createdAt !== "string" ||
        points.length === 0
      ) {
        return [];
      }

      const pointCount = type === "horizontal" ? 1 : 2;

      if (points.length < pointCount) return [];

      return [
        {
          id: candidate.id,
          type,
          points: points.slice(0, pointCount),
          color: candidate.color,
          createdAt: candidate.createdAt,
        },
      ];
    })
    .slice(-200);
}

function loadChartDrawings(storageKey: string): ChartDrawing[] {
  if (typeof window === "undefined") return [];

  try {
    const raw = window.localStorage.getItem(storageKey);

    if (!raw) return [];

    return normalizeStoredChartDrawings(JSON.parse(raw));
  } catch {
    return [];
  }
}

function saveChartDrawings(storageKey: string, drawings: ChartDrawing[]) {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(storageKey, JSON.stringify(drawings.slice(-200)));
  } catch {
    // Best-effort local draft storage; chart drawing should never break the market view.
  }
}

function serializeChartDrawings(drawings: ChartDrawing[]) {
  return JSON.stringify(drawings);
}

function TechnicalIndicatorMenu({
  indicators,
  activeTemplate,
  onApplyTemplate,
  onToggleIndicator,
  includeParameters = false,
  parameters,
  onUpdateParameter,
  className = "w-80",
}: {
  indicators: IndicatorSettings;
  activeTemplate: IndicatorTemplateKey | null;
  onApplyTemplate: (templateKey: IndicatorTemplateKey) => void;
  onToggleIndicator: (key: IndicatorKey) => void;
  includeParameters?: boolean;
  parameters?: IndicatorParameters;
  onUpdateParameter?: (
    key: keyof IndicatorParameters,
    value: string,
    min: number,
    max: number
  ) => void;
  className?: string;
}) {
  return (
    <div
      className={[
        "absolute right-0 z-30 mt-2 max-h-[74vh] overflow-y-auto border border-slate-200 bg-white p-3 text-left shadow-lg",
        className,
      ].join(" ")}
    >
      <div className="border-b border-slate-200 pb-3">
        <div className="mb-2 text-xs font-bold text-slate-500">快速組合</div>
        <div className="grid grid-cols-5 gap-1">
          {indicatorTemplates.map((template) => (
            <button
              key={template.key}
              type="button"
              onClick={() => onApplyTemplate(template.key)}
              className={[
                "h-8 border text-xs font-semibold",
                activeTemplate === template.key
                  ? "border-red-700 bg-red-700 text-white"
                  : "border-slate-300 bg-white text-slate-700 hover:border-slate-900",
              ].join(" ")}
            >
              {template.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3 border-b border-slate-200 py-3">
        {indicatorCategoryGroups.map((group) => (
          <div key={group.key}>
            <div className="mb-1">
              <div className="text-xs font-bold text-slate-700">{group.label}</div>
              <div className="text-[11px] leading-4 text-slate-400">{group.description}</div>
            </div>
            <div className="space-y-0.5">
              {group.options.map((option) =>
                option.status === "available" ? (
                  <label
                    key={option.key}
                    className="flex cursor-pointer items-start gap-2 px-2 py-1.5 text-xs hover:bg-slate-50"
                  >
                    <input
                      type="checkbox"
                      checked={indicators[option.key]}
                      onChange={() => onToggleIndicator(option.key)}
                      className="mt-0.5"
                    />
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 font-semibold text-slate-800">
                        <span>{option.label}</span>
                        <span className="text-[10px] font-medium uppercase text-slate-400">
                          {option.plot}
                        </span>
                      </span>
                      <span className="block text-slate-500">{option.description}</span>
                    </span>
                  </label>
                ) : (
                  <div
                    key={option.key}
                    className="flex cursor-not-allowed items-start justify-between gap-3 px-2 py-1.5 text-xs opacity-60"
                  >
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 font-semibold text-slate-600">
                        <span>{option.label}</span>
                        <span className="text-[10px] font-medium uppercase text-slate-400">
                          {option.plot}
                        </span>
                      </span>
                      <span className="block text-slate-500">{option.description}</span>
                    </span>
                    <span className="shrink-0 bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-500">
                      待補
                    </span>
                  </div>
                )
              )}
            </div>
          </div>
        ))}
      </div>

      {includeParameters && parameters && onUpdateParameter ? (
        <div className="pt-3">
          <div className="mb-2 text-xs font-bold text-slate-500">參數</div>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: "MA短", key: "maShort", min: 1, max: 300 },
              { label: "MA中", key: "maMiddle", min: 1, max: 400 },
              { label: "MA長", key: "maLong", min: 1, max: 600 },
              { label: "EMA快", key: "emaFast", min: 1, max: 200 },
              { label: "EMA慢", key: "emaSlow", min: 2, max: 400 },
              { label: "BOLL週期", key: "bollingerPeriod", min: 2, max: 300 },
              { label: "BOLL倍數", key: "bollingerStdDev", min: 0.5, max: 5, step: 0.1 },
              { label: "量均", key: "volumeMa", min: 1, max: 300 },
              { label: "RSI", key: "rsiPeriod", min: 2, max: 100 },
              { label: "MACD快", key: "macdFast", min: 1, max: 100 },
              { label: "MACD慢", key: "macdSlow", min: 2, max: 200 },
              { label: "MACD Sig", key: "macdSignal", min: 1, max: 100 },
              { label: "KD", key: "kdPeriod", min: 2, max: 100 },
              { label: "ATR", key: "atrPeriod", min: 2, max: 100 },
              { label: "ADX", key: "adxPeriod", min: 2, max: 100 },
              { label: "DONCH", key: "donchianPeriod", min: 2, max: 300 },
              { label: "一目轉換", key: "ichimokuConversionPeriod", min: 2, max: 120 },
              { label: "一目基準", key: "ichimokuBasePeriod", min: 2, max: 240 },
              { label: "一目SpanB", key: "ichimokuSpanBPeriod", min: 2, max: 360 },
              { label: "一目位移", key: "ichimokuDisplacement", min: 0, max: 120 },
              { label: "ST ATR", key: "supertrendAtrPeriod", min: 2, max: 100 },
              { label: "ST倍數", key: "supertrendMultiplier", min: 0.5, max: 10, step: 0.1 },
              { label: "KC週期", key: "keltnerPeriod", min: 2, max: 300 },
              { label: "KC ATR", key: "keltnerAtrPeriod", min: 2, max: 100 },
              { label: "KC倍數", key: "keltnerMultiplier", min: 0.5, max: 10, step: 0.1 },
              { label: "Aroon", key: "aroonPeriod", min: 2, max: 200 },
              { label: "OBV MA", key: "obvMa", min: 1, max: 200 },
              { label: "MFI", key: "mfiPeriod", min: 2, max: 100 },
              { label: "CCI", key: "cciPeriod", min: 2, max: 200 },
              { label: "W%R", key: "williamsRPeriod", min: 2, max: 100 },
              { label: "ROC", key: "rocPeriod", min: 1, max: 200 },
              { label: "StochRSI", key: "stochRsiPeriod", min: 2, max: 100 },
              { label: "Stoch K", key: "stochRsiSmoothK", min: 1, max: 20 },
              { label: "Stoch D", key: "stochRsiSmoothD", min: 1, max: 20 },
              { label: "TRIX", key: "trixPeriod", min: 2, max: 100 },
              { label: "TRIX Sig", key: "trixSignal", min: 1, max: 50 },
            ].map((field) => (
              <label key={field.key} className="text-xs">
                <span className="mb-1 block font-semibold text-slate-500">{field.label}</span>
                <input
                  type="number"
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  value={parameters[field.key as keyof IndicatorParameters]}
                  onChange={(event) =>
                    onUpdateParameter(
                      field.key as keyof IndicatorParameters,
                      event.target.value,
                      field.min,
                      field.max
                    )
                  }
                  className="h-8 w-full border border-slate-300 px-2 text-xs font-semibold text-slate-800"
                />
              </label>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatSignedPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatPrice(value)}`;
}

function formatSignedPointChange(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";

  return `${sign}${value.toLocaleString("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value));
}

function formatTradeValueYi(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return (value / 100_000_000).toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatSignedTradeValueYi(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";

  return `${sign}${formatTradeValueYi(value)}`;
}

function formatSignedContracts(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value)}口`;
}

function formatContributionPoint(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(4)}`;
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

function formatLotUnits(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value));
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatIndicatorValue(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
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

function shiftIsoDate(value: string, days: number) {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);

  if (!year || !month || !day) return value.slice(0, 10);

  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readBackfillCount(result: unknown, key: string) {
  if (!isRecord(result)) return null;

  const value = result[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatPanelJobProgress(label: string, job: JobRunRead) {
  const total = Math.max(job.progress_total || 1, 1);
  const current = Math.min(Math.max(job.progress_current || 0, 0), total);
  const status = getJobResultStatus(job) ?? job.status;

  if (status === "error") {
    return `${label}：補齊失敗，詳見左側更新狀態`;
  }

  if (status === "partial_success") {
    return `${label}：部分完成，詳見左側更新狀態`;
  }

  if (status === "success") {
    return `${label}：補齊完成，詳見左側更新狀態`;
  }

  return `${label}：補齊中，進度 ${current}/${total}，詳見左側更新狀態`;
}

function formatBackfillOutcome(job: JobRunRead, label: string) {
  const status = getJobResultStatus(job);
  const insertedCount =
    readBackfillCount(job.result, "inserted_count") ??
    readBackfillCount(job.result, "refreshed_count");
  const skippedCount =
    readBackfillCount(job.result, "skipped_existing_count") ??
    readBackfillCount(job.result, "skipped_count");
  const errorCount = readBackfillCount(job.result, "error_count");
  const details = [
    insertedCount !== null && insertedCount > 0 ? `更新 ${insertedCount}` : null,
    skippedCount !== null && skippedCount > 0 ? `已存在 ${skippedCount}` : null,
    errorCount !== null && errorCount > 0 ? `失敗 ${errorCount}` : null,
  ].filter(Boolean);
  const suffix =
    status === "partial_success"
      ? "部分完成"
      : status === "skipped"
        ? "無需補齊"
        : status === "error"
          ? "失敗"
          : "補齊完成";

  return `${label}${suffix}${details.length ? `（${details.join("、")}）` : ""}`;
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

type PriceLimitStatus = "limit_up" | "limit_down" | null;

function estimatedPriceLimitStatus(value: number | null | undefined): PriceLimitStatus {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  if (value >= 9.5) return "limit_up";
  if (value <= -9.5) return "limit_down";
  return null;
}

function priceLimitTone(status: PriceLimitStatus, fallback: number | null | undefined) {
  if (status === "limit_up") return "text-red-600";
  if (status === "limit_down") return "text-emerald-600";
  return valueTone(fallback);
}

function priceLimitBoxClass(status: PriceLimitStatus) {
  if (status === "limit_up") {
    return "rounded-[4px] bg-red-500 px-3 py-2 text-white shadow-sm";
  }

  if (status === "limit_down") {
    return "rounded-[4px] bg-emerald-500 px-3 py-2 text-white shadow-sm";
  }

  return "";
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

function finiteNumber(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

function isProfessionalIntradayTimeframe(
  value: ProfessionalTimeframe
): value is ProfessionalIntradayTimeframe {
  return value in professionalIntradayMinutes;
}

function intradayTimeMs(value: string) {
  const date = new Date(value);
  const timestamp = date.getTime();

  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function aggregateProfessionalIntradayBars(
  points: IntradayTrendPoint[],
  intervalMinutes: number
): ChartPoint[] {
  const buckets = new Map<number, IntradayTrendPoint[]>();

  points
    .filter((point) => finiteNumber(point.price) && isTaiwanRegularSessionPoint(point.time))
    .slice()
    .sort((left, right) => intradayTimeMs(left.time) - intradayTimeMs(right.time))
    .forEach((point) => {
      const minutes = getTaipeiMinutesOfDay(point.time);

      if (minutes === null) return;

      const bucket =
        TAIWAN_SESSION_START_MINUTES +
        Math.floor((minutes - TAIWAN_SESSION_START_MINUTES) / intervalMinutes) *
          intervalMinutes;
      const current = buckets.get(bucket) ?? [];

      current.push(point);
      buckets.set(bucket, current);
    });

  return Array.from(buckets.entries())
    .sort(([left], [right]) => left - right)
    .map(([, bucketPoints]) => {
      const first = bucketPoints[0];
      const last = bucketPoints[bucketPoints.length - 1];
      const highs = bucketPoints.map((point) => point.high ?? point.price).filter(finiteNumber);
      const lows = bucketPoints.map((point) => point.low ?? point.price).filter(finiteNumber);
      const volume = bucketPoints.reduce((total, point) => {
        return total + (finiteNumber(point.volume) && point.volume > 0 ? point.volume : 0);
      }, 0);

      return {
        time: first.time,
        open: first.open ?? first.price,
        high: highs.length ? Math.max(...highs) : last.price,
        low: lows.length ? Math.min(...lows) : last.price,
        close: last.price,
        volume: volume > 0 ? volume : null,
        trade_value: null,
        transaction_count: null,
      };
    });
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

function averageRecentChartValue(
  points: ChartPoint[],
  key: "close" | "volume",
  windowSize: number
) {
  const values = points
    .slice(-windowSize)
    .map((point) => point[key])
    .filter((value): value is number => value !== null && value !== undefined);

  if (values.length < windowSize) return null;

  return values.reduce((total, value) => total + value, 0) / values.length;
}

function chartWindowStats(points: ChartPoint[], windowSize: number) {
  const rows = points.slice(-windowSize);
  const firstClose = rows.find((point) => finiteNumber(point.close))?.close ?? null;
  const latest = [...rows].reverse().find((point) => finiteNumber(point.close)) ?? null;
  const latestClose = latest?.close ?? null;
  const highs = rows.map((point) => point.high).filter(finiteNumber);
  const lows = rows.map((point) => point.low).filter(finiteNumber);
  const volumes = rows.map((point) => point.volume).filter(finiteNumber);
  const high = highs.length ? Math.max(...highs) : null;
  const low = lows.length ? Math.min(...lows) : null;
  const changePct =
    finiteNumber(latestClose) && finiteNumber(firstClose) && firstClose !== 0
      ? ((latestClose - firstClose) / firstClose) * 100
      : null;
  const rangePositionPct =
    finiteNumber(latestClose) && finiteNumber(high) && finiteNumber(low) && high !== low
      ? ((latestClose - low) / (high - low)) * 100
      : null;

  return {
    pointCount: rows.length,
    latestClose,
    changePct,
    high,
    low,
    rangePositionPct,
    volumeAverage:
      volumes.length > 0
        ? volumes.reduce((total, value) => total + value, 0) / volumes.length
        : null,
  };
}

function averageRecentChartClose(points: ChartPoint[], windowSize: number) {
  return averageRecentChartValue(points, "close", windowSize);
}

function latestLargeHolderSummary(
  rows: ShareholdingDistributionWeeklyRead[],
  largeHolderLots: number
) {
  const groups = new Map<string, ShareholdingDistributionWeeklyRead[]>();

  rows.forEach((row) => {
    groups.set(row.data_date, [...(groups.get(row.data_date) ?? []), row]);
  });

  const points = Array.from(groups.entries())
    .sort(([leftDate], [rightDate]) => leftDate.localeCompare(rightDate))
    .map(([dataDate, groupRows]) => {
      const largeRows = groupRows.filter((row) => {
        const range = shareholdingLevelRanges[row.holding_level_order ?? -1];
        return range ? range.minLots >= largeHolderLots : false;
      });
      const ratio = largeRows.reduce((total, row) => total + (row.share_ratio ?? 0), 0);

      return {
        dataDate,
        ratio: largeRows.length ? ratio : null,
      };
    })
    .filter((point) => point.ratio !== null);
  const latest = points[points.length - 1] ?? null;
  const previous = points[points.length - 2] ?? null;
  const change =
    latest?.ratio !== null &&
    latest?.ratio !== undefined &&
    previous?.ratio !== null &&
    previous?.ratio !== undefined
      ? latest.ratio - previous.ratio
      : null;

  return {
    ratio: latest?.ratio ?? null,
    change,
    dataDate: latest?.dataDate ?? null,
  };
}

function sumRecentInstitutionalNet(rows: InstitutionalTradeDailyRead[], rowCount: number) {
  const values = rows
    .slice(-rowCount)
    .map((row) => row.total_institutional_net)
    .filter(finiteNumber);

  if (!values.length) return null;

  return values.reduce((total, value) => total + value, 0);
}

function summarizeIntradayPoints(points: IntradayTrendPoint[]) {
  const validPoints = points.filter((point) => point.price !== null && point.price !== undefined);

  if (validPoints.length === 0) {
    return {
      open: null,
      high: null,
      low: null,
      volume: null,
    };
  }

  const firstPoint = validPoints[0];
  const highs = validPoints.map((point) => point.high ?? point.price);
  const lows = validPoints.map((point) => point.low ?? point.price);
  const volumes = validPoints
    .map((point) => point.volume)
    .filter((value): value is number => value !== null && value !== undefined);

  return {
    open: firstPoint.open ?? firstPoint.price,
    high: Math.max(...highs),
    low: Math.min(...lows),
    volume: volumes.length > 0 ? volumes.reduce((total, value) => total + value, 0) : null,
  };
}

type TechnicalTone = "positive" | "negative" | "neutral" | "warning";

type TechnicalReportRow = {
  title: string;
  description: string;
  value: string;
  pulseValue?: number | string | null;
  direction?: number | null;
  tone?: TechnicalTone;
};

type TechnicalReportBadge = {
  label: string;
  tone: string;
};

type TechnicalReport = {
  title: string;
  summary: string;
  value: number | null;
  valueLabel: string;
  score: number;
  rows: TechnicalReportRow[];
  badges: TechnicalReportBadge[];
};

function technicalToneClass(tone: TechnicalTone) {
  if (tone === "positive") return "text-red-600";
  if (tone === "negative") return "text-emerald-600";
  if (tone === "warning") return "text-amber-600";
  return "text-slate-700";
}

function semanticTechnicalTone(tone: string | null | undefined): TechnicalTone {
  if (tone === "positive" || tone === "negative" || tone === "warning") return tone;
  return "neutral";
}

function semanticBadgeToneClass(tone: string | null | undefined) {
  if (tone === "positive") return "text-red-700 bg-red-50";
  if (tone === "negative") return "text-emerald-700 bg-emerald-50";
  if (tone === "warning") return "text-amber-700 bg-amber-50";
  return "text-slate-600 bg-slate-100";
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function mapBackendTechnicalReport(report: StockTechnicalReportRead): TechnicalReport {
  return {
    title: report.title,
    summary: report.summary,
    value: report.value,
    valueLabel: report.value_label,
    score: report.score,
    rows: report.rows.map((row) => ({
      title: row.label,
      description: row.description,
      value: row.display_value,
      pulseValue: numberValue(row.value),
      direction: row.direction,
      tone: semanticTechnicalTone(row.tone),
    })),
    badges: report.badges.map((badge) => ({
      label: badge.label,
      tone: semanticBadgeToneClass(badge.tone),
    })),
  };
}

function TechnicalSignalRow({
  title,
  description,
  value,
  pulseValue,
  direction,
  tone = "neutral",
}: {
  title: string;
  description: string;
  value: string;
  pulseValue?: number | string | null;
  direction?: number | null;
  tone?: TechnicalTone;
}) {
  return (
    <div className={`omi-technical-row omi-technical-row-${tone} flex items-start justify-between gap-4 border-t border-slate-100 py-2 first:border-t-0 first:pt-0`}>
      <div className="min-w-0">
        <div className="text-sm font-bold text-slate-950">{title}</div>
        <div className="mt-0.5 text-xs leading-4 text-slate-500">{description}</div>
      </div>
      <div className={`omi-technical-score shrink-0 text-right text-sm font-bold ${technicalToneClass(tone)}`}>
        <PriceUpdatePulse
          value={pulseValue ?? value}
          direction={direction}
          resetKey={title}
          className="justify-end tabular-nums"
        >
          {value}
        </PriceUpdatePulse>
      </div>
    </div>
  );
}

function TechnicalLoadingPanel() {
  return (
    <>
      <div className="omi-technical-summary border-b border-slate-200 px-5 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            Technical
          </div>
          <LoadingDots label="Technical 分析讀取中" />
        </div>
        <div className="mt-3 flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="omi-skeleton h-5 w-32" />
            <div className="omi-skeleton h-3 w-56 max-w-full" />
          </div>
          <div className="w-20 space-y-2">
            <div className="ml-auto omi-skeleton h-5 w-16" />
            <div className="ml-auto omi-skeleton h-2.5 w-12" />
          </div>
        </div>
      </div>

      <div className="px-5 py-3">
        <div className="space-y-0">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              className="omi-technical-loading-row flex items-start justify-between gap-4 border-t border-slate-100 py-2 first:border-t-0 first:pt-0"
              aria-hidden="true"
            >
              <div className="min-w-0 flex-1 space-y-2">
                <div className="omi-skeleton h-3.5 w-24" />
                <div className="omi-skeleton h-2.5 w-48 max-w-full" />
              </div>
              <div className="w-20 space-y-2">
                <div className="ml-auto omi-skeleton h-3.5 w-14" />
                <div className="ml-auto omi-skeleton h-2.5 w-10" />
              </div>
            </div>
          ))}
        </div>

        <div className="mt-3 border-t border-slate-200 pt-3">
          <div className="omi-technical-loading-row flex items-start justify-between gap-4 text-xs">
            <div className="space-y-2">
              <div className="omi-skeleton h-3 w-16" />
              <div className="omi-skeleton h-4 w-20" />
              <div className="omi-skeleton h-2.5 w-24" />
            </div>
            <div className="w-20 space-y-2">
              <div className="ml-auto omi-skeleton h-3.5 w-16" />
              <div className="ml-auto omi-skeleton h-2.5 w-12" />
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2" aria-hidden="true">
          <div className="omi-skeleton h-7 w-20" />
          <div className="omi-skeleton h-7 w-24" />
          <div className="omi-skeleton h-7 w-16" />
        </div>
      </div>
    </>
  );
}

function overnightConfidenceLabel(value: string | null | undefined) {
  if (value === "high") return "高信心";
  if (value === "medium") return "中信心";
  if (value === "low") return "低信心";
  return "信心待確認";
}

function OvernightImpactPanel({
  report,
  loadState,
}: {
  report: OvernightImpactRead | null;
  loadState: LoadState;
}) {
  if (loadState === "idle") return null;

  if (loadState === "loading") {
    return (
      <div className="mt-3 border-t border-slate-200 pt-3">
        <div className="flex items-center justify-between gap-3 text-xs">
          <div>
            <div className="font-bold uppercase tracking-[0.14em] text-slate-500">
              Overnight
            </div>
            <div className="mt-1 text-slate-500">美股隔夜影響讀取中</div>
          </div>
          <LoadingDots label="讀取中" />
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mt-3 border-t border-slate-200 pt-3">
        <div className="flex items-start justify-between gap-4 text-xs">
          <div>
            <div className="font-bold uppercase tracking-[0.14em] text-slate-500">
              Overnight
            </div>
            <div className="mt-1 text-sm font-bold text-slate-950">美股隔夜資料不足</div>
            <div className="mt-0.5 text-slate-500">暫不納入台股映射判斷</div>
          </div>
          <div className="text-right font-bold text-slate-400">-</div>
        </div>
      </div>
    );
  }

  const driverRows = [
    ...report.factors.map((factor) => ({
      key: `factor:${factor.symbol}`,
      label: factor.label,
      value: factor.change_pct,
      contribution: factor.weighted_contribution,
    })),
    ...report.baskets.map((basket) => ({
      key: `basket:${basket.group_id}`,
      label: basket.group_name,
      value: basket.average_change_pct,
      contribution: basket.weighted_contribution,
    })),
  ]
    .filter((item) => item.contribution !== null && item.contribution !== undefined)
    .sort((a, b) => Math.abs(b.contribution ?? 0) - Math.abs(a.contribution ?? 0))
    .slice(0, 3);
  const hasWarning = report.warnings.length > 0 || report.confidence === "low";

  return (
    <div className="mt-3 border-t border-slate-200 pt-3">
      <div className="omi-overnight-impact flex items-start justify-between gap-4 text-xs">
        <div className="min-w-0">
          <div className="font-bold uppercase tracking-[0.14em] text-slate-500">
            Overnight
          </div>
          <div className="mt-0.5 text-sm font-bold text-slate-950">{report.title}</div>
          <div className="mt-0.5 max-h-8 overflow-hidden leading-4 text-slate-500">{report.summary}</div>
        </div>
        <div className={`shrink-0 text-right text-sm font-bold ${valueTone(report.weighted_change_pct)}`}>
          <PriceUpdatePulse
            value={report.weighted_change_pct}
            direction={report.weighted_change_pct}
            resetKey={`${report.stock_id}:overnight:${report.as_of ?? "none"}`}
            className="justify-end tabular-nums"
          >
            {formatPct(report.weighted_change_pct)}
          </PriceUpdatePulse>
          <div className="text-xs font-medium text-slate-500">{overnightConfidenceLabel(report.confidence)}</div>
        </div>
      </div>

      {driverRows.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {driverRows.map((item) => (
            <span
              key={item.key}
              className="inline-flex items-center gap-1 bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-600"
            >
              <span>{item.label}</span>
              <span className={valueTone(item.value)}>{formatPct(item.value)}</span>
            </span>
          ))}
        </div>
      ) : null}

      {hasWarning ? (
        <div className="mt-2 text-[11px] leading-4 text-amber-700">
          {report.as_of ? `資料日期 ${formatDate(report.as_of)}，` : ""}
          {report.warnings[0] ?? "資料完整度偏低，僅作參考"}
        </div>
      ) : null}
    </div>
  );
}

function marketRegimeLabel(index: MarketIndexSnapshot | null | undefined) {
  if (!index || index.close === null || index.close === undefined) return "資料不足";

  if (index.price_vs_ma20 !== null && index.price_vs_ma20 !== undefined) {
    if (index.price_vs_ma20 > 1) return "站上 MA20";
    if (index.price_vs_ma20 < -1) return "跌破 MA20";
  }

  if (index.change_pct !== null && index.change_pct !== undefined) {
    if (index.change_pct > 0) return "短線偏多";
    if (index.change_pct < 0) return "短線偏弱";
  }

  return "中性震盪";
}

function IndexListPanel({
  items,
  loadState,
  marketLabel,
}: {
  items: MarketIndexListItem[];
  loadState: LoadState;
  marketLabel: string;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
          Market
        </div>
        <div className="mt-2 flex items-end justify-between gap-4">
          <div>
            <div className="text-xl font-bold text-slate-950">{marketLabel}指數列表</div>
            {loadState === "loading" ? (
              <div className="mt-1 inline-flex items-center gap-2 text-xs text-slate-500">
                讀取中
                <LoadingDots label={`${marketLabel}指數列表讀取中`} />
              </div>
            ) : (
              <div className="mt-1 text-xs text-slate-500">{`${items.length} 檔指數`}</div>
            )}
          </div>
          <div className="text-right text-xs font-semibold text-slate-500">
            {marketLabel}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {items.length > 0 ? (
          items.map((item) => (
            <div
              key={`${item.market}-${item.rank}-${item.name}`}
              className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-slate-100 py-2 text-sm first:border-t-0"
            >
              <div className="min-w-0">
                <div className="truncate font-semibold text-slate-900">
                  {item.rank}. {item.name}
                </div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {item.trade_date ?? "-"}
                </div>
              </div>
              <div className="text-right font-semibold text-slate-950">
                {formatPrice(item.close)}
              </div>
              <div className={`min-w-20 text-right font-semibold ${valueTone(item.change_pct)}`}>
                <div>{formatPct(item.change_pct)}</div>
                <div className="text-xs font-medium">{formatSignedPrice(item.change)}</div>
              </div>
            </div>
          ))
        ) : loadState === "loading" ? (
          <div className="space-y-0" aria-hidden="true">
            {Array.from({ length: 6 }).map((_, index) => (
              <div
                key={index}
                className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-slate-100 py-2 first:border-t-0"
              >
                <div className="min-w-0 space-y-2">
                  <div className="omi-skeleton h-3.5 w-32" />
                  <div className="omi-skeleton h-2.5 w-20" />
                </div>
                <div className="omi-skeleton h-3.5 w-16" />
                <div className="omi-skeleton h-7 w-20" />
              </div>
            ))}
          </div>
        ) : (
          <div className="py-10 text-center text-sm text-slate-500">
            尚無指數列表資料
          </div>
        )}
      </div>
    </div>
  );
}

function IndexDetailDataPanel({
  index,
  timeframe,
  latestChart,
  todayStats,
  todayPreviousClose,
  marketChip,
  marketChipLoadState,
  contributions,
  contributionLoadState,
}: {
  index: MarketIndexSnapshot | null;
  timeframe: Timeframe;
  latestChart: ChartPoint | null;
  todayStats: ReturnType<typeof summarizeIntradayPoints>;
  todayPreviousClose: number | null;
  marketChip: MarketChipDaily | null;
  marketChipLoadState: LoadState;
  contributions: MarketIndexContributionResponse | null;
  contributionLoadState: LoadState;
}) {
  const isToday = timeframe === "today";
  const breadth = index?.breadth ?? null;
  const open = isToday
    ? todayStats.open ?? index?.open ?? latestChart?.open ?? null
    : latestChart?.open ?? index?.open ?? null;
  const high = isToday
    ? todayStats.high ?? index?.high ?? latestChart?.high ?? null
    : latestChart?.high ?? index?.high ?? null;
  const low = isToday
    ? todayStats.low ?? index?.low ?? latestChart?.low ?? null
    : latestChart?.low ?? index?.low ?? null;
  const reference = todayPreviousClose ?? index?.previous_close ?? null;
  const tradeValue = index?.trade_value ?? breadth?.trade_value ?? latestChart?.trade_value ?? null;
  const estimatedTradeValue = index?.estimated_trade_value ?? tradeValue;

  return (
    <section className="border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            Index Data
          </div>
          <div className="mt-1 text-lg font-bold text-slate-950">指數詳細數據</div>
        </div>
        <div className="text-right text-xs text-slate-500">
          更新 {formatDateTime(index?.as_of)}
        </div>
      </div>

      <div className="grid gap-2 border-b border-slate-200 p-5 sm:grid-cols-2 xl:grid-cols-4">
        <IndexMetricCard
          label="開盤"
          value={formatPrice(open)}
          tone={valueTone(open !== null && reference !== null ? open - reference : null)}
        />
        <IndexMetricCard
          label="最高"
          value={formatPrice(high)}
          tone={valueTone(high !== null && reference !== null ? high - reference : null)}
        />
        <IndexMetricCard
          label="最低"
          value={formatPrice(low)}
          tone={valueTone(low !== null && reference !== null ? low - reference : null)}
        />
        <IndexMetricCard label="參考" value={formatPrice(reference)} />
        <IndexMetricCard label="成交金額(億)" value={formatTradeValueYi(tradeValue)} />
        <IndexMetricCard label="估計金額(億)" value={formatTradeValueYi(estimatedTradeValue)} />
        <IndexMetricCard label="上漲家" value={formatNumber(breadth?.advance_count)} tone="text-red-600" />
        <IndexMetricCard label="下跌家" value={formatNumber(breadth?.decline_count)} tone="text-emerald-600" />
        <IndexMetricCard label="漲停家" value={formatNumber(breadth?.limit_up_count)} tone="text-red-600" />
        <IndexMetricCard label="跌停家" value={formatNumber(breadth?.limit_down_count)} tone="text-emerald-600" />
        <IndexMetricCard label="平盤家" value={formatNumber(breadth?.unchanged_count)} />
        <IndexMetricCard label="總家數" value={formatNumber(breadth?.total_count)} />
      </div>

      <div className="border-b border-slate-200 px-5 py-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-xs font-bold text-slate-950">籌碼日報</div>
            <div className="mt-0.5 text-xs text-slate-500">
              大盤期貨未平倉、法人買賣超與信用交易摘要
            </div>
          </div>
          <div className="text-xs text-slate-500">
            資料日 {marketChip?.trade_date ? formatDate(marketChip.trade_date) : "-"}
          </div>
        </div>
        {marketChipLoadState === "loading" ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="omi-skeleton h-3 w-24" />
                <div className="omi-skeleton mt-2 h-4 w-20" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <IndexMetricCard
              label="外資淨未平倉"
              value={formatSignedContracts(marketChip?.foreign_futures_net_oi)}
              tone={valueTone(marketChip?.foreign_futures_net_oi)}
            />
            <IndexMetricCard
              label="外資未平倉加減"
              value={formatSignedContracts(marketChip?.foreign_futures_net_oi_change)}
              tone={valueTone(marketChip?.foreign_futures_net_oi_change)}
            />
            <IndexMetricCard
              label="散戶淨未平倉"
              value={formatSignedContracts(marketChip?.retail_futures_net_oi)}
              tone={valueTone(marketChip?.retail_futures_net_oi)}
            />
            <IndexMetricCard
              label="散戶未平倉加減"
              value={formatSignedContracts(marketChip?.retail_futures_net_oi_change)}
              tone={valueTone(marketChip?.retail_futures_net_oi_change)}
            />
            <IndexMetricCard
              label="三大法人買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.total_institutional_net_value)}
              tone={valueTone(marketChip?.total_institutional_net_value)}
            />
            <IndexMetricCard
              label="外資買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.foreign_investor_net_value)}
              tone={valueTone(marketChip?.foreign_investor_net_value)}
            />
            <IndexMetricCard
              label="投信買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.investment_trust_net_value)}
              tone={valueTone(marketChip?.investment_trust_net_value)}
            />
            <IndexMetricCard
              label="自營商買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.dealer_net_value)}
              tone={valueTone(marketChip?.dealer_net_value)}
            />
            <IndexMetricCard
              label="官股買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.government_bank_net_value)}
              tone={valueTone(marketChip?.government_bank_net_value)}
            />
            <IndexMetricCard
              label="融資變動(億)"
              value={formatSignedTradeValueYi(marketChip?.margin_balance_change_value)}
              tone={valueTone(marketChip?.margin_balance_change_value)}
            />
            <IndexMetricCard
              label="融資變動(張)"
              value={formatSignedLots(marketChip?.margin_balance_change_shares)}
              tone={valueTone(marketChip?.margin_balance_change_shares)}
            />
            <IndexMetricCard
              label="融券變動(張)"
              value={formatSignedLots(marketChip?.short_balance_change_shares)}
              tone={valueTone(marketChip?.short_balance_change_shares)}
            />
          </div>
        )}
      </div>

      <IndexContributionRanking
        contributions={contributions}
        loadState={contributionLoadState}
      />

      <div className="px-5 py-3 text-xs text-slate-500">
        {breadth?.source
          ? `市場廣度來源 ${breadth.source}；貢獻排行為估算值`
          : "市場廣度待資料更新"}
      </div>
    </section>
  );
}

function IndexMetricCard({
  label,
  value,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className={`mt-1 text-base font-bold ${tone}`}>{value}</div>
    </div>
  );
}

function ContributionColumn({
  title,
  items,
  tone,
}: {
  title: string;
  items: MarketIndexContributionItem[];
  tone: string;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-slate-500">
        {title}
      </div>
      <div className="overflow-hidden border border-slate-200">
        {items.length > 0 ? (
          items.map((item) => (
            <div
              key={`${title}-${item.stock_id}`}
              className="grid grid-cols-[34px_minmax(0,1fr)_82px_88px] items-center border-b border-slate-100 px-3 py-2 text-xs last:border-b-0"
            >
              <div className="text-slate-500">#{item.rank}</div>
              <div className="min-w-0">
                <div className="truncate font-semibold text-slate-950">
                  {item.stock_id} {item.stock_name ?? ""}
                </div>
                <div className="mt-0.5 text-slate-500">
                  {formatPrice(item.close)} / {formatPct(item.change_pct)}
                </div>
              </div>
              <div className={`text-right font-bold ${tone}`}>
                {formatContributionPoint(item.contribution_points)}
              </div>
              <div className="text-right text-slate-600">
                {formatTradeValueYi(item.trade_value)}
              </div>
            </div>
          ))
        ) : (
          <div className="px-3 py-8 text-center text-sm text-slate-500">尚無資料</div>
        )}
      </div>
    </div>
  );
}

function IndexContributionRanking({
  contributions,
  loadState,
}: {
  contributions: MarketIndexContributionResponse | null;
  loadState: LoadState;
}) {
  return (
    <div className="border-b border-slate-200 px-5 py-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            Contribution
          </div>
          <div className="mt-1 text-base font-bold text-slate-950">個股貢獻排行</div>
        </div>
        <div className="text-right text-xs text-slate-500">
          {loadState === "loading"
            ? "讀取中"
            : contributions?.trade_date
              ? `${contributions.trade_date} · 點數估算`
              : "點數估算"}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ContributionColumn
          title="正貢獻"
          items={contributions?.positive ?? []}
          tone="text-red-600"
        />
        <ContributionColumn
          title="負貢獻"
          items={contributions?.negative ?? []}
          tone="text-emerald-600"
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
        "omi-data-tab flex h-11 min-w-0 flex-1 items-center justify-center gap-2 border-r border-slate-200 text-sm font-semibold transition last:border-r-0",
        active
          ? "omi-data-tab-active bg-white text-slate-950"
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

function DataPanelLoadingState({ message }: { message: string }) {
  return (
    <div className="omi-tab-panel border border-slate-200 bg-white px-4 py-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div className="inline-flex min-w-0 items-center gap-2 text-sm font-semibold text-slate-700">
          <span className="truncate">{message}</span>
          <LoadingDots label={message} />
        </div>
        <div className="h-1.5 w-20 overflow-hidden bg-slate-100">
          <div className="omi-loading-bar h-full w-1/2 bg-slate-900" />
        </div>
      </div>
      <div className="space-y-3">
        <div className="omi-skeleton h-3 w-2/3" />
        <div className="grid grid-cols-3 gap-3">
          <div className="omi-skeleton h-16" />
          <div className="omi-skeleton h-16" />
          <div className="omi-skeleton h-16" />
        </div>
        <div className="omi-skeleton h-44" />
      </div>
    </div>
  );
}

function DataPanelRefreshRail({ message }: { message: string | null }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-10">
      <div className="h-0.5 overflow-hidden bg-slate-100">
        <div className="omi-loading-bar h-full w-1/3 bg-red-700" />
      </div>
      {message ? (
        <div className="absolute right-0 top-2 max-w-[70%] truncate bg-white/90 px-2 py-1 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200">
          {message}
        </div>
      ) : null}
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
  let hasStarted = false;

  return points
    .map((point, index) => {
      const value = point[valueKey];
      if (value === null || value === undefined || Number.isNaN(value)) return null;

      const x = chartX(index, points.length, left, width);
      const y = chartY(value, scale.min, scale.max, top, height);
      const command = hasStarted ? "L" : "M";
      hasStarted = true;
      return `${command} ${x.toFixed(2)} ${y.toFixed(2)}`;
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
  let hasStarted = false;

  return points
    .map((point, index) => {
      const value = getValue(point);
      if (value === null || value === undefined || Number.isNaN(value)) return null;

      const x = chartX(index, points.length, left, width);
      const y = chartY(value, scale.min, scale.max, top, height);
      const command = hasStarted ? "L" : "M";
      hasStarted = true;
      return `${command} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

function chartEventViewX(event: ReactMouseEvent<SVGSVGElement>, viewWidth: number) {
  const svg = event.currentTarget;
  const screenMatrix = typeof svg.getScreenCTM === "function" ? svg.getScreenCTM() : null;

  if (screenMatrix && typeof DOMPoint !== "undefined") {
    return new DOMPoint(event.clientX, event.clientY).matrixTransform(screenMatrix.inverse()).x;
  }

  const rect = svg.getBoundingClientRect();
  if (rect.width <= 0) return 0;

  return ((event.clientX - rect.left) / rect.width) * viewWidth;
}

function nearestChartIndex(
  event: ReactMouseEvent<SVGSVGElement>,
  pointCount: number,
  left: number,
  width: number,
  viewWidth: number
) {
  if (pointCount <= 1) return 0;

  const viewX = chartEventViewX(event, viewWidth);
  const clampedX = Math.max(left, Math.min(left + width, viewX));
  const ratio = (clampedX - left) / width;
  return Math.max(0, Math.min(pointCount - 1, Math.round(ratio * (pointCount - 1))));
}

function tooltipX(x: number, tooltipWidth: number, viewWidth: number) {
  const padding = 8;
  const gap = 16;
  const rightX = x + gap;

  if (rightX + tooltipWidth <= viewWidth - padding) {
    return rightX;
  }

  return Math.max(padding, x - tooltipWidth - gap);
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
  activeDate,
  showXAxisLabels = false,
  onHoverPointChange,
}: {
  points: InstitutionalSeriesPoint[];
  title: string;
  netKey: InstitutionalNetKey;
  cumulativeKey: InstitutionalCumulativeKey;
  activeDate?: string | null;
  showXAxisLabels?: boolean;
  onHoverPointChange?: (point: InstitutionalSeriesPoint | null) => void;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const chartPoints = points;
  const viewWidth = 860;
  const viewHeight = showXAxisLabels ? 150 : 126;
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
  const activeIndex = activeDate
    ? chartPoints.findIndex((point) => point.date === activeDate)
    : -1;
  const guideIndex = hoverIndex ?? (activeIndex >= 0 ? activeIndex : null);
  const guideX =
    guideIndex === null ? null : chartX(guideIndex, chartPoints.length, left, width);
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
        className={showXAxisLabels ? "h-[150px] w-full" : "h-[126px] w-full"}
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, chartPoints.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
          onHoverPointChange?.(chartPoints[nextIndex] ?? null);
        }}
        onMouseLeave={() => {
          setHoverIndex(null);
          onHoverPointChange?.(null);
        }}
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
        {showXAxisLabels ? (
          <>
            <text x={left} y={top + height + 24} className="fill-slate-500 text-[10px]">
              {formatMonthDay(chartPoints[0]?.date)}
            </text>
            <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-slate-500 text-[10px]">
              {formatMonthDay(chartPoints[chartPoints.length - 1]?.date)}
            </text>
          </>
        ) : null}
        {guideX !== null ? (
          <g pointerEvents="none">
            <line
              x1={guideX}
              x2={guideX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
          </g>
        ) : null}
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
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
            {showXAxisLabels ? (
              <>
                <rect x={hoverX - 28} y={top + height + 28} width={56} height={20} rx={3} fill="#6b7280" />
                <text x={hoverX} y={top + height + 42} textAnchor="middle" className="fill-white text-[11px] font-semibold">
                  {formatMonthDay(hoverPoint.date)}
                </text>
              </>
            ) : null}
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
  marketIndexSummary,
  onChartFocusModeChange,
}: Props) {
  const [timeframe, setTimeframe] = useState<Timeframe>("daily");
  const [indicatorMenuOpen, setIndicatorMenuOpen] = useState(false);
  const [chartFocusMode, setChartFocusMode] = useState(false);
  const [professionalTimeframe, setProfessionalTimeframe] =
    useState<ProfessionalTimeframe>("daily");
  const [professionalChartStyle, setProfessionalChartStyle] =
    useState<ProfessionalChartStyle>("candlestick");
  const [chartIndicators, setChartIndicators] =
    useState<IndicatorSettings>(defaultIndicators);
  const [chartDrawingTool, setChartDrawingTool] = useState<ChartDrawingTool>("cursor");
  const [selectedChartDrawingId, setSelectedChartDrawingId] = useState<string | null>(null);
  const [chartDrawingState, setChartDrawingState] = useState<ChartDrawingStorageState>({
    key: "",
    drawings: [],
  });
  const [chartDrawingHistoryState, setChartDrawingHistoryState] =
    useState<ChartDrawingHistoryState>({
      key: "",
      past: [],
      future: [],
    });
  const chartDrawingKey = chartDrawingStorageKey(stockId, professionalTimeframe);
  const chartDrawings =
    chartDrawingState.key === chartDrawingKey
      ? chartDrawingState.drawings
      : loadChartDrawings(chartDrawingKey);
  const chartDrawingHistory =
    chartDrawingHistoryState.key === chartDrawingKey
      ? chartDrawingHistoryState
      : { key: chartDrawingKey, past: [], future: [] };
  const canUndoChartDrawing = chartDrawingHistory.past.length > 0;
  const canRedoChartDrawing = chartDrawingHistory.future.length > 0;
  const activeSelectedChartDrawingId = chartDrawings.some(
    (drawing) => drawing.id === selectedChartDrawingId
  )
    ? selectedChartDrawingId
    : null;
  const [intradayIndicators, setIntradayIndicators] =
    useState<IntradayIndicatorSettings>(defaultIntradayIndicators);
  const [activeIndicatorTemplate, setActiveIndicatorTemplate] =
    useState<IndicatorTemplateKey | null>("basic");
  const [indicatorParameters, setIndicatorParameters] =
    useState<IndicatorParameters>(defaultIndicatorParameters);
  const [chartData, setChartData] = useState<ChartPoint[]>(initialChartData);
  const [chartStockId, setChartStockId] = useState<string | null>(stockId);
  const [chartTimeframe, setChartTimeframe] = useState<ChartTimeframe>("daily");
  const [todayTrend, setTodayTrend] = useState<IntradayTrendPoint[]>([]);
  const [todayPreviousClose, setTodayPreviousClose] = useState<number | null>(null);
  const [todaySource, setTodaySource] = useState("unavailable");
  const [todayUpdatedAt, setTodayUpdatedAt] = useState<string | null>(null);
  const [professionalIntradayData, setProfessionalIntradayData] = useState<ChartPoint[]>([]);
  const [professionalIntradayStockId, setProfessionalIntradayStockId] = useState<string | null>(
    null
  );
  const [professionalIntradayInterval, setProfessionalIntradayInterval] =
    useState<ProfessionalIntradayTimeframe | null>(null);
  const [professionalIntradayFallbackActive, setProfessionalIntradayFallbackActive] =
    useState(false);
  const [indicatorData, setIndicatorData] =
    useState<StockIndicatorPoint[]>(initialIndicatorData);
  const [institutional, setInstitutional] = useState<InstitutionalTradeDailyRead | null>(null);
  const [institutionalHistory, setInstitutionalHistory] = useState<InstitutionalTradeDailyRead[]>([]);
  const [margin, setMargin] = useState<MarginTradingDailyRead | null>(null);
  const [brokerBranchSummary, setBrokerBranchSummary] =
    useState<BrokerBranchTradeDailySummaryRead | null>(null);
  const [shareholding, setShareholding] = useState<ShareholdingDistributionWeeklyRead[]>([]);
  const [chipCoverage, setChipCoverage] = useState<StockChipCoverageRead | null>(null);
  const [monthlyRevenue, setMonthlyRevenue] = useState<MonthlyRevenueRead | null>(null);
  const [monthlyRevenueHistory, setMonthlyRevenueHistory] = useState<MonthlyRevenueRead[]>([]);
  const [financialMetric, setFinancialMetric] =
    useState<FinancialMetricQuarterlyRead | null>(null);
  const [financialMetricHistory, setFinancialMetricHistory] = useState<FinancialMetricQuarterlyRead[]>([]);
  const [stockInfo, setStockInfo] = useState<StockMasterRead | null>(null);
  const [institutionalHoldingRatio, setInstitutionalHoldingRatio] =
    useState<InstitutionalHoldingRatioRead | null>(null);
  const [activeDataTab, setActiveDataTab] = useState<DataPanelTab>("chips");
  const [dataPanelLoading, setDataPanelLoading] = useState<DataPanelTab | null>(null);
  const [dataPanelMessage, setDataPanelMessage] = useState<string | null>(null);
  const [institutionalHoverDate, setInstitutionalHoverDate] = useState<string | null>(null);
  const [branchTableSide, setBranchTableSide] = useState<BranchTableSide>("buy");
  const [branchDays, setBranchDays] = useState(1);
  const [largeHolderLots, setLargeHolderLots] = useState(1000);
  const [smallHolderLots, setSmallHolderLots] = useState(100);
  const [revenueView, setRevenueView] = useState<RevenueView>("monthly");
  const [revenueYear, setRevenueYear] = useState<number | null>(null);
  const [earningsView, setEarningsView] = useState<EarningsView>("quarterly");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [chartHistoryMessage, setChartHistoryMessage] = useState<string | null>(null);
  const [backendTechnicalReport, setBackendTechnicalReport] =
    useState<StockTechnicalReportRead | null>(null);
  const [overnightImpact, setOvernightImpact] =
    useState<OvernightImpactRead | null>(null);
  const [overnightImpactLoadState, setOvernightImpactLoadState] =
    useState<LoadState>("idle");
  const [indexList, setIndexList] = useState<MarketIndexListItem[]>([]);
  const [indexListLoadState, setIndexListLoadState] = useState<LoadState>("idle");
  const [indexContributions, setIndexContributions] =
    useState<MarketIndexContributionResponse | null>(null);
  const [indexContributionLoadState, setIndexContributionLoadState] =
    useState<LoadState>("idle");
  const [marketChip, setMarketChip] = useState<MarketChipDaily | null>(null);
  const [marketChipLoadState, setMarketChipLoadState] = useState<LoadState>("idle");
  const finalIntradayRefreshDate = useRef<string | null>(null);
  const activeStockIdRef = useRef<string | null>(stockId);
  const activeDataTabRef = useRef<DataPanelTab>(activeDataTab);
  const branchDaysRef = useRef(branchDays);
  const dataPanelRequestKeyRef = useRef<string | null>(null);
  const dataPanelResolvedKeysRef = useRef<Set<string>>(new Set());
  const branchSummaryCacheRef = useRef<Map<string, BrokerBranchTradeDailySummaryRead>>(new Map());
  const chartHistoryBackfillKeysRef = useRef<Set<string>>(new Set());
  const indexProduct = stockId ? indexProducts.get(stockId) ?? null : null;
  const isIndexProduct = indexProduct !== null;
  const effectiveTimeframe = timeframe;
  const availableTimeframes = isIndexProduct ? indexTimeframes : allTimeframes;
  const indexMarket = indexProduct?.market ?? null;

  useEffect(() => {
    onChartFocusModeChange?.(chartFocusMode);
  }, [chartFocusMode, onChartFocusModeChange]);
  const indexId = indexProduct?.indexId ?? null;

  useEffect(() => {
    activeStockIdRef.current = stockId;
  }, [stockId]);

  useEffect(() => {
    activeDataTabRef.current = activeDataTab;
  }, [activeDataTab]);

  useEffect(() => {
    branchDaysRef.current = branchDays;
  }, [branchDays]);

  useEffect(() => {
    if (!stockId || isIndexProduct) {
      return;
    }

    let cancelled = false;
    const currentStockId = stockId;

    async function loadOvernightImpact() {
      setOvernightImpact(null);
      setOvernightImpactLoadState("loading");

      try {
        const response = await fetchJson<OvernightImpactRead>(
          `/api/market/overnight-impact/${currentStockId}`
        );

        if (cancelled) return;

        setOvernightImpact(response);
        setOvernightImpactLoadState("success");
      } catch {
        if (cancelled) return;

        setOvernightImpact(null);
        setOvernightImpactLoadState("error");
      }
    }

    void loadOvernightImpact();

    return () => {
      cancelled = true;
    };
  }, [isIndexProduct, stockId]);

  useEffect(() => {
    if (!isIndexProduct || !indexMarket) {
      return;
    }

    let cancelled = false;
    const market = indexMarket;

    async function loadIndexList() {
      setIndexList([]);
      setIndexListLoadState("loading");

      try {
        const response = await fetchJson<MarketIndexListResponse>(
          "/api/market/indices/list",
          {
            market,
            limit: 80,
          }
        );

        if (cancelled) return;

        setIndexList(response.items);
        setIndexListLoadState("success");
      } catch {
        if (cancelled) return;

        setIndexList([]);
        setIndexListLoadState("error");
      }
    }

    void loadIndexList();

    return () => {
      cancelled = true;
    };
  }, [indexMarket, isIndexProduct]);

  useEffect(() => {
    if (!isIndexProduct || !indexId) {
      return;
    }

    let cancelled = false;
    const currentIndexId = indexId;

    async function loadIndexContributions() {
      setIndexContributions(null);
      setIndexContributionLoadState("loading");

      try {
        const response = await fetchJson<MarketIndexContributionResponse>(
          `/api/market/indices/${currentIndexId}/contributions`,
          { limit: 20 }
        );

        if (cancelled) return;

        setIndexContributions(response);
        setIndexContributionLoadState("success");
      } catch {
        if (cancelled) return;

        setIndexContributions(null);
        setIndexContributionLoadState("error");
      }
    }

    void loadIndexContributions();

    return () => {
      cancelled = true;
    };
  }, [indexId, isIndexProduct]);

  useEffect(() => {
    if (!isIndexProduct || !indexId) {
      return;
    }

    let cancelled = false;
    const currentIndexId = indexId;

    async function loadMarketChip() {
      setMarketChip(null);
      setMarketChipLoadState("loading");

      try {
        const response = await fetchJson<MarketChipDaily>(
          "/api/market/market-chips/latest",
          {
            index_id: currentIndexId,
            ensure_latest: true,
          }
        );

        if (cancelled) return;

        setMarketChip(response);
        setMarketChipLoadState("success");
      } catch {
        if (cancelled) return;

        setMarketChip(null);
        setMarketChipLoadState("error");
      }
    }

    void loadMarketChip();

    return () => {
      cancelled = true;
    };
  }, [indexId, isIndexProduct]);

  const currentStockInfoId = stockInfo?.stock_id ?? null;
  const currentStockInfoMarket = stockInfo?.market ?? null;

  function toggleChartIndicator(key: IndicatorKey) {
    setActiveIndicatorTemplate(null);
    setChartIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  function toggleIntradayIndicator(key: IntradayIndicatorKey) {
    setIntradayIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  function handleProfessionalTimeframeChange(nextTimeframe: ProfessionalTimeframe) {
    setProfessionalTimeframe(nextTimeframe);
    setIndicatorMenuOpen(false);

    if (!isProfessionalIntradayTimeframe(nextTimeframe)) {
      setTimeframe(nextTimeframe);
    }
  }

  function applyIndicatorTemplate(templateKey: IndicatorTemplateKey) {
    const template = indicatorTemplates.find((item) => item.key === templateKey);

    if (!template) return;

    setActiveIndicatorTemplate(template.key);
    setChartIndicators(template.indicators);
    setIndicatorParameters({
      ...defaultIndicatorParameters,
      ...(template.parameters ?? {}),
    });
  }

  function updateIndicatorParameter(
    key: keyof IndicatorParameters,
    value: string,
    min: number,
    max: number
  ) {
    const parsed = Number(value);

    if (!Number.isFinite(parsed)) return;

    setActiveIndicatorTemplate(null);
    setIndicatorParameters((current) => ({
      ...current,
      [key]: Math.max(min, Math.min(max, parsed)),
    }));
  }

  const storeChartDrawings = useCallback((drawingsToSave: ChartDrawing[]) => {
    setChartDrawingState({
      key: chartDrawingKey,
      drawings: drawingsToSave,
    });
    saveChartDrawings(chartDrawingKey, drawingsToSave);
  }, [chartDrawingKey]);

  function updateChartDrawings(
    nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
    options: { recordHistory?: boolean } = {}
  ) {
    const nextDrawings =
      typeof nextValue === "function" ? nextValue(chartDrawings) : nextValue;
    const drawingsToSave = nextDrawings.slice(-200);

    if (serializeChartDrawings(chartDrawings) === serializeChartDrawings(drawingsToSave)) {
      return;
    }

    if (options.recordHistory !== false) {
      const currentPast =
        chartDrawingHistoryState.key === chartDrawingKey ? chartDrawingHistoryState.past : [];

      setChartDrawingHistoryState({
        key: chartDrawingKey,
        past: [...currentPast, chartDrawings].slice(-50),
        future: [],
      });
    }

    storeChartDrawings(drawingsToSave);
  }

  const undoChartDrawing = useCallback(() => {
    if (!canUndoChartDrawing) return;

    const past = chartDrawingHistory.past;
    const previousDrawings = past[past.length - 1];

    if (!previousDrawings) return;

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: past.slice(0, -1),
      future: [chartDrawings, ...chartDrawingHistory.future].slice(0, 50),
    });
    storeChartDrawings(previousDrawings);
    setSelectedChartDrawingId(null);
  }, [
    canUndoChartDrawing,
    chartDrawingHistory.future,
    chartDrawingHistory.past,
    chartDrawingKey,
    chartDrawings,
    storeChartDrawings,
  ]);

  const redoChartDrawing = useCallback(() => {
    if (!canRedoChartDrawing) return;

    const nextDrawings = chartDrawingHistory.future[0];

    if (!nextDrawings) return;

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: [...chartDrawingHistory.past, chartDrawings].slice(-50),
      future: chartDrawingHistory.future.slice(1),
    });
    storeChartDrawings(nextDrawings);
    setSelectedChartDrawingId(null);
  }, [
    canRedoChartDrawing,
    chartDrawingHistory.future,
    chartDrawingHistory.past,
    chartDrawingKey,
    chartDrawings,
    storeChartDrawings,
  ]);

  function deleteSelectedChartDrawing() {
    if (!activeSelectedChartDrawingId) return;

    updateChartDrawings((current) =>
      current.filter((drawing) => drawing.id !== activeSelectedChartDrawingId)
    );
    setSelectedChartDrawingId(null);
  }

  function clearChartDrawings() {
    if (chartDrawings.length === 0) return;
    if (!window.confirm("清除目前週期的所有畫線？")) return;

    updateChartDrawings([]);
    setSelectedChartDrawingId(null);
  }

  useEffect(() => {
    if (!chartFocusMode) return;

    function handleChartDrawingHistoryKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();

      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;
      if (!event.ctrlKey && !event.metaKey) return;

      const key = event.key.toLowerCase();

      if (key === "z" && !event.shiftKey) {
        if (!canUndoChartDrawing) return;

        event.preventDefault();
        undoChartDrawing();
        return;
      }

      if (key === "y" || (key === "z" && event.shiftKey)) {
        if (!canRedoChartDrawing) return;

        event.preventDefault();
        redoChartDrawing();
      }
    }

    window.addEventListener("keydown", handleChartDrawingHistoryKeyDown);

    return () => window.removeEventListener("keydown", handleChartDrawingHistoryKeyDown);
  }, [
    canRedoChartDrawing,
    canUndoChartDrawing,
    chartFocusMode,
    redoChartDrawing,
    undoChartDrawing,
  ]);

  useEffect(() => {
    dataPanelResolvedKeysRef.current.clear();
    branchSummaryCacheRef.current.clear();
    chartHistoryBackfillKeysRef.current.clear();

    if (!stockId) {
      const timer = window.setTimeout(() => {
        setChartData([]);
        setChartStockId(null);
        setChartTimeframe("daily");
        setTodayTrend([]);
        setTodayPreviousClose(null);
        setTodaySource("unavailable");
        setTodayUpdatedAt(null);
        setIndicatorData([]);
        setInstitutional(null);
        setInstitutionalHistory([]);
        setMargin(null);
        setBrokerBranchSummary(null);
        setShareholding([]);
        setChipCoverage(null);
        setMonthlyRevenue(null);
        setMonthlyRevenueHistory([]);
        setFinancialMetric(null);
        setFinancialMetricHistory([]);
        setStockInfo(null);
        setInstitutionalHoldingRatio(null);
        setActiveDataTab("chips");
        setDataPanelLoading(null);
        setDataPanelMessage(null);
        setInstitutionalHoverDate(null);
        setBranchDays(1);
        setRevenueYear(null);
        setLoadState("idle");
        setErrorMessage(null);
        setChartHistoryMessage(null);
      }, 0);

      return () => window.clearTimeout(timer);
    }

    if (isIndexProduct) {
      const timer = window.setTimeout(() => {
        setInstitutional(null);
        setInstitutionalHistory([]);
        setMargin(null);
        setBrokerBranchSummary(null);
        setShareholding([]);
        setMonthlyRevenue(null);
        setMonthlyRevenueHistory([]);
        setFinancialMetric(null);
        setFinancialMetricHistory([]);
        setStockInfo(null);
        setInstitutionalHoldingRatio(null);
        setActiveDataTab("chips");
        setDataPanelLoading(null);
        setDataPanelMessage(null);
        setInstitutionalHoverDate(null);
        setBranchDays(1);
        setRevenueYear(null);
        setChartHistoryMessage(null);
      }, 0);

      return () => window.clearTimeout(timer);
    }

    let cancelled = false;
    const resetTimer = window.setTimeout(() => {
      if (cancelled) return;

      setInstitutional(null);
      setInstitutionalHistory([]);
      setMargin(null);
      setBrokerBranchSummary(null);
      setShareholding([]);
      setChipCoverage(null);
      setMonthlyRevenue(null);
      setMonthlyRevenueHistory([]);
      setFinancialMetric(null);
      setFinancialMetricHistory([]);
      setStockInfo(null);
      setInstitutionalHoldingRatio(null);
      setDataPanelLoading(null);
      setDataPanelMessage(null);
      setInstitutionalHoverDate(null);
      setBranchDays(1);
      setRevenueYear(null);
      setChartHistoryMessage(null);
    }, 0);

    async function loadBasicDetail() {
      try {
        const [institutionalData, stockData] = await Promise.all([
          fetchOptional<InstitutionalTradeDailyRead>(
            `/api/market/institutional/${stockId}/latest`,
            { ensure_daily: false }
          ),
          fetchOptional<StockMasterRead>(`/api/stocks/${stockId}`),
        ]);

        if (cancelled) return;

        setInstitutional(institutionalData);
        setStockInfo(stockData);
      } catch {
        if (!cancelled) {
          setInstitutional(null);
          setStockInfo(null);
        }
      }
    }

    void loadBasicDetail();

    return () => {
      cancelled = true;
      window.clearTimeout(resetTimer);
    };
  }, [isIndexProduct, stockId]);

  useEffect(() => {
    if (!stockId) return;

    const effectStockId = stockId;
    let cancelled = false;
    let intradayTimer: number | undefined;
    let intradayRequestInFlight = false;
    const shouldLoadProfessionalIntraday =
      chartFocusMode &&
      !isIndexProduct &&
      isProfessionalIntradayTimeframe(professionalTimeframe);

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
          isIndexProduct
            ? `/api/market/indices/${stockId}/intraday`
            : `/api/market/intraday/${stockId}`
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

    async function loadProfessionalIntradayHistory() {
      if (!isProfessionalIntradayTimeframe(professionalTimeframe)) return;

      setLoadState("loading");
      setErrorMessage(null);
      setProfessionalIntradayData([]);
      setProfessionalIntradayStockId(effectStockId);
      setProfessionalIntradayInterval(professionalTimeframe);
      setProfessionalIntradayFallbackActive(false);

      try {
        const history = await fetchJson<IntradayHistoryResponse>(
          `/api/market/intraday/${effectStockId}/history`,
          {
            interval: professionalTimeframe,
            range: "auto",
            refresh: true,
          }
        );

        if (cancelled || activeStockIdRef.current !== effectStockId) return;

        if (history.points.length === 0) {
          await loadTodayTrend(false);

          if (cancelled || activeStockIdRef.current !== effectStockId) return;

          setProfessionalIntradayFallbackActive(true);
          setErrorMessage("歷史分鐘線暫無資料，先以今日盤中資料顯示");
          return;
        }

        setProfessionalIntradayData(history.points);
        setProfessionalIntradayStockId(effectStockId);
        setProfessionalIntradayInterval(professionalTimeframe);
        setProfessionalIntradayFallbackActive(false);
        setLoadState("success");
        setErrorMessage(null);
      } catch (error) {
        if (cancelled || activeStockIdRef.current !== effectStockId) return;

        setProfessionalIntradayData([]);
        setProfessionalIntradayStockId(effectStockId);
        setProfessionalIntradayInterval(professionalTimeframe);
        await loadTodayTrend(false);

        if (cancelled || activeStockIdRef.current !== effectStockId) return;

        setProfessionalIntradayFallbackActive(true);
        setErrorMessage(
          error instanceof Error
            ? `歷史分鐘線讀取失敗，暫以今日盤中資料顯示：${error.message}`
            : "歷史分鐘線讀取失敗，暫以今日盤中資料顯示"
        );
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

    async function resolveStockMarketForBackfill(targetStockId: string) {
      if (currentStockInfoId === targetStockId) {
        return currentStockInfoMarket;
      }

      const stockData = await fetchOptional<StockMasterRead>(`/api/stocks/${targetStockId}`);

      if (stockData && !cancelled && activeStockIdRef.current === targetStockId) {
        setStockInfo(stockData);
      }

      return stockData?.market ?? null;
    }

    async function maybeQueueChartHistoryBackfill(
      targetStockId: string,
      requestedTimeframe: TaiwanChartTimeframe,
      ohlc: OhlcChartResponse
    ) {
      const requirement = getTaiwanChartHistoryRequirement(requestedTimeframe);

      if (ohlc.point_count >= requirement.minPoints) {
        setChartHistoryMessage(null);
        return;
      }

      const market = await resolveStockMarketForBackfill(targetStockId);
      const backfillPath = taiwanDailyPriceBackfillPath(targetStockId, market);

      if (!backfillPath) {
        if (!cancelled && activeStockIdRef.current === targetStockId) {
          setChartHistoryMessage(
            `${requirement.label}資料深度不足，目前市場 ${market ?? "-"} 尚未支援自動補齊`
          );
        }
        return;
      }

      const endDate = ohlc.to_date.slice(0, 10);
      const startDate = shiftIsoDate(endDate, -requirement.lookbackDays);
      const backfillKey = `${targetStockId}:${requestedTimeframe}:${startDate}:${endDate}`;

      if (chartHistoryBackfillKeysRef.current.has(backfillKey)) return;

      chartHistoryBackfillKeysRef.current.add(backfillKey);

      if (!cancelled && activeStockIdRef.current === targetStockId) {
        setChartHistoryMessage(
          `${requirement.label}目前只有 ${ohlc.point_count} 根，背景補歷史資料中`
        );
      }

      try {
        await requestBackfillJob(
          backfillPath,
          { method: "POST" },
          {
            start_date: startDate,
            end_date: endDate,
            sleep_seconds: 0.05,
            skip_existing_months: true,
          },
          {
            intervalMs: 2000,
            timeoutMs: 900000,
            onUpdate: (job) => {
              if (!cancelled && activeStockIdRef.current === targetStockId) {
                setChartHistoryMessage(formatPanelJobProgress(requirement.label, job));
              }
            },
          }
        );

        const refreshedOhlc = await fetchJson<OhlcChartResponse>(
          `/api/market/ohlc/${targetStockId}`,
          {
            timeframe: requestedTimeframe,
            bars: chartBarsByTimeframe[requestedTimeframe],
            ensure_history: false,
          }
        );
        const refreshedIndicators = await fetchJson<StockIndicatorPoint[]>(
          `/api/market/indicators/${targetStockId}/daily`,
          {
            limit: dailyIndicatorLimit,
            ma_windows: "5,20,60",
            volume_ma_windows: "5,20",
          }
        );

        if (cancelled || activeStockIdRef.current !== targetStockId) return;

        setChartData(refreshedOhlc.points);
        setIndicatorData(refreshedIndicators);
        setChartStockId(targetStockId);
        setChartTimeframe(requestedTimeframe);
        setChartHistoryMessage(
          refreshedOhlc.point_count >= requirement.minPoints
            ? `${requirement.label}歷史資料已補齊`
            : `${requirement.label}歷史資料已補齊，目前可用 ${refreshedOhlc.point_count} 根`
        );
      } catch {
        if (cancelled || activeStockIdRef.current !== targetStockId) return;

        setChartHistoryMessage(`${requirement.label}歷史資料背景補齊失敗，詳見左側更新狀態`);
      }
    }

    async function loadChart() {
      if (shouldLoadProfessionalIntraday) {
        await loadProfessionalIntradayHistory();
        return;
      }

      if (effectiveTimeframe === "today") {
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
        const requestedStockId = effectStockId;
        const requestedTimeframe = effectiveTimeframe as TaiwanChartTimeframe;
        const chartBars = chartBarsByTimeframe[requestedTimeframe];
        const ohlc = await fetchJson<OhlcChartResponse>(
          isIndexProduct
            ? `/api/market/indices/${requestedStockId}/ohlc`
            : `/api/market/ohlc/${requestedStockId}`,
          {
            timeframe: requestedTimeframe,
            bars: chartBars,
            ensure_history: false,
          }
        );
        const indicators =
          isIndexProduct
            ? []
            : await fetchJson<StockIndicatorPoint[]>(
                `/api/market/indicators/${requestedStockId}/daily`,
                {
                  limit: dailyIndicatorLimit,
                  ma_windows: "5,20,60",
                  volume_ma_windows: "5,20",
                }
              );

        if (cancelled) return;

        setChartData(ohlc.points);
        setIndicatorData(indicators);
        setChartStockId(requestedStockId);
        setChartTimeframe(requestedTimeframe);
        setLoadState("success");

        if (!isIndexProduct) {
          void maybeQueueChartHistoryBackfill(requestedStockId, requestedTimeframe, ohlc);
        }
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
  }, [
    chartFocusMode,
    currentStockInfoId,
    currentStockInfoMarket,
    effectiveTimeframe,
    isIndexProduct,
    professionalTimeframe,
    stockId,
  ]);

  useEffect(() => {
    if (!stockId || isIndexProduct || !["today", "daily"].includes(effectiveTimeframe)) {
      return;
    }

    let cancelled = false;
    const requestedStockId = stockId;
    const requestedTimeframe = effectiveTimeframe as "today" | "daily";

    async function loadBackendTechnicalReport() {
      try {
        const report = await fetchJson<StockTechnicalReportRead>(
          `/api/market/technical/${requestedStockId}`,
          {
            timeframe: requestedTimeframe,
            include_intraday: requestedTimeframe === "today",
          }
        );

        if (cancelled || activeStockIdRef.current !== requestedStockId) return;

        setBackendTechnicalReport(report);
      } catch {
        if (cancelled || activeStockIdRef.current !== requestedStockId) return;

        setBackendTechnicalReport(null);
      }
    }

    void loadBackendTechnicalReport();

    return () => {
      cancelled = true;
    };
  }, [effectiveTimeframe, isIndexProduct, stockId, todayUpdatedAt]);

  const indicatorForTimeframe = useMemo(() => {
    if (effectiveTimeframe === "daily") return indicatorData.slice(-180);
    return [];
  }, [effectiveTimeframe, indicatorData]);

  const latestIndicator = indicatorData[indicatorData.length - 1] ?? null;
  const latestChart = chartData[chartData.length - 1] ?? null;
  const previousChart = chartData[chartData.length - 2] ?? null;
  const currentChartReady =
    effectiveTimeframe !== "today" &&
    chartStockId === stockId &&
    chartTimeframe === effectiveTimeframe;
  const canUseFocusedKLine = currentChartReady && chartData.length > 0;
  const latestToday = todayTrend[todayTrend.length - 1] ?? null;
  const todayStats = useMemo(() => summarizeIntradayPoints(todayTrend), [todayTrend]);
  const professionalIsIntraday = isProfessionalIntradayTimeframe(professionalTimeframe);
  const professionalChartData = useMemo<ChartPoint[]>(() => {
    if (!isProfessionalIntradayTimeframe(professionalTimeframe)) return chartData;

    const hasMatchingHistory =
      professionalIntradayStockId === stockId &&
      professionalIntradayInterval === professionalTimeframe &&
      professionalIntradayData.length > 0;

    if (hasMatchingHistory) return professionalIntradayData;

    const canUseTodayFallback =
      professionalIntradayFallbackActive &&
      professionalIntradayStockId === stockId &&
      professionalIntradayInterval === professionalTimeframe;

    if (!canUseTodayFallback) return [];

    return aggregateProfessionalIntradayBars(
      todayTrend,
      professionalIntradayMinutes[professionalTimeframe]
    );
  }, [
    chartData,
    professionalIntradayData,
    professionalIntradayFallbackActive,
    professionalIntradayInterval,
    professionalIntradayStockId,
    professionalTimeframe,
    stockId,
    todayTrend,
  ]);
  const professionalChartReady =
    chartFocusMode &&
    professionalChartData.length > 0 &&
    (professionalIsIntraday || currentChartReady);
  const professionalTimeframeLabel =
    professionalTimeframeOptions.find((option) => option.key === professionalTimeframe)?.label ??
    timeframeLabels.daily;
  const latestProfessionalChart = professionalChartData[professionalChartData.length - 1] ?? null;
  const latestClose =
    effectiveTimeframe === "today"
      ? latestToday?.price ?? null
      : latestIndicator?.close ?? latestChart?.close ?? null;
  const dailyPreviousClose =
    latestIndicator?.close !== null &&
    latestIndicator?.close !== undefined &&
    latestIndicator?.change !== null &&
    latestIndicator?.change !== undefined
      ? latestIndicator.close - latestIndicator.change
      : null;
  const todayReferenceClose = todayPreviousClose ?? dailyPreviousClose;
  const chartChangePct =
    latestChart?.close !== null &&
    latestChart?.close !== undefined &&
    previousChart?.close !== null &&
    previousChart?.close !== undefined &&
    previousChart.close !== 0
      ? ((latestChart.close - previousChart.close) / previousChart.close) * 100
      : null;
  const chartChange =
    latestChart?.close !== null &&
    latestChart?.close !== undefined &&
    previousChart?.close !== null &&
    previousChart?.close !== undefined
      ? latestChart.close - previousChart.close
      : null;
  const latestChange =
    effectiveTimeframe === "today" && latestToday && todayReferenceClose
      ? latestToday.price - todayReferenceClose
      : latestIndicator?.change ?? chartChange;
  const latestChangePct =
    effectiveTimeframe === "today" && latestToday && todayReferenceClose
      ? ((latestToday.price - todayReferenceClose) / todayReferenceClose) * 100
      : latestIndicator?.change_pct ?? chartChangePct;
  const professionalLatestClose =
    chartFocusMode && professionalIsIntraday
      ? latestProfessionalChart?.close ?? latestToday?.price ?? latestClose
      : latestClose;
  const professionalLatestChange =
    chartFocusMode && professionalIsIntraday && latestToday && todayReferenceClose
      ? latestToday.price - todayReferenceClose
      : latestChange;
  const professionalLatestChangePct =
    chartFocusMode && professionalIsIntraday && latestToday && todayReferenceClose
      ? ((latestToday.price - todayReferenceClose) / todayReferenceClose) * 100
      : latestChangePct;
  const professionalHeaderLimitStatus = isIndexProduct
    ? null
    : estimatedPriceLimitStatus(professionalLatestChangePct);
  const headerLimitStatus = isIndexProduct ? null : estimatedPriceLimitStatus(latestChangePct);
  const ma5 = latestIndicator?.ma?.ma5 ?? averageRecentChartValue(chartData, "close", 5);
  const ma20 = latestIndicator?.ma?.ma20 ?? averageRecentChartValue(chartData, "close", 20);
  const ma60 = latestIndicator?.ma?.ma60 ?? averageRecentChartValue(chartData, "close", 60);
  const volumeMa20 =
    latestIndicator?.volume_ma?.volume_ma20 ?? averageRecentChartValue(chartData, "volume", 20);
  const priceVsMa20 =
    latestClose !== null && ma20 !== null && ma20 !== 0
      ? ((latestClose - ma20) / ma20) * 100
      : null;
  const latestVolume =
    effectiveTimeframe === "today"
      ? todayStats.volume ?? latestToday?.volume ?? null
      : latestIndicator?.volume ?? latestChart?.volume ?? null;
  const volumeRatio = safeRatio(latestVolume, volumeMa20);
  const volumeRatioPct = volumeRatio === null ? null : (volumeRatio - 1) * 100;
  const totalInstitutionalNet = institutional?.total_institutional_net ?? null;
  const displayTime =
    effectiveTimeframe === "today" && latestToday
      ? formatDateTime(latestToday.time)
      : effectiveTimeframe === "today"
        ? "-"
        : latestIndicator?.time ?? latestChart?.time ?? "-";
  const marketIndicesById = useMemo(() => {
    return new Map(
      (marketIndexSummary?.indices ?? []).map((index) => [index.index_id, index])
    );
  }, [marketIndexSummary]);
  const taiexIndex = marketIndicesById.get("TAIEX") ?? null;
  const tpexIndex = marketIndicesById.get("TPEX") ?? null;
  const selectedIndexSnapshot =
    indexProduct?.indexId === "TPEX" ? tpexIndex : taiexIndex;
  const primaryMarketIndex =
    indexProduct?.indexId === "TPEX" || stockInfo?.market === "TPEX"
      ? tpexIndex
      : taiexIndex;
  const relativeToPrimaryIndex =
    latestChangePct !== null &&
    latestChangePct !== undefined &&
    primaryMarketIndex?.change_pct !== null &&
    primaryMarketIndex?.change_pct !== undefined
      ? latestChangePct - primaryMarketIndex.change_pct
      : null;

  const fallbackTechnicalReport = useMemo<TechnicalReport>(() => {
    const rows: TechnicalReportRow[] = [];
    const badges: TechnicalReportBadge[] = [];
    let score = 0;
    const hasCurrentChart =
      effectiveTimeframe === "today" || currentChartReady || isIndexProduct;

    function addScore(value: number) {
      score += value;
    }

    function addBadge(label: string, tone: string) {
      if (badges.some((badge) => badge.label === label)) return;
      badges.push({ label, tone });
    }

    function rowTone(value: number | null | undefined): TechnicalTone {
      if (!finiteNumber(value)) return "neutral";
      if (value > 0) return "positive";
      if (value < 0) return "negative";
      return "neutral";
    }

    function titleFor(shortLabel: string, neutralLabel: string, weakLabel: string) {
      if (score >= 3) return shortLabel;
      if (score <= -3) return weakLabel;
      return neutralLabel;
    }

    function summaryFrom(parts: string[]) {
      if (loadState === "loading") return "資料讀取中";
      const validParts = parts.filter((part) => part && part !== "資料不足");
      return validParts.length ? validParts.join("，") : "訊號資料不足";
    }

    if (effectiveTimeframe === "today" && !latestToday) {
      addBadge("等待盤中", "text-slate-600 bg-slate-100");

      return {
        title: loadState === "loading" ? "資料讀取中" : "等待盤中資料",
        summary:
          loadState === "loading"
            ? "正在取得今日盤中資料"
            : "尚未取得今日第一筆成交，日線資料暫不作盤中判斷",
        value: null,
        valueLabel: "vs 昨收",
        score: 0,
        rows: [
          {
            title: "資料狀態",
            description: "尚未取得今日第一筆成交或即時快照",
            value: "0筆",
            tone: "neutral",
          },
          {
            title: "參考基準",
            description: "今日漲跌幅將以上一交易日收盤價計算",
            value: formatPrice(todayReferenceClose),
            pulseValue: todayReferenceClose,
            tone: "neutral",
          },
        ],
        badges,
      };
    }

    if (!finiteNumber(latestClose) || !hasCurrentChart) {
      return {
        title: loadState === "loading" ? "資料讀取中" : "資料不足",
        summary: loadState === "loading" ? "正在整理技術訊號" : "尚無足夠資料產生報告",
        value: null,
        valueLabel: timeframeLabels[effectiveTimeframe],
        score: 0,
        rows: [
          {
            title: "資料狀態",
            description: hasCurrentChart ? "價格資料不足" : "等待目前週期 K 線資料",
            value: "-",
            tone: "neutral",
          },
        ],
        badges,
      };
    }

    const rsi14 = latestIndicator?.rsi?.rsi14 ?? null;
    const macdHistogram = latestIndicator?.macd?.histogram ?? null;
    const roc12 = latestIndicator?.roc?.roc12 ?? null;
    const mfi14 = latestIndicator?.mfi?.mfi14 ?? null;
    const atr14 = latestIndicator?.atr?.atr14 ?? null;
    const adx14 = latestIndicator?.adx?.adx14 ?? null;
    const plusDi14 = latestIndicator?.adx?.plus_di14 ?? null;
    const minusDi14 = latestIndicator?.adx?.minus_di14 ?? null;
    const donchianUpper20 = latestIndicator?.donchian?.upper20 ?? null;
    const donchianLower20 = latestIndicator?.donchian?.lower20 ?? null;
    const atrPct =
      finiteNumber(atr14) && latestClose !== 0 ? (atr14 / latestClose) * 100 : null;
    const donchianPositionPct =
      finiteNumber(donchianUpper20) &&
      finiteNumber(donchianLower20) &&
      donchianUpper20 !== donchianLower20
        ? ((latestClose - donchianLower20) / (donchianUpper20 - donchianLower20)) * 100
        : null;
    const latestInstitutionalNet =
      institutional?.total_institutional_net ?? totalInstitutionalNet;
    const largeHolder = latestLargeHolderSummary(shareholding, largeHolderLots);
    const marginBalanceChange =
      finiteNumber(margin?.margin_today_balance) && finiteNumber(margin?.margin_previous_balance)
        ? margin.margin_today_balance - margin.margin_previous_balance
        : null;
    const marketRelativeLabel =
      relativeToPrimaryIndex === null
        ? "資料不足"
        : relativeToPrimaryIndex > 0
          ? "強於大盤"
          : relativeToPrimaryIndex < 0
            ? "弱於大盤"
            : "同步大盤";

    if (effectiveTimeframe === "today") {
      const pointCount = todayTrend.length;
      const latestIntradayMinutes = latestToday ? getTaipeiMinutesOfDay(latestToday.time) : null;
      const minutesFromOpen = finiteNumber(latestIntradayMinutes)
        ? latestIntradayMinutes - TAIWAN_SESSION_START_MINUTES
        : null;
      const isOpeningPhase =
        !finiteNumber(minutesFromOpen) ||
        minutesFromOpen < openingObservationMinutes ||
        pointCount < openingObservationMinPoints;
      const todayOpen = todayStats.open ?? latestToday?.open ?? null;
      const priceVsOpenPct =
        finiteNumber(latestClose) && finiteNumber(todayOpen) && todayOpen !== 0
          ? ((latestClose - todayOpen) / todayOpen) * 100
          : null;
      const openingGapPct =
        finiteNumber(todayOpen) && finiteNumber(todayReferenceClose) && todayReferenceClose !== 0
          ? ((todayOpen - todayReferenceClose) / todayReferenceClose) * 100
          : null;
      const intradayRangePct =
        finiteNumber(todayStats.high) &&
        finiteNumber(todayStats.low) &&
        finiteNumber(todayReferenceClose) &&
        todayReferenceClose !== 0
          ? ((todayStats.high - todayStats.low) / todayReferenceClose) * 100
          : null;
      const currentVolume = todayStats.volume ?? latestToday?.volume ?? null;
      const currentVolumeVsDailyAverage = safeRatio(currentVolume, volumeMa20);
      const currentVolumeVsDailyAveragePct =
        currentVolumeVsDailyAverage === null ? null : currentVolumeVsDailyAverage * 100;

      if (finiteNumber(latestChangePct)) {
        if (latestChangePct > 0) addScore(1);
        if (latestChangePct < 0) addScore(-1);
      }
      if (finiteNumber(openingGapPct)) {
        if (openingGapPct > 0) addScore(1);
        if (openingGapPct < 0) addScore(-1);
      }
      if (!isOpeningPhase && finiteNumber(priceVsOpenPct)) {
        if (priceVsOpenPct > 0) addScore(1);
        if (priceVsOpenPct < 0) addScore(-1);
      }
      if (!isOpeningPhase && finiteNumber(relativeToPrimaryIndex)) {
        if (relativeToPrimaryIndex > 0) addScore(1);
        if (relativeToPrimaryIndex < 0) addScore(-1);
      }

      const intradayHighLow = `${formatPrice(todayStats.high)} / ${formatPrice(todayStats.low)}`;
      rows.push(
        {
          title: "即時價格",
          description: `相對昨收 ${formatPct(latestChangePct)}，${pointCount} 筆盤中資料`,
          value: formatPrice(latestClose),
          pulseValue: latestClose,
          direction: latestChangePct,
          tone: rowTone(latestChangePct),
        },
        {
          title: "開盤結構",
          description: `開盤 ${formatPrice(todayOpen)}，高低 ${intradayHighLow}，振幅 ${formatPct(intradayRangePct)}`,
          value: formatPct(priceVsOpenPct),
          pulseValue: priceVsOpenPct,
          direction: priceVsOpenPct,
          tone: rowTone(priceVsOpenPct),
        },
        {
          title: "量能速度",
          description: `目前累計量，20日均量占比 ${formatPct(currentVolumeVsDailyAveragePct)}`,
          value: currentVolume === null ? "觀察中" : `${formatLots(currentVolume)}張`,
          pulseValue: currentVolume,
          direction: null,
          tone: "neutral",
        },
        {
          title: "日線背景",
          description: `RSI ${formatIndicatorValue(rsi14)}，MACD H ${formatIndicatorValue(macdHistogram)}，MA20 ${formatPrice(ma20)}`,
          value: formatPct(priceVsMa20),
          pulseValue: priceVsMa20,
          direction: priceVsMa20,
          tone:
            finiteNumber(rsi14) && rsi14 >= 80
              ? "warning"
              : finiteNumber(priceVsMa20)
                ? rowTone(priceVsMa20)
                : "neutral",
        },
        {
          title: "法人籌碼",
          description: `最新已公布三大法人，融資餘額 ${formatSignedNumber(marginBalanceChange)}`,
          value:
            latestInstitutionalNet === null
              ? "-"
              : `${formatSignedLots(latestInstitutionalNet)}張`,
          pulseValue: latestInstitutionalNet,
          direction: latestInstitutionalNet,
          tone: rowTone(latestInstitutionalNet),
        },
        {
          title: "相對市場",
          description: `相對${primaryMarketIndex?.short_label ?? "大盤"}，${
            isOpeningPhase ? "開盤初期僅作方向參考" : marketRelativeLabel
          }`,
          value: formatPct(relativeToPrimaryIndex),
          pulseValue: relativeToPrimaryIndex,
          direction: relativeToPrimaryIndex,
          tone: rowTone(relativeToPrimaryIndex),
        }
      );

      if (isOpeningPhase) addBadge("開盤資料少", "text-amber-700 bg-amber-50");
      if (finiteNumber(openingGapPct)) {
        addBadge(
          openingGapPct >= 0 ? "開高" : "開低",
          openingGapPct >= 0 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50"
        );
      }
      if (finiteNumber(priceVsMa20)) {
        addBadge(
          priceVsMa20 >= 0 ? "日線站上 MA20" : "日線跌破 MA20",
          priceVsMa20 >= 0 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50"
        );
      }
      if (finiteNumber(rsi14) && rsi14 >= 80) addBadge("日線 RSI 過熱", "text-amber-700 bg-amber-50");

      return {
        title: isOpeningPhase
          ? titleFor("開盤偏強", "開盤觀察", "開盤偏弱")
          : titleFor("盤中偏多", "盤中觀察", "盤中偏弱"),
        summary: summaryFrom([
          `${pointCount} 筆盤中資料`,
          finiteNumber(latestChangePct)
            ? latestChangePct >= 0
              ? "現價高於昨收"
              : "現價低於昨收"
            : "資料不足",
          finiteNumber(openingGapPct)
            ? openingGapPct >= 0
              ? "開高"
              : "開低"
            : "資料不足",
          isOpeningPhase ? "日線指標僅作背景" : marketRelativeLabel,
        ]),
        value: latestChangePct ?? null,
        valueLabel: "vs 昨收",
        score,
        rows,
        badges,
      };
    }

    if (effectiveTimeframe === "daily") {
      if (finiteNumber(priceVsMa20)) addScore(priceVsMa20 >= 0 ? 1 : -1);
      if (finiteNumber(ma5) && finiteNumber(ma20)) addScore(ma5 >= ma20 ? 1 : -1);
      if (finiteNumber(ma20) && finiteNumber(ma60)) addScore(ma20 >= ma60 ? 1 : -1);
      if (finiteNumber(macdHistogram)) addScore(macdHistogram >= 0 ? 1 : -1);
      if (finiteNumber(rsi14)) {
        if (rsi14 >= 50 && rsi14 < 80) addScore(1);
        if (rsi14 < 40) addScore(-1);
      }
      if (finiteNumber(mfi14) && mfi14 >= 50 && mfi14 < 85) addScore(1);
      if (finiteNumber(adx14) && adx14 >= 25 && finiteNumber(plusDi14) && finiteNumber(minusDi14)) {
        addScore(plusDi14 >= minusDi14 ? 1 : -1);
      }
      if (finiteNumber(latestInstitutionalNet)) addScore(latestInstitutionalNet > 0 ? 1 : -1);

      rows.push(
        {
          title: "趨勢結構",
          description: `MA5/20/60 ${formatPrice(ma5)} / ${formatPrice(ma20)} / ${formatPrice(ma60)}，ADX ${formatIndicatorValue(adx14)}`,
          value: formatPct(priceVsMa20),
          pulseValue: priceVsMa20,
          direction: priceVsMa20,
          tone: rowTone(priceVsMa20),
        },
        {
          title: "動能指標",
          description: `RSI ${formatIndicatorValue(rsi14)}，MACD H ${formatIndicatorValue(macdHistogram)}，ROC12 ${formatPct(roc12)}`,
          value: formatIndicatorValue(rsi14),
          pulseValue: rsi14,
          direction: macdHistogram,
          tone:
            finiteNumber(rsi14) && rsi14 >= 80
              ? "warning"
              : finiteNumber(macdHistogram)
                ? rowTone(macdHistogram)
                : "neutral",
        },
        {
          title: "量價資金",
          description: `量能 ${formatPct(volumeRatioPct)} vs 20 日均量，MFI ${formatIndicatorValue(mfi14)}`,
          value: formatPct(volumeRatioPct),
          pulseValue: volumeRatioPct,
          direction: volumeRatioPct,
          tone: finiteNumber(volumeRatio) && volumeRatio >= 1.5 ? "warning" : "neutral",
        },
        {
          title: "波動風險",
          description: `ATR ${formatPct(atrPct)}，Donchian 位置 ${formatPct(donchianPositionPct)}`,
          value: formatPct(atrPct),
          pulseValue: atrPct,
          direction: finiteNumber(atrPct) && atrPct > 5 ? 1 : 0,
          tone: finiteNumber(atrPct) && atrPct > 5 ? "warning" : "neutral",
        },
        {
          title: "法人籌碼",
          description: `最新三大法人合計，融資餘額 ${formatSignedNumber(marginBalanceChange)}`,
          value:
            latestInstitutionalNet === null
              ? "-"
              : `${formatSignedLots(latestInstitutionalNet)}張`,
          pulseValue: latestInstitutionalNet,
          direction: latestInstitutionalNet,
          tone: rowTone(latestInstitutionalNet),
        },
        {
          title: "相對市場",
          description: `相對${primaryMarketIndex?.short_label ?? "大盤"}，${marketRelativeLabel}`,
          value: formatPct(relativeToPrimaryIndex),
          pulseValue: relativeToPrimaryIndex,
          direction: relativeToPrimaryIndex,
          tone: rowTone(relativeToPrimaryIndex),
        }
      );

      if (finiteNumber(priceVsMa20)) addBadge(priceVsMa20 >= 0 ? "站上 MA20" : "跌破 MA20", priceVsMa20 >= 0 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50");
      if (finiteNumber(macdHistogram)) addBadge(macdHistogram >= 0 ? "MACD 偏多" : "MACD 偏弱", macdHistogram >= 0 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50");
      if (finiteNumber(rsi14) && rsi14 >= 80) addBadge("RSI 過熱", "text-amber-700 bg-amber-50");
      if (finiteNumber(volumeRatio) && volumeRatio >= 1.5) addBadge("放量", "text-amber-700 bg-amber-50");

      return {
        title: titleFor("短線偏多", "短線整理", "短線偏弱"),
        summary: summaryFrom([
          finiteNumber(priceVsMa20) ? (priceVsMa20 >= 0 ? "站上 MA20" : "跌破 MA20") : "資料不足",
          finiteNumber(macdHistogram) ? (macdHistogram >= 0 ? "MACD 偏多" : "MACD 偏弱") : "資料不足",
          finiteNumber(volumeRatio) ? (volumeRatio >= 1.5 ? "放量" : "量能一般") : "資料不足",
        ]),
        value: priceVsMa20,
        valueLabel: "vs MA20",
        score,
        rows,
        badges,
      };
    }

    if (effectiveTimeframe === "weekly") {
      const weekStats13 = chartWindowStats(chartData, 13);
      const weekStats26 = chartWindowStats(chartData, 26);
      const weeklyMa4 = averageRecentChartClose(chartData, 4);
      const weeklyMa13 = averageRecentChartClose(chartData, 13);
      const weeklyVolumeRatio = safeRatio(latestChart?.volume, weekStats13.volumeAverage);
      const weeklyVolumeRatioPct =
        weeklyVolumeRatio === null ? null : (weeklyVolumeRatio - 1) * 100;
      const institutional20 = sumRecentInstitutionalNet(institutionalHistory, 20) ?? latestInstitutionalNet;

      if (finiteNumber(weekStats13.changePct)) addScore(weekStats13.changePct >= 0 ? 1 : -1);
      if (finiteNumber(weeklyMa4) && finiteNumber(weeklyMa13)) addScore(weeklyMa4 >= weeklyMa13 ? 1 : -1);
      if (finiteNumber(weekStats26.rangePositionPct)) {
        if (weekStats26.rangePositionPct >= 65) addScore(1);
        if (weekStats26.rangePositionPct <= 35) addScore(-1);
      }
      if (finiteNumber(institutional20)) addScore(institutional20 > 0 ? 1 : -1);

      rows.push(
        {
          title: "中線趨勢",
          description: `4週/13週均價 ${formatPrice(weeklyMa4)} / ${formatPrice(weeklyMa13)}`,
          value: formatPct(weekStats13.changePct),
          pulseValue: weekStats13.changePct,
          direction: weekStats13.changePct,
          tone: rowTone(weekStats13.changePct),
        },
        {
          title: "區間位置",
          description: `26週高低 ${formatPrice(weekStats26.high)} / ${formatPrice(weekStats26.low)}`,
          value: formatPct(weekStats26.rangePositionPct),
          pulseValue: weekStats26.rangePositionPct,
          direction:
            finiteNumber(weekStats26.rangePositionPct) ? weekStats26.rangePositionPct - 50 : null,
          tone:
            finiteNumber(weekStats26.rangePositionPct) && weekStats26.rangePositionPct >= 70
              ? "positive"
              : finiteNumber(weekStats26.rangePositionPct) && weekStats26.rangePositionPct <= 30
                ? "negative"
                : "neutral",
        },
        {
          title: "週量節奏",
          description: "最新週量相對 13 週均量",
          value: formatPct(weeklyVolumeRatioPct),
          pulseValue: weeklyVolumeRatioPct,
          direction: weeklyVolumeRatioPct,
          tone: finiteNumber(weeklyVolumeRatio) && weeklyVolumeRatio >= 1.5 ? "warning" : "neutral",
        },
        {
          title: "法人累積",
          description: "近 20 個交易日三大法人合計",
          value: institutional20 === null ? "-" : `${formatSignedLots(institutional20)}張`,
          pulseValue: institutional20,
          direction: institutional20,
          tone: rowTone(institutional20),
        },
        {
          title: "市場背景",
          description: `${primaryMarketIndex?.short_label ?? "大盤"} ${marketRegimeLabel(primaryMarketIndex)}`,
          value: formatPct(primaryMarketIndex?.change_pct),
          pulseValue: primaryMarketIndex?.change_pct,
          direction: primaryMarketIndex?.change_pct,
          tone: rowTone(primaryMarketIndex?.change_pct),
        }
      );

      if (finiteNumber(weeklyMa4) && finiteNumber(weeklyMa13)) addBadge(weeklyMa4 >= weeklyMa13 ? "週線偏多" : "週線偏弱", weeklyMa4 >= weeklyMa13 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50");
      if (finiteNumber(weekStats26.rangePositionPct) && weekStats26.rangePositionPct >= 80) addBadge("接近26週高位", "text-amber-700 bg-amber-50");
      if (finiteNumber(weeklyVolumeRatio) && weeklyVolumeRatio >= 1.5) addBadge("週量放大", "text-amber-700 bg-amber-50");

      return {
        title: titleFor("中線轉強", "中線整理", "中線偏弱"),
        summary: summaryFrom([
          finiteNumber(weekStats13.changePct) ? `13週${weekStats13.changePct >= 0 ? "走升" : "走弱"}` : "資料不足",
          finiteNumber(weekStats26.rangePositionPct)
            ? weekStats26.rangePositionPct >= 65
              ? "位於區間上緣"
              : weekStats26.rangePositionPct <= 35
                ? "位於區間下緣"
                : "區間中段"
            : "資料不足",
          institutional20 !== null ? (institutional20 >= 0 ? "法人累積買超" : "法人累積賣超") : "資料不足",
        ]),
        value: weekStats13.changePct,
        valueLabel: "近13週",
        score,
        rows,
        badges,
      };
    }

    const monthStats6 = chartWindowStats(chartData, 6);
    const monthStats12 = chartWindowStats(chartData, 12);
    const monthlyMa6 = averageRecentChartClose(chartData, 6);
    const monthlyMa12 = averageRecentChartClose(chartData, 12);
    const revenueGrowth = monthlyRevenue?.year_over_year_pct ?? null;
    const cumulativeRevenueGrowth = monthlyRevenue?.cumulative_year_over_year_pct ?? null;
    const eps = financialMetric?.eps ?? null;
    const roe = financialMetric?.roe ?? null;

    if (finiteNumber(monthStats12.changePct)) addScore(monthStats12.changePct >= 0 ? 1 : -1);
    if (finiteNumber(monthlyMa6) && finiteNumber(monthlyMa12)) addScore(monthlyMa6 >= monthlyMa12 ? 1 : -1);
    if (finiteNumber(revenueGrowth)) addScore(revenueGrowth >= 0 ? 1 : -1);
    if (finiteNumber(eps)) addScore(eps > 0 ? 1 : -1);
    if (finiteNumber(largeHolder.change)) addScore(largeHolder.change >= 0 ? 1 : -1);

    rows.push(
      {
        title: "長線趨勢",
        description: `6月/12月均價 ${formatPrice(monthlyMa6)} / ${formatPrice(monthlyMa12)}`,
        value: formatPct(monthStats12.changePct),
        pulseValue: monthStats12.changePct,
        direction: monthStats12.changePct,
        tone: rowTone(monthStats12.changePct),
      },
      {
        title: "長期區間",
        description: `12月高低 ${formatPrice(monthStats12.high)} / ${formatPrice(monthStats12.low)}`,
        value: formatPct(monthStats12.rangePositionPct),
        pulseValue: monthStats12.rangePositionPct,
        direction:
          finiteNumber(monthStats12.rangePositionPct) ? monthStats12.rangePositionPct - 50 : null,
        tone:
          finiteNumber(monthStats12.rangePositionPct) && monthStats12.rangePositionPct >= 70
            ? "positive"
            : finiteNumber(monthStats12.rangePositionPct) && monthStats12.rangePositionPct <= 30
              ? "negative"
              : "neutral",
      },
      {
        title: "營收動能",
        description: `月營收 YoY ${formatPct(revenueGrowth)}，累計 YoY ${formatPct(cumulativeRevenueGrowth)}`,
        value: formatPct(revenueGrowth),
        pulseValue: revenueGrowth,
        direction: revenueGrowth,
        tone: rowTone(revenueGrowth),
      },
      {
        title: "獲利品質",
        description: `EPS ${formatIndicatorValue(eps)}，ROE ${formatRatioPct(roe)}`,
        value: formatIndicatorValue(eps),
        pulseValue: eps,
        direction: eps,
        tone: rowTone(eps),
      },
      {
        title: "長期籌碼",
        description: `${largeHolderLots}張以上持股比 ${formatRatioPct(largeHolder.ratio)}，最新 ${formatDate(largeHolder.dataDate)}`,
        value: formatPct(largeHolder.change),
        pulseValue: largeHolder.change,
        direction: largeHolder.change,
        tone: rowTone(largeHolder.change),
      }
    );

    if (finiteNumber(monthlyMa6) && finiteNumber(monthlyMa12)) addBadge(monthlyMa6 >= monthlyMa12 ? "月線偏多" : "月線偏弱", monthlyMa6 >= monthlyMa12 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50");
    if (finiteNumber(revenueGrowth)) addBadge(revenueGrowth >= 0 ? "營收成長" : "營收衰退", revenueGrowth >= 0 ? "text-red-700 bg-red-50" : "text-emerald-700 bg-emerald-50");
    if (finiteNumber(monthStats12.rangePositionPct) && monthStats12.rangePositionPct >= 80) addBadge("接近12月高位", "text-amber-700 bg-amber-50");

    return {
      title: titleFor("長線偏多", "長線觀察", "長線偏弱"),
      summary: summaryFrom([
        finiteNumber(monthStats12.changePct) ? `12月${monthStats12.changePct >= 0 ? "走升" : "走弱"}` : "資料不足",
        finiteNumber(revenueGrowth) ? (revenueGrowth >= 0 ? "營收成長" : "營收衰退") : "營收待讀取",
        finiteNumber(largeHolder.change) ? (largeHolder.change >= 0 ? "大戶增加" : "大戶減少") : "籌碼待讀取",
      ]),
      value: monthStats6.changePct ?? monthStats12.changePct,
      valueLabel: monthStats6.changePct !== null ? "近6月" : "近12月",
      score,
      rows,
      badges,
    };
  }, [
    chartData,
    currentChartReady,
    effectiveTimeframe,
    financialMetric,
    institutional,
    institutionalHistory,
    isIndexProduct,
    largeHolderLots,
    latestChangePct,
    latestChart?.volume,
    latestClose,
    latestIndicator,
    latestToday,
    loadState,
    ma5,
    ma20,
    ma60,
    margin,
    monthlyRevenue,
    primaryMarketIndex,
    priceVsMa20,
    relativeToPrimaryIndex,
    shareholding,
    todayStats.high,
    todayStats.low,
    todayStats.open,
    todayStats.volume,
    todayReferenceClose,
    todayTrend.length,
    totalInstitutionalNet,
    volumeMa20,
    volumeRatio,
    volumeRatioPct,
  ]);
  const backendTechnicalReportView = useMemo(() => {
    if (
      !backendTechnicalReport ||
      backendTechnicalReport.stock_id !== stockId ||
      backendTechnicalReport.timeframe !== effectiveTimeframe
    ) {
      return null;
    }

    return mapBackendTechnicalReport(backendTechnicalReport);
  }, [backendTechnicalReport, effectiveTimeframe, stockId]);
  const technicalReport = backendTechnicalReportView ?? fallbackTechnicalReport;
  const technicalStatus = technicalReport.title;
  const technicalSummaryText = technicalReport.summary;
  const visibleSignals = technicalReport.badges.slice(0, 4);
  const displayOvernightImpact = !stockId || isIndexProduct ? null : overnightImpact;
  const displayOvernightImpactLoadState: LoadState =
    !stockId || isIndexProduct ? "idle" : overnightImpactLoadState;
  const technicalSourceReady =
    effectiveTimeframe === "today" ? todayTrend.length > 0 : currentChartReady;
  const showTechnicalLoading =
    !isIndexProduct &&
    loadState === "loading" &&
    !technicalSourceReady &&
    backendTechnicalReportView === null;

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

  function dataTabHasCurrentData(tab: DataPanelTab, targetStockId = stockId) {
    if (!targetStockId) return false;

    if (tab === "chips") {
      return (
        (margin !== null && margin.stock_id === targetStockId) ||
        shareholding.some((row) => row.stock_id === targetStockId)
      );
    }

    if (tab === "institutional") {
      return institutionalHistory.some((row) => row.stock_id === targetStockId);
    }

    if (tab === "branch") {
      return (
        brokerBranchSummary !== null &&
        brokerBranchSummary.stock_id === targetStockId &&
        brokerBranchSummary.requested_days === branchDays &&
        dataPanelResolvedKeysRef.current.has(
          dataPanelCacheKey(targetStockId, "branch", branchDays)
        )
      );
    }

    if (tab === "revenue") {
      const currentRows = monthlyRevenueHistory.filter(
        (row) => row.stock_id === targetStockId
      );

      return currentRows.length >= minimumUsableRevenueRows;
    }

    if (tab === "earnings") {
      const currentRows = financialMetricHistory.filter(
        (row) => row.stock_id === targetStockId
      );

      return currentRows.length >= minimumUsableFinancialRows;
    }

    return false;
  }

  async function refreshDataTab(tab: DataPanelTab) {
    if (!stockId) return;

    const targetStockId = stockId;
    const targetBranchDays = tab === "branch" ? branchDays : 1;
    const requestKey = dataPanelCacheKey(targetStockId, tab, targetBranchDays);

    if (dataPanelRequestKeyRef.current === requestKey) return;

    dataPanelRequestKeyRef.current = requestKey;
    setDataPanelLoading(tab);
    setDataPanelMessage(null);

    const panelRefreshProfile = getTaiwanDataPanelRefreshProfile(tab);
    const panelRefreshLabel = getTaiwanDataPanelRefreshLabel(tab);

    const runPanelRefresh = async (
      profile: TaiwanRefreshProfile,
      label: string
    ) => {
      const job = await requestBackfillJob(
        taiwanSelectionRefreshPath(targetStockId),
        { method: "POST" },
        { profile, sleep_seconds: 0.05 },
        {
          intervalMs: 1500,
          timeoutMs: 600000,
          onUpdate: (job) => {
            if (activeStockIdRef.current === targetStockId) {
              setDataPanelMessage(formatPanelJobProgress(label, job));
            }
          },
        }
      );

      if (getJobResultStatus(job) === "error") {
        throw new Error(formatBackfillOutcome(job, label));
      }

      return job;
    };

    const loadCachedChips = async (statusNote?: string) => {
      const [coverageResult, shareholdingResult, marginResult] = await Promise.allSettled([
        fetchJson<StockChipCoverageRead>(`/api/market/chips/${targetStockId}/coverage`),
        fetchJson<ShareholdingDistributionWeeklyRead[]>(
          `/api/market/shareholding/${targetStockId}/history`,
          { limit: 12000, ensure_history: false }
        ),
        fetchJson<MarginTradingDailyRead[]>(`/api/market/margin/${targetStockId}/history`, {
          lookback_days: 365,
          limit: 365,
          ensure_history: false,
        }),
      ]);

      if (activeStockIdRef.current !== targetStockId) {
        return { hasShareholding: false, hasMargin: false };
      }

      const fallbackCoverage = chipCoverage?.stock_id === targetStockId ? chipCoverage : null;
      const fallbackShareholding = shareholding.filter((row) => row.stock_id === targetStockId);
      const fallbackMargin = margin?.stock_id === targetStockId ? margin : null;
      const nextCoverage =
        coverageResult.status === "fulfilled" ? coverageResult.value : fallbackCoverage;
      const nextShareholding =
        shareholdingResult.status === "fulfilled"
          ? shareholdingResult.value
          : fallbackShareholding;
      const nextMarginRows = marginResult.status === "fulfilled" ? marginResult.value : [];
      const nextMargin =
        marginResult.status === "fulfilled"
          ? nextMarginRows[nextMarginRows.length - 1] ?? null
          : fallbackMargin;
      const hasShareholding = nextShareholding.length > 0;
      const hasMargin = nextMargin !== null;
      const fallbackShareholdingWeekCount = new Set(
        nextShareholding.map((row) => row.data_date)
      ).size;

      setChipCoverage(nextCoverage);
      setShareholding(nextShareholding);
      setMargin(nextMargin);

      const coverageText = nextCoverage
        ? `集保 ${nextCoverage.shareholding_week_count} 週${
            nextCoverage.shareholding_latest_date
              ? `，最新 ${formatDate(nextCoverage.shareholding_latest_date)}`
              : ""
          }；融資融券 ${nextCoverage.margin_row_count} 筆${
            nextCoverage.margin_latest_trade_date
              ? `，最新 ${formatDate(nextCoverage.margin_latest_trade_date)}`
              : ""
          }`
        : `集保 ${fallbackShareholdingWeekCount} 週；融資融券 ${
            nextMarginRows.length || (nextMargin ? 1 : 0)
          } 筆`;

      const failures = [
        coverageResult.status === "rejected" ? "快取狀態" : null,
        shareholdingResult.status === "rejected" ? "集保股權分散" : null,
        marginResult.status === "rejected" ? "融資融券" : null,
      ].filter(Boolean);

      const panelNotes = [
        statusNote,
        coverageText,
        failures.length ? `部分快取讀取失敗：${failures.join("、")}` : null,
      ].filter(Boolean);

      setDataPanelMessage(panelNotes.join("；"));

      return { hasShareholding, hasMargin };
    };

    try {
      if (tab === "branch") {
        const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);
        const branchSummary = await fetchJson<BrokerBranchTradeDailySummaryRead>(
          `/api/market/broker-branches/${targetStockId}/daily`,
          { ensure_daily: false, days: targetBranchDays }
        );

        if (activeStockIdRef.current !== targetStockId) return;

        dataPanelResolvedKeysRef.current.add(requestKey);
        branchSummaryCacheRef.current.set(requestKey, branchSummary);

        if (
          activeDataTabRef.current === "branch" &&
          dataPanelCacheKey(targetStockId, "branch", branchDaysRef.current) !== requestKey
        ) {
          return;
        }

        setBrokerBranchSummary(branchSummary);
        setDataPanelMessage(
          branchSummary.trade_date
            ? `${formatBackfillOutcome(refreshJob, panelRefreshLabel)}；分點 Top15 已讀取至 ${formatDate(branchSummary.trade_date)}`
            : "尚無分點 Top15 資料"
        );
        return;
      }

      if (tab === "chips") {
        const initialCache = await loadCachedChips("已先顯示本機快取");
        let hasBackfillIssue = false;

        if (initialCache.hasShareholding || initialCache.hasMargin) {
          dataPanelResolvedKeysRef.current.add(requestKey);
        }

        try {
          const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);
          if (getJobResultStatus(refreshJob) === "partial_success") {
            hasBackfillIssue = true;
          }
        } catch {
          hasBackfillIssue = true;
        }

        const finalCache = await loadCachedChips(
          hasBackfillIssue ? "部分補齊未完成，詳見左側更新狀態" : "籌碼資料已重新讀取"
        );

        if (activeStockIdRef.current !== targetStockId) return;

        if (finalCache.hasShareholding || finalCache.hasMargin) {
          dataPanelResolvedKeysRef.current.add(requestKey);
        }
        return;
      }

      if (tab === "institutional") {
        const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);

        const institutionalRows = await fetchJson<InstitutionalTradeDailyRead[]>(
          `/api/market/institutional/${targetStockId}/history`,
          {
            lookback_days: institutionalLookbackDays,
            limit: institutionalHistoryLimit,
            ensure_history: false,
          }
        );

        if (activeStockIdRef.current !== targetStockId) return;

        dataPanelResolvedKeysRef.current.add(requestKey);
        setInstitutional(institutionalRows[institutionalRows.length - 1] ?? null);
        setInstitutionalHistory(institutionalRows);
        setDataPanelMessage(formatBackfillOutcome(refreshJob, panelRefreshLabel));
        return;
      }

      if (tab === "revenue") {
        const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);

        const revenueRows = await fetchJson<MonthlyRevenueRead[]>(
          `/api/market/revenue/${targetStockId}/history`,
          {
            limit: revenueHistoryLimit,
            ensure_history: false,
          }
        );

        if (activeStockIdRef.current !== targetStockId) return;

        dataPanelResolvedKeysRef.current.add(requestKey);
        setMonthlyRevenue(revenueRows[revenueRows.length - 1] ?? null);
        setMonthlyRevenueHistory(revenueRows);
        setDataPanelMessage(formatBackfillOutcome(refreshJob, panelRefreshLabel));
        return;
      }

      if (tab === "earnings") {
        const refreshJob = await runPanelRefresh(panelRefreshProfile, panelRefreshLabel);

        const financialRows = await fetchJson<FinancialMetricQuarterlyRead[]>(
          `/api/market/financials/${targetStockId}/history`,
          {
            limit: financialHistoryLimit,
            ensure_history: false,
          }
        );

        if (activeStockIdRef.current !== targetStockId) return;

        dataPanelResolvedKeysRef.current.add(requestKey);
        setFinancialMetric(financialRows[financialRows.length - 1] ?? null);
        setFinancialMetricHistory(financialRows);
        setDataPanelMessage(formatBackfillOutcome(refreshJob, panelRefreshLabel));
      }
    } catch {
      if (activeStockIdRef.current !== targetStockId) return;

      setDataPanelMessage("補資料失敗，詳見左側更新狀態或稍後重試");
    } finally {
      if (dataPanelRequestKeyRef.current === requestKey) {
        dataPanelRequestKeyRef.current = null;
        setDataPanelLoading(null);
      }
    }
  }

  useEffect(() => {
    if (!stockId || isIndexProduct) return;

    let cancelled = false;
    const targetStockId = stockId;
    const timer = window.setTimeout(() => {
      void requestBackfillJob(
        taiwanSelectionRefreshPath(targetStockId),
        { method: "POST" },
        { profile: "basic", sleep_seconds: 0.05 },
        {
          intervalMs: 1500,
          timeoutMs: 600000,
          onUpdate: (job) => {
            if (!cancelled && activeStockIdRef.current === targetStockId) {
              setDataPanelMessage(formatPanelJobProgress("自選股基礎資料自動更新", job));
            }
          },
        }
      )
        .then((job) => {
          if (cancelled || activeStockIdRef.current !== targetStockId) return;

          const resultStatus = getJobResultStatus(job);
          setDataPanelMessage(
            resultStatus === "partial_success"
              ? "自選股基礎資料自動更新部分完成，部分來源暫時不可用"
              : resultStatus === "error"
                ? "自選股基礎資料自動更新失敗"
                : "自選股基礎資料自動更新完成"
          );
        })
        .catch(() => {
          if (cancelled || activeStockIdRef.current !== targetStockId) return;

          setDataPanelMessage("自選股基礎資料自動更新失敗，詳見左側更新狀態");
        });
    }, 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // Queue once per selected stock; tab-level datasets are loaded by the visible tab effect.
  }, [isIndexProduct, stockId]);

  function handleDataTabClick(tab: DataPanelTab) {
    if (isIndexProduct) return;
    setActiveDataTab(tab);
  }

  useEffect(() => {
    if (!stockId || isIndexProduct) return;

    const requestKey = dataPanelCacheKey(stockId, activeDataTab, branchDays);
    const cachedBranchSummary =
      activeDataTab === "branch" ? branchSummaryCacheRef.current.get(requestKey) : null;
    const hasCachedResult = dataPanelResolvedKeysRef.current.has(requestKey);
    const hasCurrentData = dataTabHasCurrentData(activeDataTab);

    if (cachedBranchSummary) {
      const timer = window.setTimeout(() => {
        if (dataPanelRequestKeyRef.current === requestKey) return;

        setBrokerBranchSummary(cachedBranchSummary);
        setDataPanelLoading((current) => (current === activeDataTab ? null : current));
        setDataPanelMessage("使用暫存資料");
      }, 0);

      return () => window.clearTimeout(timer);
    }

    if (hasCachedResult || hasCurrentData) {
      const timer = window.setTimeout(() => {
        if (dataPanelRequestKeyRef.current === requestKey) return;

        setDataPanelLoading((current) => (current === activeDataTab ? null : current));
        setDataPanelMessage(hasCachedResult ? "使用暫存資料" : null);
      }, 0);

      return () => window.clearTimeout(timer);
    }

    const timer = window.setTimeout(() => {
      void refreshDataTab(activeDataTab);
    }, 0);

    return () => window.clearTimeout(timer);
    // Populate the visible right-panel tab whenever the selected stock or tab changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDataTab, branchDays, isIndexProduct, stockId]);

  if (!stockId) {
    return watchlistRankingPanel ? (
      <section className="min-w-0">{watchlistRankingPanel}</section>
    ) : null;
  }

  const selectedStockId = stockId;

  function hasRowsFromOtherStock<T extends { stock_id: string }>(rows: T[]) {
    return rows.some((row) => row.stock_id !== selectedStockId);
  }

  function activeDataTabHasStaleData() {
    if (activeDataTab === "chips") {
      return (
        (margin !== null && margin.stock_id !== selectedStockId) ||
        hasRowsFromOtherStock(shareholding)
      );
    }

    if (activeDataTab === "institutional") {
      return hasRowsFromOtherStock(institutionalHistory);
    }

    if (activeDataTab === "branch") {
      return (
        brokerBranchSummary !== null &&
        (brokerBranchSummary.stock_id !== selectedStockId ||
          brokerBranchSummary.requested_days !== branchDays)
      );
    }

    if (activeDataTab === "revenue") {
      return (
        (monthlyRevenue !== null && monthlyRevenue.stock_id !== selectedStockId) ||
        hasRowsFromOtherStock(monthlyRevenueHistory)
      );
    }

    if (activeDataTab === "earnings") {
      return (
        (financialMetric !== null && financialMetric.stock_id !== selectedStockId) ||
        hasRowsFromOtherStock(financialMetricHistory)
      );
    }

    return false;
  }

  function activeDataTabHasRenderableData() {
    if (activeDataTab === "chips") {
      return (
        (margin !== null && margin.stock_id === selectedStockId) ||
        shareholding.some((row) => row.stock_id === selectedStockId)
      );
    }

    if (activeDataTab === "institutional") {
      return institutionalHistory.some((row) => row.stock_id === selectedStockId);
    }

    if (activeDataTab === "branch") {
      return (
        brokerBranchSummary !== null &&
        brokerBranchSummary.stock_id === selectedStockId &&
        brokerBranchSummary.requested_days === branchDays
      );
    }

    if (activeDataTab === "revenue") {
      const currentRows = monthlyRevenueHistory.filter(
        (row) => row.stock_id === selectedStockId
      );

      return currentRows.length >= minimumUsableRevenueRows;
    }

    if (activeDataTab === "earnings") {
      const currentRows = financialMetricHistory.filter(
        (row) => row.stock_id === selectedStockId
      );

      return currentRows.length >= minimumUsableFinancialRows;
    }

    return false;
  }

  function renderChipTab() {
    const hasShareholding = shareholdingSeries.length > 0;
    const hasMargin = margin !== null;
    const currentChipCoverage = chipCoverage?.stock_id === stockId ? chipCoverage : null;

    if (!hasShareholding && !hasMargin) {
      return <EmptyDataState message="尚無籌碼或融資融券資料" />;
    }

    return (
      <div className="space-y-5">
        {currentChipCoverage ? (
          <div className="text-xs leading-5 text-slate-500">
            集保最新 {formatDate(currentChipCoverage.shareholding_latest_date)}，
            共 {currentChipCoverage.shareholding_week_count} 週；融資融券最新{" "}
            {formatDate(currentChipCoverage.margin_latest_trade_date)}，
            共 {currentChipCoverage.margin_row_count} 筆
          </div>
        ) : null}

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
    const activeDailyPoint =
      recentPoints.find((point) => point.date === institutionalHoverDate) ?? displayLatestPoint;
    const currentHoldingRatio =
      institutionalHoldingRatio?.stock_id === selectedStockId ? institutionalHoldingRatio : null;
    const ratioHistory = currentHoldingRatio?.history ?? [];
    const activeHoldingRatio = institutionalHoverDate
      ? ratioHistory.find((point) => point.trade_date === institutionalHoverDate) ?? null
      : currentHoldingRatio;
    const ratioDate =
      institutionalHoverDate ?? activeHoldingRatio?.trade_date ?? activeDailyPoint.date;
    const tableRows = recentPoints.slice().reverse();
    const handleInstitutionalHoverPoint = (point: InstitutionalSeriesPoint | null) => {
      setInstitutionalHoverDate((current) =>
        current === point?.date ? current : point?.date ?? null
      );
    };

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
            activeDate={institutionalHoverDate}
            onHoverPointChange={handleInstitutionalHoverPoint}
          />
          <InstitutionalFlowChart
            points={recentPoints}
            title="投信"
            netKey="investmentTrustNet"
            cumulativeKey="investmentTrustCumulative"
            activeDate={institutionalHoverDate}
            onHoverPointChange={handleInstitutionalHoverPoint}
          />
          <InstitutionalFlowChart
            points={recentPoints}
            title="自營商"
            netKey="dealerNet"
            cumulativeKey="dealerCumulative"
            activeDate={institutionalHoverDate}
            showXAxisLabels
            onHoverPointChange={handleInstitutionalHoverPoint}
          />
        </div>

        <div className="border border-slate-200 bg-white px-4 py-3">
          <div className="mb-3 flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-bold text-slate-950">法人持有比例</div>
              <div className="mt-1 text-[11px] text-slate-500">
                實際持股比例
              </div>
            </div>
            <div className="text-sm font-bold text-slate-900">
              {formatDate(ratioDate)}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            {[
              {
                label: "外資",
                value: activeHoldingRatio?.foreign_investor_ratio ?? null,
              },
              {
                label: "投信",
                value: activeHoldingRatio?.investment_trust_ratio ?? null,
              },
              {
                label: "自營商",
                value: activeHoldingRatio?.dealer_ratio ?? null,
              },
            ].map((item) => (
              <div key={item.label} className="border border-slate-200 px-3 py-3">
                <div className="font-semibold text-slate-700">{item.label}</div>
                <div className="mt-2 text-base font-bold text-slate-950">
                  {formatRatioPct(item.value)}
                </div>
                <div className="mt-1 text-[11px] text-slate-500">持股比例</div>
              </div>
            ))}
          </div>
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
    if (!brokerBranchSummary || brokerBranchSummary.row_count === 0) {
      return <EmptyDataState message="尚無分點 Top15 資料" />;
    }

    const buyTotal = brokerBranchSummary.buy_top.reduce(
      (sum, row) => sum + (row.net_lots ?? 0),
      0
    );
    const sellTotal = brokerBranchSummary.sell_top.reduce(
      (sum, row) => sum + Math.abs(row.net_lots ?? 0),
      0
    );
    const compareRows = Array.from(
      {
        length: Math.max(
          brokerBranchSummary.buy_top.length,
          brokerBranchSummary.sell_top.length
        ),
      },
      (_, index) => ({
        buy: brokerBranchSummary.buy_top[index] ?? null,
        sell: brokerBranchSummary.sell_top[index] ?? null,
      })
    );
    const maxCompareValue = Math.max(
      1,
      ...compareRows.flatMap((row) => [
        Math.abs(row.buy?.net_lots ?? 0),
        Math.abs(row.sell?.net_lots ?? 0),
      ])
    );
    const detailRows =
      branchTableSide === "buy"
        ? brokerBranchSummary.buy_top
        : brokerBranchSummary.sell_top;
    const detailTotal =
      branchTableSide === "buy" ? buyTotal : sellTotal;
    const detailNetLabel = branchTableSide === "buy" ? "買超(張)" : "賣超(張)";
    const detailNameLabel = branchTableSide === "buy" ? "買超Top15" : "賣超Top15";
    const detailTotalLabel =
      branchTableSide === "buy" ? "Top15總買超" : "Top15總賣超";
    const detailTone =
      branchTableSide === "buy" ? "text-red-500" : "text-emerald-600";

    const branchDisplayName = (row: BrokerBranchTradeDailyRead | null) =>
      row?.branch_name || "-";
    const branchNetAbs = (row: BrokerBranchTradeDailyRead | null) =>
      Math.abs(row?.net_lots ?? 0);
    const branchBarWidth = (row: BrokerBranchTradeDailyRead | null) =>
      `${(branchNetAbs(row) / maxCompareValue) * 100}%`;
    const branchTradeDates = brokerBranchSummary.trade_dates ?? [];
    const branchDateRange =
      branchTradeDates.length > 1
        ? `${formatDate(branchTradeDates[branchTradeDates.length - 1])} - ${formatDate(
            branchTradeDates[0]
          )}`
        : formatDate(brokerBranchSummary.trade_date);
    const branchCoverageText =
      brokerBranchSummary.requested_days > 1
        ? brokerBranchSummary.is_partial
          ? `目前僅有 ${brokerBranchSummary.available_days} / ${brokerBranchSummary.requested_days} 日已存分點資料`
          : `目前顯示最近 ${brokerBranchSummary.available_days} 日分點資料`
        : "目前顯示一日分點資料";

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="text-lg font-bold text-slate-950">分點</div>
          <div className="text-right text-[11px] text-slate-500">
            <div>資料日期：{branchDateRange}</div>
            <a
              href={brokerBranchSummary.source_url}
              target="_blank"
              rel="noreferrer"
              className="font-semibold text-slate-700 underline-offset-2 hover:underline"
            >
              {brokerBranchSummary.source_name ?? "nStock"}
            </a>
          </div>
        </div>

        <div className="flex items-center justify-center gap-3 text-xs">
          <span className="font-semibold text-slate-600">天數</span>
          <div className="grid grid-cols-8 overflow-hidden border border-slate-800">
            {branchDayOptions.map((option) => {
              const disabled = option.days === null;
              const selected = option.days === branchDays;

              return (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => {
                    if (option.days !== null) setBranchDays(option.days);
                  }}
                  disabled={disabled}
                  className={[
                    "h-7 w-12 border-r border-slate-800 text-xs font-semibold last:border-r-0",
                    selected
                      ? "bg-slate-700 text-white"
                      : disabled
                        ? "bg-slate-100 text-slate-400"
                        : "bg-white text-slate-800 hover:bg-slate-50",
                  ].join(" ")}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="space-y-2">
          <div className="grid grid-cols-[1.2fr_1fr_1fr_1.2fr] text-xs font-semibold text-slate-500">
            <div>買超Top15</div>
            <div className="text-right">買超(張)</div>
            <div className="text-left">賣超(張)</div>
            <div className="text-right">賣超Top15</div>
          </div>

          <div className="space-y-1">
            {compareRows.map((row, index) => (
              <div
                key={`branch-compare-${index}`}
                className="grid grid-cols-[1.2fr_1fr_1fr_1.2fr] items-center gap-2 text-xs"
              >
                <div className="min-w-0 truncate font-semibold text-slate-900">
                  {branchDisplayName(row.buy)}
                </div>
                <div className="relative h-6 overflow-hidden bg-red-50 text-right">
                  <div
                    className="absolute bottom-0 right-0 top-0 bg-red-100"
                    style={{ width: branchBarWidth(row.buy) }}
                  />
                  <span className="relative z-10 pr-1 font-semibold text-red-500">
                    {formatLotUnits(branchNetAbs(row.buy))}
                  </span>
                </div>
                <div className="relative h-6 overflow-hidden bg-emerald-50 text-left">
                  <div
                    className="absolute bottom-0 left-0 top-0 bg-emerald-100"
                    style={{ width: branchBarWidth(row.sell) }}
                  />
                  <span className="relative z-10 pl-1 font-semibold text-emerald-600">
                    {formatLotUnits(branchNetAbs(row.sell))}
                  </span>
                </div>
                <div className="min-w-0 truncate text-right font-semibold text-slate-900">
                  {branchDisplayName(row.sell)}
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-slate-200 pt-2">
            <div className="mb-1 flex items-center justify-between text-xs font-semibold text-slate-900">
              <span>Top15總買超</span>
              <span>Top15總賣超</span>
            </div>
            <div className="grid grid-cols-2 overflow-hidden text-xs">
              <div className="bg-red-50 px-1 py-1 text-left font-semibold text-red-500">
                {formatLotUnits(buyTotal)}
              </div>
              <div className="bg-emerald-50 px-1 py-1 text-right font-semibold text-emerald-600">
                {formatLotUnits(sellTotal)}
              </div>
            </div>
          </div>
        </div>

        <div className="space-y-3 border-t border-slate-200 pt-5">
          <div className="text-center text-sm font-bold text-slate-950">
            Top15券商分點買賣超
          </div>

          <div className="flex items-center justify-center text-sm font-semibold">
            <div className="flex overflow-hidden border border-slate-800">
              {[
                { key: "buy", label: "買方" },
                { key: "sell", label: "賣方" },
              ].map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setBranchTableSide(item.key as BranchTableSide)}
                  className={[
                    "h-8 w-12 border-r border-slate-800 text-sm last:border-r-0",
                    branchTableSide === item.key
                      ? "bg-slate-700 text-white"
                      : "bg-white text-slate-800 hover:bg-slate-50",
                  ].join(" ")}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-hidden border-t border-slate-200">
            <div
              className="grid grid-cols-[1.5fr_0.9fr_0.8fr_0.8fr_0.9fr_0.9fr] border-b border-slate-200 text-xs font-semibold text-slate-500"
            >
              <div className="px-1 py-2">{detailNameLabel}</div>
              <div className="px-1 py-2 text-right">{detailNetLabel}</div>
              <div className="px-1 py-2 text-right">買張</div>
              <div className="px-1 py-2 text-right">賣張</div>
              <div className="px-1 py-2 text-right">買均價</div>
              <div className="px-1 py-2 text-right">賣均價</div>
            </div>
            {detailRows.map((row) => (
              <div
                key={`${branchTableSide}-${row.branch_code}-${row.branch_name}`}
                className="grid grid-cols-[1.5fr_0.9fr_0.8fr_0.8fr_0.9fr_0.9fr] border-b border-slate-200 text-sm last:border-b-0"
              >
                <div className="min-w-0 truncate px-1 py-2 font-semibold text-slate-950">
                  {row.branch_name || "-"}
                </div>
                <div className={`px-1 py-2 text-right ${detailTone}`}>
                  {formatLotUnits(Math.abs(row.net_lots ?? 0))}
                </div>
                <div className="px-1 py-2 text-right text-slate-950">
                  {formatLotUnits(row.buy_lots)}
                </div>
                <div className="px-1 py-2 text-right text-slate-950">
                  {formatLotUnits(row.sell_lots)}
                </div>
                <div className="px-1 py-2 text-right text-slate-950">
                  {formatPrice(row.buy_avg_price)}
                </div>
                <div className="px-1 py-2 text-right text-slate-950">
                  {formatPrice(row.sell_avg_price)}
                </div>
              </div>
            ))}
            <div
              className="grid grid-cols-[1.5fr_0.9fr_0.8fr_0.8fr_0.9fr_0.9fr] border-t border-slate-200 text-sm font-semibold"
            >
              <div className="px-1 py-2 text-slate-950">{detailTotalLabel}</div>
              <div className={`px-1 py-2 text-right ${detailTone}`}>
                {formatLotUnits(detailTotal)}
              </div>
              <div />
              <div />
              <div />
              <div />
            </div>
          </div>

          <div className="text-right text-[11px] text-slate-500">
            {branchCoverageText}；多日為已存每日 Top15 快照加總。
          </div>
        </div>
      </div>
    );
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
    const revenueYearOptions = Array.from(
      new Set(
        monthlyRevenueHistory
          .map((row) => Number(row.period.slice(0, 4)))
          .filter((year) => Number.isFinite(year))
      )
    ).sort((left, right) => right - left);

    if (!revenueYearOptions.includes(latestYear)) {
      revenueYearOptions.unshift(latestYear);
    }

    const selectedRevenueYear =
      revenueYear !== null && revenueYearOptions.includes(revenueYear)
        ? revenueYear
        : latestYear;
    const monthlyRowsByMonth = new Map(
      monthlyRevenueHistory
        .filter((row) => Number(row.period.slice(0, 4)) === selectedRevenueYear)
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
              <div className="px-2 py-1">
                <select
                  value={selectedRevenueYear}
                  onChange={(event) => setRevenueYear(Number(event.target.value))}
                  className="h-8 w-full bg-white px-2 text-center text-sm font-semibold text-slate-800 outline outline-1 outline-slate-200"
                  aria-label="選擇營收年度"
                >
                  {revenueYearOptions.map((year) => (
                    <option key={year} value={year}>
                      {year}
                    </option>
                  ))}
                </select>
              </div>
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
    const loadingActiveTab = dataPanelLoading === activeDataTab;
    const hasRenderableData = activeDataTabHasRenderableData();

    if (activeDataTabHasStaleData()) {
      return <DataPanelLoadingState message="補齊資料中..." />;
    }

    if (loadingActiveTab && !hasRenderableData) {
      return <DataPanelLoadingState message={dataPanelMessage ?? "補齊資料中..."} />;
    }

    const content =
      activeDataTab === "institutional"
        ? renderInstitutionalTab()
        : activeDataTab === "branch"
          ? renderBranchTab()
          : activeDataTab === "revenue"
            ? renderRevenueTab()
            : activeDataTab === "earnings"
              ? renderEarningsTab()
              : renderChipTab();

    return (
      <div
        key={`${selectedStockId}:${activeDataTab}:${branchDays}`}
        className={[
          "omi-tab-panel relative",
          loadingActiveTab ? "omi-soft-refresh pt-3" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {loadingActiveTab ? <DataPanelRefreshRail message={dataPanelMessage} /> : null}
        <div className={loadingActiveTab ? "opacity-85 transition-opacity duration-150" : ""}>
          {content}
        </div>
      </div>
    );
  }

  return (
    <section
      className={[
        "grid w-full grid-cols-1 items-start justify-start gap-4",
        chartFocusMode ? "" : "xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className={["min-w-0 self-start", chartFocusMode ? "space-y-0" : "space-y-4"].join(" ")}>
        <div className="min-w-0 border border-slate-200 bg-white">
          {chartFocusMode ? (
            <div className="border-b border-slate-200 px-4 py-2">
              <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  <div className="truncate text-lg font-bold text-slate-950">
                    {stockId} {indexProduct?.stockName ?? stockName ?? stockInfo?.stock_name ?? ""}
                  </div>
                  <div
                    className={`flex items-baseline gap-2 ${priceLimitTone(
                      professionalHeaderLimitStatus,
                      professionalLatestChange
                    )}`}
                  >
                    <PriceUpdatePulse
                      value={professionalLatestClose}
                      direction={professionalLatestChange}
                      resetKey={`${stockId ?? "empty"}:professional:${professionalTimeframe}`}
                      className={[
                        "text-2xl font-bold leading-none tracking-normal tabular-nums",
                        priceLimitBoxClass(professionalHeaderLimitStatus),
                      ].join(" ")}
                    >
                      {formatPrice(professionalLatestClose)}
                    </PriceUpdatePulse>
                    <span className="text-sm font-semibold tabular-nums">
                      {formatSignedPointChange(professionalLatestChange)}
                    </span>
                    {professionalLatestChangePct !== null &&
                    professionalLatestChangePct !== undefined ? (
                      <span className="text-sm font-semibold tabular-nums">
                        ({formatPct(professionalLatestChangePct)})
                      </span>
                    ) : null}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-end gap-1.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <div className="flex border border-slate-200 bg-slate-50 p-0.5">
                      {professionalTimeframeOptions.map((option) => (
                        <button
                          key={option.key}
                          type="button"
                          onClick={() => handleProfessionalTimeframeChange(option.key)}
                          className={[
                            "h-7 px-2 text-xs font-semibold transition",
                            professionalTimeframe === option.key
                              ? "bg-slate-900 text-white"
                              : "text-slate-600 hover:bg-white hover:text-slate-950",
                          ].join(" ")}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>

                    <div className="flex border border-slate-200 bg-slate-50 p-0.5">
                      {[
                        ["candlestick", "K線"],
                        ["line", "折線"],
                      ].map(([key, labelText]) => (
                        <button
                          key={key}
                          type="button"
                          onClick={() => setProfessionalChartStyle(key as ProfessionalChartStyle)}
                          className={[
                            "h-7 px-2 text-xs font-semibold transition",
                            professionalChartStyle === key
                              ? "bg-slate-900 text-white"
                              : "text-slate-600 hover:bg-white hover:text-slate-950",
                          ].join(" ")}
                        >
                          {labelText}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <button
                      type="button"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className="h-8 border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-800 hover:border-slate-900 hover:text-slate-950"
                    >
                      技術指標
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      setIndicatorMenuOpen(false);
                      setChartDrawingTool("cursor");
                      setChartFocusMode(false);
                    }}
                    className="h-8 border border-slate-900 bg-slate-900 px-3 text-xs font-semibold text-white hover:bg-slate-800"
                  >
                    總覽
                  </button>
                </div>
              </div>

              <div className="mt-2 flex flex-wrap items-center justify-end gap-1.5 border-t border-slate-100 pt-2">
                <div className="flex max-w-full flex-wrap items-center justify-end gap-1 border border-slate-200 bg-slate-50 p-0.5">
                  {chartDrawingToolGroups.map((group, groupIndex) => (
                    <div
                      key={group.key}
                      className={[
                        "flex items-center gap-0.5",
                        groupIndex > 0 ? "border-l border-slate-200 pl-1" : "",
                      ].join(" ")}
                    >
                      {group.tools.map((toolKey) => {
                        const option = chartDrawingToolOptionMap.get(toolKey);
                        if (!option) return null;

                        return (
                          <button
                            key={option.key}
                            type="button"
                            onClick={() => {
                              setIndicatorMenuOpen(false);
                              setChartDrawingTool(option.key);
                              if (option.key === "cursor") {
                                setSelectedChartDrawingId(null);
                              }
                            }}
                            className={[
                              "h-7 px-2 text-xs font-semibold transition",
                              chartDrawingTool === option.key
                                ? "bg-slate-900 text-white"
                                : "text-slate-600 hover:bg-white hover:text-slate-950",
                            ].join(" ")}
                          >
                            {option.label}
                          </button>
                        );
                      })}
                    </div>
                  ))}
                  <div className="flex items-center gap-0.5 border-l border-slate-200 pl-1">
                    <button
                      type="button"
                      title="Undo (Ctrl+Z)"
                      disabled={!canUndoChartDrawing}
                      onClick={undoChartDrawing}
                      className={[
                        "h-7 px-2 text-xs font-semibold transition",
                        canUndoChartDrawing
                          ? "text-slate-600 hover:bg-white hover:text-slate-950"
                          : "cursor-not-allowed text-slate-300",
                      ].join(" ")}
                    >
                      Undo
                    </button>
                    <button
                      type="button"
                      title="Redo (Ctrl+Y)"
                      disabled={!canRedoChartDrawing}
                      onClick={redoChartDrawing}
                      className={[
                        "h-7 px-2 text-xs font-semibold transition",
                        canRedoChartDrawing
                          ? "text-slate-600 hover:bg-white hover:text-slate-950"
                          : "cursor-not-allowed text-slate-300",
                      ].join(" ")}
                    >
                      Redo
                    </button>
                    <button
                      type="button"
                      disabled={!activeSelectedChartDrawingId}
                      onClick={deleteSelectedChartDrawing}
                      className={[
                        "h-7 px-2 text-xs font-semibold transition",
                        activeSelectedChartDrawingId
                          ? "text-red-700 hover:bg-white"
                          : "cursor-not-allowed text-slate-300",
                      ].join(" ")}
                    >
                      刪除
                    </button>
                    <button
                      type="button"
                      disabled={chartDrawings.length === 0}
                      onClick={clearChartDrawings}
                      className={[
                        "h-7 px-2 text-xs font-semibold transition",
                        chartDrawings.length > 0
                          ? "text-slate-500 hover:bg-white hover:text-slate-950"
                          : "cursor-not-allowed text-slate-300",
                      ].join(" ")}
                    >
                      畫線 {chartDrawings.length}
                    </button>
                    <span className="hidden h-7 items-center border-l border-slate-200 px-2 text-[11px] font-semibold tabular-nums text-slate-400 min-[1500px]:inline-flex">
                      {chartDrawingHistory.past.length}/{chartDrawingHistory.future.length}
                    </span>
                  </div>
                </div>
              </div>
              {indicatorMenuOpen ? (
                <div className="relative h-0">
                  <TechnicalIndicatorMenu
                    indicators={chartIndicators}
                    activeTemplate={activeIndicatorTemplate}
                    onApplyTemplate={applyIndicatorTemplate}
                    onToggleIndicator={toggleChartIndicator}
                    includeParameters
                    parameters={indicatorParameters}
                    onUpdateParameter={updateIndicatorParameter}
                    className="w-[25rem]"
                  />
                </div>
              ) : null}
            </div>
          ) : (
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                {isIndexProduct ? "Index" : "Stock"}
              </div>
              <h2 className="mt-1 text-2xl font-bold text-slate-950">
                {stockId} {indexProduct?.stockName ?? stockName ?? stockInfo?.stock_name ?? ""}
              </h2>
              <div className="mt-1 text-sm text-slate-500">
                {indexProduct
                  ? `${indexProduct.market} · 指數 · ${indexProduct.symbol}`
                  : `${stockInfo?.market ?? "-"} · ${stockInfo?.industry ?? "未分類"}`}{" "}
                ·{" "}
                {displayTime}
              </div>
            </div>

            <div className="flex items-start gap-5">
              <div
                className={`flex flex-wrap items-center justify-end gap-x-2 gap-y-1 text-right ${priceLimitTone(
                  headerLimitStatus,
                  latestChange
                )}`}
              >
                <PriceUpdatePulse
                  value={latestClose}
                  direction={latestChange}
                  resetKey={`${stockId ?? "empty"}:${effectiveTimeframe}`}
                  className={[
                    "text-4xl font-bold leading-none tracking-normal tabular-nums",
                    priceLimitBoxClass(headerLimitStatus),
                  ].join(" ")}
                >
                  {formatPrice(latestClose)}
                </PriceUpdatePulse>
                <span className="text-base font-semibold tabular-nums">
                  {formatSignedPointChange(latestChange)}
                </span>
                {latestChangePct !== null && latestChangePct !== undefined ? (
                  <span className="text-base font-semibold tabular-nums">
                    ({formatPct(latestChangePct)})
                  </span>
                ) : null}
              </div>

              <div className="flex flex-col items-end gap-2">
                <div className="flex border border-slate-200 bg-slate-50 p-1">
                  {availableTimeframes.map((item) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => {
                        setTimeframe(item);
                        setIndicatorMenuOpen(false);
                        if (item === "today") {
                          setChartFocusMode(false);
                        }
                      }}
                      className={[
                        "h-8 min-w-12 px-3 text-sm font-semibold transition",
                        effectiveTimeframe === item
                          ? "bg-red-700 text-white"
                          : "text-slate-600 hover:bg-white",
                      ].join(" ")}
                    >
                      {timeframeLabels[item]}
                    </button>
                  ))}
                </div>

                {effectiveTimeframe === "today" ? (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className="h-8 border border-slate-900 bg-white px-3 text-sm font-semibold text-slate-900 hover:border-red-700 hover:text-red-700"
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
                ) : (
                  <div className="flex items-start gap-2">
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => setIndicatorMenuOpen((value) => !value)}
                        className="h-8 border border-slate-900 bg-white px-3 text-sm font-semibold text-slate-900 hover:border-red-700 hover:text-red-700"
                      >
                        指標
                      </button>
                      {indicatorMenuOpen ? (
                        <TechnicalIndicatorMenu
                          indicators={chartIndicators}
                          activeTemplate={activeIndicatorTemplate}
                          onApplyTemplate={applyIndicatorTemplate}
                          onToggleIndicator={toggleChartIndicator}
                          includeParameters
                          parameters={indicatorParameters}
                          onUpdateParameter={updateIndicatorParameter}
                          className="w-[26rem]"
                        />
                      ) : null}
                    </div>
                    <button
                      type="button"
                      disabled={!canUseFocusedKLine}
                      onClick={() => {
                        setIndicatorMenuOpen(false);
                        setProfessionalTimeframe(effectiveTimeframe as ChartTimeframe);
                        setChartFocusMode((value) => !value);
                      }}
                      className={[
                        "h-8 border px-3 text-sm font-semibold transition",
                        chartFocusMode
                          ? "border-slate-900 bg-slate-900 text-white hover:bg-slate-800"
                          : "border-slate-300 bg-white text-slate-700 hover:border-slate-900 hover:text-slate-950",
                        !canUseFocusedKLine
                          ? "cursor-not-allowed border-slate-200 bg-slate-50 text-slate-300 hover:border-slate-200 hover:text-slate-300"
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {chartFocusMode ? "總覽" : "放大"}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          )}

          {errorMessage ? (
            <div className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-700">
              {errorMessage}
            </div>
          ) : null}
          {chartHistoryMessage && !errorMessage ? (
            <div className="border-b border-amber-200 bg-amber-50 px-5 py-2 text-xs text-amber-800">
              {chartHistoryMessage}
            </div>
          ) : null}

          {chartFocusMode ? (
            professionalChartReady ? (
              <LightweightKLineChart
                chartData={professionalChartData}
                indicatorData={professionalIsIntraday ? [] : indicatorForTimeframe}
                label={professionalTimeframeLabel}
                height={780}
                fillViewport
                timeMode={professionalIsIntraday ? "intraday" : "date"}
                chartStyle={professionalChartStyle}
                showHeader={false}
                showMovingAverages={chartIndicators.ma}
                indicators={chartIndicators}
                indicatorParameters={indicatorParameters}
                volumePanelLabel={isIndexProduct ? "成交金額(億)" : "成交量(張)"}
                volumeValueKey={isIndexProduct ? "trade_value" : "volume"}
                drawingTool={chartDrawingTool}
                drawings={chartDrawings}
                selectedDrawingId={activeSelectedChartDrawingId}
                onDrawingsChange={updateChartDrawings}
                onSelectedDrawingChange={setSelectedChartDrawingId}
              />
            ) : (
              <EmptyDataState message={`讀取${professionalTimeframeLabel}資料中...`} />
            )
          ) : effectiveTimeframe === "today" ? (
            <IntradayTrendChart
              points={todayTrend}
              previousClose={todayPreviousClose}
              label={timeframeLabels[effectiveTimeframe]}
              source={todaySource}
              indicators={intradayIndicators}
              revealKey={`${stockId}:${effectiveTimeframe}`}
              refreshIntervalMs={TAIWAN_INTRADAY_REFRESH_MS}
              updatedAt={todayUpdatedAt}
            />
          ) : currentChartReady ? (
            <StockKLineChart
              chartData={chartData}
              indicatorData={indicatorForTimeframe}
              label={timeframeLabels[effectiveTimeframe]}
              indicators={chartIndicators}
              indicatorParameters={indicatorParameters}
              revealKey={`${stockId}:${effectiveTimeframe}`}
              volumePanelLabel={isIndexProduct ? "成交金額(億)" : undefined}
              volumeTooltipLabel={isIndexProduct ? "成交金額(億)" : undefined}
              volumeValueKey={isIndexProduct ? "trade_value" : "volume"}
              volumeValueFormatter={isIndexProduct ? formatTradeValueYi : undefined}
            />
          ) : (
            <EmptyDataState message={`讀取${timeframeLabels[effectiveTimeframe]}資料中...`} />
          )}
        </div>

        {!chartFocusMode && isIndexProduct ? (
          <IndexDetailDataPanel
            index={selectedIndexSnapshot}
            timeframe={effectiveTimeframe}
            latestChart={latestChart}
            todayStats={todayStats}
            todayPreviousClose={todayPreviousClose}
            marketChip={marketChip}
            marketChipLoadState={marketChipLoadState}
            contributions={indexContributions}
            contributionLoadState={indexContributionLoadState}
          />
        ) : !chartFocusMode && watchlistRankingPanel ? (
          <div className="min-w-0">{watchlistRankingPanel}</div>
        ) : null}
      </div>

      {!chartFocusMode ? (
      <aside
        className="flex min-w-0 flex-col border border-slate-200 bg-white"
      >
        {isIndexProduct ? (
          <IndexListPanel
            items={indexList}
            loadState={indexListLoadState}
            marketLabel={indexProduct?.market === "TPEX" ? "上櫃" : "上市"}
          />
        ) : showTechnicalLoading ? (
          <TechnicalLoadingPanel />
        ) : (
          <>
            <div className="omi-technical-summary border-b border-slate-200 px-5 py-3">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                Technical
              </div>
              <div className="mt-1.5 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-xl font-bold text-slate-950">{technicalStatus}</div>
                  <div className="mt-0.5 text-xs leading-4 text-slate-500">{technicalSummaryText}</div>
                </div>
                <div className={`omi-technical-score shrink-0 text-right text-lg font-bold ${valueTone(technicalReport.value)}`}>
                  <PriceUpdatePulse
                    value={technicalReport.value}
                    direction={technicalReport.value}
                    resetKey={`${stockId ?? "empty"}:technical:${effectiveTimeframe}`}
                    className="justify-end tabular-nums"
                  >
                    {formatPct(technicalReport.value)}
                  </PriceUpdatePulse>
                  <div className="text-xs font-medium text-slate-500">{technicalReport.valueLabel}</div>
                </div>
              </div>
            </div>

            <div className="px-5 py-3">
              <div>
                {technicalReport.rows.map((row) => (
                  <TechnicalSignalRow
                    key={row.title}
                    title={row.title}
                    description={row.description}
                    value={row.value}
                    pulseValue={row.pulseValue}
                    direction={row.direction}
                    tone={row.tone}
                  />
                ))}
              </div>

              <OvernightImpactPanel
                report={displayOvernightImpact}
                loadState={displayOvernightImpactLoadState}
              />

              <div className="mt-3 border-t border-slate-200 pt-3">
                <div className="omi-technical-market flex items-start justify-between gap-4 text-xs">
                  <div>
                    <div className="font-bold uppercase tracking-[0.14em] text-slate-500">
                      Market
                    </div>
                    <div className="mt-0.5 text-sm font-bold text-slate-950">
                      {primaryMarketIndex?.short_label ?? "大盤"}
                    </div>
                    <div className="mt-0.5 text-slate-500">{marketRegimeLabel(primaryMarketIndex)}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-bold text-slate-950">{formatPrice(primaryMarketIndex?.close)}</div>
                    <div className={valueTone(primaryMarketIndex?.change_pct)}>
                      {formatPct(primaryMarketIndex?.change_pct)}
                    </div>
                  </div>
                </div>
              </div>

              {visibleSignals.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {visibleSignals.map((signal) => (
                    <span
                      key={signal.label}
                      className={`omi-technical-badge px-2.5 py-1 text-xs font-semibold ${signal.tone}`}
                    >
                      {signal.label}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </>
        )}

        {!isIndexProduct ? (
          <div className="border-t border-slate-200 bg-white">
            <div
              aria-hidden="true"
              className="h-2 border-b border-slate-200 bg-slate-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)]"
            />

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
                </div>
              </div>

              <div className="mt-4">{renderActiveDataTab()}</div>
            </div>
          </div>
        ) : null}

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
      ) : null}

    </section>
  );
}

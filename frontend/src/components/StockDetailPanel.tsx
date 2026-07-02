"use client";

import IntradayTrendChart, {
  defaultIntradayIndicators,
  intradayIndicatorOptions,
  type IntradayIndicatorKey,
  type IntradayIndicatorSettings,
} from "@/components/IntradayTrendChart";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import ProfessionalChartPanel, {
  type ProfessionalChartStyle,
} from "@/components/ProfessionalChartPanel";
import StockKLineChart, {
  defaultIndicatorParameters,
  defaultIndicators,
  professionalIndicatorCategoryGroups,
  type IndicatorParameters,
  type IndicatorKey,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
import type { ChartDrawing, ChartDrawingTool } from "@/components/LightweightKLineChart";
import StockDetailDataPanel from "@/components/stock-detail/StockDetailDataPanel";
import QuoteDepthPanel from "@/components/stock-detail/QuoteDepthPanel";
import {
  dataPanelTabs,
  minimumUsableFinancialRows,
  minimumUsableRevenueRows,
} from "@/components/stock-detail/StockDetailPanelConstants";
import TechnicalIndicatorMenu, {
  indicatorTemplates,
  type IndicatorTemplateKey,
} from "@/components/stock-detail/TechnicalIndicatorMenu";
import {
  ChipMetricBlock,
  DataTabButton,
  EmptyDataState,
  IndexDetailDataPanel,
  IndexListPanel,
  MetricRow,
  OvernightImpactPanel,
  TechnicalLoadingPanel,
  TechnicalSignalRow,
  aggregateProfessionalIntradayBars,
  averageRecentChartClose,
  averageRecentChartValue,
  buildEarningsSeries,
  buildRevenueSeries,
  chartWindowStats,
  estimatedPriceLimitStatus,
  fetchOptional,
  finiteNumber,
  formatBackfillOutcome,
  formatDate,
  formatDateTime,
  formatIndicatorValue,
  formatLots,
  formatNumber,
  formatPanelJobProgress,
  formatPct,
  formatPrice,
  formatRatioPct,
  formatSignedLots,
  formatSignedNumber,
  formatSignedPointChange,
  formatTradeValueYi,
  isProfessionalIntradayTimeframe,
  latestLargeHolderSummary,
  localizeTechnicalReport,
  mapBackendTechnicalReport,
  marketRegimeLabel,
  priceLimitBoxClass,
  priceLimitTone,
  professionalIntradayMinutes,
  safeRatio,
  shareholdingLevelRanges,
  shiftIsoDate,
  summarizeIntradayPoints,
  sumRecentInstitutionalNet,
  valueTone,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  BranchTableSide,
  ChartTimeframe,
  DataPanelTab,
  EarningsView,
  InstitutionalSeriesPoint,
  LoadState,
  ProfessionalIntradayTimeframe,
  ProfessionalTimeframe,
  RevenueView,
  ShareholdingSeriesPoint,
  TechnicalReport,
  TechnicalReportBadge,
  TechnicalReportRow,
  TechnicalTone,
  Timeframe,
} from "@/components/stock-detail/StockDetailDataViews";
import {
  buildChartDrawingSnapshotPayload,
  chartDrawingApiPath,
  chartDrawingSnapshotsEqual,
  chartDrawingSyncDelayMs,
  createChartDrawingSnapshot,
  loadChartDrawings,
  normalizeChartDrawingSelection,
  normalizeStoredChartDrawings,
  saveChartDrawings,
  serializeChartDrawings,
  type ChartDrawingHistoryState,
  type ChartDrawingStorageState,
} from "@/components/professionalChartDrawing";
import { fetchJson, requestJson } from "@/lib/api";
import { getJobResultStatus, requestBackfillJob } from "@/lib/jobs";
import {
  getMarketCalendarStatusSnapshot,
  refreshMarketCalendarStatus,
  type MarketCalendarMarketStatus,
} from "@/lib/marketCalendarStatus";
import {
  getRefreshExecutionSeconds,
  useRefreshExecutionSettings,
} from "@/lib/refreshExecutionSettings";
import { timeframeLabel, useT, type TranslationFunction } from "@/i18n";
import {
  TAIWAN_INTRADAY_REFRESH_MS,
  TAIWAN_SESSION_START_MINUTES,
  getTaipeiMinutesOfDay,
  getTaiwanMarketRefreshState,
} from "@/lib/taiwanMarketTime";
import {
  getTaiwanChartHistoryRequirement,
  getTaiwanDataPanelRefreshProfile,
  taiwanDailyPriceBackfillPath,
  taiwanSelectionRefreshPath,
  type TaiwanChartTimeframe,
  type TaiwanRefreshProfile,
} from "@/lib/taiwanMarketRules";
import type {
  BrokerBranchTradeDailySummaryRead,
  ChartDrawingSnapshotRead,
  ChartPoint,
  FinancialMetricQuarterlyRead,
  IntradayHistoryResponse,
  IntradayTrendPoint,
  IntradayTrendResponse,
  InstitutionalHoldingRatioRead,
  InstitutionalTradeDailyRead,
  MarginTradingDailyRead,
  MarketChipDaily,
  MarketIndexContributionResponse,
  MarketIndexListItem,
  MarketIndexListResponse,
  MarketIndexSummary,
  MonthlyRevenueRead,
  OhlcChartResponse,
  OvernightImpactRead,
  ShareholdingDistributionWeeklyRead,
  StockChipCoverageRead,
  StockIndicatorPoint,
  StockMasterRead,
  StockTechnicalReportRead,
  TaiwanStockQuoteDepthPreviewMode,
  TaiwanStockQuoteDepthRead,
} from "@/types/market";
import {
  type ReactNode,
  useCallback,
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
  marketIndexSummary?: MarketIndexSummary | null;
  onChartFocusModeChange?: (active: boolean) => void;
  quoteDepthPreviewMode?: TaiwanStockQuoteDepthPreviewMode | null;
};

const TAIWAN_DATASET_INSTITUTIONAL_TRADE = "institutional_trade_daily";
const TAIWAN_DATASET_MARGIN_TRADING = "margin_trading_daily";
const TAIWAN_DATASET_BROKER_BRANCH = "broker_branch_trade_daily";
const quoteDepthLivePhases = new Set(["preopen_auction", "regular_live", "closing_auction"]);

function quoteDepthRefreshDelayMs(quoteDepth: TaiwanStockQuoteDepthRead | null) {
  return quoteDepth && quoteDepthLivePhases.has(quoteDepth.session_phase)
    ? TAIWAN_INTRADAY_REFRESH_MS
    : 60_000;
}

function dataPanelCacheKey(stockId: string, tab: DataPanelTab, branchDays = 1) {
  return tab === "branch" ? `${stockId}:${tab}:${branchDays}` : `${stockId}:${tab}`;
}

function normalizeIsoDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : null;
}

function isIsoDateOnOrAfter(
  value: string | null | undefined,
  expected: string | null | undefined
) {
  const normalizedValue = normalizeIsoDate(value);
  const normalizedExpected = normalizeIsoDate(expected);

  if (!normalizedExpected) return true;
  if (!normalizedValue) return false;

  return normalizedValue >= normalizedExpected;
}

function maxIsoDate(values: Array<string | null | undefined>) {
  let latest: string | null = null;

  for (const value of values) {
    const normalized = normalizeIsoDate(value);
    if (normalized && (!latest || normalized > latest)) {
      latest = normalized;
    }
  }

  return latest;
}

function expectedTaiwanDatasetDate(
  calendarStatus: MarketCalendarMarketStatus | null,
  datasetKey: string
) {
  return normalizeIsoDate(
    calendarStatus?.release_windows?.[datasetKey]?.expected_trade_date ?? null
  );
}

function taiwanCalendarStatusRefreshKey(
  calendarStatus: MarketCalendarMarketStatus | null
) {
  if (!calendarStatus) return "none";

  return [
    calendarStatus.date,
    expectedTaiwanDatasetDate(calendarStatus, TAIWAN_DATASET_INSTITUTIONAL_TRADE),
    expectedTaiwanDatasetDate(calendarStatus, TAIWAN_DATASET_MARGIN_TRADING),
    expectedTaiwanDatasetDate(calendarStatus, TAIWAN_DATASET_BROKER_BRANCH),
  ].join("|");
}

const institutionalLookbackDays = 100;
const institutionalHistoryLimit = 120;
const revenueHistoryLimit = 120;
const financialHistoryLimit = 40;
const allTimeframes: Timeframe[] = ["today", "daily", "weekly", "monthly"];
const professionalTimeframeOptions: ProfessionalTimeframe[] = [
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "4h",
  "daily",
  "weekly",
  "monthly",
];
const chartBarsByTimeframe: Record<ChartTimeframe, number> = {
  daily: 2600,
  weekly: 520,
  monthly: 132,
};
const dailyIndicatorLimit = 220;
const openingObservationMinutes = 5;
const openingObservationMinPoints = 5;

function shouldIncludeTaiwanOhlcIntraday() {
  const marketState = getTaiwanMarketRefreshState();

  return (
    marketState.isPollingWindow ||
    (marketState.isAfterClose && !marketState.isDailyPriceReleased)
  );
}

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

type StockSignalTone = "positive" | "negative" | "warning" | "neutral";

type StockSignalChip = {
  key: string;
  source: string;
  label: string;
  tone: StockSignalTone;
  title?: string;
};

function stockSignalToneClass(tone: StockSignalTone) {
  if (tone === "positive") return "omi-signal-chip-positive";
  if (tone === "negative") return "omi-signal-chip-negative";
  if (tone === "warning") return "omi-signal-chip-warning";
  return "omi-signal-chip-neutral";
}

function stockSignalToneFromNumber(value: number | null | undefined): StockSignalTone {
  if (!finiteNumber(value)) return "neutral";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "neutral";
}

function stockSignalToneFromTechnical(tone: TechnicalTone | undefined): StockSignalTone {
  if (tone === "positive" || tone === "negative" || tone === "warning") return tone;
  return "neutral";
}

function addStockSignalChip(
  chips: StockSignalChip[],
  chip: StockSignalChip | null
) {
  if (!chip || !chip.label || chips.some((item) => item.key === chip.key)) return;
  chips.push(chip);
}

function findTechnicalRow(report: TechnicalReport, title: string) {
  return report.rows.find((row) => row.title.includes(title)) ?? null;
}

function findTechnicalRowByKey(report: TechnicalReport, key: string) {
  return report.rows.find((row) => row.key === key) ?? null;
}

function findTechnicalBadge(report: TechnicalReport, patterns: string[]) {
  return (
    report.badges.find((badge) =>
      patterns.some((pattern) => badge.label.includes(pattern))
    ) ?? null
  );
}

function stockSignalToneFromBadgeLabel(label: string): StockSignalTone {
  const normalized = label.toLowerCase();
  if (
    label.includes("過熱") ||
    label.includes("放量") ||
    label.includes("高位") ||
    normalized.includes("overheated") ||
    normalized.includes("surge") ||
    normalized.includes("high")
  ) {
    return "warning";
  }

  if (
    label.includes("跌破") ||
    label.includes("偏弱") ||
    label.includes("衰退") ||
    label.includes("減少") ||
    normalized.includes("below") ||
    normalized.includes("weak") ||
    normalized.includes("decline") ||
    normalized.includes("decrease")
  ) {
    return "negative";
  }

  if (
    label.includes("站上") ||
    label.includes("偏多") ||
    label.includes("成長") ||
    label.includes("增加") ||
    label.includes("走升") ||
    normalized.includes("above") ||
    normalized.includes("bullish") ||
    normalized.includes("growth") ||
    normalized.includes("increase") ||
    normalized.includes("rising")
  ) {
    return "positive";
  }

  return "neutral";
}

function usableTechnicalRowValue(row: TechnicalReportRow | null) {
  const value = row?.value?.trim();
  return value && value !== "-" ? value : null;
}

function signedTextTone(valueText: string | null): StockSignalTone {
  if (!valueText) return "neutral";
  if (valueText.trim().startsWith("+")) return "positive";
  if (valueText.trim().startsWith("-")) return "negative";
  return "neutral";
}

function signedLabelFromValue(valueText: string, positiveLabel: string, negativeLabel: string, neutralLabel: string) {
  if (valueText.trim().startsWith("+")) return positiveLabel;
  if (valueText.trim().startsWith("-")) return negativeLabel;
  return neutralLabel;
}

function stockTechnicalText(
  t: TranslationFunction,
  key: string,
  values?: Record<string, string | number | null | undefined>
) {
  return t(`stockDetail.dataViews.technical.${key}`, values);
}

function stockTechnicalTerm(t: TranslationFunction, key: string) {
  return stockTechnicalText(t, `terms.${key}`);
}

function withLotsUnit(value: string, t: TranslationFunction) {
  if (value === "-") return value;
  return `${value}${t("stockDetail.dataPanel.units.lots")}`;
}

function formatSignedLotsWithUnit(value: number | null | undefined, t: TranslationFunction) {
  return withLotsUnit(formatSignedLots(value), t);
}

function extractSignedNumberAfter(text: string | null | undefined, keyword: string) {
  if (!text) return null;

  const index = text.indexOf(keyword);
  if (index < 0) return null;
  const tail = text.slice(index + keyword.length);
  const match = tail.match(/[+-]?\d[\d,]*(?:\.\d+)?/);
  if (!match) return null;

  const value = Number(match[0].replace(/,/g, ""));
  return Number.isFinite(value) ? value : null;
}

function buildStockSignalChips({
  technicalReport,
  institutional,
  margin,
  monthlyRevenue,
  overnightImpact,
  relativeToPrimaryIndex,
  primaryMarketLabel,
  t,
}: {
  technicalReport: TechnicalReport;
  institutional: InstitutionalTradeDailyRead | null;
  margin: MarginTradingDailyRead | null;
  monthlyRevenue: MonthlyRevenueRead | null;
  overnightImpact: OvernightImpactRead | null;
  relativeToPrimaryIndex: number | null;
  primaryMarketLabel: string;
  t: TranslationFunction;
}) {
  const chips: StockSignalChip[] = [];
  const trendBadge = findTechnicalBadge(technicalReport, ["MA20", "Trend", "trend", "月線", "週線"]);
  const momentumBadge = findTechnicalBadge(technicalReport, ["MACD", "RSI", "Momentum", "動能"]);
  const volumeBadge = findTechnicalBadge(technicalReport, ["Volume", "volume", "放量", "量能"]);
  const trendRow =
    findTechnicalRowByKey(technicalReport, "trend_structure") ??
    findTechnicalRowByKey(technicalReport, "daily_background") ??
    findTechnicalRow(technicalReport, "趨勢") ??
    findTechnicalRow(technicalReport, "Trend") ??
    findTechnicalRow(technicalReport, "Background");
  const momentumRow =
    findTechnicalRowByKey(technicalReport, "momentum") ??
    findTechnicalRow(technicalReport, "動能") ??
    findTechnicalRow(technicalReport, "Momentum");
  const volumeRow =
    findTechnicalRowByKey(technicalReport, "volume_flow") ??
    findTechnicalRowByKey(technicalReport, "volume_pace") ??
    findTechnicalRow(technicalReport, "量價") ??
    findTechnicalRow(technicalReport, "量能") ??
    findTechnicalRow(technicalReport, "Volume");
  const institutionalRow =
    findTechnicalRowByKey(technicalReport, "institutional_flow") ??
    findTechnicalRow(technicalReport, "法人") ??
    findTechnicalRow(technicalReport, "Institutional");
  const institutionalRowValue = usableTechnicalRowValue(institutionalRow);
  const rowMarginBalanceChange = extractSignedNumberAfter(
    institutionalRow?.description,
    "融資餘額"
  ) ?? extractSignedNumberAfter(institutionalRow?.description, "margin balance");
  const marginTodayBalance = margin?.margin_today_balance ?? null;
  const marginPreviousBalance = margin?.margin_previous_balance ?? null;
  const marginBalanceChange =
    finiteNumber(marginTodayBalance) && finiteNumber(marginPreviousBalance)
      ? marginTodayBalance - marginPreviousBalance
      : rowMarginBalanceChange;
  const institutionalNet = institutional?.total_institutional_net ?? null;
  const revenueGrowth = monthlyRevenue?.year_over_year_pct ?? null;
  const overnightChange = overnightImpact?.weighted_change_pct ?? null;

  addStockSignalChip(chips, {
    key: "classification",
    source: stockTechnicalText(t, "chips.sources.classification"),
    label: technicalReport.title,
    tone: stockSignalToneFromNumber(technicalReport.value),
    title: technicalReport.summary,
  });

  addStockSignalChip(chips, {
    key: "trend",
    source: stockTechnicalText(t, "chips.sources.trend"),
    label:
      trendBadge?.label ??
      (trendRow?.value && trendRow.value !== "-" ? `${trendRow.title} ${trendRow.value}` : ""),
    tone: trendBadge
      ? stockSignalToneFromBadgeLabel(trendBadge.label)
      : stockSignalToneFromTechnical(trendRow?.tone),
    title: trendRow?.description,
  });

  addStockSignalChip(chips, {
    key: "momentum",
    source: stockTechnicalText(t, "chips.sources.momentum"),
    label:
      momentumBadge?.label ??
      (momentumRow?.direction !== null && momentumRow?.direction !== undefined
        ? momentumRow.direction >= 0
          ? stockTechnicalTerm(t, "macdBullish")
          : stockTechnicalTerm(t, "macdWeak")
        : ""),
    tone: momentumBadge
      ? stockSignalToneFromBadgeLabel(momentumBadge.label)
      : stockSignalToneFromTechnical(momentumRow?.tone),
    title: momentumRow?.description,
  });

  addStockSignalChip(chips, {
    key: "volume",
    source: stockTechnicalText(t, "chips.sources.volume"),
    label:
      volumeBadge?.label ??
      (volumeRow?.value && volumeRow.value !== "-"
        ? stockTechnicalText(t, "chips.volumeValue", { value: volumeRow.value })
        : ""),
    tone: volumeBadge
      ? stockSignalToneFromBadgeLabel(volumeBadge.label)
      : stockSignalToneFromTechnical(volumeRow?.tone),
    title: volumeRow?.description,
  });

  if (finiteNumber(institutionalNet) || institutionalRowValue) {
    addStockSignalChip(chips, {
      key: "institutional",
      source: stockTechnicalText(t, "chips.sources.chip"),
      label: finiteNumber(institutionalNet)
        ? `${
            institutionalNet > 0
              ? stockTechnicalTerm(t, "institutionalBuy")
              : institutionalNet < 0
                ? stockTechnicalTerm(t, "institutionalSell")
                : stockTechnicalTerm(t, "institutionalFlat")
          } ${formatSignedLotsWithUnit(institutionalNet, t)}`
        : `${signedLabelFromValue(
            institutionalRowValue ?? "",
            stockTechnicalTerm(t, "institutionalBuy"),
            stockTechnicalTerm(t, "institutionalSell"),
            stockTechnicalTerm(t, "institutionalFlat")
          )} ${institutionalRowValue}`,
      tone: finiteNumber(institutionalNet)
        ? stockSignalToneFromNumber(institutionalNet)
        : signedTextTone(institutionalRowValue),
      title: finiteNumber(institutionalNet)
        ? stockTechnicalText(t, "chips.latestInstitutionalTotal", {
            value: formatSignedLotsWithUnit(institutionalNet, t),
          })
        : institutionalRow?.description,
    });
  }

  if (finiteNumber(marginBalanceChange)) {
    addStockSignalChip(chips, {
      key: "margin",
      source: stockTechnicalText(t, "chips.sources.margin"),
      label:
        marginBalanceChange > 0
          ? stockTechnicalText(t, "chips.marginIncrease", {
              value: formatSignedNumber(marginBalanceChange),
            })
          : marginBalanceChange < 0
            ? stockTechnicalText(t, "chips.marginDecrease", {
                value: formatSignedNumber(marginBalanceChange),
              })
            : stockTechnicalTerm(t, "marginFlat"),
      tone: marginBalanceChange > 0 ? "warning" : stockSignalToneFromNumber(-marginBalanceChange),
      title: stockTechnicalText(t, "chips.marginBalanceChange", {
        value: formatSignedNumber(marginBalanceChange),
      }),
    });
  }

  if (finiteNumber(revenueGrowth)) {
    addStockSignalChip(chips, {
      key: "revenue",
      source: stockTechnicalText(t, "chips.sources.revenue"),
      label:
        revenueGrowth > 0
          ? stockTechnicalText(t, "chips.revenueGrowth", { value: formatPct(revenueGrowth) })
          : revenueGrowth < 0
            ? stockTechnicalText(t, "chips.revenueDecline", { value: formatPct(revenueGrowth) })
            : stockTechnicalTerm(t, "revenueFlat"),
      tone: stockSignalToneFromNumber(revenueGrowth),
      title: stockTechnicalText(t, "chips.monthlyRevenueYoy", {
        value: formatPct(revenueGrowth),
      }),
    });
  }

  if (finiteNumber(overnightChange)) {
    addStockSignalChip(chips, {
      key: "overnight",
      source: stockTechnicalText(t, "chips.sources.overnight"),
      label:
        overnightChange > 0
          ? stockTechnicalText(t, "chips.usBullish", { value: formatPct(overnightChange) })
          : overnightChange < 0
            ? stockTechnicalText(t, "chips.usBearish", { value: formatPct(overnightChange) })
            : stockTechnicalTerm(t, "overnightNeutral"),
      tone: stockSignalToneFromNumber(overnightChange),
      title: stockTechnicalText(t, "chips.overnightImpact", {
        label: stockTechnicalTerm(t, "usOvernightMapping"),
        value: formatPct(overnightChange),
      }),
    });
  }

  if (finiteNumber(relativeToPrimaryIndex)) {
    addStockSignalChip(chips, {
      key: "market-relative",
      source: stockTechnicalText(t, "chips.sources.market"),
      label:
        relativeToPrimaryIndex > 0
          ? stockTechnicalText(t, "chips.strongerThanMarket", {
              value: formatPct(relativeToPrimaryIndex),
            })
          : relativeToPrimaryIndex < 0
            ? stockTechnicalText(t, "chips.weakerThanMarket", {
                value: formatPct(relativeToPrimaryIndex),
              })
            : stockTechnicalTerm(t, "marketInLine"),
      tone: stockSignalToneFromNumber(relativeToPrimaryIndex),
      title: stockTechnicalText(t, "chips.relativeToMarket", {
        market: primaryMarketLabel,
        value: formatPct(relativeToPrimaryIndex),
      }),
    });
  }

  return chips;
}

function chartDrawingStorageKey(stockId: string | null, timeframe: ProfessionalTimeframe) {
  return `omi:tw:chart-drawings:v1:${stockId ?? "empty"}:${timeframe}`;
}

function chartDrawingTimeMode(timeframe: ProfessionalTimeframe) {
  return isProfessionalIntradayTimeframe(timeframe) ? "intraday" : "date";
}

export default function StockDetailPanel({
  stockId,
  stockName,
  initialChartData = [],
  initialIndicatorData = [],
  watchlistRankingPanel,
  marketIndexSummary,
  onChartFocusModeChange,
  quoteDepthPreviewMode = null,
}: Props) {
  const t = useT();
  const refreshExecutionSettings = useRefreshExecutionSettings();
  const taiwanSubresourceRefreshSeconds = getRefreshExecutionSeconds(
    refreshExecutionSettings,
    "tw",
    "subresource_refresh_interval_seconds",
    0.05
  );
  const tRef = useRef(t);
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
  const storedChartDrawings = useMemo(
    () => loadChartDrawings(chartDrawingKey),
    [chartDrawingKey]
  );
  const chartDrawings =
    chartDrawingState.key === chartDrawingKey
      ? chartDrawingState.drawings
      : storedChartDrawings;
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
  const [benchmarkChartData, setBenchmarkChartData] = useState<ChartPoint[]>([]);
  const [benchmarkChartKey, setBenchmarkChartKey] = useState<string | null>(null);
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
  const [quoteDepth, setQuoteDepth] = useState<TaiwanStockQuoteDepthRead | null>(null);
  const [quoteDepthLoadState, setQuoteDepthLoadState] = useState<LoadState>("idle");
  const [taiwanCalendarStatus, setTaiwanCalendarStatus] =
    useState<MarketCalendarMarketStatus | null>(() =>
      getMarketCalendarStatusSnapshot("tw")
    );
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
  const taiwanSubresourceRefreshSecondsRef = useRef(taiwanSubresourceRefreshSeconds);
  const activeStockIdRef = useRef<string | null>(stockId);
  const activeDataTabRef = useRef<DataPanelTab>(activeDataTab);
  const branchDaysRef = useRef(branchDays);
  const dataPanelRequestKeyRef = useRef<string | null>(null);
  const dataPanelResolvedKeysRef = useRef<Set<string>>(new Set());
  const branchSummaryCacheRef = useRef<Map<string, BrokerBranchTradeDailySummaryRead>>(new Map());
  const chartHistoryBackfillKeysRef = useRef<Set<string>>(new Set());
  const chartDrawingSyncTimerRef = useRef<number | null>(null);
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
    tRef.current = t;
  }, [t]);

  useEffect(() => {
    taiwanSubresourceRefreshSecondsRef.current = taiwanSubresourceRefreshSeconds;
  }, [taiwanSubresourceRefreshSeconds]);

  useEffect(() => {
    let cancelled = false;
    let refreshTimer: number | undefined;

    function setCalendarStatusIfChanged(
      nextStatus: MarketCalendarMarketStatus | null
    ) {
      if (cancelled) return;

      setTaiwanCalendarStatus((currentStatus) =>
        taiwanCalendarStatusRefreshKey(currentStatus) ===
        taiwanCalendarStatusRefreshKey(nextStatus)
          ? currentStatus
          : nextStatus
      );
    }

    async function loadTaiwanCalendarStatus() {
      const cachedStatus = getMarketCalendarStatusSnapshot("tw");
      if (!cancelled && cachedStatus) {
        setCalendarStatusIfChanged(cachedStatus);
      }

      try {
        const envelope = await refreshMarketCalendarStatus("tw");
        const nextStatus =
          envelope.markets.tw ?? getMarketCalendarStatusSnapshot("tw");
        setCalendarStatusIfChanged(nextStatus ?? null);
      } catch {
        if (!cancelled && !cachedStatus) {
          setCalendarStatusIfChanged(null);
        }
      } finally {
        if (!cancelled) {
          refreshTimer = window.setTimeout(loadTaiwanCalendarStatus, 60_000);
        }
      }
    }

    void loadTaiwanCalendarStatus();

    return () => {
      cancelled = true;
      if (refreshTimer !== undefined) {
        window.clearTimeout(refreshTimer);
      }
    };
  }, []);

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
  const chartDrawingRemoteMarket = isIndexProduct ? indexMarket : currentStockInfoMarket;
  const benchmarkIndexId =
    !isIndexProduct && stockId ? (currentStockInfoMarket === "TPEX" ? "TPEX" : "TAIEX") : null;
  const benchmarkLabel = benchmarkIndexId === "TPEX" ? "櫃買" : benchmarkIndexId === "TAIEX" ? "加權" : undefined;

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

  const queueChartDrawingRemoteSave = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave: string | null
  ) => {
    if (typeof window === "undefined") return;
    if (!stockId || !chartDrawingRemoteMarket) return;

    const path = chartDrawingApiPath(
      chartDrawingRemoteMarket,
      stockId,
      professionalTimeframe
    );
    const payload = buildChartDrawingSnapshotPayload({
      drawings: drawingsToSave,
      market: chartDrawingRemoteMarket,
      selectedDrawingId: selectedDrawingIdToSave,
      source: "frontend.professional_chart",
      stockName,
      symbol: stockId,
      timeframe: professionalTimeframe,
      timeMode: chartDrawingTimeMode(professionalTimeframe),
    });

    if (chartDrawingSyncTimerRef.current) {
      window.clearTimeout(chartDrawingSyncTimerRef.current);
    }

    chartDrawingSyncTimerRef.current = window.setTimeout(() => {
      void requestJson<ChartDrawingSnapshotRead>(path, {
        method: "PUT",
        body: JSON.stringify(payload),
      }).catch(() => {
        // Best-effort server sync. Local chart drawings remain available via localStorage.
      });
    }, chartDrawingSyncDelayMs);
  }, [chartDrawingRemoteMarket, professionalTimeframe, stockId, stockName]);

  const storeChartDrawings = useCallback((
    drawingsToSave: ChartDrawing[],
    selectedDrawingIdToSave = activeSelectedChartDrawingId
  ) => {
    setChartDrawingState({
      key: chartDrawingKey,
      drawings: drawingsToSave,
    });
    saveChartDrawings(chartDrawingKey, drawingsToSave);
    queueChartDrawingRemoteSave(drawingsToSave, selectedDrawingIdToSave);
  }, [
    activeSelectedChartDrawingId,
    chartDrawingKey,
    queueChartDrawingRemoteSave,
  ]);

  useEffect(() => {
    return () => {
      if (chartDrawingSyncTimerRef.current && typeof window !== "undefined") {
        window.clearTimeout(chartDrawingSyncTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!chartFocusMode || !stockId || !chartDrawingRemoteMarket) {
      return;
    }

    let cancelled = false;
    const remoteMarket = chartDrawingRemoteMarket;
    const remoteSymbol = stockId;
    const localDrawings = loadChartDrawings(chartDrawingKey);
    const normalizedLocalSelection = normalizeChartDrawingSelection(
      localDrawings,
      activeSelectedChartDrawingId
    );

    if (localDrawings.length > 0) {
      queueChartDrawingRemoteSave(localDrawings, normalizedLocalSelection);
      return () => {
        cancelled = true;
      };
    }

    async function loadRemoteChartDrawings() {
      try {
        const snapshot = await fetchJson<ChartDrawingSnapshotRead>(
          chartDrawingApiPath(remoteMarket, remoteSymbol, professionalTimeframe)
        );

        if (cancelled) return;

        const remoteDrawings = normalizeStoredChartDrawings(snapshot.drawings);
        if (remoteDrawings.length === 0) return;

        const remoteSelection = normalizeChartDrawingSelection(
          remoteDrawings,
          snapshot.selected_drawing_id
        );

        setChartDrawingState({
          key: chartDrawingKey,
          drawings: remoteDrawings,
        });
        saveChartDrawings(chartDrawingKey, remoteDrawings);
        setSelectedChartDrawingId(remoteSelection);
      } catch {
        // A missing remote snapshot simply means this chart has not been saved server-side yet.
      }
    }

    void loadRemoteChartDrawings();

    return () => {
      cancelled = true;
    };
  }, [
    activeSelectedChartDrawingId,
    chartDrawingKey,
    chartDrawingRemoteMarket,
    chartFocusMode,
    professionalTimeframe,
    queueChartDrawingRemoteSave,
    stockId,
  ]);

  function updateChartDrawingState(
    nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
    nextSelectedDrawingId?: string | null,
    options: { recordHistory?: boolean } = {}
  ) {
    const nextDrawings =
      typeof nextValue === "function" ? nextValue(chartDrawings) : nextValue;
    const currentSnapshot = createChartDrawingSnapshot(
      chartDrawings,
      activeSelectedChartDrawingId
    );
    const nextSnapshot = createChartDrawingSnapshot(
      nextDrawings,
      nextSelectedDrawingId === undefined
        ? activeSelectedChartDrawingId
        : nextSelectedDrawingId
    );

    if (chartDrawingSnapshotsEqual(currentSnapshot, nextSnapshot)) {
      return;
    }

    if (
      serializeChartDrawings(currentSnapshot.drawings) ===
      serializeChartDrawings(nextSnapshot.drawings)
    ) {
      setSelectedChartDrawingId(nextSnapshot.selectedDrawingId);
      return;
    }

    if (options.recordHistory !== false) {
      const currentPast =
        chartDrawingHistoryState.key === chartDrawingKey ? chartDrawingHistoryState.past : [];

      setChartDrawingHistoryState({
        key: chartDrawingKey,
        past: [...currentPast, currentSnapshot].slice(-50),
        future: [],
      });
    }

    storeChartDrawings(nextSnapshot.drawings, nextSnapshot.selectedDrawingId);
    setSelectedChartDrawingId(nextSnapshot.selectedDrawingId);
  }

  function updateChartDrawings(
    nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
    options: { recordHistory?: boolean } = {}
  ) {
    updateChartDrawingState(nextValue, undefined, options);
  }

  const undoChartDrawing = useCallback(() => {
    if (!canUndoChartDrawing) return;

    const past = chartDrawingHistory.past;
    const previousSnapshot = past[past.length - 1];

    if (!previousSnapshot) return;

    setChartDrawingHistoryState({
      key: chartDrawingKey,
      past: past.slice(0, -1),
      future: [
        createChartDrawingSnapshot(chartDrawings, activeSelectedChartDrawingId),
        ...chartDrawingHistory.future,
      ].slice(0, 50),
    });
    storeChartDrawings(previousSnapshot.drawings, previousSnapshot.selectedDrawingId);
    setSelectedChartDrawingId(previousSnapshot.selectedDrawingId);
  }, [
    activeSelectedChartDrawingId,
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
      past: [
        ...chartDrawingHistory.past,
        createChartDrawingSnapshot(chartDrawings, activeSelectedChartDrawingId),
      ].slice(-50),
      future: chartDrawingHistory.future.slice(1),
    });
    storeChartDrawings(nextDrawings.drawings, nextDrawings.selectedDrawingId);
    setSelectedChartDrawingId(nextDrawings.selectedDrawingId);
  }, [
    activeSelectedChartDrawingId,
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
    if (!window.confirm(t("stockDetail.confirm.clearDrawings"))) return;

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
        const [institutionalData, marginData, revenueData, stockData] = await Promise.all([
          fetchOptional<InstitutionalTradeDailyRead>(
            `/api/market/institutional/${stockId}/latest`,
            { ensure_daily: false }
          ),
          fetchOptional<MarginTradingDailyRead>(
            `/api/market/margin/${stockId}/latest`,
            { ensure_daily: false }
          ),
          fetchOptional<MonthlyRevenueRead>(
            `/api/market/revenue/${stockId}/latest`,
            { ensure_latest: false }
          ),
          fetchOptional<StockMasterRead>(`/api/stocks/${stockId}`),
        ]);

        if (cancelled) return;

        setInstitutional(institutionalData);
        setMargin(marginData);
        setMonthlyRevenue(revenueData);
        setStockInfo(stockData);
      } catch {
        if (!cancelled) {
          setInstitutional(null);
          setMargin(null);
          setMonthlyRevenue(null);
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
        setErrorMessage(error instanceof Error ? error.message : tRef.current("stockDetail.errors.dataLoad"));
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
          setErrorMessage(tRef.current("stockDetail.errors.intradayHistoryFallbackNoData"));
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
            ? tRef.current("stockDetail.errors.intradayHistoryFallbackFailedWithMessage", {
                message: error.message,
              })
            : tRef.current("stockDetail.errors.intradayHistoryFallbackFailed")
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
      const requirementLabel = timeframeLabel(tRef.current, requestedTimeframe);

      if (ohlc.point_count >= requirement.minPoints) {
        setChartHistoryMessage(null);
        return;
      }

      const market = await resolveStockMarketForBackfill(targetStockId);
      const backfillPath = taiwanDailyPriceBackfillPath(targetStockId, market);

      if (!backfillPath) {
        if (!cancelled && activeStockIdRef.current === targetStockId) {
          setChartHistoryMessage(
            tRef.current("stockDetail.chartHistory.depthUnsupported", {
              label: requirementLabel,
              market: market ?? "-",
            })
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
          tRef.current("stockDetail.chartHistory.backgroundBackfill", {
            label: requirementLabel,
            count: ohlc.point_count,
          })
        );
      }

      try {
        await requestBackfillJob(
          backfillPath,
          { method: "POST" },
          {
            start_date: startDate,
            end_date: endDate,
            sleep_seconds: taiwanSubresourceRefreshSecondsRef.current,
            skip_existing_months: true,
          },
          {
            intervalMs: 2000,
            timeoutMs: 900000,
            onUpdate: (job) => {
              if (!cancelled && activeStockIdRef.current === targetStockId) {
                setChartHistoryMessage(
                  formatPanelJobProgress(requirementLabel, job, tRef.current)
                );
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
            include_intraday: shouldIncludeTaiwanOhlcIntraday(),
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
            ? tRef.current("stockDetail.chartHistory.complete", { label: requirementLabel })
            : tRef.current("stockDetail.chartHistory.completeWithCount", {
                label: requirementLabel,
                count: refreshedOhlc.point_count,
              })
        );
      } catch {
        if (cancelled || activeStockIdRef.current !== targetStockId) return;

        setChartHistoryMessage(
          tRef.current("stockDetail.chartHistory.failed", { label: requirementLabel })
        );
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
        const includeIntraday =
          !isIndexProduct && shouldIncludeTaiwanOhlcIntraday();
        const ohlc = await fetchJson<OhlcChartResponse>(
          isIndexProduct
            ? `/api/market/indices/${requestedStockId}/ohlc`
            : `/api/market/ohlc/${requestedStockId}`,
          {
            timeframe: requestedTimeframe,
            bars: chartBars,
            ensure_history: false,
            ...(includeIntraday ? { include_intraday: true } : {}),
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
        setErrorMessage(error instanceof Error ? error.message : tRef.current("stockDetail.errors.dataLoad"));
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
    if (!benchmarkIndexId || effectiveTimeframe === "today") {
      return;
    }

    let cancelled = false;
    const requestedIndexId = benchmarkIndexId;
    const requestedTimeframe = effectiveTimeframe as ChartTimeframe;
    const requestedKey = `${requestedIndexId}:${requestedTimeframe}`;

    async function loadBenchmarkChart() {
      try {
        const ohlc = await fetchJson<OhlcChartResponse>(
          `/api/market/indices/${requestedIndexId}/ohlc`,
          {
            timeframe: requestedTimeframe,
            bars: chartBarsByTimeframe[requestedTimeframe],
            ensure_history: false,
          }
        );

        if (cancelled) return;

        setBenchmarkChartData(ohlc.points);
        setBenchmarkChartKey(requestedKey);
      } catch {
        if (cancelled) return;

        setBenchmarkChartData([]);
        setBenchmarkChartKey(null);
      }
    }

    void loadBenchmarkChart();

    return () => {
      cancelled = true;
    };
  }, [benchmarkIndexId, effectiveTimeframe]);

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

  useEffect(() => {
    if (!stockId || isIndexProduct) {
      return;
    }

    let cancelled = false;
    let quoteDepthTimer: number | undefined;
    let quoteDepthRequestInFlight = false;
    let latestQuoteDepth: TaiwanStockQuoteDepthRead | null = null;
    const requestedStockId = stockId;

    function clearQuoteDepthTimer() {
      if (quoteDepthTimer !== undefined) {
        window.clearTimeout(quoteDepthTimer);
        quoteDepthTimer = undefined;
      }
    }

    async function loadQuoteDepth(showLoading: boolean) {
      if (quoteDepthRequestInFlight) return latestQuoteDepth;
      quoteDepthRequestInFlight = true;

      if (showLoading) {
        setQuoteDepth(null);
        setQuoteDepthLoadState("loading");
      }

      try {
        const depth = await fetchJson<TaiwanStockQuoteDepthRead>(
          `/api/market/quote-depth/${requestedStockId}`,
          { refresh: true }
        );

        if (cancelled || activeStockIdRef.current !== requestedStockId) return latestQuoteDepth;

        latestQuoteDepth = depth;
        setQuoteDepth(depth);
        setQuoteDepthLoadState("success");
        return depth;
      } catch {
        if (cancelled || activeStockIdRef.current !== requestedStockId) return latestQuoteDepth;

        setQuoteDepthLoadState("error");
        if (latestQuoteDepth === null) {
          setQuoteDepth(null);
        }
        return latestQuoteDepth;
      } finally {
        quoteDepthRequestInFlight = false;
      }
    }

    function scheduleQuoteDepthRefresh(depth: TaiwanStockQuoteDepthRead | null) {
      if (cancelled) return;

      quoteDepthTimer = window.setTimeout(() => {
        void loadQuoteDepth(false).then(scheduleQuoteDepthRefresh);
      }, quoteDepthRefreshDelayMs(depth));
    }

    void loadQuoteDepth(true).then(scheduleQuoteDepthRefresh);

    return () => {
      cancelled = true;
      clearQuoteDepthTimer();
    };
  }, [isIndexProduct, stockId]);

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
  const emptyProfessionalIndicatorData = useMemo<StockIndicatorPoint[]>(() => [], []);
  const emptyProfessionalBenchmarkData = useMemo<ChartPoint[]>(() => [], []);
  const benchmarkDataForChart = useMemo(
    () =>
      benchmarkIndexId &&
      benchmarkChartKey === `${benchmarkIndexId}:${effectiveTimeframe}` &&
      effectiveTimeframe !== "today"
        ? benchmarkChartData
        : emptyProfessionalBenchmarkData,
    [
      benchmarkChartData,
      benchmarkChartKey,
      benchmarkIndexId,
      effectiveTimeframe,
      emptyProfessionalBenchmarkData,
    ]
  );
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
  const professionalTimeframeLabel = t(`timeframes.${professionalTimeframe}`);
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
  const professionalDrawingContext = useMemo(
    () => ({
      symbol: stockId,
      market: currentStockInfoMarket,
      timeframe: professionalTimeframe,
    }),
    [currentStockInfoMarket, professionalTimeframe, stockId]
  );
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
      addBadge("等待盤中", "text-omi-text-muted bg-omi-surface-muted");

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
        valueLabel: timeframeLabel(t, effectiveTimeframe),
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

      if (isOpeningPhase) addBadge("開盤資料少", "text-omi-warning bg-omi-warning-soft");
      if (finiteNumber(openingGapPct)) {
        addBadge(
          openingGapPct >= 0 ? "開高" : "開低",
          openingGapPct >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft"
        );
      }
      if (finiteNumber(priceVsMa20)) {
        addBadge(
          priceVsMa20 >= 0 ? "日線站上 MA20" : "日線跌破 MA20",
          priceVsMa20 >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft"
        );
      }
      if (finiteNumber(rsi14) && rsi14 >= 80) addBadge("日線 RSI 過熱", "text-omi-warning bg-omi-warning-soft");

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

      if (finiteNumber(priceVsMa20)) addBadge(priceVsMa20 >= 0 ? "站上 MA20" : "跌破 MA20", priceVsMa20 >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
      if (finiteNumber(macdHistogram)) addBadge(macdHistogram >= 0 ? "MACD 偏多" : "MACD 偏弱", macdHistogram >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
      if (finiteNumber(rsi14) && rsi14 >= 80) addBadge("RSI 過熱", "text-omi-warning bg-omi-warning-soft");
      if (finiteNumber(volumeRatio) && volumeRatio >= 1.5) addBadge("放量", "text-omi-warning bg-omi-warning-soft");

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
          description: `${primaryMarketIndex?.short_label ?? t("stockDetail.marketFallback")} ${marketRegimeLabel(primaryMarketIndex, t)}`,
          value: formatPct(primaryMarketIndex?.change_pct),
          pulseValue: primaryMarketIndex?.change_pct,
          direction: primaryMarketIndex?.change_pct,
          tone: rowTone(primaryMarketIndex?.change_pct),
        }
      );

      if (finiteNumber(weeklyMa4) && finiteNumber(weeklyMa13)) addBadge(weeklyMa4 >= weeklyMa13 ? "週線偏多" : "週線偏弱", weeklyMa4 >= weeklyMa13 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
      if (finiteNumber(weekStats26.rangePositionPct) && weekStats26.rangePositionPct >= 80) addBadge("接近26週高位", "text-omi-warning bg-omi-warning-soft");
      if (finiteNumber(weeklyVolumeRatio) && weeklyVolumeRatio >= 1.5) addBadge("週量放大", "text-omi-warning bg-omi-warning-soft");

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

    if (finiteNumber(monthlyMa6) && finiteNumber(monthlyMa12)) addBadge(monthlyMa6 >= monthlyMa12 ? "月線偏多" : "月線偏弱", monthlyMa6 >= monthlyMa12 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
    if (finiteNumber(revenueGrowth)) addBadge(revenueGrowth >= 0 ? "營收成長" : "營收衰退", revenueGrowth >= 0 ? "text-omi-danger bg-omi-danger-soft" : "text-omi-success bg-omi-success-soft");
    if (finiteNumber(monthStats12.rangePositionPct) && monthStats12.rangePositionPct >= 80) addBadge("接近12月高位", "text-omi-warning bg-omi-warning-soft");

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
    t,
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
  const localizedFallbackTechnicalReport = useMemo(
    () => localizeTechnicalReport(fallbackTechnicalReport, t),
    [fallbackTechnicalReport, t]
  );
  const backendTechnicalReportView = useMemo(() => {
    if (
      !backendTechnicalReport ||
      backendTechnicalReport.stock_id !== stockId ||
      backendTechnicalReport.timeframe !== effectiveTimeframe
    ) {
      return null;
    }

    return mapBackendTechnicalReport(backendTechnicalReport, t);
  }, [backendTechnicalReport, effectiveTimeframe, stockId, t]);
  const technicalReport = backendTechnicalReportView ?? localizedFallbackTechnicalReport;
  const technicalStatus = technicalReport.title;
  const technicalSummaryText = technicalReport.summary;
  const displayOvernightImpact = !stockId || isIndexProduct ? null : overnightImpact;
  const displayOvernightImpactLoadState: LoadState =
    !stockId || isIndexProduct ? "idle" : overnightImpactLoadState;
  const stockSignalChips = useMemo(
    () =>
      buildStockSignalChips({
        technicalReport,
        institutional,
        margin,
        monthlyRevenue,
        overnightImpact: displayOvernightImpact,
        relativeToPrimaryIndex,
        primaryMarketLabel: primaryMarketIndex?.short_label ?? stockTechnicalTerm(t, "market"),
        t,
      }),
    [
      displayOvernightImpact,
      institutional,
      margin,
      monthlyRevenue,
      primaryMarketIndex?.short_label,
      relativeToPrimaryIndex,
      t,
      technicalReport,
    ]
  );
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
      const expectedMarginDate = expectedTaiwanDatasetDate(
        taiwanCalendarStatus,
        TAIWAN_DATASET_MARGIN_TRADING
      );
      const latestMarginDate =
        chipCoverage?.stock_id === targetStockId
          ? chipCoverage.margin_latest_trade_date
          : margin?.stock_id === targetStockId
            ? margin.trade_date
            : null;

      if (
        expectedMarginDate &&
        !isIsoDateOnOrAfter(latestMarginDate, expectedMarginDate)
      ) {
        return false;
      }

      return (
        latestMarginDate !== null ||
        shareholding.some((row) => row.stock_id === targetStockId)
      );
    }

    if (tab === "institutional") {
      const latestInstitutionalDate = maxIsoDate(
        institutionalHistory
          .filter((row) => row.stock_id === targetStockId)
          .map((row) => row.trade_date)
      );
      const expectedInstitutionalDate = expectedTaiwanDatasetDate(
        taiwanCalendarStatus,
        TAIWAN_DATASET_INSTITUTIONAL_TRADE
      );

      if (expectedInstitutionalDate) {
        return isIsoDateOnOrAfter(
          latestInstitutionalDate,
          expectedInstitutionalDate
        );
      }

      return latestInstitutionalDate !== null;
    }

    if (tab === "branch") {
      const expectedBranchDate = expectedTaiwanDatasetDate(
        taiwanCalendarStatus,
        TAIWAN_DATASET_BROKER_BRANCH
      );

      return (
        brokerBranchSummary !== null &&
        brokerBranchSummary.stock_id === targetStockId &&
        brokerBranchSummary.requested_days === branchDays &&
        isIsoDateOnOrAfter(brokerBranchSummary.trade_date, expectedBranchDate) &&
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
    const panelRefreshLabel = t(`stockDetail.tabs.${tab}`);

    const runPanelRefresh = async (
      profile: TaiwanRefreshProfile,
      label: string
    ) => {
      const job = await requestBackfillJob(
        taiwanSelectionRefreshPath(targetStockId),
        { method: "POST" },
        { profile, sleep_seconds: taiwanSubresourceRefreshSecondsRef.current },
        {
          intervalMs: 1500,
          timeoutMs: 600000,
          onUpdate: (job) => {
            if (activeStockIdRef.current === targetStockId) {
              setDataPanelMessage(formatPanelJobProgress(label, job, t));
            }
          },
        }
      );

      if (getJobResultStatus(job) === "error") {
        throw new Error(formatBackfillOutcome(job, label, t));
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

      const shareholdingLatest =
        nextCoverage?.shareholding_latest_date
          ? t("stockDetail.dataPanel.cache.latestDate", {
              date: formatDate(nextCoverage.shareholding_latest_date),
            })
          : "";
      const marginLatest =
        nextCoverage?.margin_latest_trade_date
          ? t("stockDetail.dataPanel.cache.latestDate", {
              date: formatDate(nextCoverage.margin_latest_trade_date),
            })
          : "";
      const marginRows = nextCoverage
        ? nextCoverage.margin_row_count
        : nextMarginRows.length || (nextMargin ? 1 : 0);
      const coverageText = t("stockDetail.dataPanel.cache.coverageSummary", {
        weekCount: nextCoverage?.shareholding_week_count ?? fallbackShareholdingWeekCount,
        shareholdingLatest,
        marginRows,
        marginLatest,
      });

      const failures = [
        coverageResult.status === "rejected" ? t("stockDetail.dataPanel.cache.status") : null,
        shareholdingResult.status === "rejected"
          ? t("stockDetail.dataPanel.cache.shareholding")
          : null,
        marginResult.status === "rejected" ? t("stockDetail.dataPanel.cache.marginShort") : null,
      ].filter(Boolean);

      const panelNotes = [
        statusNote,
        coverageText,
        failures.length
          ? t("stockDetail.dataPanel.cache.readPartialFailed", {
              items: failures.join(t("stockDetail.jobs.outcome.detailSeparator")),
            })
          : null,
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
            ? t("stockDetail.dataPanel.branchLoadedThrough", {
                outcome: formatBackfillOutcome(refreshJob, panelRefreshLabel, t),
                date: formatDate(branchSummary.trade_date),
              })
            : t("stockDetail.dataPanel.empty.branch")
        );
        return;
      }

      if (tab === "chips") {
        const initialCache = await loadCachedChips(t("stockDetail.dataPanel.cache.localShown"));
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
          hasBackfillIssue
            ? t("stockDetail.dataPanel.cache.partialBackfill")
            : t("stockDetail.dataPanel.cache.chipsReloaded")
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
        setDataPanelMessage(formatBackfillOutcome(refreshJob, panelRefreshLabel, t));
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
        setDataPanelMessage(formatBackfillOutcome(refreshJob, panelRefreshLabel, t));
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
        setDataPanelMessage(formatBackfillOutcome(refreshJob, panelRefreshLabel, t));
      }
    } catch {
      if (activeStockIdRef.current !== targetStockId) return;

      setDataPanelMessage(t("stockDetail.dataPanel.backfillFailedRetry"));
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
        { profile: "basic", sleep_seconds: taiwanSubresourceRefreshSecondsRef.current },
        {
          intervalMs: 1500,
          timeoutMs: 600000,
          onUpdate: (job) => {
            if (!cancelled && activeStockIdRef.current === targetStockId) {
              const translate = tRef.current;
              setDataPanelMessage(
                formatPanelJobProgress(
                  translate("stockDetail.jobs.fallbackLabels.basicAutoRefresh"),
                  job,
                  translate
                )
              );
            }
          },
        }
      )
        .then((job) => {
          if (cancelled || activeStockIdRef.current !== targetStockId) return;

          const resultStatus = getJobResultStatus(job);
          const translate = tRef.current;
          setDataPanelMessage(
            resultStatus === "partial_success"
              ? translate("stockDetail.dataPanel.basicAutoRefresh.partial")
              : resultStatus === "error"
                ? translate("stockDetail.dataPanel.basicAutoRefresh.error")
                : translate("stockDetail.dataPanel.basicAutoRefresh.success")
          );
        })
        .catch(() => {
          if (cancelled || activeStockIdRef.current !== targetStockId) return;

          setDataPanelMessage(
            tRef.current("stockDetail.dataPanel.basicAutoRefresh.failedWithStatus")
          );
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
      activeDataTab === "branch"
        ? branchSummaryCacheRef.current.get(requestKey) ?? null
        : null;
    const cachedBranchSummaryIsCurrent =
      cachedBranchSummary !== null &&
      cachedBranchSummary.stock_id === stockId &&
      cachedBranchSummary.requested_days === branchDays &&
      isIsoDateOnOrAfter(
        cachedBranchSummary.trade_date,
        expectedTaiwanDatasetDate(taiwanCalendarStatus, TAIWAN_DATASET_BROKER_BRANCH)
      );
    const hasCachedResult = dataPanelResolvedKeysRef.current.has(requestKey);
    const hasCurrentData = dataTabHasCurrentData(activeDataTab);

    if (cachedBranchSummary && cachedBranchSummaryIsCurrent) {
      const timer = window.setTimeout(() => {
        if (dataPanelRequestKeyRef.current === requestKey) return;

        setBrokerBranchSummary(cachedBranchSummary);
        setDataPanelLoading((current) => (current === activeDataTab ? null : current));
        setDataPanelMessage(tRef.current("stockDetail.dataPanel.cache.cachedData"));
      }, 0);

      return () => window.clearTimeout(timer);
    }

    if (hasCurrentData) {
      const timer = window.setTimeout(() => {
        if (dataPanelRequestKeyRef.current === requestKey) return;

        setDataPanelLoading((current) => (current === activeDataTab ? null : current));
        setDataPanelMessage(
          hasCachedResult ? tRef.current("stockDetail.dataPanel.cache.cachedData") : null
        );
      }, 0);

      return () => window.clearTimeout(timer);
    }

    const timer = window.setTimeout(() => {
      void refreshDataTab(activeDataTab);
    }, 0);

    return () => window.clearTimeout(timer);
    // Populate the visible right-panel tab whenever the selected stock or tab changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDataTab, branchDays, isIndexProduct, stockId, taiwanCalendarStatus]);

  if (!stockId) {
    return watchlistRankingPanel ? (
      <section className="min-w-0">{watchlistRankingPanel}</section>
    ) : null;
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
        <div className={chartFocusMode ? "min-w-0" : "min-w-0 border border-omi-border-subtle bg-omi-surface"}>
          {chartFocusMode ? null : (
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {isIndexProduct
                  ? t("stockDetail.entity.index")
                  : t("stockDetail.entity.stock")}
              </div>
              <h2 className="mt-1 text-2xl font-bold text-omi-text-strong">
                {stockId} {indexProduct?.stockName ?? stockName ?? stockInfo?.stock_name ?? ""}
              </h2>
              <div className="mt-1 text-sm text-omi-text-muted">
                {indexProduct
                  ? `${indexProduct.market} · 指數 · ${indexProduct.symbol}`
                  : `${stockInfo?.market ?? "-"} · ${
                      stockInfo?.industry ?? t("stockDetail.uncategorized")
                    }`}{" "}
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
                    "text-3xl font-bold leading-none tracking-normal tabular-nums",
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
                <div className="flex border border-omi-border-subtle bg-omi-surface-subtle p-1">
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
                          ? "omi-timeframe-tab-active"
                          : "text-omi-text-muted hover:bg-omi-surface",
                      ].join(" ")}
                    >
                      {t(`timeframes.${item}`)}
                    </button>
                  ))}
                </div>

                {effectiveTimeframe === "today" ? (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                    >
                      {t("stockDetail.indicators")}
                    </button>
                    {indicatorMenuOpen ? (
                      <div className="absolute right-0 z-20 mt-2 w-56 border border-omi-border-subtle bg-omi-surface p-3 text-left shadow-lg">
                        <div className="mb-2 text-xs font-bold text-omi-text-muted">{t("stockDetail.displayItems")}</div>
                        {intradayIndicatorOptions.map((option) => (
                          <label
                            key={option.key}
                            className="flex cursor-pointer items-start gap-2 px-2 py-2 text-xs hover:bg-omi-surface-subtle"
                          >
                            <input
                              type="checkbox"
                              checked={intradayIndicators[option.key]}
                              onChange={() => toggleIntradayIndicator(option.key)}
                              className="mt-0.5"
                            />
                            <span>
                              <span className="block font-semibold text-omi-text">
                                {option.label}
                              </span>
                              <span className="block text-omi-text-muted">
                                {t(option.descriptionKey)}
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
                        className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                      >
                        {t("stockDetail.indicators")}
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
                          ? "border-omi-control bg-omi-control text-omi-text-inverse hover:bg-omi-control-muted"
                          : "border-omi-border bg-omi-surface text-omi-text hover:border-omi-control hover:text-omi-text-strong",
                        !canUseFocusedKLine
                          ? "cursor-not-allowed border-omi-border-subtle bg-omi-surface-subtle text-omi-text-inverse-muted hover:border-omi-border-subtle hover:text-omi-text-inverse-muted"
                          : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {chartFocusMode ? t("stockDetail.overview") : t("stockDetail.expand")}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>

          )}

          {!chartFocusMode && errorMessage ? (
            <div className="border-b border-omi-danger-border bg-omi-danger-soft px-5 py-3 text-sm text-omi-danger">
              {errorMessage}
            </div>
          ) : null}
          {!chartFocusMode && chartHistoryMessage && !errorMessage ? (
            <div className="border-b border-omi-warning-border bg-omi-warning-soft px-5 py-2 text-xs text-omi-warning-strong">
              {chartHistoryMessage}
            </div>
          ) : null}

          {chartFocusMode ? (
            <ProfessionalChartPanel
              title={`${stockId} ${
                indexProduct?.stockName ?? stockName ?? stockInfo?.stock_name ?? ""
              }`}
              priceSummary={
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
              }
              timeframeOptions={professionalTimeframeOptions.map((option) => ({
                key: option,
                label: timeframeLabel(t, option),
              }))}
              timeframe={professionalTimeframe}
              onTimeframeChange={handleProfessionalTimeframeChange}
              chartStyle={professionalChartStyle}
              onChartStyleChange={setProfessionalChartStyle}
              indicatorMenuOpen={indicatorMenuOpen}
              onToggleIndicatorMenu={() => setIndicatorMenuOpen((value) => !value)}
              onCloseIndicatorMenu={() => setIndicatorMenuOpen(false)}
              indicatorMenu={
                <TechnicalIndicatorMenu
                  indicators={chartIndicators}
                  activeTemplate={activeIndicatorTemplate}
                  onApplyTemplate={applyIndicatorTemplate}
                  onToggleIndicator={toggleChartIndicator}
                  groups={professionalIndicatorCategoryGroups}
                  includeParameters
                  parameters={indicatorParameters}
                  onUpdateParameter={updateIndicatorParameter}
                  className="w-[25rem]"
                />
              }
              onClose={() => {
                setIndicatorMenuOpen(false);
                setChartDrawingTool("cursor");
                setChartFocusMode(false);
              }}
              message={
                errorMessage ? (
                  <div className="border-b border-omi-danger-border bg-omi-danger-soft px-5 py-3 text-sm text-omi-danger">
                    {errorMessage}
                  </div>
                ) : chartHistoryMessage ? (
                  <div className="border-b border-omi-warning-border bg-omi-warning-soft px-5 py-2 text-xs text-omi-warning-strong">
                    {chartHistoryMessage}
                  </div>
                ) : null
              }
              chartReady={professionalChartReady}
              emptyState={
                <EmptyDataState
                  message={t("stockDetail.loadingFrame", {
                    label: professionalTimeframeLabel,
                  })}
                />
              }
              chartData={professionalChartData}
              indicatorData={
                professionalIsIntraday ? emptyProfessionalIndicatorData : indicatorForTimeframe
              }
              label={professionalTimeframeLabel}
              timeMode={professionalIsIntraday ? "intraday" : "date"}
              showMovingAverages={chartIndicators.ma}
              indicators={chartIndicators}
              indicatorParameters={indicatorParameters}
              benchmarkData={
                professionalIsIntraday ? emptyProfessionalBenchmarkData : benchmarkDataForChart
              }
              benchmarkLabel={benchmarkLabel}
              volumePanelLabel={isIndexProduct ? t("chart.kline.tradeValueYi") : undefined}
              volumeValueKey={isIndexProduct ? "trade_value" : "volume"}
              drawingTool={chartDrawingTool}
              drawings={chartDrawings}
              selectedDrawingId={activeSelectedChartDrawingId}
              drawingContext={professionalDrawingContext}
              onDrawingToolChange={setChartDrawingTool}
              onDrawingsChange={updateChartDrawings}
              onDrawingStateChange={updateChartDrawingState}
              onSelectedDrawingChange={setSelectedChartDrawingId}
              canUndoDrawing={canUndoChartDrawing}
              canRedoDrawing={canRedoChartDrawing}
              onUndoDrawing={undoChartDrawing}
              onRedoDrawing={redoChartDrawing}
              onDeleteSelectedDrawing={deleteSelectedChartDrawing}
              onClearDrawings={clearChartDrawings}
              historyCounts={{
                past: chartDrawingHistory.past.length,
                future: chartDrawingHistory.future.length,
              }}
            />
          ) : effectiveTimeframe === "today" ? (
            <IntradayTrendChart
              points={todayTrend}
              previousClose={todayPreviousClose}
              label={timeframeLabel(t, effectiveTimeframe)}
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
              label={timeframeLabel(t, effectiveTimeframe)}
              indicators={chartIndicators}
              indicatorParameters={indicatorParameters}
              benchmarkData={benchmarkDataForChart}
              benchmarkLabel={benchmarkLabel}
              revealKey={`${stockId}:${effectiveTimeframe}`}
              volumePanelLabel={isIndexProduct ? t("chart.kline.tradeValueYi") : undefined}
              volumeTooltipLabel={isIndexProduct ? t("chart.kline.tradeValueYi") : undefined}
              volumeValueKey={isIndexProduct ? "trade_value" : "volume"}
              volumeValueFormatter={isIndexProduct ? formatTradeValueYi : undefined}
            />
          ) : (
            <EmptyDataState
              message={t("stockDetail.loadingFrame", {
                label: timeframeLabel(t, effectiveTimeframe),
              })}
            />
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
        className="flex min-w-0 flex-col border border-omi-border-subtle bg-omi-surface"
      >
        {isIndexProduct ? (
          <IndexListPanel
            items={indexList}
            loadState={indexListLoadState}
            marketLabel={
              indexProduct?.market === "TPEX"
                ? t("stockDetail.marketLabels.otc")
                : t("stockDetail.marketLabels.listed")
            }
          />
        ) : showTechnicalLoading ? (
          <TechnicalLoadingPanel />
        ) : (
          <>
            <QuoteDepthPanel
              quoteDepth={quoteDepth}
              loadState={quoteDepthLoadState}
              quoteDepthPreviewMode={quoteDepthPreviewMode}
            />

            <div className="omi-technical-summary border-b border-omi-border-subtle px-5 py-3">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {stockTechnicalText(t, "eyebrow")}
              </div>
              <div className="mt-1.5 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-xl font-bold text-omi-text-strong">{technicalStatus}</div>
                  <div className="mt-0.5 text-xs leading-4 text-omi-text-muted">{technicalSummaryText}</div>
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
                  <div className="text-xs font-medium text-omi-text-muted">{technicalReport.valueLabel}</div>
                </div>
              </div>
              {stockSignalChips.length ? (
                <div
                  className="mt-3 flex flex-wrap gap-1.5"
                  aria-label={t("stockDetail.chipMetrics.technicalSignalsAria")}
                >
                  {stockSignalChips.map((signal) => (
                    <span
                      key={signal.key}
                      className={[
                        "omi-technical-badge omi-signal-chip inline-flex items-center gap-1 border px-2 py-1 text-[11px] font-semibold",
                        stockSignalToneClass(signal.tone),
                      ].join(" ")}
                      title={signal.title}
                    >
                      <span className="text-[10px] opacity-75">{signal.source}：</span>
                      <span>{signal.label}</span>
                    </span>
                  ))}
                </div>
              ) : null}
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

              <div className="mt-3 border-t border-omi-border-subtle pt-3">
                <div className="omi-technical-market flex items-start justify-between gap-4 text-xs">
                  <div>
                    <div className="font-bold uppercase tracking-[0.14em] text-omi-text-muted">
                      {t("dashboard.marketIndex.market")}
                    </div>
                    <div className="mt-0.5 text-sm font-bold text-omi-text-strong">
                      {primaryMarketIndex?.short_label ?? t("stockDetail.marketFallback")}
                    </div>
                    <div className="mt-0.5 text-omi-text-muted">{marketRegimeLabel(primaryMarketIndex, t)}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-bold text-omi-text-strong">{formatPrice(primaryMarketIndex?.close)}</div>
                    <div className={valueTone(primaryMarketIndex?.change_pct)}>
                      {formatPct(primaryMarketIndex?.change_pct)}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </>
        )}

        {!isIndexProduct ? (
          <div className="border-t border-omi-border-subtle bg-omi-surface">
            <div
              aria-hidden="true"
              className="h-2 border-b border-omi-border-subtle bg-omi-surface-muted shadow-[var(--omi-shadow-surface-inset)]"
            />

            <div className="flex border-b border-omi-border-subtle">
              {dataPanelTabs.map((tab) => (
                <DataTabButton
                  key={tab.key}
                  tab={{ ...tab, label: t(`stockDetail.tabs.${tab.key}`) }}
                  active={activeDataTab === tab.key}
                  onClick={() => handleDataTabClick(tab.key)}
                />
              ))}
            </div>

            <div className="px-5 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {t("stockDetail.data")}
              </div>
              <div className="mt-1 flex items-end justify-between gap-4">
                <div>
                  <div className="text-lg font-bold text-omi-text-strong">
                    {t(`stockDetail.tabs.${activeDataTab}`)} {t("stockDetail.data")}
                  </div>
                </div>
              </div>

              <div className="mt-4">
                <StockDetailDataPanel
                  activeDataTab={activeDataTab}
                  branchDays={branchDays}
                  branchTableSide={branchTableSide}
                  brokerBranchSummary={brokerBranchSummary}
                  chipCoverage={chipCoverage}
                  dataPanelLoading={dataPanelLoading}
                  dataPanelMessage={dataPanelMessage}
                  earningsSeries={earningsSeries}
                  earningsView={earningsView}
                  financialMetric={financialMetric}
                  financialMetricHistory={financialMetricHistory}
                  institutionalHoldingRatio={institutionalHoldingRatio}
                  institutionalHistory={institutionalHistory}
                  institutionalHoverDate={institutionalHoverDate}
                  institutionalSeries={institutionalSeries}
                  largeHolderLots={largeHolderLots}
                  margin={margin}
                  monthlyRevenue={monthlyRevenue}
                  monthlyRevenueHistory={monthlyRevenueHistory}
                  revenueSeries={revenueSeries}
                  revenueView={revenueView}
                  revenueYear={revenueYear}
                  setBranchDays={setBranchDays}
                  setBranchTableSide={setBranchTableSide}
                  setEarningsView={setEarningsView}
                  setInstitutionalHoverDate={setInstitutionalHoverDate}
                  setLargeHolderLots={setLargeHolderLots}
                  setRevenueView={setRevenueView}
                  setRevenueYear={setRevenueYear}
                  setSmallHolderLots={setSmallHolderLots}
                  shareholding={shareholding}
                  shareholdingSeries={shareholdingSeries}
                  smallHolderLots={smallHolderLots}
                  stockId={stockId}
                />
              </div>
            </div>
          </div>
        ) : null}

          <div className="hidden">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
              Data
            </div>
            <div className="mt-1 flex items-end justify-between gap-4">
              <div>
                <div className="text-lg font-bold text-omi-text-strong">{t("stockDetail.chipData")}</div>
                <div className="mt-1 text-xs text-omi-text-muted">{t("stockDetail.byDataDate")}</div>
              </div>
            </div>

            <div className="mt-4 space-y-4">
              {chipDateGroups.length ? (
                chipDateGroups.map((group) => (
                  <div key={group.tradeDate} className="space-y-3">
                    <div className="flex items-center justify-between border-b border-omi-border-subtle pb-2">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
                        Date
                      </span>
                      <span className="text-sm font-bold text-omi-text">
                        {group.tradeDate}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
                      <ChipMetricBlock title={t("stockDetail.chipMetrics.institutionalTitle")}>
                        <MetricRow
                          label={t("stockDetail.chipMetrics.foreignNet")}
                          value={formatSignedNumber(group.institutional?.foreign_investor_net)}
                          tone={valueTone(group.institutional?.foreign_investor_net)}
                        />
                        <MetricRow
                          label={t("stockDetail.chipMetrics.investmentTrustNet")}
                          value={formatSignedNumber(group.institutional?.investment_trust_net)}
                          tone={valueTone(group.institutional?.investment_trust_net)}
                        />
                        <MetricRow
                          label={t("stockDetail.chipMetrics.dealerNet")}
                          value={formatSignedNumber(group.institutional?.dealer_net)}
                          tone={valueTone(group.institutional?.dealer_net)}
                        />
                        <MetricRow
                          label={t("stockDetail.chipMetrics.totalInstitutionalNet")}
                          value={formatSignedNumber(group.institutional?.total_institutional_net)}
                          tone={valueTone(group.institutional?.total_institutional_net)}
                        />
                      </ChipMetricBlock>

                      <ChipMetricBlock title={t("stockDetail.chipMetrics.marginShortTitle")}>
                        <MetricRow
                          label={t("stockDetail.chipMetrics.marginBalance")}
                          value={formatNumber(group.margin?.margin_today_balance)}
                        />
                        <MetricRow
                          label={t("stockDetail.chipMetrics.shortBalance")}
                          value={formatNumber(group.margin?.short_today_balance)}
                        />
                        <MetricRow
                          label={t("stockDetail.chipMetrics.offset")}
                          value={formatNumber(group.margin?.offset)}
                        />
                        <MetricRow
                          label={t("stockDetail.chipMetrics.marginBuySell")}
                          value={`${formatNumber(group.margin?.margin_buy)} / ${formatNumber(
                            group.margin?.margin_sell
                          )}`}
                        />
                      </ChipMetricBlock>
                    </div>
                  </div>
                ))
              ) : (
                <div className="border border-dashed border-omi-border-subtle px-4 py-6 text-center text-sm text-omi-text-muted">
                  {t("stockDetail.chipMetrics.empty")}
                </div>
              )}
            </div>
          </div>
      </aside>
      ) : null}

    </section>
  );
}

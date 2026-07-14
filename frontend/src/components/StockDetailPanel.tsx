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
import type { ChartDrawingTool } from "@/components/LightweightKLineChart";
import StockDetailDataPanel from "@/components/stock-detail/StockDetailDataPanel";
import QuoteDepthPanel from "@/components/stock-detail/QuoteDepthPanel";
import { dataPanelTabs } from "@/components/stock-detail/StockDetailPanelConstants";
import {
  buildChipDateGroups,
  buildEarningsSeries,
  buildInstitutionalSeries,
  buildRevenueSeries,
  buildShareholdingSeries,
} from "@/components/stock-detail/stockDetailSeriesProjection";
import {
  buildStockSignalChips,
  stockTechnicalTerm,
  stockTechnicalText,
  type StockSignalTone,
} from "@/components/stock-detail/stockDetailSignalProjection";
import { buildFallbackTechnicalReport } from "@/components/stock-detail/stockDetailTechnicalReportProjection";
import TechnicalIndicatorMenu, {
  indicatorTemplates,
  type IndicatorTemplateKey,
} from "@/components/stock-detail/TechnicalIndicatorMenu";
import { useChartDrawingPersistence } from "@/components/stock-detail/useChartDrawingPersistence";
import { useTaiwanDetailContext } from "@/components/stock-detail/useTaiwanDetailContext";
import { useTaiwanDataPanel } from "@/components/stock-detail/useTaiwanDataPanel";
import { useTaiwanQuoteDepth } from "@/components/stock-detail/useTaiwanQuoteDepth";
import { useTaiwanStockChartData } from "@/components/stock-detail/useTaiwanStockChartData";
import { useTaiwanTechnicalReport } from "@/components/stock-detail/useTaiwanTechnicalReport";
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
  averageRecentChartValue,
  estimatedPriceLimitStatus,
  finiteNumber,
  formatDateTime,
  formatNumber,
  formatPct,
  formatPrice,
  formatSignedNumber,
  formatSignedPointChange,
  formatTradeValueYi,
  isProfessionalIntradayTimeframe,
  localizeTechnicalReport,
  mapBackendTechnicalReport,
  marketRegimeLabel,
  priceLimitBoxClass,
  priceLimitTone,
  professionalIntradayMinutes,
  safeRatio,
  summarizeIntradayPoints,
  valueTone,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  BranchTableSide,
  ChartTimeframe,
  EarningsView,
  LoadState,
  ProfessionalTimeframe,
  RevenueView,
  Timeframe,
} from "@/components/stock-detail/StockDetailDataViews";
import { emitDataStatusEvent, type DataStatusLevel } from "@/lib/dataStatusEvents";
import {
  getRefreshExecutionSeconds,
  useRefreshExecutionSettings,
} from "@/lib/refreshExecutionSettings";
import { timeframeLabel, useT } from "@/i18n";
import { TAIWAN_INTRADAY_REFRESH_MS } from "@/lib/taiwanMarketTime";
import type {
  ChartPoint,
  MarketIndexSummary,
  OhlcIntradayOverlay,
  StockIndicatorPoint,
  TaiwanStockQuoteDepthPreviewMode,
} from "@/types/market";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

type Props = {
  stockId: string | null;
  stockName: string | null;
  initialChartData?: ChartPoint[];
  initialChartIntradayOverlay?: OhlcIntradayOverlay | null;
  initialIndicatorData?: StockIndicatorPoint[];
  watchlistRankingPanel?: ReactNode;
  marketIndexSummary?: MarketIndexSummary | null;
  onChartFocusModeChange?: (active: boolean) => void;
  quoteDepthPreviewMode?: TaiwanStockQuoteDepthPreviewMode | null;
};

function normalizeIsoDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : null;
}

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

function overlayMatchesChartLatest(
  overlay: OhlcIntradayOverlay | null,
  latestChart: ChartPoint | null
) {
  return (
    Boolean(overlay?.provisional) &&
    normalizeIsoDate(overlay?.trade_date) === normalizeIsoDate(latestChart?.time)
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

function stockSignalToneClass(tone: StockSignalTone) {
  if (tone === "positive") return "omi-signal-chip-positive";
  if (tone === "negative") return "omi-signal-chip-negative";
  if (tone === "warning") return "omi-signal-chip-warning";
  return "omi-signal-chip-neutral";
}

export default function StockDetailPanel({
  stockId,
  stockName,
  initialChartData = [],
  initialChartIntradayOverlay = null,
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
  const [intradayIndicators, setIntradayIndicators] =
    useState<IntradayIndicatorSettings>(defaultIntradayIndicators);
  const [activeIndicatorTemplate, setActiveIndicatorTemplate] =
    useState<IndicatorTemplateKey | null>("basic");
  const [indicatorParameters, setIndicatorParameters] =
    useState<IndicatorParameters>(defaultIndicatorParameters);
  const [institutionalHoverDate, setInstitutionalHoverDate] = useState<string | null>(null);
  const [branchTableSide, setBranchTableSide] = useState<BranchTableSide>("buy");
  const [largeHolderLots, setLargeHolderLots] = useState(1000);
  const [smallHolderLots, setSmallHolderLots] = useState(100);
  const [revenueView, setRevenueView] = useState<RevenueView>("monthly");
  const [revenueYear, setRevenueYear] = useState<number | null>(null);
  const [earningsView, setEarningsView] = useState<EarningsView>("quarterly");
  const indexProduct = stockId ? indexProducts.get(stockId) ?? null : null;
  const isIndexProduct = indexProduct !== null;
  const indexId = indexProduct?.indexId ?? null;
  const indexMarket = indexProduct?.market ?? null;
  const { quoteDepth, loadState: quoteDepthLoadState } = useTaiwanQuoteDepth({
    enabled: !isIndexProduct,
    stockId,
  });
  const {
    state: {
      activeDataTab,
      branchDays,
      brokerBranchSummary,
      chartReloadNonce,
      chipCoverage,
      dataPanelLoading,
      dataPanelMessage,
      financialMetric,
      financialMetricHistory,
      institutional,
      institutionalHistory,
      margin,
      monthlyRevenue,
      monthlyRevenueHistory,
      shareholding,
      stockInfo,
    },
    actions: {
      selectDataTab,
      setBranchDays,
      setStockInfo,
    },
  } = useTaiwanDataPanel({
    isIndexProduct,
    stockId,
    subresourceRefreshSeconds: taiwanSubresourceRefreshSeconds,
    t,
  });
  const {
    indexContributionLoadState,
    indexContributions,
    indexList,
    indexListLoadState,
    marketChip,
    marketChipLoadState,
    overnightImpact,
    overnightImpactLoadState,
  } = useTaiwanDetailContext({
    indexId,
    indexMarket,
    isIndexProduct,
    stockId,
  });
  const chartDrawingRemoteMarket = isIndexProduct
    ? indexProduct.market
    : stockInfo?.market ?? null;
  const {
    state: {
      activeSelectedDrawingId: activeSelectedChartDrawingId,
      canRedo: canRedoChartDrawing,
      canUndo: canUndoChartDrawing,
      drawings: chartDrawings,
      history: chartDrawingHistory,
    },
    actions: {
      clear: clearChartDrawings,
      deleteSelected: deleteSelectedChartDrawing,
      redo: redoChartDrawing,
      setSelectedDrawingId: setSelectedChartDrawingId,
      undo: undoChartDrawing,
      updateDrawingState: updateChartDrawingState,
      updateDrawings: updateChartDrawings,
    },
  } = useChartDrawingPersistence({
    active: chartFocusMode,
    clearConfirmationMessage: t("stockDetail.confirm.clearDrawings"),
    market: chartDrawingRemoteMarket,
    stockId,
    stockName,
    timeframe: professionalTimeframe,
  });
  const dataStatusDisplayName = indexProduct?.stockName ?? stockName;
  const dataStatusContextLabel = stockId
    ? `${stockId}${dataStatusDisplayName ? ` ${dataStatusDisplayName}` : ""}`
    : t("watchlist.noGroupSelected");
  const dataStatusContextKey = `tw:${isIndexProduct ? "index" : "stock"}:${stockId ?? "unknown"}`;
  const dataStatusSource = isIndexProduct ? "台股指數" : "台股個股";

  const publishDetailDataStatus = useCallback(
    ({
      level = "error",
      title,
      message,
      source = dataStatusSource,
    }: {
      level?: DataStatusLevel;
      title: string;
      message: string;
      source?: string;
    }) => {
      if (!stockId) return;

      emitDataStatusEvent({
        market: "tw",
        level,
        title,
        message,
        source,
        contextKey: dataStatusContextKey,
        contextLabel: dataStatusContextLabel,
        dedupeKey: `${dataStatusContextKey}:${source}:${title}:${level}`,
      });
    },
    [dataStatusContextKey, dataStatusContextLabel, dataStatusSource, stockId]
  );
  const currentStockInfoId = stockInfo?.stock_id ?? null;
  const currentStockInfoMarket = stockInfo?.market ?? null;
  const effectiveTimeframe = timeframe;
  const availableTimeframes = isIndexProduct ? indexTimeframes : allTimeframes;
  const {
    state: {
      benchmarkChartData,
      benchmarkChartKey,
      benchmarkIndexId,
      chartData,
      chartHistoryMessage,
      chartIntradayOverlay,
      chartStockId,
      chartTimeframe,
      errorMessage,
      indicatorData,
      loadState,
      professionalIntradayData,
      professionalIntradayFallbackActive,
      professionalIntradayInterval,
      professionalIntradayStockId,
      todayPreviousClose,
      todaySource,
      todayTrend,
      todayUpdatedAt,
    },
  } = useTaiwanStockChartData({
    chartFocusMode,
    currentStockInfoId,
    currentStockInfoMarket,
    effectiveTimeframe,
    initialChartData,
    initialChartIntradayOverlay,
    initialIndicatorData,
    isIndexProduct,
    onStockInfoResolved: setStockInfo,
    professionalTimeframe,
    publishDataStatus: publishDetailDataStatus,
    reloadNonce: chartReloadNonce,
    stockId,
    subresourceRefreshSeconds: taiwanSubresourceRefreshSeconds,
    t,
  });
  const backendTechnicalReport = useTaiwanTechnicalReport({
    effectiveTimeframe,
    isIndexProduct,
    stockId,
    todayUpdatedAt,
  });
  const benchmarkLabel =
    benchmarkIndexId === "TPEX"
      ? "櫃買"
      : benchmarkIndexId === "TAIEX"
        ? "加權"
        : undefined;

  useEffect(() => {
    onChartFocusModeChange?.(chartFocusMode);
  }, [chartFocusMode, onChartFocusModeChange]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setInstitutionalHoverDate(null);
      setRevenueYear(null);
    }, 0);

    return () => window.clearTimeout(timer);
  }, [isIndexProduct, stockId]);

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

  const indicatorForTimeframe = useMemo(() => {
    if (effectiveTimeframe === "daily") return indicatorData.slice(-180);
    return [];
  }, [effectiveTimeframe, indicatorData]);

  const latestIndicator = indicatorData[indicatorData.length - 1] ?? null;
  const latestChart = chartData[chartData.length - 1] ?? null;
  const previousChart = chartData[chartData.length - 2] ?? null;
  const latestChartDate = normalizeIsoDate(latestChart?.time);
  const latestIndicatorDate = normalizeIsoDate(latestIndicator?.time);
  const latestCurrentIndicator =
    latestIndicator !== null &&
    latestChartDate !== null &&
    latestIndicatorDate === latestChartDate
      ? latestIndicator
      : null;
  const chartOverlayPreviousClose =
    overlayMatchesChartLatest(chartIntradayOverlay, latestChart) &&
    finiteNumber(chartIntradayOverlay?.previous_close)
      ? chartIntradayOverlay.previous_close
      : null;
  const chartPreviousClose = chartOverlayPreviousClose ?? previousChart?.close ?? null;
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
      : latestCurrentIndicator?.close ?? latestChart?.close ?? null;
  const dailyPreviousClose =
    latestCurrentIndicator?.close !== null &&
    latestCurrentIndicator?.close !== undefined &&
    latestCurrentIndicator?.change !== null &&
    latestCurrentIndicator?.change !== undefined
      ? latestCurrentIndicator.close - latestCurrentIndicator.change
      : null;
  const todayReferenceClose = todayPreviousClose ?? dailyPreviousClose;
  const chartChangePct =
    latestChart?.close !== null &&
    latestChart?.close !== undefined &&
    chartPreviousClose !== null &&
    chartPreviousClose !== undefined &&
    chartPreviousClose !== 0
      ? ((latestChart.close - chartPreviousClose) / chartPreviousClose) * 100
      : null;
  const chartChange =
    latestChart?.close !== null &&
    latestChart?.close !== undefined &&
    chartPreviousClose !== null &&
    chartPreviousClose !== undefined
      ? latestChart.close - chartPreviousClose
      : null;
  const latestChange =
    effectiveTimeframe === "today" && latestToday && todayReferenceClose
      ? latestToday.price - todayReferenceClose
      : latestCurrentIndicator?.change ?? chartChange;
  const latestChangePct =
    effectiveTimeframe === "today" && latestToday && todayReferenceClose
      ? ((latestToday.price - todayReferenceClose) / todayReferenceClose) * 100
      : latestCurrentIndicator?.change_pct ?? chartChangePct;
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
  const ma5 = latestCurrentIndicator?.ma?.ma5 ?? averageRecentChartValue(chartData, "close", 5);
  const ma20 = latestCurrentIndicator?.ma?.ma20 ?? averageRecentChartValue(chartData, "close", 20);
  const ma60 = latestCurrentIndicator?.ma?.ma60 ?? averageRecentChartValue(chartData, "close", 60);
  const volumeMa20 =
    latestCurrentIndicator?.volume_ma?.volume_ma20 ??
    averageRecentChartValue(chartData, "volume", 20);
  const priceVsMa20 =
    latestClose !== null && ma20 !== null && ma20 !== 0
      ? ((latestClose - ma20) / ma20) * 100
      : null;
  const latestVolume =
    effectiveTimeframe === "today"
      ? todayStats.volume ?? latestToday?.volume ?? null
      : latestCurrentIndicator?.volume ?? latestChart?.volume ?? null;
  const volumeRatio = safeRatio(latestVolume, volumeMa20);
  const volumeRatioPct = volumeRatio === null ? null : (volumeRatio - 1) * 100;
  const totalInstitutionalNet = institutional?.total_institutional_net ?? null;
  const displayTime =
    effectiveTimeframe === "today" && latestToday
      ? formatDateTime(latestToday.time)
      : effectiveTimeframe === "today"
        ? "-"
        : latestCurrentIndicator?.time ?? latestChart?.time ?? "-";
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

  const fallbackTechnicalReport = useMemo(
    () =>
      buildFallbackTechnicalReport({
        chartData,
        currentChartReady,
        effectiveTimeframe,
        financialMetric,
        institutional,
        institutionalHistory,
        isIndexProduct,
        largeHolderLots,
        latestChangePct,
        latestChartVolume: latestChart?.volume ?? null,
        latestClose,
        latestCurrentIndicator,
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
        todayStats,
        todayReferenceClose,
        todayTrendLength: todayTrend.length,
        totalInstitutionalNet,
        volumeMa20,
        volumeRatio,
        volumeRatioPct,
      }),
    [
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
      latestCurrentIndicator,
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
      todayStats,
      todayReferenceClose,
      todayTrend.length,
      totalInstitutionalNet,
      volumeMa20,
      volumeRatio,
      volumeRatioPct,
    ]
  );
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

  const shareholdingSeries = useMemo(
    () =>
      buildShareholdingSeries({
        indicatorData,
        largeHolderLots,
        shareholding,
        smallHolderLots,
      }),
    [indicatorData, largeHolderLots, shareholding, smallHolderLots]
  );
  const institutionalSeries = useMemo(
    () => buildInstitutionalSeries(institutionalHistory),
    [institutionalHistory]
  );
  const chipDateGroups = useMemo(
    () => buildChipDateGroups(institutional, margin),
    [institutional, margin]
  );
  const revenueSeries = useMemo(
    () => buildRevenueSeries(monthlyRevenueHistory, revenueView),
    [monthlyRevenueHistory, revenueView]
  );
  const earningsSeries = useMemo(
    () => buildEarningsSeries(financialMetricHistory, earningsView),
    [financialMetricHistory, earningsView]
  );

  if (!stockId) {
    return watchlistRankingPanel ? (
      <section className="min-w-0">{watchlistRankingPanel}</section>
    ) : null;
  }


  return (
    <section
      data-testid="stock-detail-panel"
      data-chart-stock-id={chartStockId ?? ""}
      data-chart-timeframe={chartTimeframe}
      data-chart-load-state={loadState}
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
                      data-testid="stock-detail-expand"
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
                chartHistoryMessage && !errorMessage ? (
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
                  tone="loading"
                  busy
                  className="m-4"
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
              latestPreviousClose={chartOverlayPreviousClose}
            />
          ) : (
            <EmptyDataState
              message={t("stockDetail.loadingFrame", {
                label: timeframeLabel(t, effectiveTimeframe),
              })}
              tone="loading"
              busy
              className="m-4"
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
                  onClick={() => selectDataTab(tab.key)}
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
                  institutionalHoldingRatio={null}
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
                <EmptyDataState message={t("stockDetail.chipMetrics.empty")} />
              )}
            </div>
          </div>
      </aside>
      ) : null}

    </section>
  );
}

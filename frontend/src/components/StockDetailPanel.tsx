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
import NextSessionPlanPanel from "@/components/stock-detail/NextSessionPlanPanel";
import StockDetailDataPanel from "@/components/stock-detail/StockDetailDataPanel";
import TaiwanETFDataPanel from "@/components/stock-detail/TaiwanETFDataPanel";
import TaiwanQuoteDepthSurface from "@/components/stock-detail/TaiwanQuoteDepthSurface";
import {
  dataPanelTabs,
  etfDataPanelTabs,
} from "@/components/stock-detail/StockDetailPanelConstants";
import type { DataPanelSurfaceTab } from "@/components/stock-detail/DataPanelPrimitives";
import {
  buildChipDateGroups,
  buildEarningsSeries,
  buildInstitutionalSeries,
  buildRevenueSeries,
  buildShareholdingSeries,
} from "@/components/stock-detail/stockDetailSeriesProjection";
import {
  buildStockSignalChips,
  STOCK_DETAIL_DATA_PANEL_ID,
  stockTechnicalTerm,
  stockTechnicalText,
  type StockSignalTone,
} from "@/components/stock-detail/stockDetailSignalProjection";
import { buildFallbackTechnicalReport } from "@/components/stock-detail/stockDetailTechnicalReportProjection";
import TechnicalIndicatorMenu, {
  indicatorTemplates,
  type IndicatorTemplateKey,
} from "@/components/stock-detail/TechnicalIndicatorMenu";
import {
  buildCorporateEventChartMarkers,
  corporateEventMarkerOption,
  corporateEventMarkerOptionKey,
  defaultCorporateEventMarkersEnabled,
} from "@/components/stock-detail/corporateEventChartMarkers";
import { useChartDrawingPersistence } from "@/components/stock-detail/useChartDrawingPersistence";
import { useTaiwanDetailContext } from "@/components/stock-detail/useTaiwanDetailContext";
import { useTaiwanNextSessionPlan } from "@/components/stock-detail/useTaiwanNextSessionPlan";
import { useTaiwanDataPanel } from "@/components/stock-detail/useTaiwanDataPanel";
import { useTaiwanQuoteDepth } from "@/components/stock-detail/useTaiwanQuoteDepth";
import { useTaiwanStockChartData } from "@/components/stock-detail/useTaiwanStockChartData";
import { useTaiwanTechnicalReport } from "@/components/stock-detail/useTaiwanTechnicalReport";
import { useTaiwanCorporateEventChartHistory } from "@/components/stock-detail/useTaiwanCorporateEventChartHistory";
import {
  ChipMetricBlock,
  DataTabButton,
  EmptyDataState,
  IndexDetailDataPanel,
  IndexListPanel,
  MetricRow,
  OvernightImpactPanel,
  TechnicalCurrentStateEvidence,
  TechnicalCurrentStateOverview,
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
  resolveTodayHeadlineValues,
  safeRatio,
  summarizeIntradayPoints,
  valueTone,
} from "@/components/stock-detail/StockDetailDataViews";
import type {
  BranchTableSide,
  ChartTimeframe,
  DataPanelTab,
  EarningsView,
  LoadState,
  ProfessionalTimeframe,
  RevenueView,
  TechnicalReport,
  Timeframe,
} from "@/components/stock-detail/StockDetailDataViews";
import { emitDataStatusEvent, type DataStatusLevel } from "@/lib/dataStatusEvents";
import {
  getRefreshExecutionSeconds,
  useRefreshExecutionSettings,
} from "@/lib/refreshExecutionSettings";
import { timeframeLabel, useT, type TranslationFunction } from "@/i18n";
import { TAIWAN_INTRADAY_REFRESH_MS } from "@/lib/taiwanMarketTime";
import type {
  ChartPoint,
  MarketIndexSummary,
  OhlcIntradayOverlay,
  StockIndicatorPoint,
  TaiwanCorporateEventRead,
  TaiwanStockQuoteDepthPreviewMode,
} from "@/types/market";
import {
  type CSSProperties,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

type Props = {
  stockId: string | null;
  stockName: string | null;
  stockMarket?: string | null;
  instrumentType?: string | null;
  initialChartData?: ChartPoint[];
  initialChartIntradayOverlay?: OhlcIntradayOverlay | null;
  initialChartStockId?: string | null;
  initialChartVolumeUnit?: string | null;
  initialIndicatorData?: StockIndicatorPoint[];
  watchlistRankingPanel?: ReactNode;
  marketIndexSummary?: MarketIndexSummary | null;
  onChartFocusModeChange?: (active: boolean) => void;
  onDailyPricesChanged?: () => void;
  quoteDepthPreviewMode?: TaiwanStockQuoteDepthPreviewMode | null;
};

const emptyChartPoints: ChartPoint[] = [];
const emptyIndicatorPoints: StockIndicatorPoint[] = [];

function normalizeIsoDate(value: string | null | undefined) {
  return value ? value.slice(0, 10) : null;
}

function backendCurrentPartialIndicator(value: unknown): StockIndicatorPoint | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.time !== "string" ||
    typeof candidate.close !== "number" ||
    candidate.calculation_role !== "backend_authoritative"
  ) {
    return null;
  }
  return candidate as unknown as StockIndicatorPoint;
}

function corporateEventTone(eventType: string) {
  if (eventType === "ex_dividend") {
    return "border-omi-success bg-omi-success-soft text-omi-success-strong";
  }
  if (eventType === "financial_report") {
    return "border-omi-warning bg-omi-warning-soft text-omi-warning-strong";
  }
  return "border-omi-info bg-omi-info-soft text-omi-info-strong";
}

function corporateEventBadgeLabel(
  event: TaiwanCorporateEventRead,
  t: TranslationFunction
) {
  const eventLabel = t(`stockDetail.corporateEvents.types.${event.event_type}`);
  if (event.days_until === 0) {
    return eventLabel;
  }
  if (event.days_until === 1) {
    return t("stockDetail.corporateEvents.tomorrow", { event: eventLabel });
  }
  return t("stockDetail.corporateEvents.inDays", {
    days: event.days_until,
    event: eventLabel,
  });
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

function technicalMetricBarStyle(value: number | null | undefined): CSSProperties {
  const scale =
    value === null || value === undefined || Number.isNaN(value)
      ? 0
      : Math.max(0, Math.min(100, Math.abs(value))) / 100;
  return { "--omi-technical-bar-scale": scale } as CSSProperties;
}

function technicalMetricBarClass(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "bg-omi-border";
  }
  if (value > 0) return "bg-omi-market-up-flash";
  if (value < 0) return "bg-omi-market-down-flash";
  return "bg-omi-border";
}

function TechnicalMetricBar({
  displayValue,
  label,
  metricValue,
  resetKey,
  testId,
}: {
  displayValue: string;
  label: string;
  metricValue: number | null;
  resetKey: string;
  testId: string;
}) {
  return (
    <div data-testid={testId}>
      <div className="mb-1 flex justify-between gap-3 text-xs text-omi-text-muted">
        <span>{label}</span>
        <span className={valueTone(metricValue)}>
          <PriceUpdatePulse
            value={metricValue}
            direction={metricValue}
            resetKey={resetKey}
            className="justify-end tabular-nums"
          >
            {displayValue}
          </PriceUpdatePulse>
        </span>
      </div>
      <div className="h-2 bg-omi-surface-muted">
        <div
          className={`omi-technical-bar h-2 ${technicalMetricBarClass(metricValue)}`}
          style={technicalMetricBarStyle(metricValue)}
        />
      </div>
    </div>
  );
}

export default function StockDetailPanel({
  stockId,
  stockName,
  stockMarket = null,
  instrumentType = null,
  initialChartData = [],
  initialChartIntradayOverlay = null,
  initialChartStockId = null,
  initialChartVolumeUnit = "shares",
  initialIndicatorData = [],
  watchlistRankingPanel,
  marketIndexSummary,
  onChartFocusModeChange,
  onDailyPricesChanged,
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
  const [corporateEventMarkersEnabled, setCorporateEventMarkersEnabled] =
    useState(defaultCorporateEventMarkersEnabled);
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
  const [etfDataTabSelection, setEtfDataTabSelection] = useState<{
    stockId: string;
    tab: DataPanelSurfaceTab;
  } | null>(null);
  const indexProduct = stockId ? indexProducts.get(stockId) ?? null : null;
  const isIndexProduct = indexProduct !== null;
  const requestedInstrumentType =
    instrumentType?.trim().toLowerCase() ?? "unknown";
  const requestedInstrumentTypeResolved =
    requestedInstrumentType !== "" && requestedInstrumentType !== "unknown";
  const requestedIsEtfProduct = requestedInstrumentType === "etf";
  const requestedEtfDataTab =
    requestedIsEtfProduct && etfDataTabSelection?.stockId === stockId
      ? etfDataTabSelection.tab
      : "etf";
  const indexId = indexProduct?.indexId ?? null;
  const indexMarket = indexProduct?.market ?? null;
  const {
    quoteDepth,
    quoteReplay,
    loadState: quoteDepthLoadState,
    replayLoadState: quoteReplayLoadState,
  } = useTaiwanQuoteDepth({
    enabled: !isIndexProduct,
    stockId,
    streamEnabled: false,
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
      financialContract,
      institutional,
      institutionalHoldingRatio,
      institutionalHistory,
      margin,
      monthlyRevenue,
      monthlyRevenueHistory,
      shareholding,
      stockInfo,
    },
    actions: {
      refreshDataTab,
      selectDataTab,
      setBranchDays,
    },
  } = useTaiwanDataPanel({
    autoRefreshEnabled: requestedInstrumentTypeResolved
      ? !requestedIsEtfProduct || requestedEtfDataTab !== "etf"
      : null,
    includeFundamentals: requestedInstrumentTypeResolved
      ? !requestedIsEtfProduct
      : null,
    isIndexProduct,
    onDailyPricesChanged,
    stockId,
    subresourceRefreshSeconds: taiwanSubresourceRefreshSeconds,
    t,
  });
  const stockInfoInstrumentType =
    stockInfo?.stock_id === stockId
      ? stockInfo.instrument_type?.trim().toLowerCase() ?? "unknown"
      : "unknown";
  const normalizedInstrumentType = requestedInstrumentTypeResolved
    ? requestedInstrumentType
    : stockInfoInstrumentType;
  const isEtfProduct = normalizedInstrumentType === "etf";
  const selectedEtfDataTab =
    isEtfProduct && etfDataTabSelection?.stockId === stockId
      ? etfDataTabSelection.tab
      : "etf";
  const visibleDataPanelTabs = isEtfProduct ? etfDataPanelTabs : dataPanelTabs;
  const activeDataSurfaceTab = isEtfProduct ? selectedEtfDataTab : activeDataTab;
  const selectDataSurfaceTab = useCallback(
    (tab: DataPanelSurfaceTab) => {
      if (isEtfProduct) {
        if (!stockId) return;
        setEtfDataTabSelection({ stockId, tab });
      }
      if (tab !== "etf") {
        selectDataTab(tab);
      }
    },
    [isEtfProduct, selectDataTab, stockId]
  );
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
  const {
    loadState: nextSessionPlanLoadState,
    plan: nextSessionPlan,
  } = useTaiwanNextSessionPlan({
    enabled: !isIndexProduct && !isEtfProduct,
    stockId,
    stockName,
  });
  const chartDrawingRemoteMarket = isIndexProduct
    ? indexProduct.market
    : stockInfo?.market ?? stockMarket;
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
  const dataStatusContextKey = `tw:${isIndexProduct ? "index" : isEtfProduct ? "etf" : "stock"}:${stockId ?? "unknown"}`;
  const dataStatusSource = isIndexProduct ? "台股指數" : isEtfProduct ? "台股 ETF" : "台股個股";

  const publishDetailDataStatus = useCallback(
    ({
      level = "error",
      title,
      message,
      source = dataStatusSource,
      statusKey,
    }: {
      level?: DataStatusLevel;
      title: string;
      message: string;
      source?: string;
      statusKey?: string;
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
        dedupeKey: statusKey
          ? `${dataStatusContextKey}:${statusKey}`
          : `${dataStatusContextKey}:${source}:${title}:${level}`,
      });
    },
    [dataStatusContextKey, dataStatusContextLabel, dataStatusSource, stockId]
  );
  const currentStockInfoId = stockInfo?.stock_id ?? null;
  const currentStockInfoMarket = stockInfo?.market ?? null;
  const { events: corporateEventChartHistory } =
    useTaiwanCorporateEventChartHistory({
      contextKey: dataStatusContextKey,
      contextLabel: dataStatusContextLabel,
      enabled: !isIndexProduct && !isEtfProduct && corporateEventMarkersEnabled,
      fallback: stockInfo?.event_history,
      market: currentStockInfoMarket,
      stockId: currentStockInfoId,
    });
  const corporateEventMenuOptions = useMemo(
    () =>
      isIndexProduct || isEtfProduct
        ? []
        : [corporateEventMarkerOption(corporateEventMarkersEnabled, t)],
    [corporateEventMarkersEnabled, isEtfProduct, isIndexProduct, t]
  );
  const dispositionStatus = !isIndexProduct && !isEtfProduct
    ? stockInfo?.disposition ?? null
    : null;
  const dispositionVisible = Boolean(
    dispositionStatus?.is_disposition &&
      (dispositionStatus.status === "active" || dispositionStatus.status === "upcoming")
  );
  const dispositionSourceUncertain = Boolean(
    dispositionStatus &&
      !dispositionStatus.is_disposition &&
      dispositionStatus.cache_status !== "current"
  );
  const upcomingCorporateEvents = !isIndexProduct && !isEtfProduct
    ? stockInfo?.upcoming_events?.results ?? []
    : [];
  const historicalCorporateEvents = !isIndexProduct && !isEtfProduct
    ? stockInfo?.event_history?.results ?? []
    : [];
  const corporateEventSourceUncertain = Boolean(
    !upcomingCorporateEvents.length &&
      stockInfo?.upcoming_events &&
      stockInfo.upcoming_events.cache_status !== "current"
  );
  const corporateEventHistorySourceUncertain = Boolean(
    !historicalCorporateEvents.length &&
      stockInfo?.event_history &&
      stockInfo.event_history.cache_status !== "current"
  );
  useEffect(() => {
    if (
      !stockId ||
      isIndexProduct ||
      stockInfo?.stock_id !== stockId ||
      !stockInfo.upcoming_events
    ) {
      return;
    }

    const warnings = Array.from(new Set([
      stockInfo.upcoming_events.warning,
      stockInfo.event_history?.warning,
    ].filter((value): value is string => Boolean(value))));
    emitDataStatusEvent({
      market: "tw",
      level: warnings.length ? "warning" : "success",
      title: warnings.length
        ? t("settings.calendar.status.warningTitle")
        : t("settings.calendar.status.successTitle"),
      message: warnings.length
        ? warnings.join("；")
        : t("settings.calendar.status.stockSuccessMessage", {
            count: stockInfo.upcoming_events.result_count,
            stock: dataStatusContextLabel,
          }),
      source: t("settings.calendar.status.source"),
      contextKey: dataStatusContextKey,
      contextLabel: dataStatusContextLabel,
      dedupeKey: `${dataStatusContextKey}:corporate-events`,
    });
  }, [
    dataStatusContextKey,
    dataStatusContextLabel,
    isIndexProduct,
    stockId,
    stockInfo?.event_history?.warning,
    stockInfo?.stock_id,
    stockInfo?.upcoming_events,
    t,
  ]);
  const effectiveTimeframe = timeframe;
  const availableTimeframes = isIndexProduct ? indexTimeframes : allTimeframes;
  const {
    state: {
      benchmarkChartData,
      benchmarkChartKey,
      benchmarkIndexId,
      chartData,
      chartIntradayOverlay,
      chartVolumeUnit,
      chartStockId,
      chartTimeframe,
      indicatorData,
      loadState,
      professionalIntradayData,
      professionalIntradayFallbackActive,
      professionalIntradayInterval,
      professionalIntradayStockId,
      todayCapabilities,
      todayCurrentObservation,
      todayPreviousClose,
      todayPriceDiagnostics,
      todaySource,
      todayStockId,
      todayTradeDate,
      todayTrend,
      todayUpdatedAt,
    },
  } = useTaiwanStockChartData({
    chartFocusMode,
    currentStockInfoMarket,
    effectiveTimeframe,
    initialChartData,
    initialChartIntradayOverlay,
    initialChartStockId,
    initialChartVolumeUnit,
    initialIndicatorData,
    isIndexProduct,
    professionalTimeframe,
    publishDataStatus: publishDetailDataStatus,
    reloadNonce: chartReloadNonce,
    stockId,
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

  const chartMatchesSelection = stockId !== null && chartStockId === stockId;
  const currentChartReady =
    effectiveTimeframe !== "today" &&
    chartMatchesSelection &&
    chartTimeframe === effectiveTimeframe;
  const chartDataForTimeframe = currentChartReady ? chartData : emptyChartPoints;
  const indicatorDataForTimeframe = currentChartReady
    ? indicatorData
    : emptyIndicatorPoints;
  const dailyReferenceChartData =
    chartMatchesSelection && chartTimeframe === "daily" ? chartData : emptyChartPoints;
  const dailyReferenceIndicatorData =
    chartMatchesSelection && chartTimeframe === "daily"
      ? indicatorData
      : emptyIndicatorPoints;

  function toggleChartIndicator(key: IndicatorKey) {
    setActiveIndicatorTemplate(null);
    setChartIndicators((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  function toggleCorporateEventMarker(key: string) {
    if (key !== corporateEventMarkerOptionKey) return;
    setCorporateEventMarkersEnabled((current) => !current);
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
    if (effectiveTimeframe === "daily") {
      const pointsByDate = new Map(
        indicatorDataForTimeframe.map((point) => [normalizeIsoDate(point.time), point])
      );
      const currentPartial = backendCurrentPartialIndicator(
        backendTechnicalReport?.data.current_partial_indicator
      );
      if (currentPartial) {
        pointsByDate.set(normalizeIsoDate(currentPartial.time), currentPartial);
      }
      return [...pointsByDate.values()]
        .sort((left, right) => left.time.localeCompare(right.time))
        .slice(-180);
    }
    return [];
  }, [backendTechnicalReport, effectiveTimeframe, indicatorDataForTimeframe]);

  const latestIndicator =
    indicatorDataForTimeframe[indicatorDataForTimeframe.length - 1] ?? null;
  const latestChart = chartDataForTimeframe[chartDataForTimeframe.length - 1] ?? null;
  const previousChart = chartDataForTimeframe[chartDataForTimeframe.length - 2] ?? null;
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
  const canUseFocusedKLine = currentChartReady && chartDataForTimeframe.length > 0;
  const latestToday = todayTrend[todayTrend.length - 1] ?? null;
  const latestTodayDisplayPrice = finiteNumber(todayCurrentObservation?.value)
    ? todayCurrentObservation.value
    : latestToday?.price ?? null;
  const officialCompletedClose =
    quoteDepth?.official_close_available === true &&
    finiteNumber(quoteDepth.official_close_price)
      ? quoteDepth.official_close_price
      : null;
  const confirmedSessionClose =
    quoteDepth?.session_close_available === true &&
    finiteNumber(quoteDepth.session_close_price)
      ? quoteDepth.session_close_price
      : null;
  const completedSessionHeadline = officialCompletedClose ?? confirmedSessionClose;
  const todayStats = useMemo(
    () =>
      summarizeIntradayPoints(todayTrend, {
        tradeDate: todayTradeDate,
      }),
    [todayTradeDate, todayTrend]
  );
  const todayIndicatorOptions = intradayIndicatorOptions.filter((option) => {
    if (option.key === "volume") return todayCapabilities.supports_volume;
    if (option.key === "vwap") return todayCapabilities.supports_vwap;
    return true;
  });
  const todayIntradayIndicators = {
    ...intradayIndicators,
    volume: intradayIndicators.volume && todayCapabilities.supports_volume,
    vwap: intradayIndicators.vwap && todayCapabilities.supports_vwap,
  };
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
  const chartCorporateEventMarkers = useMemo(
    () =>
      effectiveTimeframe === "today"
        ? []
        : buildCorporateEventChartMarkers({
            chartData,
            enabled: corporateEventMarkersEnabled,
            events: corporateEventChartHistory,
            timeframe: effectiveTimeframe,
            t,
          }),
    [
      chartData,
      corporateEventChartHistory,
      corporateEventMarkersEnabled,
      effectiveTimeframe,
      t,
    ]
  );
  const professionalCorporateEventMarkers = useMemo(
    () =>
      professionalIsIntraday
        ? []
        : buildCorporateEventChartMarkers({
            chartData: professionalChartData,
            enabled: corporateEventMarkersEnabled,
            events: corporateEventChartHistory,
            timeframe: professionalTimeframe,
            t,
          }),
    [
      corporateEventChartHistory,
      corporateEventMarkersEnabled,
      professionalChartData,
      professionalIsIntraday,
      professionalTimeframe,
      t,
    ]
  );
  const professionalChartReady =
    chartFocusMode &&
    professionalChartData.length > 0 &&
    (professionalIsIntraday || currentChartReady);
  const professionalTimeframeLabel = t(`timeframes.${professionalTimeframe}`);
  const latestProfessionalChart = professionalChartData[professionalChartData.length - 1] ?? null;
  const latestDailyReferenceChart =
    dailyReferenceChartData[dailyReferenceChartData.length - 1] ?? null;
  const latestDailyReferenceIndicator =
    dailyReferenceIndicatorData[dailyReferenceIndicatorData.length - 1] ?? null;
  const latestDailyReferenceIndicatorDate = normalizeIsoDate(
    latestDailyReferenceIndicator?.time
  );
  const latestDailyCurrentIndicator =
    latestDailyReferenceIndicator !== null &&
    normalizeIsoDate(latestDailyReferenceChart?.time) !== null &&
    latestDailyReferenceIndicatorDate === normalizeIsoDate(latestDailyReferenceChart?.time)
      ? latestDailyReferenceIndicator
      : null;
  const dailyPreviousClose =
    latestDailyCurrentIndicator?.close !== null &&
    latestDailyCurrentIndicator?.close !== undefined &&
    latestDailyCurrentIndicator?.change !== null &&
    latestDailyCurrentIndicator?.change !== undefined
      ? latestDailyCurrentIndicator.close - latestDailyCurrentIndicator.change
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
  const todayHeadlineValues = resolveTodayHeadlineValues({
    currentPrice: latestTodayDisplayPrice,
    currentReferenceClose: todayReferenceClose,
    completedSessionPrice: completedSessionHeadline,
    completedSessionReferenceClose: quoteDepth?.previous_close,
  });
  const todayHeadlinePrice: number | null = todayHeadlineValues[0];
  const todayHeadlineChange: number | null = todayHeadlineValues[1];
  const todayHeadlineChangePct: number | null = todayHeadlineValues[2];
  const latestClose: number | null =
    effectiveTimeframe === "today"
      ? todayHeadlinePrice
      : completedSessionHeadline ?? latestCurrentIndicator?.close ?? latestChart?.close ?? null;
  const latestChange: number | null =
    effectiveTimeframe === "today"
      ? todayHeadlineChange
      : completedSessionHeadline !== null && finiteNumber(quoteDepth?.previous_close)
        ? completedSessionHeadline - quoteDepth.previous_close
      : latestCurrentIndicator?.change ?? chartChange;
  const latestChangePct: number | null =
    effectiveTimeframe === "today"
      ? todayHeadlineChangePct
      : completedSessionHeadline !== null &&
          finiteNumber(quoteDepth?.previous_close) &&
          quoteDepth.previous_close !== 0
        ? ((completedSessionHeadline - quoteDepth.previous_close) / quoteDepth.previous_close) * 100
      : latestCurrentIndicator?.change_pct ?? chartChangePct;
  const professionalLatestClose =
    chartFocusMode && professionalIsIntraday
      ? latestProfessionalChart?.close ?? latestTodayDisplayPrice ?? latestClose
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
    chartFocusMode && professionalIsIntraday && latestTodayDisplayPrice !== null && todayReferenceClose
      ? latestTodayDisplayPrice - todayReferenceClose
      : latestChange;
  const professionalLatestChangePct =
    chartFocusMode && professionalIsIntraday && latestTodayDisplayPrice !== null && todayReferenceClose
      ? ((latestTodayDisplayPrice - todayReferenceClose) / todayReferenceClose) * 100
      : latestChangePct;
  const professionalHeaderLimitStatus = isIndexProduct
    ? null
    : estimatedPriceLimitStatus(professionalLatestChangePct);
  const headerLimitStatus = isIndexProduct ? null : estimatedPriceLimitStatus(latestChangePct);
  const technicalReferenceChartData =
    effectiveTimeframe === "today" ? dailyReferenceChartData : chartDataForTimeframe;
  const technicalReferenceIndicator =
    effectiveTimeframe === "today" ? latestDailyCurrentIndicator : latestCurrentIndicator;
  const ma5 =
    technicalReferenceIndicator?.ma?.ma5 ??
    averageRecentChartValue(technicalReferenceChartData, "close", 5);
  const ma20 =
    technicalReferenceIndicator?.ma?.ma20 ??
    averageRecentChartValue(technicalReferenceChartData, "close", 20);
  const ma60 =
    technicalReferenceIndicator?.ma?.ma60 ??
    averageRecentChartValue(technicalReferenceChartData, "close", 60);
  const volumeMa20 =
    technicalReferenceIndicator?.volume_ma?.volume_ma20 ??
    averageRecentChartValue(technicalReferenceChartData, "volume", 20);
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
    effectiveTimeframe === "today" && todayCurrentObservation?.observed_at
      ? formatDateTime(todayCurrentObservation.observed_at)
      : effectiveTimeframe === "today" && latestToday
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

  const fallbackTechnicalReport = buildFallbackTechnicalReport({
    chartData: technicalReferenceChartData,
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
  });
  const localizedFallbackTechnicalReport = localizeTechnicalReport(
    fallbackTechnicalReport,
    t
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
  const unavailableDailyTechnicalReport = useMemo<TechnicalReport>(
    () => ({
      title: t("stockDetail.dataViews.technical.unavailableTitle"),
      summary: t("stockDetail.dataViews.technical.unavailableSummary"),
      value: null,
      valueLabel: t("stockDetail.dataViews.technical.finalizedValueLabel"),
      score: 0,
      rows: [],
      badges: [],
      currentState: null,
      decisionState: null,
      decisionStateStatus: "unavailable",
      currentStateStatus: "unavailable",
      currentStateDecisionUsable: false,
      warningCount: 1,
    }),
    [t]
  );
  const technicalReport =
    backendTechnicalReportView ??
    (effectiveTimeframe === "daily"
      ? unavailableDailyTechnicalReport
      : localizedFallbackTechnicalReport);
  const technicalDecisionState =
    effectiveTimeframe === "daily"
      ? technicalReport.decisionState ??
        (technicalReport.currentStateDecisionUsable
          ? technicalReport.currentState ?? null
          : null)
      : null;
  const technicalProvisionalState =
    effectiveTimeframe === "daily" &&
    technicalReport.currentObservation?.decisionUsable === false
      ? technicalReport.currentObservation.currentState
      : null;
  const technicalCurrentState = technicalDecisionState;
  const technicalStatus = technicalDecisionState?.headline.label ?? technicalReport.title;
  const technicalSummaryText = technicalReport.summary;
  const technicalPositionUsesBelow =
    (technicalCurrentState?.position.belowCount ?? 0) > 0;
  const technicalPositionCount =
    technicalCurrentState && technicalCurrentState.position.availableCount > 0
      ? `${
          technicalPositionUsesBelow
            ? technicalCurrentState.position.belowCount
            : technicalCurrentState.position.aboveCount
        }/${technicalCurrentState.position.availableCount}`
      : "-";
  const technicalPositionLabel = technicalCurrentState
    ? technicalCurrentState.position.availableCount > 0
      ? t(
          technicalPositionUsesBelow
            ? "stockDetail.technicalCurrentState.belowAverages"
            : "stockDetail.technicalCurrentState.aboveAverages"
        )
      : technicalCurrentState.position.label
    : "";
  const intradayVolumePaceRow =
    effectiveTimeframe === "today"
      ? technicalReport.rows.find((row) => row.key === "volume_pace") ?? null
      : null;
  const intradayVolumePaceValue = intradayVolumePaceRow?.pulseValue;
  const parsedIntradayVolumePaceRatio =
    typeof intradayVolumePaceValue === "number"
      ? intradayVolumePaceValue
      : typeof intradayVolumePaceValue === "string" && intradayVolumePaceValue.trim()
        ? Number(intradayVolumePaceValue)
        : Number.NaN;
  const intradayVolumePaceRatio = Number.isFinite(parsedIntradayVolumePaceRatio)
    ? parsedIntradayVolumePaceRatio
    : null;
  const technicalVolumeMetric =
    effectiveTimeframe === "today"
      ? intradayVolumePaceRatio === null
        ? null
        : (intradayVolumePaceRatio - 1) * 100
      : volumeRatioPct;
  const technicalVolumeDisplay =
    effectiveTimeframe === "today"
      ? intradayVolumePaceRow?.value ?? "-"
      : formatPct(volumeRatioPct);
  const displayOvernightImpact = !stockId || isIndexProduct ? null : overnightImpact;
  const displayOvernightImpactLoadState: LoadState =
    !stockId || isIndexProduct ? "idle" : overnightImpactLoadState;
  const stockSignalChips = buildStockSignalChips({
    technicalReport,
    institutional,
    margin,
    monthlyRevenue,
    overnightImpact: displayOvernightImpact,
    relativeToPrimaryIndex,
    primaryMarketLabel: primaryMarketIndex?.short_label ?? stockTechnicalTerm(t, "market"),
    t,
  });
  const stockSignalChipGroups = [
    {
      key: "technical",
      label: stockTechnicalText(t, "chips.groups.core"),
      chips: stockSignalChips.filter((chip) => chip.group === "technical"),
    },
    {
      key: "context",
      label: stockTechnicalText(t, "chips.groups.context"),
      chips: stockSignalChips.filter((chip) => chip.group === "context"),
    },
  ].filter((group) => group.chips.length > 0);
  const revealStockSignalDetail = useCallback(
    (targetId: string, dataTabTarget?: DataPanelTab) => {
      const target = document.getElementById(targetId);
      if (!(target instanceof HTMLElement)) return;

      if (target instanceof HTMLDetailsElement) {
        target.open = true;
      }
      let ancestorDetails = target.parentElement?.closest("details") ?? null;
      while (ancestorDetails instanceof HTMLDetailsElement) {
        ancestorDetails.open = true;
        ancestorDetails = ancestorDetails.parentElement?.closest("details") ?? null;
      }
      if (dataTabTarget) {
        selectDataSurfaceTab(dataTabTarget);
      }

      window.requestAnimationFrame(() => {
        const prefersReducedMotion = window.matchMedia(
          "(prefers-reduced-motion: reduce)"
        ).matches;
        target.scrollIntoView({
          behavior: prefersReducedMotion ? "auto" : "smooth",
          block: "nearest",
        });
        const focusTarget = dataTabTarget
          ? target.querySelector(`[data-data-tab="${dataTabTarget}"]`)
          : target.querySelector("summary");
        if (focusTarget instanceof HTMLElement) {
          focusTarget.focus({ preventScroll: true });
        }
      });
    },
    [selectDataSurfaceTab]
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
      data-current-price={latestClose ?? ""}
      data-today-stock-id={todayStockId ?? ""}
      className={[
        "grid w-full grid-cols-1 items-start justify-start gap-4",
        chartFocusMode ? "" : "xl:grid-cols-[minmax(0,7fr)_minmax(360px,5fr)]",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className={["min-w-0 self-start", chartFocusMode ? "space-y-0" : "space-y-4"].join(" ")}>
        <div
          data-testid="stock-chart-card"
          className={chartFocusMode ? "min-w-0" : "min-w-0 border border-omi-border-subtle bg-omi-surface"}
        >
          {chartFocusMode ? null : (
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {isIndexProduct
                  ? t("stockDetail.entity.index")
                  : t("stockDetail.entity.stock")}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <h2 className="text-2xl font-bold text-omi-text-strong">
                  {stockId} {indexProduct?.stockName ?? stockName ?? stockInfo?.stock_name ?? ""}
                </h2>
                {dispositionVisible ? (
                  <span
                    className={[
                      "inline-flex items-center border px-2 py-1 text-xs font-bold",
                      dispositionStatus?.is_active
                        ? "border-omi-market-down/50 bg-omi-market-down/10 text-omi-market-down"
                        : "border-amber-400/50 bg-amber-400/10 text-amber-200",
                    ].join(" ")}
                    title={[
                      dispositionStatus?.reason,
                      dispositionStatus?.start_date && dispositionStatus?.end_date
                        ? `${dispositionStatus.start_date} – ${dispositionStatus.end_date}`
                        : null,
                      dispositionStatus?.warning,
                    ]
                      .filter(Boolean)
                      .join("\n")}
                  >
                    {dispositionStatus?.is_active
                      ? t("stockDetail.disposition.active")
                      : t("stockDetail.disposition.upcoming")}
                    {dispositionStatus?.matching_interval_minutes
                      ? ` · ${t("stockDetail.disposition.interval", {
                          minutes: dispositionStatus.matching_interval_minutes,
                        })}`
                      : null}
                  </span>
                ) : dispositionSourceUncertain ? (
                  <span
                    className="inline-flex items-center border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-xs font-semibold text-amber-200"
                    title={dispositionStatus?.warning ?? undefined}
                  >
                    {t("stockDetail.disposition.sourceUncertain")}
                  </span>
                ) : null}
                {upcomingCorporateEvents.map((event) => (
                  <span
                    key={event.event_id}
                    className={[
                      "inline-flex items-center border px-2 py-1 text-xs font-bold",
                      corporateEventTone(event.event_type),
                    ].join(" ")}
                    title={[
                      `${event.start_date}${event.start_time ? ` ${event.start_time}` : ""}`,
                      event.summary,
                      event.location,
                      event.source_name,
                    ]
                      .filter(Boolean)
                      .join("\n")}
                  >
                    {corporateEventBadgeLabel(event, t)}
                  </span>
                ))}
                {corporateEventSourceUncertain ? (
                  <span
                    className="inline-flex items-center border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-xs font-semibold text-amber-200"
                    title={stockInfo?.upcoming_events?.warning ?? undefined}
                  >
                    {t("stockDetail.corporateEvents.sourceUncertain")}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 text-sm text-omi-text-muted">
                {indexProduct
                  ? `${indexProduct.market} · 指數 · ${indexProduct.symbol}`
                  : `${stockInfo?.market ?? "-"} · ${
                      stockInfo?.industry ?? t("stockDetail.uncategorized")
                    }`}{" "}
                ·{" "}
                {displayTime}
              </div>
              {historicalCorporateEvents.length ? (
                <details className="group mt-3 max-w-[720px] text-sm">
                  <summary className="inline-flex cursor-pointer list-none items-center gap-2 border border-omi-border bg-omi-surface-subtle px-3 py-1.5 text-xs font-bold text-omi-text-muted hover:border-omi-control hover:text-omi-text">
                    <span>{t("stockDetail.corporateEvents.historyTitle")}</span>
                    <span className="text-omi-text-strong">
                      {stockInfo?.event_history?.total_count ?? historicalCorporateEvents.length}
                    </span>
                    <span aria-hidden="true" className="transition group-open:rotate-180">⌄</span>
                  </summary>
                  <div className="mt-2 max-h-56 overflow-y-auto border border-omi-border-subtle bg-omi-surface-subtle">
                    {historicalCorporateEvents.map((event) => (
                      <div
                        key={event.event_id}
                        className="grid gap-2 border-b border-omi-border-subtle px-3 py-2 last:border-b-0 sm:grid-cols-[92px_88px_minmax(0,1fr)_auto] sm:items-center"
                      >
                        <span className="font-mono text-xs text-omi-text-muted">
                          {event.start_date}
                        </span>
                        <span className={`w-fit border px-2 py-0.5 text-[11px] font-bold ${corporateEventTone(event.event_type)}`}>
                          {t(`stockDetail.corporateEvents.types.${event.event_type}`)}
                        </span>
                        <span className="min-w-0 truncate text-xs text-omi-text" title={event.summary ?? event.title}>
                          {event.title}
                          {event.cash_dividend !== null
                            ? ` · ${t("settings.calendar.cashDividend", { amount: event.cash_dividend })}`
                            : ""}
                        </span>
                        <a
                          href={event.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs font-semibold text-omi-accent hover:underline"
                        >
                          {t("settings.calendar.sourceLink")}
                        </a>
                      </div>
                    ))}
                  </div>
                </details>
              ) : corporateEventHistorySourceUncertain ? (
                <div className="mt-2 text-xs font-semibold text-omi-warning">
                  {t("stockDetail.corporateEvents.historyUnavailable")}
                </div>
              ) : null}
            </div>

            <div className="flex items-start gap-5">
              <div
                data-testid={effectiveTimeframe === "today" ? "today-header-price" : undefined}
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
                      data-testid={`timeframe-${item}`}
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
                      data-testid="chart-indicator-menu-toggle"
                      onClick={() => setIndicatorMenuOpen((value) => !value)}
                      className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                    >
                      {t("stockDetail.indicators")}
                    </button>
                    {indicatorMenuOpen ? (
                      <div
                        data-testid="intraday-indicator-menu"
                        className="absolute right-0 z-20 mt-2 w-56 border border-omi-border-subtle bg-omi-surface p-3 text-left shadow-lg"
                      >
                        <div className="mb-2 text-xs font-bold text-omi-text-muted">{t("stockDetail.displayItems")}</div>
                        {todayIndicatorOptions.map((option) => (
                          <label
                            key={option.key}
                            data-indicator-option={option.key}
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
                        data-testid="chart-indicator-menu-toggle"
                        onClick={() => setIndicatorMenuOpen((value) => !value)}
                        className="h-8 border border-omi-control bg-omi-surface px-3 text-sm font-semibold text-omi-text hover:border-omi-accent hover:text-omi-danger"
                      >
                        {t("stockDetail.indicators")}
                      </button>
                      {indicatorMenuOpen ? (
                        <TechnicalIndicatorMenu
                          indicators={chartIndicators}
                          activeTemplate={
                            activeIndicatorTemplate
                          }
                          onApplyTemplate={applyIndicatorTemplate}
                          onToggleIndicator={toggleChartIndicator}
                          supplementalMarkerOptions={
                            corporateEventMenuOptions
                          }
                          onToggleSupplementalMarker={
                            toggleCorporateEventMarker
                          }
                          showTemplates
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
                  supplementalMarkerOptions={corporateEventMenuOptions}
                  onToggleSupplementalMarker={toggleCorporateEventMarker}
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
              eventMarkers={professionalCorporateEventMarkers}
              volumePanelLabel={
                isIndexProduct
                  ? t("chart.kline.tradeValueYi")
                  : chartVolumeUnit === "shares"
                    ? t("chart.kline.volumeShares")
                    : t("chart.kline.volume")
              }
              volumeValueKey={isIndexProduct ? "trade_value" : "volume"}
              canonicalIndicatorAuthority={
                !isIndexProduct && professionalTimeframe === "daily"
                  ? "backend"
                  : "presentation"
              }
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
            <div
              data-testid="today-intraday-surface"
              data-point-count={todayTrend.length}
            >
              <IntradayTrendChart
                points={todayTrend}
                previousClose={todayPreviousClose}
                label={timeframeLabel(t, effectiveTimeframe)}
                source={todaySource}
                indicators={todayIntradayIndicators}
                revealKey={`${stockId}:${effectiveTimeframe}`}
                refreshIntervalMs={TAIWAN_INTRADAY_REFRESH_MS}
                updatedAt={todayUpdatedAt}
                priceLimitEnabled={todayCapabilities.supports_price_limit}
                priceDiagnostics={todayPriceDiagnostics}
                tradeDate={todayTradeDate}
              />
            </div>
          ) : currentChartReady ? (
            <StockKLineChart
              chartData={chartData}
              indicatorData={indicatorForTimeframe}
              label={timeframeLabel(t, effectiveTimeframe)}
              indicators={chartIndicators}
              indicatorParameters={indicatorParameters}
              benchmarkData={benchmarkDataForChart}
              benchmarkLabel={benchmarkLabel}
              eventMarkers={chartCorporateEventMarkers}
              revealKey={`${stockId}:${effectiveTimeframe}`}
              volumePanelLabel={
                isIndexProduct
                  ? t("chart.kline.tradeValueYi")
                  : chartVolumeUnit === "shares"
                    ? t("chart.kline.volumeShares")
                    : t("chart.kline.volume")
              }
              volumeTooltipLabel={
                isIndexProduct
                  ? t("chart.kline.tradeValueYi")
                  : chartVolumeUnit === "shares"
                    ? t("chart.kline.volumeShares")
                    : t("chart.kline.volume")
              }
              volumeValueKey={isIndexProduct ? "trade_value" : "volume"}
              volumeValueFormatter={
                isIndexProduct
                  ? formatTradeValueYi
                  : chartVolumeUnit === "shares"
                    ? formatNumber
                    : undefined
              }
              latestPreviousClose={chartOverlayPreviousClose}
              canonicalIndicatorAuthority={
                !isIndexProduct && effectiveTimeframe === "daily"
                  ? "backend"
                  : "presentation"
              }
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

        {!chartFocusMode && !isIndexProduct ? (
          <button
            type="button"
            data-testid="technical-compact-jump"
            onClick={() => {
              document
                .getElementById("tw-stock-technical-panel")
                ?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            className="flex w-full items-center justify-between gap-3 border border-omi-border-subtle bg-omi-surface px-4 py-3 text-left xl:hidden"
          >
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
              Technical
            </span>
            <span className="min-w-0 truncate text-sm font-semibold text-omi-text-strong">
              {technicalStatus}
            </span>
            <span aria-hidden="true" className="text-omi-text-muted">
              ↓
            </span>
          </button>
        ) : null}

        {!chartFocusMode && !isIndexProduct && !showTechnicalLoading ? (
          <div className="min-w-0 border-x border-t border-omi-border-subtle bg-omi-surface">
            <TaiwanQuoteDepthSurface
              stockId={stockId}
              quoteDepth={quoteDepth}
              quoteReplay={quoteReplay}
              loadState={quoteDepthLoadState}
              replayLoadState={quoteReplayLoadState}
              quoteDepthPreviewMode={quoteDepthPreviewMode}
            />
          </div>
        ) : null}

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
        id="tw-stock-technical-panel"
        data-testid="stock-detail-secondary-panel"
        data-current-state-status={technicalReport.currentStateStatus ?? "unknown"}
        data-decision-state-status={technicalReport.decisionStateStatus ?? "unknown"}
        data-current-state-decision-usable={
          technicalReport.currentStateDecisionUsable === false ? "false" : "true"
        }
        className="flex min-w-0 scroll-mt-4 flex-col border border-omi-border-subtle bg-omi-surface"
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
            <div className="omi-technical-summary border-b border-omi-border-subtle px-5 py-3">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                {effectiveTimeframe === "daily"
                  ? t("stockDetail.dataViews.technical.finalizedTitle")
                  : stockTechnicalText(t, "eyebrow")}
              </div>
              <div className="mt-1.5 flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-lg font-semibold leading-5 text-omi-text-strong">
                    {technicalStatus}
                  </div>
                  <div className="mt-0.5 text-xs leading-4 text-omi-text-muted">
                    {technicalSummaryText}
                  </div>
                  {technicalReport.basisLabel ? (
                    <div className="mt-1 text-[11px] leading-4 text-omi-text-muted">
                      {technicalReport.basisLabel}
                      {technicalReport.warningCount ? (
                        <span className="ml-1 text-omi-warning">
                          · {t("stockDetail.dataViews.technical.basis.warningCount", {
                            count: technicalReport.warningCount,
                          })}
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                  {effectiveTimeframe === "daily" && technicalReport.decisionStateTime ? (
                    <div className="mt-1 text-[11px] leading-4 text-omi-text-subtle">
                      {t("stockDetail.dataViews.technical.finalizedAsOf", {
                        date: technicalReport.decisionStateTime.slice(0, 10),
                      })}
                    </div>
                  ) : null}
                </div>
                {technicalCurrentState ? (
                  <div
                    className="omi-technical-score shrink-0 text-right"
                    data-testid="tw-technical-position-count"
                  >
                    <div className="text-lg font-semibold leading-5 tabular-nums text-omi-text-strong">
                      {technicalPositionCount}
                    </div>
                    <div className="text-xs font-medium text-omi-text-muted">
                      {technicalPositionLabel}
                    </div>
                    <div className="mt-0.5 max-w-44 text-[11px] leading-4 text-omi-text-subtle">
                      {technicalCurrentState.position.orderLabel}
                    </div>
                  </div>
                ) : (
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
                )}
              </div>
              {stockSignalChipGroups.length ? (
                <div
                  className="mt-2 space-y-1"
                  aria-label={t("stockDetail.chipMetrics.technicalSignalsAria")}
                  data-testid="tw-signal-chip-groups"
                >
                  {stockSignalChipGroups.map((group) => (
                    <div
                      key={group.key}
                      className="flex items-start gap-1.5"
                      data-testid={`tw-signal-chip-group-${group.key}`}
                    >
                      <span className="w-14 shrink-0 pt-0.5 text-[10px] font-semibold leading-4 text-omi-text-muted">
                        {group.label}
                      </span>
                      <div className="flex min-w-0 flex-wrap gap-1">
                        {group.chips.map((signal) => {
                          const chipClassName = [
                            "omi-technical-badge omi-signal-chip omi-technical-signal-chip inline-flex shrink-0 items-center gap-1 border px-1.5 py-0.5 text-[11px] font-semibold leading-4 tabular-nums",
                            stockSignalToneClass(signal.tone),
                            signal.detailTarget
                              ? "cursor-pointer outline-none transition hover:-translate-y-px hover:brightness-95 active:translate-y-0 focus-visible:ring-2 focus-visible:ring-omi-accent"
                              : "",
                          ].join(" ");
                          const content = (
                            <>
                              <span className="text-[10px] opacity-75">
                                {signal.source}：
                              </span>
                              <span>{signal.label}</span>
                            </>
                          );
                          const sharedProps = {
                            className: chipClassName,
                            title: signal.title,
                            "data-testid": `tw-signal-chip-${signal.key}`,
                            "data-horizon": signal.horizon,
                            "data-as-of": signal.asOf ?? undefined,
                          };

                          return signal.detailTarget ? (
                            <button
                              key={signal.key}
                              type="button"
                              {...sharedProps}
                              aria-controls={signal.detailTarget}
                              data-data-tab-target={signal.dataTabTarget}
                              onClick={() =>
                                revealStockSignalDetail(
                                  signal.detailTarget ?? "",
                                  signal.dataTabTarget
                                )
                              }
                            >
                              {content}
                            </button>
                          ) : (
                            <span key={signal.key} {...sharedProps}>
                              {content}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>

            {technicalProvisionalState ? (
              <section
                className="border-b border-omi-warning/40 bg-omi-warning/5"
                data-testid="tw-technical-provisional-section"
              >
                <div className="flex items-start justify-between gap-4 px-5 py-3">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-warning">
                      {t("stockDetail.dataViews.technical.provisionalTitle")}
                    </div>
                    <div className="mt-1 text-sm font-semibold text-omi-text-strong">
                      {technicalProvisionalState.headline.label}
                    </div>
                    <div className="mt-0.5 text-xs leading-4 text-omi-text-muted">
                      {technicalProvisionalState.summary}
                    </div>
                    <div className="mt-1 text-[11px] leading-4 text-omi-text-subtle">
                      {t("stockDetail.dataViews.technical.provisionalAsOf", {
                        date:
                          technicalReport.currentObservation?.time?.slice(0, 10) ?? "-",
                        status:
                          technicalReport.currentObservation?.status ?? "-",
                      })}
                    </div>
                  </div>
                  <span className="shrink-0 border border-omi-warning/50 bg-omi-surface px-2 py-1 text-[11px] font-semibold text-omi-warning">
                    {t("stockDetail.dataViews.technical.decisionUnavailable")}
                  </span>
                </div>
                <div className="grid gap-px border-t border-omi-warning/30 bg-omi-border-subtle sm:grid-cols-3">
                  <div className="bg-omi-surface px-5 py-3">
                    <div className="text-[11px] font-semibold text-omi-text-muted">
                      {t("stockDetail.dataViews.technical.provisionalPrice")}
                    </div>
                    <div className="mt-0.5 text-sm font-semibold tabular-nums text-omi-text-strong">
                      {formatPrice(technicalProvisionalState.position.price)}
                    </div>
                  </div>
                  <div className="bg-omi-surface px-5 py-3">
                    <div className="text-[11px] font-semibold text-omi-text-muted">
                      {t("stockDetail.dataViews.technical.provisionalPosition")}
                    </div>
                    <div className="mt-0.5 text-sm font-semibold text-omi-text-strong">
                      {technicalProvisionalState.position.label}
                    </div>
                  </div>
                  <div className="bg-omi-surface px-5 py-3">
                    <div className="text-[11px] font-semibold text-omi-text-muted">
                      {t("stockDetail.dataViews.technical.provisionalMomentum")}
                    </div>
                    <div className="mt-0.5 text-sm font-semibold text-omi-text-strong">
                      {technicalProvisionalState.qualifier.label}
                    </div>
                  </div>
                </div>
              </section>
            ) : null}

            {technicalCurrentState ? (
              <TechnicalCurrentStateOverview state={technicalCurrentState} />
            ) : (
              <div
                className="space-y-3 border-b border-omi-border-subtle px-5 py-4 text-sm"
                data-testid="tw-technical-metrics"
              >
                <TechnicalMetricBar
                  label={t("stockDetail.technicalMetrics.priceVsMa20")}
                  displayValue={formatPct(priceVsMa20)}
                  metricValue={priceVsMa20}
                  resetKey={`${stockId ?? "empty"}:technical-metric-price`}
                  testId="tw-technical-metric-price"
                />
                <TechnicalMetricBar
                  label={t(
                    effectiveTimeframe === "today"
                      ? "stockDetail.technicalMetrics.volumePace"
                      : "stockDetail.technicalMetrics.volumeVsMa20"
                  )}
                  displayValue={technicalVolumeDisplay}
                  metricValue={technicalVolumeMetric}
                  resetKey={`${stockId ?? "empty"}:technical-metric-volume`}
                  testId="tw-technical-metric-volume"
                />
                <TechnicalMetricBar
                  label={t("stockDetail.technicalMetrics.dayChangePct")}
                  displayValue={formatPct(latestChangePct)}
                  metricValue={latestChangePct}
                  resetKey={`${stockId ?? "empty"}:technical-metric-change`}
                  testId="tw-technical-metric-change"
                />
              </div>
            )}

            <div className="px-5 py-3">
              {technicalCurrentState ? (
                <>
                  <div className="mb-2 text-xs font-semibold text-omi-text-muted">
                    {t("stockDetail.dataViews.technical.finalizedDetailTitle")}
                  </div>
                  <TechnicalCurrentStateEvidence state={technicalCurrentState}>
                    <details
                      id="tw-technical-context"
                      className="group/technical-context border border-omi-border-subtle bg-omi-surface-muted"
                      data-testid="tw-technical-context"
                    >
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3.5 py-2.5 outline-none transition hover:bg-omi-surface focus-visible:ring-2 focus-visible:ring-omi-accent [&::-webkit-details-marker]:hidden">
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold text-omi-text-strong">
                          {t("stockDetail.technicalCurrentState.contextTitle")}
                        </span>
                        <span className="mt-0.5 block text-xs leading-4 text-omi-text-subtle">
                          {t("stockDetail.technicalCurrentState.contextHint")}
                        </span>
                      </span>
                      <span
                        aria-hidden="true"
                        className="shrink-0 text-base text-omi-text-muted transition-transform group-open/technical-context:rotate-45"
                      >
                        ＋
                      </span>
                    </summary>
                    <div className="border-t border-omi-border-subtle px-3 pb-3">
                      {technicalReport.rows
                        .filter((row) => row.key === "institutional_flow")
                        .map((row) => (
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
                      <div className="mt-3 border-t border-omi-border-subtle pt-3">
                        <div className="omi-technical-market flex items-start justify-between gap-4 text-xs">
                          <div>
                            <div className="font-bold uppercase tracking-[0.14em] text-omi-text-muted">
                              {t("dashboard.marketIndex.market")}
                            </div>
                            <div className="mt-0.5 text-sm font-bold text-omi-text-strong">
                              {primaryMarketIndex?.short_label ?? t("stockDetail.marketFallback")}
                            </div>
                            <div className="mt-0.5 text-omi-text-muted">
                              {marketRegimeLabel(primaryMarketIndex, t)}
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="font-bold text-omi-text-strong">
                              {formatPrice(primaryMarketIndex?.close)}
                            </div>
                            <div className={valueTone(primaryMarketIndex?.change_pct)}>
                              {formatPct(primaryMarketIndex?.change_pct)}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                    </details>
                  </TechnicalCurrentStateEvidence>
                  <NextSessionPlanPanel
                    plan={nextSessionPlan}
                    loadState={nextSessionPlanLoadState}
                  />
                  <OvernightImpactPanel
                    report={displayOvernightImpact}
                    loadState={displayOvernightImpactLoadState}
                  />
                </>
              ) : (
                <>
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

                  <NextSessionPlanPanel
                    plan={nextSessionPlan}
                    loadState={nextSessionPlanLoadState}
                  />

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
                        <div className="mt-0.5 text-omi-text-muted">
                          {marketRegimeLabel(primaryMarketIndex, t)}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-bold text-omi-text-strong">
                          {formatPrice(primaryMarketIndex?.close)}
                        </div>
                        <div className={valueTone(primaryMarketIndex?.change_pct)}>
                          {formatPct(primaryMarketIndex?.change_pct)}
                        </div>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          </>
        )}

        {!isIndexProduct ? (
          <div
            id={STOCK_DETAIL_DATA_PANEL_ID}
            className="border-t border-omi-border-subtle bg-omi-surface"
            data-testid={STOCK_DETAIL_DATA_PANEL_ID}
          >
            <div
              aria-hidden="true"
              className="h-2 border-b border-omi-border-subtle bg-omi-surface-muted shadow-[var(--omi-shadow-surface-inset)]"
            />

            <div
              role="tablist"
              aria-label={t("stockDetail.data")}
              className="flex border-b border-omi-border-subtle"
            >
              {visibleDataPanelTabs.map((tab) => (
                <DataTabButton
                  key={tab.key}
                  tab={{ ...tab, label: t(`stockDetail.tabs.${tab.key}`) }}
                  active={activeDataSurfaceTab === tab.key}
                  onClick={() => selectDataSurfaceTab(tab.key)}
                />
              ))}
            </div>

            {isEtfProduct && activeDataSurfaceTab === "etf" ? (
              <TaiwanETFDataPanel
                stockId={stockId}
                stockName={stockName}
                market={stockMarket}
              />
            ) : (
              <div role="tabpanel" className="px-5 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
                  {t("stockDetail.data")}
                </div>
                <div className="mt-1 flex items-end justify-between gap-4">
                  <div>
                    <div className="text-lg font-bold text-omi-text-strong">
                      {t(`stockDetail.tabs.${activeDataTab}`)} {t("stockDetail.data")}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void refreshDataTab(activeDataTab)}
                    disabled={dataPanelLoading !== null}
                    className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:cursor-wait disabled:border-omi-border-subtle disabled:text-omi-text-subtle"
                  >
                    {dataPanelLoading === activeDataTab
                      ? t("stockDetail.dataPanel.refreshing")
                      : t("stockDetail.dataPanel.refresh")}
                  </button>
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
                    financialContract={financialContract}
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
            )}
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

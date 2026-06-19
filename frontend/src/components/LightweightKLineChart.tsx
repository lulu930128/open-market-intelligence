"use client";

import ChartStaticIndicatorLayer from "@/components/chart/ChartStaticIndicatorLayer";
import ProfessionalChartHeader from "@/components/chart/ProfessionalChartHeader";
import SelectedDrawingMetricsCard from "@/components/chart/SelectedDrawingMetricsCard";
import type { ChartPoint } from "@/types/market";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type LineData,
  type LogicalRange,
  type Time,
  type TickMarkType,
} from "lightweight-charts";
import {
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  ChartDrawing,
  ChartDrawingContext,
  ChartDrawingPoint,
  ChartDrawingVolumeProfileAnalysis,
  DrawingAnchor,
  DrawingCoordinate,
  DrawingDragState,
  LightweightKLineChartProps,
  PlotLineData,
  PointerAnchor,
  PriceCoordinateApi,
  ProjectedCloudPolygon,
  ProjectedDraftDrawing,
  ProjectedDrawing,
  ProjectedGapZone,
  ProjectedRangeVolumeProfileBin,
  ProjectedSupportResistanceLevel,
  ProjectedTechnicalSignal,
  ProjectedVolumeProfileBin,
} from "@/components/chart/LightweightKLineChartDrawing";
import {
  DEFAULT_LIGHTWEIGHT_VISIBLE_BARS,
  applyDrawingDragToDrawings,
  attachDrawingAnalytics,
  buildDrawingDerivedMetrics,
  buildDrawingOmiSummary,
  buildFibonacciLevels,
  buildMeasurementStats,
  chartPointTypicalPrice,
  chartPointVolume,
  chartTime,
  chartTimeParts,
  createDrawingId,
  defaultLightweightParameters,
  detectCandlestickPattern,
  drawingDefaultColor,
  drawingModeBadgeWidth,
  drawingSnapDistancePx,
  drawingTimeFromChartTime,
  drawingToolModeLabel,
  drawingTypeLabel,
  emptyDrawings,
  emptyIndicatorData,
  extendRayToViewport,
  finiteNumber,
  formatChartDate,
  formatChartDateTime,
  formatCompactVolume,
  formatDrawingPrice,
  isProjectedDrawingHit,
  isTwoPointDrawingTool,
  isTwoPointDrawingType,
  lockCoordinateToNearestAngle,
  measurementStatsFromMetrics,
  measurementToneColor,
  pad2,
  preserveEmptyProjection,
  rectangleBounds,
} from "@/components/chart/LightweightKLineChartDrawing";
import {
  buildDefaultVisibleLogicalRange,
  buildSeriesData,
  calculateDmi,
  calculateDonchian,
  calculateEma,
  calculateMacd,
  calculateRsi,
  chartKeyboardBoundaryPaddingBars,
  chartRightPaddingBars,
  formatPrice,
  logicalRange,
  mergeIndicators,
  movingAverage,
} from "@/components/chart/LightweightKLineChartIndicators";
import { getOmiChartColors, type OmiTheme } from "@/lib/themeColors";
export type {
  ChartDrawing,
  ChartDrawingAnchoredVwapAnalysis,
  ChartDrawingContext,
  ChartDrawingDerivedMetrics,
  ChartDrawingFibonacciAnalysis,
  ChartDrawingFibonacciLevel,
  ChartDrawingLineAnalysis,
  ChartDrawingOmiSummary,
  ChartDrawingPoint,
  ChartDrawingTool,
  ChartDrawingVolumeProfileAnalysis,
  ChartDrawingVolumeProfileLevel,
  ChartDrawingZoneAnalysis,
  ChartTimeMode,
} from "@/components/chart/LightweightKLineChartDrawing";

function readOmiTheme(): OmiTheme {
  if (typeof document === "undefined") return "light";

  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export default function LightweightKLineChart({
  chartData,
  indicatorData = emptyIndicatorData,
  label,
  height = 720,
  fillViewport = false,
  timeMode = "date",
  chartStyle = "candlestick",
  showHeader = true,
  showMovingAverages = true,
  indicators,
  indicatorParameters,
  benchmarkData,
  benchmarkLabel,
  volumePanelLabel = "成交量(張)",
  volumeValueKey = "volume",
  drawingTool = "cursor",
  drawings = emptyDrawings,
  selectedDrawingId = null,
  drawingContext,
  onDrawingsChange,
  onDrawingStateChange,
  onSelectedDrawingChange,
}: LightweightKLineChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const overlaySvgRef = useRef<SVGSVGElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<PriceCoordinateApi | null>(null);
  const dragStateRef = useRef<DrawingDragState | null>(null);
  const visibleLogicalRangeRef = useRef<LogicalRange | null>(null);
  const visibleLogicalRangeKeyRef = useRef<string | null>(null);
  const overlayRevisionFrameRef = useRef<number | null>(null);
  const shortcutActiveRef = useRef(false);
  const [overlaySize, setOverlaySize] = useState({ width: 0, height: 0 });
  const [overlayRevision, setOverlayRevision] = useState(0);
  const [draftAnchor, setDraftAnchor] = useState<DrawingAnchor | null>(null);
  const [hoverAnchor, setHoverAnchor] = useState<DrawingAnchor | null>(null);
  const [snapCoordinate, setSnapCoordinate] = useState<DrawingCoordinate | null>(null);
  const [dragPreviewDrawings, setDragPreviewDrawings] = useState<ChartDrawing[] | null>(null);
  const [hoveredDrawingId, setHoveredDrawingId] = useState<string | null>(null);
  const [projectedCloudPolygons, setProjectedCloudPolygons] = useState<ProjectedCloudPolygon[]>([]);
  const [projectedVolumeProfile, setProjectedVolumeProfile] =
    useState<ProjectedVolumeProfileBin[]>([]);
  const [projectedGapZones, setProjectedGapZones] = useState<ProjectedGapZone[]>([]);
  const [projectedSupportResistance, setProjectedSupportResistance] =
    useState<ProjectedSupportResistanceLevel[]>([]);
  const [projectedTechnicalSignals, setProjectedTechnicalSignals] =
    useState<ProjectedTechnicalSignal[]>([]);
  const [projectedDrawings, setProjectedDrawings] = useState<ProjectedDrawing[]>([]);
  const [projectedDraftDrawing, setProjectedDraftDrawing] =
    useState<ProjectedDraftDrawing | null>(null);
  const [omiTheme, setOmiTheme] = useState<OmiTheme>(() => readOmiTheme());
  const omiChartColors = useMemo(() => getOmiChartColors(omiTheme), [omiTheme]);
  const maColors = useMemo(
    () => ({
      maShort: omiChartColors.indicator.maShort,
      maMiddle: omiChartColors.indicator.maMiddle,
      maLong: omiChartColors.indicator.maLong,
    }),
    [omiChartColors]
  );
  const upColor = omiChartColors.marketUp;
  const downColor = omiChartColors.marketDown;
  const selectedDrawingColor = omiChartColors.drawing.selected;
  const hoveredDrawingColor = omiChartColors.drawing.hovered;
  const drawingHandleBorderColor = omiChartColors.drawing.handleBorder;
  const activeDrawings = dragPreviewDrawings ?? drawings;
  const activeIndicators = useMemo(
    () => mergeIndicators(indicators, showMovingAverages),
    [indicators, showMovingAverages]
  );
  const params = useMemo(
    () => ({
      ...defaultLightweightParameters,
      ...(indicatorParameters ?? {}),
    }),
    [indicatorParameters]
  );
  const seriesData = useMemo(
    () => buildSeriesData(chartData, indicatorData, volumeValueKey, timeMode, params, benchmarkData),
    [benchmarkData, chartData, indicatorData, params, timeMode, volumeValueKey]
  );
  const chartSeriesKey = useMemo(() => {
    const firstPoint = chartData[0];

    return [
      timeMode,
      drawingContext?.market ?? "",
      drawingContext?.symbol ?? label,
      drawingContext?.timeframe ?? label,
      volumeValueKey,
      firstPoint?.time ?? "empty",
    ].join(":");
  }, [
    chartData,
    drawingContext?.market,
    drawingContext?.symbol,
    drawingContext?.timeframe,
    label,
    timeMode,
    volumeValueKey,
  ]);
  const chartDataTimeIndex = useMemo(() => {
    const indexByTime = new Map<string, number>();

    chartData.forEach((point, index) => {
      indexByTime.set(point.time, index);
      indexByTime.set(drawingTimeFromChartTime(chartTime(point.time, timeMode), timeMode), index);
    });

    return indexByTime;
  }, [chartData, timeMode]);
  const activeDrawingContext = useMemo<ChartDrawingContext>(
    () => ({
      ...drawingContext,
      label,
      timeMode,
    }),
    [drawingContext, label, timeMode]
  );
  const attachActiveDrawingAnalytics = useCallback(
    (drawing: ChartDrawing) =>
      attachDrawingAnalytics(drawing, chartDataTimeIndex, activeDrawingContext, chartData),
    [activeDrawingContext, chartData, chartDataTimeIndex]
  );
  const attachActiveDrawingsAnalytics = useCallback(
    (nextDrawings: ChartDrawing[]) => nextDrawings.map(attachActiveDrawingAnalytics),
    [attachActiveDrawingAnalytics]
  );

  useEffect(() => {
    if (typeof document === "undefined") return;

    const root = document.documentElement;
    const updateTheme = () => {
      setOmiTheme(readOmiTheme());
    };
    const observer = new MutationObserver(updateTheme);

    updateTheme();
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    window.addEventListener("storage", updateTheme);

    return () => {
      observer.disconnect();
      window.removeEventListener("storage", updateTheme);
    };
  }, []);

  const drawingPointToCoordinate = useCallback((point: ChartDrawingPoint): DrawingCoordinate | null => {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;

    if (!chart || !series) return null;

    const x = chart.timeScale().timeToCoordinate(chartTime(point.time, timeMode));
    const y = series.priceToCoordinate(point.price);

    if (x === null || y === null) return null;

    return { x, y };
  }, [timeMode]);

  const linePointToCoordinate = useCallback((point: LineData<Time>): DrawingCoordinate | null => {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;

    if (!chart || !series) return null;

    const x = chart.timeScale().timeToCoordinate(point.time);
    const y = series.priceToCoordinate(point.value);

    if (x === null || y === null) return null;

    return { x, y };
  }, []);

  const buildAnchoredVwapProjection = useCallback((anchor: ChartDrawingPoint): DrawingCoordinate[] => {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;
    const anchorIndex = chartDataTimeIndex.get(anchor.time);

    if (!chart || !series || anchorIndex === undefined) return [];

    let cumulativeVolume = 0;
    let cumulativeTypicalValue = 0;
    const points: DrawingCoordinate[] = [];

    for (let index = anchorIndex; index < chartData.length; index += 1) {
      const point = chartData[index];
      const typicalPrice = chartPointTypicalPrice(point);
      const volume = chartPointVolume(point);

      if (!finiteNumber(typicalPrice) || !finiteNumber(volume) || volume <= 0) continue;

      cumulativeVolume += volume;
      cumulativeTypicalValue += typicalPrice * volume;

      const vwap = cumulativeTypicalValue / cumulativeVolume;
      const x = chart.timeScale().timeToCoordinate(chartTime(point.time, timeMode));
      const y = series.priceToCoordinate(vwap);

      if (x === null || y === null) continue;

      points.push({ x, y });
    }

    return points;
  }, [chartData, chartDataTimeIndex, timeMode]);

  const buildVolumeProfileRangeProjection = useCallback((
    analysis: ChartDrawingVolumeProfileAnalysis | null | undefined,
    first: DrawingCoordinate,
    second: DrawingCoordinate
  ): ProjectedRangeVolumeProfileBin[] => {
    const series = mainSeriesRef.current;

    if (!series || !analysis || analysis.levels.length === 0) return [];

    const box = rectangleBounds([first, second]);
    const maxVolume = Math.max(...analysis.levels.map((level) => level.totalVolume), 0);

    if (!Number.isFinite(maxVolume) || maxVolume <= 0) return [];

    const profileWidth = Math.max(44, Math.min(Math.max(box.width - 16, 44), 180));
    const profileX = box.x + 8;

    return analysis.levels.flatMap((level): ProjectedRangeVolumeProfileBin[] => {
      if (level.totalVolume <= 0) return [];

      const topY = series.priceToCoordinate(level.priceMax);
      const bottomY = series.priceToCoordinate(level.priceMin);

      if (topY === null || bottomY === null) return [];

      const y = Math.min(topY, bottomY);
      const height = Math.max(1, Math.abs(bottomY - topY) - 0.5);
      const width = Math.max(1, (level.totalVolume / maxVolume) * profileWidth);
      const sellWidth = level.totalVolume > 0 ? width * (level.sellVolume / level.totalVolume) : 0;
      const buyWidth = Math.max(0, width - sellWidth);

      return [
        {
          id: `vp-range-${level.index}`,
          x: profileX,
          y,
          height,
          width,
          buyWidth,
          sellWidth,
          priceLabel: level.label,
          volumeLabel: level.volumeLabel,
          poc: level.isPoc,
          valueArea: level.inValueArea,
        },
      ];
    });
  }, []);

  const visibleChartPointEntries = useCallback(() => {
    const chart = chartRef.current;

    if (!chart || chartData.length === 0) return [];

    const range = chart.timeScale().getVisibleLogicalRange() ?? visibleLogicalRangeRef.current;
    const fromIndex = Math.max(
      0,
      Math.floor(range?.from ?? Math.max(0, chartData.length - DEFAULT_LIGHTWEIGHT_VISIBLE_BARS))
    );
    const toIndex = Math.min(
      chartData.length - 1,
      Math.ceil(range?.to ?? chartData.length - 1)
    );
    const entries: Array<{ point: ChartPoint; index: number; x: number; time: Time }> = [];

    for (let index = fromIndex; index <= toIndex; index += 1) {
      const point = chartData[index];
      const time = chartTime(point.time, timeMode);
      const x = chart.timeScale().timeToCoordinate(time);

      if (x === null) continue;

      entries.push({ point, index, x, time });
    }

    return entries;
  }, [chartData, timeMode]);

  const buildVolumeProfileProjection = useCallback((): ProjectedVolumeProfileBin[] => {
    const series = mainSeriesRef.current;

    if (!series || overlaySize.width <= 0 || overlaySize.height <= 0) return [];

    const entries = visibleChartPointEntries().filter(({ point }) => {
      const volumeValue = volumeValueKey === "trade_value" ? point.trade_value : point.volume;

      return (
        finiteNumber(point.open) &&
        finiteNumber(point.high) &&
        finiteNumber(point.low) &&
        finiteNumber(point.close) &&
        finiteNumber(volumeValue) &&
        volumeValue > 0
      );
    });

    if (entries.length < 2) return [];

    let minPrice = Number.POSITIVE_INFINITY;
    let maxPrice = Number.NEGATIVE_INFINITY;

    entries.forEach(({ point }) => {
      if (finiteNumber(point.low)) minPrice = Math.min(minPrice, point.low);
      if (finiteNumber(point.high)) maxPrice = Math.max(maxPrice, point.high);
    });

    const priceRange = maxPrice - minPrice;

    if (!Number.isFinite(priceRange) || priceRange <= 0) return [];

    const rowCount = Math.max(8, Math.min(80, Math.round(params.volumeProfileRows)));
    const binSize = priceRange / rowCount;
    const bins = Array.from({ length: rowCount }, (_, index) => ({
      index,
      buy: 0,
      sell: 0,
      total: 0,
    }));

    entries.forEach(({ point }) => {
      if (
        !finiteNumber(point.open) ||
        !finiteNumber(point.high) ||
        !finiteNumber(point.low) ||
        !finiteNumber(point.close)
      ) {
        return;
      }

      const volumeValue = volumeValueKey === "trade_value" ? point.trade_value : point.volume;

      if (!finiteNumber(volumeValue) || volumeValue <= 0) return;

      const startBin = Math.max(
        0,
        Math.min(rowCount - 1, Math.floor((point.low - minPrice) / binSize))
      );
      const endBin = Math.max(
        startBin,
        Math.min(rowCount - 1, Math.floor((point.high - minPrice) / binSize))
      );
      const share = volumeValue / (endBin - startBin + 1);
      const side = point.close >= point.open ? "buy" : "sell";

      for (let binIndex = startBin; binIndex <= endBin; binIndex += 1) {
        bins[binIndex][side] += share;
        bins[binIndex].total += share;
      }
    });

    const maxTotal = Math.max(...bins.map((bin) => bin.total));

    if (!Number.isFinite(maxTotal) || maxTotal <= 0) return [];

    const maxWidth = Math.max(96, Math.min(220, overlaySize.width * 0.16));
    const right = Math.max(120, overlaySize.width - 74);

    return bins.flatMap((bin): ProjectedVolumeProfileBin[] => {
      if (bin.total <= 0) return [];

      const priceMin = minPrice + bin.index * binSize;
      const priceMax = priceMin + binSize;
      const topY = series.priceToCoordinate(priceMax);
      const bottomY = series.priceToCoordinate(priceMin);

      if (topY === null || bottomY === null) return [];

      const y = Math.min(topY, bottomY);
      const height = Math.max(1, Math.abs(bottomY - topY) - 0.5);
      const width = Math.max(1, (bin.total / maxTotal) * maxWidth);
      const sellWidth = width * (bin.sell / bin.total);
      const buyWidth = width - sellWidth;
      const centerPrice = (priceMin + priceMax) / 2;

      return [
        {
          id: `vpvr-${bin.index}`,
          x: right - width,
          y,
          height,
          width,
          buyWidth,
          sellWidth,
          priceLabel: formatDrawingPrice(centerPrice),
          volumeLabel: formatCompactVolume(bin.total),
          poc: bin.total === maxTotal,
        },
      ];
    });
  }, [
    overlaySize.height,
    overlaySize.width,
    params.volumeProfileRows,
    visibleChartPointEntries,
    volumeValueKey,
  ]);

  const buildGapZoneProjection = useCallback((): ProjectedGapZone[] => {
    const series = mainSeriesRef.current;

    if (!series || overlaySize.width <= 0 || overlaySize.height <= 0) return [];

    const entries = visibleChartPointEntries();
    const zones: ProjectedGapZone[] = [];
    const rightEdge = Math.max(140, overlaySize.width - 74);

    entries.forEach(({ point, index, x }) => {
      const previous = chartData[index - 1];

      if (
        !previous ||
        !finiteNumber(point.open) ||
        !finiteNumber(previous.high) ||
        !finiteNumber(previous.low) ||
        !finiteNumber(previous.close) ||
        previous.close === 0
      ) {
        return;
      }

      const gapUpPct = ((point.open - previous.high) / previous.close) * 100;
      const gapDownPct = ((previous.low - point.open) / previous.close) * 100;
      const isGapUp = gapUpPct >= params.gapMinPct;
      const isGapDown = gapDownPct >= params.gapMinPct;

      if (!isGapUp && !isGapDown) return;

      const topPrice = isGapUp ? point.open : previous.low;
      const bottomPrice = isGapUp ? previous.high : point.open;
      const topY = series.priceToCoordinate(topPrice);
      const bottomY = series.priceToCoordinate(bottomPrice);

      if (topY === null || bottomY === null) return;

      const y = Math.min(topY, bottomY);
      const height = Math.max(3, Math.abs(bottomY - topY));
      const width = Math.max(12, rightEdge - x);
      const label = `${isGapUp ? "Gap +" : "Gap -"}${Math.abs(isGapUp ? gapUpPct : gapDownPct).toFixed(2)}%`;

      zones.push({
        id: `gap-${point.time}-${isGapUp ? "up" : "down"}`,
        x,
        y,
        width,
        height,
        tone: isGapUp ? "up" : "down",
        label,
      });
    });

    return zones.slice(-12);
  }, [chartData, overlaySize.height, overlaySize.width, params.gapMinPct, visibleChartPointEntries]);

  const buildSupportResistanceProjection = useCallback((): ProjectedSupportResistanceLevel[] => {
    const series = mainSeriesRef.current;
    const entries = visibleChartPointEntries();

    if (!series || entries.length < 8 || overlaySize.height <= 0 || overlaySize.width <= 0) {
      return [];
    }

    const visibleHighs = entries.map(({ point }) => point.high).filter(finiteNumber);
    const visibleLows = entries.map(({ point }) => point.low).filter(finiteNumber);
    const latestClose = [...entries]
      .reverse()
      .map(({ point }) => point.close)
      .find(finiteNumber);

    if (visibleHighs.length === 0 || visibleLows.length === 0 || !finiteNumber(latestClose)) {
      return [];
    }

    const minPrice = Math.min(...visibleLows);
    const maxPrice = Math.max(...visibleHighs);
    const tolerance = Math.max((maxPrice - minPrice) * 0.006, Math.abs(latestClose) * 0.0015);
    const pivotRadius = Math.max(2, Math.min(10, Math.round(params.supportResistanceLookback / 5)));
    const firstIndex = entries[0].index;
    const lastIndex = entries[entries.length - 1].index;
    const candidates: Array<{ price: number; tone: "support" | "resistance" }> = [];

    for (let index = Math.max(pivotRadius, firstIndex); index <= Math.min(chartData.length - 1 - pivotRadius, lastIndex); index += 1) {
      const point = chartData[index];

      if (!finiteNumber(point.high) || !finiteNumber(point.low)) continue;

      let isPivotHigh = true;
      let isPivotLow = true;

      for (let offset = -pivotRadius; offset <= pivotRadius; offset += 1) {
        if (offset === 0) continue;

        const neighbor = chartData[index + offset];

        if (!neighbor) continue;
        if (finiteNumber(neighbor.high) && neighbor.high > point.high) isPivotHigh = false;
        if (finiteNumber(neighbor.low) && neighbor.low < point.low) isPivotLow = false;
      }

      if (isPivotHigh) candidates.push({ price: point.high, tone: "resistance" });
      if (isPivotLow) candidates.push({ price: point.low, tone: "support" });
    }

    const clusters: Array<{ price: number; tone: "support" | "resistance"; strength: number }> = [];

    candidates.forEach((candidate) => {
      const cluster = clusters.find(
        (current) =>
          current.tone === candidate.tone &&
          Math.abs(current.price - candidate.price) <= tolerance
      );

      if (cluster) {
        cluster.price =
          (cluster.price * cluster.strength + candidate.price) / (cluster.strength + 1);
        cluster.strength += 1;
        return;
      }

      clusters.push({ ...candidate, strength: 1 });
    });

    return clusters
      .sort((left, right) => {
        if (right.strength !== left.strength) return right.strength - left.strength;

        return Math.abs(left.price - latestClose) - Math.abs(right.price - latestClose);
      })
      .slice(0, 8)
      .flatMap((cluster): ProjectedSupportResistanceLevel[] => {
        const y = series.priceToCoordinate(cluster.price);

        if (y === null || y < -24 || y > overlaySize.height + 24) return [];

        return [
          {
            id: `sr-${cluster.tone}-${cluster.price.toFixed(4)}`,
            y,
            priceLabel: formatDrawingPrice(cluster.price),
            tone: cluster.tone,
            strength: cluster.strength,
            opacity: Math.min(0.82, 0.32 + cluster.strength * 0.12),
          },
        ];
      });
  }, [
    chartData,
    overlaySize.height,
    overlaySize.width,
    params.supportResistanceLookback,
    visibleChartPointEntries,
  ]);

  const buildTechnicalSignalProjection = useCallback((): ProjectedTechnicalSignal[] => {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;

    if (!chart || !series || overlaySize.width <= 0 || overlaySize.height <= 0) return [];

    const activeChart = chart;
    const activeSeries = series;
    const entries = visibleChartPointEntries();
    const signals: ProjectedTechnicalSignal[] = [];

    function projectSignal(
      id: string,
      point: ChartPoint,
      price: number,
      label: string,
      tone: ProjectedTechnicalSignal["tone"],
      line?: [DrawingCoordinate, DrawingCoordinate]
    ) {
      const x = activeChart.timeScale().timeToCoordinate(chartTime(point.time, timeMode));
      const anchorY = activeSeries.priceToCoordinate(price);

      if (x === null || anchorY === null) return;

      const yOffset = tone === "bearish" ? -16 : tone === "bullish" ? 18 : -18;
      const y = Math.max(18, Math.min(anchorY + yOffset, overlaySize.height - 16));

      signals.push({
        id,
        x,
        y,
        anchorY,
        label,
        tone,
        timeLabel: point.time.slice(0, 16).replace("T", " "),
        priceLabel: formatDrawingPrice(price),
        line,
      });
    }

    if (activeIndicators.signals) {
      const closes = chartData.map((point) => point.close);
      const emaFast = calculateEma(closes, params.emaFast);
      const emaSlow = calculateEma(closes, params.emaSlow);
      const macdValues = calculateMacd(
        closes,
        params.macdFast,
        params.macdSlow,
        params.macdSignal
      );
      const donchian = calculateDonchian(chartData, params.donchianPeriod);
      const dmi = calculateDmi(chartData, params.adxPeriod);
      const volumes = chartData.map((point) =>
        volumeValueKey === "trade_value" ? point.trade_value : point.volume
      );

      entries.forEach(({ point, index }) => {
        if (index < 1) return;

        const previous = chartData[index - 1];
        const bullishPrice = point.low ?? point.close;
        const bearishPrice = point.high ?? point.close;
        const previousDonchianUpper = donchian[index - 1]?.upper;
        const previousDonchianLower = donchian[index - 1]?.lower;
        const previousAdx = dmi[index - 1]?.adx;
        const currentAdx = dmi[index]?.adx;
        const previousEmaFast = emaFast[index - 1];
        const previousEmaSlow = emaSlow[index - 1];
        const currentEmaFast = emaFast[index];
        const currentEmaSlow = emaSlow[index];
        const previousMacd = macdValues.macd[index - 1];
        const previousMacdSignal = macdValues.signal[index - 1];
        const currentMacd = macdValues.macd[index];
        const currentMacdSignal = macdValues.signal[index];

        if (
          finiteNumber(previousEmaFast) &&
          finiteNumber(previousEmaSlow) &&
          finiteNumber(currentEmaFast) &&
          finiteNumber(currentEmaSlow) &&
          finiteNumber(bullishPrice) &&
          previousEmaFast <= previousEmaSlow &&
          currentEmaFast > currentEmaSlow
        ) {
          projectSignal(`signal-${point.time}-ema-up`, point, bullishPrice, "EMA金叉", "bullish");
        }

        if (
          finiteNumber(previousEmaFast) &&
          finiteNumber(previousEmaSlow) &&
          finiteNumber(currentEmaFast) &&
          finiteNumber(currentEmaSlow) &&
          finiteNumber(bearishPrice) &&
          previousEmaFast >= previousEmaSlow &&
          currentEmaFast < currentEmaSlow
        ) {
          projectSignal(
            `signal-${point.time}-ema-down`,
            point,
            bearishPrice,
            "EMA死叉",
            "bearish"
          );
        }

        if (
          finiteNumber(previousMacd) &&
          finiteNumber(previousMacdSignal) &&
          finiteNumber(currentMacd) &&
          finiteNumber(currentMacdSignal) &&
          finiteNumber(bullishPrice) &&
          previousMacd <= previousMacdSignal &&
          currentMacd > currentMacdSignal
        ) {
          projectSignal(
            `signal-${point.time}-macd-up`,
            point,
            bullishPrice,
            "MACD翻紅",
            "bullish"
          );
        }

        if (
          finiteNumber(previousMacd) &&
          finiteNumber(previousMacdSignal) &&
          finiteNumber(currentMacd) &&
          finiteNumber(currentMacdSignal) &&
          finiteNumber(bearishPrice) &&
          previousMacd >= previousMacdSignal &&
          currentMacd < currentMacdSignal
        ) {
          projectSignal(
            `signal-${point.time}-macd-down`,
            point,
            bearishPrice,
            "MACD翻黑",
            "bearish"
          );
        }

        if (
          finiteNumber(point.close) &&
          finiteNumber(previousDonchianUpper) &&
          finiteNumber(bullishPrice) &&
          point.close > previousDonchianUpper
        ) {
          projectSignal(
            `signal-${point.time}-donch-up`,
            point,
            bullishPrice,
            "通道突破",
            "bullish"
          );
        }

        if (
          finiteNumber(point.close) &&
          finiteNumber(previousDonchianLower) &&
          finiteNumber(bearishPrice) &&
          point.close < previousDonchianLower
        ) {
          projectSignal(
            `signal-${point.time}-donch-down`,
            point,
            bearishPrice,
            "通道跌破",
            "bearish"
          );
        }

        const volumeMa = movingAverage(volumes, index, params.volumeMa);
        const volume = volumes[index];
        const previousClose = previous?.close;
        const changePct =
          finiteNumber(point.close) && finiteNumber(previousClose) && previousClose !== 0
            ? ((point.close - previousClose) / previousClose) * 100
            : null;

        if (
          finiteNumber(volume) &&
          finiteNumber(volumeMa) &&
          finiteNumber(changePct) &&
          finiteNumber(bullishPrice) &&
          volumeMa > 0 &&
          volume / volumeMa >= 1.8 &&
          changePct > 0
        ) {
          projectSignal(
            `signal-${point.time}-volume-up`,
            point,
            bullishPrice,
            "放量上攻",
            "bullish"
          );
        }

        if (
          finiteNumber(previousAdx) &&
          finiteNumber(currentAdx) &&
          finiteNumber(point.close) &&
          previousAdx <= 25 &&
          currentAdx > 25
        ) {
          projectSignal(
            `signal-${point.time}-adx-trend`,
            point,
            point.close,
            "趨勢成形",
            "neutral"
          );
        }
      });
    }

    if (activeIndicators.candlestickPatterns) {
      entries.forEach(({ point, index }) => {
        const pattern = detectCandlestickPattern(point, chartData[index - 1]);

        if (!pattern) return;

        projectSignal(
          `pattern-${point.time}-${pattern.label}`,
          point,
          pattern.price,
          pattern.label,
          pattern.tone
        );
      });
    }

    if (activeIndicators.divergence && chartData.length >= 18) {
      const closes = chartData.map((point) => point.close);
      const rsiValues = calculateRsi(closes, params.rsiPeriod);
      const macdValues = calculateMacd(
        closes,
        params.macdFast,
        params.macdSlow,
        params.macdSignal
      );
      const pivotRadius = 3;
      const firstIndex = entries[0]?.index ?? 0;
      const lastIndex = entries[entries.length - 1]?.index ?? chartData.length - 1;
      const lowPivots: number[] = [];
      const highPivots: number[] = [];

      for (
        let index = pivotRadius;
        index <= chartData.length - 1 - pivotRadius;
        index += 1
      ) {
        const point = chartData[index];

        if (!finiteNumber(point.low) || !finiteNumber(point.high)) continue;

        let isLowPivot = true;
        let isHighPivot = true;

        for (let offset = -pivotRadius; offset <= pivotRadius; offset += 1) {
          if (offset === 0) continue;

          const neighbor = chartData[index + offset];

          if (!neighbor) continue;
          if (finiteNumber(neighbor.low) && neighbor.low < point.low) isLowPivot = false;
          if (finiteNumber(neighbor.high) && neighbor.high > point.high) isHighPivot = false;
        }

        if (isLowPivot) lowPivots.push(index);
        if (isHighPivot) highPivots.push(index);
      }

      function previousPivot(pivots: number[], currentIndex: number) {
        return [...pivots].reverse().find(
          (pivotIndex) => pivotIndex < currentIndex && currentIndex - pivotIndex <= 90
        );
      }

      function pivotCoordinate(index: number, price: number): DrawingCoordinate | null {
        const point = chartData[index];
        const x = activeChart.timeScale().timeToCoordinate(chartTime(point.time, timeMode));
        const y = activeSeries.priceToCoordinate(price);

        if (x === null || y === null) return null;

        return { x, y };
      }

      lowPivots
        .filter((index) => index >= firstIndex && index <= lastIndex)
        .forEach((index) => {
          const previousIndex = previousPivot(lowPivots, index);
          const point = chartData[index];
          const previousPoint = previousIndex === undefined ? null : chartData[previousIndex];

          if (
            previousIndex === undefined ||
            !previousPoint ||
            !finiteNumber(point.low) ||
            !finiteNumber(previousPoint.low) ||
            point.low >= previousPoint.low
          ) {
            return;
          }

          const rsiBullish =
            finiteNumber(rsiValues[index]) &&
            finiteNumber(rsiValues[previousIndex]) &&
            rsiValues[index] - rsiValues[previousIndex] >= 3;
          const macdBullish =
            finiteNumber(macdValues.histogram[index]) &&
            finiteNumber(macdValues.histogram[previousIndex]) &&
            macdValues.histogram[index] > macdValues.histogram[previousIndex];

          if (!rsiBullish && !macdBullish) return;

          const start = pivotCoordinate(previousIndex, previousPoint.low);
          const end = pivotCoordinate(index, point.low);

          projectSignal(
            `divergence-bull-${point.time}`,
            point,
            point.low,
            rsiBullish && macdBullish ? "RSI/MACD底背" : rsiBullish ? "RSI底背" : "MACD底背",
            "bullish",
            start && end ? [start, end] : undefined
          );
        });

      highPivots
        .filter((index) => index >= firstIndex && index <= lastIndex)
        .forEach((index) => {
          const previousIndex = previousPivot(highPivots, index);
          const point = chartData[index];
          const previousPoint = previousIndex === undefined ? null : chartData[previousIndex];

          if (
            previousIndex === undefined ||
            !previousPoint ||
            !finiteNumber(point.high) ||
            !finiteNumber(previousPoint.high) ||
            point.high <= previousPoint.high
          ) {
            return;
          }

          const rsiBearish =
            finiteNumber(rsiValues[index]) &&
            finiteNumber(rsiValues[previousIndex]) &&
            rsiValues[previousIndex] - rsiValues[index] >= 3;
          const macdBearish =
            finiteNumber(macdValues.histogram[index]) &&
            finiteNumber(macdValues.histogram[previousIndex]) &&
            macdValues.histogram[index] < macdValues.histogram[previousIndex];

          if (!rsiBearish && !macdBearish) return;

          const start = pivotCoordinate(previousIndex, previousPoint.high);
          const end = pivotCoordinate(index, point.high);

          projectSignal(
            `divergence-bear-${point.time}`,
            point,
            point.high,
            rsiBearish && macdBearish ? "RSI/MACD頂背" : rsiBearish ? "RSI頂背" : "MACD頂背",
            "bearish",
            start && end ? [start, end] : undefined
          );
        });
    }

    return signals
      .sort((left, right) => left.x - right.x)
      .slice(-18);
  }, [
    activeIndicators.candlestickPatterns,
    activeIndicators.divergence,
    activeIndicators.signals,
    chartData,
    overlaySize.height,
    overlaySize.width,
    params.adxPeriod,
    params.donchianPeriod,
    params.emaFast,
    params.emaSlow,
    params.macdFast,
    params.macdSignal,
    params.macdSlow,
    params.rsiPeriod,
    params.volumeMa,
    timeMode,
    visibleChartPointEntries,
    volumeValueKey,
  ]);

  const drawingTimeFromCoordinateX = useCallback((coordinateX: number) => {
    const chart = chartRef.current;

    if (!chart) return null;

    const directTime = chart.timeScale().coordinateToTime(coordinateX);

    if (directTime !== null) {
      return drawingTimeFromChartTime(directTime, timeMode);
    }

    if (chartData.length === 0) return null;

    const logical = chart.timeScale().coordinateToLogical(coordinateX);

    if (logical === null || !Number.isFinite(Number(logical))) {
      return chartData[chartData.length - 1]?.time ?? null;
    }

    const nearestIndex = Math.min(
      Math.max(Math.round(Number(logical)), 0),
      chartData.length - 1
    );

    return chartData[nearestIndex]?.time ?? chartData[chartData.length - 1]?.time ?? null;
  }, [chartData, timeMode]);

  const coordinateToDrawingPoint = useCallback((coordinate: DrawingCoordinate): ChartDrawingPoint | null => {
    const series = mainSeriesRef.current;

    if (!series) return null;

    const time = drawingTimeFromCoordinateX(coordinate.x);
    const price = series.coordinateToPrice(coordinate.y);

    if (time === null || price === null || !Number.isFinite(price)) return null;

    return { time, price };
  }, [drawingTimeFromCoordinateX]);

  function pointerCoordinateFromEvent(event: { clientX: number; clientY: number }): DrawingCoordinate | null {
    const target = overlaySvgRef.current;

    if (!target) return null;

    const rect = target.getBoundingClientRect();

    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  const rememberVisibleLogicalRange = useCallback(() => {
    const chart = chartRef.current;
    const range = chart?.timeScale().getVisibleLogicalRange();

    if (!range) return null;

    const visibleRange = { from: range.from, to: range.to };
    visibleLogicalRangeRef.current = visibleRange;
    visibleLogicalRangeKeyRef.current = chartSeriesKey;

    return visibleRange;
  }, [chartSeriesKey]);

  const restoreVisibleLogicalRange = useCallback((range: LogicalRange | null | undefined) => {
    if (!range) return;

    window.requestAnimationFrame(() => {
      const chart = chartRef.current;

      if (!chart) return;

      chart.timeScale().setVisibleLogicalRange(range);
      visibleLogicalRangeRef.current = { from: range.from, to: range.to };
      visibleLogicalRangeKeyRef.current = chartSeriesKey;
    });
  }, [chartSeriesKey]);

  const scheduleOverlayRevision = useCallback(() => {
    if (overlayRevisionFrameRef.current !== null) return;

    overlayRevisionFrameRef.current = window.requestAnimationFrame(() => {
      overlayRevisionFrameRef.current = null;
      setOverlayRevision((value) => value + 1);
    });
  }, []);

  const applyVisibleLogicalRange = useCallback((range: LogicalRange) => {
    const chart = chartRef.current;

    if (!chart) return;

    chart.timeScale().setVisibleLogicalRange(range);
    visibleLogicalRangeRef.current = { from: range.from, to: range.to };
    visibleLogicalRangeKeyRef.current = chartSeriesKey;
    scheduleOverlayRevision();
  }, [chartSeriesKey, scheduleOverlayRevision]);

  const resetVisibleLogicalRangeToLatest = useCallback(() => {
    const chart = chartRef.current;

    if (!chart || seriesData.candles.length === 0) return;

    const defaultRange = buildDefaultVisibleLogicalRange(seriesData.candles.length, timeMode);

    if (defaultRange) {
      applyVisibleLogicalRange(defaultRange);
      return;
    }

    chart.timeScale().fitContent();
    const range = chart.timeScale().getVisibleLogicalRange();

    if (range) {
      visibleLogicalRangeRef.current = { from: range.from, to: range.to };
      visibleLogicalRangeKeyRef.current = chartSeriesKey;
    }

    scheduleOverlayRevision();
  }, [
    applyVisibleLogicalRange,
    chartSeriesKey,
    scheduleOverlayRevision,
    seriesData.candles.length,
    timeMode,
  ]);

  const updateVisibleLogicalRange = useCallback((
    transform: (range: { from: number; to: number }) => { from: number; to: number }
  ) => {
    const chart = chartRef.current;
    const currentRange =
      chart?.timeScale().getVisibleLogicalRange() ??
      visibleLogicalRangeRef.current ??
      buildDefaultVisibleLogicalRange(seriesData.candles.length, timeMode);

    if (!currentRange || seriesData.candles.length === 0) return;

    const currentNumericRange = {
      from: Number(currentRange.from),
      to: Number(currentRange.to),
    };
    const lastIndex = seriesData.candles.length - 1;
    const boundaryPadding = chartKeyboardBoundaryPaddingBars(timeMode);
    const minFrom = -Math.min(boundaryPadding, Math.max(seriesData.candles.length, 1));
    const maxTo = lastIndex + boundaryPadding;
    const nextRange = transform(currentNumericRange);
    const width = Math.max(4, nextRange.to - nextRange.from);
    let from = nextRange.from;
    let to = nextRange.to;

    if (to > maxTo) {
      to = maxTo;
      from = to - width;
    }

    if (from < minFrom) {
      from = minFrom;
      to = from + width;
    }

    applyVisibleLogicalRange(logicalRange(from, to));
  }, [applyVisibleLogicalRange, seriesData.candles.length, timeMode]);

  function snapAnchorToHighLow(anchor: DrawingAnchor, x: number, y: number): PointerAnchor {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;

    if (!chart || !series || chartData.length === 0) {
      return { ...anchor, x, y, snapped: false };
    }

    let best:
      | {
          anchor: PointerAnchor;
          score: number;
        }
      | null = null;

    for (const point of chartData) {
      const pointX = chart.timeScale().timeToCoordinate(chartTime(point.time, timeMode));

      if (pointX === null) continue;

      const candidates = [
        { price: point.high, time: point.time },
        { price: point.low, time: point.time },
      ];

      for (const candidate of candidates) {
        if (!finiteNumber(candidate.price)) continue;

        const pointY = series.priceToCoordinate(candidate.price);

        if (pointY === null) continue;

        const dx = Math.abs(pointX - x);
        const dy = Math.abs(pointY - y);

        if (dx > drawingSnapDistancePx || dy > drawingSnapDistancePx) continue;

        const score = dx + dy;

        if (!best || score < best.score) {
          const candidateTime = drawingTimeFromChartTime(
            chartTime(candidate.time, timeMode),
            timeMode
          );

          best = {
            score,
            anchor: {
              time: candidateTime,
              price: candidate.price,
              x: pointX,
              y: pointY,
              snapped: true,
            },
          };
        }
      }
    }

    return best?.anchor ?? { ...anchor, x, y, snapped: false };
  }

  function anchorFromPointer<T extends SVGElement>(
    event: ReactPointerEvent<T>,
    options: { snap?: boolean } = {}
  ): PointerAnchor | null {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;
    const coordinate = pointerCoordinateFromEvent(event);

    if (!chart || !series || !coordinate) return null;

    const price = series.coordinateToPrice(coordinate.y);
    const time = drawingTimeFromCoordinateX(coordinate.x);

    if (time === null || price === null || !Number.isFinite(price)) return null;

    const anchor = {
      time,
      price,
    };

    if (options.snap === false) {
      return {
        ...anchor,
        ...coordinate,
        snapped: false,
      };
    }

    return snapAnchorToHighLow(anchor, coordinate.x, coordinate.y);
  }

  function constrainAnchorToAngle(
    anchor: PointerAnchor,
    originCoordinate: DrawingCoordinate | null | undefined
  ): PointerAnchor {
    if (!originCoordinate) return anchor;

    const lockedCoordinate = lockCoordinateToNearestAngle(originCoordinate, anchor);
    const lockedPoint = coordinateToDrawingPoint(lockedCoordinate);

    if (!lockedPoint) return anchor;

    return {
      ...lockedPoint,
      x: lockedCoordinate.x,
      y: lockedCoordinate.y,
      snapped: false,
    };
  }

  const commitDrawingState = useCallback((nextDrawings: ChartDrawing[], nextSelectedDrawingId: string | null) => {
    if (onDrawingStateChange) {
      onDrawingStateChange(nextDrawings, nextSelectedDrawingId);
      return;
    }

    onDrawingsChange?.(nextDrawings);
    onSelectedDrawingChange?.(nextSelectedDrawingId);
  }, [onDrawingStateChange, onDrawingsChange, onSelectedDrawingChange]);

  function commitDrawing(type: ChartDrawing["type"], points: ChartDrawingPoint[]) {
    if ((!onDrawingStateChange && !onDrawingsChange) || points.length === 0) return;

    const visibleRange = rememberVisibleLogicalRange();
    const nextDrawing = attachActiveDrawingAnalytics({
      id: createDrawingId(),
      type,
      points,
      color: drawingDefaultColor(type),
      createdAt: new Date().toISOString(),
    });

    commitDrawingState([...drawings, nextDrawing], nextDrawing.id);
    restoreVisibleLogicalRange(visibleRange);
  }

  const deleteDrawing = useCallback((drawingId: string) => {
    const visibleRange = rememberVisibleLogicalRange();
    const nextSelectedDrawingId = selectedDrawingId === drawingId ? null : selectedDrawingId;

    commitDrawingState(
      drawings.filter((drawing) => drawing.id !== drawingId),
      nextSelectedDrawingId
    );

    restoreVisibleLogicalRange(visibleRange);
  }, [
    commitDrawingState,
    drawings,
    rememberVisibleLogicalRange,
    restoreVisibleLogicalRange,
    selectedDrawingId,
  ]);

  function handleDrawingContextMenu(event: ReactMouseEvent<SVGElement>, drawingId: string) {
    event.preventDefault();
    event.stopPropagation();
    deleteDrawing(drawingId);
  }

  function applyActiveDrawingDrag(
    sourceDrawings: ChartDrawing[],
    dragState: DrawingDragState,
    anchor: DrawingAnchor | null,
    pointerCoordinate: DrawingCoordinate | null
  ) {
    if (dragState.mode !== "line") {
      return anchor ? applyDrawingDragToDrawings(sourceDrawings, dragState, anchor) : sourceDrawings;
    }

    if (
      !dragState.startCoordinate ||
      !pointerCoordinate ||
      !dragState.originCoordinates ||
      dragState.originCoordinates.length < 2
    ) {
      return sourceDrawings;
    }

    const dx = pointerCoordinate.x - dragState.startCoordinate.x;
    const dy = pointerCoordinate.y - dragState.startCoordinate.y;
    const [originFirst, originSecond] = dragState.originCoordinates;

    if (!originFirst || !originSecond) return sourceDrawings;

    return sourceDrawings.map((drawing) => {
      if (drawing.id !== dragState.drawingId || !isTwoPointDrawingType(drawing.type)) return drawing;

      const first = coordinateToDrawingPoint({
        x: originFirst.x + dx,
        y: originFirst.y + dy,
      });
      const second = coordinateToDrawingPoint({
        x: originSecond.x + dx,
        y: originSecond.y + dy,
      });

      if (!first || !second) return drawing;

      return {
        ...drawing,
        points: [first, second],
      };
    });
  }

  const buildIchimokuCloudPolygons = useCallback((): ProjectedCloudPolygon[] => {
    const spanAByTime = new Map(
      seriesData.lines.ichimokuSpanA.map((point) => [String(point.time), point])
    );
    const pairedPoints = seriesData.lines.ichimokuSpanB.flatMap((spanBPoint): Array<{
      timeKey: string;
      spanA: DrawingCoordinate;
      spanB: DrawingCoordinate;
      tone: ProjectedCloudPolygon["tone"];
    }> => {
      const spanAPoint = spanAByTime.get(String(spanBPoint.time));

      if (!spanAPoint) return [];

      const spanA = linePointToCoordinate(spanAPoint);
      const spanB = linePointToCoordinate(spanBPoint);

      if (!spanA || !spanB) return [];

      return [
        {
          timeKey: String(spanBPoint.time),
          spanA,
          spanB,
          tone: spanAPoint.value >= spanBPoint.value ? "bullish" : "bearish",
        },
      ];
    });

    const polygons: ProjectedCloudPolygon[] = [];

    for (let index = 1; index < pairedPoints.length; index += 1) {
      const previous = pairedPoints[index - 1];
      const current = pairedPoints[index];

      if (Math.abs(current.spanA.x - previous.spanA.x) > Math.max(overlaySize.width, 1) * 0.5) {
        continue;
      }

      polygons.push({
        id: `${previous.timeKey}:${current.timeKey}:${current.tone}`,
        tone: current.tone,
        points: [
          `${previous.spanA.x},${previous.spanA.y}`,
          `${current.spanA.x},${current.spanA.y}`,
          `${current.spanB.x},${current.spanB.y}`,
          `${previous.spanB.x},${previous.spanB.y}`,
        ].join(" "),
      });
    }

    return polygons;
  }, [linePointToCoordinate, overlaySize.width, seriesData.lines.ichimokuSpanA, seriesData.lines.ichimokuSpanB]);

  function handleDrawingPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;

    if (drawingTool === "cursor") {
      const pointerCoordinate = pointerCoordinateFromEvent(event);
      const hitDrawingId = pointerCoordinate ? findHoveredDrawingId(pointerCoordinate) : null;

      if (!hitDrawingId) {
        setHoveredDrawingId(null);
        onSelectedDrawingChange?.(null);
      }

      return;
    }

    let anchor = anchorFromPointer(event, { snap: !event.altKey });

    if (!anchor) return;

    if (event.shiftKey && draftAnchor) {
      anchor = constrainAnchorToAngle(anchor, drawingPointToCoordinate(draftAnchor));
    }

    setSnapCoordinate(anchor.snapped ? { x: anchor.x, y: anchor.y } : null);

    if (drawingTool === "anchorVwap") {
      commitDrawing("anchorVwap", [anchor]);
      setDraftAnchor(null);
      setHoverAnchor(null);
      return;
    }

    if (drawingTool === "horizontal") {
      commitDrawing("horizontal", [anchor]);
      setDraftAnchor(null);
      setHoverAnchor(null);
      return;
    }

    if (!isTwoPointDrawingTool(drawingTool)) return;

    if (!draftAnchor) {
      setDraftAnchor(anchor);
      setHoverAnchor(anchor);
      return;
    }

    commitDrawing(drawingTool, [draftAnchor, anchor]);
    setDraftAnchor(null);
    setHoverAnchor(null);
  }

  function handleDrawingPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const dragState = dragStateRef.current;

    if (dragState) {
      const pointerCoordinate = pointerCoordinateFromEvent(event);
      let anchor =
        dragState.mode === "line" ? null : anchorFromPointer(event, { snap: !event.altKey });

      if (dragState.mode !== "line" && !anchor) return;

      if (anchor && event.shiftKey && dragState.mode === "point") {
        anchor = constrainAnchorToAngle(anchor, dragState.oppositeCoordinate);
      }

      setSnapCoordinate(anchor?.snapped ? { x: anchor.x, y: anchor.y } : null);
      setDragPreviewDrawings((current) =>
        applyActiveDrawingDrag(
          current ?? drawings,
          dragState,
          anchor,
          pointerCoordinate
        )
      );
      return;
    }

    const pointerCoordinate = pointerCoordinateFromEvent(event);

    if (!draftAnchor) {
      const nextHoveredDrawingId = pointerCoordinate ? findHoveredDrawingId(pointerCoordinate) : null;
      setHoveredDrawingId((current) =>
        current === nextHoveredDrawingId ? current : nextHoveredDrawingId
      );
    }

    if (!isTwoPointDrawingTool(drawingTool) || !draftAnchor) return;

    let anchor = anchorFromPointer(event, { snap: !event.altKey });

    if (anchor) {
      if (event.shiftKey) {
        anchor = constrainAnchorToAngle(anchor, drawingPointToCoordinate(draftAnchor));
      }

      setHoverAnchor(anchor);
      setSnapCoordinate(anchor.snapped ? { x: anchor.x, y: anchor.y } : null);
    }
  }

  function startDrawingDrag(
    event: ReactPointerEvent<SVGElement>,
    drawing: ChartDrawing,
    mode: DrawingDragState["mode"],
    pointIndex: 0 | 1 = 0
  ) {
    if (event.button !== 0) return;

    event.stopPropagation();

    const startCoordinate = pointerCoordinateFromEvent(event);
    const visibleRange = rememberVisibleLogicalRange();
    const pointCoordinates = isTwoPointDrawingType(drawing.type)
      ? drawing.points
          .slice(0, 2)
          .map((point) => drawingPointToCoordinate(point))
          .filter((coordinate): coordinate is DrawingCoordinate => coordinate !== null)
      : [];
    const originCoordinates =
      mode === "line" ? pointCoordinates : undefined;
    const oppositeCoordinate =
      mode === "point" && pointCoordinates.length >= 2
        ? pointCoordinates[pointIndex === 0 ? 1 : 0]
        : undefined;

    if (mode === "line" && (!startCoordinate || !originCoordinates || originCoordinates.length < 2)) {
      return;
    }

    event.currentTarget.setPointerCapture(event.pointerId);
    dragStateRef.current = {
      drawingId: drawing.id,
      mode,
      pointIndex,
      pointerId: event.pointerId,
      startCoordinate: mode === "line" ? startCoordinate ?? undefined : undefined,
      originCoordinates,
      oppositeCoordinate,
      visibleLogicalRange: visibleRange ?? undefined,
    };
    setDraftAnchor(null);
    setHoverAnchor(null);
    setDragPreviewDrawings(activeDrawings);
    selectDrawing(drawing.id);
  }

  function finishDrawingDrag(event: ReactPointerEvent<SVGSVGElement>) {
    const dragState = dragStateRef.current;

    if (!dragState) return;

    const pointerCoordinate = pointerCoordinateFromEvent(event);
    let anchor =
      dragState.mode === "line" ? null : anchorFromPointer(event, { snap: !event.altKey });

    if (anchor && event.shiftKey && dragState.mode === "point") {
      anchor = constrainAnchorToAngle(anchor, dragState.oppositeCoordinate);
    }

    const sourceDrawings = dragPreviewDrawings ?? drawings;
    const nextDrawings = attachActiveDrawingsAnalytics(
      applyActiveDrawingDrag(sourceDrawings, dragState, anchor, pointerCoordinate)
    );
    const visibleRange = dragState.visibleLogicalRange ?? rememberVisibleLogicalRange();

    commitDrawingState(nextDrawings, dragState.drawingId);
    dragStateRef.current = null;
    setDragPreviewDrawings(null);
    setSnapCoordinate(null);
    restoreVisibleLogicalRange(visibleRange);
  }

  function selectDrawing(drawingId: string) {
    onSelectedDrawingChange?.(drawingId);
  }

  function clearDrawingDraft() {
    dragStateRef.current = null;
    setDraftAnchor(null);
    setHoverAnchor(null);
    setHoveredDrawingId(null);
    setSnapCoordinate(null);
    setDragPreviewDrawings(null);
  }

  function handleDrawingPointerEnter(drawingId: string) {
    setHoveredDrawingId(drawingId);
  }

  function handleDrawingPointerLeave(drawingId: string) {
    setHoveredDrawingId((current) => (current === drawingId ? null : current));
  }

  const findHoveredDrawingId = useCallback((coordinate: DrawingCoordinate) => {
    for (let index = projectedDrawings.length - 1; index >= 0; index -= 1) {
      const projectedDrawing = projectedDrawings[index];

      if (isProjectedDrawingHit(coordinate, projectedDrawing)) {
        return projectedDrawing.drawing.id;
      }
    }

    return null;
  }, [projectedDrawings]);

  useEffect(() => {
    if (drawingTool !== "cursor" || projectedDrawings.length === 0) {
      return undefined;
    }

    function handleWindowPointerMove(event: PointerEvent) {
      if (dragStateRef.current) return;

      const overlay = overlaySvgRef.current;

      if (!overlay) return;

      const rect = overlay.getBoundingClientRect();
      const coordinate = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      const isInside =
        coordinate.x >= 0 &&
        coordinate.x <= rect.width &&
        coordinate.y >= 0 &&
        coordinate.y <= rect.height;
      const nextHoveredDrawingId = isInside ? findHoveredDrawingId(coordinate) : null;

      setHoveredDrawingId((current) =>
        current === nextHoveredDrawingId ? current : nextHoveredDrawingId
      );
    }

    window.addEventListener("pointermove", handleWindowPointerMove);

    return () => window.removeEventListener("pointermove", handleWindowPointerMove);
  }, [drawingTool, findHoveredDrawingId, projectedDrawings.length]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();

      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;

      if (event.key === "Escape") {
        if (!draftAnchor && !dragStateRef.current && !selectedDrawingId) return;

        event.preventDefault();
        clearDrawingDraft();
        if (!draftAnchor && selectedDrawingId) {
          onSelectedDrawingChange?.(null);
        }
        return;
      }

      if (!selectedDrawingId) return;
      if (event.key !== "Delete" && event.key !== "Backspace") return;

      event.preventDefault();
      deleteDrawing(selectedDrawingId);
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deleteDrawing, draftAnchor, onSelectedDrawingChange, selectedDrawingId]);

  useEffect(() => {
    function handleChartNavigationKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();
      const container = containerRef.current;
      const isChartActive =
        shortcutActiveRef.current ||
        (container !== null &&
          document.activeElement instanceof Node &&
          container.contains(document.activeElement));

      if (!isChartActive) return;
      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;
      if (event.altKey || event.ctrlKey || event.metaKey) return;

      const key = event.key;
      const code = event.code;

      if (key === "+" || key === "=" || code === "NumpadAdd") {
        event.preventDefault();
        updateVisibleLogicalRange((range) => {
          const center = (range.from + range.to) / 2;
          const width = Math.max(6, (range.to - range.from) * 0.82);

          return {
            from: center - width / 2,
            to: center + width / 2,
          };
        });
        return;
      }

      if (key === "-" || key === "_" || code === "NumpadSubtract") {
        event.preventDefault();
        updateVisibleLogicalRange((range) => {
          const center = (range.from + range.to) / 2;
          const width = Math.max(8, (range.to - range.from) * 1.18);

          return {
            from: center - width / 2,
            to: center + width / 2,
          };
        });
        return;
      }

      if (key === "ArrowLeft" || key === "ArrowRight") {
        event.preventDefault();
        updateVisibleLogicalRange((range) => {
          const width = Math.max(1, range.to - range.from);
          const delta = width * (key === "ArrowRight" ? 0.12 : -0.12);

          return {
            from: range.from + delta,
            to: range.to + delta,
          };
        });
        return;
      }

      if (key === "Home" || key === "End") {
        event.preventDefault();
        resetVisibleLogicalRangeToLatest();
      }
    }

    window.addEventListener("keydown", handleChartNavigationKeyDown);

    return () => window.removeEventListener("keydown", handleChartNavigationKeyDown);
  }, [resetVisibleLogicalRangeToLatest, updateVisibleLogicalRange]);

  useEffect(() => {
    if (!isTwoPointDrawingTool(drawingTool)) {
      const timer = window.setTimeout(() => {
        setDraftAnchor(null);
        setHoverAnchor(null);
        setHoveredDrawingId(null);
      }, 0);

      return () => window.clearTimeout(timer);
    }

    return undefined;
  }, [drawingTool]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const nextDrawings = activeDrawings.flatMap((drawing): ProjectedDrawing[] => {
        if (drawing.type === "horizontal") {
          const point = drawing.points[0];
          const coordinate = point ? drawingPointToCoordinate(point) : null;

          if (!point || !coordinate) return [];

          return [
            {
              drawing,
              label: formatDrawingPrice(point.price),
              points: [
                { x: 0, y: coordinate.y },
                { x: overlaySize.width, y: coordinate.y },
              ],
            },
          ];
        }

        if (drawing.type === "anchorVwap") {
          const point = drawing.points[0];
          const coordinate = point ? drawingPointToCoordinate(point) : null;

          if (!point || !coordinate) return [];

          const anchoredVwapLine = buildAnchoredVwapProjection(point);
          const lineEnd = anchoredVwapLine[anchoredVwapLine.length - 1] ?? coordinate;

          return [
            {
              drawing,
              label: drawing.derivedMetrics?.anchoredVwapAnalysis?.labels.vwap ?? "VWAP",
              points: [coordinate, lineEnd],
              anchorPoints: [coordinate, coordinate],
              anchoredVwapLine,
            },
          ];
        }

        const first = drawing.points[0] ? drawingPointToCoordinate(drawing.points[0]) : null;
        const second = drawing.points[1] ? drawingPointToCoordinate(drawing.points[1]) : null;

        if (!first || !second) return [];

        if (drawing.type === "trend") {
          return [
            {
              drawing,
              label: formatDrawingPrice(drawing.points[1].price),
              points: [first, second],
              anchorPoints: [first, second],
            },
          ];
        }

        if (drawing.type === "ray") {
          return [
            {
              drawing,
              label: formatDrawingPrice(drawing.points[1].price),
              points: extendRayToViewport(first, second, overlaySize.width, overlaySize.height),
              anchorPoints: [first, second],
            },
          ];
        }

        if (drawing.type === "fibonacci") {
          return [
            {
              drawing,
              label: "Fib",
              points: [first, second],
              anchorPoints: [first, second],
              fibonacciLevels: buildFibonacciLevels(
                first,
                second,
                drawing.points[0].price,
                drawing.points[1].price
              ),
            },
          ];
        }

        if (drawing.type === "measure" || drawing.type === "priceRange") {
          return [
            {
              drawing,
              label: "量測",
              points: [first, second],
              anchorPoints: [first, second],
              measurementStats: drawing.derivedMetrics
                ? measurementStatsFromMetrics(drawing.derivedMetrics)
                : buildMeasurementStats(
                    drawing.points[0],
                    drawing.points[1],
                    chartDataTimeIndex
                  ),
            },
          ];
        }

        if (drawing.type === "volumeProfileRange") {
          return [
            {
              drawing,
              label: "VP",
              points: [first, second],
              anchorPoints: [first, second],
              volumeProfileBins: buildVolumeProfileRangeProjection(
                drawing.derivedMetrics?.volumeProfileAnalysis,
                first,
                second
              ),
            },
          ];
        }

        return [
          {
            drawing,
            label: `${formatDrawingPrice(Math.min(drawing.points[0].price, drawing.points[1].price))}-${formatDrawingPrice(Math.max(drawing.points[0].price, drawing.points[1].price))}`,
            points: [first, second],
            anchorPoints: [first, second],
          },
        ];
      });

      const draftDrawingType = isTwoPointDrawingTool(drawingTool) ? drawingTool : null;
      const firstDraftPoint =
        draftDrawingType && draftAnchor ? drawingPointToCoordinate(draftAnchor) : null;
      const secondDraftPoint =
        draftDrawingType && hoverAnchor ? drawingPointToCoordinate(hoverAnchor) : null;

      const nextCloudPolygons = activeIndicators.ichimoku ? buildIchimokuCloudPolygons() : [];
      let nextDraftDrawing: ProjectedDraftDrawing | null = null;

      if (draftDrawingType && draftAnchor && hoverAnchor && firstDraftPoint && secondDraftPoint) {
        const draftPoints: [DrawingCoordinate, DrawingCoordinate] =
          draftDrawingType === "trend"
            ? [firstDraftPoint, secondDraftPoint]
            : draftDrawingType === "ray"
              ? extendRayToViewport(
                  firstDraftPoint,
                  secondDraftPoint,
                  overlaySize.width,
                  overlaySize.height
                )
              : [firstDraftPoint, secondDraftPoint];

        nextDraftDrawing = {
              type: draftDrawingType,
              points: draftPoints,
              anchorPoints: [firstDraftPoint, secondDraftPoint],
              fibonacciLevels:
                draftDrawingType === "fibonacci"
                  ? buildFibonacciLevels(
                      firstDraftPoint,
                      secondDraftPoint,
                      draftAnchor.price,
                      hoverAnchor.price
                    )
                  : undefined,
              measurementStats:
                draftDrawingType === "measure" || draftDrawingType === "priceRange"
                  ? buildMeasurementStats(draftAnchor, hoverAnchor, chartDataTimeIndex)
                  : undefined,
            };
      }

      setProjectedCloudPolygons((current) =>
        preserveEmptyProjection(current, nextCloudPolygons)
      );
      setProjectedDrawings((current) =>
        preserveEmptyProjection(current, nextDrawings)
      );
      setProjectedDraftDrawing((current) =>
        current === null && nextDraftDrawing === null ? current : nextDraftDrawing
      );
    });

    return () => window.cancelAnimationFrame(frame);
  }, [
    activeIndicators.ichimoku,
    chartDataTimeIndex,
    drawingPointToCoordinate,
    activeDrawings,
    buildAnchoredVwapProjection,
    buildIchimokuCloudPolygons,
    buildVolumeProfileRangeProjection,
    draftAnchor,
    drawingTool,
    hoverAnchor,
    overlayRevision,
    overlaySize.height,
    overlaySize.width,
    timeMode,
  ]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const nextVolumeProfile = activeIndicators.volumeProfile
        ? buildVolumeProfileProjection()
        : [];
      const nextGapZones = activeIndicators.gap ? buildGapZoneProjection() : [];
      const nextSupportResistance = activeIndicators.supportResistance
        ? buildSupportResistanceProjection()
        : [];
      const nextTechnicalSignals =
        activeIndicators.signals ||
        activeIndicators.candlestickPatterns ||
        activeIndicators.divergence
          ? buildTechnicalSignalProjection()
          : [];

      setProjectedVolumeProfile((current) =>
        preserveEmptyProjection(current, nextVolumeProfile)
      );
      setProjectedGapZones((current) =>
        preserveEmptyProjection(current, nextGapZones)
      );
      setProjectedSupportResistance((current) =>
        preserveEmptyProjection(current, nextSupportResistance)
      );
      setProjectedTechnicalSignals((current) =>
        preserveEmptyProjection(current, nextTechnicalSignals)
      );
    });

    return () => window.cancelAnimationFrame(frame);
  }, [
    activeIndicators.candlestickPatterns,
    activeIndicators.divergence,
    activeIndicators.gap,
    activeIndicators.signals,
    activeIndicators.supportResistance,
    activeIndicators.volumeProfile,
    buildGapZoneProjection,
    buildSupportResistanceProjection,
    buildTechnicalSignalProjection,
    buildVolumeProfileProjection,
    overlayRevision,
  ]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || seriesData.candles.length === 0) return;
    const initialHeight = container.clientHeight || height;

    const chart = createChart(container, {
      autoSize: false,
      width: container.clientWidth,
      height: initialHeight,
      layout: {
        background: { type: ColorType.Solid, color: omiChartColors.surface },
        textColor: omiChartColors.neutralMuted,
        fontSize: 12,
        fontFamily:
          'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        attributionLogo: false,
        panes: {
          separatorColor: omiChartColors.grid,
          separatorHoverColor: omiChartColors.tooltipBorder,
          enableResize: true,
        },
      },
      grid: {
        vertLines: { color: omiChartColors.gridSubtle },
        horzLines: { color: omiChartColors.grid },
      },
      rightPriceScale: {
        borderColor: omiChartColors.axisBorder,
        scaleMargins: {
          top: 0.07,
          bottom: activeIndicators.volume ? 0.27 : 0.08,
        },
      },
      timeScale: {
        borderColor: omiChartColors.axisBorder,
        timeVisible: timeMode === "intraday",
        secondsVisible: false,
        rightOffset: chartRightPaddingBars(timeMode),
        barSpacing: timeMode === "intraday" ? 10 : 7,
        fixRightEdge: false,
        rightBarStaysOnScroll: false,
        lockVisibleTimeRangeOnResize: true,
        tickMarkFormatter: (time: Time, tickMarkType: TickMarkType) => {
          if (timeMode === "intraday" && tickMarkType >= 3) {
            const parts = chartTimeParts(time);

            if (parts) return `${pad2(parts.hour)}:${pad2(parts.minute)}`;
          }

          return formatChartDate(time);
        },
      },
      crosshair: {
        mode: CrosshairMode.MagnetOHLC,
        vertLine: {
          color: omiChartColors.crosshair,
          labelBackgroundColor: omiChartColors.text,
          style: 2,
        },
        horzLine: {
          color: omiChartColors.crosshair,
          labelBackgroundColor: omiChartColors.text,
          style: 2,
        },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: true,
      },
      localization: {
        locale: "zh-TW",
        dateFormat: "yyyy/MM/dd",
        timeFormatter: (time: Time) => formatChartDateTime(time, timeMode),
        priceFormatter: (price: number) => formatPrice(price),
      },
    });

    chartRef.current = chart;

    if (chartStyle === "line") {
      const mainLineSeries = chart.addSeries(LineSeries, {
        title: "Close",
        color: omiChartColors.text,
        lineWidth: 2,
        priceLineVisible: true,
        lastValueVisible: true,
        priceFormat: {
          type: "price",
          precision: 2,
          minMove: 0.01,
        },
      });
      mainLineSeries.setData(seriesData.line);
      mainSeriesRef.current = mainLineSeries;
    } else {
      const candleSeries = chart.addSeries(CandlestickSeries, {
        title: "K",
        upColor,
        downColor,
        borderUpColor: upColor,
        borderDownColor: downColor,
        wickUpColor: upColor,
        wickDownColor: downColor,
        priceFormat: {
          type: "price",
          precision: 2,
          minMove: 0.01,
        },
      });
      candleSeries.setData(seriesData.candles);
      mainSeriesRef.current = candleSeries;
    }

    if (activeIndicators.volume) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        title: volumePanelLabel,
        priceScaleId: "",
        priceFormat: {
          type: "volume",
        },
        color: omiChartColors.volume,
      });
      volumeSeries.setData(seriesData.volumes);
      chart.priceScale("").applyOptions({
        scaleMargins: {
          top: 0.82,
          bottom: 0,
        },
      });
    }

    function addMainLine(
      data: PlotLineData[],
      title: string,
      color: string,
      options?: { lineWidth?: 1 | 2 | 3 | 4; dashed?: boolean; pointsOnly?: boolean }
    ) {
      if (data.length === 0) return;

      const series = chart.addSeries(LineSeries, {
        title,
        color,
        lineWidth: options?.lineWidth ?? 2,
        lineVisible: !options?.pointsOnly,
        pointMarkersVisible: Boolean(options?.pointsOnly),
        pointMarkersRadius: options?.pointsOnly ? 3 : undefined,
        priceLineVisible: false,
        lastValueVisible: false,
        lineStyle: options?.dashed ? 2 : 0,
      });
      series.setData(data);
    }

    function addPaneLine(
      paneIndex: number,
      data: LineData<Time>[],
      title: string,
      color: string,
      options?: { lineWidth?: 1 | 2 | 3 | 4; dashed?: boolean }
    ) {
      if (data.length === 0) return;

      const series = chart.addSeries(
        LineSeries,
        {
          title,
          color,
          lineWidth: options?.lineWidth ?? 2,
          priceLineVisible: false,
          lastValueVisible: true,
          lineStyle: options?.dashed ? 2 : 0,
        },
        paneIndex
      );
      series.setData(data);
    }

    function addIndicatorPane(heightPx = 92) {
      const pane = chart.addPane();
      pane.setHeight(heightPx);
      return pane.paneIndex();
    }

    if (activeIndicators.ma) {
      addMainLine(seriesData.lines.maShort, `MA${params.maShort}`, maColors.maShort);
      addMainLine(seriesData.lines.maMiddle, `MA${params.maMiddle}`, maColors.maMiddle);
      addMainLine(seriesData.lines.maLong, `MA${params.maLong}`, maColors.maLong, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.ema) {
      addMainLine(seriesData.lines.emaFast, `EMA${params.emaFast}`, omiChartColors.cyan);
      addMainLine(seriesData.lines.emaSlow, `EMA${params.emaSlow}`, omiChartColors.rose);
    }

    if (activeIndicators.wma) {
      addMainLine(seriesData.lines.wma, `WMA${params.wmaPeriod}`, omiChartColors.sky);
    }

    if (activeIndicators.hma) {
      addMainLine(seriesData.lines.hma, `HMA${params.hmaPeriod}`, omiChartColors.roseDark);
    }

    if (activeIndicators.vwma) {
      addMainLine(seriesData.lines.vwma, `VWMA${params.vwmaPeriod}`, omiChartColors.green, {
        dashed: true,
      });
    }

    if (activeIndicators.bollinger) {
      addMainLine(seriesData.lines.bollingerUpper, "BOLL Upper", omiChartColors.indicator.bollinger, { lineWidth: 1 });
      addMainLine(seriesData.lines.bollingerMiddle, "BOLL Mid", omiChartColors.indicator.bollingerMiddle, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.bollingerLower, "BOLL Lower", omiChartColors.indicator.bollinger, { lineWidth: 1 });
    }

    if (activeIndicators.vwap) {
      addMainLine(seriesData.lines.vwap, "VWAP", omiChartColors.neutralLine, { dashed: true });
    }

    if (activeIndicators.psar) {
      addMainLine(seriesData.lines.psar, "SAR", omiChartColors.purple, { pointsOnly: true, lineWidth: 1 });
    }

    if (activeIndicators.donchian) {
      addMainLine(seriesData.lines.donchianUpper, `DONCH${params.donchianPeriod} U`, omiChartColors.lime, {
        lineWidth: 1,
      });
      addMainLine(seriesData.lines.donchianLower, `DONCH${params.donchianPeriod} L`, omiChartColors.lime, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.ichimoku) {
      addMainLine(
        seriesData.lines.ichimokuConversion,
        `Tenkan${params.ichimokuConversionPeriod}`,
        omiChartColors.marketUp,
        { lineWidth: 1 }
      );
      addMainLine(
        seriesData.lines.ichimokuBase,
        `Kijun${params.ichimokuBasePeriod}`,
        omiChartColors.info,
        { lineWidth: 1 }
      );
      addMainLine(seriesData.lines.ichimokuSpanA, "Senkou A", omiChartColors.marketDown, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.ichimokuSpanB, "Senkou B", omiChartColors.amberDark, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.ichimokuLagging, "Chikou", omiChartColors.textMuted, {
        lineWidth: 1,
        dashed: true,
      });
    }

    if (activeIndicators.supertrend) {
      addMainLine(seriesData.lines.supertrendUp, `ST${params.supertrendAtrPeriod}`, omiChartColors.marketDown, {
        lineWidth: 2,
      });
      addMainLine(seriesData.lines.supertrendDown, `ST${params.supertrendAtrPeriod}`, omiChartColors.marketUp, {
        lineWidth: 2,
      });
    }

    if (activeIndicators.keltner) {
      addMainLine(seriesData.lines.keltnerUpper, `KC${params.keltnerPeriod} U`, omiChartColors.teal, {
        lineWidth: 1,
      });
      addMainLine(seriesData.lines.keltnerMiddle, `KC${params.keltnerPeriod} M`, omiChartColors.tealBright, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.keltnerLower, `KC${params.keltnerPeriod} L`, omiChartColors.teal, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.pivotPoints) {
      addMainLine(seriesData.lines.pivot, "Pivot", omiChartColors.neutralMuted, { lineWidth: 1, dashed: true });
      addMainLine(seriesData.lines.pivotR1, "R1", omiChartColors.marketUp, { lineWidth: 1, dashed: true });
      addMainLine(seriesData.lines.pivotS1, "S1", omiChartColors.marketDown, { lineWidth: 1, dashed: true });
    }

    if (activeIndicators.supportResistance) {
      addMainLine(seriesData.lines.resistance, `R${params.supportResistanceLookback}`, omiChartColors.marketUpFlash, {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.support, `S${params.supportResistanceLookback}`, omiChartColors.marketDownFlash, {
        lineWidth: 1,
        dashed: true,
      });
    }

    if (activeIndicators.gap) {
      addMainLine(seriesData.lines.gapUp, `Gap Up ${params.gapMinPct}%`, omiChartColors.marketUp, {
        pointsOnly: true,
        lineWidth: 1,
      });
      addMainLine(seriesData.lines.gapDown, `Gap Down ${params.gapMinPct}%`, omiChartColors.marketDown, {
        pointsOnly: true,
        lineWidth: 1,
      });
    }

    if (activeIndicators.rsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.rsi, `RSI${params.rsiPeriod}`, omiChartColors.fuchsia);
    }

    if (activeIndicators.macd) {
      const paneIndex = addIndicatorPane(104);
      const histogramSeries = chart.addSeries(
        HistogramSeries,
        {
          title: "MACD H",
          color: omiChartColors.volumeStrong,
          priceLineVisible: false,
          lastValueVisible: true,
          priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        },
        paneIndex
      );
      histogramSeries.setData(seriesData.macdHistogram);
      addPaneLine(paneIndex, seriesData.lines.macd, "MACD", omiChartColors.info, { lineWidth: 1 });
      addPaneLine(paneIndex, seriesData.lines.macdSignal, "Signal", omiChartColors.warning, { lineWidth: 1 });
    }

    if (activeIndicators.kd) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.kdK, `K${params.kdPeriod}`, omiChartColors.info);
      addPaneLine(paneIndex, seriesData.lines.kdD, `D${params.kdPeriod}`, omiChartColors.warning);
    }

    if (activeIndicators.momentum) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.momentum, `MOM${params.momentumPeriod}`, omiChartColors.indicator.momentum);
    }

    if (activeIndicators.tsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.tsi, `TSI${params.tsiLongPeriod}/${params.tsiShortPeriod}`, omiChartColors.purple);
      addPaneLine(paneIndex, seriesData.lines.tsiSignal, `TSI Sig${params.tsiSignalPeriod}`, omiChartColors.warning, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.awesomeOscillator) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.awesomeOscillator,
        `AO${params.awesomeFastPeriod}/${params.awesomeSlowPeriod}`,
        omiChartColors.pink
      );
    }

    if (activeIndicators.ultimateOscillator) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.ultimateOscillator,
        `UO${params.ultimateShortPeriod}/${params.ultimateMiddlePeriod}/${params.ultimateLongPeriod}`,
        omiChartColors.purpleAlt
      );
    }

    if (activeIndicators.atr) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.atr, `ATR${params.atrPeriod}`, omiChartColors.heat);
    }

    if (activeIndicators.bbWidth) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.bbWidth, `BB Width${params.bbWidthPeriod}`, omiChartColors.indicator.bollinger);
    }

    if (activeIndicators.stdDev) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.stdDev, `StdDev${params.stdDevPeriod}`, omiChartColors.neutralLine);
    }

    if (activeIndicators.choppiness) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.choppiness, `CHOP${params.choppinessPeriod}`, omiChartColors.brown);
    }

    if (activeIndicators.adx) {
      const paneIndex = addIndicatorPane(104);
      addPaneLine(paneIndex, seriesData.lines.adx, `ADX${params.adxPeriod}`, omiChartColors.purple);
      addPaneLine(paneIndex, seriesData.lines.plusDi, "+DI", omiChartColors.marketUp, { lineWidth: 1 });
      addPaneLine(paneIndex, seriesData.lines.minusDi, "-DI", omiChartColors.marketDown, { lineWidth: 1 });
    }

    if (activeIndicators.aroon) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.aroonUp, `Aroon Up${params.aroonPeriod}`, omiChartColors.marketUp);
      addPaneLine(paneIndex, seriesData.lines.aroonDown, `Aroon Down${params.aroonPeriod}`, omiChartColors.marketDown);
    }

    if (activeIndicators.obv) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.obv, "OBV", omiChartColors.neutralLine);
      addPaneLine(paneIndex, seriesData.lines.obvMa, `OBV MA${params.obvMa}`, omiChartColors.warning, {
        lineWidth: 1,
      });
    }

    if (activeIndicators.mfi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.mfi, `MFI${params.mfiPeriod}`, omiChartColors.teal);
    }

    if (activeIndicators.cmf) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.cmf, `CMF${params.cmfPeriod}`, omiChartColors.marketDown);
    }

    if (activeIndicators.adLine) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.adLine, "A/D", omiChartColors.neutralMuted);
    }

    if (activeIndicators.pvt) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.pvt, "PVT", omiChartColors.skyDark);
    }

    if (activeIndicators.relativeStrength) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.relativeStrength,
        `RS${params.relativeStrengthLookback}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        omiChartColors.purple
      );
    }

    if (activeIndicators.beta) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.beta,
        `Beta${params.betaPeriod}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        omiChartColors.teal
      );
    }

    if (activeIndicators.correlation) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.correlation,
        `Corr${params.correlationPeriod}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        omiChartColors.skyDark
      );
    }

    if (activeIndicators.cci) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.cci, `CCI${params.cciPeriod}`, omiChartColors.indigo);
    }

    if (activeIndicators.williamsR) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.williamsR, `W%R${params.williamsRPeriod}`, omiChartColors.pink);
    }

    if (activeIndicators.roc) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.roc, `ROC${params.rocPeriod}`, omiChartColors.indicator.momentum);
    }

    if (activeIndicators.stochRsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.stochRsiK, "StochRSI K", omiChartColors.info);
      addPaneLine(paneIndex, seriesData.lines.stochRsiD, "StochRSI D", omiChartColors.warning);
    }

    if (activeIndicators.trix) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.trix, `TRIX${params.trixPeriod}`, omiChartColors.purple);
      addPaneLine(paneIndex, seriesData.lines.trixSignal, `Signal${params.trixSignal}`, omiChartColors.warning, {
        lineWidth: 1,
      });
    }

    chart.panes()[0]?.setStretchFactor(4);

    const savedLogicalRange =
      visibleLogicalRangeKeyRef.current === chartSeriesKey
        ? visibleLogicalRangeRef.current
        : null;
    const defaultLogicalRange = buildDefaultVisibleLogicalRange(
      seriesData.candles.length,
      timeMode
    );

    if (savedLogicalRange) {
      chart.timeScale().setVisibleLogicalRange(savedLogicalRange);
    } else if (defaultLogicalRange) {
      chart.timeScale().setVisibleLogicalRange(defaultLogicalRange);
    } else {
      chart.timeScale().fitContent();
    }

    setOverlaySize((current) => {
      const nextSize = { width: container.clientWidth, height: container.clientHeight || height };

      return current.width === nextSize.width && current.height === nextSize.height
        ? current
        : nextSize;
    });

    const syncOverlay = (logicalRange: LogicalRange | null) => {
      if (logicalRange) {
        visibleLogicalRangeRef.current = {
          from: logicalRange.from,
          to: logicalRange.to,
        };
        visibleLogicalRangeKeyRef.current = chartSeriesKey;
      }

      scheduleOverlayRevision();
    };

    chart.timeScale().subscribeVisibleLogicalRangeChange(syncOverlay);

    const resizeObserver = new ResizeObserver(() => {
      const nextHeight = container.clientHeight || height;
      chart.applyOptions({
        autoSize: false,
        width: container.clientWidth,
        height: nextHeight,
      });
      setOverlaySize((current) => {
        const nextSize = { width: container.clientWidth, height: nextHeight };

        return current.width === nextSize.width && current.height === nextSize.height
          ? current
          : nextSize;
      });
      scheduleOverlayRevision();
    });
    resizeObserver.observe(container);
    scheduleOverlayRevision();

    return () => {
      const latestLogicalRange = chart.timeScale().getVisibleLogicalRange();

      if (latestLogicalRange) {
        visibleLogicalRangeRef.current = {
          from: latestLogicalRange.from,
          to: latestLogicalRange.to,
        };
        visibleLogicalRangeKeyRef.current = chartSeriesKey;
      }

      if (overlayRevisionFrameRef.current !== null) {
        window.cancelAnimationFrame(overlayRevisionFrameRef.current);
        overlayRevisionFrameRef.current = null;
      }

      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncOverlay);
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      mainSeriesRef.current = null;
    };
  }, [
    activeIndicators,
    benchmarkLabel,
    chartSeriesKey,
    chartStyle,
    downColor,
    height,
    maColors,
    omiChartColors,
    params,
    scheduleOverlayRevision,
    seriesData,
    timeMode,
    upColor,
    volumePanelLabel,
  ]);

  useEffect(() => {
    const chart = chartRef.current;

    if (!chart) return;

    const interactive = drawingTool === "cursor";

    chart.applyOptions({
      handleScroll: {
        mouseWheel: interactive,
        pressedMouseMove: interactive,
        horzTouchDrag: interactive,
        vertTouchDrag: false,
      },
      handleScale: {
        mouseWheel: interactive,
        pinch: interactive,
        axisPressedMouseMove: interactive,
      },
    });
  }, [drawingTool]);

  if (seriesData.candles.length === 0) {
    return (
      <div className="flex h-[520px] items-center justify-center border-t border-omi-border-subtle bg-omi-surface text-sm text-omi-text-muted">
        尚無可繪製的 K 線資料
      </div>
    );
  }

  const draftRectangleBox =
    projectedDraftDrawing?.type === "rectangle" || projectedDraftDrawing?.type === "volumeProfileRange"
      ? rectangleBounds(projectedDraftDrawing.anchorPoints ?? projectedDraftDrawing.points)
      : null;
  const draftPriceRangeBox =
    projectedDraftDrawing?.type === "priceRange"
      ? rectangleBounds(projectedDraftDrawing.anchorPoints ?? projectedDraftDrawing.points)
      : null;
  const shouldCaptureDrawingPointer =
    drawingTool !== "cursor" || Boolean(draftAnchor || dragPreviewDrawings);
  const selectedProjectedDrawing =
    selectedDrawingId === null
      ? null
      : projectedDrawings.find((item) => item.drawing.id === selectedDrawingId) ?? null;
  const selectedDrawingMetrics = selectedProjectedDrawing
    ? selectedProjectedDrawing.drawing.derivedMetrics ??
      buildDrawingDerivedMetrics(
        selectedProjectedDrawing.drawing.type,
        selectedProjectedDrawing.drawing.points,
        chartDataTimeIndex,
        chartData
      )
    : null;
  const selectedDrawingSummary =
    selectedProjectedDrawing && selectedDrawingMetrics
      ? selectedProjectedDrawing.drawing.omiSummary ??
        buildDrawingOmiSummary(
          selectedProjectedDrawing.drawing,
          selectedDrawingMetrics,
          activeDrawingContext
        )
      : null;

  return (
    <div className="border-t border-omi-border-subtle bg-omi-surface">
      {showHeader ? (
        <ProfessionalChartHeader
          candleCount={seriesData.candles.length}
          label={label}
          maColors={maColors}
          maEnabled={activeIndicators.ma}
          maLong={params.maLong}
          maMiddle={params.maMiddle}
          maShort={params.maShort}
          volumeEnabled={activeIndicators.volume}
          volumePanelLabel={volumePanelLabel}
        />
      ) : null}

      <div
        className="relative min-h-[520px] w-full overflow-hidden"
        onPointerEnter={() => {
          shortcutActiveRef.current = true;
        }}
        onPointerLeave={() => {
          shortcutActiveRef.current = false;
        }}
        onPointerDown={() => {
          containerRef.current?.focus({ preventScroll: true });
        }}
        onPointerDownCapture={(event) => {
          shortcutActiveRef.current = true;

          if (drawingTool !== "cursor") return;

          const overlay = overlaySvgRef.current;

          if (!overlay) return;

          const rect = overlay.getBoundingClientRect();
          const coordinate = {
            x: event.clientX - rect.left,
            y: event.clientY - rect.top,
          };
          const isInside =
            coordinate.x >= 0 &&
            coordinate.x <= rect.width &&
            coordinate.y >= 0 &&
            coordinate.y <= rect.height;
          const hitDrawingId = isInside ? findHoveredDrawingId(coordinate) : null;

          if (hitDrawingId) return;

          setHoveredDrawingId(null);
          onSelectedDrawingChange?.(null);
        }}
        style={{
          height: fillViewport ? "max(620px, calc(100vh - 132px))" : height,
        }}
      >
        <div ref={containerRef} tabIndex={0} className="absolute inset-0 outline-none" />
        {selectedProjectedDrawing && selectedDrawingMetrics ? (
          <SelectedDrawingMetricsCard
            drawingType={drawingTypeLabel(selectedProjectedDrawing.drawing.type)}
            metrics={selectedDrawingMetrics}
            summaryText={selectedDrawingSummary?.text ?? null}
          />
        ) : null}
        <svg
          ref={overlaySvgRef}
          className={[
            "absolute inset-0 z-10 h-full w-full",
            drawingTool === "cursor" ? "" : "cursor-crosshair",
          ].join(" ")}
          width={overlaySize.width}
          height={overlaySize.height}
          viewBox={`0 0 ${Math.max(overlaySize.width, 1)} ${Math.max(overlaySize.height, 1)}`}
          preserveAspectRatio="none"
          style={{
            pointerEvents: shouldCaptureDrawingPointer ? "auto" : "none",
          }}
          onPointerDown={handleDrawingPointerDown}
          onPointerMove={handleDrawingPointerMove}
          onPointerUp={finishDrawingDrag}
          onPointerCancel={finishDrawingDrag}
          onPointerLeave={() => {
            if (!dragStateRef.current) {
              setHoverAnchor(null);
              setSnapCoordinate(null);
            }
          }}
        >
          <ChartStaticIndicatorLayer
            chartColors={omiChartColors}
            cloudPolygons={projectedCloudPolygons}
            gapZones={projectedGapZones}
            overlaySize={overlaySize}
            supportResistance={projectedSupportResistance}
            technicalSignals={projectedTechnicalSignals}
            volumeProfile={projectedVolumeProfile}
          />
          {projectedDrawings.map(({ drawing, label: drawingLabel, points, anchorPoints, anchoredVwapLine, fibonacciLevels, volumeProfileBins, measurementStats }) => {
            const selected = drawing.id === selectedDrawingId;
            const hovered = drawing.id === hoveredDrawingId;
            const active = selected || hovered;
            const stroke = selected
              ? selectedDrawingColor
              : hovered
                ? hoveredDrawingColor
                : drawing.color;
            const lineWidth = selected ? 2.5 : hovered ? 2.1 : 1.5;
            const handles = anchorPoints ?? points;
            const zoneAnalysis = drawing.derivedMetrics?.zoneAnalysis ?? null;
            const fibonacciAnalysis = drawing.derivedMetrics?.fibonacciAnalysis ?? null;
            const anchoredVwapAnalysis = drawing.derivedMetrics?.anchoredVwapAnalysis ?? null;
            const volumeProfileAnalysis = drawing.derivedMetrics?.volumeProfileAnalysis ?? null;

            if (drawing.type === "anchorVwap") {
              const linePoints = (anchoredVwapLine ?? []).map((point) => `${point.x},${point.y}`).join(" ");
              const lastLinePoint = anchoredVwapLine?.[anchoredVwapLine.length - 1] ?? points[0];
              const labelWidth = 132;
              const labelX = Math.max(8, Math.min(lastLinePoint.x + 10, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(lastLinePoint.y - 22, overlaySize.height - 38));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  {linePoints ? (
                    <>
                      <polyline
                        points={linePoints}
                        fill="none"
                        stroke="transparent"
                        strokeWidth={14}
                        className="cursor-move"
                        pointerEvents="stroke"
                        onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                        onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                      />
                      <polyline
                        points={linePoints}
                        fill="none"
                        stroke={stroke}
                        strokeWidth={selected ? 2.4 : hovered ? 2 : 1.6}
                        strokeDasharray="7 4"
                        opacity={active ? 0.96 : 0.82}
                        pointerEvents="none"
                      />
                    </>
                  ) : null}
                  <circle
                    cx={points[0].x}
                    cy={points[0].y}
                    r={11}
                    fill="transparent"
                    className="cursor-grab"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "point", 0)}
                  />
                  <circle
                    cx={points[0].x}
                    cy={points[0].y}
                    r={active ? 4.8 : 4.2}
                    fill={stroke}
                    stroke={drawingHandleBorderColor}
                    strokeWidth={1.2}
                    pointerEvents="none"
                  />
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={30} rx={3} fill={omiChartColors.surface} stroke={stroke} opacity={0.95} />
                    <text x={10} y={13} className="fill-omi-text text-[10px] font-bold tabular-nums">
                      AVWAP {anchoredVwapAnalysis?.labels.vwap ?? drawingLabel}
                    </text>
                    <text x={10} y={25} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      {anchoredVwapAnalysis?.labels.status ?? "錨定 VWAP"}
                    </text>
                  </g>
                </g>
              );
            }

            if (drawing.type === "measure" && measurementStats) {
              const tone = measurementToneColor(measurementStats.tone);
              const actionStroke = selected
                ? selectedDrawingColor
                : hovered
                  ? hoveredDrawingColor
                  : tone;
              const labelWidth = 148;
              const labelX = Math.max(
                8,
                Math.min((points[0].x + points[1].x) / 2 + 10, overlaySize.width - labelWidth - 8)
              );
              const labelY = Math.max(18, Math.min((points[0].y + points[1].y) / 2 - 24, overlaySize.height - 52));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <line
                    x1={points[0].x}
                    y1={points[0].y}
                    x2={points[1].x}
                    y2={points[1].y}
                    stroke="transparent"
                    strokeWidth={14}
                    className="cursor-move"
                    pointerEvents="stroke"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line")}
                  />
                  <line
                    x1={points[0].x}
                    y1={points[0].y}
                    x2={points[1].x}
                    y2={points[1].y}
                    stroke={actionStroke}
                    strokeWidth={lineWidth}
                    strokeDasharray="6 4"
                    pointerEvents="none"
                  />
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={actionStroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={38} rx={3} fill={omiChartColors.surface} stroke={actionStroke} opacity={0.96} />
                    <text x={10} y={15} className="fill-omi-text text-[10px] font-bold tabular-nums">
                      價差 {measurementStats.priceDiffLabel} ({measurementStats.percentLabel})
                    </text>
                    <text x={10} y={30} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      {measurementStats.barsLabel ?? "跨距 -"} · 高 {measurementStats.highLabel} / 低 {measurementStats.lowLabel}
                    </text>
                  </g>
                </g>
              );
            }

            if (drawing.type === "priceRange" && measurementStats) {
              const tone = measurementToneColor(measurementStats.tone);
              const actionStroke = selected
                ? selectedDrawingColor
                : hovered
                  ? hoveredDrawingColor
                  : tone;
              const box = rectangleBounds(handles);
              const labelWidth = zoneAnalysis ? 152 : 136;
              const labelHeight = zoneAnalysis ? 52 : 38;
              const labelX = Math.max(8, Math.min(box.x + box.width + 8, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(box.y + 8, overlaySize.height - labelHeight - 14));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill={tone}
                    opacity={active ? 0.12 : 0.08}
                    pointerEvents="none"
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="transparent"
                    stroke="transparent"
                    strokeWidth={12}
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line")}
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="none"
                    stroke={actionStroke}
                    strokeWidth={lineWidth}
                    strokeDasharray="5 4"
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y}
                    x2={box.x + box.width}
                    y2={box.y}
                    stroke={actionStroke}
                    strokeWidth={1}
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y + box.height}
                    x2={box.x + box.width}
                    y2={box.y + box.height}
                    stroke={actionStroke}
                    strokeWidth={1}
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y + box.height / 2}
                    x2={box.x + box.width}
                    y2={box.y + box.height / 2}
                    stroke={actionStroke}
                    strokeWidth={1}
                    strokeDasharray="3 4"
                    opacity={0.72}
                    pointerEvents="none"
                  />
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={actionStroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={labelHeight} rx={3} fill={omiChartColors.surface} stroke={actionStroke} opacity={0.96} />
                    <text x={10} y={15} className="fill-omi-text text-[10px] font-bold tabular-nums">
                      {measurementStats.priceDiffLabel} ({measurementStats.percentLabel})
                    </text>
                    <text x={10} y={30} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      高 {measurementStats.highLabel} / 低 {measurementStats.lowLabel}
                    </text>
                    {zoneAnalysis ? (
                      <text x={10} y={45} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                        {zoneAnalysis.labels.status} · 位置 {zoneAnalysis.labels.position}
                      </text>
                    ) : null}
                  </g>
                </g>
              );
            }

            if (drawing.type === "volumeProfileRange") {
              const box = rectangleBounds(handles);
              const profileBins = volumeProfileBins ?? [];
              const labelWidth = 150;
              const labelHeight = 46;
              const labelX = Math.max(8, Math.min(box.x + box.width + 8, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(box.y + 8, overlaySize.height - labelHeight - 14));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill={stroke}
                    opacity={active ? 0.08 : 0.045}
                    pointerEvents="none"
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="transparent"
                    stroke="transparent"
                    strokeWidth={12}
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line")}
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={lineWidth}
                    strokeDasharray={selected ? undefined : "6 4"}
                    pointerEvents="none"
                  />
                  {profileBins.map((bin) => (
                    <g key={bin.id} pointerEvents="none">
                      <rect
                        x={bin.x}
                        y={bin.y}
                        width={bin.width}
                        height={bin.height}
                        fill={omiChartColors.text}
                        opacity={bin.poc ? 0.12 : bin.valueArea ? 0.065 : 0.035}
                      />
                      <rect
                        x={bin.x}
                        y={bin.y}
                        width={bin.sellWidth}
                        height={bin.height}
                        fill={omiChartColors.marketDown}
                        opacity={bin.poc ? 0.44 : bin.valueArea ? 0.3 : 0.2}
                      />
                      <rect
                        x={bin.x + bin.sellWidth}
                        y={bin.y}
                        width={bin.buyWidth}
                        height={bin.height}
                        fill={omiChartColors.marketUp}
                        opacity={bin.poc ? 0.44 : bin.valueArea ? 0.3 : 0.2}
                      />
                      {bin.poc ? (
                        <line
                          x1={box.x}
                          y1={bin.y + bin.height / 2}
                          x2={box.x + box.width}
                          y2={bin.y + bin.height / 2}
                          stroke={stroke}
                          strokeDasharray="4 4"
                          strokeWidth={1}
                          opacity={0.42}
                        />
                      ) : null}
                    </g>
                  ))}
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={stroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={labelHeight} rx={3} fill={omiChartColors.surface} stroke={stroke} opacity={0.95} />
                    <text x={10} y={14} className="fill-omi-text text-[10px] font-bold tabular-nums">
                      POC {volumeProfileAnalysis?.labels.poc ?? "-"}
                    </text>
                    <text x={10} y={28} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      VA {volumeProfileAnalysis?.labels.valueArea ?? "-"}
                    </text>
                    <text x={10} y={41} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      {volumeProfileAnalysis?.labels.latestPosition ?? "成交量分布"}
                    </text>
                  </g>
                </g>
              );
            }

            if (drawing.type === "rectangle") {
              const box = rectangleBounds(handles);
              const labelWidth = zoneAnalysis ? 132 : 108;
              const labelHeight = zoneAnalysis ? 34 : 18;
              const labelX = Math.max(8, Math.min(box.x + box.width + 8, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(box.y + 8, overlaySize.height - labelHeight - 14));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill={stroke}
                    opacity={active ? 0.1 : 0.07}
                    pointerEvents="none"
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="transparent"
                    stroke="transparent"
                    strokeWidth={12}
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line")}
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={lineWidth}
                    strokeDasharray={selected ? undefined : "6 4"}
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y + box.height / 2}
                    x2={box.x + box.width}
                    y2={box.y + box.height / 2}
                    stroke={stroke}
                    strokeWidth={1}
                    strokeDasharray="3 4"
                    opacity={0.72}
                    pointerEvents="none"
                  />
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={stroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  <g
                    transform={`translate(${labelX}, ${labelY})`}
                    pointerEvents="none"
                  >
                    <rect width={labelWidth} height={labelHeight} rx={3} fill={omiChartColors.surface} stroke={stroke} opacity={0.94} />
                    <text
                      x={labelWidth / 2}
                      y={12}
                      textAnchor="middle"
                      className="fill-omi-text text-[10px] font-bold tabular-nums"
                    >
                      {zoneAnalysis ? zoneAnalysis.labels.role : drawingLabel}
                    </text>
                    {zoneAnalysis ? (
                      <text
                        x={labelWidth / 2}
                        y={27}
                        textAnchor="middle"
                        className="fill-omi-text-muted text-[10px] font-semibold tabular-nums"
                      >
                        {zoneAnalysis.labels.status} · {zoneAnalysis.labels.position}
                      </text>
                    ) : null}
                  </g>
                </g>
              );
            }

            if (drawing.type === "fibonacci" && fibonacciLevels) {
              const minY = Math.min(handles[0].y, handles[1].y);
              const maxY = Math.max(handles[0].y, handles[1].y);

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <rect
                    x={0}
                    y={minY}
                    width={overlaySize.width}
                    height={Math.max(1, maxY - minY)}
                    fill={stroke}
                    opacity={active ? 0.07 : 0.04}
                    pointerEvents="none"
                  />
                  <rect
                    x={0}
                    y={minY}
                    width={overlaySize.width}
                    height={Math.max(12, maxY - minY)}
                    fill="transparent"
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line")}
                  />
                  {fibonacciLevels.map((level) => {
                    const nearest = fibonacciAnalysis?.nearestRatio === level.ratio;

                    return (
                    <g key={`${drawing.id}-fib-${level.ratio}`} pointerEvents="none">
                      <line
                        x1={0}
                        y1={level.y}
                        x2={overlaySize.width}
                        y2={level.y}
                        stroke={stroke}
                        strokeWidth={
                          nearest && active
                            ? Math.max(lineWidth, 2)
                            : level.ratio === 0 || level.ratio === 1
                              ? lineWidth
                              : 1
                        }
                        strokeDasharray={level.ratio === 0 || level.ratio === 1 ? undefined : "5 4"}
                        opacity={nearest && active ? 0.96 : level.ratio === 0 || level.ratio === 1 ? 0.95 : 0.72}
                      />
                      <g transform={`translate(${Math.max(8, overlaySize.width - 104)}, ${Math.max(14, level.y - 9)})`}>
                        <rect
                          width={96}
                          height={18}
                          rx={3}
                          fill={nearest && active ? omiChartColors.heatSoft : omiChartColors.surface}
                          stroke={stroke}
                          opacity={nearest && active ? 0.98 : 0.92}
                        />
                        <text
                          x={48}
                          y={12}
                          textAnchor="middle"
                          className="fill-omi-text text-[10px] font-bold tabular-nums"
                        >
                          {level.label} {level.priceLabel}
                        </text>
                      </g>
                    </g>
                    );
                  })}
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={stroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                </g>
              );
            }

            return (
              <g
                key={drawing.id}
                onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
              >
                <line
                  x1={points[0].x}
                  y1={points[0].y}
                  x2={points[1].x}
                  y2={points[1].y}
                  stroke="transparent"
                  strokeWidth={12}
                  className={drawing.type === "horizontal" ? "cursor-ns-resize" : "cursor-move"}
                  pointerEvents="stroke"
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerDown={(event) => {
                    if (drawing.type === "horizontal") {
                      startDrawingDrag(event, drawing, "horizontal");
                    } else {
                      startDrawingDrag(event, drawing, "line");
                    }
                  }}
                />
                <line
                  x1={points[0].x}
                  y1={points[0].y}
                  x2={points[1].x}
                  y2={points[1].y}
                  stroke={stroke}
                  strokeWidth={lineWidth}
                  strokeDasharray={drawing.type === "horizontal" ? "5 4" : undefined}
                  pointerEvents="none"
                />
                {active ? (
                  <>
                    {handles.map((handle, index) => (
                      <g key={`${drawing.id}-handle-${index}`}>
                        <circle
                          cx={handle.x}
                          cy={handle.y}
                          r={11}
                          fill="transparent"
                          className={drawing.type === "horizontal" ? "cursor-ns-resize" : "cursor-grab"}
                          pointerEvents="all"
                          onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                          onPointerDown={(event) =>
                            startDrawingDrag(
                              event,
                              drawing,
                              drawing.type === "horizontal" ? "horizontal" : "point",
                              index as 0 | 1
                            )
                          }
                        />
                        <circle
                          cx={handle.x}
                          cy={handle.y}
                          r={selected ? 4.6 : 4.2}
                          fill={stroke}
                          stroke={drawingHandleBorderColor}
                          strokeWidth={1.2}
                          pointerEvents="none"
                        />
                      </g>
                    ))}
                  </>
                ) : null}
                <g transform={`translate(${Math.max(8, Math.min(points[1].x + 8, overlaySize.width - 74))}, ${Math.max(16, points[1].y - 8)})`}>
                  <rect width={66} height={18} rx={3} fill={omiChartColors.surface} stroke={stroke} opacity={0.94} />
                  <text
                    x={33}
                    y={12}
                    textAnchor="middle"
                    className="fill-omi-text text-[10px] font-bold tabular-nums"
                  >
                    {drawingLabel}
                  </text>
                </g>
              </g>
            );
          })}
          {projectedDraftDrawing ? (
            draftRectangleBox ? (
              <rect
                x={draftRectangleBox.x}
                y={draftRectangleBox.y}
                width={draftRectangleBox.width}
                height={draftRectangleBox.height}
                fill={omiChartColors.marketUp}
                opacity={0.06}
                stroke={omiChartColors.marketUp}
                strokeWidth={1.5}
                strokeDasharray="5 4"
                pointerEvents="none"
              />
            ) : draftPriceRangeBox && projectedDraftDrawing.measurementStats ? (
              <g pointerEvents="none">
                <rect
                  x={draftPriceRangeBox.x}
                  y={draftPriceRangeBox.y}
                  width={draftPriceRangeBox.width}
                  height={draftPriceRangeBox.height}
                  fill={measurementToneColor(projectedDraftDrawing.measurementStats.tone)}
                  opacity={0.08}
                  stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)}
                  strokeWidth={1.5}
                  strokeDasharray="5 4"
                />
                <g
                  transform={`translate(${Math.max(
                    8,
                    Math.min(draftPriceRangeBox.x + draftPriceRangeBox.width + 8, overlaySize.width - 132)
                  )}, ${Math.max(18, Math.min(draftPriceRangeBox.y + 8, overlaySize.height - 40))})`}
                >
                  <rect width={124} height={24} rx={3} fill={omiChartColors.surface} stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)} opacity={0.94} />
                  <text x={10} y={16} className="fill-omi-text text-[10px] font-bold tabular-nums">
                    {projectedDraftDrawing.measurementStats.priceDiffLabel} ({projectedDraftDrawing.measurementStats.percentLabel})
                  </text>
                </g>
              </g>
            ) : projectedDraftDrawing.type === "fibonacci" && projectedDraftDrawing.fibonacciLevels ? (
              <g pointerEvents="none">
                {projectedDraftDrawing.fibonacciLevels.map((level) => (
                  <line
                    key={`draft-fib-${level.ratio}`}
                    x1={0}
                    y1={level.y}
                    x2={overlaySize.width}
                    y2={level.y}
                    stroke={omiChartColors.marketUp}
                    strokeWidth={1.25}
                    strokeDasharray="5 4"
                    opacity={0.7}
                  />
                ))}
              </g>
            ) : projectedDraftDrawing.type === "measure" && projectedDraftDrawing.measurementStats ? (
              <g pointerEvents="none">
                <line
                  x1={projectedDraftDrawing.points[0].x}
                  y1={projectedDraftDrawing.points[0].y}
                  x2={projectedDraftDrawing.points[1].x}
                  y2={projectedDraftDrawing.points[1].y}
                  stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)}
                  strokeWidth={1.5}
                  strokeDasharray="5 4"
                />
                <g
                  transform={`translate(${Math.max(
                    8,
                    Math.min(
                      (projectedDraftDrawing.points[0].x + projectedDraftDrawing.points[1].x) / 2 + 10,
                      overlaySize.width - 150
                    )
                  )}, ${Math.max(
                    18,
                    Math.min(
                      (projectedDraftDrawing.points[0].y + projectedDraftDrawing.points[1].y) / 2 - 22,
                      overlaySize.height - 40
                    )
                  )})`}
                >
                  <rect width={142} height={24} rx={3} fill={omiChartColors.surface} stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)} opacity={0.94} />
                  <text x={10} y={16} className="fill-omi-text text-[10px] font-bold tabular-nums">
                    {projectedDraftDrawing.measurementStats.priceDiffLabel} ({projectedDraftDrawing.measurementStats.percentLabel})
                  </text>
                </g>
              </g>
            ) : (
              <line
                x1={projectedDraftDrawing.points[0].x}
                y1={projectedDraftDrawing.points[0].y}
                x2={projectedDraftDrawing.points[1].x}
                y2={projectedDraftDrawing.points[1].y}
                stroke={omiChartColors.marketUp}
                strokeWidth={1.5}
                strokeDasharray="5 4"
                pointerEvents="none"
              />
            )
          ) : null}
          {snapCoordinate ? (
            <circle
              cx={snapCoordinate.x}
              cy={snapCoordinate.y}
              r={5}
              fill={omiChartColors.marketUp}
              stroke={omiChartColors.surface}
              strokeWidth={2}
              pointerEvents="none"
            />
          ) : null}
          {drawingTool !== "cursor" ? (
            <g transform="translate(12, 12)" pointerEvents="none">
              <rect width={drawingModeBadgeWidth(drawingTool)} height={24} rx={3} fill={omiChartColors.text} opacity={0.92} />
              <text x={12} y={16} className="fill-omi-surface text-[11px] font-bold">
                {drawingToolModeLabel(drawingTool)}
              </text>
            </g>
          ) : null}
        </svg>
      </div>
      <div className="border-t border-omi-border-subtle px-4 py-1.5 text-right text-[10px] text-omi-text-subtle">
        Chart engine:{" "}
        <a
          href="https://www.tradingview.com/"
          target="_blank"
          rel="noreferrer"
          className="font-medium text-omi-text-muted hover:text-omi-text"
        >
          TradingView Lightweight Charts
        </a>
      </div>
    </div>
  );
}

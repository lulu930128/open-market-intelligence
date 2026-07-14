"use client";

import ChartStaticIndicatorLayer from "@/components/chart/ChartStaticIndicatorLayer";
import ProfessionalChartHeader from "@/components/chart/ProfessionalChartHeader";
import SelectedDrawingMetricsCard from "@/components/chart/SelectedDrawingMetricsCard";
import ChartDrawingLayer from "@/components/chart/lightweight-chart/ChartDrawingLayer";
import { useChartDrawingInteraction } from "@/components/chart/lightweight-chart/useChartDrawingInteraction";
import { useLightweightChartEngine } from "@/components/chart/lightweight-chart/useLightweightChartEngine";
import type { ChartPoint } from "@/types/market";
import {
  type LineData,
  type Logical,
  type Time,
} from "lightweight-charts";
import {
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
  DrawingCoordinate,
  LightweightKLineChartProps,
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
  attachDrawingAnalytics,
  buildDrawingDerivedMetrics,
  buildDrawingOmiSummary,
  buildFibonacciLevels,
  buildMeasurementStats,
  buildRiskRewardStats,
  chartPointTypicalPrice,
  chartPointVolume,
  chartTime,
  defaultLightweightParameters,
  detectCandlestickPattern,
  drawingTimeFromChartTime,
  drawingTypeLabel,
  emptyDrawings,
  emptyIndicatorData,
  extendRayToViewport,
  finiteNumber,
  formatCompactVolume,
  formatDrawingPrice,
  isTwoPointDrawingTool,
  preserveEmptyProjection,
  rectangleBounds,
} from "@/components/chart/LightweightKLineChartDrawing";
import {
  buildSeriesData,
  calculateDmi,
  calculateDonchian,
  calculateEma,
  calculateMacd,
  calculateRsi,
  mergeIndicators,
  movingAverage,
} from "@/components/chart/LightweightKLineChartIndicators";
import { StateSurface } from "@/components/LoadingPlaceholders";
import { useI18n } from "@/i18n";
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

  const baseTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  if (document.documentElement.dataset.contrast === "high") {
    return baseTheme === "dark" ? "dark-high-contrast" : "light-high-contrast";
  }

  return baseTheme;
}

function parseHexColor(color: string): [number, number, number] | null {
  const normalized = color.trim();
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(normalized);

  if (!match) return null;

  const hex = match[1];
  const expanded =
    hex.length === 3
      ? hex
          .split("")
          .map((character) => `${character}${character}`)
          .join("")
      : hex;

  return [
    Number.parseInt(expanded.slice(0, 2), 16),
    Number.parseInt(expanded.slice(2, 4), 16),
    Number.parseInt(expanded.slice(4, 6), 16),
  ];
}

function colorChannelLuminance(channel: number) {
  const value = channel / 255;

  return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function colorLuminance(color: string) {
  const rgb = parseHexColor(color);

  if (!rgb) return null;

  return (
    colorChannelLuminance(rgb[0]) * 0.2126 +
    colorChannelLuminance(rgb[1]) * 0.7152 +
    colorChannelLuminance(rgb[2]) * 0.0722
  );
}

function colorContrastRatio(foreground: string, background: string) {
  const foregroundLuminance = colorLuminance(foreground);
  const backgroundLuminance = colorLuminance(background);

  if (foregroundLuminance === null || backgroundLuminance === null) return null;

  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);

  return (lighter + 0.05) / (darker + 0.05);
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
  volumePanelLabel,
  volumeValueKey = "volume",
  drawingTool = "cursor",
  drawings = emptyDrawings,
  selectedDrawingId = null,
  drawingContext,
  onDrawingsChange,
  onDrawingStateChange,
  onSelectedDrawingChange,
}: LightweightKLineChartProps) {
  const { locale, t } = useI18n();
  const drawingI18n = useMemo(() => ({ locale, t }), [locale, t]);
  const resolvedVolumePanelLabel = volumePanelLabel ?? t("chart.kline.volumeLots");
  const overlaySvgRef = useRef<SVGSVGElement | null>(null);
  const shortcutActiveRef = useRef(false);
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
  const selectedDrawingColor = omiChartColors.drawing.selected;
  const hoveredDrawingColor = omiChartColors.drawing.hovered;
  const drawingHandleBorderColor = omiChartColors.drawing.handleBorder;
  const themeDrawingDefaultColor = useCallback(
    (type: ChartDrawing["type"]) => {
      if (type === "anchorVwap") return omiChartColors.drawing.anchorVwap;
      if (type === "volumeProfileRange") return omiChartColors.drawing.volumeProfileRange;
      if (type === "priceRange") return omiChartColors.drawing.priceRange;
      if (type === "riskReward") return omiChartColors.warning;
      if (type === "measure") return omiChartColors.drawing.measure;
      if (type === "rectangle") return omiChartColors.drawing.rectangle;
      if (type === "fibonacci") return omiChartColors.drawing.fibonacci;
      if (type === "ray") return omiChartColors.drawing.ray;

      return omiChartColors.drawing.default;
    },
    [omiChartColors]
  );
  const readableDrawingColor = useCallback(
    (color: string, type: ChartDrawing["type"]) => {
      const contrastRatio = colorContrastRatio(color, omiChartColors.surface);

      if (contrastRatio !== null && contrastRatio < 2.4) {
        return themeDrawingDefaultColor(type);
      }

      return color;
    },
    [omiChartColors.surface, themeDrawingDefaultColor]
  );
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
    return [
      timeMode,
      drawingContext?.market ?? "",
      drawingContext?.symbol ?? label,
      drawingContext?.timeframe ?? label,
      volumeValueKey,
    ].join(":");
  }, [
    drawingContext?.market,
    drawingContext?.symbol,
    drawingContext?.timeframe,
    label,
    timeMode,
    volumeValueKey,
  ]);
  const {
    applyChartPointerInteractivity,
    beginChartInteraction,
    chartRef,
    containerRef,
    endChartInteraction,
    getVisibleLogicalRange,
    mainSeriesRef,
    overlayRevision,
    overlaySize,
    rememberVisibleLogicalRange,
    resetVisibleLogicalRangeToLatest,
    restoreChartPointerInteractivity,
    restoreVisibleLogicalRange,
    updateVisibleLogicalRange,
  } = useLightweightChartEngine({
    activeIndicators,
    benchmarkLabel,
    chartSeriesKey,
    chartStyle,
    drawingTool,
    height,
    maColors,
    omiChartColors,
    params,
    resolvedVolumePanelLabel,
    seriesData,
    timeMode,
  });

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
      attachDrawingAnalytics(
        drawing,
        chartDataTimeIndex,
        activeDrawingContext,
        chartData,
        drawingI18n
      ),
    [activeDrawingContext, chartData, chartDataTimeIndex, drawingI18n]
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
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme", "data-contrast"] });
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
  }, [chartRef, mainSeriesRef, timeMode]);

  const riskRewardPointToCoordinate = useCallback(
    (point: ChartDrawingPoint, fallbackX?: number): DrawingCoordinate | null => {
      const chart = chartRef.current;
      const series = mainSeriesRef.current;

      if (!chart || !series) return null;

      const logicalX =
        Number.isFinite(point.logical)
          ? chart.timeScale().logicalToCoordinate(point.logical as Logical)
          : null;
      const timeX = chart.timeScale().timeToCoordinate(chartTime(point.time, timeMode));
      const x = logicalX ?? timeX ?? fallbackX ?? null;
      const y = series.priceToCoordinate(point.price);

      if (x === null || y === null) return null;

      return { x, y };
    },
    [chartRef, mainSeriesRef, timeMode]
  );

  const priceToCoordinateY = useCallback((price: number): number | null => {
    const series = mainSeriesRef.current;

    if (!series || !Number.isFinite(price)) return null;

    return series.priceToCoordinate(price);
  }, [mainSeriesRef]);

  const linePointToCoordinate = useCallback((point: LineData<Time>): DrawingCoordinate | null => {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;

    if (!chart || !series) return null;

    const x = chart.timeScale().timeToCoordinate(point.time);
    const y = series.priceToCoordinate(point.value);

    if (x === null || y === null) return null;

    return { x, y };
  }, [chartRef, mainSeriesRef]);

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
  }, [chartData, chartDataTimeIndex, chartRef, mainSeriesRef, timeMode]);

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
  }, [mainSeriesRef]);

  const visibleChartPointEntries = useCallback(() => {
    const chart = chartRef.current;

    if (!chart || chartData.length === 0) return [];

    const range = getVisibleLogicalRange();
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
  }, [chartData, chartRef, getVisibleLogicalRange, timeMode]);

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
          volumeLabel: formatCompactVolume(bin.total, drawingI18n),
          poc: bin.total === maxTotal,
        },
      ];
    });
  }, [
    overlaySize.height,
    overlaySize.width,
    drawingI18n,
    mainSeriesRef,
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
  }, [chartData, mainSeriesRef, overlaySize.height, overlaySize.width, params.gapMinPct, visibleChartPointEntries]);

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
    mainSeriesRef,
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
          projectSignal(
            `signal-${point.time}-ema-up`,
            point,
            bullishPrice,
            t("chart.technicalSignals.emaBullishCross"),
            "bullish"
          );
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
            t("chart.technicalSignals.emaBearishCross"),
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
            t("chart.technicalSignals.macdBullish"),
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
            t("chart.technicalSignals.macdBearish"),
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
            t("chart.technicalSignals.channelBreakout"),
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
            t("chart.technicalSignals.channelBreakdown"),
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
            t("chart.technicalSignals.volumeBreakout"),
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
            t("chart.technicalSignals.trendForming"),
            "neutral"
          );
        }
      });
    }

    if (activeIndicators.candlestickPatterns) {
      entries.forEach(({ point, index }) => {
        const pattern = detectCandlestickPattern(point, chartData[index - 1], drawingI18n);

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
            rsiBullish && macdBullish
              ? t("chart.technicalSignals.rsiMacdBullishDivergence")
              : rsiBullish
                ? t("chart.technicalSignals.rsiBullishDivergence")
                : t("chart.technicalSignals.macdBullishDivergence"),
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
            rsiBearish && macdBearish
              ? t("chart.technicalSignals.rsiMacdBearishDivergence")
              : rsiBearish
                ? t("chart.technicalSignals.rsiBearishDivergence")
                : t("chart.technicalSignals.macdBearishDivergence"),
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
    chartRef,
    drawingI18n,
    mainSeriesRef,
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
    t,
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
  }, [chartData, chartRef, timeMode]);

  const drawingLogicalFromCoordinateX = useCallback((coordinateX: number) => {
    const chart = chartRef.current;

    if (!chart) return null;

    const logical = chart.timeScale().coordinateToLogical(coordinateX);

    return logical !== null && Number.isFinite(Number(logical)) ? Number(logical) : null;
  }, [chartRef]);

  const coordinateToDrawingPoint = useCallback((coordinate: DrawingCoordinate): ChartDrawingPoint | null => {
    const series = mainSeriesRef.current;

    if (!series) return null;

    const time = drawingTimeFromCoordinateX(coordinate.x);
    const logical = drawingLogicalFromCoordinateX(coordinate.x);
    const price = series.coordinateToPrice(coordinate.y);

    if (time === null || price === null || !Number.isFinite(price)) return null;

    return { time, price, logical: logical ?? undefined };
  }, [drawingLogicalFromCoordinateX, drawingTimeFromCoordinateX, mainSeriesRef]);


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

  const {
    activeDrawings,
    draftAnchor,
    dragPreviewDrawings,
    finishDrawingDrag,
    handleChartSelectionPointerDown,
    handleDrawingContextMenu,
    handleDrawingOverlayPointerLeave,
    handleDrawingPointerDown,
    handleDrawingPointerEnter,
    handleDrawingPointerLeave,
    handleDrawingPointerMove,
    hoverAnchor,
    hoveredDrawingId,
    snapCoordinate,
    startDrawingDrag,
  } = useChartDrawingInteraction({
    applyChartPointerInteractivity,
    attachActiveDrawingAnalytics,
    attachActiveDrawingsAnalytics,
    beginChartInteraction,
    chartData,
    chartRef,
    coordinateToDrawingPoint,
    drawingLogicalFromCoordinateX,
    drawingPointToCoordinate,
    drawings,
    drawingTimeFromCoordinateX,
    drawingTool,
    endChartInteraction,
    mainSeriesRef,
    onDrawingsChange,
    onDrawingStateChange,
    onSelectedDrawingChange,
    overlaySvgRef,
    projectedDrawings,
    rememberVisibleLogicalRange,
    restoreChartPointerInteractivity,
    restoreVisibleLogicalRange,
    selectedDrawingId,
    themeDrawingDefaultColor,
    timeMode,
  });

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
  }, [containerRef, resetVisibleLogicalRangeToLatest, updateVisibleLogicalRange]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const nextDrawings = activeDrawings.flatMap((drawing): ProjectedDrawing[] => {
        if (drawing.type === "horizontal") {
          const point = drawing.points[0];
          const y = point ? priceToCoordinateY(point.price) : null;

          if (!point || y === null) return [];

          return [
            {
              drawing,
              label: formatDrawingPrice(point.price),
              points: [
                { x: 0, y },
                { x: overlaySize.width, y },
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

        if (drawing.type === "riskReward") {
          const entryPoint = drawing.points[0];
          const targetPoint = drawing.points[1];
          const stopPoint = drawing.points[2];
          const entry = entryPoint ? drawingPointToCoordinate(entryPoint) : null;
          const target = targetPoint
            ? riskRewardPointToCoordinate(targetPoint, entry ? entry.x + 120 : undefined)
            : null;
          const stop = stopPoint
            ? riskRewardPointToCoordinate(stopPoint, target?.x ?? (entry ? entry.x + 120 : undefined))
            : null;

          if (!entryPoint || !targetPoint || !stopPoint || !entry || !target || !stop) return [];

          return [
            {
              drawing,
              label: t("chart.drawingTools.riskReward"),
              points: [entry, target, stop],
              anchorPoints: [entry, target, stop],
              riskRewardStats: buildRiskRewardStats(entryPoint, targetPoint, stopPoint),
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
              label: t("chart.drawingTools.measure"),
              points: [first, second],
              anchorPoints: [first, second],
              measurementStats: buildMeasurementStats(
                drawing.points[0],
                drawing.points[1],
                chartDataTimeIndex,
                drawingI18n
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
                  ? buildMeasurementStats(draftAnchor, hoverAnchor, chartDataTimeIndex, drawingI18n)
                  : undefined,
            };
      }

      if (drawingTool === "riskReward" && draftAnchor && hoverAnchor) {
        const entryPoint = drawingPointToCoordinate(draftAnchor);
        const widthPoint = riskRewardPointToCoordinate(
          hoverAnchor,
          entryPoint ? entryPoint.x + 120 : undefined
        );

        if (entryPoint && widthPoint) {
          nextDraftDrawing = {
            type: "riskReward",
            points: [entryPoint, widthPoint],
            anchorPoints: [entryPoint, widthPoint],
          };
        }
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
    riskRewardPointToCoordinate,
    activeDrawings,
    buildAnchoredVwapProjection,
    buildIchimokuCloudPolygons,
    buildVolumeProfileRangeProjection,
    draftAnchor,
    drawingI18n,
    drawingTool,
    hoverAnchor,
    overlayRevision,
    overlaySize.height,
    overlaySize.width,
    priceToCoordinateY,
    t,
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


  if (seriesData.candles.length === 0) {
    return (
      <div className="border-t border-omi-border-subtle bg-omi-surface p-4">
        <StateSurface
          title={t("chart.kline.empty")}
          tone="empty"
          className="h-[488px]"
        />
      </div>
    );
  }

  const shouldCaptureDrawingPointer =
    drawingTool !== "cursor" || Boolean(draftAnchor || dragPreviewDrawings);
  const selectedProjectedDrawing =
    selectedDrawingId === null
      ? null
      : projectedDrawings.find((item) => item.drawing.id === selectedDrawingId) ?? null;
  const selectedDrawingMetrics = selectedProjectedDrawing
    ? buildDrawingDerivedMetrics(
        selectedProjectedDrawing.drawing.type,
        selectedProjectedDrawing.drawing.points,
        chartDataTimeIndex,
        chartData,
        drawingI18n
      )
    : null;
  const selectedDrawingSummary =
    selectedProjectedDrawing && selectedDrawingMetrics
      ? buildDrawingOmiSummary(
          selectedProjectedDrawing.drawing,
          selectedDrawingMetrics,
          activeDrawingContext,
          drawingI18n
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
          volumePanelLabel={resolvedVolumePanelLabel}
        />
      ) : null}

      <div
        data-testid="lightweight-kline-chart"
        data-drawing-count={activeDrawings.length}
        data-drawing-tool={drawingTool}
        data-selected-drawing-id={selectedDrawingId ?? ""}
        className="relative min-h-[520px] w-full overflow-hidden"
        onPointerEnter={() => {
          shortcutActiveRef.current = true;
        }}
        onPointerLeave={() => {
          shortcutActiveRef.current = false;
        }}
        onPointerDown={() => {
          beginChartInteraction();
          containerRef.current?.focus({ preventScroll: true });
        }}
        onPointerDownCapture={(event) => {
          shortcutActiveRef.current = true;
          handleChartSelectionPointerDown(event);
        }}
        style={{
          height: fillViewport ? "max(620px, calc(100vh - 132px))" : height,
        }}
      >
        <div ref={containerRef} tabIndex={0} className="absolute inset-0 outline-none" />
        {selectedProjectedDrawing && selectedDrawingMetrics ? (
          <SelectedDrawingMetricsCard
            drawingType={drawingTypeLabel(selectedProjectedDrawing.drawing.type, drawingI18n)}
            metrics={selectedDrawingMetrics}
            summaryText={selectedDrawingSummary?.text ?? null}
          />
        ) : null}
        <svg
          ref={overlaySvgRef}
          data-testid="lightweight-chart-overlay"
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
          onPointerLeave={handleDrawingOverlayPointerLeave}
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
          <ChartDrawingLayer
            drawingHandleBorderColor={drawingHandleBorderColor}
            drawingI18n={drawingI18n}
            drawingTool={drawingTool}
            handleDrawingContextMenu={handleDrawingContextMenu}
            handleDrawingPointerEnter={handleDrawingPointerEnter}
            handleDrawingPointerLeave={handleDrawingPointerLeave}
            hoveredDrawingColor={hoveredDrawingColor}
            hoveredDrawingId={hoveredDrawingId}
            omiChartColors={omiChartColors}
            overlaySize={overlaySize}
            projectedDraftDrawing={projectedDraftDrawing}
            projectedDrawings={projectedDrawings}
            readableDrawingColor={readableDrawingColor}
            selectedDrawingColor={selectedDrawingColor}
            selectedDrawingId={selectedDrawingId}
            snapCoordinate={snapCoordinate}
            startDrawingDrag={startDrawingDrag}
            t={t}
          />
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

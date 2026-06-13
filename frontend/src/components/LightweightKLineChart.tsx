"use client";

import type { IndicatorParameters, IndicatorSettings } from "@/components/StockKLineChart";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type Logical,
  type LineData,
  type LogicalRange,
  type Time,
  type TickMarkType,
  type UTCTimestamp,
  type WhitespaceData,
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

export type ChartTimeMode = "date" | "intraday";
type ChartDisplayStyle = "candlestick" | "line";
type BusinessDayTime = Extract<Time, { year: number; month: number; day: number }>;
type ChartTimeParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
};

type Props = {
  chartData: ChartPoint[];
  indicatorData?: StockIndicatorPoint[];
  label: string;
  height?: number;
  fillViewport?: boolean;
  timeMode?: ChartTimeMode;
  chartStyle?: ChartDisplayStyle;
  showHeader?: boolean;
  showMovingAverages?: boolean;
  indicators?: IndicatorSettings;
  indicatorParameters?: IndicatorParameters;
  benchmarkData?: ChartPoint[];
  benchmarkLabel?: string;
  volumePanelLabel?: string;
  volumeValueKey?: "volume" | "trade_value";
  drawingTool?: ChartDrawingTool;
  drawings?: ChartDrawing[];
  selectedDrawingId?: string | null;
  drawingContext?: Omit<ChartDrawingContext, "label" | "timeMode" | "updatedAt">;
  onDrawingsChange?: (drawings: ChartDrawing[]) => void;
  onDrawingStateChange?: (drawings: ChartDrawing[], selectedDrawingId: string | null) => void;
  onSelectedDrawingChange?: (drawingId: string | null) => void;
};

export type ChartDrawingTool =
  | "cursor"
  | "horizontal"
  | "trend"
  | "ray"
  | "rectangle"
  | "fibonacci"
  | "anchorVwap"
  | "volumeProfileRange"
  | "measure"
  | "priceRange";

type ChartDrawingType = Exclude<ChartDrawingTool, "cursor">;

export type ChartDrawingPoint = {
  time: string;
  price: number;
};

export type ChartDrawingContext = {
  symbol?: string | null;
  market?: string | null;
  timeframe?: string | null;
  label?: string | null;
  timeMode?: ChartTimeMode;
  updatedAt?: string;
};

export type ChartDrawingDerivedMetrics = {
  version: 1;
  anchorCount: number;
  startTime: string | null;
  endTime: string | null;
  startPrice: number | null;
  endPrice: number | null;
  highPrice: number | null;
  lowPrice: number | null;
  midPrice: number | null;
  priceDiff: number | null;
  priceDiffAbs: number | null;
  percentChange: number | null;
  rangePct: number | null;
  barCount: number | null;
  durationDays: number | null;
  durationMinutes: number | null;
  slopePerBar: number | null;
  slopePctPerBar: number | null;
  direction: "up" | "down" | "flat" | "unknown";
  lineAnalysis?: ChartDrawingLineAnalysis | null;
  zoneAnalysis?: ChartDrawingZoneAnalysis | null;
  fibonacciAnalysis?: ChartDrawingFibonacciAnalysis | null;
  anchoredVwapAnalysis?: ChartDrawingAnchoredVwapAnalysis | null;
  volumeProfileAnalysis?: ChartDrawingVolumeProfileAnalysis | null;
  labels: {
    priceDiff: string;
    percentChange: string;
    rangePct: string;
    bars: string | null;
    duration: string | null;
    high: string;
    low: string;
    mid: string;
    slope: string | null;
  };
};

export type ChartDrawingAnchoredVwapAnalysis = {
  version: 1;
  anchorTime: string | null;
  anchorPrice: number | null;
  latestTime: string | null;
  latestPrice: number | null;
  latestVwap: number | null;
  firstVwap: number | null;
  distance: number | null;
  distancePct: number | null;
  vwapChange: number | null;
  vwapChangePct: number | null;
  barCount: number | null;
  cumulativeVolume: number | null;
  cumulativeTypicalValue: number | null;
  status: "above_vwap" | "below_vwap" | "testing_vwap" | "unknown";
  labels: {
    status: string;
    vwap: string;
    distance: string;
    distancePct: string;
    vwapChange: string;
    vwapChangePct: string;
    barCount: string;
    cumulativeVolume: string;
  };
};

export type ChartDrawingVolumeProfileLevel = {
  index: number;
  priceMin: number;
  priceMax: number;
  centerPrice: number;
  buyVolume: number;
  sellVolume: number;
  totalVolume: number;
  totalPct: number;
  inValueArea: boolean;
  isPoc: boolean;
  label: string;
  volumeLabel: string;
};

export type ChartDrawingVolumeProfileAnalysis = {
  version: 1;
  rowCount: number;
  startTime: string | null;
  endTime: string | null;
  priceHigh: number | null;
  priceLow: number | null;
  totalVolume: number | null;
  buyVolume: number | null;
  sellVolume: number | null;
  pocPrice: number | null;
  pocVolume: number | null;
  valueAreaHigh: number | null;
  valueAreaLow: number | null;
  valueAreaVolumePct: number | null;
  latestPrice: number | null;
  latestPosition: "above_value_area" | "inside_value_area" | "below_value_area" | "unknown";
  imbalancePct: number | null;
  levels: ChartDrawingVolumeProfileLevel[];
  labels: {
    totalVolume: string;
    poc: string;
    valueArea: string;
    valueAreaVolumePct: string;
    latestPosition: string;
    imbalance: string;
  };
};

export type ChartDrawingFibonacciLevel = {
  ratio: number;
  kind: "anchor" | "retracement" | "extension";
  price: number;
  distance: number | null;
  distancePct: number | null;
  isNearest: boolean;
  label: string;
  priceLabel: string;
  distanceLabel: string;
  distancePctLabel: string;
};

export type ChartDrawingFibonacciAnalysis = {
  version: 1;
  trend: "upswing" | "downswing" | "flat" | "unknown";
  status: "inside_range" | "above_anchor" | "below_anchor" | "near_level" | "unknown";
  anchorStartPrice: number | null;
  anchorEndPrice: number | null;
  anchorHighPrice: number | null;
  anchorLowPrice: number | null;
  latestPrice: number | null;
  latestTime: string | null;
  range: number | null;
  positionPct: number | null;
  rangePositionPct: number | null;
  extensionPct: number | null;
  nearestRatio: number | null;
  nearestPrice: number | null;
  nearestDistance: number | null;
  nearestDistancePct: number | null;
  tolerance: number | null;
  levels: ChartDrawingFibonacciLevel[];
  labels: {
    trend: string;
    status: string;
    range: string;
    position: string;
    rangePosition: string;
    extension: string;
    nearest: string;
    nearestDistance: string;
    nearestDistancePct: string;
    tolerance: string;
  };
};

export type ChartDrawingOmiSummary = {
  title: string;
  text: string;
  tags: string[];
  facts: Record<string, string | number | null>;
};

export type ChartDrawingLineAnalysis = {
  version: 1;
  kind: "horizontal" | "trend";
  role: "support" | "resistance" | "neutral" | "unknown";
  status:
    | "testing"
    | "above"
    | "below"
    | "breakout"
    | "breakdown"
    | "retest_support"
    | "retest_resistance"
    | "unknown";
  levelPrice: number | null;
  projectedPrice: number | null;
  latestPrice: number | null;
  latestTime: string | null;
  distance: number | null;
  distancePct: number | null;
  tolerance: number | null;
  touchCount: number | null;
  lastTouchTime: string | null;
  lastCrossTime: string | null;
  labels: {
    role: string;
    status: string;
    level: string;
    distance: string;
    distancePct: string;
    tolerance: string;
    touchCount: string;
    lastTouch: string;
  };
};

export type ChartDrawingZoneAnalysis = {
  version: 1;
  kind: "rectangle" | "price_range";
  role: "support_zone" | "resistance_zone" | "range" | "unknown";
  status:
    | "inside_zone"
    | "above_zone"
    | "below_zone"
    | "breakout_up"
    | "breakdown_down"
    | "testing_upper"
    | "testing_lower"
    | "unknown";
  upperPrice: number | null;
  lowerPrice: number | null;
  midPrice: number | null;
  latestPrice: number | null;
  latestTime: string | null;
  width: number | null;
  widthPct: number | null;
  positionPct: number | null;
  distanceToUpper: number | null;
  distanceToLower: number | null;
  tolerance: number | null;
  upperTouchCount: number | null;
  lowerTouchCount: number | null;
  lastUpperTouchTime: string | null;
  lastLowerTouchTime: string | null;
  compressionRatio: number | null;
  compressionState: "compressing" | "expanding" | "neutral" | "unknown";
  labels: {
    role: string;
    status: string;
    upper: string;
    lower: string;
    mid: string;
    width: string;
    widthPct: string;
    position: string;
    distanceToUpper: string;
    distanceToLower: string;
    tolerance: string;
    upperTouches: string;
    lowerTouches: string;
    compression: string;
  };
};

export type ChartDrawing = {
  id: string;
  type: ChartDrawingType;
  points: ChartDrawingPoint[];
  color: string;
  createdAt: string;
  context?: ChartDrawingContext;
  derivedMetrics?: ChartDrawingDerivedMetrics;
  omiSummary?: ChartDrawingOmiSummary;
};

const emptyIndicatorData: StockIndicatorPoint[] = [];
const emptyDrawings: ChartDrawing[] = [];

type PriceCoordinateApi = {
  coordinateToPrice: (coordinate: number) => number | null;
  priceToCoordinate: (price: number) => number | null;
};

type DrawingAnchor = {
  time: string;
  price: number;
};

type DrawingCoordinate = {
  x: number;
  y: number;
};

type ProjectedDrawing = {
  drawing: ChartDrawing;
  label: string;
  points: [DrawingCoordinate, DrawingCoordinate];
  anchorPoints?: [DrawingCoordinate, DrawingCoordinate];
  anchoredVwapLine?: DrawingCoordinate[];
  fibonacciLevels?: ProjectedFibonacciLevel[];
  volumeProfileBins?: ProjectedRangeVolumeProfileBin[];
  measurementStats?: ProjectedMeasurementStats;
};

type ProjectedDraftDrawing = {
  type: Exclude<ChartDrawingType, "horizontal">;
  points: [DrawingCoordinate, DrawingCoordinate];
  anchorPoints?: [DrawingCoordinate, DrawingCoordinate];
  fibonacciLevels?: ProjectedFibonacciLevel[];
  measurementStats?: ProjectedMeasurementStats;
};

type ProjectedFibonacciLevel = {
  ratio: number;
  y: number;
  label: string;
  priceLabel: string;
};

type ProjectedRangeVolumeProfileBin = {
  id: string;
  x: number;
  y: number;
  height: number;
  width: number;
  buyWidth: number;
  sellWidth: number;
  priceLabel: string;
  volumeLabel: string;
  poc: boolean;
  valueArea: boolean;
};

type ProjectedMeasurementStats = {
  tone: "up" | "down" | "flat";
  priceDiffLabel: string;
  percentLabel: string;
  barsLabel: string | null;
  highLabel: string;
  lowLabel: string;
};

type DrawingDragState = {
  drawingId: string;
  mode: "horizontal" | "point" | "line";
  pointIndex: 0 | 1;
  pointerId: number;
  startCoordinate?: DrawingCoordinate;
  originCoordinates?: DrawingCoordinate[];
  oppositeCoordinate?: DrawingCoordinate;
  visibleLogicalRange?: LogicalRange;
};

type PointerAnchor = DrawingAnchor & {
  x: number;
  y: number;
  snapped: boolean;
};

type PlotLineData = LineData<Time> | WhitespaceData<Time>;

type ProjectedCloudPolygon = {
  id: string;
  points: string;
  tone: "bullish" | "bearish";
};

type ProjectedVolumeProfileBin = {
  id: string;
  x: number;
  y: number;
  height: number;
  width: number;
  buyWidth: number;
  sellWidth: number;
  priceLabel: string;
  volumeLabel: string;
  poc: boolean;
};

type ProjectedGapZone = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  tone: "up" | "down";
  label: string;
};

type ProjectedSupportResistanceLevel = {
  id: string;
  y: number;
  priceLabel: string;
  tone: "support" | "resistance";
  strength: number;
  opacity: number;
};

type ProjectedTechnicalSignal = {
  id: string;
  x: number;
  y: number;
  anchorY: number;
  label: string;
  tone: "bullish" | "bearish" | "neutral";
  timeLabel: string;
  priceLabel: string;
  line?: [DrawingCoordinate, DrawingCoordinate];
};

type LineSeriesData = {
  maShort: LineData<Time>[];
  maMiddle: LineData<Time>[];
  maLong: LineData<Time>[];
  emaFast: LineData<Time>[];
  emaSlow: LineData<Time>[];
  wma: LineData<Time>[];
  hma: LineData<Time>[];
  vwma: LineData<Time>[];
  vwap: LineData<Time>[];
  psar: LineData<Time>[];
  bollingerUpper: LineData<Time>[];
  bollingerMiddle: LineData<Time>[];
  bollingerLower: LineData<Time>[];
  bbWidth: LineData<Time>[];
  stdDev: LineData<Time>[];
  choppiness: LineData<Time>[];
  donchianUpper: LineData<Time>[];
  donchianLower: LineData<Time>[];
  ichimokuConversion: LineData<Time>[];
  ichimokuBase: LineData<Time>[];
  ichimokuSpanA: LineData<Time>[];
  ichimokuSpanB: LineData<Time>[];
  ichimokuLagging: LineData<Time>[];
  supertrendUp: PlotLineData[];
  supertrendDown: PlotLineData[];
  keltnerUpper: LineData<Time>[];
  keltnerMiddle: LineData<Time>[];
  keltnerLower: LineData<Time>[];
  rsi: LineData<Time>[];
  macd: LineData<Time>[];
  macdSignal: LineData<Time>[];
  kdK: LineData<Time>[];
  kdD: LineData<Time>[];
  momentum: LineData<Time>[];
  tsi: LineData<Time>[];
  tsiSignal: LineData<Time>[];
  awesomeOscillator: LineData<Time>[];
  ultimateOscillator: LineData<Time>[];
  atr: LineData<Time>[];
  adx: LineData<Time>[];
  plusDi: LineData<Time>[];
  minusDi: LineData<Time>[];
  aroonUp: LineData<Time>[];
  aroonDown: LineData<Time>[];
  obv: LineData<Time>[];
  obvMa: LineData<Time>[];
  mfi: LineData<Time>[];
  cmf: LineData<Time>[];
  adLine: LineData<Time>[];
  pvt: LineData<Time>[];
  relativeStrength: LineData<Time>[];
  beta: LineData<Time>[];
  correlation: LineData<Time>[];
  cci: LineData<Time>[];
  williamsR: LineData<Time>[];
  roc: LineData<Time>[];
  stochRsiK: LineData<Time>[];
  stochRsiD: LineData<Time>[];
  trix: LineData<Time>[];
  trixSignal: LineData<Time>[];
  pivot: LineData<Time>[];
  pivotR1: LineData<Time>[];
  pivotS1: LineData<Time>[];
  support: LineData<Time>[];
  resistance: LineData<Time>[];
  gapUp: LineData<Time>[];
  gapDown: LineData<Time>[];
};

type BuiltSeriesData = {
  candles: CandlestickData<Time>[];
  line: LineData<Time>[];
  volumes: HistogramData<Time>[];
  macdHistogram: HistogramData<Time>[];
  lines: LineSeriesData;
};

const upColor = "#dc2626";
const downColor = "#059669";
const drawingSnapDistancePx = 14;
const DEFAULT_LIGHTWEIGHT_VISIBLE_BARS = 80;
const maColors = {
  maShort: "#2563eb",
  maMiddle: "#f59e0b",
  maLong: "#a855f7",
};

const defaultLightweightIndicators: IndicatorSettings = {
  signals: false,
  ma: true,
  ema: false,
  wma: false,
  hma: false,
  vwma: false,
  bollinger: false,
  bbWidth: false,
  stdDev: false,
  choppiness: false,
  vwap: false,
  psar: false,
  donchian: false,
  ichimoku: false,
  supertrend: false,
  keltner: false,
  volume: true,
  rsi: false,
  macd: false,
  kd: false,
  momentum: false,
  tsi: false,
  awesomeOscillator: false,
  ultimateOscillator: false,
  atr: false,
  adx: false,
  aroon: false,
  obv: false,
  mfi: false,
  cmf: false,
  adLine: false,
  pvt: false,
  cci: false,
  williamsR: false,
  roc: false,
  stochRsi: false,
  trix: false,
  volumeProfile: false,
  pivotPoints: false,
  supportResistance: false,
  gap: false,
  divergence: false,
  candlestickPatterns: false,
  relativeStrength: false,
  beta: false,
  correlation: false,
};

const defaultLightweightParameters: IndicatorParameters = {
  maShort: 5,
  maMiddle: 20,
  maLong: 60,
  emaFast: 12,
  emaSlow: 26,
  wmaPeriod: 20,
  hmaPeriod: 20,
  vwmaPeriod: 20,
  bollingerPeriod: 20,
  bollingerStdDev: 2,
  bbWidthPeriod: 20,
  stdDevPeriod: 20,
  choppinessPeriod: 14,
  volumeMa: 20,
  rsiPeriod: 14,
  macdFast: 12,
  macdSlow: 26,
  macdSignal: 9,
  kdPeriod: 9,
  momentumPeriod: 10,
  tsiShortPeriod: 13,
  tsiLongPeriod: 25,
  tsiSignalPeriod: 7,
  awesomeFastPeriod: 5,
  awesomeSlowPeriod: 34,
  ultimateShortPeriod: 7,
  ultimateMiddlePeriod: 14,
  ultimateLongPeriod: 28,
  atrPeriod: 14,
  adxPeriod: 14,
  donchianPeriod: 20,
  ichimokuConversionPeriod: 9,
  ichimokuBasePeriod: 26,
  ichimokuSpanBPeriod: 52,
  ichimokuDisplacement: 26,
  supertrendAtrPeriod: 10,
  supertrendMultiplier: 3,
  keltnerPeriod: 20,
  keltnerAtrPeriod: 10,
  keltnerMultiplier: 2,
  aroonPeriod: 25,
  obvMa: 10,
  mfiPeriod: 14,
  cmfPeriod: 20,
  cciPeriod: 20,
  williamsRPeriod: 14,
  rocPeriod: 12,
  stochRsiPeriod: 14,
  stochRsiSmoothK: 3,
  stochRsiSmoothD: 3,
  trixPeriod: 15,
  trixSignal: 9,
  volumeProfileRows: 24,
  pivotLookback: 1,
  supportResistanceLookback: 20,
  gapMinPct: 0.5,
  relativeStrengthLookback: 20,
  betaPeriod: 60,
  correlationPeriod: 60,
};

function finiteNumber(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

function pad2(value: number) {
  return String(value).padStart(2, "0");
}

function isBusinessDayTime(value: Time): value is BusinessDayTime {
  return typeof value === "object" && "year" in value && "month" in value && "day" in value;
}

function chartTimeParts(value: Time): ChartTimeParts | null {
  if (typeof value === "number") {
    const date = new Date(value * 1000);

    return {
      year: date.getUTCFullYear(),
      month: date.getUTCMonth() + 1,
      day: date.getUTCDate(),
      hour: date.getUTCHours(),
      minute: date.getUTCMinutes(),
    };
  }

  if (typeof value === "string") {
    const match = value.match(
      /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/
    );
    if (!match) return null;

    const [, year, month, day, hour = "0", minute = "0"] = match;
    return {
      year: Number(year),
      month: Number(month),
      day: Number(day),
      hour: Number(hour),
      minute: Number(minute),
    };
  }

  if (isBusinessDayTime(value)) {
    return {
      year: value.year,
      month: value.month,
      day: value.day,
      hour: 0,
      minute: 0,
    };
  }

  return null;
}

function formatChartDate(value: Time) {
  const parts = chartTimeParts(value);

  if (!parts) return null;

  return `${parts.year}/${pad2(parts.month)}/${pad2(parts.day)}`;
}

function formatChartDateTime(value: Time, timeMode: ChartTimeMode) {
  const parts = chartTimeParts(value);

  if (!parts) return "";

  const dateLabel = `${parts.year}/${pad2(parts.month)}/${pad2(parts.day)}`;

  if (timeMode === "date") return dateLabel;

  return `${dateLabel} ${pad2(parts.hour)}:${pad2(parts.minute)}`;
}

function chartTime(value: string, timeMode: ChartTimeMode): Time {
  if (timeMode === "date") return value.slice(0, 10);

  const wallClockMatch = value.match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/
  );
  if (wallClockMatch) {
    const [, year, month, day, hour, minute, second = "0"] = wallClockMatch;
    return Math.floor(
      Date.UTC(
        Number(year),
        Number(month) - 1,
        Number(day),
        Number(hour),
        Number(minute),
        Number(second)
      ) / 1000
    ) as UTCTimestamp;
  }

  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const hasExplicitZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(normalized);
  const date = new Date(hasExplicitZone ? normalized : `${normalized}+08:00`);
  const timestamp = date.getTime();

  if (Number.isNaN(timestamp)) return value.slice(0, 10);

  return Math.floor(timestamp / 1000) as UTCTimestamp;
}

function drawingTimeFromChartTime(value: Time, timeMode: ChartTimeMode) {
  const parts = chartTimeParts(value);

  if (!parts) return String(value);

  const dateLabel = `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`;

  if (timeMode === "date") return dateLabel;

  return `${dateLabel}T${pad2(parts.hour)}:${pad2(parts.minute)}:00`;
}

function formatDrawingPrice(value: number) {
  if (Math.abs(value) >= 1000) {
    return value.toLocaleString("zh-TW", {
      maximumFractionDigits: 2,
    });
  }

  return value.toLocaleString("zh-TW", {
    maximumFractionDigits: 2,
    minimumFractionDigits: value % 1 === 0 ? 0 : 2,
  });
}

function formatSignedDrawingPrice(value: number) {
  const sign = value > 0 ? "+" : "";

  return `${sign}${formatDrawingPrice(value)}`;
}

function formatDrawingPercent(value: number) {
  const sign = value > 0 ? "+" : "";

  return `${sign}${value.toFixed(2)}%`;
}

function formatDrawingRatioPercent(value: number | null) {
  if (!finiteNumber(value)) return "-";

  return formatDrawingPercent(value);
}

function parseDrawingTimeMs(value: string) {
  const normalized = value.includes("T") ? value : `${value}T00:00:00`;
  const hasExplicitZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(normalized);
  const date = new Date(hasExplicitZone ? normalized : `${normalized}+08:00`);
  const timestamp = date.getTime();

  return Number.isFinite(timestamp) ? timestamp : null;
}

function formatDurationLabel(days: number | null, minutes: number | null) {
  if (finiteNumber(days) && days >= 1) {
    return `${days.toLocaleString("zh-TW", { maximumFractionDigits: 1 })} 天`;
  }

  if (finiteNumber(minutes)) {
    if (minutes >= 60) {
      return `${(minutes / 60).toLocaleString("zh-TW", { maximumFractionDigits: 1 })} 小時`;
    }

    return `${minutes.toLocaleString("zh-TW", { maximumFractionDigits: 0 })} 分`;
  }

  return null;
}

function formatCompactVolume(value: number) {
  const absValue = Math.abs(value);

  if (absValue >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(2)}億`;
  }

  if (absValue >= 10_000) {
    return `${(value / 10_000).toFixed(1)}萬`;
  }

  return value.toLocaleString("zh-TW", {
    maximumFractionDigits: 0,
  });
}

function candleParts(point: ChartPoint) {
  if (
    !finiteNumber(point.open) ||
    !finiteNumber(point.high) ||
    !finiteNumber(point.low) ||
    !finiteNumber(point.close)
  ) {
    return null;
  }

  const body = Math.abs(point.close - point.open);
  const range = point.high - point.low;
  const upperWick = point.high - Math.max(point.open, point.close);
  const lowerWick = Math.min(point.open, point.close) - point.low;

  if (range <= 0) return null;

  return {
    bullish: point.close >= point.open,
    bearish: point.close < point.open,
    body,
    range,
    upperWick,
    lowerWick,
  };
}

function detectCandlestickPattern(
  point: ChartPoint,
  previous: ChartPoint | undefined
): { label: string; tone: ProjectedTechnicalSignal["tone"]; price: number } | null {
  const currentParts = candleParts(point);

  if (!currentParts || !finiteNumber(point.high) || !finiteNumber(point.low)) return null;

  const bodyRatio = currentParts.body / currentParts.range;

  if (previous && finiteNumber(previous.open) && finiteNumber(previous.close)) {
    if (
      previous.close < previous.open &&
      currentParts.bullish &&
      finiteNumber(point.open) &&
      finiteNumber(point.close) &&
      point.open <= previous.close &&
      point.close >= previous.open
    ) {
      return { label: "多方吞噬", tone: "bullish", price: point.low };
    }

    if (
      previous.close > previous.open &&
      currentParts.bearish &&
      finiteNumber(point.open) &&
      finiteNumber(point.close) &&
      point.open >= previous.close &&
      point.close <= previous.open
    ) {
      return { label: "空方吞噬", tone: "bearish", price: point.high };
    }
  }

  if (
    bodyRatio <= 0.34 &&
    currentParts.lowerWick >= Math.max(currentParts.body * 2, currentParts.range * 0.38) &&
    currentParts.upperWick <= Math.max(currentParts.body * 1.2, currentParts.range * 0.18)
  ) {
    return { label: currentParts.bullish ? "錘子" : "下影反轉", tone: "bullish", price: point.low };
  }

  if (
    bodyRatio <= 0.34 &&
    currentParts.upperWick >= Math.max(currentParts.body * 2, currentParts.range * 0.38) &&
    currentParts.lowerWick <= Math.max(currentParts.body * 1.2, currentParts.range * 0.18)
  ) {
    return { label: currentParts.bearish ? "流星" : "上影壓力", tone: "bearish", price: point.high };
  }

  if (bodyRatio <= 0.08) {
    return { label: "十字", tone: "neutral", price: finiteNumber(point.close) ? point.close : point.high };
  }

  return null;
}

function createDrawingId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `drawing-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function preserveEmptyProjection<T>(current: T[], next: T[]) {
  return current.length === 0 && next.length === 0 ? current : next;
}

function isTwoPointDrawingTool(
  value: ChartDrawingTool
): value is Exclude<ChartDrawingType, "horizontal"> {
  return (
    value === "trend" ||
    value === "ray" ||
    value === "rectangle" ||
    value === "fibonacci" ||
    value === "volumeProfileRange" ||
    value === "measure" ||
    value === "priceRange"
  );
}

function isTwoPointDrawingType(
  value: ChartDrawing["type"]
): value is Exclude<ChartDrawingType, "horizontal"> {
  return (
    value === "trend" ||
    value === "ray" ||
    value === "rectangle" ||
    value === "fibonacci" ||
    value === "volumeProfileRange" ||
    value === "measure" ||
    value === "priceRange"
  );
}

function drawingDefaultColor(type: ChartDrawing["type"]) {
  if (type === "anchorVwap") return "#0891b2";
  if (type === "volumeProfileRange") return "#475569";
  if (type === "priceRange") return "#64748b";
  if (type === "measure") return "#334155";
  if (type === "rectangle") return "#2563eb";
  if (type === "fibonacci") return "#7c3aed";
  if (type === "ray") return "#0f766e";

  return "#0f172a";
}

function drawingToolModeLabel(tool: ChartDrawingTool) {
  switch (tool) {
    case "horizontal":
      return "水平線模式";
    case "trend":
      return "趨勢線模式";
    case "ray":
      return "射線模式";
    case "rectangle":
      return "區間框模式";
    case "fibonacci":
      return "Fib 回撤模式";
    case "anchorVwap":
      return "錨定VWAP模式";
    case "volumeProfileRange":
      return "量價分布模式";
    case "measure":
      return "量測模式";
    case "priceRange":
      return "價幅%模式";
    default:
      return "";
  }
}

function drawingModeBadgeWidth(tool: ChartDrawingTool) {
  switch (tool) {
    case "anchorVwap":
      return 112;
    case "volumeProfileRange":
      return 126;
    case "fibonacci":
      return 106;
    case "priceRange":
      return 88;
    case "rectangle":
      return 94;
    case "horizontal":
      return 86;
    default:
      return 82;
  }
}

function measurementToneColor(tone: ProjectedMeasurementStats["tone"]) {
  if (tone === "up") return "#dc2626";
  if (tone === "down") return "#059669";

  return "#334155";
}

function medianFinite(values: number[]) {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);

  if (sorted.length === 0) return null;

  const middle = Math.floor(sorted.length / 2);

  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

function pointClose(point: ChartPoint | null | undefined) {
  if (!point) return null;
  if (finiteNumber(point.close)) return point.close;
  if (finiteNumber(point.open)) return point.open;

  return null;
}

function lineValueAtIndex(
  startPrice: number,
  endPrice: number,
  startIndex: number,
  endIndex: number,
  targetIndex: number
) {
  if (startIndex === endIndex) return endPrice;

  return startPrice + ((targetIndex - startIndex) / (endIndex - startIndex)) * (endPrice - startPrice);
}

function estimateLineAnalysisTolerance(chartData: ChartPoint[], referencePrice: number) {
  const recentRanges = chartData.slice(-120).flatMap((point) => {
    if (!finiteNumber(point.high) || !finiteNumber(point.low)) return [];
    const range = point.high - point.low;

    return range > 0 ? [range] : [];
  });
  const medianRange = medianFinite(recentRanges);
  const priceTolerance = Math.abs(referencePrice) * 0.003;
  const rangeTolerance = finiteNumber(medianRange) ? medianRange * 0.25 : 0;
  const rawTolerance = Math.max(priceTolerance, rangeTolerance, 0.01);
  const cap = Math.abs(referencePrice) > 0 ? Math.abs(referencePrice) * 0.02 : rawTolerance;

  return Math.min(rawTolerance, cap);
}

function candleTouchesPrice(point: ChartPoint, price: number, tolerance: number) {
  if (finiteNumber(point.high) && finiteNumber(point.low)) {
    return point.low - tolerance <= price && point.high + tolerance >= price;
  }

  const close = pointClose(point);

  return finiteNumber(close) ? Math.abs(close - price) <= tolerance : false;
}

function lineAnalysisRole(distance: number | null, tolerance: number | null): ChartDrawingLineAnalysis["role"] {
  if (!finiteNumber(distance) || !finiteNumber(tolerance)) return "unknown";
  if (Math.abs(distance) <= tolerance) return "neutral";

  return distance > 0 ? "support" : "resistance";
}

function lineAnalysisStatusLabel(status: ChartDrawingLineAnalysis["status"]) {
  switch (status) {
    case "testing":
      return "測試線位";
    case "above":
      return "站在線上";
    case "below":
      return "跌在線下";
    case "breakout":
      return "突破";
    case "breakdown":
      return "跌破";
    case "retest_support":
      return "回踩支撐";
    case "retest_resistance":
      return "反壓回測";
    default:
      return "資料不足";
  }
}

function lineAnalysisRoleLabel(role: ChartDrawingLineAnalysis["role"]) {
  switch (role) {
    case "support":
      return "支撐";
    case "resistance":
      return "壓力";
    case "neutral":
      return "測試中";
    default:
      return "未判定";
  }
}

function buildLineAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData: ChartPoint[] | undefined
): ChartDrawingLineAnalysis | null {
  if (type !== "horizontal" && type !== "trend" && type !== "ray") return null;
  if (!chartData || chartData.length === 0) return null;

  const first = points[0] ?? null;
  const second = points[1] ?? first;
  const firstIndex = first ? timeIndex.get(first.time) : undefined;
  const secondIndex = second ? timeIndex.get(second.time) : undefined;
  const latestIndex = chartData.length - 1;
  const latestPoint = chartData[latestIndex] ?? null;
  const previousPoint = latestIndex > 0 ? chartData[latestIndex - 1] : null;
  const latestPrice = pointClose(latestPoint);
  const previousPrice = pointClose(previousPoint);

  if (!first || !finiteNumber(first.price) || !latestPoint || !finiteNumber(latestPrice)) {
    return null;
  }

  const projectedPrice =
    type === "horizontal"
      ? first.price
      : finiteNumber(first.price) &&
          finiteNumber(second?.price) &&
          firstIndex !== undefined &&
          secondIndex !== undefined
        ? lineValueAtIndex(first.price, second.price, firstIndex, secondIndex, latestIndex)
        : null;

  if (!finiteNumber(projectedPrice)) return null;

  const previousProjectedPrice =
    type === "horizontal"
      ? first.price
      : finiteNumber(first.price) &&
          finiteNumber(second?.price) &&
          firstIndex !== undefined &&
          secondIndex !== undefined &&
          previousPoint
        ? lineValueAtIndex(first.price, second.price, firstIndex, secondIndex, latestIndex - 1)
        : null;
  const tolerance = estimateLineAnalysisTolerance(chartData, projectedPrice);
  const distance = latestPrice - projectedPrice;
  const distancePct = projectedPrice !== 0 ? (distance / projectedPrice) * 100 : null;
  const latestTouches = candleTouchesPrice(latestPoint, projectedPrice, tolerance);
  const previousDistance =
    finiteNumber(previousPrice) && finiteNumber(previousProjectedPrice)
      ? previousPrice - previousProjectedPrice
      : null;
  const role = lineAnalysisRole(distance, tolerance);
  let status: ChartDrawingLineAnalysis["status"] = "unknown";

  if (Math.abs(distance) <= tolerance || latestTouches) {
    status = "testing";
  }

  if (
    finiteNumber(previousDistance) &&
    previousDistance <= tolerance &&
    distance > tolerance
  ) {
    status = "breakout";
  } else if (
    finiteNumber(previousDistance) &&
    previousDistance >= -tolerance &&
    distance < -tolerance
  ) {
    status = "breakdown";
  } else if (distance > tolerance && latestTouches) {
    status = "retest_support";
  } else if (distance < -tolerance && latestTouches) {
    status = "retest_resistance";
  } else if (status === "unknown") {
    status = distance > 0 ? "above" : distance < 0 ? "below" : "testing";
  }

  let touchCount = 0;
  let inTouchCluster = false;
  let lastTouchTime: string | null = null;
  let lastCrossTime: string | null = null;
  let previousSign: -1 | 0 | 1 | null = null;

  chartData.forEach((point, index) => {
    const close = pointClose(point);
    const linePrice =
      type === "horizontal"
        ? first.price
        : finiteNumber(first.price) &&
            finiteNumber(second?.price) &&
            firstIndex !== undefined &&
            secondIndex !== undefined
          ? lineValueAtIndex(first.price, second.price, firstIndex, secondIndex, index)
          : null;

    if (!finiteNumber(linePrice) || !finiteNumber(close)) return;

    const pointDistance = close - linePrice;
    const sign =
      Math.abs(pointDistance) <= tolerance ? 0 : pointDistance > 0 ? 1 : -1;
    const touches = candleTouchesPrice(point, linePrice, tolerance);

    if (touches) {
      if (!inTouchCluster) {
        touchCount += 1;
      }
      inTouchCluster = true;
      lastTouchTime = point.time;
    } else {
      inTouchCluster = false;
    }

    if (
      previousSign !== null &&
      sign !== 0 &&
      previousSign !== 0 &&
      sign !== previousSign
    ) {
      lastCrossTime = point.time;
    }

    if (sign !== 0) {
      previousSign = sign;
    }
  });

  return {
    version: 1,
    kind: type === "horizontal" ? "horizontal" : "trend",
    role,
    status,
    levelPrice: type === "horizontal" ? first.price : null,
    projectedPrice,
    latestPrice,
    latestTime: latestPoint.time,
    distance,
    distancePct,
    tolerance,
    touchCount,
    lastTouchTime,
    lastCrossTime,
    labels: {
      role: lineAnalysisRoleLabel(role),
      status: lineAnalysisStatusLabel(status),
      level: formatDrawingPrice(projectedPrice),
      distance: formatSignedDrawingPrice(distance),
      distancePct: formatDrawingRatioPercent(distancePct),
      tolerance: `±${formatDrawingPrice(tolerance)}`,
      touchCount: `${touchCount.toLocaleString("zh-TW")} 次`,
      lastTouch: lastTouchTime ?? "-",
    },
  };
}

function zoneAnalysisRoleLabel(role: ChartDrawingZoneAnalysis["role"]) {
  switch (role) {
    case "support_zone":
      return "支撐帶";
    case "resistance_zone":
      return "壓力帶";
    case "range":
      return "區間內";
    default:
      return "未判定";
  }
}

function zoneAnalysisStatusLabel(status: ChartDrawingZoneAnalysis["status"]) {
  switch (status) {
    case "inside_zone":
      return "區間內";
    case "above_zone":
      return "站上區間";
    case "below_zone":
      return "跌破區間";
    case "breakout_up":
      return "向上突破";
    case "breakdown_down":
      return "向下跌破";
    case "testing_upper":
      return "測試上緣";
    case "testing_lower":
      return "測試下緣";
    default:
      return "資料不足";
  }
}

function zoneCompressionLabel(state: ChartDrawingZoneAnalysis["compressionState"]) {
  switch (state) {
    case "compressing":
      return "壓縮";
    case "expanding":
      return "擴張";
    case "neutral":
      return "一般";
    default:
      return "不足";
  }
}

function countBoundaryTouches(
  rows: ChartPoint[],
  price: number,
  tolerance: number
) {
  let count = 0;
  let inCluster = false;
  let lastTouchTime: string | null = null;

  rows.forEach((point) => {
    const touches = candleTouchesPrice(point, price, tolerance);

    if (touches) {
      if (!inCluster) {
        count += 1;
      }
      inCluster = true;
      lastTouchTime = point.time;
      return;
    }

    inCluster = false;
  });

  return { count, lastTouchTime };
}

function buildZoneAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData: ChartPoint[] | undefined
): ChartDrawingZoneAnalysis | null {
  if (type !== "rectangle" && type !== "priceRange") return null;
  if (!chartData || chartData.length === 0) return null;

  const first = points[0] ?? null;
  const second = points[1] ?? null;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const previousPoint = chartData.length > 1 ? chartData[chartData.length - 2] : null;
  const latestPrice = pointClose(latestPoint);
  const previousPrice = pointClose(previousPoint);

  if (!first || !second || !latestPoint || !finiteNumber(latestPrice)) return null;

  const upperPrice = Math.max(first.price, second.price);
  const lowerPrice = Math.min(first.price, second.price);
  const width = upperPrice - lowerPrice;

  if (!Number.isFinite(width) || width <= 0) return null;

  const midPrice = (upperPrice + lowerPrice) / 2;
  const widthPct = lowerPrice !== 0 ? (width / lowerPrice) * 100 : null;
  const positionPct = ((latestPrice - lowerPrice) / width) * 100;
  const distanceToUpper = latestPrice - upperPrice;
  const distanceToLower = latestPrice - lowerPrice;
  const tolerance = estimateLineAnalysisTolerance(chartData, midPrice);
  const previousAbove = finiteNumber(previousPrice) ? previousPrice > upperPrice + tolerance : false;
  const previousBelow = finiteNumber(previousPrice) ? previousPrice < lowerPrice - tolerance : false;
  let status: ChartDrawingZoneAnalysis["status"] = "unknown";

  if (latestPrice > upperPrice + tolerance) {
    status = previousAbove ? "above_zone" : "breakout_up";
  } else if (latestPrice < lowerPrice - tolerance) {
    status = previousBelow ? "below_zone" : "breakdown_down";
  } else if (Math.abs(latestPrice - upperPrice) <= tolerance) {
    status = "testing_upper";
  } else if (Math.abs(latestPrice - lowerPrice) <= tolerance) {
    status = "testing_lower";
  } else {
    status = "inside_zone";
  }

  const role: ChartDrawingZoneAnalysis["role"] =
    status === "above_zone" || status === "breakout_up"
      ? "support_zone"
      : status === "below_zone" || status === "breakdown_down"
        ? "resistance_zone"
        : "range";
  const firstIndex = first ? timeIndex.get(first.time) : undefined;
  const secondIndex = second ? timeIndex.get(second.time) : undefined;
  const fromIndex =
    firstIndex !== undefined && secondIndex !== undefined
      ? Math.max(0, Math.min(firstIndex, secondIndex))
      : 0;
  const rowsForTouches = chartData.slice(fromIndex);
  const upperTouches = countBoundaryTouches(rowsForTouches, upperPrice, tolerance);
  const lowerTouches = countBoundaryTouches(rowsForTouches, lowerPrice, tolerance);
  const recentRows = chartData.slice(-20);
  const recentHigh = Math.max(
    ...recentRows.flatMap((point) => (finiteNumber(point.high) ? [point.high] : []))
  );
  const recentLow = Math.min(
    ...recentRows.flatMap((point) => (finiteNumber(point.low) ? [point.low] : []))
  );
  const recentRange =
    Number.isFinite(recentHigh) && Number.isFinite(recentLow) ? recentHigh - recentLow : null;
  const compressionRatio =
    finiteNumber(recentRange) && width > 0 ? Math.max(0, recentRange / width) : null;
  const compressionState: ChartDrawingZoneAnalysis["compressionState"] =
    status === "breakout_up" || status === "breakdown_down"
      ? "expanding"
      : !finiteNumber(compressionRatio)
        ? "unknown"
        : status === "inside_zone" && compressionRatio <= 0.35
          ? "compressing"
          : compressionRatio >= 0.85
            ? "expanding"
            : "neutral";

  return {
    version: 1,
    kind: type === "priceRange" ? "price_range" : "rectangle",
    role,
    status,
    upperPrice,
    lowerPrice,
    midPrice,
    latestPrice,
    latestTime: latestPoint.time,
    width,
    widthPct,
    positionPct,
    distanceToUpper,
    distanceToLower,
    tolerance,
    upperTouchCount: upperTouches.count,
    lowerTouchCount: lowerTouches.count,
    lastUpperTouchTime: upperTouches.lastTouchTime,
    lastLowerTouchTime: lowerTouches.lastTouchTime,
    compressionRatio,
    compressionState,
    labels: {
      role: zoneAnalysisRoleLabel(role),
      status: zoneAnalysisStatusLabel(status),
      upper: formatDrawingPrice(upperPrice),
      lower: formatDrawingPrice(lowerPrice),
      mid: formatDrawingPrice(midPrice),
      width: formatDrawingPrice(width),
      widthPct: formatDrawingRatioPercent(widthPct),
      position: formatDrawingRatioPercent(positionPct),
      distanceToUpper: formatSignedDrawingPrice(distanceToUpper),
      distanceToLower: formatSignedDrawingPrice(distanceToLower),
      tolerance: `±${formatDrawingPrice(tolerance)}`,
      upperTouches: `${upperTouches.count.toLocaleString("zh-TW")} 次`,
      lowerTouches: `${lowerTouches.count.toLocaleString("zh-TW")} 次`,
      compression: finiteNumber(compressionRatio)
        ? `${zoneCompressionLabel(compressionState)} ${formatDrawingPercent(compressionRatio * 100)}`
        : zoneCompressionLabel(compressionState),
    },
  };
}

function fibonacciTrendLabel(trend: ChartDrawingFibonacciAnalysis["trend"]) {
  switch (trend) {
    case "upswing":
      return "上升波";
    case "downswing":
      return "下降波";
    case "flat":
      return "橫向";
    default:
      return "未判定";
  }
}

function fibonacciStatusLabel(status: ChartDrawingFibonacciAnalysis["status"]) {
  switch (status) {
    case "inside_range":
      return "錨點區間內";
    case "above_anchor":
      return "站上錨點";
    case "below_anchor":
      return "跌破錨點";
    case "near_level":
      return "貼近位階";
    default:
      return "資料不足";
  }
}

function fibonacciLevelKind(ratio: number): ChartDrawingFibonacciLevel["kind"] {
  if (ratio === 0 || ratio === 1) return "anchor";
  if (ratio < 0 || ratio > 1) return "extension";

  return "retracement";
}

function buildFibonacciAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  chartData: ChartPoint[] | undefined
): ChartDrawingFibonacciAnalysis | null {
  if (type !== "fibonacci") return null;
  if (!chartData || chartData.length === 0) return null;

  const first = points[0] ?? null;
  const second = points[1] ?? null;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const latestPrice = pointClose(latestPoint);

  if (!first || !second || !latestPoint || !finiteNumber(latestPrice)) return null;

  const priceDiff = second.price - first.price;
  const range = Math.abs(priceDiff);

  if (!Number.isFinite(range) || range <= 0) return null;

  const anchorHighPrice = Math.max(first.price, second.price);
  const anchorLowPrice = Math.min(first.price, second.price);
  const trend: ChartDrawingFibonacciAnalysis["trend"] =
    priceDiff > 0 ? "upswing" : priceDiff < 0 ? "downswing" : "flat";
  const tolerance = estimateLineAnalysisTolerance(chartData, latestPrice);
  const rawLevels = fibonacciAnalysisRatios.map((ratio) => {
    const price = first.price + priceDiff * ratio;
    const distance = latestPrice - price;
    const distancePct = price !== 0 ? (distance / price) * 100 : null;

    return {
      ratio,
      kind: fibonacciLevelKind(ratio),
      price,
      distance,
      distancePct,
    };
  });
  const nearestRaw = rawLevels.reduce<(typeof rawLevels)[number] | null>((nearest, level) => {
    if (!nearest) return level;

    return Math.abs(level.distance) < Math.abs(nearest.distance) ? level : nearest;
  }, null);
  const nearestRatio = nearestRaw?.ratio ?? null;
  const nearestDistance = nearestRaw?.distance ?? null;
  const nearestDistancePct = nearestRaw?.distancePct ?? null;
  const positionPct = (latestPrice - first.price) / priceDiff * 100;
  const rangePositionPct = (latestPrice - anchorLowPrice) / range * 100;
  const extensionPct =
    latestPrice > anchorHighPrice
      ? ((latestPrice - anchorHighPrice) / range) * 100
      : latestPrice < anchorLowPrice
        ? ((anchorLowPrice - latestPrice) / range) * 100
        : 0;
  const status: ChartDrawingFibonacciAnalysis["status"] =
    finiteNumber(nearestDistance) && Math.abs(nearestDistance) <= tolerance
      ? "near_level"
      : latestPrice > anchorHighPrice + tolerance
        ? "above_anchor"
        : latestPrice < anchorLowPrice - tolerance
          ? "below_anchor"
          : "inside_range";
  const levels: ChartDrawingFibonacciLevel[] = rawLevels.map((level) => ({
    ...level,
    isNearest: level.ratio === nearestRatio,
    label: formatFibonacciRatio(level.ratio),
    priceLabel: formatDrawingPrice(level.price),
    distanceLabel: formatSignedDrawingPrice(level.distance),
    distancePctLabel: formatDrawingRatioPercent(level.distancePct),
  }));
  const nearestLabel =
    nearestRaw === null
      ? "-"
      : `${formatFibonacciRatio(nearestRaw.ratio)} ${formatDrawingPrice(nearestRaw.price)}`;

  return {
    version: 1,
    trend,
    status,
    anchorStartPrice: first.price,
    anchorEndPrice: second.price,
    anchorHighPrice,
    anchorLowPrice,
    latestPrice,
    latestTime: latestPoint.time,
    range,
    positionPct,
    rangePositionPct,
    extensionPct,
    nearestRatio,
    nearestPrice: nearestRaw?.price ?? null,
    nearestDistance,
    nearestDistancePct,
    tolerance,
    levels,
    labels: {
      trend: fibonacciTrendLabel(trend),
      status: fibonacciStatusLabel(status),
      range: formatDrawingPrice(range),
      position: formatDrawingRatioPercent(positionPct),
      rangePosition: formatDrawingRatioPercent(rangePositionPct),
      extension: formatDrawingRatioPercent(extensionPct),
      nearest: nearestLabel,
      nearestDistance: finiteNumber(nearestDistance) ? formatSignedDrawingPrice(nearestDistance) : "-",
      nearestDistancePct: formatDrawingRatioPercent(nearestDistancePct),
      tolerance: `±${formatDrawingPrice(tolerance)}`,
    },
  };
}

function chartPointTypicalPrice(point: ChartPoint) {
  if (finiteNumber(point.high) && finiteNumber(point.low) && finiteNumber(point.close)) {
    return (point.high + point.low + point.close) / 3;
  }

  return pointClose(point);
}

function chartPointVolume(point: ChartPoint) {
  if (finiteNumber(point.volume) && point.volume > 0) return point.volume;
  if (finiteNumber(point.trade_value) && point.trade_value > 0) return point.trade_value;

  return null;
}

function anchoredVwapStatusLabel(status: ChartDrawingAnchoredVwapAnalysis["status"]) {
  switch (status) {
    case "above_vwap":
      return "站上 VWAP";
    case "below_vwap":
      return "跌破 VWAP";
    case "testing_vwap":
      return "測試 VWAP";
    default:
      return "資料不足";
  }
}

function buildAnchoredVwapAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData: ChartPoint[] | undefined
): ChartDrawingAnchoredVwapAnalysis | null {
  if (type !== "anchorVwap") return null;
  if (!chartData || chartData.length === 0) return null;

  const anchor = points[0] ?? null;
  const anchorIndex = anchor ? timeIndex.get(anchor.time) : undefined;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const latestPrice = pointClose(latestPoint);

  if (!anchor || anchorIndex === undefined || !latestPoint || !finiteNumber(latestPrice)) {
    return null;
  }

  let cumulativeVolume = 0;
  let cumulativeTypicalValue = 0;
  let firstVwap: number | null = null;
  let latestVwap: number | null = null;
  let validBars = 0;

  for (let index = anchorIndex; index < chartData.length; index += 1) {
    const point = chartData[index];
    const typicalPrice = chartPointTypicalPrice(point);
    const volume = chartPointVolume(point);

    if (!finiteNumber(typicalPrice) || !finiteNumber(volume) || volume <= 0) continue;

    cumulativeVolume += volume;
    cumulativeTypicalValue += typicalPrice * volume;
    validBars += 1;
    latestVwap = cumulativeTypicalValue / cumulativeVolume;

    if (!finiteNumber(firstVwap)) {
      firstVwap = latestVwap;
    }
  }

  if (!finiteNumber(latestVwap) || cumulativeVolume <= 0 || validBars === 0) return null;

  const distance = latestPrice - latestVwap;
  const distancePct = latestVwap !== 0 ? (distance / latestVwap) * 100 : null;
  const vwapChange =
    finiteNumber(firstVwap) && finiteNumber(latestVwap) ? latestVwap - firstVwap : null;
  const vwapChangePct =
    finiteNumber(vwapChange) && finiteNumber(firstVwap) && firstVwap !== 0
      ? (vwapChange / firstVwap) * 100
      : null;
  const tolerance = estimateLineAnalysisTolerance(chartData.slice(anchorIndex), latestVwap);
  const status: ChartDrawingAnchoredVwapAnalysis["status"] =
    Math.abs(distance) <= tolerance
      ? "testing_vwap"
      : distance > 0
        ? "above_vwap"
        : "below_vwap";

  return {
    version: 1,
    anchorTime: anchor.time,
    anchorPrice: anchor.price,
    latestTime: latestPoint.time,
    latestPrice,
    latestVwap,
    firstVwap,
    distance,
    distancePct,
    vwapChange,
    vwapChangePct,
    barCount: validBars,
    cumulativeVolume,
    cumulativeTypicalValue,
    status,
    labels: {
      status: anchoredVwapStatusLabel(status),
      vwap: formatDrawingPrice(latestVwap),
      distance: formatSignedDrawingPrice(distance),
      distancePct: formatDrawingRatioPercent(distancePct),
      vwapChange: finiteNumber(vwapChange) ? formatSignedDrawingPrice(vwapChange) : "-",
      vwapChangePct: formatDrawingRatioPercent(vwapChangePct),
      barCount: `${validBars.toLocaleString("zh-TW")} 根`,
      cumulativeVolume: formatCompactVolume(cumulativeVolume),
    },
  };
}

function volumeProfilePositionLabel(
  position: ChartDrawingVolumeProfileAnalysis["latestPosition"]
) {
  switch (position) {
    case "above_value_area":
      return "價值區上方";
    case "inside_value_area":
      return "價值區內";
    case "below_value_area":
      return "價值區下方";
    default:
      return "資料不足";
  }
}

function buildVolumeProfileAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData: ChartPoint[] | undefined
): ChartDrawingVolumeProfileAnalysis | null {
  if (type !== "volumeProfileRange") return null;
  if (!chartData || chartData.length === 0) return null;

  const first = points[0] ?? null;
  const second = points[1] ?? null;
  const firstIndex = first ? timeIndex.get(first.time) : undefined;
  const secondIndex = second ? timeIndex.get(second.time) : undefined;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const latestPrice = pointClose(latestPoint);

  if (!first || !second || firstIndex === undefined || secondIndex === undefined) return null;

  const fromIndex = Math.max(0, Math.min(firstIndex, secondIndex));
  const toIndex = Math.min(chartData.length - 1, Math.max(firstIndex, secondIndex));
  const priceHigh = Math.max(first.price, second.price);
  const priceLow = Math.min(first.price, second.price);
  const priceRange = priceHigh - priceLow;

  if (!Number.isFinite(priceRange) || priceRange <= 0) return null;

  const rowCount = drawingVolumeProfileRows;
  const binSize = priceRange / rowCount;
  const bins = Array.from({ length: rowCount }, (_, index) => ({
    index,
    buyVolume: 0,
    sellVolume: 0,
    totalVolume: 0,
  }));

  for (let index = fromIndex; index <= toIndex; index += 1) {
    const point = chartData[index];
    const volume = chartPointVolume(point);

    if (
      !finiteNumber(volume) ||
      volume <= 0 ||
      !finiteNumber(point.open) ||
      !finiteNumber(point.close) ||
      !finiteNumber(point.high) ||
      !finiteNumber(point.low)
    ) {
      continue;
    }

    const overlapLow = Math.max(point.low, priceLow);
    const overlapHigh = Math.min(point.high, priceHigh);

    if (overlapHigh < overlapLow) continue;

    const startBin = Math.max(
      0,
      Math.min(rowCount - 1, Math.floor((overlapLow - priceLow) / binSize))
    );
    const endBin = Math.max(
      startBin,
      Math.min(rowCount - 1, Math.floor((overlapHigh - priceLow) / binSize))
    );
    const share = volume / (endBin - startBin + 1);
    const side = point.close >= point.open ? "buyVolume" : "sellVolume";

    for (let binIndex = startBin; binIndex <= endBin; binIndex += 1) {
      bins[binIndex][side] += share;
      bins[binIndex].totalVolume += share;
    }
  }

  const totalVolume = bins.reduce((sum, bin) => sum + bin.totalVolume, 0);

  if (!Number.isFinite(totalVolume) || totalVolume <= 0) return null;

  const buyVolume = bins.reduce((sum, bin) => sum + bin.buyVolume, 0);
  const sellVolume = bins.reduce((sum, bin) => sum + bin.sellVolume, 0);
  const pocBin = bins.reduce((best, bin) => (bin.totalVolume > best.totalVolume ? bin : best), bins[0]);
  let valueAreaLowIndex = pocBin.index;
  let valueAreaHighIndex = pocBin.index;
  let valueAreaVolume = pocBin.totalVolume;
  const targetVolume = totalVolume * (drawingValueAreaTargetPct / 100);

  while (
    valueAreaVolume < targetVolume &&
    (valueAreaLowIndex > 0 || valueAreaHighIndex < rowCount - 1)
  ) {
    const nextLower = valueAreaLowIndex > 0 ? bins[valueAreaLowIndex - 1] : null;
    const nextUpper = valueAreaHighIndex < rowCount - 1 ? bins[valueAreaHighIndex + 1] : null;
    const lowerVolume = nextLower?.totalVolume ?? -1;
    const upperVolume = nextUpper?.totalVolume ?? -1;

    if (upperVolume >= lowerVolume && nextUpper) {
      valueAreaHighIndex += 1;
      valueAreaVolume += nextUpper.totalVolume;
    } else if (nextLower) {
      valueAreaLowIndex -= 1;
      valueAreaVolume += nextLower.totalVolume;
    } else {
      break;
    }
  }

  const valueAreaLow = priceLow + valueAreaLowIndex * binSize;
  const valueAreaHigh = priceLow + (valueAreaHighIndex + 1) * binSize;
  const valueAreaVolumePct = (valueAreaVolume / totalVolume) * 100;
  const pocPrice = priceLow + (pocBin.index + 0.5) * binSize;
  const latestPosition: ChartDrawingVolumeProfileAnalysis["latestPosition"] =
    !finiteNumber(latestPrice)
      ? "unknown"
      : latestPrice > valueAreaHigh
        ? "above_value_area"
        : latestPrice < valueAreaLow
          ? "below_value_area"
          : "inside_value_area";
  const imbalancePct = totalVolume > 0 ? ((buyVolume - sellVolume) / totalVolume) * 100 : null;
  const levels: ChartDrawingVolumeProfileLevel[] = bins.map((bin) => {
    const priceMin = priceLow + bin.index * binSize;
    const priceMax = priceMin + binSize;
    const centerPrice = (priceMin + priceMax) / 2;

    return {
      index: bin.index,
      priceMin,
      priceMax,
      centerPrice,
      buyVolume: bin.buyVolume,
      sellVolume: bin.sellVolume,
      totalVolume: bin.totalVolume,
      totalPct: (bin.totalVolume / totalVolume) * 100,
      inValueArea: bin.index >= valueAreaLowIndex && bin.index <= valueAreaHighIndex,
      isPoc: bin.index === pocBin.index,
      label: formatDrawingPrice(centerPrice),
      volumeLabel: formatCompactVolume(bin.totalVolume),
    };
  });

  return {
    version: 1,
    rowCount,
    startTime: chartData[fromIndex]?.time ?? first.time,
    endTime: chartData[toIndex]?.time ?? second.time,
    priceHigh,
    priceLow,
    totalVolume,
    buyVolume,
    sellVolume,
    pocPrice,
    pocVolume: pocBin.totalVolume,
    valueAreaHigh,
    valueAreaLow,
    valueAreaVolumePct,
    latestPrice: latestPrice ?? null,
    latestPosition,
    imbalancePct,
    levels,
    labels: {
      totalVolume: formatCompactVolume(totalVolume),
      poc: `${formatDrawingPrice(pocPrice)} / ${formatCompactVolume(pocBin.totalVolume)}`,
      valueArea: `${formatDrawingPrice(valueAreaLow)} - ${formatDrawingPrice(valueAreaHigh)}`,
      valueAreaVolumePct: formatDrawingRatioPercent(valueAreaVolumePct),
      latestPosition: volumeProfilePositionLabel(latestPosition),
      imbalance: formatDrawingRatioPercent(imbalancePct),
    },
  };
}

function buildDrawingDerivedMetrics(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData?: ChartPoint[]
): ChartDrawingDerivedMetrics {
  const first = points[0] ?? null;
  const second = points[1] ?? first;
  const anchorCount =
    type === "horizontal" || type === "anchorVwap"
      ? Math.min(points.length, 1)
      : Math.min(points.length, 2);
  const startPrice = first?.price ?? null;
  const endPrice = second?.price ?? null;
  const priceDiff =
    finiteNumber(startPrice) &&
    finiteNumber(endPrice) &&
    type !== "horizontal" &&
    type !== "anchorVwap"
      ? endPrice - startPrice
      : null;
  const priceDiffAbs = finiteNumber(priceDiff) ? Math.abs(priceDiff) : null;
  const percentChange =
    finiteNumber(priceDiff) && finiteNumber(startPrice) && startPrice !== 0
      ? (priceDiff / startPrice) * 100
      : null;
  const highPrice =
    finiteNumber(startPrice) && finiteNumber(endPrice)
      ? Math.max(startPrice, endPrice)
      : startPrice ?? endPrice ?? null;
  const lowPrice =
    finiteNumber(startPrice) && finiteNumber(endPrice)
      ? Math.min(startPrice, endPrice)
      : startPrice ?? endPrice ?? null;
  const midPrice =
    finiteNumber(highPrice) && finiteNumber(lowPrice) ? (highPrice + lowPrice) / 2 : null;
  const rangePct =
    finiteNumber(highPrice) && finiteNumber(lowPrice) && lowPrice !== 0
      ? ((highPrice - lowPrice) / lowPrice) * 100
      : null;
  const firstIndex = first ? timeIndex.get(first.time) : undefined;
  const secondIndex = second ? timeIndex.get(second.time) : undefined;
  const barCount =
    firstIndex !== undefined &&
    secondIndex !== undefined &&
    type !== "horizontal" &&
    type !== "anchorVwap"
      ? Math.abs(secondIndex - firstIndex)
      : null;
  const startTimeMs = first ? parseDrawingTimeMs(first.time) : null;
  const endTimeMs = second ? parseDrawingTimeMs(second.time) : null;
  const durationMinutes =
    finiteNumber(startTimeMs) &&
    finiteNumber(endTimeMs) &&
    type !== "horizontal" &&
    type !== "anchorVwap"
      ? Math.abs(endTimeMs - startTimeMs) / 60000
      : null;
  const durationDays = finiteNumber(durationMinutes) ? durationMinutes / 1440 : null;
  const slopePerBar =
    finiteNumber(priceDiff) && finiteNumber(barCount) && barCount > 0
      ? priceDiff / barCount
      : null;
  const slopePctPerBar =
    finiteNumber(percentChange) && finiteNumber(barCount) && barCount > 0
      ? percentChange / barCount
      : null;
  const direction =
    !finiteNumber(priceDiff) ? "unknown" : priceDiff > 0 ? "up" : priceDiff < 0 ? "down" : "flat";
  const durationLabel = formatDurationLabel(durationDays, durationMinutes);
  const lineAnalysis = buildLineAnalysis(type, points, timeIndex, chartData);
  const zoneAnalysis = buildZoneAnalysis(type, points, timeIndex, chartData);
  const fibonacciAnalysis = buildFibonacciAnalysis(type, points, chartData);
  const anchoredVwapAnalysis = buildAnchoredVwapAnalysis(type, points, timeIndex, chartData);
  const volumeProfileAnalysis = buildVolumeProfileAnalysis(type, points, timeIndex, chartData);

  return {
    version: 1,
    anchorCount,
    startTime: first?.time ?? null,
    endTime: second?.time ?? null,
    startPrice,
    endPrice,
    highPrice,
    lowPrice,
    midPrice,
    priceDiff,
    priceDiffAbs,
    percentChange,
    rangePct,
    barCount,
    durationDays,
    durationMinutes,
    slopePerBar,
    slopePctPerBar,
    direction,
    lineAnalysis,
    zoneAnalysis,
    fibonacciAnalysis,
    anchoredVwapAnalysis,
    volumeProfileAnalysis,
    labels: {
      priceDiff: finiteNumber(priceDiff) ? formatSignedDrawingPrice(priceDiff) : "-",
      percentChange: formatDrawingRatioPercent(percentChange),
      rangePct: formatDrawingRatioPercent(rangePct),
      bars: barCount === null ? null : `${barCount.toLocaleString("zh-TW")} 根`,
      duration: durationLabel,
      high: finiteNumber(highPrice) ? formatDrawingPrice(highPrice) : "-",
      low: finiteNumber(lowPrice) ? formatDrawingPrice(lowPrice) : "-",
      mid: finiteNumber(midPrice) ? formatDrawingPrice(midPrice) : "-",
      slope:
        finiteNumber(slopePerBar) && finiteNumber(slopePctPerBar)
          ? `${formatSignedDrawingPrice(slopePerBar)} / 根 (${formatDrawingPercent(slopePctPerBar)} / 根)`
          : null,
    },
  };
}

function drawingTypeLabel(type: ChartDrawing["type"]) {
  switch (type) {
    case "horizontal":
      return "水平線";
    case "trend":
      return "趨勢線";
    case "ray":
      return "射線";
    case "rectangle":
      return "區間框";
    case "fibonacci":
      return "Fib";
    case "anchorVwap":
      return "Anchored VWAP";
    case "volumeProfileRange":
      return "VP Range";
    case "measure":
      return "量測";
    case "priceRange":
      return "價幅";
    default:
      return "畫線";
  }
}

function buildDrawingOmiSummary(
  drawing: Pick<ChartDrawing, "type" | "points">,
  metrics: ChartDrawingDerivedMetrics,
  context: ChartDrawingContext
): ChartDrawingOmiSummary {
  const typeLabel = drawingTypeLabel(drawing.type);
  const subject = context.symbol ? `${context.symbol}` : context.label ?? "目前標的";
  const tags = [drawing.type, metrics.direction, context.timeframe ?? null].filter(
    (value): value is string => Boolean(value)
  );
  if (metrics.lineAnalysis?.role && metrics.lineAnalysis.role !== "unknown") {
    tags.push(metrics.lineAnalysis.role);
  }
  if (metrics.lineAnalysis?.status && metrics.lineAnalysis.status !== "unknown") {
    tags.push(metrics.lineAnalysis.status);
  }
  if (metrics.zoneAnalysis?.role && metrics.zoneAnalysis.role !== "unknown") {
    tags.push(metrics.zoneAnalysis.role);
  }
  if (metrics.zoneAnalysis?.status && metrics.zoneAnalysis.status !== "unknown") {
    tags.push(metrics.zoneAnalysis.status);
  }
  if (metrics.fibonacciAnalysis?.trend && metrics.fibonacciAnalysis.trend !== "unknown") {
    tags.push(metrics.fibonacciAnalysis.trend);
  }
  if (metrics.fibonacciAnalysis?.status && metrics.fibonacciAnalysis.status !== "unknown") {
    tags.push(metrics.fibonacciAnalysis.status);
  }
  if (metrics.anchoredVwapAnalysis?.status && metrics.anchoredVwapAnalysis.status !== "unknown") {
    tags.push(metrics.anchoredVwapAnalysis.status);
  }
  if (
    metrics.volumeProfileAnalysis?.latestPosition &&
    metrics.volumeProfileAnalysis.latestPosition !== "unknown"
  ) {
    tags.push(metrics.volumeProfileAnalysis.latestPosition);
  }
  const textParts = [
    `${subject} ${typeLabel}`,
    metrics.startTime && metrics.endTime && metrics.startTime !== metrics.endTime
      ? `${metrics.startTime} 到 ${metrics.endTime}`
      : metrics.startTime ?? null,
    finiteNumber(metrics.priceDiff)
      ? `${metrics.labels.priceDiff} / ${metrics.labels.percentChange}`
      : null,
    metrics.labels.bars,
    metrics.labels.duration,
    metrics.lineAnalysis
      ? `${metrics.lineAnalysis.labels.role}，${metrics.lineAnalysis.labels.status}，距線 ${metrics.lineAnalysis.labels.distancePct}`
      : null,
    metrics.zoneAnalysis
      ? `${metrics.zoneAnalysis.labels.role}，${metrics.zoneAnalysis.labels.status}，區間位置 ${metrics.zoneAnalysis.labels.position}`
      : null,
    metrics.fibonacciAnalysis
      ? `${metrics.fibonacciAnalysis.labels.trend}，${metrics.fibonacciAnalysis.labels.status}，最近 ${metrics.fibonacciAnalysis.labels.nearest}，距離 ${metrics.fibonacciAnalysis.labels.nearestDistancePct}`
      : null,
    metrics.anchoredVwapAnalysis
      ? `${metrics.anchoredVwapAnalysis.labels.status}，VWAP ${metrics.anchoredVwapAnalysis.labels.vwap}，距離 ${metrics.anchoredVwapAnalysis.labels.distancePct}`
      : null,
    metrics.volumeProfileAnalysis
      ? `POC ${metrics.volumeProfileAnalysis.labels.poc}，VA ${metrics.volumeProfileAnalysis.labels.valueArea}，現價 ${metrics.volumeProfileAnalysis.labels.latestPosition}`
      : null,
  ].filter((value): value is string => Boolean(value));

  return {
    title: `${typeLabel} ${metrics.direction === "up" ? "上行" : metrics.direction === "down" ? "下行" : "資料"}`,
    text: textParts.join("，"),
    tags,
    facts: {
      symbol: context.symbol ?? null,
      market: context.market ?? null,
      timeframe: context.timeframe ?? null,
      type: drawing.type,
      direction: metrics.direction,
      startTime: metrics.startTime,
      endTime: metrics.endTime,
      startPrice: metrics.startPrice,
      endPrice: metrics.endPrice,
      highPrice: metrics.highPrice,
      lowPrice: metrics.lowPrice,
      priceDiff: metrics.priceDiff,
      percentChange: metrics.percentChange,
      rangePct: metrics.rangePct,
      barCount: metrics.barCount,
      durationDays: metrics.durationDays,
      slopePerBar: metrics.slopePerBar,
      slopePctPerBar: metrics.slopePctPerBar,
      lineRole: metrics.lineAnalysis?.role ?? null,
      lineStatus: metrics.lineAnalysis?.status ?? null,
      lineProjectedPrice: metrics.lineAnalysis?.projectedPrice ?? null,
      lineDistance: metrics.lineAnalysis?.distance ?? null,
      lineDistancePct: metrics.lineAnalysis?.distancePct ?? null,
      lineTouchCount: metrics.lineAnalysis?.touchCount ?? null,
      lineLastTouchTime: metrics.lineAnalysis?.lastTouchTime ?? null,
      lineLastCrossTime: metrics.lineAnalysis?.lastCrossTime ?? null,
      zoneRole: metrics.zoneAnalysis?.role ?? null,
      zoneStatus: metrics.zoneAnalysis?.status ?? null,
      zoneUpperPrice: metrics.zoneAnalysis?.upperPrice ?? null,
      zoneLowerPrice: metrics.zoneAnalysis?.lowerPrice ?? null,
      zoneMidPrice: metrics.zoneAnalysis?.midPrice ?? null,
      zoneWidth: metrics.zoneAnalysis?.width ?? null,
      zoneWidthPct: metrics.zoneAnalysis?.widthPct ?? null,
      zonePositionPct: metrics.zoneAnalysis?.positionPct ?? null,
      zoneDistanceToUpper: metrics.zoneAnalysis?.distanceToUpper ?? null,
      zoneDistanceToLower: metrics.zoneAnalysis?.distanceToLower ?? null,
      zoneTolerance: metrics.zoneAnalysis?.tolerance ?? null,
      zoneUpperTouchCount: metrics.zoneAnalysis?.upperTouchCount ?? null,
      zoneLowerTouchCount: metrics.zoneAnalysis?.lowerTouchCount ?? null,
      zoneLastUpperTouchTime: metrics.zoneAnalysis?.lastUpperTouchTime ?? null,
      zoneLastLowerTouchTime: metrics.zoneAnalysis?.lastLowerTouchTime ?? null,
      zoneCompressionRatio: metrics.zoneAnalysis?.compressionRatio ?? null,
      zoneCompressionState: metrics.zoneAnalysis?.compressionState ?? null,
      fibTrend: metrics.fibonacciAnalysis?.trend ?? null,
      fibStatus: metrics.fibonacciAnalysis?.status ?? null,
      fibAnchorStartPrice: metrics.fibonacciAnalysis?.anchorStartPrice ?? null,
      fibAnchorEndPrice: metrics.fibonacciAnalysis?.anchorEndPrice ?? null,
      fibAnchorHighPrice: metrics.fibonacciAnalysis?.anchorHighPrice ?? null,
      fibAnchorLowPrice: metrics.fibonacciAnalysis?.anchorLowPrice ?? null,
      fibRange: metrics.fibonacciAnalysis?.range ?? null,
      fibPositionPct: metrics.fibonacciAnalysis?.positionPct ?? null,
      fibRangePositionPct: metrics.fibonacciAnalysis?.rangePositionPct ?? null,
      fibExtensionPct: metrics.fibonacciAnalysis?.extensionPct ?? null,
      fibNearestRatio: metrics.fibonacciAnalysis?.nearestRatio ?? null,
      fibNearestPrice: metrics.fibonacciAnalysis?.nearestPrice ?? null,
      fibNearestDistance: metrics.fibonacciAnalysis?.nearestDistance ?? null,
      fibNearestDistancePct: metrics.fibonacciAnalysis?.nearestDistancePct ?? null,
      fibTolerance: metrics.fibonacciAnalysis?.tolerance ?? null,
      fibLevels:
        metrics.fibonacciAnalysis?.levels
          .map((level) => `${level.label}:${level.priceLabel}`)
          .join("; ") ?? null,
      anchoredVwapAnchorTime: metrics.anchoredVwapAnalysis?.anchorTime ?? null,
      anchoredVwapAnchorPrice: metrics.anchoredVwapAnalysis?.anchorPrice ?? null,
      anchoredVwapLatestVwap: metrics.anchoredVwapAnalysis?.latestVwap ?? null,
      anchoredVwapDistance: metrics.anchoredVwapAnalysis?.distance ?? null,
      anchoredVwapDistancePct: metrics.anchoredVwapAnalysis?.distancePct ?? null,
      anchoredVwapChange: metrics.anchoredVwapAnalysis?.vwapChange ?? null,
      anchoredVwapChangePct: metrics.anchoredVwapAnalysis?.vwapChangePct ?? null,
      anchoredVwapBarCount: metrics.anchoredVwapAnalysis?.barCount ?? null,
      anchoredVwapCumulativeVolume: metrics.anchoredVwapAnalysis?.cumulativeVolume ?? null,
      anchoredVwapStatus: metrics.anchoredVwapAnalysis?.status ?? null,
      vpStartTime: metrics.volumeProfileAnalysis?.startTime ?? null,
      vpEndTime: metrics.volumeProfileAnalysis?.endTime ?? null,
      vpPriceHigh: metrics.volumeProfileAnalysis?.priceHigh ?? null,
      vpPriceLow: metrics.volumeProfileAnalysis?.priceLow ?? null,
      vpTotalVolume: metrics.volumeProfileAnalysis?.totalVolume ?? null,
      vpBuyVolume: metrics.volumeProfileAnalysis?.buyVolume ?? null,
      vpSellVolume: metrics.volumeProfileAnalysis?.sellVolume ?? null,
      vpPocPrice: metrics.volumeProfileAnalysis?.pocPrice ?? null,
      vpPocVolume: metrics.volumeProfileAnalysis?.pocVolume ?? null,
      vpValueAreaHigh: metrics.volumeProfileAnalysis?.valueAreaHigh ?? null,
      vpValueAreaLow: metrics.volumeProfileAnalysis?.valueAreaLow ?? null,
      vpValueAreaVolumePct: metrics.volumeProfileAnalysis?.valueAreaVolumePct ?? null,
      vpLatestPosition: metrics.volumeProfileAnalysis?.latestPosition ?? null,
      vpImbalancePct: metrics.volumeProfileAnalysis?.imbalancePct ?? null,
      vpTopLevels:
        metrics.volumeProfileAnalysis?.levels
          .filter((level) => level.totalVolume > 0)
          .toSorted((left, right) => right.totalVolume - left.totalVolume)
          .slice(0, 5)
          .map((level) => `${level.label}:${level.volumeLabel}`)
          .join("; ") ?? null,
    },
  };
}

function attachDrawingAnalytics(
  drawing: ChartDrawing,
  timeIndex: Map<string, number>,
  context: ChartDrawingContext,
  chartData?: ChartPoint[]
): ChartDrawing {
  const derivedMetrics = buildDrawingDerivedMetrics(
    drawing.type,
    drawing.points,
    timeIndex,
    chartData
  );
  const nextContext: ChartDrawingContext = {
    ...drawing.context,
    ...context,
    updatedAt: new Date().toISOString(),
  };

  return {
    ...drawing,
    context: nextContext,
    derivedMetrics,
    omiSummary: buildDrawingOmiSummary(drawing, derivedMetrics, nextContext),
  };
}

function measurementStatsFromMetrics(metrics: ChartDrawingDerivedMetrics): ProjectedMeasurementStats {
  return {
    tone:
      metrics.direction === "up" ? "up" : metrics.direction === "down" ? "down" : "flat",
    priceDiffLabel: metrics.labels.priceDiff,
    percentLabel: metrics.labels.percentChange,
    barsLabel: metrics.labels.bars,
    highLabel: metrics.labels.high,
    lowLabel: metrics.labels.low,
  };
}

function buildMeasurementStats(
  first: ChartDrawingPoint,
  second: ChartDrawingPoint,
  timeIndex: Map<string, number>
): ProjectedMeasurementStats {
  return measurementStatsFromMetrics(
    buildDrawingDerivedMetrics("measure", [first, second], timeIndex)
  );
}

function extendRayToViewport(
  first: DrawingCoordinate,
  second: DrawingCoordinate,
  width: number,
  height: number
): [DrawingCoordinate, DrawingCoordinate] {
  const viewportWidth = Math.max(width, 1);
  const viewportHeight = Math.max(height, 1);

  if (Math.abs(second.x - first.x) < 0.001) {
    return [
      first,
      { x: first.x, y: second.y >= first.y ? viewportHeight : 0 },
    ];
  }

  const slope = (second.y - first.y) / (second.x - first.x);
  const targetX = second.x >= first.x ? viewportWidth : 0;

  return [
    first,
    { x: targetX, y: first.y + (targetX - first.x) * slope },
  ];
}

function rectangleBounds(points: [DrawingCoordinate, DrawingCoordinate]) {
  const [first, second] = points;

  return {
    x: Math.min(first.x, second.x),
    y: Math.min(first.y, second.y),
    width: Math.abs(second.x - first.x),
    height: Math.abs(second.y - first.y),
  };
}

function coordinateDistance(first: DrawingCoordinate, second: DrawingCoordinate) {
  return Math.hypot(first.x - second.x, first.y - second.y);
}

function distanceToSegment(
  point: DrawingCoordinate,
  first: DrawingCoordinate,
  second: DrawingCoordinate
) {
  const dx = second.x - first.x;
  const dy = second.y - first.y;
  const lengthSquare = dx * dx + dy * dy;

  if (lengthSquare < 0.001) return coordinateDistance(point, first);

  const ratio = Math.max(
    0,
    Math.min(1, ((point.x - first.x) * dx + (point.y - first.y) * dy) / lengthSquare)
  );
  const projection = {
    x: first.x + ratio * dx,
    y: first.y + ratio * dy,
  };

  return coordinateDistance(point, projection);
}

function expandedRectangleContains(
  point: DrawingCoordinate,
  bounds: ReturnType<typeof rectangleBounds>,
  padding: number
) {
  return (
    point.x >= bounds.x - padding &&
    point.x <= bounds.x + bounds.width + padding &&
    point.y >= bounds.y - padding &&
    point.y <= bounds.y + bounds.height + padding
  );
}

function isProjectedDrawingHit(
  point: DrawingCoordinate,
  projectedDrawing: ProjectedDrawing,
  padding = 9
) {
  const points = projectedDrawing.anchorPoints ?? projectedDrawing.points;

  if (
    projectedDrawing.drawing.type === "rectangle" ||
    projectedDrawing.drawing.type === "priceRange" ||
    projectedDrawing.drawing.type === "volumeProfileRange"
  ) {
    return expandedRectangleContains(point, rectangleBounds(points), padding);
  }

  if (projectedDrawing.drawing.type === "anchorVwap") {
    if (coordinateDistance(point, points[0]) <= padding + 3) return true;

    const line = projectedDrawing.anchoredVwapLine ?? [];

    for (let index = 1; index < line.length; index += 1) {
      if (distanceToSegment(point, line[index - 1], line[index]) <= padding) return true;
    }

    return false;
  }

  if (projectedDrawing.drawing.type === "fibonacci" && projectedDrawing.fibonacciLevels) {
    return projectedDrawing.fibonacciLevels.some((level) => Math.abs(point.y - level.y) <= padding);
  }

  return distanceToSegment(point, projectedDrawing.points[0], projectedDrawing.points[1]) <= padding;
}

function lockCoordinateToNearestAngle(
  origin: DrawingCoordinate,
  current: DrawingCoordinate
): DrawingCoordinate {
  const dx = current.x - origin.x;
  const dy = current.y - origin.y;
  const distance = Math.hypot(dx, dy);

  if (distance < 0.001) return current;

  const angleStep = Math.PI / 4;
  const snappedAngle = Math.round(Math.atan2(dy, dx) / angleStep) * angleStep;

  return {
    x: origin.x + Math.cos(snappedAngle) * distance,
    y: origin.y + Math.sin(snappedAngle) * distance,
  };
}

const fibonacciRatios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
const fibonacciAnalysisRatios = [-0.618, -0.272, ...fibonacciRatios, 1.272, 1.618] as const;
const drawingVolumeProfileRows = 24;
const drawingValueAreaTargetPct = 70;
const selectedDrawingColor = "#dc2626";
const hoveredDrawingColor = "#2563eb";
const drawingHandleBorderColor = "#ffffff";

function formatFibonacciRatio(ratio: number) {
  if (ratio === 0 || ratio === 1) return `${ratio * 100}%`;
  if (ratio === 0.5) return "50%";

  return `${(ratio * 100).toFixed(1)}%`;
}

function buildFibonacciLevels(
  first: DrawingCoordinate,
  second: DrawingCoordinate,
  firstPrice: number,
  secondPrice: number
): ProjectedFibonacciLevel[] {
  return fibonacciRatios.map((ratio) => {
    const y = first.y + (second.y - first.y) * ratio;
    const price = firstPrice + (secondPrice - firstPrice) * ratio;

    return {
      ratio,
      y,
      label: formatFibonacciRatio(ratio),
      priceLabel: formatDrawingPrice(price),
    };
  });
}

function applyDrawingDragToDrawings(
  sourceDrawings: ChartDrawing[],
  dragState: DrawingDragState,
  anchor: DrawingAnchor
) {
  return sourceDrawings.map((drawing) => {
    if (drawing.id !== dragState.drawingId) return drawing;

    if (drawing.type === "horizontal" || dragState.mode === "horizontal") {
      const basePoint = drawing.points[0] ?? anchor;

      return {
        ...drawing,
        points: [
          {
            time: basePoint.time,
            price: anchor.price,
          },
        ],
      };
    }

    return {
      ...drawing,
      points: drawing.points.map((point, index) =>
        index === dragState.pointIndex ? { time: anchor.time, price: anchor.price } : point
      ),
    };
  });
}

function average(values: Array<number | null | undefined>) {
  const valid = values.filter(finiteNumber);

  if (valid.length === 0) return null;

  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function movingAverage(values: Array<number | null | undefined>, index: number, windowSize: number) {
  if (index + 1 < windowSize) return null;

  const windowValues = values.slice(index + 1 - windowSize, index + 1);

  if (windowValues.some((value) => !finiteNumber(value))) return null;

  return average(windowValues);
}

function standardDeviation(
  values: Array<number | null | undefined>,
  index: number,
  windowSize: number
) {
  const mean = movingAverage(values, index, windowSize);

  if (mean === null) return null;

  const slice = values.slice(index + 1 - windowSize, index + 1).filter(finiteNumber);

  if (slice.length < windowSize) return null;

  const variance = slice.reduce((sum, value) => sum + (value - mean) ** 2, 0) / windowSize;

  return Math.sqrt(variance);
}

function weightedMovingAverage(
  values: Array<number | null | undefined>,
  index: number,
  windowSize: number
) {
  if (index + 1 < windowSize) return null;

  let weightedSum = 0;
  let weightTotal = 0;

  for (let cursor = index + 1 - windowSize; cursor <= index; cursor += 1) {
    const value = values[cursor];

    if (!finiteNumber(value)) return null;

    const weight = cursor - (index - windowSize);
    weightedSum += value * weight;
    weightTotal += weight;
  }

  return weightTotal > 0 ? weightedSum / weightTotal : null;
}

function calculateWma(values: Array<number | null | undefined>, period: number) {
  return values.map((_, index) => weightedMovingAverage(values, index, period));
}

function calculateHma(values: Array<number | null | undefined>, period: number) {
  const halfPeriod = Math.max(1, Math.round(period / 2));
  const sqrtPeriod = Math.max(1, Math.round(Math.sqrt(period)));
  const fullWma = calculateWma(values, period);
  const halfWma = calculateWma(values, halfPeriod);
  const raw = values.map((_, index) => {
    const half = halfWma[index];
    const full = fullWma[index];

    if (!finiteNumber(half) || !finiteNumber(full)) return null;

    return half * 2 - full;
  });

  return calculateWma(raw, sqrtPeriod);
}

function calculateVwma(points: ChartPoint[], period: number) {
  return points.map((point, index) => {
    if (index + 1 < period) return null;

    let priceVolumeTotal = 0;
    let volumeTotal = 0;

    for (let cursor = index + 1 - period; cursor <= index; cursor += 1) {
      const close = points[cursor].close;
      const volume = points[cursor].volume;

      if (!finiteNumber(close) || !finiteNumber(volume) || volume <= 0) return null;

      priceVolumeTotal += close * volume;
      volumeTotal += volume;
    }

    return volumeTotal > 0 ? priceVolumeTotal / volumeTotal : null;
  });
}

function calculateEma(values: Array<number | null | undefined>, period: number) {
  const multiplier = 2 / (period + 1);
  let previousEma: number | null = null;

  return values.map((value) => {
    if (!finiteNumber(value)) return null;

    if (previousEma === null) {
      previousEma = value;
      return value;
    }

    previousEma = value * multiplier + previousEma * (1 - multiplier);
    return previousEma;
  });
}

function calculateRsi(closes: Array<number | null | undefined>, period = 14) {
  return closes.map((close, index) => {
    if (!finiteNumber(close) || index < period) return null;

    let gain = 0;
    let loss = 0;

    for (let cursor = index - period + 1; cursor <= index; cursor += 1) {
      const current = closes[cursor];
      const previous = closes[cursor - 1];

      if (!finiteNumber(current) || !finiteNumber(previous)) return null;

      const change = current - previous;
      if (change >= 0) gain += change;
      else loss += Math.abs(change);
    }

    const averageGain = gain / period;
    const averageLoss = loss / period;

    if (averageLoss === 0) return 100;
    if (averageGain === 0) return 0;

    const rs = averageGain / averageLoss;
    return 100 - 100 / (1 + rs);
  });
}

function calculateMacd(
  closes: Array<number | null | undefined>,
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9
) {
  const fast = calculateEma(closes, fastPeriod);
  const slow = calculateEma(closes, slowPeriod);
  const macd = closes.map((_, index) => {
    if (!finiteNumber(fast[index]) || !finiteNumber(slow[index])) return null;
    return fast[index] - slow[index];
  });
  const signal = calculateEma(macd, signalPeriod);
  const histogram = macd.map((value, index) => {
    if (!finiteNumber(value) || !finiteNumber(signal[index])) return null;
    return value - signal[index];
  });

  return { macd, signal, histogram };
}

function calculateKd(points: ChartPoint[], period = 9) {
  let previousK = 50;
  let previousD = 50;

  return points.map((point, index) => {
    if (index + 1 < period || !finiteNumber(point.close)) {
      return { k: null, d: null };
    }

    const slice = points.slice(index + 1 - period, index + 1);
    const highs = slice.map((item) => item.high).filter(finiteNumber);
    const lows = slice.map((item) => item.low).filter(finiteNumber);

    if (highs.length < period || lows.length < period) {
      return { k: null, d: null };
    }

    const highest = Math.max(...highs);
    const lowest = Math.min(...lows);
    const rsv = highest === lowest ? 50 : ((point.close - lowest) / (highest - lowest)) * 100;
    const k = previousK * (2 / 3) + rsv * (1 / 3);
    const d = previousD * (2 / 3) + k * (1 / 3);

    previousK = k;
    previousD = d;

    return { k, d };
  });
}

function typicalPrice(point: ChartPoint) {
  if (!finiteNumber(point.high) || !finiteNumber(point.low) || !finiteNumber(point.close)) {
    return null;
  }

  return (point.high + point.low + point.close) / 3;
}

function calculateVwap(points: ChartPoint[]) {
  let cumulativePriceVolume = 0;
  let cumulativeVolume = 0;

  return points.map((point) => {
    const price = typicalPrice(point);
    const volume = point.volume;

    if (!finiteNumber(price) || !finiteNumber(volume) || volume <= 0) return null;

    cumulativePriceVolume += price * volume;
    cumulativeVolume += volume;

    return cumulativeVolume > 0 ? cumulativePriceVolume / cumulativeVolume : null;
  });
}

function calculateParabolicSar(points: ChartPoint[], step = 0.02, maxStep = 0.2) {
  const values: Array<number | null> = points.map(() => null);

  if (points.length < 2) return values;

  const first = points[0];
  const second = points[1];

  if (
    !finiteNumber(first.high) ||
    !finiteNumber(first.low) ||
    !finiteNumber(first.close) ||
    !finiteNumber(second.high) ||
    !finiteNumber(second.low) ||
    !finiteNumber(second.close)
  ) {
    return values;
  }

  let isUpTrend = second.close >= first.close;
  let sar = isUpTrend ? Math.min(first.low, second.low) : Math.max(first.high, second.high);
  let extremePoint = isUpTrend ? Math.max(first.high, second.high) : Math.min(first.low, second.low);
  let acceleration = step;
  values[1] = sar;

  for (let index = 2; index < points.length; index += 1) {
    const point = points[index];
    const previous = points[index - 1];
    const previous2 = points[index - 2];

    if (
      !finiteNumber(point.high) ||
      !finiteNumber(point.low) ||
      !finiteNumber(previous.high) ||
      !finiteNumber(previous.low) ||
      !finiteNumber(previous2.high) ||
      !finiteNumber(previous2.low)
    ) {
      continue;
    }

    let nextSar = sar + acceleration * (extremePoint - sar);

    if (isUpTrend) {
      nextSar = Math.min(nextSar, previous.low, previous2.low);

      if (point.low < nextSar) {
        isUpTrend = false;
        sar = extremePoint;
        extremePoint = point.low;
        acceleration = step;
      } else {
        sar = nextSar;

        if (point.high > extremePoint) {
          extremePoint = point.high;
          acceleration = Math.min(acceleration + step, maxStep);
        }
      }
    } else {
      nextSar = Math.max(nextSar, previous.high, previous2.high);

      if (point.high > nextSar) {
        isUpTrend = true;
        sar = extremePoint;
        extremePoint = point.high;
        acceleration = step;
      } else {
        sar = nextSar;

        if (point.low < extremePoint) {
          extremePoint = point.low;
          acceleration = Math.min(acceleration + step, maxStep);
        }
      }
    }

    values[index] = sar;
  }

  return values;
}

function calculateDonchian(points: ChartPoint[], period = 20) {
  return points.map((_, index) => {
    if (index + 1 < period) return { upper: null, lower: null };

    const slice = points.slice(index + 1 - period, index + 1);
    const highs = slice.map((point) => point.high).filter(finiteNumber);
    const lows = slice.map((point) => point.low).filter(finiteNumber);

    if (highs.length < period || lows.length < period) return { upper: null, lower: null };

    return {
      upper: Math.max(...highs),
      lower: Math.min(...lows),
    };
  });
}

function calculateTrueRanges(points: ChartPoint[]) {
  return points.map((point, index) => {
    if (!finiteNumber(point.high) || !finiteNumber(point.low)) return null;

    const previousClose = points[index - 1]?.close;
    const highLow = point.high - point.low;

    if (!finiteNumber(previousClose)) return highLow;

    return Math.max(
      highLow,
      Math.abs(point.high - previousClose),
      Math.abs(point.low - previousClose)
    );
  });
}

function calculateAtr(points: ChartPoint[], period = 14) {
  const trueRanges = calculateTrueRanges(points);
  let previousAtr: number | null = null;

  return trueRanges.map((trueRange, index) => {
    if (!finiteNumber(trueRange) || index + 1 < period) return null;

    if (previousAtr === null) {
      const slice = trueRanges.slice(index + 1 - period, index + 1);

      if (slice.some((value) => !finiteNumber(value))) return null;

      previousAtr = average(slice);
      return previousAtr;
    }

    previousAtr = (previousAtr * (period - 1) + trueRange) / period;
    return previousAtr;
  });
}

function calculateChoppiness(points: ChartPoint[], period = 14) {
  const trueRanges = calculateTrueRanges(points);

  return points.map((_, index) => {
    if (index + 1 < period) return null;

    const windowPoints = points.slice(index + 1 - period, index + 1);
    const highs = windowPoints.map((point) => point.high).filter(finiteNumber);
    const lows = windowPoints.map((point) => point.low).filter(finiteNumber);
    const trValues = trueRanges.slice(index + 1 - period, index + 1);

    if (
      highs.length < period ||
      lows.length < period ||
      trValues.some((value) => !finiteNumber(value))
    ) {
      return null;
    }

    const highLowRange = Math.max(...highs) - Math.min(...lows);
    const trSum = trValues.filter(finiteNumber).reduce((sum, value) => sum + value, 0);

    if (highLowRange <= 0 || trSum <= 0 || period <= 1) return null;

    return (100 * Math.log10(trSum / highLowRange)) / Math.log10(period);
  });
}

function calculateDmi(points: ChartPoint[], period = 14) {
  const trueRanges = calculateTrueRanges(points);
  const plusDm: Array<number | null> = points.map(() => null);
  const minusDm: Array<number | null> = points.map(() => null);

  for (let index = 1; index < points.length; index += 1) {
    const current = points[index];
    const previous = points[index - 1];

    if (
      !finiteNumber(current.high) ||
      !finiteNumber(current.low) ||
      !finiteNumber(previous.high) ||
      !finiteNumber(previous.low)
    ) {
      continue;
    }

    const upMove = current.high - previous.high;
    const downMove = previous.low - current.low;
    plusDm[index] = upMove > downMove && upMove > 0 ? upMove : 0;
    minusDm[index] = downMove > upMove && downMove > 0 ? downMove : 0;
  }

  let smoothedTr: number | null = null;
  let smoothedPlusDm: number | null = null;
  let smoothedMinusDm: number | null = null;
  let previousAdx: number | null = null;
  const dxValues: Array<number | null> = points.map(() => null);

  return points.map((_, index) => {
    if (index < period) return { plusDi: null, minusDi: null, adx: null };

    const trueRange = trueRanges[index];
    const plus = plusDm[index];
    const minus = minusDm[index];

    if (!finiteNumber(trueRange) || !finiteNumber(plus) || !finiteNumber(minus)) {
      return { plusDi: null, minusDi: null, adx: null };
    }

    if (smoothedTr === null || smoothedPlusDm === null || smoothedMinusDm === null) {
      const trSlice = trueRanges.slice(index + 1 - period, index + 1);
      const plusSlice = plusDm.slice(index + 1 - period, index + 1);
      const minusSlice = minusDm.slice(index + 1 - period, index + 1);

      if (
        trSlice.some((value) => !finiteNumber(value)) ||
        plusSlice.some((value) => !finiteNumber(value)) ||
        minusSlice.some((value) => !finiteNumber(value))
      ) {
        return { plusDi: null, minusDi: null, adx: null };
      }

      smoothedTr = trSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);
      smoothedPlusDm = plusSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);
      smoothedMinusDm = minusSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);
    } else {
      smoothedTr = smoothedTr - smoothedTr / period + trueRange;
      smoothedPlusDm = smoothedPlusDm - smoothedPlusDm / period + plus;
      smoothedMinusDm = smoothedMinusDm - smoothedMinusDm / period + minus;
    }

    if (smoothedTr === 0) return { plusDi: null, minusDi: null, adx: null };

    const plusDi = (smoothedPlusDm / smoothedTr) * 100;
    const minusDi = (smoothedMinusDm / smoothedTr) * 100;
    const diTotal = plusDi + minusDi;
    const dx = diTotal === 0 ? 0 : (Math.abs(plusDi - minusDi) / diTotal) * 100;
    dxValues[index] = dx;

    if (index >= period * 2 - 1) {
      if (previousAdx === null) {
        const dxSlice = dxValues.slice(index + 1 - period, index + 1);

        if (!dxSlice.some((value) => !finiteNumber(value))) {
          previousAdx = average(dxSlice);
        }
      } else {
        previousAdx = (previousAdx * (period - 1) + dx) / period;
      }
    }

    return { plusDi, minusDi, adx: previousAdx };
  });
}

function calculateObv(points: ChartPoint[]) {
  let currentObv = 0;

  return points.map((point, index) => {
    const previousClose = points[index - 1]?.close;

    if (!finiteNumber(point.close) || !finiteNumber(point.volume)) {
      return index === 0 ? 0 : currentObv;
    }

    if (!finiteNumber(previousClose)) return currentObv;

    if (point.close > previousClose) currentObv += point.volume;
    else if (point.close < previousClose) currentObv -= point.volume;

    return currentObv;
  });
}

function calculateMfi(points: ChartPoint[], period = 14) {
  const typicalPrices = points.map(typicalPrice);
  const positiveFlow: Array<number | null> = points.map(() => null);
  const negativeFlow: Array<number | null> = points.map(() => null);

  for (let index = 1; index < points.length; index += 1) {
    const price = typicalPrices[index];
    const previousPrice = typicalPrices[index - 1];
    const volume = points[index].volume;

    if (!finiteNumber(price) || !finiteNumber(previousPrice) || !finiteNumber(volume)) {
      continue;
    }

    const moneyFlow = price * volume;
    positiveFlow[index] = price > previousPrice ? moneyFlow : 0;
    negativeFlow[index] = price < previousPrice ? moneyFlow : 0;
  }

  return points.map((_, index) => {
    if (index + 1 < period) return null;

    const positiveSlice = positiveFlow.slice(index + 1 - period, index + 1);
    const negativeSlice = negativeFlow.slice(index + 1 - period, index + 1);

    if (
      positiveSlice.some((value) => !finiteNumber(value)) ||
      negativeSlice.some((value) => !finiteNumber(value))
    ) {
      return null;
    }

    const positive = positiveSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);
    const negative = negativeSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);

    if (negative === 0) return 100;
    if (positive === 0) return 0;

    return 100 - 100 / (1 + positive / negative);
  });
}

function calculateChaikinMoneyFlow(points: ChartPoint[], period = 20) {
  const moneyFlowVolume = points.map((point) => {
    if (
      !finiteNumber(point.high) ||
      !finiteNumber(point.low) ||
      !finiteNumber(point.close) ||
      !finiteNumber(point.volume)
    ) {
      return null;
    }

    const range = point.high - point.low;
    const multiplier =
      range === 0 ? 0 : ((point.close - point.low) - (point.high - point.close)) / range;

    return multiplier * point.volume;
  });

  return points.map((_, index) => {
    if (index + 1 < period) return null;

    const moneyFlowSlice = moneyFlowVolume.slice(index + 1 - period, index + 1);
    const volumeSlice = points
      .slice(index + 1 - period, index + 1)
      .map((point) => point.volume);

    if (
      moneyFlowSlice.some((value) => !finiteNumber(value)) ||
      volumeSlice.some((value) => !finiteNumber(value))
    ) {
      return null;
    }

    const moneyFlowTotal = moneyFlowSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);
    const volumeTotal = volumeSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);

    return volumeTotal !== 0 ? moneyFlowTotal / volumeTotal : null;
  });
}

function calculateAccumulationDistribution(points: ChartPoint[]) {
  let cumulative = 0;

  return points.map((point) => {
    if (
      !finiteNumber(point.high) ||
      !finiteNumber(point.low) ||
      !finiteNumber(point.close) ||
      !finiteNumber(point.volume)
    ) {
      return cumulative;
    }

    const range = point.high - point.low;
    const multiplier =
      range === 0 ? 0 : ((point.close - point.low) - (point.high - point.close)) / range;

    cumulative += multiplier * point.volume;
    return cumulative;
  });
}

function calculatePriceVolumeTrend(points: ChartPoint[]) {
  let cumulative = 0;

  return points.map((point, index) => {
    const previousClose = points[index - 1]?.close;

    if (
      !finiteNumber(point.close) ||
      !finiteNumber(previousClose) ||
      previousClose === 0 ||
      !finiteNumber(point.volume)
    ) {
      return cumulative;
    }

    cumulative += point.volume * ((point.close - previousClose) / previousClose);
    return cumulative;
  });
}

function calculateCci(points: ChartPoint[], period = 20) {
  const typicalPrices = points.map(typicalPrice);

  return typicalPrices.map((price, index) => {
    if (!finiteNumber(price) || index + 1 < period) return null;

    const slice = typicalPrices.slice(index + 1 - period, index + 1);
    const values = slice.filter(finiteNumber);

    if (values.length < period) return null;

    const mean = average(values);
    if (mean === null) return null;

    const meanDeviation = values.reduce((sum, value) => sum + Math.abs(value - mean), 0) / period;

    if (meanDeviation === 0) return 0;

    return (price - mean) / (0.015 * meanDeviation);
  });
}

function calculateWilliamsR(points: ChartPoint[], period = 14) {
  return points.map((point, index) => {
    if (!finiteNumber(point.close) || index + 1 < period) return null;

    const slice = points.slice(index + 1 - period, index + 1);
    const highs = slice.map((item) => item.high).filter(finiteNumber);
    const lows = slice.map((item) => item.low).filter(finiteNumber);

    if (highs.length < period || lows.length < period) return null;

    const highest = Math.max(...highs);
    const lowest = Math.min(...lows);

    if (highest === lowest) return -50;

    return ((highest - point.close) / (highest - lowest)) * -100;
  });
}

function calculateRoc(closes: Array<number | null | undefined>, period = 12) {
  return closes.map((close, index) => {
    const previous = closes[index - period];

    if (!finiteNumber(close) || !finiteNumber(previous) || previous === 0) return null;

    return ((close - previous) / previous) * 100;
  });
}

function calculateMomentum(closes: Array<number | null | undefined>, period = 10) {
  return closes.map((close, index) => {
    const previous = closes[index - period];

    if (!finiteNumber(close) || !finiteNumber(previous)) return null;

    return close - previous;
  });
}

function calculateTsi(
  closes: Array<number | null | undefined>,
  shortPeriod = 13,
  longPeriod = 25,
  signalPeriod = 7
) {
  const changes = closes.map((close, index) => {
    const previous = closes[index - 1];

    if (!finiteNumber(close) || !finiteNumber(previous)) return null;

    return close - previous;
  });
  const absoluteChanges = changes.map((value) => (finiteNumber(value) ? Math.abs(value) : null));
  const doubleSmoothedChange = calculateEma(calculateEma(changes, longPeriod), shortPeriod);
  const doubleSmoothedAbsChange = calculateEma(calculateEma(absoluteChanges, longPeriod), shortPeriod);
  const tsi = closes.map((_, index) => {
    const numerator = doubleSmoothedChange[index];
    const denominator = doubleSmoothedAbsChange[index];

    if (!finiteNumber(numerator) || !finiteNumber(denominator) || denominator === 0) return null;

    return (numerator / denominator) * 100;
  });
  const signal = calculateEma(tsi, signalPeriod);

  return { tsi, signal };
}

function calculateAwesomeOscillator(points: ChartPoint[], fastPeriod = 5, slowPeriod = 34) {
  const medianPrices = points.map((point) =>
    finiteNumber(point.high) && finiteNumber(point.low) ? (point.high + point.low) / 2 : null
  );

  return medianPrices.map((_, index) => {
    const fast = movingAverage(medianPrices, index, fastPeriod);
    const slow = movingAverage(medianPrices, index, slowPeriod);

    if (!finiteNumber(fast) || !finiteNumber(slow)) return null;

    return fast - slow;
  });
}

function calculateUltimateOscillator(points: ChartPoint[], shortPeriod = 7, middlePeriod = 14, longPeriod = 28) {
  const buyingPressure: Array<number | null> = [];
  const trueRange: Array<number | null> = [];

  points.forEach((point, index) => {
    const previousClose = points[index - 1]?.close;

    if (
      !finiteNumber(point.high) ||
      !finiteNumber(point.low) ||
      !finiteNumber(point.close)
    ) {
      buyingPressure.push(null);
      trueRange.push(null);
      return;
    }

    const referenceClose = finiteNumber(previousClose) ? previousClose : point.close;
    buyingPressure.push(point.close - Math.min(point.low, referenceClose));
    trueRange.push(Math.max(point.high, referenceClose) - Math.min(point.low, referenceClose));
  });

  function averageRatio(index: number, period: number) {
    if (index + 1 < period) return null;

    const bpSlice = buyingPressure.slice(index + 1 - period, index + 1);
    const trSlice = trueRange.slice(index + 1 - period, index + 1);

    if (bpSlice.some((value) => !finiteNumber(value)) || trSlice.some((value) => !finiteNumber(value))) {
      return null;
    }

    const bpTotal = bpSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);
    const trTotal = trSlice.filter(finiteNumber).reduce((sum, value) => sum + value, 0);

    return trTotal !== 0 ? bpTotal / trTotal : null;
  }

  return points.map((_, index) => {
    const shortRatio = averageRatio(index, shortPeriod);
    const middleRatio = averageRatio(index, middlePeriod);
    const longRatio = averageRatio(index, longPeriod);

    if (!finiteNumber(shortRatio) || !finiteNumber(middleRatio) || !finiteNumber(longRatio)) {
      return null;
    }

    return 100 * ((4 * shortRatio + 2 * middleRatio + longRatio) / 7);
  });
}

function calculateStochRsi(
  rsiValues: Array<number | null>,
  period = 14,
  smoothK = 3,
  smoothD = 3
) {
  const rawValues = rsiValues.map((rsi, index) => {
    if (!finiteNumber(rsi) || index + 1 < period) return null;

    const slice = rsiValues.slice(index + 1 - period, index + 1);

    if (slice.some((value) => !finiteNumber(value))) return null;

    const values = slice.filter(finiteNumber);
    const minRsi = Math.min(...values);
    const maxRsi = Math.max(...values);

    if (maxRsi === minRsi) return 50;

    return ((rsi - minRsi) / (maxRsi - minRsi)) * 100;
  });
  const k = rawValues.map((_, index) => movingAverage(rawValues, index, smoothK));
  const d = k.map((_, index) => movingAverage(k, index, smoothD));

  return { k, d };
}

function midpointOfRange(points: ChartPoint[], index: number, period: number) {
  if (index + 1 < period) return null;

  const slice = points.slice(index + 1 - period, index + 1);
  const highs = slice.map((point) => point.high).filter(finiteNumber);
  const lows = slice.map((point) => point.low).filter(finiteNumber);

  if (highs.length < period || lows.length < period) return null;

  return (Math.max(...highs) + Math.min(...lows)) / 2;
}

function calculateIchimoku(points: ChartPoint[], params: IndicatorParameters) {
  const conversion = points.map((_, index) =>
    midpointOfRange(points, index, params.ichimokuConversionPeriod)
  );
  const base = points.map((_, index) => midpointOfRange(points, index, params.ichimokuBasePeriod));
  const spanBSource = points.map((_, index) =>
    midpointOfRange(points, index, params.ichimokuSpanBPeriod)
  );
  const spanA = points.map((_, index) => {
    const sourceIndex = index - params.ichimokuDisplacement;
    const sourceConversion = conversion[sourceIndex];
    const sourceBase = base[sourceIndex];

    if (!finiteNumber(sourceConversion) || !finiteNumber(sourceBase)) return null;

    return (sourceConversion + sourceBase) / 2;
  });
  const spanB = points.map((_, index) => {
    const sourceIndex = index - params.ichimokuDisplacement;
    return spanBSource[sourceIndex] ?? null;
  });
  const lagging = points.map((_, index) => {
    const sourceIndex = index + params.ichimokuDisplacement;
    return points[sourceIndex]?.close ?? null;
  });

  return { conversion, base, spanA, spanB, lagging };
}

function calculateKeltner(points: ChartPoint[], params: IndicatorParameters) {
  const closes = points.map((point) => point.close);
  const middle = calculateEma(closes, params.keltnerPeriod);
  const atr = calculateAtr(points, params.keltnerAtrPeriod);

  return points.map((_, index) => {
    const middleValue = middle[index];
    const atrValue = atr[index];

    if (!finiteNumber(middleValue) || !finiteNumber(atrValue)) {
      return { upper: null, middle: middleValue ?? null, lower: null };
    }

    const offset = atrValue * params.keltnerMultiplier;

    return {
      upper: middleValue + offset,
      middle: middleValue,
      lower: middleValue - offset,
    };
  });
}

function calculateSupertrend(points: ChartPoint[], period = 10, multiplier = 3) {
  const atr = calculateAtr(points, period);
  const values: Array<{ value: number | null; direction: 1 | -1 | null }> = points.map(() => ({
    value: null,
    direction: null,
  }));
  let finalUpper: number | null = null;
  let finalLower: number | null = null;
  let previousValue: number | null = null;
  let previousDirection: 1 | -1 = 1;

  for (let index = 0; index < points.length; index += 1) {
    const point = points[index];
    const atrValue = atr[index];

    if (
      !finiteNumber(point.high) ||
      !finiteNumber(point.low) ||
      !finiteNumber(point.close) ||
      !finiteNumber(atrValue)
    ) {
      continue;
    }

    const hl2 = (point.high + point.low) / 2;
    const basicUpper = hl2 + multiplier * atrValue;
    const basicLower = hl2 - multiplier * atrValue;
    const previousClose = points[index - 1]?.close;

    if (finalUpper === null || finalLower === null || !finiteNumber(previousClose)) {
      finalUpper = basicUpper;
      finalLower = basicLower;
      previousDirection = point.close >= hl2 ? 1 : -1;
      previousValue = previousDirection === 1 ? finalLower : finalUpper;
      values[index] = { value: previousValue, direction: previousDirection };
      continue;
    }

    finalUpper = basicUpper < finalUpper || previousClose > finalUpper ? basicUpper : finalUpper;
    finalLower = basicLower > finalLower || previousClose < finalLower ? basicLower : finalLower;

    let direction: 1 | -1;

    if (previousValue === finalUpper) {
      direction = point.close <= finalUpper ? -1 : 1;
    } else {
      direction = point.close >= finalLower ? 1 : -1;
    }

    const value: number = direction === 1 ? finalLower : finalUpper;

    previousDirection = direction;
    previousValue = value;
    values[index] = { value, direction };
  }

  return values;
}

function calculateAroon(points: ChartPoint[], period = 25) {
  return points.map((_, index) => {
    if (index + 1 < period) return { up: null, down: null };

    const slice = points.slice(index + 1 - period, index + 1);
    const highs = slice.map((point) => point.high);
    const lows = slice.map((point) => point.low);

    if (highs.some((value) => !finiteNumber(value)) || lows.some((value) => !finiteNumber(value))) {
      return { up: null, down: null };
    }

    let highIndex = 0;
    let lowIndex = 0;

    for (let cursor = 1; cursor < slice.length; cursor += 1) {
      if ((highs[cursor] as number) >= (highs[highIndex] as number)) highIndex = cursor;
      if ((lows[cursor] as number) <= (lows[lowIndex] as number)) lowIndex = cursor;
    }

    const periodsSinceHigh = period - 1 - highIndex;
    const periodsSinceLow = period - 1 - lowIndex;

    return {
      up: ((period - periodsSinceHigh) / period) * 100,
      down: ((period - periodsSinceLow) / period) * 100,
    };
  });
}

function calculateTrix(closes: Array<number | null | undefined>, period = 15, signalPeriod = 9) {
  const first = calculateEma(closes, period);
  const second = calculateEma(first, period);
  const third = calculateEma(second, period);
  const trix = third.map((value, index) => {
    const previous = third[index - 1];

    if (!finiteNumber(value) || !finiteNumber(previous) || previous === 0) return null;

    return ((value - previous) / previous) * 100;
  });
  const signal = trix.map((_, index) => movingAverage(trix, index, signalPeriod));

  return { trix, signal };
}

function calculatePivots(points: ChartPoint[], lookback = 1) {
  return points.map((_, index) => {
    const source = points[index - lookback];

    if (
      !source ||
      !finiteNumber(source.high) ||
      !finiteNumber(source.low) ||
      !finiteNumber(source.close)
    ) {
      return { pivot: null, r1: null, s1: null };
    }

    const pivot = (source.high + source.low + source.close) / 3;

    return {
      pivot,
      r1: pivot * 2 - source.low,
      s1: pivot * 2 - source.high,
    };
  });
}

function calculateSupportResistance(points: ChartPoint[], period = 20) {
  return points.map((_, index) => {
    if (index + 1 < period) return { support: null, resistance: null };

    const windowPoints = points.slice(index + 1 - period, index + 1);
    const highs = windowPoints.map((point) => point.high).filter(finiteNumber);
    const lows = windowPoints.map((point) => point.low).filter(finiteNumber);

    if (highs.length < period || lows.length < period) {
      return { support: null, resistance: null };
    }

    return {
      support: Math.min(...lows),
      resistance: Math.max(...highs),
    };
  });
}

function calculateGaps(points: ChartPoint[], minPct = 0.5) {
  return points.map((point, index) => {
    const previous = points[index - 1];

    if (
      !previous ||
      !finiteNumber(point.open) ||
      !finiteNumber(previous.high) ||
      !finiteNumber(previous.low) ||
      !finiteNumber(previous.close) ||
      previous.close === 0
    ) {
      return { up: null, down: null };
    }

    const gapUpPct = ((point.open - previous.high) / previous.close) * 100;
    const gapDownPct = ((previous.low - point.open) / previous.close) * 100;

    return {
      up: gapUpPct >= minPct ? point.open : null,
      down: gapDownPct >= minPct ? point.open : null,
    };
  });
}

function calculateRelativeMetrics(
  points: ChartPoint[],
  benchmarkPoints: ChartPoint[] | undefined,
  params: IndicatorParameters
) {
  const relativeStrength: Array<number | null> = points.map(() => null);
  const beta: Array<number | null> = points.map(() => null);
  const correlation: Array<number | null> = points.map(() => null);

  if (!benchmarkPoints || benchmarkPoints.length === 0) {
    return { relativeStrength, beta, correlation };
  }

  const benchmarkCloseByDate = new Map<string, number>();

  benchmarkPoints.forEach((point) => {
    if (finiteNumber(point.close)) {
      benchmarkCloseByDate.set(point.time.slice(0, 10), point.close);
    }
  });

  const stockReturns: Array<number | null> = points.map(() => null);
  const benchmarkReturns: Array<number | null> = points.map(() => null);

  points.forEach((point, index) => {
    const previousPoint = points[index - 1];
    const benchmarkClose = benchmarkCloseByDate.get(point.time.slice(0, 10));
    const previousBenchmarkClose = previousPoint
      ? benchmarkCloseByDate.get(previousPoint.time.slice(0, 10))
      : undefined;

    if (
      finiteNumber(point.close) &&
      finiteNumber(previousPoint?.close) &&
      previousPoint.close !== 0
    ) {
      stockReturns[index] = point.close / previousPoint.close - 1;
    }

    if (
      finiteNumber(benchmarkClose) &&
      finiteNumber(previousBenchmarkClose) &&
      previousBenchmarkClose !== 0
    ) {
      benchmarkReturns[index] = benchmarkClose / previousBenchmarkClose - 1;
    }
  });

  points.forEach((point, index) => {
    const baseIndex = index - params.relativeStrengthLookback;
    const basePoint = points[baseIndex];
    const benchmarkClose = benchmarkCloseByDate.get(point.time.slice(0, 10));
    const baseBenchmarkClose = basePoint
      ? benchmarkCloseByDate.get(basePoint.time.slice(0, 10))
      : undefined;

    if (
      baseIndex >= 0 &&
      finiteNumber(point.close) &&
      finiteNumber(basePoint?.close) &&
      basePoint.close !== 0 &&
      finiteNumber(benchmarkClose) &&
      finiteNumber(baseBenchmarkClose) &&
      baseBenchmarkClose !== 0
    ) {
      const stockReturn = point.close / basePoint.close - 1;
      const benchmarkReturn = benchmarkClose / baseBenchmarkClose - 1;
      relativeStrength[index] = (stockReturn - benchmarkReturn) * 100;
    }
  });

  function collectPairedReturns(index: number, period: number) {
    const startIndex = Math.max(1, index + 1 - period);
    const pairedReturns: Array<{ stock: number; benchmark: number }> = [];

    for (let cursor = startIndex; cursor <= index; cursor += 1) {
      const stockReturn = stockReturns[cursor];
      const benchmarkReturn = benchmarkReturns[cursor];

      if (finiteNumber(stockReturn) && finiteNumber(benchmarkReturn)) {
        pairedReturns.push({ stock: stockReturn, benchmark: benchmarkReturn });
      }
    }

    return pairedReturns;
  }

  points.forEach((_, index) => {
    const period = Math.max(5, Math.round(params.betaPeriod));
    const pairedReturns = collectPairedReturns(index, period);
    const minSamples = Math.max(8, Math.ceil(period * 0.6));

    if (pairedReturns.length < minSamples) return;

    const stockAverage =
      pairedReturns.reduce((sum, item) => sum + item.stock, 0) / pairedReturns.length;
    const benchmarkAverage =
      pairedReturns.reduce((sum, item) => sum + item.benchmark, 0) / pairedReturns.length;
    const covariance = pairedReturns.reduce(
      (sum, item) => sum + (item.stock - stockAverage) * (item.benchmark - benchmarkAverage),
      0
    );
    const variance = pairedReturns.reduce(
      (sum, item) => sum + (item.benchmark - benchmarkAverage) ** 2,
      0
    );

    beta[index] = variance > 0 ? covariance / variance : null;
  });

  points.forEach((_, index) => {
    const period = Math.max(5, Math.round(params.correlationPeriod));
    const pairedReturns = collectPairedReturns(index, period);
    const minSamples = Math.max(8, Math.ceil(period * 0.6));

    if (pairedReturns.length < minSamples) return;

    const stockAverage =
      pairedReturns.reduce((sum, item) => sum + item.stock, 0) / pairedReturns.length;
    const benchmarkAverage =
      pairedReturns.reduce((sum, item) => sum + item.benchmark, 0) / pairedReturns.length;
    const covariance = pairedReturns.reduce(
      (sum, item) => sum + (item.stock - stockAverage) * (item.benchmark - benchmarkAverage),
      0
    );
    const stockVariance = pairedReturns.reduce(
      (sum, item) => sum + (item.stock - stockAverage) ** 2,
      0
    );
    const benchmarkVariance = pairedReturns.reduce(
      (sum, item) => sum + (item.benchmark - benchmarkAverage) ** 2,
      0
    );
    const denominator = Math.sqrt(stockVariance * benchmarkVariance);

    correlation[index] =
      denominator > 0 ? Math.max(-1, Math.min(1, covariance / denominator)) : null;
  });

  return { relativeStrength, beta, correlation };
}

function formatPrice(value: number | null | undefined) {
  if (!finiteNumber(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: value >= 1000 ? 2 : 4,
  });
}

function createLineSeriesData(): LineSeriesData {
  return {
    maShort: [],
    maMiddle: [],
    maLong: [],
    emaFast: [],
    emaSlow: [],
    wma: [],
    hma: [],
    vwma: [],
    vwap: [],
    psar: [],
    bollingerUpper: [],
    bollingerMiddle: [],
    bollingerLower: [],
    bbWidth: [],
    stdDev: [],
    choppiness: [],
    donchianUpper: [],
    donchianLower: [],
    ichimokuConversion: [],
    ichimokuBase: [],
    ichimokuSpanA: [],
    ichimokuSpanB: [],
    ichimokuLagging: [],
    supertrendUp: [],
    supertrendDown: [],
    keltnerUpper: [],
    keltnerMiddle: [],
    keltnerLower: [],
    rsi: [],
    macd: [],
    macdSignal: [],
    kdK: [],
    kdD: [],
    momentum: [],
    tsi: [],
    tsiSignal: [],
    awesomeOscillator: [],
    ultimateOscillator: [],
    atr: [],
    adx: [],
    plusDi: [],
    minusDi: [],
    aroonUp: [],
    aroonDown: [],
    obv: [],
    obvMa: [],
    mfi: [],
    cmf: [],
    adLine: [],
    pvt: [],
    relativeStrength: [],
    beta: [],
    correlation: [],
    cci: [],
    williamsR: [],
    roc: [],
    stochRsiK: [],
    stochRsiD: [],
    trix: [],
    trixSignal: [],
    pivot: [],
    pivotR1: [],
    pivotS1: [],
    support: [],
    resistance: [],
    gapUp: [],
    gapDown: [],
  };
}

function pushLine(target: LineData<Time>[], time: Time, value: number | null | undefined) {
  if (!finiteNumber(value)) return;

  target.push({ time, value });
}

function pushSupertrendLine(
  upTarget: PlotLineData[],
  downTarget: PlotLineData[],
  time: Time,
  value: number | null | undefined,
  direction: 1 | -1 | null
) {
  if (!finiteNumber(value) || direction === null) {
    upTarget.push({ time });
    downTarget.push({ time });
    return;
  }

  if (direction === 1) {
    upTarget.push({ time, value });
    downTarget.push({ time });
    return;
  }

  downTarget.push({ time, value });
  upTarget.push({ time });
}

function buildSeriesData(
  chartData: ChartPoint[],
  indicatorData: StockIndicatorPoint[],
  volumeValueKey: Props["volumeValueKey"],
  timeMode: ChartTimeMode,
  params: IndicatorParameters,
  benchmarkData?: ChartPoint[]
): BuiltSeriesData {
  const indicatorByTime = new Map(indicatorData.map((point) => [point.time.slice(0, 10), point]));
  const closes = chartData.map((point) => point.close);
  const emaFast = calculateEma(closes, params.emaFast);
  const emaSlow = calculateEma(closes, params.emaSlow);
  const wma = calculateWma(closes, params.wmaPeriod);
  const hma = calculateHma(closes, params.hmaPeriod);
  const vwma = calculateVwma(chartData, params.vwmaPeriod);
  const vwap = calculateVwap(chartData);
  const psar = calculateParabolicSar(chartData);
  const donchian = calculateDonchian(chartData, params.donchianPeriod);
  const ichimoku = calculateIchimoku(chartData, params);
  const supertrend = calculateSupertrend(
    chartData,
    params.supertrendAtrPeriod,
    params.supertrendMultiplier
  );
  const keltner = calculateKeltner(chartData, params);
  const rsi = calculateRsi(closes, params.rsiPeriod);
  const macd = calculateMacd(closes, params.macdFast, params.macdSlow, params.macdSignal);
  const kd = calculateKd(chartData, params.kdPeriod);
  const atr = calculateAtr(chartData, params.atrPeriod);
  const stdDev = closes.map((_, index) => standardDeviation(closes, index, params.stdDevPeriod));
  const choppiness = calculateChoppiness(chartData, params.choppinessPeriod);
  const momentum = calculateMomentum(closes, params.momentumPeriod);
  const tsi = calculateTsi(
    closes,
    params.tsiShortPeriod,
    params.tsiLongPeriod,
    params.tsiSignalPeriod
  );
  const awesomeOscillator = calculateAwesomeOscillator(
    chartData,
    params.awesomeFastPeriod,
    params.awesomeSlowPeriod
  );
  const ultimateOscillator = calculateUltimateOscillator(
    chartData,
    params.ultimateShortPeriod,
    params.ultimateMiddlePeriod,
    params.ultimateLongPeriod
  );
  const dmi = calculateDmi(chartData, params.adxPeriod);
  const aroon = calculateAroon(chartData, params.aroonPeriod);
  const obv = calculateObv(chartData);
  const obvMa = obv.map((_, index) => movingAverage(obv, index, params.obvMa));
  const mfi = calculateMfi(chartData, params.mfiPeriod);
  const cmf = calculateChaikinMoneyFlow(chartData, params.cmfPeriod);
  const adLine = calculateAccumulationDistribution(chartData);
  const pvt = calculatePriceVolumeTrend(chartData);
  const cci = calculateCci(chartData, params.cciPeriod);
  const williamsR = calculateWilliamsR(chartData, params.williamsRPeriod);
  const roc = calculateRoc(closes, params.rocPeriod);
  const stochRsi = calculateStochRsi(
    rsi,
    params.stochRsiPeriod,
    params.stochRsiSmoothK,
    params.stochRsiSmoothD
  );
  const trix = calculateTrix(closes, params.trixPeriod, params.trixSignal);
  const pivots = calculatePivots(chartData, params.pivotLookback);
  const supportResistance = calculateSupportResistance(
    chartData,
    params.supportResistanceLookback
  );
  const gaps = calculateGaps(chartData, params.gapMinPct);
  const relativeMetrics = calculateRelativeMetrics(chartData, benchmarkData, params);
  const candles: CandlestickData<Time>[] = [];
  const line: LineData<Time>[] = [];
  const volumesSeries: HistogramData<Time>[] = [];
  const macdHistogram: HistogramData<Time>[] = [];
  const lines = createLineSeriesData();

  chartData.forEach((point, index) => {
    if (
      !finiteNumber(point.open) ||
      !finiteNumber(point.high) ||
      !finiteNumber(point.low) ||
      !finiteNumber(point.close)
    ) {
      return;
    }

    const timeKey = point.time.slice(0, 10);
    const time = chartTime(point.time, timeMode);
    const color = point.close >= point.open ? upColor : downColor;
    const indicator = indicatorByTime.get(timeKey);
    const maShort =
      indicator?.ma?.[`ma${params.maShort}`] ?? movingAverage(closes, index, params.maShort);
    const maMiddle =
      indicator?.ma?.[`ma${params.maMiddle}`] ?? movingAverage(closes, index, params.maMiddle);
    const maLong =
      indicator?.ma?.[`ma${params.maLong}`] ?? movingAverage(closes, index, params.maLong);
    const bbMiddle = movingAverage(closes, index, params.bollingerPeriod);
    const bbStd = standardDeviation(closes, index, params.bollingerPeriod);
    const bbWidthMiddle = movingAverage(closes, index, params.bbWidthPeriod);
    const bbWidthStd = standardDeviation(closes, index, params.bbWidthPeriod);
    const macdHistogramValue = macd.histogram[index];

    candles.push({
      time,
      open: point.open,
      high: point.high,
      low: point.low,
      close: point.close,
      color,
      borderColor: color,
      wickColor: color,
    });
    line.push({
      time,
      value: point.close,
      color,
    });

    const volumeValue = volumeValueKey === "trade_value" ? point.trade_value : point.volume;
    if (finiteNumber(volumeValue)) {
      volumesSeries.push({
        time,
        value: volumeValue,
        color: point.close >= point.open ? "rgba(220, 38, 38, 0.24)" : "rgba(5, 150, 105, 0.24)",
      });
    }

    if (finiteNumber(macdHistogramValue)) {
      macdHistogram.push({
        time,
        value: macdHistogramValue,
        color: macdHistogramValue >= 0 ? "rgba(220, 38, 38, 0.35)" : "rgba(5, 150, 105, 0.35)",
      });
    }

    pushLine(lines.maShort, time, maShort);
    pushLine(lines.maMiddle, time, maMiddle);
    pushLine(lines.maLong, time, maLong);
    pushLine(lines.emaFast, time, emaFast[index]);
    pushLine(lines.emaSlow, time, emaSlow[index]);
    pushLine(lines.wma, time, wma[index]);
    pushLine(lines.hma, time, hma[index]);
    pushLine(lines.vwma, time, vwma[index]);
    pushLine(lines.vwap, time, vwap[index]);
    pushLine(lines.psar, time, psar[index]);
    pushLine(lines.donchianUpper, time, donchian[index].upper);
    pushLine(lines.donchianLower, time, donchian[index].lower);
    pushLine(lines.ichimokuConversion, time, ichimoku.conversion[index]);
    pushLine(lines.ichimokuBase, time, ichimoku.base[index]);
    pushLine(lines.ichimokuSpanA, time, ichimoku.spanA[index]);
    pushLine(lines.ichimokuSpanB, time, ichimoku.spanB[index]);
    pushLine(lines.ichimokuLagging, time, ichimoku.lagging[index]);
    pushSupertrendLine(
      lines.supertrendUp,
      lines.supertrendDown,
      time,
      supertrend[index].value,
      supertrend[index].direction
    );
    pushLine(lines.keltnerUpper, time, keltner[index].upper);
    pushLine(lines.keltnerMiddle, time, keltner[index].middle);
    pushLine(lines.keltnerLower, time, keltner[index].lower);
    pushLine(lines.rsi, time, indicator?.rsi?.rsi14 ?? rsi[index]);
    pushLine(lines.macd, time, macd.macd[index]);
    pushLine(lines.macdSignal, time, macd.signal[index]);
    pushLine(lines.kdK, time, kd[index].k);
    pushLine(lines.kdD, time, kd[index].d);
    pushLine(lines.atr, time, indicator?.atr?.atr14 ?? atr[index]);
    pushLine(lines.adx, time, indicator?.adx?.adx14 ?? dmi[index].adx);
    pushLine(lines.plusDi, time, indicator?.adx?.plus_di14 ?? dmi[index].plusDi);
    pushLine(lines.minusDi, time, indicator?.adx?.minus_di14 ?? dmi[index].minusDi);
    pushLine(lines.aroonUp, time, aroon[index].up);
    pushLine(lines.aroonDown, time, aroon[index].down);
    pushLine(lines.obv, time, obv[index]);
    pushLine(lines.obvMa, time, obvMa[index]);
    pushLine(lines.mfi, time, indicator?.mfi?.mfi14 ?? mfi[index]);
    pushLine(lines.cci, time, cci[index]);
    pushLine(lines.williamsR, time, williamsR[index]);
    pushLine(lines.roc, time, indicator?.roc?.roc12 ?? roc[index]);
    pushLine(lines.stochRsiK, time, stochRsi.k[index]);
    pushLine(lines.stochRsiD, time, stochRsi.d[index]);
    pushLine(lines.trix, time, trix.trix[index]);
    pushLine(lines.trixSignal, time, trix.signal[index]);

    if (bbMiddle !== null && bbStd !== null) {
      pushLine(lines.bollingerUpper, time, bbMiddle + bbStd * params.bollingerStdDev);
      pushLine(lines.bollingerMiddle, time, bbMiddle);
      pushLine(lines.bollingerLower, time, bbMiddle - bbStd * params.bollingerStdDev);
    }

    if (finiteNumber(bbWidthMiddle) && finiteNumber(bbWidthStd) && bbWidthMiddle !== 0) {
      pushLine(
        lines.bbWidth,
        time,
        ((bbWidthStd * params.bollingerStdDev * 2) / bbWidthMiddle) * 100
      );
    }

    pushLine(lines.stdDev, time, stdDev[index]);
    pushLine(lines.choppiness, time, choppiness[index]);
    pushLine(lines.momentum, time, momentum[index]);
    pushLine(lines.tsi, time, tsi.tsi[index]);
    pushLine(lines.tsiSignal, time, tsi.signal[index]);
    pushLine(lines.awesomeOscillator, time, awesomeOscillator[index]);
    pushLine(lines.ultimateOscillator, time, ultimateOscillator[index]);
    pushLine(lines.cmf, time, cmf[index]);
    pushLine(lines.adLine, time, adLine[index]);
    pushLine(lines.pvt, time, pvt[index]);
    pushLine(lines.relativeStrength, time, relativeMetrics.relativeStrength[index]);
    pushLine(lines.beta, time, relativeMetrics.beta[index]);
    pushLine(lines.correlation, time, relativeMetrics.correlation[index]);
    pushLine(lines.pivot, time, pivots[index].pivot);
    pushLine(lines.pivotR1, time, pivots[index].r1);
    pushLine(lines.pivotS1, time, pivots[index].s1);
    pushLine(lines.support, time, supportResistance[index].support);
    pushLine(lines.resistance, time, supportResistance[index].resistance);
    pushLine(lines.gapUp, time, gaps[index].up);
    pushLine(lines.gapDown, time, gaps[index].down);
  });

  return {
    candles,
    line,
    volumes: volumesSeries,
    macdHistogram,
    lines,
  };
}

function mergeIndicators(indicators: IndicatorSettings | undefined, showMovingAverages: boolean) {
  return {
    ...defaultLightweightIndicators,
    ...(indicators ?? {}),
    ma: showMovingAverages && (indicators?.ma ?? defaultLightweightIndicators.ma),
  };
}

function chartRightPaddingBars(timeMode: ChartTimeMode) {
  return timeMode === "intraday" ? 34 : 10;
}

function chartKeyboardBoundaryPaddingBars(timeMode: ChartTimeMode) {
  return timeMode === "intraday" ? 96 : 30;
}

function logicalRange(from: number, to: number): LogicalRange {
  return {
    from: from as Logical,
    to: to as Logical,
  };
}

function buildDefaultVisibleLogicalRange(
  pointCount: number,
  timeMode: ChartTimeMode
): LogicalRange | null {
  if (pointCount <= 0) return null;
  if (timeMode !== "intraday") return null;

  const lastIndex = pointCount - 1;
  const rightPadding = chartRightPaddingBars(timeMode);
  const targetVisibleBars = Math.min(Math.max(pointCount, 54), 120);
  const to = lastIndex + rightPadding;

  return logicalRange(Math.max(0, to - targetVisibleBars), to);
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
}: Props) {
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
    chartData,
    overlaySize.height,
    overlaySize.width,
    params.macdFast,
    params.macdSignal,
    params.macdSlow,
    params.rsiPeriod,
    timeMode,
    visibleChartPointEntries,
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
        activeIndicators.candlestickPatterns || activeIndicators.divergence
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
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#475569",
        fontSize: 12,
        fontFamily:
          'ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        attributionLogo: false,
        panes: {
          separatorColor: "#e2e8f0",
          separatorHoverColor: "#cbd5e1",
          enableResize: true,
        },
      },
      grid: {
        vertLines: { color: "#f1f5f9" },
        horzLines: { color: "#e2e8f0" },
      },
      rightPriceScale: {
        borderColor: "#dbe3ef",
        scaleMargins: {
          top: 0.07,
          bottom: activeIndicators.volume ? 0.27 : 0.08,
        },
      },
      timeScale: {
        borderColor: "#dbe3ef",
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
          color: "#94a3b8",
          labelBackgroundColor: "#0f172a",
          style: 2,
        },
        horzLine: {
          color: "#94a3b8",
          labelBackgroundColor: "#0f172a",
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
        color: "#0f172a",
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
        color: "rgba(100, 116, 139, 0.18)",
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
      addMainLine(seriesData.lines.emaFast, `EMA${params.emaFast}`, "#0891b2");
      addMainLine(seriesData.lines.emaSlow, `EMA${params.emaSlow}`, "#f43f5e");
    }

    if (activeIndicators.wma) {
      addMainLine(seriesData.lines.wma, `WMA${params.wmaPeriod}`, "#0ea5e9");
    }

    if (activeIndicators.hma) {
      addMainLine(seriesData.lines.hma, `HMA${params.hmaPeriod}`, "#be185d");
    }

    if (activeIndicators.vwma) {
      addMainLine(seriesData.lines.vwma, `VWMA${params.vwmaPeriod}`, "#16a34a", {
        dashed: true,
      });
    }

    if (activeIndicators.bollinger) {
      addMainLine(seriesData.lines.bollingerUpper, "BOLL Upper", "#0284c7", { lineWidth: 1 });
      addMainLine(seriesData.lines.bollingerMiddle, "BOLL Mid", "#38bdf8", {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.bollingerLower, "BOLL Lower", "#0284c7", { lineWidth: 1 });
    }

    if (activeIndicators.vwap) {
      addMainLine(seriesData.lines.vwap, "VWAP", "#334155", { dashed: true });
    }

    if (activeIndicators.psar) {
      addMainLine(seriesData.lines.psar, "SAR", "#7c3aed", { pointsOnly: true, lineWidth: 1 });
    }

    if (activeIndicators.donchian) {
      addMainLine(seriesData.lines.donchianUpper, `DONCH${params.donchianPeriod} U`, "#65a30d", {
        lineWidth: 1,
      });
      addMainLine(seriesData.lines.donchianLower, `DONCH${params.donchianPeriod} L`, "#65a30d", {
        lineWidth: 1,
      });
    }

    if (activeIndicators.ichimoku) {
      addMainLine(
        seriesData.lines.ichimokuConversion,
        `Tenkan${params.ichimokuConversionPeriod}`,
        "#dc2626",
        { lineWidth: 1 }
      );
      addMainLine(
        seriesData.lines.ichimokuBase,
        `Kijun${params.ichimokuBasePeriod}`,
        "#2563eb",
        { lineWidth: 1 }
      );
      addMainLine(seriesData.lines.ichimokuSpanA, "Senkou A", "#059669", {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.ichimokuSpanB, "Senkou B", "#b45309", {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.ichimokuLagging, "Chikou", "#64748b", {
        lineWidth: 1,
        dashed: true,
      });
    }

    if (activeIndicators.supertrend) {
      addMainLine(seriesData.lines.supertrendUp, `ST${params.supertrendAtrPeriod}`, "#059669", {
        lineWidth: 2,
      });
      addMainLine(seriesData.lines.supertrendDown, `ST${params.supertrendAtrPeriod}`, "#dc2626", {
        lineWidth: 2,
      });
    }

    if (activeIndicators.keltner) {
      addMainLine(seriesData.lines.keltnerUpper, `KC${params.keltnerPeriod} U`, "#0f766e", {
        lineWidth: 1,
      });
      addMainLine(seriesData.lines.keltnerMiddle, `KC${params.keltnerPeriod} M`, "#14b8a6", {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.keltnerLower, `KC${params.keltnerPeriod} L`, "#0f766e", {
        lineWidth: 1,
      });
    }

    if (activeIndicators.pivotPoints) {
      addMainLine(seriesData.lines.pivot, "Pivot", "#475569", { lineWidth: 1, dashed: true });
      addMainLine(seriesData.lines.pivotR1, "R1", "#dc2626", { lineWidth: 1, dashed: true });
      addMainLine(seriesData.lines.pivotS1, "S1", "#059669", { lineWidth: 1, dashed: true });
    }

    if (activeIndicators.supportResistance) {
      addMainLine(seriesData.lines.resistance, `R${params.supportResistanceLookback}`, "#ef4444", {
        lineWidth: 1,
        dashed: true,
      });
      addMainLine(seriesData.lines.support, `S${params.supportResistanceLookback}`, "#10b981", {
        lineWidth: 1,
        dashed: true,
      });
    }

    if (activeIndicators.gap) {
      addMainLine(seriesData.lines.gapUp, `Gap Up ${params.gapMinPct}%`, "#dc2626", {
        pointsOnly: true,
        lineWidth: 1,
      });
      addMainLine(seriesData.lines.gapDown, `Gap Down ${params.gapMinPct}%`, "#059669", {
        pointsOnly: true,
        lineWidth: 1,
      });
    }

    if (activeIndicators.rsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.rsi, `RSI${params.rsiPeriod}`, "#c026d3");
    }

    if (activeIndicators.macd) {
      const paneIndex = addIndicatorPane(104);
      const histogramSeries = chart.addSeries(
        HistogramSeries,
        {
          title: "MACD H",
          color: "rgba(100, 116, 139, 0.35)",
          priceLineVisible: false,
          lastValueVisible: true,
          priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        },
        paneIndex
      );
      histogramSeries.setData(seriesData.macdHistogram);
      addPaneLine(paneIndex, seriesData.lines.macd, "MACD", "#2563eb", { lineWidth: 1 });
      addPaneLine(paneIndex, seriesData.lines.macdSignal, "Signal", "#f59e0b", { lineWidth: 1 });
    }

    if (activeIndicators.kd) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.kdK, `K${params.kdPeriod}`, "#2563eb");
      addPaneLine(paneIndex, seriesData.lines.kdD, `D${params.kdPeriod}`, "#f59e0b");
    }

    if (activeIndicators.momentum) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.momentum, `MOM${params.momentumPeriod}`, "#0e7490");
    }

    if (activeIndicators.tsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.tsi, `TSI${params.tsiLongPeriod}/${params.tsiShortPeriod}`, "#7c3aed");
      addPaneLine(paneIndex, seriesData.lines.tsiSignal, `TSI Sig${params.tsiSignalPeriod}`, "#f59e0b", {
        lineWidth: 1,
      });
    }

    if (activeIndicators.awesomeOscillator) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.awesomeOscillator,
        `AO${params.awesomeFastPeriod}/${params.awesomeSlowPeriod}`,
        "#db2777"
      );
    }

    if (activeIndicators.ultimateOscillator) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.ultimateOscillator,
        `UO${params.ultimateShortPeriod}/${params.ultimateMiddlePeriod}/${params.ultimateLongPeriod}`,
        "#9333ea"
      );
    }

    if (activeIndicators.atr) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.atr, `ATR${params.atrPeriod}`, "#f97316");
    }

    if (activeIndicators.bbWidth) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.bbWidth, `BB Width${params.bbWidthPeriod}`, "#0284c7");
    }

    if (activeIndicators.stdDev) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.stdDev, `StdDev${params.stdDevPeriod}`, "#334155");
    }

    if (activeIndicators.choppiness) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.choppiness, `CHOP${params.choppinessPeriod}`, "#92400e");
    }

    if (activeIndicators.adx) {
      const paneIndex = addIndicatorPane(104);
      addPaneLine(paneIndex, seriesData.lines.adx, `ADX${params.adxPeriod}`, "#7c3aed");
      addPaneLine(paneIndex, seriesData.lines.plusDi, "+DI", "#dc2626", { lineWidth: 1 });
      addPaneLine(paneIndex, seriesData.lines.minusDi, "-DI", "#059669", { lineWidth: 1 });
    }

    if (activeIndicators.aroon) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.aroonUp, `Aroon Up${params.aroonPeriod}`, "#dc2626");
      addPaneLine(paneIndex, seriesData.lines.aroonDown, `Aroon Down${params.aroonPeriod}`, "#059669");
    }

    if (activeIndicators.obv) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.obv, "OBV", "#334155");
      addPaneLine(paneIndex, seriesData.lines.obvMa, `OBV MA${params.obvMa}`, "#f59e0b", {
        lineWidth: 1,
      });
    }

    if (activeIndicators.mfi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.mfi, `MFI${params.mfiPeriod}`, "#0f766e");
    }

    if (activeIndicators.cmf) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.cmf, `CMF${params.cmfPeriod}`, "#059669");
    }

    if (activeIndicators.adLine) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.adLine, "A/D", "#475569");
    }

    if (activeIndicators.pvt) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.pvt, "PVT", "#0369a1");
    }

    if (activeIndicators.relativeStrength) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.relativeStrength,
        `RS${params.relativeStrengthLookback}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        "#7c3aed"
      );
    }

    if (activeIndicators.beta) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.beta,
        `Beta${params.betaPeriod}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        "#0f766e"
      );
    }

    if (activeIndicators.correlation) {
      const paneIndex = addIndicatorPane();
      addPaneLine(
        paneIndex,
        seriesData.lines.correlation,
        `Corr${params.correlationPeriod}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`,
        "#0369a1"
      );
    }

    if (activeIndicators.cci) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.cci, `CCI${params.cciPeriod}`, "#4f46e5");
    }

    if (activeIndicators.williamsR) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.williamsR, `W%R${params.williamsRPeriod}`, "#db2777");
    }

    if (activeIndicators.roc) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.roc, `ROC${params.rocPeriod}`, "#0e7490");
    }

    if (activeIndicators.stochRsi) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.stochRsiK, "StochRSI K", "#2563eb");
      addPaneLine(paneIndex, seriesData.lines.stochRsiD, "StochRSI D", "#f59e0b");
    }

    if (activeIndicators.trix) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.trix, `TRIX${params.trixPeriod}`, "#7c3aed");
      addPaneLine(paneIndex, seriesData.lines.trixSignal, `Signal${params.trixSignal}`, "#f59e0b", {
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
    });
    resizeObserver.observe(container);

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
    height,
    params,
    scheduleOverlayRevision,
    seriesData,
    timeMode,
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
      <div className="flex h-[520px] items-center justify-center border-t border-slate-200 bg-white text-sm text-slate-500">
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
    <div className="border-t border-slate-200 bg-white">
      {showHeader ? (
        <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-200 px-4 py-1.5">
          <div className="flex min-w-0 items-baseline gap-2">
            <span className="shrink-0 text-xs font-bold text-slate-950">專業 K 線</span>
            <span className="truncate text-[11px] font-medium text-slate-500">
              {label} · {seriesData.candles.length.toLocaleString("zh-TW")} 根 · 可拖移縮放
            </span>
          </div>
          <div className="flex shrink-0 flex-wrap items-center justify-end gap-3 text-[11px] font-semibold text-slate-600">
            {activeIndicators.ma ? (
              <>
                <span className="inline-flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: maColors.maShort }} />
                  MA{params.maShort}
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: maColors.maMiddle }} />
                  MA{params.maMiddle}
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: maColors.maLong }} />
                  MA{params.maLong}
                </span>
              </>
            ) : null}
            {activeIndicators.volume ? <span className="text-slate-400">{volumePanelLabel}</span> : null}
          </div>
        </div>
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
          <div className="pointer-events-none absolute left-3 top-3 z-20 w-[15.5rem] border border-slate-300 bg-white/95 px-3 py-2 text-[11px] shadow-sm backdrop-blur">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="font-bold text-slate-950">
                {drawingTypeLabel(selectedProjectedDrawing.drawing.type)}
              </span>
              <span
                className={[
                  "font-bold tabular-nums",
                  selectedDrawingMetrics.direction === "up"
                    ? "text-red-500"
                    : selectedDrawingMetrics.direction === "down"
                      ? "text-emerald-600"
                      : "text-slate-600",
                ].join(" ")}
              >
                {selectedDrawingMetrics.labels.percentChange}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-500">
              <span>價差</span>
              <span className="text-right font-semibold text-slate-900 tabular-nums">
                {selectedDrawingMetrics.labels.priceDiff}
              </span>
              <span>區間</span>
              <span className="text-right font-semibold text-slate-900 tabular-nums">
                {selectedDrawingMetrics.labels.low} - {selectedDrawingMetrics.labels.high}
              </span>
              <span>K棒 / 時間</span>
              <span className="text-right font-semibold text-slate-900 tabular-nums">
                {[selectedDrawingMetrics.labels.bars, selectedDrawingMetrics.labels.duration]
                  .filter(Boolean)
                  .join(" / ") || "-"}
              </span>
              <span>斜率</span>
              <span className="text-right font-semibold text-slate-900 tabular-nums">
                {selectedDrawingMetrics.labels.slope ?? "-"}
              </span>
              {selectedDrawingMetrics.lineAnalysis ? (
                <>
                  <span>線位狀態</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.lineAnalysis.labels.role} · {selectedDrawingMetrics.lineAnalysis.labels.status}
                  </span>
                  <span>距線</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.lineAnalysis.labels.distance} / {selectedDrawingMetrics.lineAnalysis.labels.distancePct}
                  </span>
                  <span>觸碰</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.lineAnalysis.labels.touchCount}
                  </span>
                </>
              ) : null}
              {selectedDrawingMetrics.zoneAnalysis ? (
                <>
                  <span>區間狀態</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.zoneAnalysis.labels.role} · {selectedDrawingMetrics.zoneAnalysis.labels.status}
                  </span>
                  <span>上 / 中 / 下</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.zoneAnalysis.labels.upper} / {selectedDrawingMetrics.zoneAnalysis.labels.mid} / {selectedDrawingMetrics.zoneAnalysis.labels.lower}
                  </span>
                  <span>位置 / 寬度</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.zoneAnalysis.labels.position} / {selectedDrawingMetrics.zoneAnalysis.labels.widthPct}
                  </span>
                  <span>上 / 下觸碰</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.zoneAnalysis.labels.upperTouches} / {selectedDrawingMetrics.zoneAnalysis.labels.lowerTouches}
                  </span>
                  <span>區間波動</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.zoneAnalysis.labels.compression}
                  </span>
                </>
              ) : null}
              {selectedDrawingMetrics.fibonacciAnalysis ? (
                <>
                  <span>Fib 狀態</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.fibonacciAnalysis.labels.trend} · {selectedDrawingMetrics.fibonacciAnalysis.labels.status}
                  </span>
                  <span>最近位階</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.fibonacciAnalysis.labels.nearest}
                  </span>
                  <span>距位階</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.fibonacciAnalysis.labels.nearestDistance} / {selectedDrawingMetrics.fibonacciAnalysis.labels.nearestDistancePct}
                  </span>
                  <span>位置 / 延伸</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.fibonacciAnalysis.labels.rangePosition} / {selectedDrawingMetrics.fibonacciAnalysis.labels.extension}
                  </span>
                </>
              ) : null}
              {selectedDrawingMetrics.anchoredVwapAnalysis ? (
                <>
                  <span>錨定 VWAP</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.anchoredVwapAnalysis.labels.vwap}
                  </span>
                  <span>VWAP 狀態</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.anchoredVwapAnalysis.labels.status}
                  </span>
                  <span>距 VWAP</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.anchoredVwapAnalysis.labels.distance} / {selectedDrawingMetrics.anchoredVwapAnalysis.labels.distancePct}
                  </span>
                  <span>累積量 / K棒</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.anchoredVwapAnalysis.labels.cumulativeVolume} / {selectedDrawingMetrics.anchoredVwapAnalysis.labels.barCount}
                  </span>
                </>
              ) : null}
              {selectedDrawingMetrics.volumeProfileAnalysis ? (
                <>
                  <span>POC</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.volumeProfileAnalysis.labels.poc}
                  </span>
                  <span>價值區間</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.volumeProfileAnalysis.labels.valueArea}
                  </span>
                  <span>現價位置</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.volumeProfileAnalysis.labels.latestPosition}
                  </span>
                  <span>買賣差</span>
                  <span className="text-right font-semibold text-slate-900 tabular-nums">
                    {selectedDrawingMetrics.volumeProfileAnalysis.labels.imbalance}
                  </span>
                </>
              ) : null}
            </div>
            {selectedDrawingSummary ? (
              <div className="mt-2 border-t border-slate-100 pt-1 text-[10px] font-medium leading-relaxed text-slate-500">
                {selectedDrawingSummary.text}
              </div>
            ) : null}
          </div>
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
          {projectedCloudPolygons.map((polygon) => (
            <polygon
              key={polygon.id}
              points={polygon.points}
              fill={polygon.tone === "bullish" ? "#10b981" : "#ef4444"}
              opacity={0.1}
              pointerEvents="none"
            />
          ))}
          {projectedGapZones.map((zone) => {
            const color = zone.tone === "up" ? "#dc2626" : "#059669";

            return (
              <g key={zone.id} pointerEvents="none">
                <rect
                  x={zone.x}
                  y={zone.y}
                  width={zone.width}
                  height={zone.height}
                  fill={color}
                  opacity={0.055}
                />
                <rect
                  x={zone.x}
                  y={zone.y}
                  width={zone.width}
                  height={zone.height}
                  fill="none"
                  stroke={color}
                  strokeDasharray="4 4"
                  strokeWidth={1}
                  opacity={0.28}
                />
                {zone.height >= 10 ? (
                  <text
                    x={Math.max(8, Math.min(zone.x + 5, overlaySize.width - 118))}
                    y={Math.max(12, zone.y + 11)}
                    className="fill-slate-500 text-[10px] font-semibold tabular-nums"
                    opacity={0.82}
                  >
                    {zone.label}
                  </text>
                ) : null}
              </g>
            );
          })}
          {projectedSupportResistance.map((level) => {
            const color = level.tone === "resistance" ? "#dc2626" : "#059669";
            const prefix = level.tone === "resistance" ? "R" : "S";
            const label = `${prefix} ${level.priceLabel} x${level.strength}`;
            const labelX = Math.max(62, overlaySize.width - 164);
            const labelY = Math.max(14, Math.min(level.y - 6, overlaySize.height - 12));

            return (
              <g key={level.id} pointerEvents="none" opacity={level.opacity}>
                <line
                  x1={56}
                  y1={level.y}
                  x2={Math.max(56, overlaySize.width - 74)}
                  y2={level.y}
                  stroke={color}
                  strokeDasharray="7 5"
                  strokeWidth={1.1}
                />
                <rect
                  x={labelX - 5}
                  y={labelY - 10}
                  width={98}
                  height={15}
                  rx={2}
                  fill="white"
                  opacity={0.86}
                />
                <text
                  x={labelX}
                  y={labelY}
                  className="text-[10px] font-bold tabular-nums"
                  fill={color}
                >
                  {label}
                </text>
              </g>
            );
          })}
          {projectedVolumeProfile.map((bin) => (
            <g key={bin.id} pointerEvents="none">
              <title>{`VPVR ${bin.priceLabel} · ${bin.volumeLabel}`}</title>
              <rect
                x={bin.x}
                y={bin.y}
                width={bin.width}
                height={bin.height}
                fill="#0f172a"
                opacity={bin.poc ? 0.08 : 0.035}
              />
              <rect
                x={bin.x}
                y={bin.y}
                width={bin.sellWidth}
                height={bin.height}
                fill="#059669"
                opacity={bin.poc ? 0.34 : 0.22}
              />
              <rect
                x={bin.x + bin.sellWidth}
                y={bin.y}
                width={bin.buyWidth}
                height={bin.height}
                fill="#dc2626"
                opacity={bin.poc ? 0.34 : 0.22}
              />
              {bin.poc ? (
                <>
                  <line
                    x1={Math.max(56, bin.x - 10)}
                    y1={bin.y + bin.height / 2}
                    x2={bin.x + bin.width}
                    y2={bin.y + bin.height / 2}
                    stroke="#0f172a"
                    strokeDasharray="4 4"
                    strokeWidth={1}
                    opacity={0.38}
                  />
                  <text
                    x={Math.max(62, bin.x - 68)}
                    y={Math.max(12, bin.y + bin.height / 2 - 4)}
                    className="fill-slate-700 text-[10px] font-bold tabular-nums"
                    opacity={0.86}
                  >
                    POC {bin.priceLabel}
                  </text>
                </>
              ) : null}
            </g>
          ))}
          {projectedTechnicalSignals.map((signal) => {
            const color =
              signal.tone === "bullish"
                ? "#dc2626"
                : signal.tone === "bearish"
                  ? "#059669"
                  : "#7c3aed";
            const labelWidth = Math.max(58, signal.label.length * 11 + 14);
            const preferLeft = signal.x + labelWidth + 14 > overlaySize.width - 68;
            const labelX = preferLeft ? Math.max(6, signal.x - labelWidth - 10) : signal.x + 10;
            const labelY = Math.max(12, Math.min(signal.y - 10, overlaySize.height - 22));
            const connectorX = preferLeft ? labelX + labelWidth : labelX;

            return (
              <g key={signal.id} pointerEvents="none">
                <title>{`${signal.timeLabel} ${signal.label} ${signal.priceLabel}`}</title>
                {signal.line ? (
                  <line
                    x1={signal.line[0].x}
                    y1={signal.line[0].y}
                    x2={signal.line[1].x}
                    y2={signal.line[1].y}
                    stroke={color}
                    strokeWidth={1.4}
                    strokeDasharray="5 4"
                    opacity={0.64}
                  />
                ) : null}
                <line
                  x1={signal.x}
                  y1={signal.anchorY}
                  x2={connectorX}
                  y2={labelY + 9}
                  stroke="#94a3b8"
                  strokeDasharray="3 3"
                  strokeWidth={1}
                  opacity={0.56}
                />
                <circle
                  cx={signal.x}
                  cy={signal.anchorY}
                  r={3.2}
                  fill={color}
                  stroke="white"
                  strokeWidth={1.1}
                  opacity={0.92}
                />
                <rect
                  x={labelX}
                  y={labelY}
                  width={labelWidth}
                  height={18}
                  rx={2}
                  fill={color}
                  opacity={0.92}
                />
                <text
                  x={labelX + labelWidth / 2}
                  y={labelY + 12.5}
                  textAnchor="middle"
                  className="fill-white text-[10px] font-bold"
                >
                  {signal.label}
                </text>
              </g>
            );
          })}
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
                    <rect width={labelWidth} height={30} rx={3} fill="white" stroke={stroke} opacity={0.95} />
                    <text x={10} y={13} className="fill-slate-800 text-[10px] font-bold tabular-nums">
                      AVWAP {anchoredVwapAnalysis?.labels.vwap ?? drawingLabel}
                    </text>
                    <text x={10} y={25} className="fill-slate-500 text-[10px] font-semibold tabular-nums">
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
                    <rect width={labelWidth} height={38} rx={3} fill="white" stroke={actionStroke} opacity={0.96} />
                    <text x={10} y={15} className="fill-slate-800 text-[10px] font-bold tabular-nums">
                      價差 {measurementStats.priceDiffLabel} ({measurementStats.percentLabel})
                    </text>
                    <text x={10} y={30} className="fill-slate-500 text-[10px] font-semibold tabular-nums">
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
                    <rect width={labelWidth} height={labelHeight} rx={3} fill="white" stroke={actionStroke} opacity={0.96} />
                    <text x={10} y={15} className="fill-slate-800 text-[10px] font-bold tabular-nums">
                      {measurementStats.priceDiffLabel} ({measurementStats.percentLabel})
                    </text>
                    <text x={10} y={30} className="fill-slate-500 text-[10px] font-semibold tabular-nums">
                      高 {measurementStats.highLabel} / 低 {measurementStats.lowLabel}
                    </text>
                    {zoneAnalysis ? (
                      <text x={10} y={45} className="fill-slate-500 text-[10px] font-semibold tabular-nums">
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
                        fill="#0f172a"
                        opacity={bin.poc ? 0.12 : bin.valueArea ? 0.065 : 0.035}
                      />
                      <rect
                        x={bin.x}
                        y={bin.y}
                        width={bin.sellWidth}
                        height={bin.height}
                        fill="#059669"
                        opacity={bin.poc ? 0.44 : bin.valueArea ? 0.3 : 0.2}
                      />
                      <rect
                        x={bin.x + bin.sellWidth}
                        y={bin.y}
                        width={bin.buyWidth}
                        height={bin.height}
                        fill="#dc2626"
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
                    <rect width={labelWidth} height={labelHeight} rx={3} fill="white" stroke={stroke} opacity={0.95} />
                    <text x={10} y={14} className="fill-slate-800 text-[10px] font-bold tabular-nums">
                      POC {volumeProfileAnalysis?.labels.poc ?? "-"}
                    </text>
                    <text x={10} y={28} className="fill-slate-500 text-[10px] font-semibold tabular-nums">
                      VA {volumeProfileAnalysis?.labels.valueArea ?? "-"}
                    </text>
                    <text x={10} y={41} className="fill-slate-500 text-[10px] font-semibold tabular-nums">
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
                    <rect width={labelWidth} height={labelHeight} rx={3} fill="white" stroke={stroke} opacity={0.94} />
                    <text
                      x={labelWidth / 2}
                      y={12}
                      textAnchor="middle"
                      className="fill-slate-800 text-[10px] font-bold tabular-nums"
                    >
                      {zoneAnalysis ? zoneAnalysis.labels.role : drawingLabel}
                    </text>
                    {zoneAnalysis ? (
                      <text
                        x={labelWidth / 2}
                        y={27}
                        textAnchor="middle"
                        className="fill-slate-500 text-[10px] font-semibold tabular-nums"
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
                          fill={nearest && active ? "#fff7ed" : "white"}
                          stroke={stroke}
                          opacity={nearest && active ? 0.98 : 0.92}
                        />
                        <text
                          x={48}
                          y={12}
                          textAnchor="middle"
                          className="fill-slate-800 text-[10px] font-bold tabular-nums"
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
                  <rect width={66} height={18} rx={3} fill="white" stroke={stroke} opacity={0.94} />
                  <text
                    x={33}
                    y={12}
                    textAnchor="middle"
                    className="fill-slate-800 text-[10px] font-bold tabular-nums"
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
                fill="#dc2626"
                opacity={0.06}
                stroke="#dc2626"
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
                  <rect width={124} height={24} rx={3} fill="white" stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)} opacity={0.94} />
                  <text x={10} y={16} className="fill-slate-800 text-[10px] font-bold tabular-nums">
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
                    stroke="#dc2626"
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
                  <rect width={142} height={24} rx={3} fill="white" stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)} opacity={0.94} />
                  <text x={10} y={16} className="fill-slate-800 text-[10px] font-bold tabular-nums">
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
                stroke="#dc2626"
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
              fill="#dc2626"
              stroke="white"
              strokeWidth={2}
              pointerEvents="none"
            />
          ) : null}
          {drawingTool !== "cursor" ? (
            <g transform="translate(12, 12)" pointerEvents="none">
              <rect width={drawingModeBadgeWidth(drawingTool)} height={24} rx={3} fill="#0f172a" opacity={0.92} />
              <text x={12} y={16} className="fill-white text-[11px] font-bold">
                {drawingToolModeLabel(drawingTool)}
              </text>
            </g>
          ) : null}
        </svg>
      </div>
      <div className="border-t border-slate-100 px-4 py-1.5 text-right text-[10px] text-slate-400">
        Chart engine:{" "}
        <a
          href="https://www.tradingview.com/"
          target="_blank"
          rel="noreferrer"
          className="font-medium text-slate-500 hover:text-slate-700"
        >
          TradingView Lightweight Charts
        </a>
      </div>
    </div>
  );
}

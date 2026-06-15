import type { IndicatorParameters, IndicatorSettings } from "@/components/StockKLineChart";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";
import {
  type CandlestickData,
  type HistogramData,
  type LineData,
  type LogicalRange,
  type Time,
  type UTCTimestamp,
  type WhitespaceData,
} from "lightweight-charts";
export type ChartTimeMode = "date" | "intraday";
export type ChartDisplayStyle = "candlestick" | "line";
export type BusinessDayTime = Extract<Time, { year: number; month: number; day: number }>;
export type ChartTimeParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
};

export type LightweightKLineChartProps = {
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

export type ChartDrawingType = Exclude<ChartDrawingTool, "cursor">;

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

export const emptyIndicatorData: StockIndicatorPoint[] = [];
export const emptyDrawings: ChartDrawing[] = [];

export type PriceCoordinateApi = {
  coordinateToPrice: (coordinate: number) => number | null;
  priceToCoordinate: (price: number) => number | null;
};

export type DrawingAnchor = {
  time: string;
  price: number;
};

export type DrawingCoordinate = {
  x: number;
  y: number;
};

export type ProjectedDrawing = {
  drawing: ChartDrawing;
  label: string;
  points: [DrawingCoordinate, DrawingCoordinate];
  anchorPoints?: [DrawingCoordinate, DrawingCoordinate];
  anchoredVwapLine?: DrawingCoordinate[];
  fibonacciLevels?: ProjectedFibonacciLevel[];
  volumeProfileBins?: ProjectedRangeVolumeProfileBin[];
  measurementStats?: ProjectedMeasurementStats;
};

export type ProjectedDraftDrawing = {
  type: Exclude<ChartDrawingType, "horizontal">;
  points: [DrawingCoordinate, DrawingCoordinate];
  anchorPoints?: [DrawingCoordinate, DrawingCoordinate];
  fibonacciLevels?: ProjectedFibonacciLevel[];
  measurementStats?: ProjectedMeasurementStats;
};

export type ProjectedFibonacciLevel = {
  ratio: number;
  y: number;
  label: string;
  priceLabel: string;
};

export type ProjectedRangeVolumeProfileBin = {
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

export type ProjectedMeasurementStats = {
  tone: "up" | "down" | "flat";
  priceDiffLabel: string;
  percentLabel: string;
  barsLabel: string | null;
  highLabel: string;
  lowLabel: string;
};

export type DrawingDragState = {
  drawingId: string;
  mode: "horizontal" | "point" | "line";
  pointIndex: 0 | 1;
  pointerId: number;
  startCoordinate?: DrawingCoordinate;
  originCoordinates?: DrawingCoordinate[];
  oppositeCoordinate?: DrawingCoordinate;
  visibleLogicalRange?: LogicalRange;
};

export type PointerAnchor = DrawingAnchor & {
  x: number;
  y: number;
  snapped: boolean;
};

export type PlotLineData = LineData<Time> | WhitespaceData<Time>;

export type ProjectedCloudPolygon = {
  id: string;
  points: string;
  tone: "bullish" | "bearish";
};

export type ProjectedVolumeProfileBin = {
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

export type ProjectedGapZone = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  tone: "up" | "down";
  label: string;
};

export type ProjectedSupportResistanceLevel = {
  id: string;
  y: number;
  priceLabel: string;
  tone: "support" | "resistance";
  strength: number;
  opacity: number;
};

export type ProjectedTechnicalSignal = {
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

export type LineSeriesData = {
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

export type BuiltSeriesData = {
  candles: CandlestickData<Time>[];
  line: LineData<Time>[];
  volumes: HistogramData<Time>[];
  macdHistogram: HistogramData<Time>[];
  lines: LineSeriesData;
};

export const upColor = "#dc2626";
export const downColor = "#059669";
export const drawingSnapDistancePx = 14;
export const DEFAULT_LIGHTWEIGHT_VISIBLE_BARS = 80;
export const maColors = {
  maShort: "#2563eb",
  maMiddle: "#f59e0b",
  maLong: "#a855f7",
};

export const defaultLightweightIndicators: IndicatorSettings = {
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

export const defaultLightweightParameters: IndicatorParameters = {
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

export function finiteNumber(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

export function pad2(value: number) {
  return String(value).padStart(2, "0");
}

export function isBusinessDayTime(value: Time): value is BusinessDayTime {
  return typeof value === "object" && "year" in value && "month" in value && "day" in value;
}

export function chartTimeParts(value: Time): ChartTimeParts | null {
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

export function formatChartDate(value: Time) {
  const parts = chartTimeParts(value);

  if (!parts) return null;

  return `${parts.year}/${pad2(parts.month)}/${pad2(parts.day)}`;
}

export function formatChartDateTime(value: Time, timeMode: ChartTimeMode) {
  const parts = chartTimeParts(value);

  if (!parts) return "";

  const dateLabel = `${parts.year}/${pad2(parts.month)}/${pad2(parts.day)}`;

  if (timeMode === "date") return dateLabel;

  return `${dateLabel} ${pad2(parts.hour)}:${pad2(parts.minute)}`;
}

export function chartTime(value: string, timeMode: ChartTimeMode): Time {
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

export function drawingTimeFromChartTime(value: Time, timeMode: ChartTimeMode) {
  const parts = chartTimeParts(value);

  if (!parts) return String(value);

  const dateLabel = `${parts.year}-${pad2(parts.month)}-${pad2(parts.day)}`;

  if (timeMode === "date") return dateLabel;

  return `${dateLabel}T${pad2(parts.hour)}:${pad2(parts.minute)}:00`;
}

export function formatDrawingPrice(value: number) {
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

export function formatSignedDrawingPrice(value: number) {
  const sign = value > 0 ? "+" : "";

  return `${sign}${formatDrawingPrice(value)}`;
}

export function formatDrawingPercent(value: number) {
  const sign = value > 0 ? "+" : "";

  return `${sign}${value.toFixed(2)}%`;
}

export function formatDrawingRatioPercent(value: number | null) {
  if (!finiteNumber(value)) return "-";

  return formatDrawingPercent(value);
}

export function parseDrawingTimeMs(value: string) {
  const normalized = value.includes("T") ? value : `${value}T00:00:00`;
  const hasExplicitZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(normalized);
  const date = new Date(hasExplicitZone ? normalized : `${normalized}+08:00`);
  const timestamp = date.getTime();

  return Number.isFinite(timestamp) ? timestamp : null;
}

export function formatDurationLabel(days: number | null, minutes: number | null) {
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

export function formatCompactVolume(value: number) {
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

export function candleParts(point: ChartPoint) {
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

export function detectCandlestickPattern(
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

export function createDrawingId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `drawing-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function preserveEmptyProjection<T>(current: T[], next: T[]) {
  return current.length === 0 && next.length === 0 ? current : next;
}

export function isTwoPointDrawingTool(
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

export function isTwoPointDrawingType(
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

export function drawingDefaultColor(type: ChartDrawing["type"]) {
  if (type === "anchorVwap") return "#0891b2";
  if (type === "volumeProfileRange") return "#475569";
  if (type === "priceRange") return "#64748b";
  if (type === "measure") return "#334155";
  if (type === "rectangle") return "#2563eb";
  if (type === "fibonacci") return "#7c3aed";
  if (type === "ray") return "#0f766e";

  return "#0f172a";
}

export function drawingToolModeLabel(tool: ChartDrawingTool) {
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

export function drawingModeBadgeWidth(tool: ChartDrawingTool) {
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

export function measurementToneColor(tone: ProjectedMeasurementStats["tone"]) {
  if (tone === "up") return "#dc2626";
  if (tone === "down") return "#059669";

  return "#334155";
}

export function medianFinite(values: number[]) {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);

  if (sorted.length === 0) return null;

  const middle = Math.floor(sorted.length / 2);

  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

export function pointClose(point: ChartPoint | null | undefined) {
  if (!point) return null;
  if (finiteNumber(point.close)) return point.close;
  if (finiteNumber(point.open)) return point.open;

  return null;
}

export function lineValueAtIndex(
  startPrice: number,
  endPrice: number,
  startIndex: number,
  endIndex: number,
  targetIndex: number
) {
  if (startIndex === endIndex) return endPrice;

  return startPrice + ((targetIndex - startIndex) / (endIndex - startIndex)) * (endPrice - startPrice);
}

export function estimateLineAnalysisTolerance(chartData: ChartPoint[], referencePrice: number) {
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

export function candleTouchesPrice(point: ChartPoint, price: number, tolerance: number) {
  if (finiteNumber(point.high) && finiteNumber(point.low)) {
    return point.low - tolerance <= price && point.high + tolerance >= price;
  }

  const close = pointClose(point);

  return finiteNumber(close) ? Math.abs(close - price) <= tolerance : false;
}

export function lineAnalysisRole(distance: number | null, tolerance: number | null): ChartDrawingLineAnalysis["role"] {
  if (!finiteNumber(distance) || !finiteNumber(tolerance)) return "unknown";
  if (Math.abs(distance) <= tolerance) return "neutral";

  return distance > 0 ? "support" : "resistance";
}

export function lineAnalysisStatusLabel(status: ChartDrawingLineAnalysis["status"]) {
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

export function lineAnalysisRoleLabel(role: ChartDrawingLineAnalysis["role"]) {
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

export function buildLineAnalysis(
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

export function zoneAnalysisRoleLabel(role: ChartDrawingZoneAnalysis["role"]) {
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

export function zoneAnalysisStatusLabel(status: ChartDrawingZoneAnalysis["status"]) {
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

export function zoneCompressionLabel(state: ChartDrawingZoneAnalysis["compressionState"]) {
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

export function countBoundaryTouches(
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

export function buildZoneAnalysis(
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

export function fibonacciTrendLabel(trend: ChartDrawingFibonacciAnalysis["trend"]) {
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

export function fibonacciStatusLabel(status: ChartDrawingFibonacciAnalysis["status"]) {
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

export function fibonacciLevelKind(ratio: number): ChartDrawingFibonacciLevel["kind"] {
  if (ratio === 0 || ratio === 1) return "anchor";
  if (ratio < 0 || ratio > 1) return "extension";

  return "retracement";
}

export function buildFibonacciAnalysis(
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

export function chartPointTypicalPrice(point: ChartPoint) {
  if (finiteNumber(point.high) && finiteNumber(point.low) && finiteNumber(point.close)) {
    return (point.high + point.low + point.close) / 3;
  }

  return pointClose(point);
}

export function chartPointVolume(point: ChartPoint) {
  if (finiteNumber(point.volume) && point.volume > 0) return point.volume;
  if (finiteNumber(point.trade_value) && point.trade_value > 0) return point.trade_value;

  return null;
}

export function anchoredVwapStatusLabel(status: ChartDrawingAnchoredVwapAnalysis["status"]) {
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

export function buildAnchoredVwapAnalysis(
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

export function volumeProfilePositionLabel(
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

export function buildVolumeProfileAnalysis(
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

export function buildDrawingDerivedMetrics(
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

export function drawingTypeLabel(type: ChartDrawing["type"]) {
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

export function buildDrawingOmiSummary(
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

export function attachDrawingAnalytics(
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

export function measurementStatsFromMetrics(metrics: ChartDrawingDerivedMetrics): ProjectedMeasurementStats {
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

export function buildMeasurementStats(
  first: ChartDrawingPoint,
  second: ChartDrawingPoint,
  timeIndex: Map<string, number>
): ProjectedMeasurementStats {
  return measurementStatsFromMetrics(
    buildDrawingDerivedMetrics("measure", [first, second], timeIndex)
  );
}

export function extendRayToViewport(
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

export function rectangleBounds(points: [DrawingCoordinate, DrawingCoordinate]) {
  const [first, second] = points;

  return {
    x: Math.min(first.x, second.x),
    y: Math.min(first.y, second.y),
    width: Math.abs(second.x - first.x),
    height: Math.abs(second.y - first.y),
  };
}

export function coordinateDistance(first: DrawingCoordinate, second: DrawingCoordinate) {
  return Math.hypot(first.x - second.x, first.y - second.y);
}

export function distanceToSegment(
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

export function expandedRectangleContains(
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

export function isProjectedDrawingHit(
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

export function lockCoordinateToNearestAngle(
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

export const fibonacciRatios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
export const fibonacciAnalysisRatios = [-0.618, -0.272, ...fibonacciRatios, 1.272, 1.618] as const;
export const drawingVolumeProfileRows = 24;
export const drawingValueAreaTargetPct = 70;
export const selectedDrawingColor = "#dc2626";
export const hoveredDrawingColor = "#2563eb";
export const drawingHandleBorderColor = "#ffffff";

export function formatFibonacciRatio(ratio: number) {
  if (ratio === 0 || ratio === 1) return `${ratio * 100}%`;
  if (ratio === 0.5) return "50%";

  return `${(ratio * 100).toFixed(1)}%`;
}

export function buildFibonacciLevels(
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

export function applyDrawingDragToDrawings(
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

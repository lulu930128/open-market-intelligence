import type { IndicatorParameters, IndicatorSettings } from "@/components/StockKLineChart";
import type { ChartEventMarker } from "@/components/chart/chartEventMarkers";
import { omiChartColors } from "@/lib/themeColors";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";
import type { CanonicalIndicatorAuthority } from "@/components/stock-k-line/indicatorAuthority";
import type { TranslationFunction, TranslationValues } from "@/i18n";
import {
  type CandlestickData,
  type HistogramData,
  type LineData,
  type LogicalRange,
  type Time,
  type UTCTimestamp,
  type WhitespaceData,
} from "lightweight-charts";

export type DrawingAnalysisI18n = {
  locale?: string;
  t?: TranslationFunction;
};

function interpolateDrawingFallback(message: string, values: TranslationValues | undefined) {
  if (!values) return message;

  return message.replace(/\{(\w+)\}/g, (match, key) => {
    const value = values[key];
    return value === null || value === undefined ? match : String(value);
  });
}

export function translateDrawing(
  i18n: DrawingAnalysisI18n | undefined,
  key: string,
  fallback: string,
  values?: TranslationValues
) {
  const messageKey = `chart.drawingAnalysis.${key}`;
  const translated = i18n?.t?.(messageKey, values);

  if (translated && translated !== messageKey) return translated;

  return interpolateDrawingFallback(fallback, values);
}

export function drawingNumberLocale(i18n?: DrawingAnalysisI18n) {
  return i18n?.locale ?? "zh-TW";
}

export function formatDrawingUnitCount(
  count: number,
  key: "times" | "bars",
  fallbackUnit: string,
  i18n?: DrawingAnalysisI18n
) {
  return translateDrawing(i18n, `units.${key}`, `{count} ${fallbackUnit}`, {
    count: count.toLocaleString(drawingNumberLocale(i18n)),
  });
}

export type ChartTimeMode = "date" | "intraday";
export type ChartDateGranularity = "daily" | "weekly" | "monthly" | null;
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
  eventMarkers?: ChartEventMarker[];
  volumePanelLabel?: string;
  volumeValueKey?: "volume" | "trade_value";
  pricePrecision?: number;
  canonicalIndicatorAuthority?: CanonicalIndicatorAuthority;
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
  | "priceRange"
  | "riskReward";

export type ChartDrawingType = Exclude<ChartDrawingTool, "cursor">;
export type TwoPointChartDrawingType = Exclude<
  ChartDrawingType,
  "horizontal" | "anchorVwap" | "riskReward"
>;

export type ChartDrawingPoint = {
  time: string;
  price: number;
  logical?: number;
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
  logical?: number;
};

export type DrawingCoordinate = {
  x: number;
  y: number;
};

export type ProjectedDrawing = {
  drawing: ChartDrawing;
  label: string;
  points:
    | [DrawingCoordinate, DrawingCoordinate]
    | [DrawingCoordinate, DrawingCoordinate, DrawingCoordinate];
  anchorPoints?:
    | [DrawingCoordinate, DrawingCoordinate]
    | [DrawingCoordinate, DrawingCoordinate, DrawingCoordinate];
  anchoredVwapLine?: DrawingCoordinate[];
  fibonacciLevels?: ProjectedFibonacciLevel[];
  volumeProfileBins?: ProjectedRangeVolumeProfileBin[];
  measurementStats?: ProjectedMeasurementStats;
  riskRewardStats?: ProjectedRiskRewardStats;
};

export type ProjectedDraftDrawing = {
  type: Exclude<ChartDrawingType, "horizontal">;
  points:
    | [DrawingCoordinate, DrawingCoordinate]
    | [DrawingCoordinate, DrawingCoordinate, DrawingCoordinate];
  anchorPoints?:
    | [DrawingCoordinate, DrawingCoordinate]
    | [DrawingCoordinate, DrawingCoordinate, DrawingCoordinate];
  fibonacciLevels?: ProjectedFibonacciLevel[];
  measurementStats?: ProjectedMeasurementStats;
  riskRewardStats?: ProjectedRiskRewardStats;
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

export type ProjectedRiskRewardStats = {
  rewardLabel: string;
  riskLabel: string;
  ratioLabel: string;
};

export type DrawingDragState = {
  drawingId: string;
  mode: "horizontal" | "point" | "line" | "riskRewardWidth";
  pointIndex: 0 | 1 | 2;
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

export const upColor = omiChartColors.marketUp;
export const downColor = omiChartColors.marketDown;
export const drawingSnapDistancePx = 14;
export const DEFAULT_LIGHTWEIGHT_VISIBLE_BARS = 80;
export const maColors = {
  maShort: omiChartColors.info,
  maMiddle: omiChartColors.warning,
  maLong: omiChartColors.purpleLight,
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

export function formatChartDate(
  value: Time,
  granularity: ChartDateGranularity = null
) {
  const parts = chartTimeParts(value);

  if (!parts) return null;

  if (granularity === "monthly") {
    return `${parts.year}/${pad2(parts.month)}`;
  }

  const dateLabel = `${parts.year}/${pad2(parts.month)}/${pad2(parts.day)}`;
  return granularity === "weekly" ? `${dateLabel} 週` : dateLabel;
}

export function formatChartDateTime(
  value: Time,
  timeMode: ChartTimeMode,
  granularity: ChartDateGranularity = null
) {
  const parts = chartTimeParts(value);

  if (!parts) return "";

  const dateLabel = formatChartDate(value, granularity) ?? "";

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

export function normalizeChartPointsForTimeMode(
  points: ChartPoint[],
  timeMode: ChartTimeMode
) {
  const pointsByChartTime = new Map<
    string,
    { point: ChartPoint; sortValue: number | string }
  >();

  for (const point of points) {
    const rawTime = String(point.time ?? "").trim();
    if (!rawTime) continue;

    const projectedTime = chartTime(rawTime, timeMode);
    if (timeMode === "date") {
      const dateKey = String(projectedTime);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(dateKey)) continue;

      pointsByChartTime.set(`date:${dateKey}`, {
        point: rawTime === point.time ? point : { ...point, time: rawTime },
        sortValue: dateKey,
      });
      continue;
    }

    if (typeof projectedTime !== "number" || !Number.isFinite(projectedTime)) continue;

    pointsByChartTime.set(`timestamp:${projectedTime}`, {
      point: rawTime === point.time ? point : { ...point, time: rawTime },
      sortValue: projectedTime,
    });
  }

  return [...pointsByChartTime.values()]
    .sort((left, right) => {
      if (typeof left.sortValue === "number" && typeof right.sortValue === "number") {
        return left.sortValue - right.sortValue;
      }

      return String(left.sortValue).localeCompare(String(right.sortValue));
    })
    .map(({ point }) => point);
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

export function formatRiskRewardRatio(value: number | null) {
  if (!finiteNumber(value)) return "-";

  return value.toLocaleString("zh-TW", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  });
}

export function buildRiskRewardStats(
  entry: ChartDrawingPoint,
  target: ChartDrawingPoint,
  stop: ChartDrawingPoint
): ProjectedRiskRewardStats {
  const reward = target.price - entry.price;
  const risk = stop.price - entry.price;
  const rewardPct = entry.price !== 0 ? (reward / entry.price) * 100 : null;
  const riskPct = entry.price !== 0 ? (risk / entry.price) * 100 : null;
  const rewardAbs = Math.abs(reward);
  const riskAbs = Math.abs(risk);
  const ratio = riskAbs > 0 ? rewardAbs / riskAbs : null;

  return {
    rewardLabel: formatDrawingRatioPercent(rewardPct),
    riskLabel: formatDrawingRatioPercent(riskPct),
    ratioLabel: formatRiskRewardRatio(ratio),
  };
}

export function riskRewardMinimumPriceGap(entryPrice: number) {
  return Math.max(Math.abs(entryPrice) * 0.0001, 0.01);
}

export function parseDrawingTimeMs(value: string) {
  const normalized = value.includes("T") ? value : `${value}T00:00:00`;
  const hasExplicitZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(normalized);
  const date = new Date(hasExplicitZone ? normalized : `${normalized}+08:00`);
  const timestamp = date.getTime();

  return Number.isFinite(timestamp) ? timestamp : null;
}

export function formatDurationLabel(
  days: number | null,
  minutes: number | null,
  i18n?: DrawingAnalysisI18n
) {
  if (finiteNumber(days) && days >= 1) {
    return translateDrawing(i18n, "duration.days", "{value} 天", {
      value: days.toLocaleString(drawingNumberLocale(i18n), { maximumFractionDigits: 1 }),
    });
  }

  if (finiteNumber(minutes)) {
    if (minutes >= 60) {
      return translateDrawing(i18n, "duration.hours", "{value} 小時", {
        value: (minutes / 60).toLocaleString(drawingNumberLocale(i18n), {
          maximumFractionDigits: 1,
        }),
      });
    }

    return translateDrawing(i18n, "duration.minutes", "{value} 分", {
      value: minutes.toLocaleString(drawingNumberLocale(i18n), { maximumFractionDigits: 0 }),
    });
  }

  return null;
}

export function formatCompactVolume(value: number, i18n?: DrawingAnalysisI18n) {
  const absValue = Math.abs(value);

  if (absValue >= 100_000_000) {
    return translateDrawing(i18n, "compactVolume.hundredMillion", "{value}億", {
      value: (value / 100_000_000).toLocaleString(drawingNumberLocale(i18n), {
        maximumFractionDigits: 2,
        minimumFractionDigits: 2,
      }),
    });
  }

  if (absValue >= 10_000) {
    return translateDrawing(i18n, "compactVolume.tenThousand", "{value}萬", {
      value: (value / 10_000).toLocaleString(drawingNumberLocale(i18n), {
        maximumFractionDigits: 1,
        minimumFractionDigits: 1,
      }),
    });
  }

  return value.toLocaleString(drawingNumberLocale(i18n), {
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
  previous: ChartPoint | undefined,
  i18n?: DrawingAnalysisI18n
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
      return {
        label: translateDrawing(i18n, "candlestick.bullishEngulfing", "多方吞噬"),
        tone: "bullish",
        price: point.low,
      };
    }

    if (
      previous.close > previous.open &&
      currentParts.bearish &&
      finiteNumber(point.open) &&
      finiteNumber(point.close) &&
      point.open >= previous.close &&
      point.close <= previous.open
    ) {
      return {
        label: translateDrawing(i18n, "candlestick.bearishEngulfing", "空方吞噬"),
        tone: "bearish",
        price: point.high,
      };
    }
  }

  if (
    bodyRatio <= 0.34 &&
    currentParts.lowerWick >= Math.max(currentParts.body * 2, currentParts.range * 0.38) &&
    currentParts.upperWick <= Math.max(currentParts.body * 1.2, currentParts.range * 0.18)
  ) {
    return {
      label: currentParts.bullish
        ? translateDrawing(i18n, "candlestick.hammer", "錘子")
        : translateDrawing(i18n, "candlestick.lowerShadowReversal", "下影反轉"),
      tone: "bullish",
      price: point.low,
    };
  }

  if (
    bodyRatio <= 0.34 &&
    currentParts.upperWick >= Math.max(currentParts.body * 2, currentParts.range * 0.38) &&
    currentParts.lowerWick <= Math.max(currentParts.body * 1.2, currentParts.range * 0.18)
  ) {
    return {
      label: currentParts.bearish
        ? translateDrawing(i18n, "candlestick.shootingStar", "流星")
        : translateDrawing(i18n, "candlestick.upperShadowPressure", "上影壓力"),
      tone: "bearish",
      price: point.high,
    };
  }

  if (bodyRatio <= 0.08) {
    return {
      label: translateDrawing(i18n, "candlestick.doji", "十字"),
      tone: "neutral",
      price: finiteNumber(point.close) ? point.close : point.high,
    };
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
): value is TwoPointChartDrawingType {
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
): value is TwoPointChartDrawingType {
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

export function isRiskRewardDrawingTool(value: ChartDrawingTool): value is "riskReward" {
  return value === "riskReward";
}

export function drawingDefaultColor(type: ChartDrawing["type"]) {
  if (type === "anchorVwap") return omiChartColors.cyan;
  if (type === "volumeProfileRange") return omiChartColors.neutralMuted;
  if (type === "priceRange") return omiChartColors.textMuted;
  if (type === "riskReward") return omiChartColors.warning;
  if (type === "measure") return omiChartColors.neutralLine;
  if (type === "rectangle") return omiChartColors.info;
  if (type === "fibonacci") return omiChartColors.purple;
  if (type === "ray") return omiChartColors.teal;

  return omiChartColors.text;
}

export function drawingToolModeLabel(tool: ChartDrawingTool, i18n?: DrawingAnalysisI18n) {
  switch (tool) {
    case "horizontal":
      return translateDrawing(i18n, "toolModes.horizontal", "水平線模式");
    case "trend":
      return translateDrawing(i18n, "toolModes.trend", "趨勢線模式");
    case "ray":
      return translateDrawing(i18n, "toolModes.ray", "射線模式");
    case "rectangle":
      return translateDrawing(i18n, "toolModes.rectangle", "區間框模式");
    case "fibonacci":
      return translateDrawing(i18n, "toolModes.fibonacci", "Fib 回撤模式");
    case "anchorVwap":
      return translateDrawing(i18n, "toolModes.anchorVwap", "錨定VWAP模式");
    case "volumeProfileRange":
      return translateDrawing(i18n, "toolModes.volumeProfileRange", "量價分布模式");
    case "measure":
      return translateDrawing(i18n, "toolModes.measure", "量測模式");
    case "priceRange":
      return translateDrawing(i18n, "toolModes.priceRange", "價幅%模式");
    case "riskReward":
      return translateDrawing(i18n, "toolModes.riskReward", "上下限模式");
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
    case "riskReward":
      return 104;
    case "rectangle":
      return 94;
    case "horizontal":
      return 86;
    default:
      return 82;
  }
}

export function measurementToneColor(tone: ProjectedMeasurementStats["tone"]) {
  if (tone === "up") return omiChartColors.marketUp;
  if (tone === "down") return omiChartColors.marketDown;

  return omiChartColors.neutralLine;
}

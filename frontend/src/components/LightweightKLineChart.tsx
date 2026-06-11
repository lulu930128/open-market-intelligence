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

type ChartTimeMode = "date" | "intraday";
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
  volumePanelLabel?: string;
  volumeValueKey?: "volume" | "trade_value";
  drawingTool?: ChartDrawingTool;
  drawings?: ChartDrawing[];
  selectedDrawingId?: string | null;
  onDrawingsChange?: (drawings: ChartDrawing[]) => void;
  onSelectedDrawingChange?: (drawingId: string | null) => void;
};

export type ChartDrawingTool =
  | "cursor"
  | "horizontal"
  | "trend"
  | "ray"
  | "rectangle"
  | "fibonacci"
  | "measure"
  | "priceRange";

type ChartDrawingType = Exclude<ChartDrawingTool, "cursor">;

export type ChartDrawingPoint = {
  time: string;
  price: number;
};

export type ChartDrawing = {
  id: string;
  type: ChartDrawingType;
  points: ChartDrawingPoint[];
  color: string;
  createdAt: string;
};

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
  fibonacciLevels?: ProjectedFibonacciLevel[];
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

type LineSeriesData = {
  maShort: LineData<Time>[];
  maMiddle: LineData<Time>[];
  maLong: LineData<Time>[];
  emaFast: LineData<Time>[];
  emaSlow: LineData<Time>[];
  vwap: LineData<Time>[];
  psar: LineData<Time>[];
  bollingerUpper: LineData<Time>[];
  bollingerMiddle: LineData<Time>[];
  bollingerLower: LineData<Time>[];
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
  atr: LineData<Time>[];
  adx: LineData<Time>[];
  plusDi: LineData<Time>[];
  minusDi: LineData<Time>[];
  aroonUp: LineData<Time>[];
  aroonDown: LineData<Time>[];
  obv: LineData<Time>[];
  obvMa: LineData<Time>[];
  mfi: LineData<Time>[];
  cci: LineData<Time>[];
  williamsR: LineData<Time>[];
  roc: LineData<Time>[];
  stochRsiK: LineData<Time>[];
  stochRsiD: LineData<Time>[];
  trix: LineData<Time>[];
  trixSignal: LineData<Time>[];
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
const maColors = {
  maShort: "#2563eb",
  maMiddle: "#f59e0b",
  maLong: "#a855f7",
};

const defaultLightweightIndicators: IndicatorSettings = {
  signals: false,
  ma: true,
  ema: false,
  bollinger: false,
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
  atr: false,
  adx: false,
  aroon: false,
  obv: false,
  mfi: false,
  cci: false,
  williamsR: false,
  roc: false,
  stochRsi: false,
  trix: false,
};

const defaultLightweightParameters: IndicatorParameters = {
  maShort: 5,
  maMiddle: 20,
  maLong: 60,
  emaFast: 12,
  emaSlow: 26,
  bollingerPeriod: 20,
  bollingerStdDev: 2,
  volumeMa: 20,
  rsiPeriod: 14,
  macdFast: 12,
  macdSlow: 26,
  macdSignal: 9,
  kdPeriod: 9,
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
  cciPeriod: 20,
  williamsRPeriod: 14,
  rocPeriod: 12,
  stochRsiPeriod: 14,
  stochRsiSmoothK: 3,
  stochRsiSmoothD: 3,
  trixPeriod: 15,
  trixSignal: 9,
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

function createDrawingId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  return `drawing-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function isTwoPointDrawingTool(
  value: ChartDrawingTool
): value is Exclude<ChartDrawingType, "horizontal"> {
  return (
    value === "trend" ||
    value === "ray" ||
    value === "rectangle" ||
    value === "fibonacci" ||
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
    value === "measure" ||
    value === "priceRange"
  );
}

function drawingDefaultColor(type: ChartDrawing["type"]) {
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

function buildMeasurementStats(
  first: ChartDrawingPoint,
  second: ChartDrawingPoint,
  timeIndex: Map<string, number>
): ProjectedMeasurementStats {
  const priceDiff = second.price - first.price;
  const percent = first.price !== 0 ? (priceDiff / first.price) * 100 : 0;
  const firstIndex = timeIndex.get(first.time);
  const secondIndex = timeIndex.get(second.time);
  const bars =
    firstIndex !== undefined && secondIndex !== undefined
      ? Math.abs(secondIndex - firstIndex)
      : null;
  const highPrice = Math.max(first.price, second.price);
  const lowPrice = Math.min(first.price, second.price);

  return {
    tone: priceDiff > 0 ? "up" : priceDiff < 0 ? "down" : "flat",
    priceDiffLabel: formatSignedDrawingPrice(priceDiff),
    percentLabel: formatDrawingPercent(percent),
    barsLabel: bars === null ? null : `${bars.toLocaleString("zh-TW")} 根`,
    highLabel: formatDrawingPrice(highPrice),
    lowLabel: formatDrawingPrice(lowPrice),
  };
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

const fibonacciRatios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;

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
    vwap: [],
    psar: [],
    bollingerUpper: [],
    bollingerMiddle: [],
    bollingerLower: [],
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
    atr: [],
    adx: [],
    plusDi: [],
    minusDi: [],
    aroonUp: [],
    aroonDown: [],
    obv: [],
    obvMa: [],
    mfi: [],
    cci: [],
    williamsR: [],
    roc: [],
    stochRsiK: [],
    stochRsiD: [],
    trix: [],
    trixSignal: [],
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
  params: IndicatorParameters
): BuiltSeriesData {
  const indicatorByTime = new Map(indicatorData.map((point) => [point.time.slice(0, 10), point]));
  const closes = chartData.map((point) => point.close);
  const emaFast = calculateEma(closes, params.emaFast);
  const emaSlow = calculateEma(closes, params.emaSlow);
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
  const dmi = calculateDmi(chartData, params.adxPeriod);
  const aroon = calculateAroon(chartData, params.aroonPeriod);
  const obv = calculateObv(chartData);
  const obvMa = obv.map((_, index) => movingAverage(obv, index, params.obvMa));
  const mfi = calculateMfi(chartData, params.mfiPeriod);
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

export default function LightweightKLineChart({
  chartData,
  indicatorData = [],
  label,
  height = 720,
  fillViewport = false,
  timeMode = "date",
  chartStyle = "candlestick",
  showHeader = true,
  showMovingAverages = true,
  indicators,
  indicatorParameters,
  volumePanelLabel = "成交量(張)",
  volumeValueKey = "volume",
  drawingTool = "cursor",
  drawings = [],
  selectedDrawingId = null,
  onDrawingsChange,
  onSelectedDrawingChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const overlaySvgRef = useRef<SVGSVGElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<PriceCoordinateApi | null>(null);
  const dragStateRef = useRef<DrawingDragState | null>(null);
  const visibleLogicalRangeRef = useRef<LogicalRange | null>(null);
  const visibleLogicalRangeKeyRef = useRef<string | null>(null);
  const [overlaySize, setOverlaySize] = useState({ width: 0, height: 0 });
  const [overlayRevision, setOverlayRevision] = useState(0);
  const [draftAnchor, setDraftAnchor] = useState<DrawingAnchor | null>(null);
  const [hoverAnchor, setHoverAnchor] = useState<DrawingAnchor | null>(null);
  const [snapCoordinate, setSnapCoordinate] = useState<DrawingCoordinate | null>(null);
  const [dragPreviewDrawings, setDragPreviewDrawings] = useState<ChartDrawing[] | null>(null);
  const [projectedCloudPolygons, setProjectedCloudPolygons] = useState<ProjectedCloudPolygon[]>([]);
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
    () => buildSeriesData(chartData, indicatorData, volumeValueKey, timeMode, params),
    [chartData, indicatorData, params, timeMode, volumeValueKey]
  );
  const chartDataRangeKey = useMemo(() => {
    const firstPoint = chartData[0];
    const lastPoint = chartData[chartData.length - 1];

    return [
      timeMode,
      chartData.length,
      firstPoint?.time ?? "empty",
      lastPoint?.time ?? "empty",
    ].join(":");
  }, [chartData, timeMode]);
  const chartDataTimeIndex = useMemo(() => {
    const indexByTime = new Map<string, number>();

    chartData.forEach((point, index) => {
      indexByTime.set(point.time, index);
      indexByTime.set(drawingTimeFromChartTime(chartTime(point.time, timeMode), timeMode), index);
    });

    return indexByTime;
  }, [chartData, timeMode]);

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

  const coordinateToDrawingPoint = useCallback((coordinate: DrawingCoordinate): ChartDrawingPoint | null => {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;

    if (!chart || !series) return null;

    const time = chart.timeScale().coordinateToTime(coordinate.x);
    const price = series.coordinateToPrice(coordinate.y);

    if (time === null || price === null || !Number.isFinite(price)) return null;

    return {
      time: drawingTimeFromChartTime(time, timeMode),
      price,
    };
  }, [timeMode]);

  function pointerCoordinateFromEvent(event: { clientX: number; clientY: number }): DrawingCoordinate | null {
    const target = overlaySvgRef.current;

    if (!target) return null;

    const rect = target.getBoundingClientRect();

    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

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

    const time = chart.timeScale().coordinateToTime(coordinate.x);
    const price = series.coordinateToPrice(coordinate.y);

    if (time === null || price === null || !Number.isFinite(price)) return null;

    const anchor = {
      time: drawingTimeFromChartTime(time, timeMode),
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

  function commitDrawing(type: ChartDrawing["type"], points: ChartDrawingPoint[]) {
    if (!onDrawingsChange || points.length === 0) return;

    const nextDrawing: ChartDrawing = {
      id: createDrawingId(),
      type,
      points,
      color: drawingDefaultColor(type),
      createdAt: new Date().toISOString(),
    };

    onDrawingsChange([...drawings, nextDrawing]);
    onSelectedDrawingChange?.(nextDrawing.id);
  }

  const deleteDrawing = useCallback((drawingId: string) => {
    onDrawingsChange?.(drawings.filter((drawing) => drawing.id !== drawingId));

    if (selectedDrawingId === drawingId) {
      onSelectedDrawingChange?.(null);
    }
  }, [drawings, onDrawingsChange, onSelectedDrawingChange, selectedDrawingId]);

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
    if (drawingTool === "cursor") return;

    const anchor = anchorFromPointer(event);

    if (!anchor) return;

    setSnapCoordinate(anchor.snapped ? { x: anchor.x, y: anchor.y } : null);

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
      const anchor = dragState.mode === "line" ? null : anchorFromPointer(event);

      if (dragState.mode !== "line" && !anchor) return;

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

    if (!isTwoPointDrawingTool(drawingTool) || !draftAnchor) return;

    const anchor = anchorFromPointer(event);

    if (anchor) {
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
    const originCoordinates =
      mode === "line"
        ? drawing.points
            .slice(0, 2)
            .map((point) => drawingPointToCoordinate(point))
            .filter((coordinate): coordinate is DrawingCoordinate => coordinate !== null)
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
    const anchor = dragState.mode === "line" ? null : anchorFromPointer(event);
    const sourceDrawings = dragPreviewDrawings ?? drawings;
    const nextDrawings = applyActiveDrawingDrag(sourceDrawings, dragState, anchor, pointerCoordinate);

    onDrawingsChange?.(nextDrawings);
    dragStateRef.current = null;
    setDragPreviewDrawings(null);
    setSnapCoordinate(null);
  }

  function selectDrawing(drawingId: string) {
    onSelectedDrawingChange?.(drawingId);
  }

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (!selectedDrawingId) return;
      if (event.key !== "Delete" && event.key !== "Backspace") return;

      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();

      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;

      event.preventDefault();
      deleteDrawing(selectedDrawingId);
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deleteDrawing, selectedDrawingId]);

  useEffect(() => {
    if (!isTwoPointDrawingTool(drawingTool)) {
      const timer = window.setTimeout(() => {
        setDraftAnchor(null);
        setHoverAnchor(null);
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
              measurementStats: buildMeasurementStats(
                drawing.points[0],
                drawing.points[1],
                chartDataTimeIndex
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

      setProjectedCloudPolygons(activeIndicators.ichimoku ? buildIchimokuCloudPolygons() : []);
      setProjectedDrawings(nextDrawings);
      setProjectedDraftDrawing(
        draftDrawingType && draftAnchor && hoverAnchor && firstDraftPoint && secondDraftPoint
          ? {
              type: draftDrawingType,
              points:
                draftDrawingType === "trend"
                  ? [firstDraftPoint, secondDraftPoint]
                  : draftDrawingType === "ray"
                    ? extendRayToViewport(
                        firstDraftPoint,
                        secondDraftPoint,
                        overlaySize.width,
                        overlaySize.height
                      )
                    : [firstDraftPoint, secondDraftPoint],
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
            }
          : null
      );
    });

    return () => window.cancelAnimationFrame(frame);
  }, [
    activeIndicators.ichimoku,
    chartDataTimeIndex,
    drawingPointToCoordinate,
    activeDrawings,
    buildIchimokuCloudPolygons,
    draftAnchor,
    drawingTool,
    hoverAnchor,
    overlayRevision,
    overlaySize.height,
    overlaySize.width,
    timeMode,
  ]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || seriesData.candles.length === 0) return;
    const initialHeight = container.clientHeight || height;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: initialHeight,
      autoSize: true,
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
        rightOffset: 6,
        barSpacing: timeMode === "intraday" ? 10 : 7,
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

    if (activeIndicators.atr) {
      const paneIndex = addIndicatorPane();
      addPaneLine(paneIndex, seriesData.lines.atr, `ATR${params.atrPeriod}`, "#f97316");
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
      visibleLogicalRangeKeyRef.current === chartDataRangeKey
        ? visibleLogicalRangeRef.current
        : null;

    if (savedLogicalRange) {
      chart.timeScale().setVisibleLogicalRange(savedLogicalRange);
    } else {
      chart.timeScale().fitContent();
    }

    setOverlaySize({ width: container.clientWidth, height: container.clientHeight || height });

    const syncOverlay = (logicalRange: LogicalRange | null) => {
      if (logicalRange) {
        visibleLogicalRangeRef.current = {
          from: logicalRange.from,
          to: logicalRange.to,
        };
        visibleLogicalRangeKeyRef.current = chartDataRangeKey;
      }

      setOverlayRevision((value) => value + 1);
    };

    chart.timeScale().subscribeVisibleLogicalRangeChange(syncOverlay);

    const resizeObserver = new ResizeObserver(() => {
      const nextHeight = container.clientHeight || height;
      chart.applyOptions({
        width: container.clientWidth,
        height: nextHeight,
      });
      setOverlaySize({ width: container.clientWidth, height: nextHeight });
    });
    resizeObserver.observe(container);

    return () => {
      const latestLogicalRange = chart.timeScale().getVisibleLogicalRange();

      if (latestLogicalRange) {
        visibleLogicalRangeRef.current = {
          from: latestLogicalRange.from,
          to: latestLogicalRange.to,
        };
        visibleLogicalRangeKeyRef.current = chartDataRangeKey;
      }

      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncOverlay);
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      mainSeriesRef.current = null;
    };
  }, [
    activeIndicators,
    chartDataRangeKey,
    chartStyle,
    height,
    params,
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
    projectedDraftDrawing?.type === "rectangle"
      ? rectangleBounds(projectedDraftDrawing.anchorPoints ?? projectedDraftDrawing.points)
      : null;
  const draftPriceRangeBox =
    projectedDraftDrawing?.type === "priceRange"
      ? rectangleBounds(projectedDraftDrawing.anchorPoints ?? projectedDraftDrawing.points)
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
        style={{
          height: fillViewport ? "max(620px, calc(100vh - 132px))" : height,
        }}
      >
        <div ref={containerRef} className="absolute inset-0" />
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
          style={{ pointerEvents: drawingTool === "cursor" ? "none" : "auto" }}
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
          {projectedDrawings.map(({ drawing, label: drawingLabel, points, anchorPoints, fibonacciLevels, measurementStats }) => {
            const selected = drawing.id === selectedDrawingId;
            const stroke = selected ? "#dc2626" : drawing.color;
            const lineWidth = selected ? 2.5 : 1.5;
            const handles = anchorPoints ?? points;

            if (drawing.type === "measure" && measurementStats) {
              const tone = measurementToneColor(measurementStats.tone);
              const labelWidth = 148;
              const labelX = Math.max(
                8,
                Math.min((points[0].x + points[1].x) / 2 + 10, overlaySize.width - labelWidth - 8)
              );
              const labelY = Math.max(18, Math.min((points[0].y + points[1].y) / 2 - 24, overlaySize.height - 52));

              return (
                <g key={drawing.id} onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}>
                  <line
                    x1={points[0].x}
                    y1={points[0].y}
                    x2={points[1].x}
                    y2={points[1].y}
                    stroke="transparent"
                    strokeWidth={14}
                    className="cursor-move"
                    pointerEvents={drawingTool === "cursor" ? "none" : "stroke"}
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line")}
                  />
                  <line
                    x1={points[0].x}
                    y1={points[0].y}
                    x2={points[1].x}
                    y2={points[1].y}
                    stroke={selected ? "#dc2626" : tone}
                    strokeWidth={lineWidth}
                    strokeDasharray="6 4"
                    pointerEvents="none"
                  />
                  {selected
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents={drawingTool === "cursor" ? "none" : "all"}
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle cx={handle.x} cy={handle.y} r={4} fill={selected ? "#dc2626" : tone} pointerEvents="none" />
                        </g>
                      ))
                    : null}
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={38} rx={3} fill="white" stroke={selected ? "#dc2626" : tone} opacity={0.96} />
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
              const box = rectangleBounds(handles);
              const labelWidth = 136;
              const labelX = Math.max(8, Math.min(box.x + box.width + 8, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(box.y + 8, overlaySize.height - 52));

              return (
                <g key={drawing.id} onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}>
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill={tone}
                    opacity={selected ? 0.12 : 0.08}
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
                    pointerEvents={drawingTool === "cursor" ? "none" : "all"}
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line")}
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="none"
                    stroke={selected ? "#dc2626" : tone}
                    strokeWidth={lineWidth}
                    strokeDasharray="5 4"
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y}
                    x2={box.x + box.width}
                    y2={box.y}
                    stroke={selected ? "#dc2626" : tone}
                    strokeWidth={1}
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y + box.height}
                    x2={box.x + box.width}
                    y2={box.y + box.height}
                    stroke={selected ? "#dc2626" : tone}
                    strokeWidth={1}
                    pointerEvents="none"
                  />
                  {selected
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents={drawingTool === "cursor" ? "none" : "all"}
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle cx={handle.x} cy={handle.y} r={4} fill={selected ? "#dc2626" : tone} pointerEvents="none" />
                        </g>
                      ))
                    : null}
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={38} rx={3} fill="white" stroke={selected ? "#dc2626" : tone} opacity={0.96} />
                    <text x={10} y={15} className="fill-slate-800 text-[10px] font-bold tabular-nums">
                      {measurementStats.priceDiffLabel} ({measurementStats.percentLabel})
                    </text>
                    <text x={10} y={30} className="fill-slate-500 text-[10px] font-semibold tabular-nums">
                      高 {measurementStats.highLabel} / 低 {measurementStats.lowLabel}
                    </text>
                  </g>
                </g>
              );
            }

            if (drawing.type === "rectangle") {
              const box = rectangleBounds(handles);

              return (
                <g key={drawing.id} onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}>
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill={stroke}
                    opacity={selected ? 0.1 : 0.07}
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
                    pointerEvents={drawingTool === "cursor" ? "none" : "all"}
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
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
                  {selected
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents={drawingTool === "cursor" ? "none" : "all"}
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle cx={handle.x} cy={handle.y} r={4} fill={stroke} pointerEvents="none" />
                        </g>
                      ))
                    : null}
                  <g
                    transform={`translate(${Math.max(8, Math.min(box.x + box.width + 8, overlaySize.width - 116))}, ${Math.max(18, box.y + 8)})`}
                    pointerEvents="none"
                  >
                    <rect width={108} height={18} rx={3} fill="white" stroke={stroke} opacity={0.94} />
                    <text
                      x={54}
                      y={12}
                      textAnchor="middle"
                      className="fill-slate-800 text-[10px] font-bold tabular-nums"
                    >
                      {drawingLabel}
                    </text>
                  </g>
                </g>
              );
            }

            if (drawing.type === "fibonacci" && fibonacciLevels) {
              const minY = Math.min(handles[0].y, handles[1].y);
              const maxY = Math.max(handles[0].y, handles[1].y);

              return (
                <g key={drawing.id} onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}>
                  <rect
                    x={0}
                    y={minY}
                    width={overlaySize.width}
                    height={Math.max(1, maxY - minY)}
                    fill={stroke}
                    opacity={selected ? 0.07 : 0.04}
                    pointerEvents="none"
                  />
                  <rect
                    x={0}
                    y={minY}
                    width={overlaySize.width}
                    height={Math.max(12, maxY - minY)}
                    fill="transparent"
                    className="cursor-move"
                    pointerEvents={drawingTool === "cursor" ? "none" : "all"}
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line")}
                  />
                  {fibonacciLevels.map((level) => (
                    <g key={`${drawing.id}-fib-${level.ratio}`} pointerEvents="none">
                      <line
                        x1={0}
                        y1={level.y}
                        x2={overlaySize.width}
                        y2={level.y}
                        stroke={stroke}
                        strokeWidth={level.ratio === 0 || level.ratio === 1 ? lineWidth : 1}
                        strokeDasharray={level.ratio === 0 || level.ratio === 1 ? undefined : "5 4"}
                        opacity={level.ratio === 0 || level.ratio === 1 ? 0.95 : 0.72}
                      />
                      <g transform={`translate(${Math.max(8, overlaySize.width - 104)}, ${Math.max(14, level.y - 9)})`}>
                        <rect width={96} height={18} rx={3} fill="white" stroke={stroke} opacity={0.92} />
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
                  ))}
                  {selected
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents={drawingTool === "cursor" ? "none" : "all"}
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1)
                            }
                          />
                          <circle cx={handle.x} cy={handle.y} r={4} fill={stroke} pointerEvents="none" />
                        </g>
                      ))
                    : null}
                </g>
              );
            }

            return (
              <g key={drawing.id} onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}>
                <line
                  x1={points[0].x}
                  y1={points[0].y}
                  x2={points[1].x}
                  y2={points[1].y}
                  stroke="transparent"
                  strokeWidth={12}
                  className={drawing.type === "horizontal" ? "cursor-ns-resize" : "cursor-move"}
                  pointerEvents={drawingTool === "cursor" ? "none" : "stroke"}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
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
                {selected ? (
                  <>
                    {handles.map((handle, index) => (
                      <g key={`${drawing.id}-handle-${index}`}>
                        <circle
                          cx={handle.x}
                          cy={handle.y}
                          r={11}
                          fill="transparent"
                          className={drawing.type === "horizontal" ? "cursor-ns-resize" : "cursor-grab"}
                          pointerEvents={drawingTool === "cursor" ? "none" : "all"}
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
                        <circle cx={handle.x} cy={handle.y} r={4} fill={stroke} pointerEvents="none" />
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

"use client";

import { type MouseEvent, type WheelEvent, useMemo, useState } from "react";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";

type Props = {
  chartData: ChartPoint[];
  indicatorData?: StockIndicatorPoint[];
  label: string;
  indicators: IndicatorSettings;
  indicatorParameters?: IndicatorParameters;
};

export type IndicatorSettings = {
  signals: boolean;
  ma: boolean;
  ema: boolean;
  bollinger: boolean;
  vwap: boolean;
  psar: boolean;
  donchian: boolean;
  volume: boolean;
  rsi: boolean;
  macd: boolean;
  kd: boolean;
  atr: boolean;
  adx: boolean;
  obv: boolean;
  mfi: boolean;
  cci: boolean;
  williamsR: boolean;
  roc: boolean;
  stochRsi: boolean;
};

export type IndicatorKey = keyof IndicatorSettings;

export type IndicatorParameters = {
  maShort: number;
  maMiddle: number;
  maLong: number;
  emaFast: number;
  emaSlow: number;
  bollingerPeriod: number;
  bollingerStdDev: number;
  volumeMa: number;
  rsiPeriod: number;
  macdFast: number;
  macdSlow: number;
  macdSignal: number;
  kdPeriod: number;
  atrPeriod: number;
  adxPeriod: number;
  donchianPeriod: number;
  obvMa: number;
  mfiPeriod: number;
  cciPeriod: number;
  williamsRPeriod: number;
  rocPeriod: number;
  stochRsiPeriod: number;
  stochRsiSmoothK: number;
  stochRsiSmoothD: number;
};

type MergedPoint = ChartPoint & {
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
  ema12: number | null;
  ema26: number | null;
  vwap: number | null;
  psar: number | null;
  donchianUpper: number | null;
  donchianLower: number | null;
  volumeMa20: number | null;
  changePct: number | null;
  bbMiddle: number | null;
  bbUpper: number | null;
  bbLower: number | null;
  rsi14: number | null;
  macd: number | null;
  macdSignal: number | null;
  macdHistogram: number | null;
  k: number | null;
  d: number | null;
  atr14: number | null;
  plusDi14: number | null;
  minusDi14: number | null;
  adx14: number | null;
  obv: number | null;
  obvMa10: number | null;
  mfi14: number | null;
  cci20: number | null;
  williamsR14: number | null;
  roc12: number | null;
  stochRsiK: number | null;
  stochRsiD: number | null;
};

type Panel = {
  key:
    | "volume"
    | "rsi"
    | "macd"
    | "kd"
    | "atr"
    | "adx"
    | "obv"
    | "mfi"
    | "cci"
    | "williamsR"
    | "roc"
    | "stochRsi";
  label: string;
  top: number;
  height: number;
};

type VisibleRangeState = {
  start: number;
  count: number;
  pinnedToLatest: boolean;
  dataKey: string | null;
};

export const indicatorOptions: Array<{ key: IndicatorKey; label: string; description: string }> = [
  { key: "signals", label: "SIGNAL", description: "交叉 / 突破標記" },
  { key: "ma", label: "MA", description: "MA5 / MA20 / MA60" },
  { key: "ema", label: "EMA", description: "EMA12 / EMA26" },
  { key: "bollinger", label: "BOLL", description: "20MA +/- 2SD" },
  { key: "vwap", label: "VWAP", description: "量價均價" },
  { key: "psar", label: "SAR", description: "Parabolic SAR" },
  { key: "donchian", label: "DONCH", description: "20 日通道" },
  { key: "volume", label: "VOL", description: "成交量" },
  { key: "rsi", label: "RSI", description: "RSI 14" },
  { key: "macd", label: "MACD", description: "12 / 26 / 9" },
  { key: "kd", label: "KD", description: "KD 9 / 3" },
  { key: "atr", label: "ATR", description: "ATR 14" },
  { key: "adx", label: "ADX", description: "ADX / +DI / -DI" },
  { key: "obv", label: "OBV", description: "能量潮" },
  { key: "mfi", label: "MFI", description: "Money Flow 14" },
  { key: "cci", label: "CCI", description: "CCI 20" },
  { key: "williamsR", label: "W%R", description: "Williams %R 14" },
  { key: "roc", label: "ROC", description: "ROC 12" },
  { key: "stochRsi", label: "StochRSI", description: "RSI 隨機指標" },
];

export const defaultIndicators: IndicatorSettings = {
  signals: true,
  ma: true,
  ema: false,
  bollinger: false,
  vwap: false,
  psar: false,
  donchian: false,
  volume: true,
  rsi: false,
  macd: false,
  kd: false,
  atr: false,
  adx: false,
  obv: false,
  mfi: false,
  cci: false,
  williamsR: false,
  roc: false,
  stochRsi: false,
};

export const defaultIndicatorParameters: IndicatorParameters = {
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
  obvMa: 10,
  mfiPeriod: 14,
  cciPeriod: 20,
  williamsRPeriod: 14,
  rocPeriod: 12,
  stochRsiPeriod: 14,
  stochRsiSmoothK: 3,
  stochRsiSmoothD: 3,
};

const DEFAULT_VISIBLE_BARS = 80;
const MIN_VISIBLE_BARS = 20;

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value / 1000));
}

function formatTradeValue(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  if (Math.abs(value) >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(1)}億`;
  }

  if (Math.abs(value) >= 10_000) {
    return `${(value / 10_000).toFixed(1)}萬`;
  }

  return new Intl.NumberFormat("zh-TW").format(value);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function formatIndicator(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function validNumber(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && !Number.isNaN(value);
}

function average(values: Array<number | null | undefined>) {
  const valid = values.filter(validNumber);

  if (valid.length === 0) return null;

  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function movingAverage(
  values: Array<number | null | undefined>,
  index: number,
  windowSize: number
): number | null {
  if (index + 1 < windowSize) return null;

  const slice = values.slice(index + 1 - windowSize, index + 1);

  if (slice.some((value) => !validNumber(value))) return null;

  return average(slice);
}

function standardDeviation(
  values: Array<number | null | undefined>,
  index: number,
  windowSize: number
): number | null {
  const mean = movingAverage(values, index, windowSize);

  if (mean === null) return null;

  const meanValue: number = mean;
  const slice = values.slice(index + 1 - windowSize, index + 1).filter(validNumber);

  if (slice.length < windowSize) return null;

  const variance =
    slice.reduce((sum, value) => sum + (value - meanValue) ** 2, 0) / windowSize;

  return Math.sqrt(variance);
}

function calculateChangePct(current: number | null | undefined, previous: number | null | undefined) {
  if (!validNumber(current) || !validNumber(previous) || previous === 0) return null;
  return ((current - previous) / previous) * 100;
}

function calculateRsi(closes: Array<number | null | undefined>, period = 14) {
  return closes.map((close, index) => {
    if (!validNumber(close) || index < period) return null;

    let gain = 0;
    let loss = 0;

    for (let cursor = index - period + 1; cursor <= index; cursor += 1) {
      const current = closes[cursor];
      const previous = closes[cursor - 1];

      if (!validNumber(current) || !validNumber(previous)) return null;

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

function calculateEma(values: Array<number | null | undefined>, period: number) {
  const multiplier = 2 / (period + 1);
  let previousEma: number | null = null;

  return values.map((value) => {
    if (!validNumber(value)) return null;

    if (previousEma === null) {
      previousEma = value;
      return value;
    }

    previousEma = value * multiplier + previousEma * (1 - multiplier);
    return previousEma;
  });
}

function calculateMacd(
  closes: Array<number | null | undefined>,
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9
) {
  const ema12 = calculateEma(closes, fastPeriod);
  const ema26 = calculateEma(closes, slowPeriod);
  const macd = closes.map((_, index) => {
    if (!validNumber(ema12[index]) || !validNumber(ema26[index])) return null;
    return ema12[index] - ema26[index];
  });
  const signal = calculateEma(macd, signalPeriod);
  const histogram = macd.map((value, index) => {
    if (!validNumber(value) || !validNumber(signal[index])) return null;
    return value - signal[index];
  });

  return { macd, signal, histogram };
}

function calculateKd(points: ChartPoint[], period = 9) {
  let previousK = 50;
  let previousD = 50;

  return points.map((point, index) => {
    if (index + 1 < period || !validNumber(point.close)) {
      return { k: null, d: null };
    }

    const slice = points.slice(index + 1 - period, index + 1);
    const highs = slice.map((item) => item.high).filter(validNumber);
    const lows = slice.map((item) => item.low).filter(validNumber);

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
  if (!validNumber(point.high) || !validNumber(point.low) || !validNumber(point.close)) {
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

    if (!validNumber(price) || !validNumber(volume) || volume <= 0) {
      return null;
    }

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
    !validNumber(first.high) ||
    !validNumber(first.low) ||
    !validNumber(first.close) ||
    !validNumber(second.high) ||
    !validNumber(second.low) ||
    !validNumber(second.close)
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
      !validNumber(point.high) ||
      !validNumber(point.low) ||
      !validNumber(previous.high) ||
      !validNumber(previous.low) ||
      !validNumber(previous2.high) ||
      !validNumber(previous2.low)
    ) {
      values[index] = null;
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
    if (index + 1 < period) {
      return { upper: null, lower: null };
    }

    const slice = points.slice(index + 1 - period, index + 1);
    const highs = slice.map((point) => point.high).filter(validNumber);
    const lows = slice.map((point) => point.low).filter(validNumber);

    if (highs.length < period || lows.length < period) {
      return { upper: null, lower: null };
    }

    return {
      upper: Math.max(...highs),
      lower: Math.min(...lows),
    };
  });
}

function calculateTrueRanges(points: ChartPoint[]) {
  return points.map((point, index) => {
    if (!validNumber(point.high) || !validNumber(point.low)) return null;

    const previousClose = points[index - 1]?.close;
    const highLow = point.high - point.low;

    if (!validNumber(previousClose)) return highLow;

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
    if (!validNumber(trueRange)) return null;

    if (index + 1 < period) return null;

    if (previousAtr === null) {
      const slice = trueRanges.slice(index + 1 - period, index + 1);

      if (slice.some((value) => !validNumber(value))) return null;

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
      !validNumber(current.high) ||
      !validNumber(current.low) ||
      !validNumber(previous.high) ||
      !validNumber(previous.low)
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
    if (index < period) {
      return { plusDi: null, minusDi: null, adx: null };
    }

    const trueRange = trueRanges[index];
    const plus = plusDm[index];
    const minus = minusDm[index];

    if (!validNumber(trueRange) || !validNumber(plus) || !validNumber(minus)) {
      return { plusDi: null, minusDi: null, adx: null };
    }

    if (smoothedTr === null || smoothedPlusDm === null || smoothedMinusDm === null) {
      const trSlice = trueRanges.slice(index + 1 - period, index + 1);
      const plusSlice = plusDm.slice(index + 1 - period, index + 1);
      const minusSlice = minusDm.slice(index + 1 - period, index + 1);

      const trValues = trSlice.filter(validNumber);
      const plusValues = plusSlice.filter(validNumber);
      const minusValues = minusSlice.filter(validNumber);

      if (
        trValues.length < period ||
        plusValues.length < period ||
        minusValues.length < period
      ) {
        return { plusDi: null, minusDi: null, adx: null };
      }

      smoothedTr = trValues.reduce((sum, value) => sum + value, 0);
      smoothedPlusDm = plusValues.reduce((sum, value) => sum + value, 0);
      smoothedMinusDm = minusValues.reduce((sum, value) => sum + value, 0);
    } else {
      smoothedTr = smoothedTr - smoothedTr / period + trueRange;
      smoothedPlusDm = smoothedPlusDm - smoothedPlusDm / period + plus;
      smoothedMinusDm = smoothedMinusDm - smoothedMinusDm / period + minus;
    }

    if (smoothedTr === null || smoothedPlusDm === null || smoothedMinusDm === null || smoothedTr === 0) {
      return { plusDi: null, minusDi: null, adx: null };
    }

    const plusDi = (smoothedPlusDm / smoothedTr) * 100;
    const minusDi = (smoothedMinusDm / smoothedTr) * 100;
    const diTotal = plusDi + minusDi;
    const dx = diTotal === 0 ? 0 : (Math.abs(plusDi - minusDi) / diTotal) * 100;
    dxValues[index] = dx;

    if (index >= period * 2 - 1) {
      if (previousAdx === null) {
        const dxSlice = dxValues.slice(index + 1 - period, index + 1);

        if (!dxSlice.some((value) => !validNumber(value))) {
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

    if (!validNumber(point.close) || !validNumber(point.volume)) {
      return index === 0 ? 0 : currentObv;
    }

    if (!validNumber(previousClose)) {
      return currentObv;
    }

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

    if (!validNumber(price) || !validNumber(previousPrice) || !validNumber(volume)) {
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

    const positiveValues = positiveSlice.filter(validNumber);
    const negativeValues = negativeSlice.filter(validNumber);

    if (positiveValues.length < period || negativeValues.length < period) {
      return null;
    }

    const positive = positiveValues.reduce((sum, value) => sum + value, 0);
    const negative = negativeValues.reduce((sum, value) => sum + value, 0);

    if (negative === 0) return 100;
    if (positive === 0) return 0;

    const moneyRatio = positive / negative;
    return 100 - 100 / (1 + moneyRatio);
  });
}

function calculateCci(points: ChartPoint[], period = 20) {
  const typicalPrices = points.map(typicalPrice);

  return typicalPrices.map((price, index) => {
    if (!validNumber(price) || index + 1 < period) return null;

    const slice = typicalPrices.slice(index + 1 - period, index + 1);
    const values = slice.filter(validNumber);

    if (values.length < period) return null;

    const mean = average(values);

    if (mean === null) return null;

    const meanDeviation =
      values.reduce((sum, value) => sum + Math.abs(value - mean), 0) / period;

    if (meanDeviation === 0) return 0;

    return (price - mean) / (0.015 * meanDeviation);
  });
}

function calculateWilliamsR(points: ChartPoint[], period = 14) {
  return points.map((point, index) => {
    if (!validNumber(point.close) || index + 1 < period) return null;

    const slice = points.slice(index + 1 - period, index + 1);
    const highs = slice.map((item) => item.high).filter(validNumber);
    const lows = slice.map((item) => item.low).filter(validNumber);

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

    if (!validNumber(close) || !validNumber(previous) || previous === 0) {
      return null;
    }

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
    if (!validNumber(rsi) || index + 1 < period) return null;

    const slice = rsiValues.slice(index + 1 - period, index + 1);

    if (slice.some((value) => !validNumber(value))) return null;

    const minRsi = Math.min(...slice.filter(validNumber));
    const maxRsi = Math.max(...slice.filter(validNumber));

    if (maxRsi === minRsi) return 50;

    return ((rsi - minRsi) / (maxRsi - minRsi)) * 100;
  });
  const k = rawValues.map((_, index) => movingAverage(rawValues, index, smoothK));
  const d = k.map((_, index) => movingAverage(k, index, smoothD));

  return { k, d };
}

function numericRange(
  values: Array<number | null | undefined>,
  options?: { includeZero?: boolean; min?: number; max?: number }
) {
  const valid = values.filter(validNumber);

  if (options?.min !== undefined && options?.max !== undefined) {
    return { min: options.min, max: options.max };
  }

  if (valid.length === 0) {
    return { min: options?.min ?? 0, max: options?.max ?? 1 };
  }

  let min = options?.min ?? Math.min(...valid);
  let max = options?.max ?? Math.max(...valid);

  if (options?.includeZero) {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }

  const range = max - min || Math.max(Math.abs(max), 1);
  const padding = range * 0.08;

  return {
    min: options?.min ?? min - padding,
    max: options?.max ?? max + padding,
  };
}

function buildLinePath(
  data: MergedPoint[],
  getValue: (point: MergedPoint) => number | null,
  getX: (index: number) => number,
  getY: (value: number) => number
) {
  let path = "";
  let started = false;

  data.forEach((point, index) => {
    const value = getValue(point);

    if (value === null || Number.isNaN(value)) {
      started = false;
      return;
    }

    const x = getX(index);
    const y = getY(value);

    if (!started) {
      path += `M ${x.toFixed(2)} ${y.toFixed(2)} `;
      started = true;
      return;
    }

    path += `L ${x.toFixed(2)} ${y.toFixed(2)} `;
  });

  return path.trim();
}

function buildBandAreaPath(
  data: MergedPoint[],
  getUpper: (point: MergedPoint) => number | null,
  getLower: (point: MergedPoint) => number | null,
  getX: (index: number) => number,
  getY: (value: number) => number
) {
  const points = data
    .map((point, index) => ({
      index,
      upper: getUpper(point),
      lower: getLower(point),
    }))
    .filter((point): point is { index: number; upper: number; lower: number } => {
      return validNumber(point.upper) && validNumber(point.lower);
    });

  if (points.length < 2) return "";

  const upperPath = points
    .map((point, pathIndex) => {
      const prefix = pathIndex === 0 ? "M" : "L";
      return `${prefix} ${getX(point.index).toFixed(2)} ${getY(point.upper).toFixed(2)}`;
    })
    .join(" ");
  const lowerPath = points
    .slice()
    .reverse()
    .map((point) => {
      return `L ${getX(point.index).toFixed(2)} ${getY(point.lower).toFixed(2)}`;
    })
    .join(" ");

  return `${upperPath} ${lowerPath} Z`;
}

function valueTone(value: number | null | undefined) {
  if (!validNumber(value)) return "text-slate-700";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
}

function labelPosition(
  x: number,
  paddingLeft: number,
  paddingRight: number,
  width: number
) {
  const labelWidth = 84;
  const isNearRight = x > width - paddingRight - labelWidth;

  return {
    x: isNearRight ? x - 10 : x + 10,
    anchor: isNearRight ? "end" : "start",
  } as const;
}

type ChartSignal = {
  key: string;
  index: number;
  label: string;
  direction: "bullish" | "bearish" | "neutral";
  price: number;
};

function buildChartSignals(data: MergedPoint[]) {
  const signals: ChartSignal[] = [];

  for (let index = 1; index < data.length; index += 1) {
    const point = data[index];
    const previous = data[index - 1];
    const bullishPrice = point.low ?? point.close;
    const bearishPrice = point.high ?? point.close;

    if (
      validNumber(previous.ema12) &&
      validNumber(previous.ema26) &&
      validNumber(point.ema12) &&
      validNumber(point.ema26) &&
      validNumber(bullishPrice) &&
      previous.ema12 <= previous.ema26 &&
      point.ema12 > point.ema26
    ) {
      signals.push({
        key: `${point.time}-ema-up`,
        index,
        label: "EMA金叉",
        direction: "bullish",
        price: bullishPrice,
      });
    }

    if (
      validNumber(previous.ema12) &&
      validNumber(previous.ema26) &&
      validNumber(point.ema12) &&
      validNumber(point.ema26) &&
      validNumber(bearishPrice) &&
      previous.ema12 >= previous.ema26 &&
      point.ema12 < point.ema26
    ) {
      signals.push({
        key: `${point.time}-ema-down`,
        index,
        label: "EMA死叉",
        direction: "bearish",
        price: bearishPrice,
      });
    }

    if (
      validNumber(previous.macd) &&
      validNumber(previous.macdSignal) &&
      validNumber(point.macd) &&
      validNumber(point.macdSignal) &&
      validNumber(bullishPrice) &&
      previous.macd <= previous.macdSignal &&
      point.macd > point.macdSignal
    ) {
      signals.push({
        key: `${point.time}-macd-up`,
        index,
        label: "MACD翻紅",
        direction: "bullish",
        price: bullishPrice,
      });
    }

    if (
      validNumber(previous.macd) &&
      validNumber(previous.macdSignal) &&
      validNumber(point.macd) &&
      validNumber(point.macdSignal) &&
      validNumber(bearishPrice) &&
      previous.macd >= previous.macdSignal &&
      point.macd < point.macdSignal
    ) {
      signals.push({
        key: `${point.time}-macd-down`,
        index,
        label: "MACD翻黑",
        direction: "bearish",
        price: bearishPrice,
      });
    }

    if (
      validNumber(point.close) &&
      validNumber(previous.donchianUpper) &&
      validNumber(bullishPrice) &&
      point.close > previous.donchianUpper
    ) {
      signals.push({
        key: `${point.time}-donch-up`,
        index,
        label: "通道突破",
        direction: "bullish",
        price: bullishPrice,
      });
    }

    if (
      validNumber(point.close) &&
      validNumber(previous.donchianLower) &&
      validNumber(bearishPrice) &&
      point.close < previous.donchianLower
    ) {
      signals.push({
        key: `${point.time}-donch-down`,
        index,
        label: "通道跌破",
        direction: "bearish",
        price: bearishPrice,
      });
    }

    if (
      validNumber(point.volume) &&
      validNumber(point.volumeMa20) &&
      validNumber(point.changePct) &&
      validNumber(bullishPrice) &&
      point.volumeMa20 > 0 &&
      point.volume / point.volumeMa20 >= 1.8 &&
      point.changePct > 0
    ) {
      signals.push({
        key: `${point.time}-volume-up`,
        index,
        label: "放量上攻",
        direction: "bullish",
        price: bullishPrice,
      });
    }

    if (
      validNumber(previous.adx14) &&
      validNumber(point.adx14) &&
      validNumber(point.close) &&
      previous.adx14 <= 25 &&
      point.adx14 > 25
    ) {
      signals.push({
        key: `${point.time}-adx-trend`,
        index,
        label: "趨勢成形",
        direction: "neutral",
        price: point.close,
      });
    }
  }

  return signals;
}

export default function StockKLineChart({
  chartData,
  indicatorData = [],
  label,
  indicators,
  indicatorParameters,
}: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [visibleRange, setVisibleRange] = useState<VisibleRangeState>({
    start: 0,
    count: DEFAULT_VISIBLE_BARS,
    pinnedToLatest: true,
    dataKey: null,
  });
  const params = useMemo(
    () => ({
      ...defaultIndicatorParameters,
      ...(indicatorParameters ?? {}),
    }),
    [indicatorParameters]
  );

  const data = useMemo<MergedPoint[]>(() => {
    const indicatorByTime = new Map<string, StockIndicatorPoint>();

    indicatorData.forEach((point) => {
      indicatorByTime.set(point.time, point);
    });

    const closes = chartData.map((point) => point.close);
    const volumes = chartData.map((point) => point.volume);
    const rsi = calculateRsi(closes, params.rsiPeriod);
    const ema12 = calculateEma(closes, params.emaFast);
    const ema26 = calculateEma(closes, params.emaSlow);
    const macd = calculateMacd(
      closes,
      params.macdFast,
      params.macdSlow,
      params.macdSignal
    );
    const kd = calculateKd(chartData, params.kdPeriod);
    const vwap = calculateVwap(chartData);
    const psar = calculateParabolicSar(chartData);
    const donchian = calculateDonchian(chartData, params.donchianPeriod);
    const atr = calculateAtr(chartData, params.atrPeriod);
    const dmi = calculateDmi(chartData, params.adxPeriod);
    const obv = calculateObv(chartData);
    const obvMa10 = obv.map((_, index) => movingAverage(obv, index, params.obvMa));
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

    return chartData.map((point, index) => {
      const indicator = indicatorByTime.get(point.time);
      const previousClose = chartData[index - 1]?.close;
      const maShort =
        indicator?.ma?.[`ma${params.maShort}`] ?? movingAverage(closes, index, params.maShort);
      const maMiddle =
        indicator?.ma?.[`ma${params.maMiddle}`] ?? movingAverage(closes, index, params.maMiddle);
      const maLong =
        indicator?.ma?.[`ma${params.maLong}`] ?? movingAverage(closes, index, params.maLong);
      const bbMiddle = movingAverage(closes, index, params.bollingerPeriod);
      const standardDev20 = standardDeviation(closes, index, params.bollingerPeriod);

      return {
        ...point,
        ma5: maShort,
        ma20: maMiddle,
        ma60: maLong,
        ema12: ema12[index],
        ema26: ema26[index],
        vwap: vwap[index],
        psar: psar[index],
        donchianUpper: donchian[index].upper,
        donchianLower: donchian[index].lower,
        volumeMa20:
          indicator?.volume_ma?.[`volume_ma${params.volumeMa}`] ??
          movingAverage(volumes, index, params.volumeMa),
        changePct: indicator?.change_pct ?? calculateChangePct(point.close, previousClose),
        bbMiddle,
        bbUpper:
          bbMiddle !== null && standardDev20 !== null
            ? bbMiddle + standardDev20 * params.bollingerStdDev
            : null,
        bbLower:
          bbMiddle !== null && standardDev20 !== null
            ? bbMiddle - standardDev20 * params.bollingerStdDev
            : null,
        rsi14: rsi[index],
        macd: macd.macd[index],
        macdSignal: macd.signal[index],
        macdHistogram: macd.histogram[index],
        k: kd[index].k,
        d: kd[index].d,
        atr14: atr[index],
        plusDi14: dmi[index].plusDi,
        minusDi14: dmi[index].minusDi,
        adx14: dmi[index].adx,
        obv: obv[index],
        obvMa10: obvMa10[index],
        mfi14: mfi[index],
        cci20: cci[index],
        williamsR14: williamsR[index],
        roc12: roc[index],
        stochRsiK: stochRsi.k[index],
        stochRsiD: stochRsi.d[index],
      };
    });
  }, [chartData, indicatorData, params]);

  const dataKey = `${label}:${data.length}:${data[0]?.time ?? ""}:${data[data.length - 1]?.time ?? ""}`;
  const activeVisibleRange =
    visibleRange.dataKey === dataKey
      ? visibleRange
      : {
          ...visibleRange,
          start: 0,
          count: DEFAULT_VISIBLE_BARS,
          pinnedToLatest: true,
          dataKey,
        };
  const minVisibleBars = Math.min(MIN_VISIBLE_BARS, Math.max(data.length, 1));
  const maxVisibleBars = Math.max(minVisibleBars, data.length || minVisibleBars);
  const visibleBarCount = Math.round(
    clamp(activeVisibleRange.count, minVisibleBars, maxVisibleBars)
  );
  const maxVisibleStart = Math.max(0, data.length - visibleBarCount);
  const visibleStart = Math.round(
    clamp(
      activeVisibleRange.pinnedToLatest ? maxVisibleStart : activeVisibleRange.start,
      0,
      maxVisibleStart
    )
  );
  const visibleEnd = Math.min(data.length, visibleStart + visibleBarCount);
  const visibleData = data.slice(visibleStart, visibleEnd);
  const canMoveRange = data.length > visibleData.length;
  const visibleStep = Math.max(1, Math.round(visibleBarCount * 0.25));

  function updateVisibleCount(nextCount: number) {
    const count = Math.round(clamp(nextCount, minVisibleBars, maxVisibleBars));
    const currentEnd = visibleStart + visibleBarCount;
    const nextMaxStart = Math.max(0, data.length - count);
    const nextStart = Math.round(clamp(currentEnd - count, 0, nextMaxStart));

    setHoverIndex(null);
    setVisibleRange({
      start: nextStart,
      count,
      pinnedToLatest: nextStart === nextMaxStart,
      dataKey,
    });
  }

  function panVisibleBars(delta: number) {
    const nextStart = Math.round(clamp(visibleStart + delta, 0, maxVisibleStart));

    setHoverIndex(null);
    setVisibleRange({
      start: nextStart,
      count: visibleBarCount,
      pinnedToLatest: nextStart === maxVisibleStart,
      dataKey,
    });
  }

  function jumpToLatest() {
    setHoverIndex(null);
    setVisibleRange({
      start: maxVisibleStart,
      count: visibleBarCount,
      pinnedToLatest: true,
      dataKey,
    });
  }

  function showAllBars() {
    setHoverIndex(null);
    setVisibleRange({
      start: 0,
      count: maxVisibleBars,
      pinnedToLatest: true,
      dataKey,
    });
  }

  const safeHoverIndex =
    hoverIndex !== null && hoverIndex >= 0 && hoverIndex < visibleData.length ? hoverIndex : null;
  const hoveredPoint =
    safeHoverIndex !== null
      ? visibleData[safeHoverIndex]
      : visibleData[visibleData.length - 1] ?? null;

  if (data.length < 1) {
    return (
      <div className="flex h-[420px] items-center justify-center border border-slate-200 bg-white text-sm text-slate-500">
        K 線資料不足
      </div>
    );
  }

  const width = 1000;
  const paddingLeft = 58;
  const paddingRight = 28;
  const chartTop = 28;
  const priceHeight = 260;
  const panelGap = 24;
  const panelHeight = 72;
  const bottomPadding = 30;
  const usableWidth = width - paddingLeft - paddingRight;

  const panels: Panel[] = [];
  let nextPanelTop = chartTop + priceHeight + panelGap;

  function addPanel(enabled: boolean, key: Panel["key"], panelLabel: string) {
    if (!enabled) return;

    panels.push({
      key,
      label: panelLabel,
      top: nextPanelTop,
      height: panelHeight,
    });
    nextPanelTop += panelHeight + panelGap;
  }

  addPanel(indicators.volume, "volume", "成交量(張)");
  addPanel(indicators.rsi, "rsi", `RSI ${params.rsiPeriod}`);
  addPanel(indicators.macd, "macd", `MACD ${params.macdFast}/${params.macdSlow}/${params.macdSignal}`);
  addPanel(indicators.kd, "kd", `KD ${params.kdPeriod}`);
  addPanel(indicators.atr, "atr", `ATR ${params.atrPeriod}`);
  addPanel(indicators.adx, "adx", "ADX / DMI");
  addPanel(indicators.obv, "obv", "OBV");
  addPanel(indicators.mfi, "mfi", `MFI ${params.mfiPeriod}`);
  addPanel(indicators.cci, "cci", `CCI ${params.cciPeriod}`);
  addPanel(indicators.williamsR, "williamsR", "Williams %R");
  addPanel(indicators.roc, "roc", `ROC ${params.rocPeriod}`);
  addPanel(indicators.stochRsi, "stochRsi", "StochRSI");

  const height = Math.max(360, nextPanelTop - panelGap + bottomPadding);
  const labelY = height - 10;
  const priceBottom = chartTop + priceHeight;
  const plotBottom = panels.length > 0 ? panels[panels.length - 1].top + panelHeight : priceBottom;

  const priceValues = visibleData
    .flatMap((point) => [
      point.open,
      point.high,
      point.low,
      point.close,
      indicators.ma ? point.ma5 : null,
      indicators.ma ? point.ma20 : null,
      indicators.ma ? point.ma60 : null,
      indicators.ema ? point.ema12 : null,
      indicators.ema ? point.ema26 : null,
      indicators.vwap ? point.vwap : null,
      indicators.psar ? point.psar : null,
      indicators.donchian ? point.donchianUpper : null,
      indicators.donchian ? point.donchianLower : null,
      indicators.bollinger ? point.bbUpper : null,
      indicators.bollinger ? point.bbLower : null,
    ])
    .filter(validNumber);

  const minPrice = priceValues.length > 0 ? Math.min(...priceValues) : 0;
  const maxPrice = priceValues.length > 0 ? Math.max(...priceValues) : 1;
  const pricePadding = (maxPrice - minPrice || 1) * 0.08;
  const yMin = minPrice - pricePadding;
  const yMax = maxPrice + pricePadding;
  const yRange = yMax - yMin || 1;
  const volumes = visibleData.map((point) => point.volume).filter(validNumber);
  const maxVolume = Math.max(...volumes, 1);
  const macdValues = visibleData
    .flatMap((point) => [point.macd, point.macdSignal, point.macdHistogram])
    .filter(validNumber);
  const macdAbsMax = Math.max(...macdValues.map((value) => Math.abs(value)), 1);
  const atrRange = numericRange(visibleData.map((point) => point.atr14), { min: 0 });
  const obvRange = numericRange(
    visibleData.flatMap((point) => [point.obv, point.obvMa10]),
    { includeZero: true }
  );
  const cciRange = numericRange(
    [...visibleData.map((point) => point.cci20), -100, 0, 100],
    { includeZero: true }
  );
  const rocRange = numericRange(visibleData.map((point) => point.roc12), { includeZero: true });
  const candleWidth = clamp((usableWidth / visibleData.length) * 0.58, 3, 12);
  const rangeHigh = visibleData.reduce<{ index: number; value: number } | null>(
    (best, point, index) => {
      const value = point.high ?? point.close;

      if (!validNumber(value)) return best;
      if (best === null || value > best.value) return { index, value };

      return best;
    },
    null
  );
  const rangeLow = visibleData.reduce<{ index: number; value: number } | null>(
    (best, point, index) => {
      const value = point.low ?? point.close;

      if (!validNumber(value)) return best;
      if (best === null || value < best.value) return { index, value };

      return best;
    },
    null
  );
  const visibleChartSignals = indicators.signals
    ? buildChartSignals(data)
        .filter((signal) => signal.index >= visibleStart && signal.index < visibleEnd)
        .map((signal) => ({
          ...signal,
          index: signal.index - visibleStart,
        }))
        .slice(-18)
    : [];

  function getX(index: number) {
    if (visibleData.length <= 1) return paddingLeft;
    return paddingLeft + (index / (visibleData.length - 1)) * usableWidth;
  }

  function getPriceY(value: number) {
    return chartTop + ((yMax - value) / yRange) * priceHeight;
  }

  function getPanelY(panel: Panel, value: number, min: number, max: number) {
    const range = max - min || 1;
    return panel.top + ((max - value) / range) * panel.height;
  }

  function getVolumeY(panel: Panel, value: number) {
    return panel.top + panel.height - (value / maxVolume) * panel.height;
  }

  function handleMouseMove(event: MouseEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const localX = paddingLeft + ratio * usableWidth;
    const dataRatio = (localX - paddingLeft) / usableWidth;
    const index = Math.round(dataRatio * (visibleData.length - 1));
    setHoverIndex(clamp(index, 0, visibleData.length - 1));
  }

  function handleWheel(event: WheelEvent<SVGRectElement>) {
    if (!canMoveRange && visibleBarCount <= minVisibleBars) return;

    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      updateVisibleCount(visibleBarCount * (event.deltaY > 0 ? 1.18 : 0.82));
      return;
    }

    const hasHorizontalIntent =
      event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY);

    if (!hasHorizontalIntent || !canMoveRange) return;

    event.preventDefault();
    const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
    panVisibleBars(Math.sign(delta) * Math.max(1, Math.round(visibleBarCount * 0.08)));
  }

  const ma5Path = buildLinePath(visibleData, (point) => point.ma5, getX, getPriceY);
  const ma20Path = buildLinePath(visibleData, (point) => point.ma20, getX, getPriceY);
  const ma60Path = buildLinePath(visibleData, (point) => point.ma60, getX, getPriceY);
  const ema12Path = buildLinePath(visibleData, (point) => point.ema12, getX, getPriceY);
  const ema26Path = buildLinePath(visibleData, (point) => point.ema26, getX, getPriceY);
  const vwapPath = buildLinePath(visibleData, (point) => point.vwap, getX, getPriceY);
  const bbUpperPath = buildLinePath(visibleData, (point) => point.bbUpper, getX, getPriceY);
  const bbMiddlePath = buildLinePath(visibleData, (point) => point.bbMiddle, getX, getPriceY);
  const bbLowerPath = buildLinePath(visibleData, (point) => point.bbLower, getX, getPriceY);
  const bbAreaPath = buildBandAreaPath(visibleData, (point) => point.bbUpper, (point) => point.bbLower, getX, getPriceY);
  const donchianUpperPath = buildLinePath(visibleData, (point) => point.donchianUpper, getX, getPriceY);
  const donchianLowerPath = buildLinePath(visibleData, (point) => point.donchianLower, getX, getPriceY);
  const donchianAreaPath = buildBandAreaPath(
    visibleData,
    (point) => point.donchianUpper,
    (point) => point.donchianLower,
    getX,
    getPriceY
  );
  const hoverX = safeHoverIndex !== null ? getX(safeHoverIndex) : null;

  return (
    <div className="border border-slate-200 bg-white">
      <div className="flex min-h-16 items-start justify-between gap-4 border-b border-slate-200 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">K 線 / 技術指標</div>
          <div className="mt-1 text-xs text-slate-500">
            {label} · {data.length} 根 K 線
          </div>
        </div>

        <div className="flex max-w-[760px] flex-col items-end gap-2">
          {hoveredPoint ? (
            <div className="grid grid-cols-5 gap-x-4 gap-y-1 text-right text-xs">
              <div>
                <span className="text-slate-400">日期</span>
                <div className="font-semibold text-slate-800">{hoveredPoint.time}</div>
              </div>
              <div>
                <span className="text-slate-400">收盤</span>
                <div className="font-semibold text-slate-800">
                  {formatPrice(hoveredPoint.close)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">漲跌</span>
                <div className={`font-semibold ${valueTone(hoveredPoint.changePct)}`}>
                  {formatPct(hoveredPoint.changePct)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">成交量(張)</span>
                <div className="font-semibold text-slate-800">
                  {formatLots(hoveredPoint.volume)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">成交金額</span>
                <div className="font-semibold text-slate-800">
                  {formatTradeValue(hoveredPoint.trade_value)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">
                  MA{params.maShort}/{params.maMiddle}/{params.maLong}
                </span>
                <div className="font-semibold text-slate-800">
                  {formatPrice(hoveredPoint.ma5)} / {formatPrice(hoveredPoint.ma20)} /{" "}
                  {formatPrice(hoveredPoint.ma60)}
                </div>
              </div>
              {indicators.ema ? (
                <div>
                  <span className="text-slate-400">
                    EMA{params.emaFast}/{params.emaSlow}
                  </span>
                  <div className="font-semibold text-slate-800">
                    {formatPrice(hoveredPoint.ema12)} / {formatPrice(hoveredPoint.ema26)}
                  </div>
                </div>
              ) : null}
              {indicators.vwap ? (
                <div>
                  <span className="text-slate-400">VWAP</span>
                  <div className="font-semibold text-slate-800">
                    {formatPrice(hoveredPoint.vwap)}
                  </div>
                </div>
              ) : null}
              {indicators.psar ? (
                <div>
                  <span className="text-slate-400">SAR</span>
                  <div className="font-semibold text-slate-800">
                    {formatPrice(hoveredPoint.psar)}
                  </div>
                </div>
              ) : null}
              <div>
                <span className="text-slate-400">RSI</span>
                <div className="font-semibold text-slate-800">
                  {formatIndicator(hoveredPoint.rsi14)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">MACD</span>
                <div className={`font-semibold ${valueTone(hoveredPoint.macdHistogram)}`}>
                  {formatIndicator(hoveredPoint.macdHistogram)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">K/D</span>
                <div className="font-semibold text-slate-800">
                  {formatIndicator(hoveredPoint.k)} / {formatIndicator(hoveredPoint.d)}
                </div>
              </div>
              {indicators.atr ? (
                <div>
                  <span className="text-slate-400">ATR</span>
                  <div className="font-semibold text-slate-800">
                    {formatIndicator(hoveredPoint.atr14)}
                  </div>
                </div>
              ) : null}
              {indicators.adx ? (
                <div>
                  <span className="text-slate-400">ADX/+DI/-DI</span>
                  <div className="font-semibold text-slate-800">
                    {formatIndicator(hoveredPoint.adx14)} / {formatIndicator(hoveredPoint.plusDi14)} /{" "}
                    {formatIndicator(hoveredPoint.minusDi14)}
                  </div>
                </div>
              ) : null}
              {indicators.obv ? (
                <div>
                  <span className="text-slate-400">OBV(張)</span>
                  <div className={`font-semibold ${valueTone(hoveredPoint.obv)}`}>
                    {formatLots(hoveredPoint.obv)}
                  </div>
                </div>
              ) : null}
              {indicators.mfi ? (
                <div>
                  <span className="text-slate-400">MFI</span>
                  <div className="font-semibold text-slate-800">
                    {formatIndicator(hoveredPoint.mfi14)}
                  </div>
                </div>
              ) : null}
              {indicators.cci ? (
                <div>
                  <span className="text-slate-400">CCI</span>
                  <div className={`font-semibold ${valueTone(hoveredPoint.cci20)}`}>
                    {formatIndicator(hoveredPoint.cci20)}
                  </div>
                </div>
              ) : null}
              {indicators.williamsR ? (
                <div>
                  <span className="text-slate-400">Williams %R</span>
                  <div className="font-semibold text-slate-800">
                    {formatIndicator(hoveredPoint.williamsR14)}
                  </div>
                </div>
              ) : null}
              {indicators.roc ? (
                <div>
                  <span className="text-slate-400">ROC</span>
                  <div className={`font-semibold ${valueTone(hoveredPoint.roc12)}`}>
                    {formatPct(hoveredPoint.roc12)}
                  </div>
                </div>
              ) : null}
              {indicators.stochRsi ? (
                <div>
                  <span className="text-slate-400">StochRSI K/D</span>
                  <div className="font-semibold text-slate-800">
                    {formatIndicator(hoveredPoint.stochRsiK)} / {formatIndicator(hoveredPoint.stochRsiD)}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="flex w-full flex-wrap items-center justify-end gap-2 text-xs">
            <span className="whitespace-nowrap text-slate-500">
              {visibleStart + 1}-{visibleEnd} / {data.length}
            </span>
            <button
              type="button"
              aria-label="往左回看"
              title="往左回看"
              onClick={() => panVisibleBars(-visibleStep)}
              disabled={!canMoveRange || visibleStart <= 0}
              className="h-7 w-7 border border-slate-300 bg-white font-semibold text-slate-700 hover:border-slate-500 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              &lt;
            </button>
            <button
              type="button"
              aria-label="往右移動"
              title="往右移動"
              onClick={() => panVisibleBars(visibleStep)}
              disabled={!canMoveRange || visibleStart >= maxVisibleStart}
              className="h-7 w-7 border border-slate-300 bg-white font-semibold text-slate-700 hover:border-slate-500 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              &gt;
            </button>
            <button
              type="button"
              aria-label="放大 K 線"
              title="放大 K 線"
              onClick={() => updateVisibleCount(visibleBarCount * 0.72)}
              disabled={visibleBarCount <= minVisibleBars}
              className="h-7 w-7 border border-slate-300 bg-white font-semibold text-slate-700 hover:border-slate-500 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              +
            </button>
            <button
              type="button"
              aria-label="縮小 K 線"
              title="縮小 K 線"
              onClick={() => updateVisibleCount(visibleBarCount * 1.38)}
              disabled={visibleBarCount >= maxVisibleBars}
              className="h-7 w-7 border border-slate-300 bg-white font-semibold text-slate-700 hover:border-slate-500 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              -
            </button>
            <button
              type="button"
              onClick={jumpToLatest}
              disabled={!canMoveRange || visibleStart >= maxVisibleStart}
              className="h-7 border border-slate-300 bg-white px-2 font-semibold text-slate-700 hover:border-slate-500 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              最新
            </button>
            <button
              type="button"
              onClick={showAllBars}
              disabled={visibleBarCount >= maxVisibleBars}
              className="h-7 border border-slate-300 bg-white px-2 font-semibold text-slate-700 hover:border-slate-500 disabled:cursor-not-allowed disabled:text-slate-300"
            >
              全部
            </button>
            <input
              type="range"
              min={0}
              max={maxVisibleStart}
              step={1}
              value={visibleStart}
              aria-label="K 線顯示區間"
              disabled={!canMoveRange}
              onChange={(event) => {
                const nextStart = Number(event.target.value);

                setHoverIndex(null);
                setVisibleRange({
                  start: nextStart,
                  count: visibleBarCount,
                  pinnedToLatest: nextStart >= maxVisibleStart,
                  dataKey,
                });
              }}
              className="h-7 w-40 accent-slate-900 disabled:opacity-40"
            />
          </div>
        </div>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }}>
        <rect x="0" y="0" width={width} height={height} className="fill-white" />

        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = chartTop + ratio * priceHeight;
          const price = yMax - ratio * yRange;

          return (
            <g key={ratio}>
              <line
                x1={paddingLeft}
                x2={width - paddingRight}
                y1={y}
                y2={y}
                className="stroke-slate-100"
              />
              <text
                x={paddingLeft - 10}
                y={y + 4}
                textAnchor="end"
                className="fill-slate-500 text-[11px]"
              >
                {formatPrice(price)}
              </text>
            </g>
          );
        })}

        {indicators.bollinger && bbAreaPath ? (
          <path d={bbAreaPath} className="fill-sky-100/70" />
        ) : null}

        {indicators.donchian && donchianAreaPath ? (
          <path d={donchianAreaPath} className="fill-lime-100/50" />
        ) : null}

        {visibleData.map((point, index) => {
          const open = point.open ?? point.close;
          const close = point.close ?? point.open;
          const high = point.high ?? Math.max(open ?? 0, close ?? 0);
          const low = point.low ?? Math.min(open ?? 0, close ?? 0);

          if (!validNumber(open) || !validNumber(close) || !validNumber(high) || !validNumber(low)) {
            return null;
          }

          const x = getX(index);
          const isUp = close >= open;
          const highY = getPriceY(high);
          const lowY = getPriceY(low);
          const openY = getPriceY(open);
          const closeY = getPriceY(close);
          const bodyY = Math.min(openY, closeY);
          const bodyHeight = Math.max(Math.abs(openY - closeY), 1.5);
          const candleClass = isUp
            ? "fill-red-600 stroke-red-600"
            : "fill-emerald-600 stroke-emerald-600";

          return (
            <g key={`${point.time}-${index}`}>
              <line
                x1={x}
                x2={x}
                y1={highY}
                y2={lowY}
                className={candleClass}
                strokeWidth="1.5"
              />
              <rect
                x={x - candleWidth / 2}
                y={bodyY}
                width={candleWidth}
                height={bodyHeight}
                className={candleClass}
              />
            </g>
          );
        })}

        {indicators.bollinger ? (
          <>
            {bbUpperPath ? (
              <path d={bbUpperPath} fill="none" strokeWidth="1.4" className="stroke-sky-500" />
            ) : null}
            {bbMiddlePath ? (
              <path d={bbMiddlePath} fill="none" strokeWidth="1.2" className="stroke-sky-400" strokeDasharray="4 4" />
            ) : null}
            {bbLowerPath ? (
              <path d={bbLowerPath} fill="none" strokeWidth="1.4" className="stroke-sky-500" />
            ) : null}
          </>
        ) : null}

        {indicators.donchian ? (
          <>
            {donchianUpperPath ? (
              <path d={donchianUpperPath} fill="none" strokeWidth="1.3" className="stroke-lime-600" />
            ) : null}
            {donchianLowerPath ? (
              <path d={donchianLowerPath} fill="none" strokeWidth="1.3" className="stroke-lime-600" />
            ) : null}
          </>
        ) : null}

        {indicators.ma && ma5Path ? (
          <path
            d={ma5Path}
            fill="none"
            strokeWidth="2"
            className="stroke-blue-600"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ma && ma20Path ? (
          <path
            d={ma20Path}
            fill="none"
            strokeWidth="2"
            className="stroke-amber-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ma && ma60Path ? (
          <path
            d={ma60Path}
            fill="none"
            strokeWidth="1.6"
            className="stroke-purple-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ema && ema12Path ? (
          <path
            d={ema12Path}
            fill="none"
            strokeWidth="1.8"
            className="stroke-cyan-600"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ema && ema26Path ? (
          <path
            d={ema26Path}
            fill="none"
            strokeWidth="1.8"
            className="stroke-rose-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.vwap && vwapPath ? (
          <path
            d={vwapPath}
            fill="none"
            strokeWidth="2"
            className="stroke-slate-700"
            strokeDasharray="6 4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.psar
          ? visibleData.map((point, index) => {
              if (!validNumber(point.psar)) return null;

              return (
                <circle
                  key={`${point.time}-psar`}
                  cx={getX(index)}
                  cy={getPriceY(point.psar)}
                  r="2.5"
                  className="fill-violet-600"
                />
              );
            })
          : null}

        {rangeHigh ? (
          <g>
            {(() => {
              const x = getX(rangeHigh.index);
              const y = getPriceY(rangeHigh.value);
              const label = labelPosition(x, paddingLeft, paddingRight, width);
              const labelY = clamp(y - 12, chartTop + 12, priceBottom - 8);

              return (
                <>
                  <circle cx={x} cy={y} r="3.5" className="fill-red-600" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={labelY}
                    className="stroke-red-400"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={labelY - 3}
                    textAnchor={label.anchor}
                    className="fill-red-600 text-[11px] font-semibold"
                  >
                    最高 {formatPrice(rangeHigh.value)}
                  </text>
                </>
              );
            })()}
          </g>
        ) : null}

        {rangeLow ? (
          <g>
            {(() => {
              const x = getX(rangeLow.index);
              const y = getPriceY(rangeLow.value);
              const label = labelPosition(x, paddingLeft, paddingRight, width);
              const labelY = clamp(y + 18, chartTop + 12, priceBottom - 8);

              return (
                <>
                  <circle cx={x} cy={y} r="3.5" className="fill-emerald-600" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={labelY}
                    className="stroke-emerald-400"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={labelY + 10}
                    textAnchor={label.anchor}
                    className="fill-emerald-600 text-[11px] font-semibold"
                  >
                    最低 {formatPrice(rangeLow.value)}
                  </text>
                </>
              );
            })()}
          </g>
        ) : null}

        {visibleChartSignals.map((signal) => {
          const x = getX(signal.index);
          const y = clamp(
            getPriceY(signal.price) + (signal.direction === "bearish" ? 18 : -18),
            chartTop + 16,
            priceBottom - 8
          );
          const labelWidth = Math.max(signal.label.length * 12 + 12, 54);
          const label = labelPosition(x, paddingLeft, paddingRight, width);
          const labelX = label.anchor === "end" ? x - 10 : x + 10;
          const rectX = label.anchor === "end" ? labelX - labelWidth : labelX;
          const tone =
            signal.direction === "bullish"
              ? "fill-red-600"
              : signal.direction === "bearish"
                ? "fill-emerald-600"
                : "fill-violet-600";

          return (
            <g key={signal.key}>
              <line
                x1={x}
                x2={labelX}
                y1={getPriceY(signal.price)}
                y2={y}
                className="stroke-slate-300"
                strokeDasharray="3 3"
              />
              <circle cx={x} cy={getPriceY(signal.price)} r="3" className={tone} />
              <rect
                x={rectX}
                y={y - 10}
                width={labelWidth}
                height="18"
                rx="2"
                className={tone}
              />
              <text
                x={label.anchor === "end" ? labelX - 6 : labelX + 6}
                y={y + 3}
                textAnchor={label.anchor}
                className="fill-white text-[10px] font-semibold"
              >
                {signal.label}
              </text>
              <title>
                {visibleData[signal.index]?.time} {signal.label}
              </title>
            </g>
          );
        })}

        {panels.map((panel) => {
          const panelBottom = panel.top + panel.height;

          return (
            <g key={panel.key}>
              <line
                x1={paddingLeft}
                x2={width - paddingRight}
                y1={panel.top}
                y2={panel.top}
                className="stroke-slate-200"
              />
              <text
                x={paddingLeft - 10}
                y={panel.top + 12}
                textAnchor="end"
                className="fill-slate-500 text-[11px]"
              >
                {panel.label}
              </text>

              {panel.key === "volume" ? (
                <>
                  {visibleData.map((point, index) => {
                    const open = point.open ?? point.close;
                    const close = point.close ?? point.open;
                    const volume = point.volume ?? 0;
                    const x = getX(index);
                    const isUp = validNumber(close) && validNumber(open) ? close >= open : true;
                    const y = getVolumeY(panel, volume);
                    const barHeight = panelBottom - y;

                    return (
                      <rect
                        key={`${point.time}-volume`}
                        x={x - candleWidth / 2}
                        y={y}
                        width={candleWidth}
                        height={Math.max(barHeight, 1)}
                        className={isUp ? "fill-red-200" : "fill-emerald-200"}
                      />
                    );
                  })}
                  <text
                    x={paddingLeft - 10}
                    y={panelBottom}
                    textAnchor="end"
                    className="fill-slate-400 text-[10px]"
                  >
                    0
                  </text>
                </>
              ) : null}

              {panel.key === "rsi" ? (
                <>
                  {[30, 50, 70].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 50 ? "stroke-slate-100" : "stroke-slate-200"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.rsi14, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-fuchsia-600"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "macd" ? (
                <>
                  <line
                    x1={paddingLeft}
                    x2={width - paddingRight}
                    y1={getPanelY(panel, 0, -macdAbsMax, macdAbsMax)}
                    y2={getPanelY(panel, 0, -macdAbsMax, macdAbsMax)}
                    className="stroke-slate-200"
                  />
                  {visibleData.map((point, index) => {
                    if (!validNumber(point.macdHistogram)) return null;

                    const x = getX(index);
                    const zeroY = getPanelY(panel, 0, -macdAbsMax, macdAbsMax);
                    const valueY = getPanelY(panel, point.macdHistogram, -macdAbsMax, macdAbsMax);

                    return (
                      <rect
                        key={`${point.time}-macd-histogram`}
                        x={x - candleWidth / 2}
                        y={Math.min(zeroY, valueY)}
                        width={candleWidth}
                        height={Math.max(Math.abs(zeroY - valueY), 1)}
                        className={point.macdHistogram >= 0 ? "fill-red-200" : "fill-emerald-200"}
                      />
                    );
                  })}
                  <path
                    d={buildLinePath(visibleData, (point) => point.macd, getX, (value) =>
                      getPanelY(panel, value, -macdAbsMax, macdAbsMax)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-blue-600"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.macdSignal, getX, (value) =>
                      getPanelY(panel, value, -macdAbsMax, macdAbsMax)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-amber-500"
                  />
                </>
              ) : null}

              {panel.key === "kd" ? (
                <>
                  {[20, 50, 80].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 50 ? "stroke-slate-100" : "stroke-slate-200"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.k, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-blue-600"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.d, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-amber-500"
                  />
                </>
              ) : null}

              {panel.key === "atr" ? (
                <>
                  <text
                    x={paddingLeft - 10}
                    y={panel.top + panel.height}
                    textAnchor="end"
                    className="fill-slate-400 text-[10px]"
                  >
                    0
                  </text>
                  <path
                    d={buildLinePath(visibleData, (point) => point.atr14, getX, (value) =>
                      getPanelY(panel, value, atrRange.min, atrRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-orange-500"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "adx" ? (
                <>
                  {[20, 25, 50].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 25 ? "stroke-slate-300" : "stroke-slate-100"}
                      strokeDasharray={value === 25 ? "4 4" : undefined}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.adx14, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-violet-600"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.plusDi14, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.5"
                    className="stroke-red-500"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.minusDi14, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.5"
                    className="stroke-emerald-500"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "obv" ? (
                <>
                  {obvRange.min < 0 && obvRange.max > 0 ? (
                    <line
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, 0, obvRange.min, obvRange.max)}
                      y2={getPanelY(panel, 0, obvRange.min, obvRange.max)}
                      className="stroke-slate-200"
                    />
                  ) : null}
                  <path
                    d={buildLinePath(visibleData, (point) => point.obv, getX, (value) =>
                      getPanelY(panel, value, obvRange.min, obvRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-slate-700"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.obvMa10, getX, (value) =>
                      getPanelY(panel, value, obvRange.min, obvRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.5"
                    className="stroke-amber-500"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "mfi" ? (
                <>
                  {[20, 50, 80].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 50 ? "stroke-slate-100" : "stroke-slate-200"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.mfi14, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-teal-600"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "cci" ? (
                <>
                  {[-100, 0, 100].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, cciRange.min, cciRange.max)}
                      y2={getPanelY(panel, value, cciRange.min, cciRange.max)}
                      className={value === 0 ? "stroke-slate-200" : "stroke-slate-300"}
                      strokeDasharray={value === 0 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.cci20, getX, (value) =>
                      getPanelY(panel, value, cciRange.min, cciRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-indigo-600"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "williamsR" ? (
                <>
                  {[-80, -50, -20].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, -100, 0)}
                      y2={getPanelY(panel, value, -100, 0)}
                      className={value === -50 ? "stroke-slate-100" : "stroke-slate-200"}
                      strokeDasharray={value === -50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.williamsR14, getX, (value) =>
                      getPanelY(panel, value, -100, 0)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-pink-600"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "roc" ? (
                <>
                  <line
                    x1={paddingLeft}
                    x2={width - paddingRight}
                    y1={getPanelY(panel, 0, rocRange.min, rocRange.max)}
                    y2={getPanelY(panel, 0, rocRange.min, rocRange.max)}
                    className="stroke-slate-200"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.roc12, getX, (value) =>
                      getPanelY(panel, value, rocRange.min, rocRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-cyan-700"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "stochRsi" ? (
                <>
                  {[20, 50, 80].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 50 ? "stroke-slate-100" : "stroke-slate-200"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.stochRsiK, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-blue-600"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.stochRsiD, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-amber-500"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}
            </g>
          );
        })}

        {hoverX !== null ? (
          <line
            x1={hoverX}
            x2={hoverX}
            y1={chartTop}
            y2={plotBottom}
            className="stroke-slate-400"
            strokeDasharray="4 4"
          />
        ) : null}

        <text x={paddingLeft} y={labelY} textAnchor="start" className="fill-slate-500 text-[11px]">
          {visibleData[0]?.time ?? "-"}
        </text>
        <text
          x={width - paddingRight}
          y={labelY}
          textAnchor="end"
          className="fill-slate-500 text-[11px]"
        >
          {visibleData[visibleData.length - 1]?.time ?? "-"}
        </text>

        <g transform={`translate(${paddingLeft}, 18)`}>
          {indicators.ma ? (
            <>
              <circle cx="0" cy="0" r="4" className="fill-blue-600" />
              <text x="10" y="4" className="fill-slate-600 text-[11px]">
                MA{params.maShort}
              </text>
              <circle cx="58" cy="0" r="4" className="fill-amber-500" />
              <text x="68" y="4" className="fill-slate-600 text-[11px]">
                MA{params.maMiddle}
              </text>
              <circle cx="126" cy="0" r="4" className="fill-purple-500" />
              <text x="136" y="4" className="fill-slate-600 text-[11px]">
                MA{params.maLong}
              </text>
            </>
          ) : null}
          {indicators.bollinger ? (
            <>
              <rect x={190} y={-4} width={8} height={8} className="fill-sky-400" />
              <text x="204" y="4" className="fill-slate-600 text-[11px]">
                BOLL
              </text>
            </>
          ) : null}
          {indicators.ema ? (
            <>
              <circle cx="248" cy="0" r="4" className="fill-cyan-600" />
              <text x="258" y="4" className="fill-slate-600 text-[11px]">
                EMA{params.emaFast}
              </text>
              <circle cx="318" cy="0" r="4" className="fill-rose-500" />
              <text x="328" y="4" className="fill-slate-600 text-[11px]">
                EMA{params.emaSlow}
              </text>
            </>
          ) : null}
          {indicators.vwap ? (
            <>
              <circle cx="388" cy="0" r="4" className="fill-slate-700" />
              <text x="398" y="4" className="fill-slate-600 text-[11px]">
                VWAP
              </text>
            </>
          ) : null}
          {indicators.psar ? (
            <>
              <circle cx="452" cy="0" r="4" className="fill-violet-600" />
              <text x="462" y="4" className="fill-slate-600 text-[11px]">
                SAR
              </text>
            </>
          ) : null}
          {indicators.donchian ? (
            <>
              <rect x={506} y={-4} width={8} height={8} className="fill-lime-500" />
              <text x="520" y="4" className="fill-slate-600 text-[11px]">
                DONCH
              </text>
            </>
          ) : null}
        </g>

        <rect
          x={paddingLeft}
          y={chartTop}
          width={usableWidth}
          height={plotBottom - chartTop}
          fill="transparent"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIndex(null)}
          onWheel={handleWheel}
        />
      </svg>
    </div>
  );
}

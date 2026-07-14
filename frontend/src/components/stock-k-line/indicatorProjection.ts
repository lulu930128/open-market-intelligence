import type { IndicatorParameters } from "@/components/stock-k-line/indicatorCatalog";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";

export type MergedPoint = ChartPoint & {
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
  relativeStrength: number | null;
  beta: number | null;
  correlation: number | null;
};

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

export function validNumber(value: number | null | undefined): value is number {
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
    if (validNumber(point.close)) {
      benchmarkCloseByDate.set(point.time.slice(0, 10), point.close);
    }
  });

  const stockReturns: Array<number | null> = points.map(() => null);
  const benchmarkReturns: Array<number | null> = points.map(() => null);

  points.forEach((point, index) => {
    const previousPoint = points[index - 1];
    const previousClose = previousPoint?.close;
    const benchmarkClose = benchmarkCloseByDate.get(point.time.slice(0, 10));
    const previousBenchmarkClose = previousPoint
      ? benchmarkCloseByDate.get(previousPoint.time.slice(0, 10))
      : undefined;

    if (validNumber(point.close) && validNumber(previousClose) && previousClose !== 0) {
      stockReturns[index] = point.close / previousClose - 1;
    }

    if (
      validNumber(benchmarkClose) &&
      validNumber(previousBenchmarkClose) &&
      previousBenchmarkClose !== 0
    ) {
      benchmarkReturns[index] = benchmarkClose / previousBenchmarkClose - 1;
    }
  });

  points.forEach((point, index) => {
    const baseIndex = index - params.relativeStrengthLookback;
    const basePoint = points[baseIndex];
    const baseClose = basePoint?.close;
    const benchmarkClose = benchmarkCloseByDate.get(point.time.slice(0, 10));
    const baseBenchmarkClose = basePoint
      ? benchmarkCloseByDate.get(basePoint.time.slice(0, 10))
      : undefined;

    if (
      baseIndex >= 0 &&
      validNumber(point.close) &&
      validNumber(baseClose) &&
      baseClose !== 0 &&
      validNumber(benchmarkClose) &&
      validNumber(baseBenchmarkClose) &&
      baseBenchmarkClose !== 0
    ) {
      const stockReturn = point.close / baseClose - 1;
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

      if (validNumber(stockReturn) && validNumber(benchmarkReturn)) {
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
      denominator > 0 ? clamp(covariance / denominator, -1, 1) : null;
  });

  return { relativeStrength, beta, correlation };
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

type ProjectStockKLineDataInput = {
  chartData: ChartPoint[];
  indicatorData: StockIndicatorPoint[];
  benchmarkData: ChartPoint[];
  params: IndicatorParameters;
  latestPreviousClose: number | null;
};

export function projectStockKLineData({
  chartData,
  indicatorData,
  benchmarkData,
  params,
  latestPreviousClose,
}: ProjectStockKLineDataInput): MergedPoint[] {
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
  const relativeMetrics = calculateRelativeMetrics(chartData, benchmarkData, params);

  return chartData.map((point, index) => {
    const indicator = indicatorByTime.get(point.time);
    const previousClose =
      index === chartData.length - 1 && validNumber(latestPreviousClose)
        ? latestPreviousClose
        : chartData[index - 1]?.close;
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
      relativeStrength: relativeMetrics.relativeStrength[index],
      beta: relativeMetrics.beta[index],
      correlation: relativeMetrics.correlation[index],
    };
  });
}

type ChartSignal = {
  key: string;
  index: number;
  label: string;
  direction: "bullish" | "bearish" | "neutral";
  price: number;
};

export function buildChartSignals(data: MergedPoint[]) {
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

import type { IndicatorParameters } from "@/components/StockKLineChart";
import type { ChartPoint } from "@/types/market";
import { finiteNumber } from "@/components/chart/lightweight-chart/drawingModel";

export function average(values: Array<number | null | undefined>) {
  const valid = values.filter(finiteNumber);

  if (valid.length === 0) return null;

  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

export function movingAverage(values: Array<number | null | undefined>, index: number, windowSize: number) {
  if (index + 1 < windowSize) return null;

  const windowValues = values.slice(index + 1 - windowSize, index + 1);

  if (windowValues.some((value) => !finiteNumber(value))) return null;

  return average(windowValues);
}

export function standardDeviation(
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

export function weightedMovingAverage(
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

export function calculateWma(values: Array<number | null | undefined>, period: number) {
  return values.map((_, index) => weightedMovingAverage(values, index, period));
}

export function calculateHma(values: Array<number | null | undefined>, period: number) {
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

export function calculateVwma(points: ChartPoint[], period: number) {
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

export function calculateEma(values: Array<number | null | undefined>, period: number) {
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

export function calculateRsi(closes: Array<number | null | undefined>, period = 14) {
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

export function calculateMacd(
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

export function calculateKd(points: ChartPoint[], period = 9) {
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

export function typicalPrice(point: ChartPoint) {
  if (!finiteNumber(point.high) || !finiteNumber(point.low) || !finiteNumber(point.close)) {
    return null;
  }

  return (point.high + point.low + point.close) / 3;
}

export function calculateVwap(points: ChartPoint[]) {
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

export function calculateParabolicSar(points: ChartPoint[], step = 0.02, maxStep = 0.2) {
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

export function calculateDonchian(points: ChartPoint[], period = 20) {
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

export function calculateTrueRanges(points: ChartPoint[]) {
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

export function calculateAtr(points: ChartPoint[], period = 14) {
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

export function calculateChoppiness(points: ChartPoint[], period = 14) {
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

export function calculateDmi(points: ChartPoint[], period = 14) {
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

export function calculateObv(points: ChartPoint[]) {
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

export function calculateMfi(points: ChartPoint[], period = 14) {
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

export function calculateChaikinMoneyFlow(points: ChartPoint[], period = 20) {
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

export function calculateAccumulationDistribution(points: ChartPoint[]) {
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

export function calculatePriceVolumeTrend(points: ChartPoint[]) {
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

export function calculateCci(points: ChartPoint[], period = 20) {
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

export function calculateWilliamsR(points: ChartPoint[], period = 14) {
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

export function calculateRoc(closes: Array<number | null | undefined>, period = 12) {
  return closes.map((close, index) => {
    const previous = closes[index - period];

    if (!finiteNumber(close) || !finiteNumber(previous) || previous === 0) return null;

    return ((close - previous) / previous) * 100;
  });
}

export function calculateMomentum(closes: Array<number | null | undefined>, period = 10) {
  return closes.map((close, index) => {
    const previous = closes[index - period];

    if (!finiteNumber(close) || !finiteNumber(previous)) return null;

    return close - previous;
  });
}

export function calculateTsi(
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

export function calculateAwesomeOscillator(points: ChartPoint[], fastPeriod = 5, slowPeriod = 34) {
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

export function calculateUltimateOscillator(points: ChartPoint[], shortPeriod = 7, middlePeriod = 14, longPeriod = 28) {
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

export function calculateStochRsi(
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

export function midpointOfRange(points: ChartPoint[], index: number, period: number) {
  if (index + 1 < period) return null;

  const slice = points.slice(index + 1 - period, index + 1);
  const highs = slice.map((point) => point.high).filter(finiteNumber);
  const lows = slice.map((point) => point.low).filter(finiteNumber);

  if (highs.length < period || lows.length < period) return null;

  return (Math.max(...highs) + Math.min(...lows)) / 2;
}

export function calculateIchimoku(points: ChartPoint[], params: IndicatorParameters) {
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

export function calculateKeltner(points: ChartPoint[], params: IndicatorParameters) {
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

export function calculateSupertrend(points: ChartPoint[], period = 10, multiplier = 3) {
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

export function calculateAroon(points: ChartPoint[], period = 25) {
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

export function calculateTrix(closes: Array<number | null | undefined>, period = 15, signalPeriod = 9) {
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

export function calculatePivots(points: ChartPoint[], lookback = 1) {
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

export function calculateSupportResistance(points: ChartPoint[], period = 20) {
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

export function calculateGaps(points: ChartPoint[], minPct = 0.5) {
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

export function calculateRelativeMetrics(
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

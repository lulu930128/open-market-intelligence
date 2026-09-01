import type { IndicatorParameters, IndicatorSettings } from "@/components/StockKLineChart";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";
import {
  backendIndicatorParametersMatch,
  backendIndicatorValue,
  backendIndicatorWindowExists,
} from "@/components/stock-k-line/indicatorAuthority";
import {
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Logical,
  type LogicalRange,
  type Time,
} from "lightweight-charts";
import {
  chartTime,
  defaultLightweightIndicators,
  downColor,
  finiteNumber,
  upColor,
  type BuiltSeriesData,
  type ChartTimeMode,
  type LightweightKLineChartProps,
  type LineSeriesData,
  type PlotLineData,
} from "@/components/chart/lightweight-chart/drawingModel";
import { omiChartColors } from "@/lib/themeColors";
import {
  movingAverage,
  standardDeviation,
  calculateWma,
  calculateHma,
  calculateVwma,
  calculateEma,
  calculateRsi,
  calculateMacd,
  calculateKd,
  calculateVwap,
  calculateParabolicSar,
  calculateDonchian,
  calculateAtr,
  calculateChoppiness,
  calculateDmi,
  calculateObv,
  calculateMfi,
  calculateChaikinMoneyFlow,
  calculateAccumulationDistribution,
  calculatePriceVolumeTrend,
  calculateCci,
  calculateWilliamsR,
  calculateRoc,
  calculateMomentum,
  calculateTsi,
  calculateAwesomeOscillator,
  calculateUltimateOscillator,
  calculateStochRsi,
  calculateIchimoku,
  calculateKeltner,
  calculateSupertrend,
  calculateAroon,
  calculateTrix,
  calculatePivots,
  calculateSupportResistance,
  calculateGaps,
  calculateRelativeMetrics,
} from "@/components/chart/lightweight-chart/indicatorMath";

export function formatPrice(
  value: number | null | undefined,
  maximumFractionDigits?: number
) {
  if (!finiteNumber(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: maximumFractionDigits ?? (value >= 1000 ? 2 : 4),
  });
}

export function createLineSeriesData(): LineSeriesData {
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

export function pushLine(target: LineData<Time>[], time: Time, value: number | null | undefined) {
  if (!finiteNumber(value)) return;

  target.push({ time, value });
}

export function pushSupertrendLine(
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

function backendIndicatorTimeKey(value: string, timeMode: ChartTimeMode) {
  return timeMode === "intraday" ? value : value.slice(0, 10);
}

function buildBackendSeriesData(
  chartData: ChartPoint[],
  indicatorData: StockIndicatorPoint[],
  volumeValueKey: LightweightKLineChartProps["volumeValueKey"],
  timeMode: ChartTimeMode,
  params: IndicatorParameters
): BuiltSeriesData {
  const indicatorByTime = new Map(
    indicatorData.map((point) => [backendIndicatorTimeKey(point.time, timeMode), point])
  );
  const candles: CandlestickData<Time>[] = [];
  const line: LineData<Time>[] = [];
  const volumes: HistogramData<Time>[] = [];
  const macdHistogram: HistogramData<Time>[] = [];
  const lines = createLineSeriesData();

  chartData.forEach((point) => {
    if (
      !finiteNumber(point.open) ||
      !finiteNumber(point.high) ||
      !finiteNumber(point.low) ||
      !finiteNumber(point.close)
    ) {
      return;
    }
    const time = chartTime(point.time, timeMode);
    const color = point.close >= point.open ? upColor : downColor;
    const indicator = indicatorByTime.get(backendIndicatorTimeKey(point.time, timeMode));
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
    line.push({ time, value: point.close, color });
    const volumeValue = volumeValueKey === "trade_value" ? point.trade_value : point.volume;
    if (finiteNumber(volumeValue)) {
      volumes.push({
        time,
        value: volumeValue,
        color:
          point.close >= point.open
            ? omiChartColors.marketUpVolume
            : omiChartColors.marketDownVolume,
      });
    }

    if (backendIndicatorWindowExists(indicator, "ma_windows", params.maShort)) {
      pushLine(lines.maShort, time, backendIndicatorValue(indicator?.ma, `ma${params.maShort}`));
    }
    if (backendIndicatorWindowExists(indicator, "ma_windows", params.maMiddle)) {
      pushLine(lines.maMiddle, time, backendIndicatorValue(indicator?.ma, `ma${params.maMiddle}`));
    }
    if (backendIndicatorWindowExists(indicator, "ma_windows", params.maLong)) {
      pushLine(lines.maLong, time, backendIndicatorValue(indicator?.ma, `ma${params.maLong}`));
    }
    if (
      backendIndicatorParametersMatch(indicator, {
        ema_fast: params.emaFast,
        ema_slow: params.emaSlow,
      })
    ) {
      pushLine(lines.emaFast, time, backendIndicatorValue(indicator?.ema, `ema${params.emaFast}`));
      pushLine(lines.emaSlow, time, backendIndicatorValue(indicator?.ema, `ema${params.emaSlow}`));
    }
    if (backendIndicatorParametersMatch(indicator, { rsi_period: params.rsiPeriod })) {
      pushLine(lines.rsi, time, backendIndicatorValue(indicator?.rsi, `rsi${params.rsiPeriod}`));
    }
    if (
      backendIndicatorParametersMatch(indicator, {
        macd_fast: params.macdFast,
        macd_slow: params.macdSlow,
        macd_signal: params.macdSignal,
      })
    ) {
      pushLine(lines.macd, time, backendIndicatorValue(indicator?.macd, "macd"));
      pushLine(lines.macdSignal, time, backendIndicatorValue(indicator?.macd, "signal"));
      const histogram = backendIndicatorValue(indicator?.macd, "histogram");
      if (finiteNumber(histogram)) {
        macdHistogram.push({
          time,
          value: histogram,
          color:
            histogram >= 0
              ? omiChartColors.marketUpHistogram
              : omiChartColors.marketDownHistogram,
        });
      }
    }
    if (backendIndicatorParametersMatch(indicator, { kd_period: params.kdPeriod })) {
      pushLine(lines.kdK, time, backendIndicatorValue(indicator?.kd, `k${params.kdPeriod}`));
      pushLine(lines.kdD, time, backendIndicatorValue(indicator?.kd, `d${params.kdPeriod}`));
    }
    if (backendIndicatorParametersMatch(indicator, { atr_period: params.atrPeriod })) {
      pushLine(lines.atr, time, backendIndicatorValue(indicator?.atr, `atr${params.atrPeriod}`));
    }
    if (backendIndicatorParametersMatch(indicator, { adx_period: params.adxPeriod })) {
      pushLine(lines.adx, time, backendIndicatorValue(indicator?.adx, `adx${params.adxPeriod}`));
      pushLine(lines.plusDi, time, backendIndicatorValue(indicator?.adx, `plus_di${params.adxPeriod}`));
      pushLine(lines.minusDi, time, backendIndicatorValue(indicator?.adx, `minus_di${params.adxPeriod}`));
    }
    if (backendIndicatorParametersMatch(indicator, { mfi_period: params.mfiPeriod })) {
      pushLine(lines.mfi, time, backendIndicatorValue(indicator?.mfi, `mfi${params.mfiPeriod}`));
    }
    if (backendIndicatorParametersMatch(indicator, { roc_period: params.rocPeriod })) {
      pushLine(lines.roc, time, backendIndicatorValue(indicator?.roc, `roc${params.rocPeriod}`));
    }
    if (
      backendIndicatorParametersMatch(indicator, {
        donchian_period: params.donchianPeriod,
      })
    ) {
      pushLine(lines.donchianUpper, time, backendIndicatorValue(indicator?.donchian, `upper${params.donchianPeriod}`));
      pushLine(lines.donchianLower, time, backendIndicatorValue(indicator?.donchian, `lower${params.donchianPeriod}`));
    }
    if (
      backendIndicatorParametersMatch(indicator, {
        bollinger_period: params.bollingerPeriod,
        bollinger_std_dev: params.bollingerStdDev,
      })
    ) {
      pushLine(lines.bollingerUpper, time, backendIndicatorValue(indicator?.bollinger, `upper${params.bollingerPeriod}`));
      pushLine(lines.bollingerMiddle, time, backendIndicatorValue(indicator?.bollinger, `middle${params.bollingerPeriod}`));
      pushLine(lines.bollingerLower, time, backendIndicatorValue(indicator?.bollinger, `lower${params.bollingerPeriod}`));
    }
    if (
      backendIndicatorParametersMatch(indicator, {
        support_resistance_period: params.supportResistanceLookback,
      })
    ) {
      pushLine(lines.support, time, backendIndicatorValue(indicator?.support_resistance, `support${params.supportResistanceLookback}`));
      pushLine(lines.resistance, time, backendIndicatorValue(indicator?.support_resistance, `resistance${params.supportResistanceLookback}`));
    }
  });

  return { candles, line, volumes, macdHistogram, lines };
}

export function buildSeriesData(
  chartData: ChartPoint[],
  indicatorData: StockIndicatorPoint[],
  volumeValueKey: LightweightKLineChartProps["volumeValueKey"],
  timeMode: ChartTimeMode,
  params: IndicatorParameters,
  benchmarkData?: ChartPoint[],
  allowCanonicalFallback = true
): BuiltSeriesData {
  if (!allowCanonicalFallback) {
    return buildBackendSeriesData(
      chartData,
      indicatorData,
      volumeValueKey,
      timeMode,
      params
    );
  }
  const indicatorByTime = new Map(
    indicatorData.map((point) => [backendIndicatorTimeKey(point.time, timeMode), point])
  );
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

    const timeKey = backendIndicatorTimeKey(point.time, timeMode);
    const presentationFallback = (value: number | null) =>
      allowCanonicalFallback ? value : null;
    const time = chartTime(point.time, timeMode);
    const color = point.close >= point.open ? upColor : downColor;
    const indicator = indicatorByTime.get(timeKey);
    const backendEma = backendIndicatorParametersMatch(indicator, {
      ema_fast: params.emaFast,
      ema_slow: params.emaSlow,
    });
    const backendMacd = backendIndicatorParametersMatch(indicator, {
      macd_fast: params.macdFast,
      macd_slow: params.macdSlow,
      macd_signal: params.macdSignal,
    });
    const backendRsi = backendIndicatorParametersMatch(indicator, {
      rsi_period: params.rsiPeriod,
    });
    const backendKd = backendIndicatorParametersMatch(indicator, {
      kd_period: params.kdPeriod,
    });
    const backendAtr = backendIndicatorParametersMatch(indicator, {
      atr_period: params.atrPeriod,
    });
    const backendAdx = backendIndicatorParametersMatch(indicator, {
      adx_period: params.adxPeriod,
    });
    const backendMfi = backendIndicatorParametersMatch(indicator, {
      mfi_period: params.mfiPeriod,
    });
    const backendRoc = backendIndicatorParametersMatch(indicator, {
      roc_period: params.rocPeriod,
    });
    const backendDonchian = backendIndicatorParametersMatch(indicator, {
      donchian_period: params.donchianPeriod,
    });
    const backendBollinger = backendIndicatorParametersMatch(indicator, {
      bollinger_period: params.bollingerPeriod,
      bollinger_std_dev: params.bollingerStdDev,
    });
    const backendSupportResistance = backendIndicatorParametersMatch(indicator, {
      support_resistance_period: params.supportResistanceLookback,
    });
    const maShort = backendIndicatorWindowExists(indicator, "ma_windows", params.maShort)
      ? backendIndicatorValue(indicator?.ma, `ma${params.maShort}`)
      : presentationFallback(movingAverage(closes, index, params.maShort));
    const maMiddle = backendIndicatorWindowExists(indicator, "ma_windows", params.maMiddle)
      ? backendIndicatorValue(indicator?.ma, `ma${params.maMiddle}`)
      : presentationFallback(movingAverage(closes, index, params.maMiddle));
    const maLong = backendIndicatorWindowExists(indicator, "ma_windows", params.maLong)
      ? backendIndicatorValue(indicator?.ma, `ma${params.maLong}`)
      : presentationFallback(movingAverage(closes, index, params.maLong));
    const bbMiddle = backendBollinger
      ? backendIndicatorValue(indicator?.bollinger, `middle${params.bollingerPeriod}`)
      : presentationFallback(movingAverage(closes, index, params.bollingerPeriod));
    const bbStd = standardDeviation(closes, index, params.bollingerPeriod);
    const bbWidthMiddle = movingAverage(closes, index, params.bbWidthPeriod);
    const bbWidthStd = standardDeviation(closes, index, params.bbWidthPeriod);
    const macdHistogramValue = backendMacd
      ? backendIndicatorValue(indicator?.macd, "histogram")
      : presentationFallback(macd.histogram[index]);

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
        color: point.close >= point.open ? omiChartColors.marketUpVolume : omiChartColors.marketDownVolume,
      });
    }

    if (finiteNumber(macdHistogramValue)) {
      macdHistogram.push({
        time,
        value: macdHistogramValue,
        color: macdHistogramValue >= 0 ? omiChartColors.marketUpHistogram : omiChartColors.marketDownHistogram,
      });
    }

    pushLine(lines.maShort, time, maShort);
    pushLine(lines.maMiddle, time, maMiddle);
    pushLine(lines.maLong, time, maLong);
    pushLine(
      lines.emaFast,
      time,
      backendEma
        ? backendIndicatorValue(indicator?.ema, `ema${params.emaFast}`)
        : presentationFallback(emaFast[index])
    );
    pushLine(
      lines.emaSlow,
      time,
      backendEma
        ? backendIndicatorValue(indicator?.ema, `ema${params.emaSlow}`)
        : presentationFallback(emaSlow[index])
    );
    pushLine(lines.wma, time, wma[index]);
    pushLine(lines.hma, time, hma[index]);
    pushLine(lines.vwma, time, vwma[index]);
    pushLine(lines.vwap, time, vwap[index]);
    pushLine(lines.psar, time, psar[index]);
    pushLine(
      lines.donchianUpper,
      time,
      backendDonchian
        ? backendIndicatorValue(indicator?.donchian, `upper${params.donchianPeriod}`)
        : presentationFallback(donchian[index].upper)
    );
    pushLine(
      lines.donchianLower,
      time,
      backendDonchian
        ? backendIndicatorValue(indicator?.donchian, `lower${params.donchianPeriod}`)
        : presentationFallback(donchian[index].lower)
    );
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
    pushLine(
      lines.rsi,
      time,
      backendRsi
        ? backendIndicatorValue(indicator?.rsi, `rsi${params.rsiPeriod}`)
        : presentationFallback(rsi[index])
    );
    pushLine(
      lines.macd,
      time,
      backendMacd
        ? backendIndicatorValue(indicator?.macd, "macd")
        : presentationFallback(macd.macd[index])
    );
    pushLine(
      lines.macdSignal,
      time,
      backendMacd
        ? backendIndicatorValue(indicator?.macd, "signal")
        : presentationFallback(macd.signal[index])
    );
    pushLine(
      lines.kdK,
      time,
      backendKd
        ? backendIndicatorValue(indicator?.kd, `k${params.kdPeriod}`)
        : presentationFallback(kd[index].k)
    );
    pushLine(
      lines.kdD,
      time,
      backendKd
        ? backendIndicatorValue(indicator?.kd, `d${params.kdPeriod}`)
        : presentationFallback(kd[index].d)
    );
    pushLine(
      lines.atr,
      time,
      backendAtr
        ? backendIndicatorValue(indicator?.atr, `atr${params.atrPeriod}`)
        : presentationFallback(atr[index])
    );
    pushLine(
      lines.adx,
      time,
      backendAdx
        ? backendIndicatorValue(indicator?.adx, `adx${params.adxPeriod}`)
        : presentationFallback(dmi[index].adx)
    );
    pushLine(
      lines.plusDi,
      time,
      backendAdx
        ? backendIndicatorValue(indicator?.adx, `plus_di${params.adxPeriod}`)
        : presentationFallback(dmi[index].plusDi)
    );
    pushLine(
      lines.minusDi,
      time,
      backendAdx
        ? backendIndicatorValue(indicator?.adx, `minus_di${params.adxPeriod}`)
        : presentationFallback(dmi[index].minusDi)
    );
    pushLine(lines.aroonUp, time, aroon[index].up);
    pushLine(lines.aroonDown, time, aroon[index].down);
    pushLine(lines.obv, time, obv[index]);
    pushLine(lines.obvMa, time, obvMa[index]);
    pushLine(
      lines.mfi,
      time,
      backendMfi
        ? backendIndicatorValue(indicator?.mfi, `mfi${params.mfiPeriod}`)
        : presentationFallback(mfi[index])
    );
    pushLine(lines.cci, time, cci[index]);
    pushLine(lines.williamsR, time, williamsR[index]);
    pushLine(
      lines.roc,
      time,
      backendRoc
        ? backendIndicatorValue(indicator?.roc, `roc${params.rocPeriod}`)
        : presentationFallback(roc[index])
    );
    pushLine(lines.stochRsiK, time, stochRsi.k[index]);
    pushLine(lines.stochRsiD, time, stochRsi.d[index]);
    pushLine(lines.trix, time, trix.trix[index]);
    pushLine(lines.trixSignal, time, trix.signal[index]);

    if (backendBollinger) {
      pushLine(
        lines.bollingerUpper,
        time,
        backendIndicatorValue(indicator?.bollinger, `upper${params.bollingerPeriod}`)
      );
      pushLine(lines.bollingerMiddle, time, bbMiddle);
      pushLine(
        lines.bollingerLower,
        time,
        backendIndicatorValue(indicator?.bollinger, `lower${params.bollingerPeriod}`)
      );
    } else if (allowCanonicalFallback && bbMiddle !== null && bbStd !== null) {
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
    pushLine(
      lines.support,
      time,
      backendSupportResistance
        ? backendIndicatorValue(
            indicator?.support_resistance,
            `support${params.supportResistanceLookback}`
          )
        : presentationFallback(supportResistance[index].support)
    );
    pushLine(
      lines.resistance,
      time,
      backendSupportResistance
        ? backendIndicatorValue(
            indicator?.support_resistance,
            `resistance${params.supportResistanceLookback}`
          )
        : presentationFallback(supportResistance[index].resistance)
    );
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

export function mergeIndicators(indicators: IndicatorSettings | undefined, showMovingAverages: boolean) {
  return {
    ...defaultLightweightIndicators,
    ...(indicators ?? {}),
    ma: showMovingAverages && (indicators?.ma ?? defaultLightweightIndicators.ma),
  };
}

export function chartRightPaddingBars(timeMode: ChartTimeMode) {
  return timeMode === "intraday" ? 34 : 10;
}

export function chartKeyboardBoundaryPaddingBars(timeMode: ChartTimeMode) {
  return timeMode === "intraday" ? 96 : 30;
}

export function logicalRange(from: number, to: number): LogicalRange {
  return {
    from: from as Logical,
    to: to as Logical,
  };
}

export function buildDefaultVisibleLogicalRange(
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

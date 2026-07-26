import type { TranslationFunction } from "@/i18n";

export type IndicatorSettings = {
  signals: boolean;
  ma: boolean;
  ema: boolean;
  wma: boolean;
  hma: boolean;
  vwma: boolean;
  bollinger: boolean;
  bbWidth: boolean;
  stdDev: boolean;
  choppiness: boolean;
  vwap: boolean;
  psar: boolean;
  donchian: boolean;
  ichimoku: boolean;
  supertrend: boolean;
  keltner: boolean;
  volume: boolean;
  rsi: boolean;
  macd: boolean;
  kd: boolean;
  momentum: boolean;
  tsi: boolean;
  awesomeOscillator: boolean;
  ultimateOscillator: boolean;
  atr: boolean;
  adx: boolean;
  aroon: boolean;
  obv: boolean;
  mfi: boolean;
  cmf: boolean;
  adLine: boolean;
  pvt: boolean;
  cci: boolean;
  williamsR: boolean;
  roc: boolean;
  stochRsi: boolean;
  trix: boolean;
  volumeProfile: boolean;
  pivotPoints: boolean;
  supportResistance: boolean;
  gap: boolean;
  divergence: boolean;
  candlestickPatterns: boolean;
  relativeStrength: boolean;
  beta: boolean;
  correlation: boolean;
};

export type IndicatorKey = keyof IndicatorSettings;

export type IndicatorCategoryKey =
  | "trend"
  | "volatility"
  | "momentum"
  | "volume"
  | "structure"
  | "relative"
  | "signals";

export type IndicatorPlotType = "overlay" | "pane" | "signal" | "context";

export type AvailableIndicatorOption = {
  status: "available";
  key: IndicatorKey;
  label: string;
  description: string;
  category: IndicatorCategoryKey;
  plot: IndicatorPlotType;
};

export type PlannedIndicatorOption = {
  status: "planned";
  key: string;
  label: string;
  description: string;
  category: IndicatorCategoryKey;
  plot: IndicatorPlotType;
};

export type ChartIndicatorOption = AvailableIndicatorOption | PlannedIndicatorOption;

export type IndicatorCategoryGroup = {
  key: IndicatorCategoryKey;
  label: string;
  description: string;
  options: ChartIndicatorOption[];
};

export type IndicatorParameters = {
  maShort: number;
  maMiddle: number;
  maLong: number;
  emaFast: number;
  emaSlow: number;
  wmaPeriod: number;
  hmaPeriod: number;
  vwmaPeriod: number;
  bollingerPeriod: number;
  bollingerStdDev: number;
  bbWidthPeriod: number;
  stdDevPeriod: number;
  choppinessPeriod: number;
  volumeMa: number;
  rsiPeriod: number;
  macdFast: number;
  macdSlow: number;
  macdSignal: number;
  kdPeriod: number;
  momentumPeriod: number;
  tsiShortPeriod: number;
  tsiLongPeriod: number;
  tsiSignalPeriod: number;
  awesomeFastPeriod: number;
  awesomeSlowPeriod: number;
  ultimateShortPeriod: number;
  ultimateMiddlePeriod: number;
  ultimateLongPeriod: number;
  atrPeriod: number;
  adxPeriod: number;
  donchianPeriod: number;
  ichimokuConversionPeriod: number;
  ichimokuBasePeriod: number;
  ichimokuSpanBPeriod: number;
  ichimokuDisplacement: number;
  supertrendAtrPeriod: number;
  supertrendMultiplier: number;
  keltnerPeriod: number;
  keltnerAtrPeriod: number;
  keltnerMultiplier: number;
  aroonPeriod: number;
  obvMa: number;
  mfiPeriod: number;
  cmfPeriod: number;
  cciPeriod: number;
  williamsRPeriod: number;
  rocPeriod: number;
  stochRsiPeriod: number;
  stochRsiSmoothK: number;
  stochRsiSmoothD: number;
  trixPeriod: number;
  trixSignal: number;
  volumeProfileRows: number;
  pivotLookback: number;
  supportResistanceLookback: number;
  gapMinPct: number;
  relativeStrengthLookback: number;
  betaPeriod: number;
  correlationPeriod: number;
};

export const indicatorCategoryDefinitions: Array<Omit<IndicatorCategoryGroup, "options">> = [
  {
    key: "trend",
    label: "Trend / Moving Average",
    description: "Direction, MA alignment, trend strength, and reversals.",
  },
  {
    key: "volatility",
    label: "Channel / Volatility",
    description: "Price ranges, volatility expansion, and risk position.",
  },
  {
    key: "momentum",
    label: "Momentum / Oscillator",
    description: "Strength, overbought/oversold zones, and short-term turns.",
  },
  {
    key: "volume",
    label: "Volume / Money Flow",
    description: "Volume, volume-price divergence, and money flow.",
  },
  {
    key: "structure",
    label: "Price Structure / Levels",
    description: "Prior highs/lows, support/resistance, gaps, and pivots.",
  },
  {
    key: "relative",
    label: "Relative / Market",
    description: "Relative strength versus the index, group, and external markets.",
  },
  {
    key: "signals",
    label: "Signals / Markers",
    description: "Crossovers, breakouts, divergences, and pattern markers.",
  },
];

export const indicatorOptions: AvailableIndicatorOption[] = [
  { status: "available", key: "ma", label: "MA", description: "MA5 / MA20 / MA60", category: "trend", plot: "overlay" },
  { status: "available", key: "ema", label: "EMA", description: "EMA12 / EMA26", category: "trend", plot: "overlay" },
  { status: "available", key: "adx", label: "ADX", description: "ADX / +DI / -DI", category: "trend", plot: "pane" },
  { status: "available", key: "psar", label: "SAR", description: "Parabolic SAR", category: "trend", plot: "overlay" },
  { status: "available", key: "supertrend", label: "Supertrend", description: "ATR trend band", category: "trend", plot: "overlay" },
  { status: "available", key: "ichimoku", label: "Ichimoku", description: "Ichimoku 9 / 26 / 52", category: "trend", plot: "overlay" },
  { status: "available", key: "bollinger", label: "BOLL", description: "20MA +/- 2SD", category: "volatility", plot: "overlay" },
  { status: "available", key: "donchian", label: "DONCH", description: "20-day channel", category: "volatility", plot: "overlay" },
  { status: "available", key: "keltner", label: "Keltner", description: "EMA + ATR channel", category: "volatility", plot: "overlay" },
  { status: "available", key: "atr", label: "ATR", description: "ATR 14", category: "volatility", plot: "pane" },
  { status: "available", key: "rsi", label: "RSI", description: "RSI 14", category: "momentum", plot: "pane" },
  { status: "available", key: "macd", label: "MACD", description: "12 / 26 / 9", category: "momentum", plot: "pane" },
  { status: "available", key: "kd", label: "KD", description: "KD 9 / 3", category: "momentum", plot: "pane" },
  { status: "available", key: "aroon", label: "Aroon", description: "New-high / new-low trend strength", category: "momentum", plot: "pane" },
  { status: "available", key: "cci", label: "CCI", description: "CCI 20", category: "momentum", plot: "pane" },
  { status: "available", key: "williamsR", label: "W%R", description: "Williams %R 14", category: "momentum", plot: "pane" },
  { status: "available", key: "roc", label: "ROC", description: "ROC 12", category: "momentum", plot: "pane" },
  { status: "available", key: "stochRsi", label: "StochRSI", description: "RSI stochastic indicator", category: "momentum", plot: "pane" },
  { status: "available", key: "trix", label: "TRIX", description: "Triple-smoothed momentum", category: "momentum", plot: "pane" },
  { status: "available", key: "volume", label: "VOL", description: "Volume", category: "volume", plot: "pane" },
  { status: "available", key: "vwap", label: "VWAP", description: "Volume-weighted average price", category: "volume", plot: "overlay" },
  { status: "available", key: "obv", label: "OBV", description: "On-balance volume", category: "volume", plot: "pane" },
  { status: "available", key: "mfi", label: "MFI", description: "Money Flow 14", category: "volume", plot: "pane" },
  { status: "available", key: "signals", label: "SIGNAL", description: "Crossover / breakout markers", category: "signals", plot: "signal" },
];

export const professionalIndicatorOptions: AvailableIndicatorOption[] = [
  { status: "available", key: "wma", label: "WMA", description: "Weighted moving average", category: "trend", plot: "overlay" },
  { status: "available", key: "hma", label: "HMA", description: "Hull Moving Average", category: "trend", plot: "overlay" },
  { status: "available", key: "vwma", label: "VWMA", description: "Volume-weighted moving average", category: "trend", plot: "overlay" },
  { status: "available", key: "bbWidth", label: "BB Width", description: "Bollinger band width", category: "volatility", plot: "pane" },
  { status: "available", key: "stdDev", label: "StdDev", description: "Standard deviation volatility", category: "volatility", plot: "pane" },
  { status: "available", key: "choppiness", label: "CHOP", description: "Chop / trend degree", category: "volatility", plot: "pane" },
  { status: "available", key: "momentum", label: "Momentum", description: "Price momentum", category: "momentum", plot: "pane" },
  { status: "available", key: "tsi", label: "TSI", description: "True Strength Index", category: "momentum", plot: "pane" },
  { status: "available", key: "awesomeOscillator", label: "AO", description: "Awesome Oscillator", category: "momentum", plot: "pane" },
  { status: "available", key: "ultimateOscillator", label: "UO", description: "Ultimate Oscillator", category: "momentum", plot: "pane" },
  { status: "available", key: "cmf", label: "CMF", description: "Chaikin Money Flow", category: "volume", plot: "pane" },
  { status: "available", key: "adLine", label: "A/D", description: "Accumulation / Distribution", category: "volume", plot: "pane" },
  { status: "available", key: "pvt", label: "PVT", description: "Price Volume Trend", category: "volume", plot: "pane" },
  { status: "available", key: "volumeProfile", label: "VPVR", description: "Approximate visible-range volume profile", category: "volume", plot: "context" },
  { status: "available", key: "pivotPoints", label: "Pivot", description: "Prior-candle pivot levels", category: "structure", plot: "overlay" },
  { status: "available", key: "supportResistance", label: "S/R", description: "Range support/resistance", category: "structure", plot: "overlay" },
  { status: "available", key: "gap", label: "Gap", description: "Gap markers", category: "structure", plot: "overlay" },
  { status: "available", key: "divergence", label: "Divergence", description: "RSI / MACD price divergence", category: "signals", plot: "signal" },
  { status: "available", key: "candlestickPatterns", label: "Pattern", description: "Candlestick pattern recognition", category: "signals", plot: "signal" },
  { status: "available", key: "relativeStrength", label: "RS", description: "Relative strength versus the index", category: "relative", plot: "pane" },
  { status: "available", key: "beta", label: "Beta", description: "Sensitivity versus the index", category: "relative", plot: "pane" },
  { status: "available", key: "correlation", label: "Corr", description: "Return correlation with the index", category: "relative", plot: "pane" },
];

export const plannedIndicatorOptions: PlannedIndicatorOption[] = [];

export const indicatorCategoryGroups: IndicatorCategoryGroup[] =
  indicatorCategoryDefinitions.map((category) => ({
    ...category,
    options: [...indicatorOptions, ...plannedIndicatorOptions].filter(
      (option) => option.category === category.key
    ),
  }));

export const professionalIndicatorCategoryGroups: IndicatorCategoryGroup[] =
  indicatorCategoryDefinitions.map((category) => ({
    ...category,
    options: [
      ...indicatorOptions,
      ...professionalIndicatorOptions,
      ...plannedIndicatorOptions,
    ].filter((option) => option.category === category.key),
  }));

function translatedOrFallback(
  t: TranslationFunction,
  key: string,
  fallback: string
) {
  const translated = t(key);
  return translated === key ? fallback : translated;
}

export function indicatorCategoryLabel(
  t: TranslationFunction,
  group: IndicatorCategoryGroup
) {
  return translatedOrFallback(t, `indicators.categories.${group.key}.label`, group.label);
}

export function indicatorCategoryDescription(
  t: TranslationFunction,
  group: IndicatorCategoryGroup
) {
  return translatedOrFallback(
    t,
    `indicators.categories.${group.key}.description`,
    group.description
  );
}

export function indicatorOptionDescription(
  t: TranslationFunction,
  option: ChartIndicatorOption
) {
  return translatedOrFallback(t, `indicators.options.${option.key}`, option.description);
}

export const defaultIndicators: IndicatorSettings = {
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

export const defaultIndicatorParameters: IndicatorParameters = {
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

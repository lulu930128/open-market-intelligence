import type { ChartPoint, StockIndicatorPoint } from "@/types/market";

export type CanonicalIndicatorAuthority = "backend" | "presentation";
export type IndicatorProjectionScope =
  | "backend_authoritative"
  | "backend_unavailable"
  | "mixed"
  | "presentation_only";

// Renderer wiring only; algorithm support comes from the Backend contract.
export const backendIndicatorCapabilities: Record<string, string> = {
  volume: "volume_ma", ma: "ma", ema: "ema", bollinger: "bollinger",
  donchian: "donchian", rsi: "rsi", macd: "macd", kd: "kd",
  atr: "atr", adx: "adx", mfi: "mfi", roc: "roc",
  supportResistance: "support_resistance", vwap: "vwap", obv: "obv",
};

export function backendIndicatorTimeKey(value: string, intraday: boolean) {
  if (!intraday) return value.slice(0, 10);
  const instant = Date.parse(value);
  return Number.isFinite(instant) ? String(instant) : value;
}

export function backendScalarIndicatorValue(
  point: StockIndicatorPoint | undefined,
  key: "vwap" | "obv"
) {
  const value = point?.[key];
  return isBackendAuthoritativeIndicator(point) &&
    typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function isBackendAuthoritativeIndicator(
  point: StockIndicatorPoint | undefined
) {
  return Boolean(
    point?.calculation_role === "backend_authoritative" &&
      (point.algorithm_version?.startsWith("omi.research.technical.") ||
        point.algorithm_version?.startsWith("tw.technical.indicators.")) &&
      point.price_basis
  );
}

export function backendIndicatorParametersMatch(
  point: StockIndicatorPoint | undefined,
  expected: Record<string, number>
) {
  if (!isBackendAuthoritativeIndicator(point)) return false;

  const contract = point?.parameter_contract ?? {};
  return Object.entries(expected).every(([key, value]) => contract[key] === value);
}

export function backendIndicatorWindowExists(
  point: StockIndicatorPoint | undefined,
  key: "ma_windows" | "volume_ma_windows",
  window: number
) {
  if (!isBackendAuthoritativeIndicator(point)) return false;

  const windows = point?.parameter_contract?.[key];
  return Array.isArray(windows) && windows.includes(window);
}

export function backendIndicatorValue(
  values: Record<string, number | null> | undefined,
  key: string
) {
  const value = values?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function indicatorProjectionScope(
  points: StockIndicatorPoint[],
  chartData: ChartPoint[],
  options?: {
    indicators?: Record<string, boolean>;
    parameters?: Record<string, number>;
    canonicalAuthority?: CanonicalIndicatorAuthority;
  }
): IndicatorProjectionScope {
  const activeIndicators = Object.entries(options?.indicators ?? {})
    .filter(([, enabled]) => enabled)
    .map(([key]) => key);
  const backendProjectedIndicators = new Set(Object.keys(backendIndicatorCapabilities));
  const usesPresentationOnlyIndicator = activeIndicators.some(
    (key) => !backendProjectedIndicators.has(key)
  );
  const parameters = options?.parameters ?? {};
  const pointMatchesActiveContract = (point: StockIndicatorPoint) => {
    if (!isBackendAuthoritativeIndicator(point)) return false;
    if (
      activeIndicators.includes("ma") &&
      ![parameters.maShort, parameters.maMiddle, parameters.maLong].every(
        (window) =>
          typeof window === "number" &&
          backendIndicatorWindowExists(point, "ma_windows", window)
      )
    ) {
      return false;
    }
    if (
      activeIndicators.includes("ema") &&
      !backendIndicatorParametersMatch(point, {
        ema_fast: parameters.emaFast,
        ema_slow: parameters.emaSlow,
      })
    ) {
      return false;
    }
    const parameterContracts: Array<[
      string,
      Record<string, number | undefined>,
    ]> = [
      [
        "bollinger",
        {
          bollinger_period: parameters.bollingerPeriod,
          bollinger_std_dev: parameters.bollingerStdDev,
        },
      ],
      ["donchian", { donchian_period: parameters.donchianPeriod }],
      ["rsi", { rsi_period: parameters.rsiPeriod }],
      [
        "macd",
        {
          macd_fast: parameters.macdFast,
          macd_slow: parameters.macdSlow,
          macd_signal: parameters.macdSignal,
        },
      ],
      ["kd", { kd_period: parameters.kdPeriod }],
      ["atr", { atr_period: parameters.atrPeriod }],
      ["adx", { adx_period: parameters.adxPeriod }],
      ["mfi", { mfi_period: parameters.mfiPeriod }],
      ["roc", { roc_period: parameters.rocPeriod }],
      [
        "supportResistance",
        { support_resistance_period: parameters.supportResistanceLookback },
      ],
    ];
    return parameterContracts.every(([key, contract]) => {
      if (!activeIndicators.includes(key)) return true;
      const completeContract = Object.fromEntries(
        Object.entries(contract).filter(
          (entry): entry is [string, number] => typeof entry[1] === "number"
        )
      );
      return (
        Object.keys(completeContract).length === Object.keys(contract).length &&
        backendIndicatorParametersMatch(point, completeContract)
      );
    });
  };
  const intraday = chartData.some((point) => point.time.length > 10);
  const authoritativeDates = new Set(
    points
      .filter(pointMatchesActiveContract)
      .map((point) => backendIndicatorTimeKey(point.time, intraday))
  );
  const chartDates = new Set(
    chartData
      .filter((point) => typeof point.close === "number" && Number.isFinite(point.close))
      .map((point) => backendIndicatorTimeKey(point.time, intraday))
  );
  const authoritativeCount = [...chartDates].filter((time) =>
    authoritativeDates.has(time)
  ).length;

  if (
    !usesPresentationOnlyIndicator &&
    chartDates.size > 0 &&
    authoritativeCount === chartDates.size
  ) {
    return "backend_authoritative";
  }

  if (options?.canonicalAuthority === "backend") {
    return "backend_unavailable";
  }
  return authoritativeCount > 0 ? "mixed" : "presentation_only";
}

export function allowsCanonicalIndicatorFallback(
  scope: IndicatorProjectionScope
) {
  return scope === "presentation_only";
}

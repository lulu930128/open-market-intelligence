import { expect, test } from "@playwright/test";
import { defaultIndicatorParameters, defaultIndicators, professionalIndicatorCategoryGroups } from "@/components/stock-k-line/indicatorCatalog";
import { filterTaiwanIndicatorPreset, projectTaiwanIndicatorMenu } from "@/components/stock-k-line/taiwanIndicatorMenu";
import { projectStockKLineData } from "@/components/stock-k-line/indicatorProjection";
import { buildSeriesData } from "@/components/chart/lightweight-chart/indicatorSeriesProjection";
import { indicatorProjectionScope } from "@/components/stock-k-line/indicatorAuthority";
import type { ChartPoint, StockIndicatorPoint, TaiwanTechnicalCapabilityContract } from "@/types/market";

const contract: TaiwanTechnicalCapabilityContract = {
  contract_version: "tw.technical.capabilities.v1",
  algorithm_version: "tw.technical.indicators.v4",
  calculation_owner: "TaiwanTechnicalService", frontend_fallback_allowed: false,
  parameter_contract: { authority: "backend", defaults: {}, ranges: {} },
  indicators: {
    rsi: { status: "available" }, wma: { status: "pending" },
    obv: { status: "available" },
    vwap: { status: "available", applicable_intervals: ["1m", "5m"] },
    volume_profile: { status: "available" },
  },
};

test("TW menu uses capability, interval and renderer availability with current periods", () => {
  const params = { ...defaultIndicatorParameters, rsiPeriod: 10 };
  const groups = projectTaiwanIndicatorMenu(professionalIndicatorCategoryGroups, contract, "1d", params);
  const options = Object.fromEntries(groups.flatMap(group => group.options).map(option => [option.key, option]));
  expect(options.rsi.status).toBe("available");
  expect(options.rsi.canonicalDescription).toBe("RSI 10");
  expect(options.wma.status).toBe("pending");
  expect(options.vwap.status).toBe("not_applicable");
  expect(options.volumeProfile.status).toBe("unavailable");
  expect(options.beta.status).toBe("unsupported");
  const preset = filterTaiwanIndicatorPreset({ ...defaultIndicators, rsi: true, wma: true, vwap: true }, groups);
  expect(preset.rsi).toBe(true);
  expect(preset.wma).toBe(false);
  expect(preset.vwap).toBe(false);
  expect(params.rsiPeriod).toBe(10);
  expect(projectTaiwanIndicatorMenu(professionalIndicatorCategoryGroups, null, "1m", params)
    .flatMap(group => group.options).every(option => option.status === "unavailable")).toBe(true);
});

function points(): { bars: ChartPoint[]; indicators: StockIndicatorPoint[] } {
  const bars = ["2026-09-14T09:01:00+08:00", "2026-09-14T09:02:00+08:00"].map(time => ({
    time, open: 100, high: 102, low: 99, close: 101, volume: 1000,
    trade_value: null, transaction_count: null,
  }));
  const indicators = bars.map((bar, i) => ({
    ...bar, change: null, change_pct: null, ma: {}, volume_ma: {},
    calculation_role: "backend_authoritative", algorithm_version: "tw.technical.indicators.v4",
    price_basis: "raw_unadjusted", parameter_contract: {}, vwap: 100 + i, obv: i === 0 ? -100 : 0,
  }));
  return { bars, indicators };
}

test("Backend VWAP and OBV keep exact intraday alignment and missing values fail closed", () => {
  const { bars, indicators } = points();
  const projected = projectStockKLineData({ chartData: bars, indicatorData: indicators,
    benchmarkData: [], params: defaultIndicatorParameters, latestPreviousClose: null, allowCanonicalFallback: false });
  expect(projected.map(point => point.vwap)).toEqual([100, 101]);
  expect(projected.map(point => point.obv)).toEqual([-100, 0]);
  const series = buildSeriesData(bars, indicators, "volume", "intraday", defaultIndicatorParameters, [], false);
  expect(series.lines.vwap.map(point => point.value)).toEqual([100, 101]);
  expect(series.lines.obv.map(point => point.value)).toEqual([-100, 0]);
  expect(series.lines.obvMa).toEqual([]);
  const utcIndicators = indicators.map(point => ({ ...point, time: new Date(point.time).toISOString() }));
  expect(buildSeriesData(bars, utcIndicators, "volume", "intraday", defaultIndicatorParameters, [], false).lines.vwap.map(point => point.value)).toEqual([100, 101]);
  expect(indicatorProjectionScope(indicators.slice(0, 1), bars, { indicators: { vwap: true }, canonicalAuthority: "backend" })).toBe("backend_unavailable");
  const missing = buildSeriesData(bars, [], "volume", "intraday", defaultIndicatorParameters, [], false);
  expect(missing.lines.vwap).toEqual([]);
  expect(missing.lines.obv).toEqual([]);
  const daily = buildSeriesData(bars.slice(0, 1), indicators.slice(0, 1), "volume", "date", defaultIndicatorParameters, [], false);
  expect(daily.lines.vwap).toEqual([]);
});

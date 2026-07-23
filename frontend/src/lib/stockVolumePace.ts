import type { StockVolumePace } from "@/types/market";

export type StockVolumePaceMetric = {
  ratio: number | null;
  differencePct: number | null;
  sampleDays: number;
  comparisonMinute: string | null;
  provisional: boolean;
  status: StockVolumePace["status"] | "missing";
};

export function stockVolumePaceMetric(
  pace: StockVolumePace | null | undefined
): StockVolumePaceMetric {
  const baseline = pace?.same_time_baseline_5d;
  const ratio =
    baseline?.pace_ratio !== null &&
    baseline?.pace_ratio !== undefined &&
    Number.isFinite(baseline.pace_ratio)
      ? baseline.pace_ratio
      : null;

  return {
    ratio,
    differencePct: ratio === null ? null : (ratio - 1) * 100,
    sampleDays: baseline?.sample_days ?? 0,
    comparisonMinute: pace?.comparison_minute ?? null,
    provisional: ratio !== null && (baseline?.sample_days ?? 0) < 5,
    status: pace?.status ?? "missing",
  };
}

export function formatStockVolumePaceRatio(value: number | null) {
  return value === null ? null : `${value.toFixed(2)}×`;
}

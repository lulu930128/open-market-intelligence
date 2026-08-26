import type { StockIndicatorPoint } from "@/types/market";

export function isBackendAuthoritativeIndicator(
  point: StockIndicatorPoint | undefined
) {
  return Boolean(
    point?.calculation_role === "backend_authoritative" &&
      point.algorithm_version?.startsWith("tw.technical.indicators.") &&
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

export function indicatorProjectionScope(points: StockIndicatorPoint[]) {
  return points.length > 0 && points.every(isBackendAuthoritativeIndicator)
    ? "backend_authoritative"
    : "presentation_only";
}

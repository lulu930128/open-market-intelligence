"use client";

import { useT } from "@/i18n";
import type { MarketBreadth, MarketIndexSnapshot } from "@/types/market";

export function CompactBreadthCoverage({ breadth }: { breadth: MarketBreadth }) {
  const t = useT();
  const percent = (value: number | null | undefined) => value == null ? "—" : `${(value * 100).toFixed(1)}%`;
  return <span data-testid="tw-breadth-coverage">{t("dashboard.marketIndex.breadthCoverageCompact", {
    receivedPct: percent(breadth.received_coverage_ratio),
    classifiedPct: percent(breadth.classified_coverage_ratio),
  })}</span>;
}

export function resolveLimitMetric(breadth: MarketBreadth | null | undefined, direction: "up" | "down") {
  const exact = direction === "up" ? breadth?.limit_up_count : breadth?.limit_down_count;
  const side = breadth?.limits?.[direction];
  if (exact != null) return { value: exact, status: "exact" as const, side };
  if (side && side.evaluated_count > 0) return { value: side.observed_count, status: "observed" as const, side };
  return { value: null, status: "unknown" as const, side };
}

export function BreadthCoverage({ breadth }: { breadth: MarketBreadth }) {
  const t = useT();
  const percent = (value: number | null | undefined) =>
    value == null ? "—" : `${(value * 100).toFixed(2)}%`;
  const limits = breadth.limits;
  return (
    <div className="w-full min-w-0 space-y-1 break-words text-xs text-omi-text-muted" data-testid="tw-breadth-coverage">
      {breadth.classified_coverage_ratio !== undefined ? (
        <div>{t("dashboard.marketIndex.breadthCoverageDual", {
          received: breadth.received_count ?? "—", total: breadth.total_count,
          classified: breadth.classified_count ?? breadth.coverage_count ?? "—",
          receivedPct: percent(breadth.received_coverage_ratio),
          classifiedPct: percent(breadth.classified_coverage_ratio),
        })}</div>
      ) : null}
      {limits && (breadth.limit_up_count == null || breadth.limit_down_count == null) ? (
        <div>{t("dashboard.marketIndex.breadthLimitsObserved", {
          up: limits.up.observed_count, down: limits.down.observed_count,
          upCoverage: limits.up.evaluated_count, downCoverage: limits.down.evaluated_count,
          total: limits.universe_count,
        })}</div>
      ) : null}
      <div>{t("dashboard.marketIndex.breadthGaps", {
        unclassified: breadth.received_unclassified_count ?? "—",
        missing: breadth.not_received_count ?? breadth.missing_count ?? "—",
      })}</div>
      {limits ? <div>{t("dashboard.marketIndex.breadthLimitUnknowns", {
        up: limits.up.unknown_count, down: limits.down.unknown_count,
      })}</div> : null}
      {Object.entries(breadth.classification_diagnostics ?? {}).map(([reason, count]) =>
        <div key={reason}>{reason}: {count}</div>)}
      <div className="break-all">{t("dashboard.marketIndex.breadthProvenance", {
        source: breadth.source ?? "—", receipt: breadth.raw_result_id ?? "—",
        date: breadth.trade_date ?? "—",
      })}</div>
      <p>{t("dashboard.marketIndex.breadthExplanation")}</p>
    </div>
  );
}

export function BreadthInfo({ breadth }: { breadth: MarketBreadth }) {
  const t = useT();
  return <details className="w-full min-w-0 text-xs text-omi-text-muted">
    <summary className="cursor-pointer"><CompactBreadthCoverage breadth={breadth} /> · {t("dashboard.marketIndex.breadthDetails")}</summary>
    <div className="mt-2"><BreadthCoverage breadth={breadth} /></div>
  </details>;
}

export function OfficialBreadthComparison({ lanes }: { lanes: MarketIndexSnapshot["breadth_lanes"] }) {
  const t = useT();
  if (!lanes || lanes.status === "not_applicable") return null;
  const daily = lanes.official_daily;
  return <div className="w-full min-w-0 text-xs text-omi-text-muted">
    {!daily || daily.status === "missing" ? t("dashboard.marketIndex.breadthOfficialMissing") :
      t(daily.published_limits ? "dashboard.marketIndex.breadthPublishedComparison" : "dashboard.marketIndex.breadthOfficialComparison", {
        date: daily.trade_date ?? "—", advance: daily.advance_count ?? "—",
        decline: daily.decline_count ?? "—", unchanged: daily.unchanged_count ?? "—",
        total: daily.total_count ?? "—",
        up: daily.limit_up_count ?? "—", down: daily.limit_down_count ?? "—",
      })}
    {daily?.status === "partial" ? ` · ${t("dashboard.marketIndex.breadthPartial")}` : null}
  </div>;
}

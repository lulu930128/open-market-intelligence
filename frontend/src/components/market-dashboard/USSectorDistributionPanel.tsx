"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "@/lib/api";
import { useT } from "@/i18n";
import { formatPct, valueTone } from "@/components/market-dashboard/dashboardFormatters";
import type { USSectorDistribution } from "@/types/usDistribution";

export default function USSectorDistributionPanel() {
  const t = useT();
  const [data, setData] = useState<USSectorDistribution | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [request, setRequest] = useState(0);
  const [dimension, setDimension] = useState<"sectors" | "industries" | "hot_groups">("sectors");
  const [sort, setSort] = useState<"strong" | "weak" | "name">("strong");

  useEffect(() => {
    const controller = new AbortController();
    async function read() {
      setLoading(true);
      setFailed(false);
      try {
        const result = await fetchJson<USSectorDistribution>("/api/us-market/sectors", undefined, { signal: controller.signal });
        if (result.schema_version !== "us.market.sector_distribution.v1" || result.data_mode !== "eod_market_snapshot") {
          throw new Error("Unsupported US EOD distribution contract");
        }
        if (!controller.signal.aborted) setData(result);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void read();
    return () => controller.abort();
  }, [request]); // EOD mount/manual read only; independent of quote polling.

  const groups = useMemo(() => {
    const values = [...(data?.[dimension] ?? [])];
    return values.sort((a, b) => {
      if (sort === "name") return (a.industry ?? a.sector ?? "").localeCompare(b.industry ?? b.sector ?? "");
      if (a.avg_return_pct === null) return b.avg_return_pct === null ? a.group_id.localeCompare(b.group_id) : 1;
      if (b.avg_return_pct === null) return -1;
      return sort === "strong" ? b.avg_return_pct - a.avg_return_pct : a.avg_return_pct - b.avg_return_pct;
    });
  }, [data, dimension, sort]);

  return (
    <section className="min-w-0 rounded-lg border border-omi-border-subtle bg-omi-surface p-3 text-xs text-omi-text" data-testid="us-sector-distribution" aria-busy={loading}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-omi-text-strong">{t("usDistribution.title")}</h2>
        <button type="button" disabled={loading} className="rounded border border-omi-border-subtle px-2 py-1 disabled:opacity-50" onClick={() => setRequest((value) => value + 1)}>
          {loading ? t("usDistribution.loading") : t("usDistribution.reload")}
        </button>
      </div>
      <p className="mt-2 text-omi-warning">{t("usDistribution.snapshot")}</p>
      <p className="mt-1 text-omi-text-muted">{t("usDistribution.taxonomy")}</p>
      {failed && <p className="mt-3 text-omi-warning" role="alert">{t("usDistribution.error")}</p>}
      {loading && !data && <p className="py-4" role="status">{t("usDistribution.loading")}</p>}
      {data && (
        <>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px]">
            <span>{t("usDistribution.asOf")}: {data.as_of ?? "—"}</span>
            <span>{t("usDistribution.expected")}: {data.expected_trade_date}</span>
            <span>{t("usDistribution.reference")}: {data.reference_trade_date}</span>
            <span>{t("usDistribution.freshness")}: {t(`usDistribution.${data.freshness_status}`)}</span>
            <span>{t("usDistribution.classificationDate")}: {data.classification_coverage.as_of ?? "—"}</span>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              [t("usDistribution.universe"), data.coverage.universe_count],
              [t("usDistribution.classified"), data.classification_coverage.mapped_count],
              [t("usDistribution.evaluated"), data.coverage.evaluated_count],
              [t("usDistribution.notCovered"), data.coverage.not_covered_count],
              [t("usDistribution.comparable"), data.counts.comparable],
              [t("usDistribution.unknown"), data.counts.unknown],
              [t("usDistribution.stale"), data.counts.stale],
              [t("usDistribution.noTrade"), data.counts.no_trade],
            ].map(([label, value]) => <div key={label} className="border-l border-omi-border-subtle pl-2"><dt className="text-omi-text-muted">{label}</dt><dd className="font-mono text-sm">{value ?? "\u2014"}</dd></div>)}
          </dl>
          <p className="mt-2 text-omi-text-muted">
            {t("usDistribution.priceCoverage")}: {formatPct(data.coverage.price_coverage_ratio === null ? null : data.coverage.price_coverage_ratio * 100)} · {t("usDistribution.comparableCoverage")}: {formatPct(data.coverage.comparable_coverage_ratio === null ? null : data.coverage.comparable_coverage_ratio * 100)} · {t("usDistribution.classificationCoverage")}: {formatPct(data.classification_coverage.coverage_ratio === null ? null : data.classification_coverage.coverage_ratio * 100)}
          </p>
          {data.status === "unavailable" && <p role="status" className="mt-3 border-l-2 border-omi-warning pl-3">{t("usDistribution.empty")}</p>}
          <div className="my-3 flex flex-wrap items-center gap-2">
            <label>{t("usDistribution.view")} <select className="rounded border border-omi-border-subtle bg-omi-surface-subtle p-1" value={dimension} onChange={(event) => setDimension(event.target.value as typeof dimension)}>
              <option value="sectors">{t("usDistribution.sectors")}</option>
              <option value="industries">{t("usDistribution.industries")}</option>
              <option value="hot_groups">{t("usDistribution.hotGroups")}</option>
            </select></label>
            <label>{t("usDistribution.sort")} <select className="rounded border border-omi-border-subtle bg-omi-surface-subtle p-1" value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}>
              <option value="strong">{t("usDistribution.strong")}</option><option value="weak">{t("usDistribution.weak")}</option><option value="name">{t("usDistribution.name")}</option>
            </select></label>
          </div>
          <div className="divide-y divide-omi-border-subtle">
            {groups.map((group) => (
              <details key={group.group_id} className="py-2">
                <summary className="cursor-pointer rounded focus-visible:outline-2 focus-visible:outline-omi-border-subtle">
                  <span className="inline-grid w-[calc(100%-1.5rem)] grid-cols-[minmax(0,1fr)_auto] items-center gap-2 align-middle">
                    <span className="min-w-0 break-words font-medium text-omi-text-strong">{group.industry ?? group.sector ?? t("usDistribution.unclassified")}<span className="ml-2 font-normal text-omi-text-subtle">{group.provider} · {group.taxonomy}</span></span>
                    <span className={`font-mono ${valueTone(group.avg_return_pct)}`}>{t("usDistribution.average")} {formatPct(group.avg_return_pct)}</span>
                    <span className="col-span-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
                      <span className="text-omi-market-up">↑ {group.counts.up}</span><span className="text-omi-market-down">↓ {group.counts.down}</span>
                      <span>＝ {group.counts.flat}</span><span>{t("usDistribution.unknown")} {group.counts.unknown}</span>
                      <span>{t("usDistribution.sampleCount", { count: group.counts.comparable, total: group.counts.universe })}</span>
                    </span>
                  </span>
                </summary>
                <div className="mt-2 space-y-2 border-l border-omi-border-subtle pl-3">
                  <p>{t("usDistribution.median")} {formatPct(group.median_return_pct)} · {t("usDistribution.fresh")} {group.counts.fresh} · {t("usDistribution.stale")} {group.counts.stale} · {t("usDistribution.noTrade")} {group.counts.no_trade}</p>
                  <p>{t("usDistribution.relativeStrength")}: {formatPct(group.relative_strength_pct)} · {t("usDistribution.turnoverUnavailable")}</p>
                  <p className="text-omi-text-subtle">{t("usDistribution.members")}</p>
                  {group.members.map((member) => <div key={member.symbol} className="break-words">
                    <span className="font-mono">{member.symbol}</span> <span className={valueTone(member.return_pct)}>{formatPct(member.return_pct)}</span>
                    <div className="text-[11px] text-omi-text-subtle">{member.price_lineage.map((line) => `${line.provider} / ${line.source} · ${line.event_at ?? "—"}`).join("; ")}</div>
                    <div className="text-[11px] text-omi-text-subtle">{t("usDistribution.classificationDate")}: {member.classification?.fetched_at ?? "—"}</div>
                  </div>)}
                  {!group.members.length && <p>{t("usDistribution.noMembers")}</p>}
                  {group.members_truncated && <p className="text-omi-text-subtle">{t("usDistribution.membersLimited")}</p>}
                </div>
              </details>
            ))}
            {!groups.length && <p className="py-3">{t("usDistribution.noGroups")}</p>}
          </div>
        </>
      )}
    </section>
  );
}

"use client";

import { useT } from "@/i18n";
import type { IntradaySessionStats } from "./intradayPresentation";
import type { SessionMetric, TaiwanSessionSummary } from "./useTaiwanSessionSummary";

type Props = { summary: TaiwanSessionSummary | null; stats?: IntradaySessionStats | null; reference?: number | null; status?: string };

function numeric(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("zh-TW", { maximumFractionDigits: digits }).format(value) : "—";
}
function evidence(metric?: SessionMetric) {
  return metric ? [metric.trade_date, metric.as_of, metric.source, metric.scope, metric.method, metric.freshness, metric.coverage,
    ...metric.limitations].filter(Boolean).join(" · ") : undefined;
}

export function IntradaySessionMetrics({ summary, stats, reference, status }: Props) {
  const t = useT();
  const metrics = summary?.metrics;
  const fallback: Record<string, number | null | undefined> = {
    open: stats?.open, high: stats?.high, low: stats?.low, reference,
    volume: stats?.totalVolume, last_volume: stats?.lastTradeVolume,
  };
  const keys = ["open", "high", "low", "reference", "average", "volume", "turnover", "last_volume", "previous_volume", "depth"];
  function value(key: string) {
    const item = metrics?.[key];
    const amount = item ? item.value : fallback[key];
    if (key === "depth") return `${numeric(metrics?.bid?.value, 1)} / ${numeric(metrics?.ask?.value, 1)}`;
    if (key === "turnover" && typeof amount === "number") return `${item?.estimated ? "≈ " : ""}${numeric(amount / 100_000_000)} ${t("stockDetail.session.hundredMillion")}`;
    return `${item?.estimated && amount != null ? "≈ " : ""}${numeric(amount, key.includes("volume") ? 1 : 2)}`;
  }
  return <div className="@container min-w-0" data-testid="intraday-session-summary">
    <dl className="grid grid-cols-2 gap-x-4 @[420px]:grid-cols-3 @[600px]:grid-cols-5">
      {keys.map((key) => {
        const item = metrics?.[key];
        const amount = item ? item.value : fallback[key];
        const price = ["open", "high", "low", "average"].includes(key);
        const base = metrics?.reference?.value ?? reference;
        const color = price && amount != null && base != null && amount !== base
          ? amount > base ? "text-omi-market-up" : "text-omi-market-down" : "text-omi-text";
        const labelKey = key === "reference" && summary?.reference_type && summary.reference_type !== "prior_regular_close" ? "comparison" : key;
        return <div key={key} className="min-w-0 border-t border-omi-border-subtle py-0" data-testid={`session-metric-${key}`} title={evidence(item ?? (key === "depth" ? metrics?.bid : undefined))}>
          <dt className="text-xs text-omi-text-muted">{t(`stockDetail.session.${labelKey}`)}</dt>
          <dd className={`mt-0.5 flex flex-wrap items-baseline gap-x-1 text-sm font-semibold tabular-nums ${color}`}>
            <span data-testid={key === "reference" ? "intraday-reference-price" : undefined} data-reference-price={key === "reference" ? amount ?? "" : undefined}>{value(key)}</span>
            {item?.status === "partial" ? <span className="text-[10px] font-normal text-omi-warning-strong">{t("stockDetail.session.partial")}</span> : null}
          </dd>
        </div>;
      })}
    </dl>
    {status !== "ready" ? <p role="status" className="mt-1 text-xs text-omi-text-muted">{t(status === "error" ? "stockDetail.session.unavailable" : "stockDetail.session.loading")}</p> : null}

  </div>;
}

export function IntradaySessionEvidence({ summary }: Pick<Props, "summary">) {
  const t = useT();
  const metrics = summary?.metrics;
  return <div>
      <p className="mt-1 leading-relaxed">{t("stockDetail.session.methodHelp")}</p>
      {metrics ? <dl className="mt-2 space-y-2 break-words">{Object.entries(metrics).map(([key, item]) => <div key={key}>
        <dt className="font-medium">{t(`stockDetail.session.${key === "bid" || key === "ask" ? "depth" : key}`)} · {item.status}</dt>
        <dd>{evidence(item)}</dd>
      </div>)}</dl> : null}
  </div>;
}

export function IntradaySessionStrip({ summary }: Pick<Props, "summary">) {
  const t = useT();
  return <dl className="flex flex-wrap gap-x-5 gap-y-2 text-xs" data-testid="intraday-session-strip">
    {["range_pct", "relative_volume", "vwap_distance_pct"].map((key) => {
      const item = summary?.metrics[key];
      return <div key={key} className="flex items-baseline gap-2" title={evidence(item)}>
        <dt className="text-omi-text-muted">{t(`stockDetail.session.${key}`)}</dt>
        <dd className="font-semibold tabular-nums text-omi-text">{numeric(item?.value)}{item?.value != null ? key === "relative_volume" ? "×" : "%" : ""}
          {item?.status === "partial" ? <span className="ml-1 font-normal text-omi-warning-strong">{t("stockDetail.session.partial")}</span> : null}
        </dd>
      </div>;
    })}
  </dl>;
}

"use client";

import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { useT } from "@/i18n";
import type { IntradayCurrentObservation, IntradayPriceDiagnostics } from "@/types/market";
import { IntradaySessionMetrics, IntradaySessionEvidence } from "./IntradaySessionSummary";
import type { TaiwanSessionSummary } from "./useTaiwanSessionSummary";
import { compactIntradayTimestamp, type IntradaySessionStats } from "./intradayPresentation";

type Props = {
  detailsTarget?: HTMLElement | null;
  chartMode: "line" | "candles";
  onChartModeChange: (mode: "line" | "candles") => void;
  candleCount: number;
  missingCandleCount: number;
  intervalControls: ReactNode;
  details: ReactNode;
  updatedAt?: string | null;
  diagnostics?: IntradayPriceDiagnostics | null;
  observation?: IntradayCurrentObservation | null;
  historyStatus?: string | null;
  degraded: boolean;
  reference: number | null;
  referenceType?: string;
  referenceStatus?: string;
  referenceReason?: string;
  high: number | null;
  low: number | null;
  volume: number | null;
  showVolume: boolean;
  volumeLabel: string;
  stats?: IntradaySessionStats | null;
  summary?: TaiwanSessionSummary | null;
  summaryStatus?: string;
  formatPrice: (value: number | null | undefined) => string;
  formatVolume: (value: number | null | undefined) => string;
};

const controlClass = "min-h-8 px-3 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-omi-text";

export default function IntradayChartHeader(props: Props) {
  const t = useT();
  const { stats, diagnostics, observation, formatPrice, formatVolume } = props;
  // Quote summary quantities are already lots; the chart formatter consumes shares.
  const formatSummaryVolume = stats?.volumeUnit === "lots"
    ? (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) && value >= 0
      ? new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 1 }).format(value) : "—"
    : formatVolume;
  const observationStatus = observation?.freshness_status;
  const status = stats?.status ?? observationStatus;
  const limitedStatus = status && !["current", "fresh", "live"].includes(status) ? status : null;
  const statusLabels: Record<string, string> = {
    stale: t("stockDetail.intraday.staleData"),
    delayed: t("stockDetail.intraday.delayedData"),
    missing: t("stockDetail.intraday.missingData"),
    unavailable: t("stockDetail.intraday.missingData"),
    partial: t("stockDetail.intraday.snapshotDegraded"),
    historical: t("stockDetail.intraday.latestCompletedPrice"),
  };
  const historyLimited = props.historyStatus && ["partial", "missing", "stale", "unavailable"].includes(props.historyStatus);
  const priceStatus = diagnostics
    ? ["official_close", "session_close"].includes(diagnostics.current_price_basis ?? "")
      ? t(diagnostics.current_price_confirmed
        ? diagnostics.current_price_basis === "official_close"
          ? "stockDetail.intraday.officialCloseConfirmed"
          : "stockDetail.intraday.sessionCloseConfirmed"
        : "stockDetail.intraday.closeUnconfirmed")
      : t(diagnostics.current_trade_available ? "stockDetail.intraday.tradeConfirmed" : "stockDetail.intraday.tradeUnconfirmed")
    : null;
  function tone(value: number | null | undefined) {
    if (typeof value !== "number" || !Number.isFinite(value) || props.reference === null || value === props.reference) return "text-omi-text";
    return value > props.reference ? "text-omi-market-up" : "text-omi-market-down";
  }
  function metric(key: string, label: string, value: ReactNode, className = "text-omi-text") {
    return <div key={key} data-testid={`intraday-stat-${key}`} className="flex min-w-0 items-baseline justify-between gap-x-3 py-1.5">
      <dt className="min-w-0 text-xs text-omi-text-muted">{label}</dt>
      <dd className={`shrink-0 text-right text-sm font-semibold tabular-nums sm:text-base ${className}`}>{value}</dd>
    </div>;
  }
  const dataDetails = (<details className={props.detailsTarget ? "group text-xs text-omi-text-muted" : "group px-4 pb-2 text-xs text-omi-text-muted"} data-testid="intraday-data-details">
        <summary className={props.detailsTarget ? "flex h-8 cursor-pointer items-center whitespace-nowrap px-2 focus-visible:outline-2" : "w-fit cursor-pointer py-1 focus-visible:outline-2 focus-visible:outline-omi-text"}>{t(props.summaryStatus ? "stockDetail.session.methods" : "stockDetail.intraday.dataDetails")}</summary>
        <div className={props.detailsTarget ? "absolute right-0 top-full z-30 mt-2 max-h-80 w-[min(36rem,calc(100vw-4rem))] space-y-2 overflow-y-auto break-words border border-omi-border bg-omi-surface p-3 text-left shadow-lg" : "mt-1 space-y-1 break-words border-l border-omi-border pl-3"}>
          {props.summaryStatus ? <IntradaySessionEvidence summary={props.summary ?? null} /> : null}
          {props.details}
          {stats ? <div>{t("stockDetail.intraday.quoteDetails", { source: stats.source ?? "—", time: stats.asOf ?? "—", status: stats.status })}</div> : null}
          {diagnostics?.current_trade_unavailable_reason ? <div>{diagnostics.current_trade_unavailable_reason}</div> : null}
          {props.historyStatus ? <div>{t("stockDetail.intraday.historyStatus", { status: props.historyStatus })}</div> : null}
          {observation?.limitations?.map((limit) => <div key={limit}>{limit}</div>)}
        </div>
      </details>);
  return (
    <div className="@container border-b border-omi-border-subtle">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-4 py-3">
        <div className="min-w-0 flex-[0_0_11rem]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-omi-text">{t("stockDetail.intraday.chartTitle")}</span>
            {props.degraded || historyLimited ? <span data-testid="intraday-snapshot-degraded" className="text-xs font-medium text-omi-warning-strong">{t("stockDetail.intraday.snapshotDegraded")}</span> : null}
          </div>
          <div className="mt-2 flex flex-col items-start gap-1">
            <div role="group" aria-label={t("stockDetail.intraday.chartMode")} className="inline-flex border border-omi-border">
              {(["line", "candles"] as const).map((mode) => <button
                key={mode} type="button" aria-pressed={props.chartMode === mode}
                disabled={mode === "candles" && props.candleCount === 0}
                title={mode === "candles" && props.candleCount === 0 ? t("stockDetail.intraday.candlesUnavailable") : undefined}
                onClick={() => props.onChartModeChange(mode)}
                className={`${controlClass} ${props.chartMode === mode ? "bg-omi-control text-omi-text-inverse" : "text-omi-text-muted hover:bg-omi-surface-muted"} disabled:cursor-not-allowed disabled:opacity-40`}
              >{t(`stockDetail.intraday.${mode}`)}</button>)}
            </div>
            {props.intervalControls}
          </div>

        </div>
        {props.summaryStatus ? <div className="min-w-0 max-w-[50rem] flex-[1_1_34rem] pt-0 @[780px]:pt-7"><IntradaySessionMetrics summary={props.summary ?? null} stats={stats} reference={props.reference} status={props.summaryStatus} /></div> : null}
        {!props.summaryStatus ? <dl data-testid="intraday-session-stats" className="grid min-w-0 flex-[2_1_26rem] grid-cols-2 content-start gap-x-5 sm:grid-cols-3 sm:gap-x-7">
          {stats ? metric("open", t("stockDetail.intraday.open"), formatPrice(stats.open), tone(stats.open)) : null}
          {metric("high", t("stockDetail.intraday.high"), formatPrice(stats ? stats.high : props.high), tone(stats ? stats.high : props.high))}
          {metric("low", t("stockDetail.intraday.low"), formatPrice(stats ? stats.low : props.low), tone(stats ? stats.low : props.low))}
          {metric("reference", t(props.referenceType && props.referenceType !== "prior_regular_close" ? "stockDetail.intraday.referencePrice" : "stockDetail.intraday.previousClose"), <>
            <span data-testid="intraday-reference-price" data-reference-price={props.reference ?? ""} data-reference-status={props.referenceStatus ?? "unknown"}>{formatPrice(props.reference)}</span>
            {props.referenceStatus && props.referenceStatus !== "current" ? <span className="ml-1 text-[10px] text-omi-warning-strong" title={props.referenceReason}>{props.referenceStatus}</span> : null}
          </>)}
          {props.showVolume || stats ? metric("volume", props.volumeLabel, formatSummaryVolume(props.volume)) : null}
          {stats ? metric("last-volume", t("stockDetail.intraday.lastMatchLots"), <span title={t("stockDetail.intraday.lastMatchHelp")}>{formatSummaryVolume(stats.lastTradeVolume)}</span>) : null}
        </dl> : null}
      </div>
          <div className="px-4 pb-2 flex flex-wrap gap-x-2 gap-y-1 text-xs text-omi-text-muted" data-testid="intraday-status">
            {priceStatus ? <span data-testid="intraday-current-price-status" className={diagnostics?.current_price_confirmed || diagnostics?.current_trade_available ? "" : "text-omi-warning-strong"}>{priceStatus}</span> : null}
            {props.detailsTarget === undefined ? <time title={props.updatedAt ?? undefined}>{compactIntradayTimestamp(props.updatedAt)}</time> : null}
            {limitedStatus ? <span className="text-omi-warning-strong" title={limitedStatus}>{stats ? `${t("stockDetail.session.quoteSnapshot")} · ` : ""}{statusLabels[limitedStatus] ?? limitedStatus}</span> : null}
            {observation?.is_fallback ? <span className="text-omi-warning-strong">{t("stockDetail.intraday.fallbackActive")}</span> : null}
          </div>
      {(props.candleCount === 0 || (props.chartMode === "candles" && props.missingCandleCount > 0)) ? <p className="px-4 pb-2 text-xs text-omi-warning-strong" data-testid="intraday-candle-limitation">
        {t(props.candleCount === 0 ? "stockDetail.intraday.candlesUnavailable" : "stockDetail.intraday.candlesPartial", { count: props.missingCandleCount })}
      </p> : null}
      {props.detailsTarget ? createPortal(dataDetails, props.detailsTarget) : dataDetails}
    </div>
  );
}

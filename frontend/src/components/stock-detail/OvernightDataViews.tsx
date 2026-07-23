"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import {
  formatDate,
  formatPct,
  formatPrice,
  formatSignedLots,
  formatSignedTradeValueYi,
  valueTone,
} from "@/components/stock-detail/stockDetailFormatters";
import type { LoadState } from "@/components/stock-detail/stockDetailTypes";
import { useT, type TranslationFunction } from "@/i18n";
import type {
  AdrParityRead,
  FxFlowContextRead,
  OvernightImpactRead,
} from "@/types/market";

export function overnightConfidenceLabel(
  value: string | null | undefined,
  t?: TranslationFunction
) {
  if (value === "high") {
    return t?.("stockDetail.dataViews.overnight.confidence.high") ?? "Complete data";
  }
  if (value === "medium") {
    return t?.("stockDetail.dataViews.overnight.confidence.medium") ?? "Partial reference";
  }
  if (value === "low") {
    return t?.("stockDetail.dataViews.overnight.confidence.low") ?? "Low completeness";
  }
  return t?.("stockDetail.dataViews.overnight.confidence.unknown") ?? "Completeness pending";
}

function overnightProfileLabel(report: OvernightImpactRead, t: TranslationFunction) {
  const profiles = new Set(report.tw_mapping?.profiles ?? []);

  if (profiles.has("memory")) return t("stockDetail.dataViews.overnight.profiles.memory");
  if (profiles.has("semiconductor")) {
    return t("stockDetail.dataViews.overnight.profiles.semiconductor");
  }
  if (profiles.has("technology")) return t("stockDetail.dataViews.overnight.profiles.technology");

  return t("stockDetail.dataViews.overnight.profiles.taiwan");
}

function overnightStanceLabel(stance: string, t: TranslationFunction) {
  if (stance === "strong_risk_on") return t("stockDetail.dataViews.overnight.stance.strongRiskOn");
  if (stance === "risk_on") return t("stockDetail.dataViews.overnight.stance.riskOn");
  if (stance === "strong_risk_off") {
    return t("stockDetail.dataViews.overnight.stance.strongRiskOff");
  }
  if (stance === "risk_off") return t("stockDetail.dataViews.overnight.stance.riskOff");
  if (stance === "neutral") return t("stockDetail.dataViews.overnight.stance.neutral");

  return t("stockDetail.dataViews.overnight.stance.unknown");
}

function overnightTitle(report: OvernightImpactRead, t: TranslationFunction) {
  const profile = overnightProfileLabel(report, t);
  const key =
    report.stance === "strong_risk_on"
      ? "strongRiskOnTitle"
      : report.stance === "risk_on"
        ? "riskOnTitle"
        : report.stance === "strong_risk_off"
          ? "strongRiskOffTitle"
          : report.stance === "risk_off"
            ? "riskOffTitle"
            : report.stance === "neutral"
              ? "neutralTitle"
              : "insufficientTitle";

  return t(`stockDetail.dataViews.overnight.${key}`, { profile });
}

function overnightTopDriver(report: OvernightImpactRead) {
  const rows = [
    ...report.factors.map((factor) => ({
      label: factor.label,
      contribution: factor.weighted_contribution,
    })),
    ...report.baskets.map((basket) => ({
      label: basket.group_name,
      contribution: basket.weighted_contribution,
    })),
  ].filter((item) => item.contribution !== null && item.contribution !== undefined);

  return rows.length
    ? rows.toSorted((left, right) => Math.abs(right.contribution ?? 0) - Math.abs(left.contribution ?? 0))[0]
        .label
    : null;
}

function overnightSummary(report: OvernightImpactRead, t: TranslationFunction) {
  if (report.weighted_change_pct === null || report.weighted_change_pct === undefined) {
    return t("stockDetail.dataViews.overnight.summaryInsufficient");
  }

  const lead = overnightTopDriver(report);

  return t(
    lead
      ? "stockDetail.dataViews.overnight.summaryWithLead"
      : "stockDetail.dataViews.overnight.summary",
    {
      date: report.as_of ? formatDate(report.as_of) : t("common.noData"),
      direction: overnightStanceLabel(report.stance, t),
      change: formatPct(report.weighted_change_pct),
      lead: lead ?? "",
    }
  );
}

function overnightWarningLabel(message: string, t: TranslationFunction) {
  if (message === "美股因素日期不一致；分數以各因素最新可用資料計算。") {
    return t("stockDetail.dataViews.overnight.warningDateMismatch");
  }

  const staleMatch = message.match(/美股日線最新日期 ([\d-]+)，落後預期 ([\d-]+)。/);
  if (staleMatch) {
    return t("stockDetail.dataViews.overnight.warningStaleDate", {
      date: staleMatch[1],
      expectedDate: staleMatch[2],
    });
  }

  return message;
}

function formatFx(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

function parityGapLabel(
  value: number | null | undefined,
  t: TranslationFunction,
  prefix: "gap" | "remaining"
) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const direction = value > 0.05 ? "Above" : value < -0.05 ? "Below" : "Flat";
  return t(`stockDetail.dataViews.overnight.adr.${prefix}${direction}`, {
    value: formatPct(value),
  });
}

function compactParityGapLabel(
  value: number | null | undefined,
  t: TranslationFunction
) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const direction = value > 0.05 ? "Above" : value < -0.05 ? "Below" : "Flat";
  return t(`stockDetail.dataViews.overnight.adr.compact${direction}`, {
    value: formatPct(value),
  });
}

function AdrParityStrip({
  parity,
  t,
}: {
  parity: AdrParityRead;
  t: TranslationFunction;
}) {
  const hasImpliedPrice =
    parity.adr_close_usd !== null &&
    parity.usd_twd !== null &&
    parity.implied_tw_price_twd !== null;
  const hasDistinctComparison =
    parity.tw_comparison_price_twd !== null &&
    parity.tw_comparison_trade_date !== null &&
    parity.tw_comparison_trade_date !== parity.tw_reference_trade_date;
  const statusLabel =
    parity.status === "partial"
      ? t("stockDetail.dataViews.overnight.adr.statusPartial")
      : parity.status === "stale"
        ? t("stockDetail.dataViews.overnight.adr.statusStale")
        : null;

  return (
    <details
      data-testid="adr-parity-strip"
      className="group mt-2 border border-omi-border-subtle bg-omi-surface-subtle text-xs"
    >
      <summary
        data-testid="adr-parity-toggle"
        title={t("stockDetail.dataViews.overnight.adr.expandLabel")}
        className="flex min-h-11 cursor-pointer list-none flex-wrap items-center justify-between gap-x-3 gap-y-1 px-2.5 py-1.5 hover:bg-omi-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-omi-accent [&::-webkit-details-marker]:hidden"
      >
        <span className="flex min-w-0 items-center gap-2 font-semibold text-omi-text-muted">
          <span className="font-bold uppercase tracking-[0.08em] text-omi-text-strong">
            {t("stockDetail.dataViews.overnight.adr.label")}
          </span>
          <span>{parity.mapping.adr_symbol}</span>
        </span>
        <span className="flex min-w-0 items-center gap-2 tabular-nums">
          {parity.implied_tw_price_twd !== null ? (
            <span className="font-bold text-omi-text-strong">
              NT${formatPrice(parity.implied_tw_price_twd)}
            </span>
          ) : null}
          {statusLabel ? (
            <span className="font-semibold text-omi-warning">{statusLabel}</span>
          ) : parity.implied_gap_pct !== null ? (
            <span className={`font-bold ${valueTone(parity.implied_gap_pct)}`}>
              {compactParityGapLabel(parity.implied_gap_pct, t)}
            </span>
          ) : null}
          <svg
            aria-hidden="true"
            viewBox="0 0 20 20"
            className="size-4 shrink-0 text-omi-text-subtle transition-transform duration-200 motion-reduce:transition-none group-open:rotate-180"
            fill="none"
          >
            <path
              d="m5 7.5 5 5 5-5"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </summary>

      <div
        data-testid="adr-parity-details"
        className="border-t border-omi-border-subtle px-2.5 pb-2 pt-1.5"
      >
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <span className="font-semibold text-omi-text-muted">
            {t("stockDetail.dataViews.overnight.adr.ratioLabel", {
              shares: parity.mapping.local_shares_per_adr,
            })}
          </span>
          {parity.implied_gap_pct !== null ? (
            <span className={`font-bold tabular-nums ${valueTone(parity.implied_gap_pct)}`}>
              {parityGapLabel(parity.implied_gap_pct, t, "gap")}
            </span>
          ) : null}
        </div>

        {hasImpliedPrice ? (
          <>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-1 font-medium tabular-nums text-omi-text-muted">
              <span className="font-semibold text-omi-text-strong">
                {parity.mapping.adr_symbol} US${formatPrice(parity.adr_close_usd)}
              </span>
              <span>×</span>
              <span>USD/TWD {formatFx(parity.usd_twd)}</span>
              <span>÷ {parity.mapping.local_shares_per_adr}</span>
              <span>=</span>
              <span className="text-sm font-bold text-omi-text-strong">
                NT${formatPrice(parity.implied_tw_price_twd)}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-[11px] leading-4 text-omi-text-muted">
              <span>
                {t("stockDetail.dataViews.overnight.adr.referenceLine", {
                  adrDate: formatDate(parity.adr_trade_date),
                  twDate: formatDate(parity.tw_reference_trade_date),
                  price: formatPrice(parity.tw_reference_price_twd),
                  fxDate: formatDate(parity.fx_as_of),
                })}
                {parity.target_tw_trade_date
                  ? ` · ${t("stockDetail.dataViews.overnight.adr.nextSessionLine", {
                      date: formatDate(parity.target_tw_trade_date),
                    })}`
                  : ""}
              </span>
              {hasDistinctComparison ? (
                <span className={valueTone(parity.remaining_gap_pct)}>
                  {t("stockDetail.dataViews.overnight.adr.comparisonLine", {
                    date: formatDate(parity.tw_comparison_trade_date),
                    price: formatPrice(parity.tw_comparison_price_twd),
                  })}
                  {` · ${parityGapLabel(parity.remaining_gap_pct, t, "remaining")}`}
                </span>
              ) : null}
            </div>
          </>
        ) : (
          <div className="mt-1 text-omi-text-muted">
            {t("stockDetail.dataViews.overnight.adr.dataUnavailable")}
          </div>
        )}

        {parity.warnings.length ? (
          <div className="mt-1 text-[11px] leading-4 text-omi-warning">
            {parity.warnings[0] ||
              t("stockDetail.dataViews.overnight.adr.warningFallback")}
          </div>
        ) : null}
      </div>
    </details>
  );
}

function fxRegimeLabel(value: string, t: TranslationFunction) {
  const key =
    value === "twd_weakening"
      ? "weakening"
      : value === "twd_strengthening"
        ? "strengthening"
        : value === "neutral"
          ? "neutral"
          : value === "mixed"
            ? "mixed"
            : "unknown";
  return t(`stockDetail.dataViews.overnight.fxFlow.regime.${key}`);
}

function fxSignalLabel(value: string, t: TranslationFunction) {
  const key =
    value === "confirmed_outflow"
      ? "confirmedOutflow"
      : value === "confirmed_inflow"
        ? "confirmedInflow"
        : value === "weak_twd_inflow_divergence"
          ? "weakTwdInflowDivergence"
          : value === "strong_twd_outflow_divergence"
            ? "strongTwdOutflowDivergence"
            : value === "fx_pressure_only"
              ? "fxPressureOnly"
              : value === "fx_support_only"
                ? "fxSupportOnly"
                : value === "outflow_only"
                  ? "outflowOnly"
                  : value === "inflow_only"
                    ? "inflowOnly"
                    : value === "mixed"
                      ? "mixed"
                      : "unknown";
  return t(`stockDetail.dataViews.overnight.fxFlow.signal.${key}`);
}

function fxRegimeTone(value: string) {
  if (value === "twd_weakening") return "text-omi-danger";
  if (value === "twd_strengthening") return "text-omi-success";
  if (value === "mixed") return "text-omi-warning";
  return "text-omi-text-muted";
}

function fxSignalTone(value: string) {
  if (value === "confirmed_outflow") return "text-omi-danger";
  if (value === "confirmed_inflow") return "text-omi-success";
  if (
    value === "weak_twd_inflow_divergence" ||
    value === "strong_twd_outflow_divergence" ||
    value === "fx_pressure_only" ||
    value === "fx_support_only"
  ) {
    return "text-omi-warning";
  }
  return "text-omi-text-muted";
}

function flowWindow(context: FxFlowContextRead, scope: "market" | "stock", days: number) {
  const flow = scope === "market" ? context.market_foreign : context.stock_foreign;
  return flow.windows.find((item) => item.days === days) ?? null;
}

function FxFlowContextStrip({
  context,
  t,
}: {
  context: FxFlowContextRead;
  t: TranslationFunction;
}) {
  const marketFiveDay = flowWindow(context, "market", 5);
  const stockFiveDay = flowWindow(context, "stock", 5);
  const statusLabel =
    context.status === "partial"
      ? t("stockDetail.dataViews.overnight.fxFlow.statusPartial")
      : context.status === "stale"
        ? t("stockDetail.dataViews.overnight.fxFlow.statusStale")
        : null;

  return (
    <details
      data-testid="fx-flow-context-strip"
      className="group mt-1.5 border border-omi-border-subtle bg-omi-surface-subtle text-xs"
    >
      <summary
        data-testid="fx-flow-context-toggle"
        title={t("stockDetail.dataViews.overnight.fxFlow.expandLabel")}
        className="flex min-h-11 cursor-pointer list-none flex-wrap items-center justify-between gap-x-3 gap-y-1 px-2.5 py-1.5 hover:bg-omi-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-omi-accent [&::-webkit-details-marker]:hidden"
      >
        <span className="flex min-w-0 items-center gap-2 font-semibold text-omi-text-muted">
          <span className="font-bold uppercase tracking-[0.08em] text-omi-text-strong">
            {t("stockDetail.dataViews.overnight.fxFlow.label")}
          </span>
          <span className="tabular-nums">
            USD/TWD {formatFx(context.fx.usd_twd)}
          </span>
        </span>
        <span className="flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-0.5 tabular-nums">
          <span className={`font-semibold ${fxRegimeTone(context.fx.regime)}`}>
            {fxRegimeLabel(context.fx.regime, t)} {formatPct(context.fx.twd_change_5d_pct)}
          </span>
          <span className={`font-bold ${fxSignalTone(context.signal)}`}>
            {fxSignalLabel(context.signal, t)}
          </span>
          {statusLabel ? (
            <span className="font-semibold text-omi-warning">{statusLabel}</span>
          ) : null}
          <svg
            aria-hidden="true"
            viewBox="0 0 20 20"
            className="size-4 shrink-0 text-omi-text-subtle transition-transform duration-200 motion-reduce:transition-none group-open:rotate-180"
            fill="none"
          >
            <path
              d="m5 7.5 5 5 5-5"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </summary>

      <div
        data-testid="fx-flow-context-details"
        className="border-t border-omi-border-subtle px-2.5 pb-2 pt-1.5"
      >
        <dl className="divide-y divide-omi-border-subtle">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1">
            <dt className="font-semibold text-omi-text-strong">
              {t("stockDetail.dataViews.overnight.fxFlow.fxTrendLabel")}
            </dt>
            <dd className="text-right tabular-nums text-omi-text-muted">
              <span className={`font-bold ${fxRegimeTone(context.fx.regime)}`}>
                {fxRegimeLabel(context.fx.regime, t)}
              </span>
              {` · ${t("stockDetail.dataViews.overnight.fxFlow.horizonChanges", {
                one: formatPct(context.fx.twd_change_1d_pct),
                five: formatPct(context.fx.twd_change_5d_pct),
                twenty: formatPct(context.fx.twd_change_20d_pct),
              })}`}
            </dd>
          </div>
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1">
            <dt className="font-semibold text-omi-text-strong">
              {t("stockDetail.dataViews.overnight.fxFlow.marketForeignLabel")}
            </dt>
            <dd className="text-right tabular-nums text-omi-text-muted">
              {t("stockDetail.dataViews.overnight.fxFlow.marketFiveDay", {
                value: formatSignedTradeValueYi(marketFiveDay?.net_value_twd),
              })}
              {marketFiveDay?.turnover_ratio_pct !== null &&
              marketFiveDay?.turnover_ratio_pct !== undefined
                ? ` · ${t("stockDetail.dataViews.overnight.fxFlow.turnoverRatio", {
                    value: formatPct(marketFiveDay.turnover_ratio_pct),
                  })}`
                : ""}
            </dd>
          </div>
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1">
            <dt className="font-semibold text-omi-text-strong">
              {t("stockDetail.dataViews.overnight.fxFlow.stockForeignLabel")}
            </dt>
            <dd className="text-right tabular-nums text-omi-text-muted">
              {t("stockDetail.dataViews.overnight.fxFlow.stockFiveDay", {
                value: formatSignedLots(stockFiveDay?.net_shares),
              })}
            </dd>
          </div>
        </dl>

        <div className="mt-1 text-[11px] leading-4 text-omi-text-muted">
          {t("stockDetail.dataViews.overnight.fxFlow.dates", {
            fxDate: formatDate(context.fx.data_date),
            marketDate: formatDate(context.market_foreign.trade_date),
            stockDate: formatDate(context.stock_foreign.trade_date),
          })}
        </div>
        <div className="mt-1 text-[11px] leading-4 text-omi-text-muted">
          {t("stockDetail.dataViews.overnight.fxFlow.causalityNote")}
        </div>
        {context.warnings.length || context.missing.length ? (
          <div className="mt-1 text-[11px] leading-4 text-omi-warning">
            {context.warnings[0] ||
              t("stockDetail.dataViews.overnight.fxFlow.dataUnavailable")}
          </div>
        ) : null}
      </div>
    </details>
  );
}

export function OvernightImpactPanel({
  report,
  loadState,
}: {
  report: OvernightImpactRead | null;
  loadState: LoadState;
}) {
  const t = useT();

  if (loadState === "idle") return null;

  if (loadState === "loading") {
    return (
      <div className="mt-3 border-t border-omi-border-subtle pt-3">
        <div className="flex items-center justify-between gap-3 text-xs">
          <div>
            <div className="font-bold uppercase tracking-[0.14em] text-omi-text-muted">
              {t("stockDetail.dataViews.overnight.eyebrow")}
            </div>
            <div className="mt-1 text-omi-text-muted">
              {t("stockDetail.dataViews.overnight.loading")}
            </div>
          </div>
          <LoadingDots label={t("stockDetail.dataViews.overnight.loadingShort")} />
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mt-3 border-t border-omi-border-subtle pt-3">
        <div className="flex items-start justify-between gap-4 text-xs">
          <div>
            <div className="font-bold uppercase tracking-[0.14em] text-omi-text-muted">
              {t("stockDetail.dataViews.overnight.eyebrow")}
            </div>
            <div className="mt-1 text-sm font-bold text-omi-text-strong">
              {t("stockDetail.dataViews.overnight.insufficientTitle")}
            </div>
            <div className="mt-0.5 text-omi-text-muted">
              {t("stockDetail.dataViews.overnight.insufficientDescription")}
            </div>
          </div>
          <div className="text-right font-bold text-omi-text-subtle">-</div>
        </div>
      </div>
    );
  }

  const canShowDrivers =
    report.weighted_change_pct !== null && report.weighted_change_pct !== undefined;
  const driverRows = canShowDrivers
    ? [
        ...report.factors.map((factor) => ({
          key: `factor:${factor.symbol}`,
          label: factor.label,
          value: factor.change_pct,
          contribution: factor.weighted_contribution,
        })),
        ...report.baskets.map((basket) => ({
          key: `basket:${basket.group_id}`,
          label: basket.group_name,
          value: basket.average_change_pct,
          contribution: basket.weighted_contribution,
        })),
      ]
        .filter((item) => item.contribution !== null && item.contribution !== undefined)
        .sort((a, b) => Math.abs(b.contribution ?? 0) - Math.abs(a.contribution ?? 0))
        .slice(0, 3)
    : [];
  const hasWarning = report.warnings.length > 0 || report.confidence === "low";

  return (
    <div className="mt-3 border-t border-omi-border-subtle pt-3">
      <div className="omi-overnight-impact flex items-start justify-between gap-4 text-xs">
        <div className="min-w-0">
          <div className="font-bold uppercase tracking-[0.14em] text-omi-text-muted">
            {t("stockDetail.dataViews.overnight.eyebrow")}
          </div>
          <div className="mt-0.5 text-sm font-bold text-omi-text-strong">
            {overnightTitle(report, t)}
          </div>
          <div className="mt-0.5 max-h-8 overflow-hidden leading-4 text-omi-text-muted">
            {overnightSummary(report, t)}
          </div>
        </div>
        <div className={`shrink-0 text-right text-sm font-bold ${valueTone(report.weighted_change_pct)}`}>
          <PriceUpdatePulse
            value={report.weighted_change_pct}
            direction={report.weighted_change_pct}
            resetKey={`${report.stock_id}:overnight:${report.as_of ?? "none"}`}
            className="justify-end tabular-nums"
          >
            {formatPct(report.weighted_change_pct)}
          </PriceUpdatePulse>
          <div className="text-xs font-medium text-omi-text-muted">
            {overnightConfidenceLabel(report.confidence, t)}
          </div>
        </div>
      </div>

      {report.adr_parity ? <AdrParityStrip parity={report.adr_parity} t={t} /> : null}

      {report.fx_flow_context ? (
        <FxFlowContextStrip context={report.fx_flow_context} t={t} />
      ) : null}

      {driverRows.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {driverRows.map((item) => (
            <span
              key={item.key}
              className="inline-flex items-center gap-1 bg-omi-surface-subtle px-2 py-1 text-xs font-semibold text-omi-text-muted"
            >
              <span>{item.label}</span>
              <span className={valueTone(item.value)}>{formatPct(item.value)}</span>
            </span>
          ))}
        </div>
      ) : null}

      {hasWarning ? (
        <div className="mt-2 text-[11px] leading-4 text-omi-warning">
          {report.as_of
            ? t("stockDetail.dataViews.overnight.dataDatePrefix", {
                date: formatDate(report.as_of),
              })
            : ""}
          {report.warnings[0]
            ? overnightWarningLabel(report.warnings[0], t)
            : t("stockDetail.dataViews.overnight.warningFallback")}
        </div>
      ) : null}
    </div>
  );
}

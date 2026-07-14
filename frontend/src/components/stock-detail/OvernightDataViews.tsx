"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import {
  formatDate,
  formatPct,
  valueTone,
} from "@/components/stock-detail/stockDetailFormatters";
import type { LoadState } from "@/components/stock-detail/stockDetailTypes";
import { useT, type TranslationFunction } from "@/i18n";
import type { OvernightImpactRead } from "@/types/market";

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

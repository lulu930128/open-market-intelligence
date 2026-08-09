"use client";

import type { LoadState } from "@/components/stock-detail/stockDetailTypes";
import {
  formatDate,
  formatPct,
  formatPrice,
} from "@/components/stock-detail/stockDetailFormatters";
import { useT, type TranslationFunction } from "@/i18n";
import type {
  TaiwanNextSessionPlanLevelRead,
  TaiwanNextSessionPlanRead,
  TaiwanNextSessionPlanStatus,
  TaiwanNextSessionScenarioZoneRead,
} from "@/types/market";

function statusTone(status: TaiwanNextSessionPlanStatus) {
  if (status === "ready") {
    return "border-omi-success-border bg-omi-success-soft text-omi-success";
  }
  if (status === "partial" || status === "pending") {
    return "border-omi-warning-border bg-omi-warning-soft text-omi-warning-strong";
  }
  if (status === "stale") {
    return "border-omi-danger-border bg-omi-danger-soft text-omi-danger";
  }
  return "border-omi-border bg-omi-surface-subtle text-omi-text-muted";
}

function levelTone(role: TaiwanNextSessionPlanLevelRead["role_at_as_of_close"]) {
  if (role === "support") {
    return {
      border: "border-omi-success-border",
      label: "text-omi-success",
    };
  }
  if (role === "reclaim") {
    return {
      border: "border-omi-warning-border",
      label: "text-omi-warning-strong",
    };
  }
  return {
    border: "border-omi-border",
    label: "text-omi-accent",
  };
}

function zoneRange(
  zone: TaiwanNextSessionScenarioZoneRead,
  t: TranslationFunction
) {
  if (zone.lower_bound === null && zone.upper_bound !== null) {
    return t("stockDetail.dataViews.nextSessionPlan.zoneBelow", {
      value: formatPrice(zone.upper_bound),
    });
  }
  if (zone.lower_bound !== null && zone.upper_bound !== null) {
    return t("stockDetail.dataViews.nextSessionPlan.zoneBetween", {
      lower: formatPrice(zone.lower_bound),
      upper: formatPrice(zone.upper_bound),
    });
  }
  if (zone.lower_bound !== null && zone.upper_bound === null) {
    return t("stockDetail.dataViews.nextSessionPlan.zoneAbove", {
      value: formatPrice(zone.lower_bound),
    });
  }
  return "-";
}

function LevelCard({
  level,
  usable,
}: {
  level: TaiwanNextSessionPlanLevelRead;
  usable: boolean;
}) {
  const t = useT();
  const tone = levelTone(level.role_at_as_of_close);
  const average = `MA${level.period}`;

  return (
    <div
      className={`border bg-omi-surface px-3 py-2.5 ${tone.border} ${usable ? "" : "opacity-60"}`}
      data-testid={`tw-next-session-level-ma${level.period}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-semibold text-omi-text-muted">
            {t("stockDetail.dataViews.nextSessionPlan.transitionLabel", {
              average,
            })}
          </div>
          <div className={`mt-0.5 text-[11px] font-semibold ${tone.label}`}>
            {t(
              `stockDetail.dataViews.nextSessionPlan.roles.${level.role_at_as_of_close}`
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-base font-bold tabular-nums text-omi-text-strong">
            {formatPrice(level.transition_price)}
          </div>
          <div className="text-[11px] tabular-nums text-omi-text-muted">
            {t("stockDetail.dataViews.nextSessionPlan.moveFromClose", {
              value: formatPct(level.move_from_as_of_close_pct),
            })}
          </div>
        </div>
      </div>
      <div className="mt-2 border-t border-omi-border-subtle pt-2 text-[11px] leading-4 text-omi-text-subtle">
        {t("stockDetail.dataViews.nextSessionPlan.flatProjection", {
          average,
          value: formatPrice(level.projected_ma_if_flat),
        })}
      </div>
    </div>
  );
}

export default function NextSessionPlanPanel({
  loadState,
  plan,
}: {
  loadState: LoadState;
  plan: TaiwanNextSessionPlanRead | null;
}) {
  const t = useT();

  if (loadState === "idle") return null;

  return (
    <section
      aria-label={t("stockDetail.dataViews.nextSessionPlan.title")}
      className="mt-3 border-t border-omi-border-subtle pt-3"
      data-decision-usable={plan?.readiness.decision_usable ?? false}
      data-testid="tw-next-session-plan"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-omi-text-muted">
            {t("stockDetail.dataViews.nextSessionPlan.eyebrow")}
          </div>
          <div className="mt-0.5 text-sm font-bold text-omi-text-strong">
            {t("stockDetail.dataViews.nextSessionPlan.title")}
          </div>
          <div className="mt-0.5 text-xs leading-4 text-omi-text-muted">
            {plan?.as_of_trade_date && plan.target_trade_date
              ? t("stockDetail.dataViews.nextSessionPlan.dateLine", {
                  asOf: formatDate(plan.as_of_trade_date),
                  target: formatDate(plan.target_trade_date),
                })
              : t("stockDetail.dataViews.nextSessionPlan.description")}
          </div>
        </div>

        {plan ? (
          <div className="shrink-0 text-right">
            <span
              className={`inline-flex border px-2 py-1 text-[11px] font-semibold ${statusTone(plan.status)}`}
              data-testid="tw-next-session-plan-status"
            >
              {t(`stockDetail.dataViews.nextSessionPlan.status.${plan.status}`)}
            </span>
            {plan.target_trade_date ? (
              <div className="mt-1 text-[11px] tabular-nums text-omi-text-subtle">
                {formatDate(plan.target_trade_date)}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {loadState === "loading" ? (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {[0, 1].map((item) => (
            <div
              key={item}
              className="omi-skeleton h-[86px] border border-omi-border-subtle bg-omi-surface-subtle"
            />
          ))}
        </div>
      ) : null}

      {loadState === "error" ? (
        <div className="mt-3 border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3 text-xs leading-5 text-omi-text-muted">
          <div className="font-semibold text-omi-text-strong">
            {t("stockDetail.dataViews.nextSessionPlan.loadUnavailableTitle")}
          </div>
          <div>{t("stockDetail.dataViews.nextSessionPlan.loadUnavailableMessage")}</div>
        </div>
      ) : null}

      {plan ? (
        <>
          {!plan.readiness.decision_usable ? (
            <div className="mt-3 border border-omi-warning-border bg-omi-warning-soft px-3 py-2 text-xs leading-4 text-omi-warning-strong">
              {t("stockDetail.dataViews.nextSessionPlan.decisionBlocked", {
                status: t(
                  `stockDetail.dataViews.nextSessionPlan.status.${plan.status}`
                ),
              })}
            </div>
          ) : null}

          {plan.levels.length ? (
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {plan.levels.map((level) => (
                <LevelCard
                  key={level.key}
                  level={level}
                  usable={plan.readiness.decision_usable}
                />
              ))}
            </div>
          ) : (
            <div className="mt-3 border border-omi-border-subtle bg-omi-surface-subtle px-3 py-3 text-xs text-omi-text-muted">
              {t("stockDetail.dataViews.nextSessionPlan.noLevels")}
            </div>
          )}

          {plan.scenario_zones.length ? (
            <div className="mt-3">
              <div className="text-[11px] font-semibold text-omi-text-muted">
                {t("stockDetail.dataViews.nextSessionPlan.zonesTitle")}
              </div>
              <div className="mt-1 grid grid-cols-1 border border-omi-border-subtle sm:grid-cols-3 sm:divide-x sm:divide-omi-border-subtle">
                {plan.scenario_zones.map((zone) => (
                  <div
                    key={zone.key}
                    className="border-t border-omi-border-subtle bg-omi-surface-subtle px-2.5 py-2 first:border-t-0 sm:border-t-0"
                    data-testid={`tw-next-session-zone-${zone.key}`}
                  >
                    <div className="text-[10px] font-semibold text-omi-text-subtle">
                      {t(
                        `stockDetail.dataViews.nextSessionPlan.zones.${zone.key}`
                      )}
                    </div>
                    <div className="mt-0.5 text-xs font-semibold tabular-nums text-omi-text-strong">
                      {zoneRange(zone, t)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="mt-2 text-[11px] leading-4 text-omi-text-subtle">
            {t("stockDetail.dataViews.nextSessionPlan.limitation")}
            {plan.readiness.missing_level_keys.length ? (
              <span className="ml-1 text-omi-warning">
                · {t("stockDetail.dataViews.nextSessionPlan.missingLevels", {
                  levels: plan.readiness.missing_level_keys
                    .map((key) => key.replace("_transition", "").toUpperCase())
                    .join("、"),
                })}
              </span>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useT } from "@/i18n";
import { fetchJson, requestJson } from "@/lib/api";
import { emitDataStatusEvent } from "@/lib/dataStatusEvents";
import type { TaiwanEtfOverviewRead } from "@/types/market";


type Props = {
  stockId: string;
  stockName: string | null;
  market: string | null;
};


function formatNumber(
  value: number | null,
  maximumFractionDigits = 2,
  minimumFractionDigits = Math.min(2, maximumFractionDigits)
) {
  if (value === null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits,
    minimumFractionDigits,
  }).format(value);
}


function formatPercent(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}%`;
}


function formatDateTime(value: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "Asia/Taipei",
  }).format(parsed);
}


function statusClass(status: string) {
  if (status === "current" || status === "closed") {
    return "border-omi-success bg-omi-success-soft text-omi-success-strong";
  }
  if (status === "stale" || status === "partial" || status === "delayed") {
    return "border-omi-warning bg-omi-warning-soft text-omi-warning-strong";
  }
  return "border-omi-border bg-omi-surface-muted text-omi-text-muted";
}


function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-l border-omi-border-subtle pl-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-omi-text-subtle">
        {label}
      </div>
      <div className="mt-1 text-base font-bold tabular-nums text-omi-text-strong">
        {value}
      </div>
    </div>
  );
}


export default function TaiwanETFDataPanel({ stockId, stockName, market }: Props) {
  const t = useT();
  const [overview, setOverview] = useState<TaiwanEtfOverviewRead | null>(null);
  const [loading, setLoading] = useState(false);
  const autoRefreshAttempted = useRef(new Set<string>());
  const contextKey = `tw:etf:${stockId}`;
  const contextLabel = `${stockId}${stockName ? ` ${stockName}` : ""}`;
  const contextLabelRef = useRef(contextLabel);
  const marketRef = useRef(market);

  useEffect(() => {
    contextLabelRef.current = contextLabel;
  }, [contextLabel]);

  useEffect(() => {
    marketRef.current = market;
  }, [market]);

  const publishFailure = useCallback(
    (title: string, error: unknown, level: "warning" | "error" = "error") => {
      emitDataStatusEvent({
        market: "tw",
        level,
        title,
        message:
          error instanceof Error
            ? error.message
            : t("stockDetail.etf.loadFailedMessage"),
        source: t("stockDetail.etf.source"),
        contextKey,
        contextLabel: contextLabelRef.current,
        dedupeKey: `${contextKey}:overview-refresh`,
      });
    },
    [contextKey, t]
  );

  const refresh = useCallback(
    async (
      signal?: AbortSignal,
      capabilities?: TaiwanEtfOverviewRead["capabilities"]
    ) => {
      setLoading(true);
      try {
        const next = await requestJson<TaiwanEtfOverviewRead>(
          `/api/market/etfs/${encodeURIComponent(stockId)}/refresh`,
          {
            method: "POST",
            body: JSON.stringify({
              refresh_profile: true,
              refresh_nav: true,
              refresh_pcf: capabilities?.pcf === true,
              refresh_inav:
                capabilities?.intraday_estimated_nav === true,
            }),
          },
          undefined,
          { signal }
        );
        setOverview(next);
        const errors = Object.entries(next.refresh?.errors ?? {});
        if (errors.length > 0) {
          publishFailure(
            t("stockDetail.etf.partialRefreshTitle"),
            new Error(errors.map(([resource, message]) => `${resource}: ${message}`).join("; ")),
            "warning"
          );
        } else if (next.warnings.length > 0) {
          publishFailure(
            t("stockDetail.etf.partialRefreshTitle"),
            new Error(next.warnings.join("; ")),
            "warning"
          );
        }
      } catch (error) {
        if (signal?.aborted) return;
        publishFailure(t("stockDetail.etf.refreshFailedTitle"), error);
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [publishFailure, stockId, t]
  );

  useEffect(() => {
    const controller = new AbortController();
    const autoRefreshAttempts = autoRefreshAttempted.current;
    let autoRefreshStarted = false;
    let autoRefreshCompleted = false;
    queueMicrotask(() => {
      if (!controller.signal.aborted) setLoading(true);
    });

    void fetchJson<TaiwanEtfOverviewRead>(
      `/api/market/etfs/${encodeURIComponent(stockId)}/overview`,
      undefined,
      { signal: controller.signal }
    )
      .then((cached) => {
        setOverview(cached);
        if (
          cached.freshness.refresh_recommended &&
          (marketRef.current ?? cached.market).toUpperCase() === "TWSE" &&
          !autoRefreshAttempts.has(stockId)
        ) {
          autoRefreshAttempts.add(stockId);
          autoRefreshStarted = true;
          return refresh(controller.signal, cached.capabilities).then(() => {
            if (!controller.signal.aborted) autoRefreshCompleted = true;
          });
        }
        return undefined;
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        publishFailure(t("stockDetail.etf.loadFailedTitle"), error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => {
      controller.abort();
      if (autoRefreshStarted && !autoRefreshCompleted) {
        autoRefreshAttempts.delete(stockId);
      }
    };
  }, [publishFailure, refresh, stockId, t]);

  const nav = overview?.daily_nav ?? null;
  const profile = overview?.profile ?? null;
  const pcf = overview?.pcf ?? null;
  const intradayNav = overview?.intraday_nav ?? null;
  const valuation = overview?.valuation ?? null;
  const strategy = overview?.strategy ?? null;
  const resourceStates = overview?.resource_states ?? {};
  const valuationStatus = valuation?.status ?? overview?.freshness.status ?? "missing";
  const pcfStatus =
    resourceStates.pcf_summary?.status ??
    overview?.freshness.pcf_status ??
    "provider_not_connected";
  const inavStatus =
    resourceStates.intraday_nav?.status ??
    overview?.freshness.inav_status ??
    "provider_not_connected";
  const componentExposureSupported =
    resourceStates.pcf_component_basket?.connector_supported ??
    overview?.capabilities.component_exposure === true;
  const inavSupported =
    resourceStates.intraday_nav?.connector_supported ??
    overview?.capabilities.intraday_estimated_nav === true;
  const componentBasketStatus =
    resourceStates.pcf_component_basket?.status ??
    ((pcf?.components.length ?? 0) > 0
      ? pcfStatus
      : componentExposureSupported
        ? "missing"
        : "provider_not_connected");
  const hasComponentBasket =
    resourceStates.pcf_component_basket?.applicable !== false &&
    (pcf?.components.length ?? 0) > 0;
  const valuationBasis = valuation?.basis ?? "daily_close";
  const canonicalNav = valuation?.nav.value ?? nav?.nav ?? null;
  const canonicalMarketPrice =
    valuation?.market_price.value ?? nav?.close_price ?? null;
  const premiumDiscount =
    valuation?.premium_discount_pct ?? nav?.premium_discount_pct ?? null;
  const valuationDate =
    valuation?.nav.as_of_date ??
    valuation?.market_price.as_of_date ??
    overview?.freshness.latest_nav_date ??
    "—";
  const benchmarkLabel =
    strategy?.benchmark_role === "performance_benchmark"
      ? t("stockDetail.etf.performanceBenchmark")
      : t("stockDetail.etf.benchmark");
  const benchmarkValue =
    strategy?.benchmark_name ??
    profile?.performance_benchmark_name ??
    profile?.benchmark_name ??
    null;
  const premiumDiscountLabel =
    premiumDiscount === null
      ? t("stockDetail.etf.premiumDiscount")
      : premiumDiscount > 0
        ? t("stockDetail.etf.premium")
        : premiumDiscount < 0
          ? t("stockDetail.etf.discount")
          : t("stockDetail.etf.flat");

  return (
    <section
      role="tabpanel"
      data-testid="tw-etf-data-panel"
      className="bg-omi-surface"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-omi-border-subtle px-5 py-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="border border-omi-accent px-2 py-0.5 text-[11px] font-bold uppercase tracking-[0.14em] text-omi-accent">
              ETF
            </span>
            <span className={`border px-2 py-0.5 text-[11px] font-semibold ${statusClass(valuationStatus)}`}>
              {t(`stockDetail.etf.status.${valuationStatus}`)}
            </span>
          </div>
          <h2 className="mt-2 text-lg font-bold text-omi-text-strong">
            {t("stockDetail.etf.title")}
          </h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-omi-text-muted">
            {valuationBasis === "intraday"
              ? t("stockDetail.etf.intradayValuationNote", {
                  time: formatDateTime(
                    valuation?.nav.observed_at ??
                      valuation?.market_price.observed_at ??
                      null
                  ),
                })
              : t("stockDetail.etf.dailyCloseNote", {
                  date: valuationDate,
                  time: overview?.freshness.nav_release_time ?? "21:00",
                })}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh(undefined, overview?.capabilities)}
          disabled={loading}
          className="h-8 border border-omi-border bg-omi-surface px-3 text-xs font-semibold text-omi-text-muted hover:border-omi-accent hover:text-omi-accent disabled:cursor-wait disabled:text-omi-text-subtle"
        >
          {loading
            ? t("stockDetail.etf.refreshing")
            : t("stockDetail.etf.refresh")}
        </button>
      </div>

      <div className="space-y-5 px-5 py-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Metric
            label={
              valuationBasis === "intraday"
                ? t("stockDetail.etf.estimatedNav")
                : t("stockDetail.etf.nav")
            }
            value={formatNumber(canonicalNav, 4, 4)}
          />
          <Metric
            label={
              valuationBasis === "intraday"
                ? t("stockDetail.etf.inavMarketPrice")
                : t("stockDetail.etf.closePrice")
            }
            value={formatNumber(canonicalMarketPrice)}
          />
          <Metric label={premiumDiscountLabel} value={formatPercent(premiumDiscount)} />
          <Metric
            label={t("stockDetail.etf.valuationBasis")}
            value={t(`stockDetail.etf.basis.${valuationBasis}`)}
          />
        </div>

        {inavSupported ? (
          <div className="border-t border-omi-border-subtle pt-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
                  {t("stockDetail.etf.inavTitle")}
                </div>
                <div className="mt-1 text-xs text-omi-text-subtle">
                  {t("stockDetail.etf.inavObservedAt", {
                    time: formatDateTime(intradayNav?.observed_at ?? null),
                  })}
                </div>
              </div>
              <span className={`border px-2 py-1 text-[11px] font-semibold ${statusClass(inavStatus)}`}>
                {t(`stockDetail.etf.resourceStatus.${inavStatus}`)}
              </span>
            </div>
            {intradayNav ? (
              <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
                <Metric
                  label={t("stockDetail.etf.estimatedNav")}
                  value={formatNumber(intradayNav.estimated_nav, 4, 4)}
                />
                <Metric
                  label={t("stockDetail.etf.inavMarketPrice")}
                  value={formatNumber(intradayNav.market_price)}
                />
                <Metric
                  label={t("stockDetail.etf.inavPremiumDiscount")}
                  value={formatPercent(intradayNav.premium_discount_pct)}
                />
                <Metric
                  label={t("stockDetail.etf.inavChange")}
                  value={formatNumber(intradayNav.nav_change)}
                />
              </div>
            ) : (
              <div className="mt-3 border border-dashed border-omi-border px-4 py-4 text-sm text-omi-text-muted">
                {t("stockDetail.etf.inavEmpty")}
              </div>
            )}
          </div>
        ) : null}

        {!profile && !nav ? (
          <div className="border border-dashed border-omi-border px-4 py-5 text-sm text-omi-text-muted">
            {t("stockDetail.etf.empty")}
          </div>
        ) : null}

        {profile ? (
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
              {t("stockDetail.etf.profile")}
            </div>
            <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 text-sm md:grid-cols-2 xl:grid-cols-3">
              {[
                [t("stockDetail.etf.fundType"), profile.fund_type],
                [benchmarkLabel, benchmarkValue],
                [t("stockDetail.etf.issuer"), profile.issuer_name],
                [t("stockDetail.etf.manager"), profile.fund_manager],
                [t("stockDetail.etf.listedDate"), profile.listed_date],
                [t("stockDetail.etf.custodian"), profile.custodian],
                [
                  t("stockDetail.etf.issuedUnits"),
                  profile.issued_units === null
                    ? null
                    : new Intl.NumberFormat().format(profile.issued_units),
                ],
                [
                  t("stockDetail.etf.foreignComponents"),
                  profile.has_foreign_components === null
                    ? null
                    : profile.has_foreign_components
                      ? t("stockDetail.etf.yes")
                      : t("stockDetail.etf.no"),
                ],
              ].map(([label, value]) => (
                <div key={label} className="border-b border-omi-border-subtle pb-2">
                  <dt className="text-xs text-omi-text-subtle">{label}</dt>
                  <dd className="mt-1 text-omi-text-strong">{value || "—"}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}

        <div className="border-t border-omi-border-subtle pt-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-omi-text-muted">
                  {t("stockDetail.etf.pcfTitle")}
                </div>
                <div className="mt-1 text-xs text-omi-text-subtle">
                  {t("stockDetail.etf.pcfDateNote", {
                    effectiveDate:
                      pcf?.effective_date ??
                      overview?.freshness.expected_pcf_date ??
                      "—",
                    referenceDate: pcf?.reference_date ?? "—",
                  })}
                </div>
              </div>
              <span className={`border px-2 py-1 text-[11px] font-semibold ${statusClass(pcfStatus)}`}>
                {t(`stockDetail.etf.resourceStatus.${pcfStatus}`)}
              </span>
            </div>

            {pcf ? (
              <>
                <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
                  {(resourceStates.pcf_component_basket?.applicable ??
                    componentExposureSupported) === true ? (
                    <Metric
                      label={t("stockDetail.etf.componentCount")}
                      value={formatNumber(pcf.component_count, 0, 0)}
                    />
                  ) : null}
                  <Metric
                    label={t("stockDetail.etf.creationUnit")}
                    value={formatNumber(pcf.creation_unit, 0, 0)}
                  />
                  <Metric
                    label={t("stockDetail.etf.pcfUnitNav")}
                    value={formatNumber(pcf.unit_nav, 4, 2)}
                  />
                  <Metric
                    label={t("stockDetail.etf.estimatedCashComponent")}
                    value={formatNumber(pcf.estimated_cash_component, 2, 0)}
                  />
                </div>

                {hasComponentBasket ? (
                  <div className="mt-4 max-h-80 overflow-auto border border-omi-border-subtle">
                    <table className="min-w-[720px] w-full border-collapse text-left text-xs">
                    <thead className="sticky top-0 bg-omi-surface-muted text-omi-text-subtle">
                      <tr>
                        <th className="px-3 py-2 font-semibold">{t("stockDetail.etf.componentType")}</th>
                        <th className="px-3 py-2 font-semibold">{t("stockDetail.etf.componentSymbol")}</th>
                        <th className="px-3 py-2 font-semibold">{t("stockDetail.etf.componentName")}</th>
                        <th className="px-3 py-2 text-right font-semibold">{t("stockDetail.etf.componentQuantity")}</th>
                        <th className="px-3 py-2 text-right font-semibold">{t("stockDetail.etf.componentWeight")}</th>
                        <th className="px-3 py-2 text-center font-semibold">{t("stockDetail.etf.cashInLieu")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pcf.components.map((component) => (
                        <tr
                          key={`${component.source_section}:${component.symbol}:${component.order_index}`}
                          className="border-t border-omi-border-subtle text-omi-text-muted"
                        >
                          <td className="whitespace-nowrap px-3 py-2">
                            {t(`stockDetail.etf.assetType.${component.asset_type}`)}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 font-semibold tabular-nums text-omi-text-strong">
                            {component.symbol}
                            {component.contract_month ? ` · ${component.contract_month}` : ""}
                          </td>
                          <td className="px-3 py-2 text-omi-text-strong">
                            {component.name || component.name_en || "—"}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                            {formatNumber(component.quantity, 4, 0)}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                            {formatPercent(component.weight_pct)}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2 text-center">
                            {component.cash_in_lieu || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="mt-4 border border-dashed border-omi-border px-4 py-4 text-sm text-omi-text-muted">
                    {componentBasketStatus === "not_applicable"
                      ? t("stockDetail.etf.componentBasketNotApplicable")
                      : componentBasketStatus === "provider_not_connected"
                        ? t("stockDetail.etf.componentBasketProviderNotConnected")
                        : componentExposureSupported
                          ? t("stockDetail.etf.componentExposureEmpty")
                          : t("stockDetail.etf.pcfSummaryOnly")}
                  </div>
                )}
              </>
            ) : (
              <div className="mt-3 border border-dashed border-omi-border px-4 py-4 text-sm text-omi-text-muted">
                {pcfStatus === "provider_not_connected"
                  ? t("stockDetail.etf.pcfProviderNotConnected")
                  : t("stockDetail.etf.pcfEmpty")}
              </div>
            )}
          </div>

        <div className="flex flex-wrap gap-2 border-t border-omi-border-subtle pt-4 text-xs">
          {[
            {
              key: "daily_nav",
              status:
                resourceStates.daily_nav?.status ??
                (canonicalNav === null ? "missing" : valuationStatus),
            },
            { key: "intraday_nav", status: inavStatus },
            { key: "pcf_summary", status: pcfStatus },
            { key: "pcf_component_basket", status: componentBasketStatus },
            {
              key: "fund_holdings",
              status:
                resourceStates.fund_holdings?.status ??
                "provider_not_connected",
            },
          ].map((resource) => (
            <span
              key={resource.key}
              className={`border px-2 py-1 ${statusClass(resource.status)}`}
            >
              {t(`stockDetail.etf.resource.${resource.key}`)} ·{" "}
              {t(`stockDetail.etf.resourceStatus.${resource.status}`)}
            </span>
          ))}
        </div>

        <div className="text-[11px] leading-5 text-omi-text-subtle">
          {t("stockDetail.etf.sourceFootnote")}
        </div>
      </div>
    </section>
  );
}

"use client";

import { useT, type TranslationFunction } from "@/i18n";
import type { TaiwanFinancialContractRead } from "@/types/market";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

type EarningsDataGuideDialogProps = {
  contract: TaiwanFinancialContractRead | null;
  financialContractReady: boolean;
  onClose: () => void;
};

const sourceReferenceDetailKeys = [
  "source_reliability",
  "source_id",
  "raw_result_id",
  "filing_id",
  "parse_run_id",
  "row_id",
] as const;

function displayValue(value: unknown) {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function formatFinancialNumber(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return "-";
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 2,
  }).format(parsed);
}

function translatedStatus(
  t: TranslationFunction,
  value: string | null | undefined
) {
  if (!value) return "-";
  const key = `stockDetail.dataPanel.earningsGuide.statuses.${value}`;
  const translated = t(key);
  return translated === key ? value : translated;
}

function statusTone(value: string | null | undefined) {
  if (["ready", "current", "complete", "valid"].includes(value ?? "")) {
    return "text-omi-success-strong";
  }
  if (
    ["blocked", "partial", "missing", "stale", "disputed", "unknown"].includes(
      value ?? ""
    )
  ) {
    return "text-omi-warning-strong";
  }
  return "text-omi-text-strong";
}

function sourceReferenceName(
  sourceReference: Record<string, unknown>,
  index: number,
  t: TranslationFunction
) {
  return (
    displayValue(sourceReference.source_name) ??
    displayValue(sourceReference.name) ??
    displayValue(sourceReference.type) ??
    t("stockDetail.dataPanel.earningsGuide.sourceFallback", {
      number: index + 1,
    })
  );
}

function sourceReferenceDetails(sourceReference: Record<string, unknown>) {
  return sourceReferenceDetailKeys
    .map((key) => {
      const value = displayValue(sourceReference[key]);
      return value ? `${key}: ${value}` : null;
    })
    .filter((value): value is string => Boolean(value));
}

export default function EarningsDataGuideDialog({
  contract,
  financialContractReady,
  onClose,
}: EarningsDataGuideDialogProps) {
  const t = useT();
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
        )
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [onClose]);

  const qualityRows = contract
    ? [
        {
          label: t("stockDetail.dataPanel.earningsGuide.freshness"),
          value: contract.quality.freshness,
        },
        {
          label: t("stockDetail.dataPanel.earningsGuide.continuity"),
          value: contract.quality.continuity,
        },
        {
          label: t("stockDetail.dataPanel.earningsGuide.semanticValidity"),
          value: contract.quality.semantic_validity,
        },
      ]
    : [];
  const sourceReferences = contract?.source_refs ?? [];
  const ttmPeriods = contract?.derived.ttm_periods?.join(" · ") ?? "-";
  const missingRevenuePeriods =
    contract?.quality.revenue_continuity.missing_periods ?? [];

  return createPortal(
    <div
      className="fixed inset-0 z-[2147483646] flex items-center justify-center bg-omi-overlay p-4"
      data-testid="earnings-data-guide-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="earnings-data-guide-title"
        aria-describedby="earnings-data-guide-description"
        className="flex h-[720px] max-h-[calc(100dvh-2rem)] w-[920px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden border border-omi-control-border bg-omi-surface shadow-2xl"
        data-testid="earnings-data-guide-dialog"
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
          <div className="min-w-0">
            <div className="text-xs font-bold uppercase tracking-[0.22em] text-omi-accent">
              Earnings data
            </div>
            <h2
              id="earnings-data-guide-title"
              className="mt-1 text-xl font-black tracking-tight text-omi-text-strong"
            >
              {t("stockDetail.dataPanel.earningsGuide.title")}
            </h2>
            <p
              id="earnings-data-guide-description"
              className="mt-2 max-w-[720px] text-sm leading-6 text-omi-text-muted"
            >
              {t("stockDetail.dataPanel.earningsGuide.description")}
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label={t("stockDetail.dataPanel.earningsGuide.close")}
            className="grid h-8 w-8 shrink-0 place-items-center border border-omi-border text-xl text-omi-text-muted transition-colors duration-200 hover:border-omi-control hover:text-omi-text-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-omi-accent active:translate-y-px"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto overscroll-contain p-5">
          <section
            className={[
              "border px-4 py-3",
              financialContractReady
                ? "border-omi-success-border bg-omi-success-soft"
                : "border-omi-warning-border bg-omi-warning-soft",
            ].join(" ")}
            aria-labelledby="earnings-contract-status-title"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-muted">
                  {t("stockDetail.dataPanel.earningsGuide.contractStatus")}
                </div>
                <h3
                  id="earnings-contract-status-title"
                  className={[
                    "mt-1 text-base font-black",
                    financialContractReady
                      ? "text-omi-success-strong"
                      : "text-omi-warning-strong",
                  ].join(" ")}
                >
                  {t(
                    financialContractReady
                      ? "stockDetail.dataPanel.earningsGuide.ready"
                      : contract
                        ? "stockDetail.dataPanel.earningsGuide.attention"
                        : "stockDetail.dataPanel.earningsGuide.missing"
                  )}
                </h3>
              </div>
              {contract ? (
                <span className="border border-current px-2 py-1 font-mono text-[11px] font-semibold text-omi-text-muted">
                  {contract.contract_version}
                </span>
              ) : null}
            </div>
            <p className="mt-2 max-w-[760px] text-sm leading-6 text-omi-text-strong">
              {contract
                ? financialContractReady
                  ? t("stockDetail.dataPanel.financialContractReady", {
                      version: contract.contract_version,
                    })
                  : t("stockDetail.dataPanel.financialContractBlocked", {
                      version: contract.contract_version,
                      status:
                        contract.normalized.status ??
                        contract.derived.status ??
                        "blocked",
                    })
                : t("stockDetail.dataPanel.earningsGuide.missingDescription")}
            </p>
          </section>

          <section aria-labelledby="earnings-method-title">
            <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-muted">
              {t("stockDetail.dataPanel.earningsGuide.methodEyebrow")}
            </div>
            <h3
              id="earnings-method-title"
              className="mt-1 text-lg font-black tracking-tight text-omi-text-strong"
            >
              {t("stockDetail.dataPanel.earningsGuide.methodTitle")}
            </h3>
            <div className="mt-3 grid gap-px overflow-hidden border border-omi-border-subtle bg-omi-border-subtle md:grid-cols-3">
              {[
                {
                  step: "01",
                  title: t("stockDetail.dataPanel.earningsGuide.reportedTitle"),
                  body: t("stockDetail.dataPanel.earningsSemanticsWarning"),
                },
                {
                  step: "02",
                  title: t("stockDetail.dataPanel.earningsGuide.normalizedTitle"),
                  body: t("stockDetail.dataPanel.earningsGuide.normalizedBody"),
                },
                {
                  step: "03",
                  title: t("stockDetail.dataPanel.earningsGuide.derivedTitle"),
                  body: t("stockDetail.dataPanel.earningsGuide.derivedBody"),
                },
              ].map((item) => (
                <article key={item.step} className="bg-omi-surface-subtle px-4 py-4">
                  <div className="font-mono text-[11px] font-bold text-omi-accent">
                    {item.step}
                  </div>
                  <h4 className="mt-2 text-sm font-black text-omi-text-strong">
                    {item.title}
                  </h4>
                  <p className="mt-2 text-xs leading-5 text-omi-text-muted">
                    {item.body}
                  </p>
                </article>
              ))}
            </div>
          </section>

          <section
            className="grid gap-5 lg:grid-cols-[1.35fr_1fr]"
            aria-label={t("stockDetail.dataPanel.earningsGuide.contractDetails")}
          >
            <article className="border border-omi-border-subtle">
              <div className="border-b border-omi-border-subtle bg-omi-surface-subtle px-4 py-3">
                <h3 className="text-sm font-black text-omi-text-strong">
                  {t("stockDetail.dataPanel.earningsGuide.basisTitle")}
                </h3>
              </div>
              <dl className="divide-y divide-omi-border-subtle text-xs">
                {[
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.asOf"),
                    value: formatDateTime(contract?.as_of),
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.mode"),
                    value: contract?.mode ?? "-",
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.comparisonBasis"),
                    value: contract?.normalized.comparison_basis_id ?? "-",
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.normalizationVersion"),
                    value: contract?.normalized.normalization_version ?? "-",
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.ttmPeriods"),
                    value: ttmPeriods,
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.valuationStatus"),
                    value: translatedStatus(t, contract?.valuation.status),
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.valuationPrice"),
                    value: formatFinancialNumber(contract?.valuation.price),
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.valuationTradeDate"),
                    value: contract?.valuation.price_trade_date ?? "-",
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.valuationBasis"),
                    value: contract?.valuation.price_basis ?? "-",
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.valuationAsOf"),
                    value: formatDateTime(contract?.valuation.price_as_of),
                  },
                  {
                    label: t("stockDetail.dataPanel.earningsGuide.valuationSource"),
                    value: contract?.valuation.price_source ?? "-",
                  },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="grid gap-1 px-4 py-2.5 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4"
                  >
                    <dt className="font-semibold text-omi-text-muted">{item.label}</dt>
                    <dd className="break-all font-mono text-omi-text-strong">
                      {item.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </article>

            <article className="border border-omi-border-subtle">
              <div className="border-b border-omi-border-subtle bg-omi-surface-subtle px-4 py-3">
                <h3 className="text-sm font-black text-omi-text-strong">
                  {t("stockDetail.dataPanel.earningsGuide.qualityTitle")}
                </h3>
              </div>
              <div className="space-y-4 p-4">
                <dl className="grid grid-cols-3 gap-2 text-xs">
                  {qualityRows.map((item) => (
                    <div key={item.label} className="min-w-0 bg-omi-surface-subtle px-3 py-2">
                      <dt className="text-[11px] font-semibold text-omi-text-muted">
                        {item.label}
                      </dt>
                      <dd
                        className={`mt-1 truncate font-mono font-semibold ${statusTone(
                          item.value
                        )}`}
                        title={item.value}
                      >
                        {translatedStatus(t, item.value)}
                      </dd>
                    </div>
                  ))}
                </dl>
                <div>
                  <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-omi-text-muted">
                    {t("stockDetail.dataPanel.earningsGuide.issues")}
                  </div>
                  {contract?.quality.issues.length ? (
                    <ul className="mt-2 space-y-1.5">
                      {contract.quality.issues.map((issue) => (
                        <li
                          key={issue}
                          className="break-all border-l-2 border-omi-warning-border pl-2 font-mono text-xs leading-5 text-omi-warning-strong"
                        >
                          {issue}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs leading-5 text-omi-text-muted">
                      {t("stockDetail.dataPanel.earningsGuide.noIssues")}
                    </p>
                  )}
                  {missingRevenuePeriods.length ? (
                    <p className="mt-3 border-l-2 border-omi-warning-border pl-2 text-xs leading-5 text-omi-warning-strong">
                      {t("stockDetail.dataPanel.revenueContinuityWarning", {
                        periods: missingRevenuePeriods.join(", "),
                      })}
                    </p>
                  ) : null}
                </div>
              </div>
            </article>
          </section>

          {sourceReferences.length ? (
            <section aria-labelledby="earnings-sources-title">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <div className="text-[11px] font-bold uppercase tracking-[0.18em] text-omi-text-muted">
                    {t("stockDetail.dataPanel.earningsGuide.sourcesEyebrow")}
                  </div>
                  <h3
                    id="earnings-sources-title"
                    className="mt-1 text-lg font-black tracking-tight text-omi-text-strong"
                  >
                    {t("stockDetail.dataPanel.earningsGuide.sourcesTitle")}
                  </h3>
                </div>
                <span className="text-xs font-semibold text-omi-text-muted">
                  {t("stockDetail.dataPanel.earningsGuide.sourceCount", {
                    count: sourceReferences.length,
                  })}
                </span>
              </div>
              <div className="mt-3 overflow-hidden border border-omi-border-subtle">
                {sourceReferences.map((sourceReference, index) => {
                  const details = sourceReferenceDetails(sourceReference);
                  return (
                    <article
                      key={`${sourceReferenceName(sourceReference, index, t)}:${index}`}
                      className="grid gap-1 border-t border-omi-border-subtle px-4 py-3 text-xs first:border-t-0 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-4"
                    >
                      <div className="font-semibold text-omi-text-strong">
                        {sourceReferenceName(sourceReference, index, t)}
                      </div>
                      <div className="break-all font-mono leading-5 text-omi-text-muted">
                        {details.length
                          ? details.join(" · ")
                          : t("stockDetail.dataPanel.earningsGuide.sourceRecorded")}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}
        </div>

        <footer className="shrink-0 border-t border-omi-border-subtle bg-omi-surface-subtle px-5 py-3 text-xs leading-5 text-omi-text-muted">
          {t("stockDetail.dataPanel.earningsGuide.footer")}
        </footer>
      </section>
    </div>,
    document.body
  );
}

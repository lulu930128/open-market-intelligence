import type { TranslationFunction, TranslationValues } from "@/i18n";
import { getJobResultStatus } from "@/lib/jobs";
import type { JobRunRead } from "@/types/market";
import type { InstitutionalSeriesPoint } from "@/components/stock-detail/stockDetailTypes";

export function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

export function formatSignedPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatPrice(value)}`;
}

export function formatSignedPointChange(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";

  return `${sign}${value.toLocaleString("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value));
}

export function formatTradeValueYi(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return (value / 100_000_000).toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

export function formatSignedTradeValueYi(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";

  return `${sign}${formatTradeValueYi(value)}`;
}

export function formatSignedContracts(value: number | null | undefined, unit = "口") {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value)}${unit}`;
}

export function formatContributionPoint(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(4)}`;
}

export function formatSignedNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value)}`;
}

export function formatLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value / 1000));
}

export function formatSignedLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatLots(value)}`;
}

export function formatLotUnits(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value));
}

export function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatIndicatorValue(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatRatioPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${value.toFixed(2)}%`;
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";

  const date = new Date(value);

  if (Number.isNaN(date.getTime()) || !value.includes("T")) return value;

  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Taipei",
    })
      .formatToParts(date)
      .map((part) => [part.type, part.value])
  );

  return `${parts.year}/${parts.month}/${parts.day} ${parts.hour}:${parts.minute}`;
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 10);
}

export function shiftIsoDate(value: string, days: number) {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);

  if (!year || !month || !day) return value.slice(0, 10);

  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function readBackfillCount(result: unknown, key: string) {
  if (!isRecord(result)) return null;

  const value = result[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function optionalTranslation(
  t: TranslationFunction | undefined,
  key: string,
  fallback: string,
  values?: TranslationValues
) {
  if (t) return t(key, values);

  if (!values) return fallback;

  return fallback.replace(/\{(\w+)\}/g, (match, valueKey) => {
    const value = values[valueKey];
    return value === null || value === undefined ? match : String(value);
  });
}

export function formatPanelJobProgress(
  label: string,
  job: JobRunRead,
  t?: TranslationFunction
) {
  const total = Math.max(job.progress_total || 1, 1);
  const current = Math.min(Math.max(job.progress_current || 0, 0), total);
  const status = getJobResultStatus(job) ?? job.status;

  if (status === "error") {
    return optionalTranslation(
      t,
      "stockDetail.jobs.progress.error",
      "{label}: backfill failed; see Update status on the left",
      { label }
    );
  }

  if (status === "partial_success") {
    return optionalTranslation(
      t,
      "stockDetail.jobs.progress.partial",
      "{label}: partially complete; see Update status on the left",
      { label }
    );
  }

  if (status === "success") {
    return optionalTranslation(
      t,
      "stockDetail.jobs.progress.success",
      "{label}: backfill complete; see Update status on the left",
      { label }
    );
  }

  return optionalTranslation(
    t,
    "stockDetail.jobs.progress.running",
    "{label}: backfilling {current}/{total}; see Update status on the left",
    { label, current, total }
  );
}

export function formatBackfillOutcome(
  job: JobRunRead,
  label: string,
  t?: TranslationFunction
) {
  const status = getJobResultStatus(job);
  const insertedCount =
    readBackfillCount(job.result, "inserted_count") ??
    readBackfillCount(job.result, "refreshed_count");
  const skippedCount =
    readBackfillCount(job.result, "skipped_existing_count") ??
    readBackfillCount(job.result, "skipped_count");
  const errorCount = readBackfillCount(job.result, "error_count");
  const details = [
    insertedCount !== null && insertedCount > 0
      ? optionalTranslation(
          t,
          "stockDetail.jobs.outcomeDetails.updated",
          "Updated {count}",
          { count: insertedCount }
        )
      : null,
    skippedCount !== null && skippedCount > 0
      ? optionalTranslation(
          t,
          "stockDetail.jobs.outcomeDetails.existing",
          "Existing {count}",
          { count: skippedCount }
        )
      : null,
    errorCount !== null && errorCount > 0
      ? optionalTranslation(
          t,
          "stockDetail.jobs.outcomeDetails.failed",
          "Failed {count}",
          { count: errorCount }
        )
      : null,
  ].filter(Boolean);
  const suffix =
    status === "partial_success"
      ? optionalTranslation(t, "stockDetail.jobs.outcome.partial", "Partially complete")
      : status === "skipped"
        ? optionalTranslation(t, "stockDetail.jobs.outcome.skipped", "No backfill needed")
        : status === "error"
          ? optionalTranslation(t, "stockDetail.jobs.outcome.error", "Failed")
          : optionalTranslation(t, "stockDetail.jobs.outcome.success", "Backfill complete");

  return optionalTranslation(
    t,
    "stockDetail.jobs.outcome.message",
    "{label}{suffix}{details}",
    {
      label,
      suffix,
      details: details.length
        ? optionalTranslation(
            t,
            "stockDetail.jobs.outcome.detailWrap",
            " ({details})",
            {
              details: details.join(
                optionalTranslation(
                  t,
                  "stockDetail.jobs.outcome.detailSeparator",
                  ", "
                )
              ),
            }
          )
        : "",
    }
  );
}

export function formatMonth(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(0, 7);
}

export function toRevenueYi(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return value / 100000;
}

export function formatRevenueYiValue(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatCompactDate(value: string | null | undefined) {
  if (!value) return "-";
  const digits = value.replace(/\D/g, "");
  if (digits.length >= 8) return digits.slice(0, 8);
  return value;
}

export function formatPeriodLabel(value: string | null | undefined) {
  return formatMonth(value);
}

export function formatMonthDay(value: string | null | undefined) {
  if (!value) return "-";
  return value.slice(5, 10).replace("-", "/");
}

export function addMonthsToDateText(value: string, months: number) {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCMonth(date.getUTCMonth() + months);
  return date.toISOString().slice(0, 10);
}

export function rebuildInstitutionalCumulative(points: InstitutionalSeriesPoint[]) {
  return points.reduce<{
    rows: InstitutionalSeriesPoint[];
    foreignCumulative: number;
    investmentTrustCumulative: number;
    dealerCumulative: number;
    totalCumulative: number;
  }>(
    (accumulator, point) => {
      const nextForeignCumulative = accumulator.foreignCumulative + (point.foreignNet ?? 0);
      const nextInvestmentTrustCumulative =
        accumulator.investmentTrustCumulative + (point.investmentTrustNet ?? 0);
      const nextDealerCumulative = accumulator.dealerCumulative + (point.dealerNet ?? 0);
      const nextTotalCumulative = accumulator.totalCumulative + (point.totalNet ?? 0);

      return {
        rows: [
          ...accumulator.rows,
          {
            ...point,
            foreignCumulative: nextForeignCumulative,
            investmentTrustCumulative: nextInvestmentTrustCumulative,
            dealerCumulative: nextDealerCumulative,
            totalCumulative: nextTotalCumulative,
          },
        ],
        foreignCumulative: nextForeignCumulative,
        investmentTrustCumulative: nextInvestmentTrustCumulative,
        dealerCumulative: nextDealerCumulative,
        totalCumulative: nextTotalCumulative,
      };
    },
    {
      rows: [],
      foreignCumulative: 0,
      investmentTrustCumulative: 0,
      dealerCumulative: 0,
      totalCumulative: 0,
    }
  ).rows;
}

export function valueTone(value: number | null | undefined) {
  if (value === null || value === undefined) return "text-omi-text-muted";
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text";
}

export type PriceLimitStatus = "limit_up" | "limit_down" | null;

export function estimatedPriceLimitStatus(value: number | null | undefined): PriceLimitStatus {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  if (value >= 9.5) return "limit_up";
  if (value <= -9.5) return "limit_down";
  return null;
}

export function priceLimitTone(status: PriceLimitStatus, fallback: number | null | undefined) {
  if (status === "limit_up") return "text-omi-market-up";
  if (status === "limit_down") return "text-omi-market-down";
  return valueTone(fallback);
}

export function priceLimitBoxClass(status: PriceLimitStatus) {
  if (status === "limit_up") {
    return "omi-price-limit-value omi-price-limit-up";
  }

  if (status === "limit_down") {
    return "omi-price-limit-value omi-price-limit-down";
  }

  return "";
}

export function safeRatio(numerator: number | null | undefined, denominator: number | null | undefined) {
  if (
    numerator === null ||
    numerator === undefined ||
    denominator === null ||
    denominator === undefined ||
    denominator === 0
  ) {
    return null;
  }

  return numerator / denominator;
}

export function finiteNumber(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

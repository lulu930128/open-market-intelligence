"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import {
  useT,
  type TranslationFunction,
  type TranslationValues,
} from "@/i18n";
import { fetchJson } from "@/lib/api";
import { getJobResultStatus } from "@/lib/jobs";
import { omiChartColors } from "@/lib/themeColors";
import {
  TAIWAN_SESSION_START_MINUTES,
  getTaipeiMinutesOfDay,
  isTaiwanRegularSessionPoint,
} from "@/lib/taiwanMarketTime";
import type { TaiwanDataPanelTab } from "@/lib/taiwanMarketRules";
import type {
  ChartPoint,
  FinancialMetricQuarterlyRead,
  IntradayTrendPoint,
  InstitutionalTradeDailyRead,
  JobRunRead,
  MarketChipDaily,
  MarketIndexContributionItem,
  MarketIndexContributionResponse,
  MarketIndexListItem,
  MarketIndexSnapshot,
  MonthlyRevenueRead,
  OvernightImpactRead,
  ShareholdingDistributionWeeklyRead,
  StockTechnicalReportRead,
} from "@/types/market";
import { type MouseEvent as ReactMouseEvent, type ReactNode, useState } from "react";
export type Timeframe = "today" | "daily" | "weekly" | "monthly";
export type ChartTimeframe = Exclude<Timeframe, "today">;
export type ProfessionalIntradayTimeframe = "1m" | "5m" | "15m" | "30m" | "1h" | "4h";
export type ProfessionalTimeframe = ProfessionalIntradayTimeframe | ChartTimeframe;
export type LoadState = "idle" | "loading" | "success" | "error";
export type DataPanelTab = TaiwanDataPanelTab;
export type BranchTableSide = "buy" | "sell";
export type RevenueView = "monthly" | "quarterly" | "yearly";
export type EarningsView = "quarterly" | "yearly";
export const professionalIntradayMinutes: Record<ProfessionalIntradayTimeframe, number> = {
  "1m": 1,
  "5m": 5,
  "15m": 15,
  "30m": 30,
  "1h": 60,
  "4h": 240,
};

export type ShareholdingSeriesPoint = {
  date: string;
  largeRatio: number | null;
  largeRatioChange: number | null;
  largeHolders: number | null;
  smallRatio: number | null;
  close: number | null;
};
export type InstitutionalSeriesPoint = {
  date: string;
  foreignNet: number | null;
  investmentTrustNet: number | null;
  dealerNet: number | null;
  totalNet: number | null;
  foreignCumulative: number | null;
  investmentTrustCumulative: number | null;
  dealerCumulative: number | null;
  totalCumulative: number | null;
};
export type InstitutionalNetKey = "foreignNet" | "investmentTrustNet" | "dealerNet";
export type InstitutionalCumulativeKey =
  | "foreignCumulative"
  | "investmentTrustCumulative"
  | "dealerCumulative";
export type RevenueSeriesPoint = {
  period: string;
  label: string;
  year: number;
  revenue: number | null;
  previousRevenue: number | null;
  growthPct: number | null;
  cumulativeRevenue: number | null;
  cumulativeGrowthPct: number | null;
  monthCount: number;
};
export type EarningsSeriesPoint = {
  period: string;
  label: string;
  fiscalYear: number;
  quarter: number | null;
  eps: number | null;
  previousEps: number | null;
  growthPct: number | null;
  roe: number | null;
  roa: number | null;
  periodCount: number;
};

export const shareholdingLevelRanges: Record<number, { minLots: number; maxLots: number | null }> = {
  1: { minLots: 0, maxLots: 1 },
  2: { minLots: 1, maxLots: 5 },
  3: { minLots: 5, maxLots: 10 },
  4: { minLots: 10, maxLots: 15 },
  5: { minLots: 15, maxLots: 20 },
  6: { minLots: 20, maxLots: 30 },
  7: { minLots: 30, maxLots: 40 },
  8: { minLots: 40, maxLots: 50 },
  9: { minLots: 50, maxLots: 100 },
  10: { minLots: 100, maxLots: 200 },
  11: { minLots: 200, maxLots: 400 },
  12: { minLots: 400, maxLots: 600 },
  13: { minLots: 600, maxLots: 800 },
  14: { minLots: 800, maxLots: 1000 },
  15: { minLots: 1000, maxLots: null },
};

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

export function isProfessionalIntradayTimeframe(
  value: ProfessionalTimeframe
): value is ProfessionalIntradayTimeframe {
  return value in professionalIntradayMinutes;
}

export function intradayTimeMs(value: string) {
  const date = new Date(value);
  const timestamp = date.getTime();

  return Number.isNaN(timestamp) ? 0 : timestamp;
}

export function aggregateProfessionalIntradayBars(
  points: IntradayTrendPoint[],
  intervalMinutes: number
): ChartPoint[] {
  const buckets = new Map<number, IntradayTrendPoint[]>();

  points
    .filter((point) => finiteNumber(point.price) && isTaiwanRegularSessionPoint(point.time))
    .slice()
    .sort((left, right) => intradayTimeMs(left.time) - intradayTimeMs(right.time))
    .forEach((point) => {
      const minutes = getTaipeiMinutesOfDay(point.time);

      if (minutes === null) return;

      const bucket =
        TAIWAN_SESSION_START_MINUTES +
        Math.floor((minutes - TAIWAN_SESSION_START_MINUTES) / intervalMinutes) *
          intervalMinutes;
      const current = buckets.get(bucket) ?? [];

      current.push(point);
      buckets.set(bucket, current);
    });

  return Array.from(buckets.entries())
    .sort(([left], [right]) => left - right)
    .map(([, bucketPoints]) => {
      const first = bucketPoints[0];
      const last = bucketPoints[bucketPoints.length - 1];
      const highs = bucketPoints.map((point) => point.high ?? point.price).filter(finiteNumber);
      const lows = bucketPoints.map((point) => point.low ?? point.price).filter(finiteNumber);
      const volume = bucketPoints.reduce((total, point) => {
        return total + (finiteNumber(point.volume) && point.volume > 0 ? point.volume : 0);
      }, 0);

      return {
        time: first.time,
        open: first.open ?? first.price,
        high: highs.length ? Math.max(...highs) : last.price,
        low: lows.length ? Math.min(...lows) : last.price,
        close: last.price,
        volume: volume > 0 ? volume : null,
        trade_value: null,
        transaction_count: null,
      };
    });
}

export async function fetchOptional<T>(
  path: string,
  params?: Record<string, string | number | boolean>
): Promise<T | null> {
  try {
    return await fetchJson<T>(path, params);
  } catch {
    return null;
  }
}

export function averageRecentChartValue(
  points: ChartPoint[],
  key: "close" | "volume",
  windowSize: number
) {
  const values = points
    .slice(-windowSize)
    .map((point) => point[key])
    .filter((value): value is number => value !== null && value !== undefined);

  if (values.length < windowSize) return null;

  return values.reduce((total, value) => total + value, 0) / values.length;
}

export function chartWindowStats(points: ChartPoint[], windowSize: number) {
  const rows = points.slice(-windowSize);
  const firstClose = rows.find((point) => finiteNumber(point.close))?.close ?? null;
  const latest = [...rows].reverse().find((point) => finiteNumber(point.close)) ?? null;
  const latestClose = latest?.close ?? null;
  const highs = rows.map((point) => point.high).filter(finiteNumber);
  const lows = rows.map((point) => point.low).filter(finiteNumber);
  const volumes = rows.map((point) => point.volume).filter(finiteNumber);
  const high = highs.length ? Math.max(...highs) : null;
  const low = lows.length ? Math.min(...lows) : null;
  const changePct =
    finiteNumber(latestClose) && finiteNumber(firstClose) && firstClose !== 0
      ? ((latestClose - firstClose) / firstClose) * 100
      : null;
  const rangePositionPct =
    finiteNumber(latestClose) && finiteNumber(high) && finiteNumber(low) && high !== low
      ? ((latestClose - low) / (high - low)) * 100
      : null;

  return {
    pointCount: rows.length,
    latestClose,
    changePct,
    high,
    low,
    rangePositionPct,
    volumeAverage:
      volumes.length > 0
        ? volumes.reduce((total, value) => total + value, 0) / volumes.length
        : null,
  };
}

export function averageRecentChartClose(points: ChartPoint[], windowSize: number) {
  return averageRecentChartValue(points, "close", windowSize);
}

export function latestLargeHolderSummary(
  rows: ShareholdingDistributionWeeklyRead[],
  largeHolderLots: number
) {
  const groups = new Map<string, ShareholdingDistributionWeeklyRead[]>();

  rows.forEach((row) => {
    groups.set(row.data_date, [...(groups.get(row.data_date) ?? []), row]);
  });

  const points = Array.from(groups.entries())
    .sort(([leftDate], [rightDate]) => leftDate.localeCompare(rightDate))
    .map(([dataDate, groupRows]) => {
      const largeRows = groupRows.filter((row) => {
        const range = shareholdingLevelRanges[row.holding_level_order ?? -1];
        return range ? range.minLots >= largeHolderLots : false;
      });
      const ratio = largeRows.reduce((total, row) => total + (row.share_ratio ?? 0), 0);

      return {
        dataDate,
        ratio: largeRows.length ? ratio : null,
      };
    })
    .filter((point) => point.ratio !== null);
  const latest = points[points.length - 1] ?? null;
  const previous = points[points.length - 2] ?? null;
  const change =
    latest?.ratio !== null &&
    latest?.ratio !== undefined &&
    previous?.ratio !== null &&
    previous?.ratio !== undefined
      ? latest.ratio - previous.ratio
      : null;

  return {
    ratio: latest?.ratio ?? null,
    change,
    dataDate: latest?.dataDate ?? null,
  };
}

export function sumRecentInstitutionalNet(rows: InstitutionalTradeDailyRead[], rowCount: number) {
  const values = rows
    .slice(-rowCount)
    .map((row) => row.total_institutional_net)
    .filter(finiteNumber);

  if (!values.length) return null;

  return values.reduce((total, value) => total + value, 0);
}

export function summarizeIntradayPoints(points: IntradayTrendPoint[]) {
  const validPoints = points.filter((point) => point.price !== null && point.price !== undefined);

  if (validPoints.length === 0) {
    return {
      open: null,
      high: null,
      low: null,
      volume: null,
    };
  }

  const firstPoint = validPoints[0];
  const highs = validPoints.map((point) => point.high ?? point.price);
  const lows = validPoints.map((point) => point.low ?? point.price);
  const volumes = validPoints
    .map((point) => point.volume)
    .filter((value): value is number => value !== null && value !== undefined);

  return {
    open: firstPoint.open ?? firstPoint.price,
    high: Math.max(...highs),
    low: Math.min(...lows),
    volume: volumes.length > 0 ? volumes.reduce((total, value) => total + value, 0) : null,
  };
}

export type TechnicalTone = "positive" | "negative" | "neutral" | "warning";

export type TechnicalReportRow = {
  key?: string;
  title: string;
  description: string;
  value: string;
  pulseValue?: number | string | null;
  direction?: number | null;
  tone?: TechnicalTone;
};

export type TechnicalReportBadge = {
  label: string;
  tone: string;
};

export type TechnicalReport = {
  title: string;
  summary: string;
  value: number | null;
  valueLabel: string;
  score: number;
  rows: TechnicalReportRow[];
  badges: TechnicalReportBadge[];
};

function translatedValue(
  t: TranslationFunction | undefined,
  key: string,
  fallback: string,
  values?: TranslationValues
) {
  if (!t) return fallback;
  const translated = t(key, values);
  return translated === key ? fallback : translated;
}

const technicalTextKeyMap: Record<string, string> = {
  資料讀取中: "loading",
  資料不足: "insufficient",
  等待盤中資料: "waitingIntraday",
  開盤偏強: "openingStrong",
  開盤觀察: "openingWatch",
  開盤偏弱: "openingWeak",
  盤中偏多: "intradayBullish",
  盤中觀察: "intradayWatch",
  盤中偏弱: "intradayWeak",
  短線偏多: "dailyBullish",
  短線整理: "dailyNeutral",
  短線偏弱: "dailyWeak",
  波段偏多: "weeklyBullish",
  波段整理: "weeklyNeutral",
  波段偏弱: "weeklyWeak",
  中線轉強: "swingBullish",
  中線整理: "swingNeutral",
  中線偏弱: "swingWeak",
  長線偏多: "longBullish",
  長線整理: "longNeutral",
  長線觀察: "longWatch",
  長線偏弱: "longWeak",
  資料狀態: "dataStatus",
  參考基準: "referenceBase",
  即時價格: "livePrice",
  開盤結構: "openingStructure",
  量能速度: "volumePace",
  日線背景: "dailyBackground",
  法人籌碼: "institutionalFlow",
  相對市場: "relativeMarket",
  趨勢結構: "trendStructure",
  動能指標: "momentum",
  量價資金: "volumeFlow",
  波動風險: "volatilityRisk",
  中線趨勢: "swingTrend",
  區間位置: "rangePosition",
  週量節奏: "weeklyVolume",
  法人累積: "institutionalAccumulation",
  市場背景: "marketBackground",
  長線趨勢: "longTrend",
  長期區間: "longRange",
  營收動能: "revenueMomentum",
  獲利品質: "earningsQuality",
  長期籌碼: "longChipFlow",
  "站上 MA20": "aboveMa20",
  "跌破 MA20": "belowMa20",
  "MACD 偏多": "macdBullish",
  "MACD 偏弱": "macdWeak",
  "RSI 過熱": "rsiOverheated",
  放量: "volumeSurge",
  走升: "rising",
  走弱: "weakening",
  等待盤中: "waitingIntradayShort",
  開盤資料少: "openingSparse",
  開高: "gapUp",
  開低: "gapDown",
  "日線站上 MA20": "dailyAboveMa20",
  "日線跌破 MA20": "dailyBelowMa20",
  "日線 RSI 過熱": "dailyRsiOverheated",
  週線偏多: "weeklyBullishLine",
  週線偏弱: "weeklyWeakLine",
  "接近26週高位": "near26WeekHigh",
  週量放大: "weeklyVolumeSurge",
  月線偏多: "monthlyBullishLine",
  月線偏弱: "monthlyWeakLine",
  營收成長: "revenueGrowth",
  營收衰退: "revenueDecline",
  大戶增加: "largeHoldersIncreasing",
  大戶減少: "largeHoldersDecreasing",
  籌碼待讀取: "chipFlowPending",
  營收待讀取: "revenuePending",
  法人累積買超: "institutionalAccumulationBuy",
  法人累積賣超: "institutionalAccumulationSell",
  位於區間上緣: "nearRangeHigh",
  位於區間下緣: "nearRangeLow",
  區間中段: "rangeMiddle",
  現價高於昨收: "priceAbovePreviousClose",
  現價低於昨收: "priceBelowPreviousClose",
  漲跌資料不足: "changeInsufficient",
  開盤資料不足: "openingInsufficient",
  日線指標僅作背景: "dailyIndicatorsAsBackground",
  盤中資料已進入觀察期: "intradayObservationReady",
  "接近12月高位": "near12MonthHigh",
  價格結構不足: "priceStructureInsufficient",
  動能資料不足: "momentumInsufficient",
  量能一般: "volumeNormal",
  量能資料不足: "volumeInsufficient",
  訊號資料不足: "signalInsufficient",
  尚無足夠資料產生報告: "notEnoughForReport",
  尚無足夠日K資料產生技術報告: "notEnoughDailyReport",
  尚無足夠週K資料產生技術報告: "notEnoughWeeklyReport",
  尚無足夠月K資料產生技術報告: "notEnoughMonthlyReport",
  正在整理技術訊號: "organizingSignals",
  觀察中: "observing",
};

export function technicalReportPhrase(
  value: string,
  t?: TranslationFunction
) {
  const key = technicalTextKeyMap[value];
  return key
    ? translatedValue(t, `stockDetail.dataViews.technical.terms.${key}`, value)
    : value;
}

function translatedTechnicalDisplayValue(value: string, t?: TranslationFunction) {
  if (!t) return value;
  if (value === "觀察中") return technicalReportPhrase(value, t);
  if (/^\d+筆$/.test(value)) {
    return translatedValue(t, "stockDetail.dataViews.technical.units.points", value, {
      count: value.replace("筆", ""),
    });
  }
  if (value.endsWith("張")) {
    return `${value.slice(0, -1)}${t("stockDetail.dataPanel.units.lots")}`;
  }
  return value;
}

function replaceKnownTechnicalTerms(text: string, t?: TranslationFunction) {
  if (!t) return text;

  let output = text;
  Object.keys(technicalTextKeyMap)
    .sort((left, right) => right.length - left.length)
    .forEach((term) => {
      output = output.replaceAll(term, technicalReportPhrase(term, t));
    });

  return output
    .replaceAll("，", ", ")
    .replaceAll("日K", translatedValue(t, "stockDetail.dataViews.technical.terms.dailyK", "Daily"))
    .replaceAll("週K", translatedValue(t, "stockDetail.dataViews.technical.terms.weeklyK", "Weekly"))
    .replaceAll("月K", translatedValue(t, "stockDetail.dataViews.technical.terms.monthlyK", "Monthly"))
    .replaceAll("20日均量", translatedValue(t, "stockDetail.dataViews.technical.terms.twentyDayAverage", "20-day average"))
    .replaceAll("20期均量", translatedValue(t, "stockDetail.dataViews.technical.terms.twentyPeriodAverage", "20-period average"))
    .replaceAll("融資餘額", translatedValue(t, "stockDetail.dataViews.technical.terms.marginBalance", "margin balance"))
    .replaceAll("最新三大法人合計", translatedValue(t, "stockDetail.dataViews.technical.terms.latestInstitutionalTotal", "Latest institutional total"))
    .replaceAll("最新已公布三大法人", translatedValue(t, "stockDetail.dataViews.technical.terms.latestInstitutionalPublished", "Latest published institutional data"))
    .replaceAll("目前累計量", translatedValue(t, "stockDetail.dataViews.technical.terms.currentCumulativeVolume", "Current cumulative volume"))
    .replaceAll("今日漲跌幅將以上一交易日收盤價計算", translatedValue(t, "stockDetail.dataViews.technical.terms.todayReferenceClose", "Today's change is calculated from the previous close"))
    .replaceAll("尚未取得今日第一筆成交或即時快照", translatedValue(t, "stockDetail.dataViews.technical.terms.noIntradaySnapshot", "No first intraday trade or realtime snapshot yet"))
    .replaceAll("相對昨收", translatedValue(t, "stockDetail.dataViews.technical.terms.vsPreviousClose", "vs previous close"))
    .replaceAll("均價", translatedValue(t, "stockDetail.dataViews.technical.terms.averagePrice", "average price"))
    .replaceAll("高低", translatedValue(t, "stockDetail.dataViews.technical.terms.highLow", "high/low"))
    .replaceAll("持股比", translatedValue(t, "stockDetail.dataViews.technical.terms.holdingRatio", "holding ratio"))
    .replaceAll("最新", translatedValue(t, "stockDetail.dataViews.technical.terms.latest", "latest"))
    .replace(/(\d+)\s*筆盤中資料/g, (_, count: string) =>
      translatedValue(t, "stockDetail.dataViews.technical.units.intradayPoints", `${count} intraday points`, {
        count,
      })
    )
    .replace(/(\d+)週/g, (_, count: string) =>
      translatedValue(t, "stockDetail.dataViews.technical.units.weeks", `${count}W`, { count })
    )
    .replace(/(\d+)月/g, (_, count: string) =>
      translatedValue(t, "stockDetail.dataViews.technical.units.months", `${count}M`, { count })
    )
    .replace(/(\d+)筆/g, (_, count: string) =>
      translatedValue(t, "stockDetail.dataViews.technical.units.points", `${count} points`, {
        count,
      })
    )
    .replace(/([+-]?[0-9,]+(?:\.\d+)?)張/g, (_, count: string) =>
      `${count}${t("stockDetail.dataPanel.units.lots")}`
    );
}

function technicalValueLabel(value: string, t?: TranslationFunction) {
  if (value === "vs 昨收") {
    return translatedValue(t, "stockDetail.dataViews.technical.valueLabels.vsPreviousClose", value);
  }
  if (value === "近13週") {
    return translatedValue(t, "stockDetail.dataViews.technical.valueLabels.last13Weeks", value);
  }
  if (value === "近6月") {
    return translatedValue(t, "stockDetail.dataViews.technical.valueLabels.last6Months", value);
  }
  if (value === "近12月") {
    return translatedValue(t, "stockDetail.dataViews.technical.valueLabels.last12Months", value);
  }
  return value;
}

export function technicalToneClass(tone: TechnicalTone) {
  if (tone === "positive") return "text-omi-market-up";
  if (tone === "negative") return "text-omi-market-down";
  if (tone === "warning") return "text-omi-warning";
  return "text-omi-text";
}

export function semanticTechnicalTone(tone: string | null | undefined): TechnicalTone {
  if (tone === "positive" || tone === "negative" || tone === "warning") return tone;
  return "neutral";
}

export function semanticBadgeToneClass(tone: string | null | undefined) {
  if (tone === "positive") return "text-omi-danger bg-omi-danger-soft";
  if (tone === "negative") return "text-omi-success bg-omi-success-soft";
  if (tone === "warning") return "text-omi-warning bg-omi-warning-soft";
  return "text-omi-text-muted bg-omi-surface-muted";
}

export function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function mapBackendTechnicalReport(
  report: StockTechnicalReportRead,
  t?: TranslationFunction
): TechnicalReport {
  return {
    title: technicalReportPhrase(report.title, t),
    summary: replaceKnownTechnicalTerms(report.summary, t),
    value: report.value,
    valueLabel: technicalValueLabel(report.value_label, t),
    score: report.score,
    rows: report.rows.map((row) => ({
      key: row.key,
      title: technicalReportPhrase(row.label, t),
      description: replaceKnownTechnicalTerms(row.description, t),
      value: translatedTechnicalDisplayValue(row.display_value, t),
      pulseValue: numberValue(row.value),
      direction: row.direction,
      tone: semanticTechnicalTone(row.tone),
    })),
    badges: report.badges.map((badge) => ({
      label: technicalReportPhrase(badge.label, t),
      tone: semanticBadgeToneClass(badge.tone),
    })),
  };
}

export function localizeTechnicalReport(
  report: TechnicalReport,
  t?: TranslationFunction
): TechnicalReport {
  if (!t) return report;

  return {
    ...report,
    title: technicalReportPhrase(report.title, t),
    summary: replaceKnownTechnicalTerms(report.summary, t),
    valueLabel: technicalValueLabel(report.valueLabel, t),
    rows: report.rows.map((row) => ({
      ...row,
      title: technicalReportPhrase(row.title, t),
      description: replaceKnownTechnicalTerms(row.description, t),
      value: translatedTechnicalDisplayValue(row.value, t),
    })),
    badges: report.badges.map((badge) => ({
      ...badge,
      label: technicalReportPhrase(badge.label, t),
    })),
  };
}

export function TechnicalSignalRow({
  title,
  description,
  value,
  pulseValue,
  direction,
  tone = "neutral",
}: {
  title: string;
  description: string;
  value: string;
  pulseValue?: number | string | null;
  direction?: number | null;
  tone?: TechnicalTone;
}) {
  return (
    <div className={`omi-technical-row omi-technical-row-${tone} flex items-start justify-between gap-4 border-t border-omi-border-subtle py-2 first:border-t-0 first:pt-0`}>
      <div className="min-w-0">
        <div className="text-sm font-bold text-omi-text-strong">{title}</div>
        <div className="mt-0.5 text-xs leading-4 text-omi-text-muted">{description}</div>
      </div>
      <div className={`omi-technical-score shrink-0 text-right text-sm font-bold ${technicalToneClass(tone)}`}>
        <PriceUpdatePulse
          value={pulseValue ?? value}
          direction={direction}
          resetKey={title}
          className="justify-end tabular-nums"
        >
          {value}
        </PriceUpdatePulse>
      </div>
    </div>
  );
}

export function TechnicalLoadingPanel() {
  const t = useT();

  return (
    <>
      <div className="omi-technical-summary border-b border-omi-border-subtle px-5 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            Technical
          </div>
          <LoadingDots label={t("stockDetail.dataViews.technicalLoading")} />
        </div>
        <div className="mt-3 flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="omi-skeleton h-5 w-32" />
            <div className="omi-skeleton h-3 w-56 max-w-full" />
          </div>
          <div className="w-20 space-y-2">
            <div className="ml-auto omi-skeleton h-5 w-16" />
            <div className="ml-auto omi-skeleton h-2.5 w-12" />
          </div>
        </div>
      </div>

      <div className="px-5 py-3">
        <div className="space-y-0">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              className="omi-technical-loading-row flex items-start justify-between gap-4 border-t border-omi-border-subtle py-2 first:border-t-0 first:pt-0"
              aria-hidden="true"
            >
              <div className="min-w-0 flex-1 space-y-2">
                <div className="omi-skeleton h-3.5 w-24" />
                <div className="omi-skeleton h-2.5 w-48 max-w-full" />
              </div>
              <div className="w-20 space-y-2">
                <div className="ml-auto omi-skeleton h-3.5 w-14" />
                <div className="ml-auto omi-skeleton h-2.5 w-10" />
              </div>
            </div>
          ))}
        </div>

        <div className="mt-3 border-t border-omi-border-subtle pt-3">
          <div className="omi-technical-loading-row flex items-start justify-between gap-4 text-xs">
            <div className="space-y-2">
              <div className="omi-skeleton h-3 w-16" />
              <div className="omi-skeleton h-4 w-20" />
              <div className="omi-skeleton h-2.5 w-24" />
            </div>
            <div className="w-20 space-y-2">
              <div className="ml-auto omi-skeleton h-3.5 w-16" />
              <div className="ml-auto omi-skeleton h-2.5 w-12" />
            </div>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2" aria-hidden="true">
          <div className="omi-skeleton h-7 w-20" />
          <div className="omi-skeleton h-7 w-24" />
          <div className="omi-skeleton h-7 w-16" />
        </div>
      </div>
    </>
  );
}

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

  const driverRows = [
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
    .slice(0, 3);
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

export function marketRegimeLabel(
  index: MarketIndexSnapshot | null | undefined,
  t?: TranslationFunction
) {
  if (!index || index.close === null || index.close === undefined) {
    return t?.("dashboard.marketIndex.insufficient") ?? "Insufficient data";
  }

  if (index.price_vs_ma20 !== null && index.price_vs_ma20 !== undefined) {
    if (index.price_vs_ma20 > 1) return t?.("dashboard.marketIndex.aboveMa20") ?? "Above MA20";
    if (index.price_vs_ma20 < -1) return t?.("dashboard.marketIndex.belowMa20") ?? "Below MA20";
  }

  if (index.change_pct !== null && index.change_pct !== undefined) {
    if (index.change_pct > 0) return t?.("dashboard.marketIndex.bullishShort") ?? "Short-term bullish";
    if (index.change_pct < 0) return t?.("dashboard.marketIndex.weakShort") ?? "Short-term weak";
  }

  return t?.("dashboard.marketIndex.neutral") ?? "Rangebound";
}

const marketIndexListNameKeys: Record<string, string> = {
  加權指數: "taiex",
  櫃買指數: "tpex",
  水泥窯製: "cementKiln",
  水泥: "cement",
  食品: "food",
  塑膠化工: "plasticsChemicals",
  塑膠: "plastics",
  紡織纖維: "textiles",
  機電: "electricalMachinery",
  電機機械: "electricMachinery",
  電器電纜: "electricalCable",
  化學生技醫療: "chemicalBiotechMedical",
  化學: "chemical",
  生技醫療: "biotechMedical",
  玻璃陶瓷: "glassCeramics",
  造紙: "paper",
  鋼鐵: "steel",
  橡膠: "rubber",
  汽車: "automobile",
  半導體: "semiconductor",
  電腦及週邊設備: "computerPeripheral",
  光電: "optoelectronics",
  通信網路: "communicationsInternet",
  電子零組件: "electronicParts",
  電子通路: "electronicDistribution",
  資訊服務: "informationService",
  其他電子: "otherElectronics",
  建材營造: "buildingMaterialConstruction",
  航運: "shipping",
  航運業: "shipping",
  觀光: "tourism",
  觀光餐旅: "tourismHospitality",
  金融保險: "financialInsurance",
  貿易百貨: "tradingConsumersGoods",
  油電燃氣: "oilGasElectricity",
  存託憑證: "depositaryReceipts",
  電子: "electronics",
  金融: "financial",
  非金電: "nonFinanceNonElectronics",
  其他: "other",
};

function normalizeMarketIndexListName(name: string) {
  const trimmedName = name.trim();

  if (trimmedName === "發行量加權股價指數") return "加權指數";
  if (trimmedName.endsWith("類指數")) return trimmedName.slice(0, -"類指數".length);

  return trimmedName;
}

function marketIndexListDisplayName(name: string, t: TranslationFunction) {
  const normalizedName = normalizeMarketIndexListName(name);
  const key = marketIndexListNameKeys[normalizedName];

  if (!key) return normalizedName || name;

  return t(`stockDetail.dataViews.indexList.names.${key}`);
}

export function IndexListPanel({
  items,
  loadState,
  marketLabel,
}: {
  items: MarketIndexListItem[];
  loadState: LoadState;
  marketLabel: string;
}) {
  const t = useT();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-omi-border-subtle px-5 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
          Market
        </div>
        <div className="mt-2 flex items-end justify-between gap-4">
          <div>
            <div className="text-xl font-bold text-omi-text-strong">
              {t("stockDetail.dataViews.indexList.title", { marketLabel })}
            </div>
            {loadState === "loading" ? (
              <div className="mt-1 inline-flex items-center gap-2 text-xs text-omi-text-muted">
                {t("stockDetail.dataViews.indexList.loading")}
                <LoadingDots
                  label={t("stockDetail.dataViews.indexList.loadingLabel", {
                    marketLabel,
                  })}
                />
              </div>
            ) : (
              <div className="mt-1 text-xs text-omi-text-muted">
                {t("stockDetail.dataViews.indexList.count", { count: items.length })}
              </div>
            )}
          </div>
          <div className="text-right text-xs font-semibold text-omi-text-muted">
            {marketLabel}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {items.length > 0 ? (
          items.map((item) => (
            <div
              key={`${item.market}-${item.rank}-${item.name}`}
              className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-omi-border-subtle py-2 text-sm first:border-t-0"
            >
              <div className="min-w-0">
                <div className="truncate font-semibold text-omi-text">
                  {item.rank}. {marketIndexListDisplayName(item.name, t)}
                </div>
                <div className="mt-0.5 text-xs text-omi-text-muted">
                  {item.trade_date ?? "-"}
                </div>
              </div>
              <div className="text-right font-semibold text-omi-text-strong">
                {formatPrice(item.close)}
              </div>
              <div className={`min-w-20 text-right font-semibold ${valueTone(item.change_pct)}`}>
                <div>{formatPct(item.change_pct)}</div>
                <div className="text-xs font-medium">{formatSignedPrice(item.change)}</div>
              </div>
            </div>
          ))
        ) : loadState === "loading" ? (
          <div className="space-y-0" aria-hidden="true">
            {Array.from({ length: 6 }).map((_, index) => (
              <div
                key={index}
                className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-omi-border-subtle py-2 first:border-t-0"
              >
                <div className="min-w-0 space-y-2">
                  <div className="omi-skeleton h-3.5 w-32" />
                  <div className="omi-skeleton h-2.5 w-20" />
                </div>
                <div className="omi-skeleton h-3.5 w-16" />
                <div className="omi-skeleton h-7 w-20" />
              </div>
            ))}
          </div>
        ) : (
          <div className="py-10 text-center text-sm text-omi-text-muted">
            {t("stockDetail.dataViews.indexList.empty")}
          </div>
        )}
      </div>
    </div>
  );
}

export function IndexDetailDataPanel({
  index,
  timeframe,
  latestChart,
  todayStats,
  todayPreviousClose,
  marketChip,
  marketChipLoadState,
  contributions,
  contributionLoadState,
}: {
  index: MarketIndexSnapshot | null;
  timeframe: Timeframe;
  latestChart: ChartPoint | null;
  todayStats: ReturnType<typeof summarizeIntradayPoints>;
  todayPreviousClose: number | null;
  marketChip: MarketChipDaily | null;
  marketChipLoadState: LoadState;
  contributions: MarketIndexContributionResponse | null;
  contributionLoadState: LoadState;
}) {
  const t = useT();
  const isToday = timeframe === "today";
  const breadth = index?.breadth ?? null;
  const contractsUnit = t("stockDetail.dataViews.indexDetail.contractsUnit");
  const open = isToday
    ? todayStats.open ?? index?.open ?? latestChart?.open ?? null
    : latestChart?.open ?? index?.open ?? null;
  const high = isToday
    ? todayStats.high ?? index?.high ?? latestChart?.high ?? null
    : latestChart?.high ?? index?.high ?? null;
  const low = isToday
    ? todayStats.low ?? index?.low ?? latestChart?.low ?? null
    : latestChart?.low ?? index?.low ?? null;
  const reference = todayPreviousClose ?? index?.previous_close ?? null;
  const tradeValue = index?.trade_value ?? breadth?.trade_value ?? latestChart?.trade_value ?? null;
  const estimatedTradeValue = index?.estimated_trade_value ?? tradeValue;

  return (
    <section className="border border-omi-border-subtle bg-omi-surface">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-omi-border-subtle px-5 py-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("stockDetail.dataViews.indexDetail.eyebrow")}
          </div>
          <div className="mt-1 text-lg font-bold text-omi-text-strong">
            {t("stockDetail.dataViews.indexDetail.title")}
          </div>
        </div>
        <div className="text-right text-xs text-omi-text-muted">
          {t("stockDetail.dataViews.indexDetail.updated", {
            time: formatDateTime(index?.as_of),
          })}
        </div>
      </div>

      <div className="grid gap-2 border-b border-omi-border-subtle p-5 sm:grid-cols-2 xl:grid-cols-4">
        <IndexMetricCard
          label={t("stockDetail.dataViews.indexDetail.open")}
          value={formatPrice(open)}
          tone={valueTone(open !== null && reference !== null ? open - reference : null)}
        />
        <IndexMetricCard
          label={t("stockDetail.dataViews.indexDetail.high")}
          value={formatPrice(high)}
          tone={valueTone(high !== null && reference !== null ? high - reference : null)}
        />
        <IndexMetricCard
          label={t("stockDetail.dataViews.indexDetail.low")}
          value={formatPrice(low)}
          tone={valueTone(low !== null && reference !== null ? low - reference : null)}
        />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.reference")} value={formatPrice(reference)} />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.tradeValueYi")} value={formatTradeValueYi(tradeValue)} />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.estimatedTradeValueYi")} value={formatTradeValueYi(estimatedTradeValue)} />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.advances")} value={formatNumber(breadth?.advance_count)} tone="text-omi-market-up" />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.declines")} value={formatNumber(breadth?.decline_count)} tone="text-omi-market-down" />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.limitUp")} value={formatNumber(breadth?.limit_up_count)} tone="text-omi-market-up" />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.limitDown")} value={formatNumber(breadth?.limit_down_count)} tone="text-omi-market-down" />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.unchanged")} value={formatNumber(breadth?.unchanged_count)} />
        <IndexMetricCard label={t("stockDetail.dataViews.indexDetail.total")} value={formatNumber(breadth?.total_count)} />
      </div>

      <div className="border-b border-omi-border-subtle px-5 py-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-xs font-bold text-omi-text-strong">
              {t("stockDetail.dataViews.indexDetail.chipTitle")}
            </div>
            <div className="mt-0.5 text-xs text-omi-text-muted">
              {t("stockDetail.dataViews.indexDetail.chipDescription")}
            </div>
          </div>
          <div className="text-xs text-omi-text-muted">
            {t("stockDetail.dataViews.indexDetail.tradeDate", {
              date: marketChip?.trade_date ? formatDate(marketChip.trade_date) : "-",
            })}
          </div>
        </div>
        {marketChipLoadState === "loading" ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
                <div className="omi-skeleton h-3 w-24" />
                <div className="omi-skeleton mt-2 h-4 w-20" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.foreignNetOi")}
              value={formatSignedContracts(marketChip?.foreign_futures_net_oi, contractsUnit)}
              tone={valueTone(marketChip?.foreign_futures_net_oi)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.foreignNetOiChange")}
              value={formatSignedContracts(
                marketChip?.foreign_futures_net_oi_change,
                contractsUnit
              )}
              tone={valueTone(marketChip?.foreign_futures_net_oi_change)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.retailNetOi")}
              value={formatSignedContracts(marketChip?.retail_futures_net_oi, contractsUnit)}
              tone={valueTone(marketChip?.retail_futures_net_oi)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.retailNetOiChange")}
              value={formatSignedContracts(
                marketChip?.retail_futures_net_oi_change,
                contractsUnit
              )}
              tone={valueTone(marketChip?.retail_futures_net_oi_change)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.totalInstitutionalNetValue")}
              value={formatSignedTradeValueYi(marketChip?.total_institutional_net_value)}
              tone={valueTone(marketChip?.total_institutional_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.foreignNetValue")}
              value={formatSignedTradeValueYi(marketChip?.foreign_investor_net_value)}
              tone={valueTone(marketChip?.foreign_investor_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.investmentTrustNetValue")}
              value={formatSignedTradeValueYi(marketChip?.investment_trust_net_value)}
              tone={valueTone(marketChip?.investment_trust_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.dealerNetValue")}
              value={formatSignedTradeValueYi(marketChip?.dealer_net_value)}
              tone={valueTone(marketChip?.dealer_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.governmentBankNetValue")}
              value={formatSignedTradeValueYi(marketChip?.government_bank_net_value)}
              tone={valueTone(marketChip?.government_bank_net_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.marginChangeValue")}
              value={formatSignedTradeValueYi(marketChip?.margin_balance_change_value)}
              tone={valueTone(marketChip?.margin_balance_change_value)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.marginChangeShares")}
              value={formatSignedLots(marketChip?.margin_balance_change_shares)}
              tone={valueTone(marketChip?.margin_balance_change_shares)}
            />
            <IndexMetricCard
              label={t("stockDetail.dataViews.indexDetail.shortChangeShares")}
              value={formatSignedLots(marketChip?.short_balance_change_shares)}
              tone={valueTone(marketChip?.short_balance_change_shares)}
            />
          </div>
        )}
      </div>

      <IndexContributionRanking
        contributions={contributions}
        loadState={contributionLoadState}
      />

      <div className="px-5 py-3 text-xs text-omi-text-muted">
        {breadth?.source
          ? t("stockDetail.dataViews.indexDetail.breadthSource", {
              source: breadth.source,
            })
          : t("stockDetail.dataViews.indexDetail.breadthPending")}
      </div>
    </section>
  );
}

export function IndexMetricCard({
  label,
  value,
  tone = "text-omi-text",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="border border-omi-border-subtle bg-omi-surface-subtle px-3 py-2">
      <div className="text-xs font-semibold text-omi-text-muted">{label}</div>
      <div className={`mt-1 text-base font-bold ${tone}`}>{value}</div>
    </div>
  );
}

export function ContributionColumn({
  title,
  items,
  tone,
}: {
  title: string;
  items: MarketIndexContributionItem[];
  tone: string;
}) {
  const t = useT();

  return (
    <div className="min-w-0">
      <div className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-omi-text-muted">
        {title}
      </div>
      <div className="overflow-hidden border border-omi-border-subtle">
        {items.length > 0 ? (
          items.map((item) => (
            <div
              key={`${title}-${item.stock_id}`}
              className="grid grid-cols-[34px_minmax(0,1fr)_82px_88px] items-center border-b border-omi-border-subtle px-3 py-2 text-xs last:border-b-0"
            >
              <div className="text-omi-text-muted">#{item.rank}</div>
              <div className="min-w-0">
                <div className="truncate font-semibold text-omi-text-strong">
                  {item.stock_id} {item.stock_name ?? ""}
                </div>
                <div className="mt-0.5 text-omi-text-muted">
                  {formatPrice(item.close)} / {formatPct(item.change_pct)}
                </div>
              </div>
              <div className={`text-right font-bold ${tone}`}>
                {formatContributionPoint(item.contribution_points)}
              </div>
              <div className="text-right text-omi-text-muted">
                {formatTradeValueYi(item.trade_value)}
              </div>
            </div>
          ))
        ) : (
          <div className="px-3 py-8 text-center text-sm text-omi-text-muted">
            {t("stockDetail.dataViews.contribution.empty")}
          </div>
        )}
      </div>
    </div>
  );
}

export function IndexContributionRanking({
  contributions,
  loadState,
}: {
  contributions: MarketIndexContributionResponse | null;
  loadState: LoadState;
}) {
  const t = useT();

  return (
    <div className="border-b border-omi-border-subtle px-5 py-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-omi-text-muted">
            {t("stockDetail.dataViews.contribution.eyebrow")}
          </div>
          <div className="mt-1 text-base font-bold text-omi-text-strong">
            {t("stockDetail.dataViews.contribution.title")}
          </div>
        </div>
        <div className="text-right text-xs text-omi-text-muted">
          {loadState === "loading"
            ? t("stockDetail.dataViews.contribution.loading")
            : contributions?.trade_date
              ? t("stockDetail.dataViews.contribution.tradeDatePoints", {
                  date: contributions.trade_date,
                })
              : t("stockDetail.dataViews.contribution.pointsEstimated")}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ContributionColumn
          title={t("stockDetail.dataViews.contribution.positive")}
          items={contributions?.positive ?? []}
          tone="text-omi-market-up"
        />
        <ContributionColumn
          title={t("stockDetail.dataViews.contribution.negative")}
          items={contributions?.negative ?? []}
          tone="text-omi-market-down"
        />
      </div>
    </div>
  );
}

export function MetricRow({
  label,
  value,
  tone = "text-omi-text",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-omi-border-subtle py-2 text-xs">
      <span className="text-omi-text-muted">{label}</span>
      <span className={`font-semibold ${tone}`}>{value}</span>
    </div>
  );
}

export function ChipMetricBlock({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="border border-omi-border-subtle bg-omi-surface px-3 py-2">
      <div className="text-xs font-bold text-omi-text">{title}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

export function DataTabIcon({ type }: { type: DataPanelTab }) {
  if (type === "institutional") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M3 8h14v2H3V8Zm1 3h2v5H4v-5Zm5 0h2v5H9v-5Zm5 0h2v5h-2v-5ZM2 17h16v1H2v-1ZM10 2l7 4H3l7-4Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "branch") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M3 8.5 10 4l7 4.5V17H3V8.5Zm2 1.1V15h10V9.6L10 6.4 5 9.6ZM7 11h2v4H7v-4Zm4 0h2v4h-2v-4Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "revenue") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M10.8 2v2.1c1.9.3 3.2 1.4 3.2 3.1h-2c0-.8-.8-1.3-2-1.3-1.3 0-2 .5-2 1.2 0 .8.8 1.1 2.6 1.5 2 .5 3.8 1.2 3.8 3.4 0 1.8-1.4 3-3.6 3.3V18H8.9v-2.6c-2.2-.3-3.7-1.5-3.7-3.4h2c0 1 1 1.6 2.4 1.6 1.6 0 2.5-.6 2.5-1.5 0-.8-.7-1.2-2.8-1.7-1.9-.5-3.5-1.2-3.5-3.2 0-1.7 1.3-2.8 3.1-3.1V2h1.9Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (type === "earnings") {
    return (
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
        <path
          d="M11 2v4h4v2h-4v2h3.5a2.5 2.5 0 0 1 0 5H11v3H9v-3H5v-2h4v-3H5V8h4V6H5V4h4V2h2Zm0 10v1h3.5a.5.5 0 0 0 0-1H11Z"
          fill="currentColor"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden="true">
      <path
        d="M10 2c3.3 0 6 1 6 2.3S13.3 6.6 10 6.6 4 5.6 4 4.3 6.7 2 10 2Zm-6 4.2c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3V6.2Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v2.1c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-2.1Zm0 4c1.2 1 3.4 1.5 6 1.5s4.8-.6 6-1.5v1.5c0 1.3-2.7 2.3-6 2.3s-6-1-6-2.3v-1.5Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function DataTabButton({
  tab,
  active,
  onClick,
}: {
  tab: { key: DataPanelTab; label: string };
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "omi-data-tab flex h-11 min-w-0 flex-1 items-center justify-center gap-2 border-r border-omi-border-subtle text-sm font-semibold transition last:border-r-0",
        active
          ? "omi-data-tab-active bg-omi-surface text-omi-text-strong"
          : "bg-omi-surface-subtle text-omi-text-muted hover:bg-omi-surface hover:text-omi-text",
      ].join(" ")}
    >
      <DataTabIcon type={tab.key} />
      <span>{tab.label}</span>
    </button>
  );
}

export function EmptyDataState({ message }: { message: string }) {
  return (
    <div className="border border-dashed border-omi-border-subtle px-4 py-8 text-center text-sm text-omi-text-muted">
      {message}
    </div>
  );
}

export function DataPanelLoadingState({ message }: { message: string }) {
  return (
    <div className="omi-tab-panel border border-omi-border-subtle bg-omi-surface px-4 py-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div className="inline-flex min-w-0 items-center gap-2 text-sm font-semibold text-omi-text">
          <span className="truncate">{message}</span>
          <LoadingDots label={message} />
        </div>
        <div className="h-1.5 w-20 overflow-hidden bg-omi-surface-muted">
          <div className="omi-loading-bar h-full w-1/2 bg-omi-control" />
        </div>
      </div>
      <div className="space-y-3">
        <div className="omi-skeleton h-3 w-2/3" />
        <div className="grid grid-cols-3 gap-3">
          <div className="omi-skeleton h-16" />
          <div className="omi-skeleton h-16" />
          <div className="omi-skeleton h-16" />
        </div>
        <div className="omi-skeleton h-44" />
      </div>
    </div>
  );
}

export function DataPanelRefreshRail({ message }: { message: string | null }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 top-0 z-10">
      <div className="h-0.5 overflow-hidden bg-omi-surface-muted">
        <div className="omi-loading-bar h-full w-1/3 bg-omi-accent" />
      </div>
      {message ? (
        <div className="absolute right-0 top-2 max-w-[70%] truncate bg-omi-surface/90 px-2 py-1 text-[11px] font-medium text-omi-text-muted shadow-sm ring-1 ring-slate-200">
          {message}
        </div>
      ) : null}
    </div>
  );
}

export function SegmentedNumberButtons({
  label,
  suffix,
  options,
  value,
  onChange,
}: {
  label: string;
  suffix: string;
  options: number[];
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 text-right font-semibold text-omi-text-muted">{label}</span>
      <div className="grid flex-1 grid-cols-6 overflow-hidden border border-omi-border-strong">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={[
              "h-7 border-r border-omi-border-strong text-xs font-semibold last:border-r-0",
              value === option
                ? "bg-omi-control-border text-omi-text-inverse"
                : "bg-omi-surface text-omi-text hover:bg-omi-surface-subtle",
            ].join(" ")}
          >
            {option}
          </button>
        ))}
      </div>
      <span className="w-4 shrink-0 text-omi-text-muted">{suffix}</span>
    </div>
  );
}

export function minMax(values: Array<number | null | undefined>) {
  const validValues = values.filter(
    (value): value is number =>
      value !== null && value !== undefined && !Number.isNaN(value)
  );

  if (!validValues.length) return null;

  const min = Math.min(...validValues);
  const max = Math.max(...validValues);
  const padding = Math.max((max - min) * 0.12, max === min ? Math.max(Math.abs(max) * 0.08, 1) : 0);

  return {
    min: min - padding,
    max: max + padding,
  };
}

export function chartX(index: number, count: number, left: number, width: number) {
  if (count <= 1) return left + width / 2;
  return left + (index / (count - 1)) * width;
}

export function chartY(value: number, min: number, max: number, top: number, height: number) {
  if (max === min) return top + height / 2;
  return top + ((max - value) / (max - min)) * height;
}

export function buildLinePath(
  points: ShareholdingSeriesPoint[],
  valueKey: keyof Pick<ShareholdingSeriesPoint, "largeRatio" | "smallRatio" | "close">,
  scale: { min: number; max: number },
  left: number,
  top: number,
  width: number,
  height: number
) {
  let hasStarted = false;

  return points
    .map((point, index) => {
      const value = point[valueKey];
      if (value === null || value === undefined || Number.isNaN(value)) return null;

      const x = chartX(index, points.length, left, width);
      const y = chartY(value, scale.min, scale.max, top, height);
      const command = hasStarted ? "L" : "M";
      hasStarted = true;
      return `${command} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

export function buildNumericLinePath<T>(
  points: T[],
  getValue: (point: T) => number | null | undefined,
  scale: { min: number; max: number },
  left: number,
  top: number,
  width: number,
  height: number
) {
  let hasStarted = false;

  return points
    .map((point, index) => {
      const value = getValue(point);
      if (value === null || value === undefined || Number.isNaN(value)) return null;

      const x = chartX(index, points.length, left, width);
      const y = chartY(value, scale.min, scale.max, top, height);
      const command = hasStarted ? "L" : "M";
      hasStarted = true;
      return `${command} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

export function chartEventViewX(event: ReactMouseEvent<SVGSVGElement>, viewWidth: number) {
  const svg = event.currentTarget;
  const screenMatrix = typeof svg.getScreenCTM === "function" ? svg.getScreenCTM() : null;

  if (screenMatrix && typeof DOMPoint !== "undefined") {
    return new DOMPoint(event.clientX, event.clientY).matrixTransform(screenMatrix.inverse()).x;
  }

  const rect = svg.getBoundingClientRect();
  if (rect.width <= 0) return 0;

  return ((event.clientX - rect.left) / rect.width) * viewWidth;
}

export function nearestChartIndex(
  event: ReactMouseEvent<SVGSVGElement>,
  pointCount: number,
  left: number,
  width: number,
  viewWidth: number
) {
  if (pointCount <= 1) return 0;

  const viewX = chartEventViewX(event, viewWidth);
  const clampedX = Math.max(left, Math.min(left + width, viewX));
  const ratio = (clampedX - left) / width;
  return Math.max(0, Math.min(pointCount - 1, Math.round(ratio * (pointCount - 1))));
}

export function tooltipX(x: number, tooltipWidth: number, viewWidth: number) {
  const padding = 8;
  const gap = 16;
  const rightX = x + gap;

  if (rightX + tooltipWidth <= viewWidth - padding) {
    return rightX;
  }

  return Math.max(padding, x - tooltipWidth - gap);
}

export function tooltipY(y: number, tooltipHeight: number, top: number, height: number) {
  return Math.max(8, Math.min(top + height - tooltipHeight - 8, y - tooltipHeight / 2));
}

export function quarterFromMonth(month: number) {
  return Math.floor((month - 1) / 3) + 1;
}

export function revenueGrowth(current: number | null, previous: number | null) {
  if (
    current === null ||
    previous === null ||
    previous === 0 ||
    Number.isNaN(current) ||
    Number.isNaN(previous)
  ) {
    return null;
  }

  return ((current - previous) / previous) * 100;
}

export function buildRevenueSeries(rows: MonthlyRevenueRead[], view: RevenueView) {
  const sortedRows = rows
    .slice()
    .sort((a, b) => a.period.localeCompare(b.period));

  if (view === "monthly") {
    return sortedRows.map<RevenueSeriesPoint>((row) => ({
      period: row.period,
      label: formatPeriodLabel(row.period),
      year: Number(row.period.slice(0, 4)),
      revenue: toRevenueYi(row.monthly_revenue),
      previousRevenue: toRevenueYi(row.previous_year_month_revenue),
      growthPct: row.year_over_year_pct,
      cumulativeRevenue: toRevenueYi(row.cumulative_revenue),
      cumulativeGrowthPct: row.cumulative_year_over_year_pct,
      monthCount: 1,
    }));
  }

  const groups = new Map<
    string,
    {
      year: number;
      quarter: number | null;
      revenue: number;
      previousRevenue: number;
      monthCount: number;
      lastPeriod: string;
    }
  >();

  sortedRows.forEach((row) => {
    const year = Number(row.period.slice(0, 4));
    const month = Number(row.period.slice(5, 7));
    const quarter = quarterFromMonth(month);
    const key = view === "quarterly" ? `${year}-Q${quarter}` : String(year);
    const current = groups.get(key) ?? {
      year,
      quarter: view === "quarterly" ? quarter : null,
      revenue: 0,
      previousRevenue: 0,
      monthCount: 0,
      lastPeriod: row.period,
    };

    current.revenue += toRevenueYi(row.monthly_revenue) ?? 0;
    current.previousRevenue += toRevenueYi(row.previous_year_month_revenue) ?? 0;
    current.monthCount += row.monthly_revenue === null || row.monthly_revenue === undefined ? 0 : 1;
    current.lastPeriod = row.period;
    groups.set(key, current);
  });

  return Array.from(groups.entries()).map<RevenueSeriesPoint>(([key, group]) => {
    const previousRevenue = group.previousRevenue || null;
    const revenue = group.monthCount ? group.revenue : null;

    return {
      period: key,
      label: key,
      year: group.year,
      revenue,
      previousRevenue,
      growthPct: revenueGrowth(revenue, previousRevenue),
      cumulativeRevenue: null,
      cumulativeGrowthPct: null,
      monthCount: group.monthCount,
    };
  });
}

export function buildEarningsSeries(rows: FinancialMetricQuarterlyRead[], view: EarningsView) {
  const sortedRows = rows
    .slice()
    .sort((a, b) => a.fiscal_year - b.fiscal_year || a.quarter - b.quarter);

  if (view === "quarterly") {
    const byPeriod = new Map(sortedRows.map((row) => [row.period, row]));

    return sortedRows.map<EarningsSeriesPoint>((row) => {
      const previous = byPeriod.get(`${row.fiscal_year - 1}Q${row.quarter}`);

      return {
        period: row.period,
        label: row.period,
        fiscalYear: row.fiscal_year,
        quarter: row.quarter,
        eps: row.eps,
        previousEps: previous?.eps ?? null,
        growthPct: revenueGrowth(row.eps, previous?.eps ?? null),
        roe: row.roe,
        roa: row.roa,
        periodCount: 1,
      };
    });
  }

  const groups = new Map<
    number,
    {
      eps: number;
      previousEps: number;
      periodCount: number;
      roe: number | null;
      roa: number | null;
    }
  >();
  const rowsByYear = new Map<number, FinancialMetricQuarterlyRead[]>();

  sortedRows.forEach((row) => {
    const list = rowsByYear.get(row.fiscal_year) ?? [];
    list.push(row);
    rowsByYear.set(row.fiscal_year, list);
  });

  Array.from(rowsByYear.entries()).forEach(([year, yearRows]) => {
    const previousRows = rowsByYear.get(year - 1) ?? [];
    const quarterSet = new Set(yearRows.map((row) => row.quarter));
    const previousComparableRows = previousRows.filter((row) => quarterSet.has(row.quarter));
    const latestRow = yearRows[yearRows.length - 1];

    groups.set(year, {
      eps: yearRows.reduce((sum, row) => sum + (row.eps ?? 0), 0),
      previousEps: previousComparableRows.reduce((sum, row) => sum + (row.eps ?? 0), 0),
      periodCount: yearRows.filter((row) => row.eps !== null && row.eps !== undefined).length,
      roe: latestRow?.roe ?? null,
      roa: latestRow?.roa ?? null,
    });
  });

  return Array.from(groups.entries()).map<EarningsSeriesPoint>(([year, group]) => {
    const eps = group.periodCount ? group.eps : null;
    const previousEps = group.previousEps || null;

    return {
      period: String(year),
      label: String(year),
      fiscalYear: year,
      quarter: null,
      eps,
      previousEps,
      growthPct: revenueGrowth(eps, previousEps),
      roe: group.roe,
      roa: group.roa,
      periodCount: group.periodCount,
    };
  });
}

export function RevenueTrendChart({
  points,
  view,
}: {
  points: RevenueSeriesPoint[];
  view: RevenueView;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const t = useT();
  const chartPoints = points.slice(-36);
  const viewWidth = 860;
  const viewHeight = 360;
  const left = 64;
  const right = 82;
  const top = 54;
  const height = 240;
  const width = viewWidth - left - right;
  const revenueScale = minMax(chartPoints.map((point) => point.revenue));
  const growthScale = minMax(chartPoints.map((point) => point.growthPct));
  const revenueLabel =
    view === "monthly"
      ? t("stockDetail.dataPanel.chart.monthlyRevenueYi")
      : view === "quarterly"
        ? t("stockDetail.dataPanel.chart.quarterlyRevenueYi")
        : t("stockDetail.dataPanel.chart.yearlyRevenueYi");

  if (!chartPoints.length || revenueScale === null) {
    return <EmptyDataState message={t("stockDetail.dataPanel.empty.revenueChart")} />;
  }

  const lineScale = growthScale ?? { min: -1, max: 1 };
  const growthPath = buildNumericLinePath(
    chartPoints,
    (point) => point.growthPct,
    lineScale,
    left,
    top,
    width,
    height
  );
  const barWidth = Math.max(4, Math.min(18, width / Math.max(chartPoints.length, 1) - 4));
  const hoverPoint = hoverIndex === null ? null : chartPoints[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, chartPoints.length, left, width);
  const hoverRevenueY =
    hoverPoint?.revenue === null || hoverPoint?.revenue === undefined
      ? null
      : chartY(hoverPoint.revenue, revenueScale.min, revenueScale.max, top, height);
  const hoverGrowthY =
    hoverPoint?.growthPct === null || hoverPoint?.growthPct === undefined
      ? null
      : chartY(hoverPoint.growthPct, lineScale.min, lineScale.max, top, height);
  const hoverTipWidth = 190;
  const hoverTipHeight = 96;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverGrowthY ?? hoverRevenueY ?? top + height / 2, hoverTipHeight, top, height);

  return (
    <div className="border border-omi-border-subtle bg-omi-surface px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-omi-text-muted">
          <span className="h-3 w-5 rounded-sm bg-omi-heat-border" />
          {revenueLabel}
        </span>
        <span className="inline-flex items-center gap-1 text-omi-text-muted">
          <span className="h-2 w-2 rounded-full border-2 border-omi-market-up-border" />
          {t("stockDetail.dataPanel.chart.yoyPct")}
        </span>
      </div>

      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[360px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, chartPoints.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2, 3].map((tick) => {
          const y = top + (tick / 3) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke={omiChartColors.grid} />;
        })}
        <text x={left} y={20} className="fill-omi-text-muted text-[10px]">
          {t("stockDetail.dataPanel.chart.revenueYi")}
        </text>
        <text x={left + width + right} y={20} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {t("stockDetail.dataPanel.chart.yoyPct")}
        </text>
        {chartPoints.map((point, index) => {
          const value = point.revenue ?? revenueScale.min;
          const x = chartX(index, chartPoints.length, left, width) - barWidth / 2;
          const y = chartY(value, revenueScale.min, revenueScale.max, top, height);

          return (
            <rect
              key={point.period}
              x={x}
              y={y}
              width={barWidth}
              height={top + height - y}
              fill={omiChartColors.heatMuted}
              opacity="0.76"
            />
          );
        })}
        {growthPath ? (
          <path d={growthPath} fill="none" stroke={omiChartColors.growth} strokeWidth="2.4" strokeLinecap="round" />
        ) : null}
        {chartPoints.map((point, index) => {
          if (point.growthPct === null || point.growthPct === undefined) return null;
          const x = chartX(index, chartPoints.length, left, width);
          const y = chartY(point.growthPct, lineScale.min, lineScale.max, top, height);
          return <circle key={`${point.period}-growth`} cx={x} cy={y} r={3} fill={omiChartColors.surface} stroke={omiChartColors.growth} strokeWidth="2" />;
        })}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatRevenueYiValue(revenueScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatRevenueYiValue(revenueScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-omi-text-muted text-[10px]">
          {formatPct(lineScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-omi-text-muted text-[10px]">
          {formatPct(lineScale.min)}
        </text>
        <text x={left} y={top + height + 28} className="fill-omi-text-muted text-[10px]">
          {chartPoints[0]?.label}
        </text>
        <text x={left + width} y={top + height + 28} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {chartPoints[chartPoints.length - 1]?.label}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke={omiChartColors.crosshair}
              strokeDasharray="4 4"
            />
            <rect x={hoverX - 34} y={top + height + 34} width={68} height={22} rx={3} fill={omiChartColors.tooltip} />
            <text x={hoverX} y={top + height + 49} textAnchor="middle" className="fill-omi-surface text-[11px] font-semibold">
              {hoverPoint.label}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill={omiChartColors.surface} stroke={omiChartColors.tooltipBorder} />
              <text x={12} y={20} className="fill-omi-text-muted text-[12px] font-semibold">
                {hoverPoint.label}
              </text>
              <rect x={12} y={34} width={10} height={10} fill={omiChartColors.heatMuted} />
              <text x={30} y={43} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.chart.revenueYi")}
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-omi-text text-[12px] font-semibold">
                {formatRevenueYiValue(hoverPoint.revenue)}
              </text>
              <circle cx={17} cy={62} r={4} fill={omiChartColors.growth} />
              <text x={30} y={66} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.columns.yoy")}
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className={`text-[12px] font-semibold ${valueTone(hoverPoint.growthPct).replace("text-", "fill-")}`}>
                {formatPct(hoverPoint.growthPct)}
              </text>
              <text x={30} y={86} className="fill-omi-text-muted text-[11px]">
                {t("stockDetail.dataPanel.chart.monthCount", {
                  count: hoverPoint.monthCount,
                })}
              </text>
            </g>
          </g>
        ) : null}
        <rect x={left} y={top} width={width} height={height + 60} fill="transparent" pointerEvents="all" />
      </svg>
    </div>
  );
}

export function EarningsTrendChart({
  points,
  view,
}: {
  points: EarningsSeriesPoint[];
  view: EarningsView;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const t = useT();
  const chartPoints = points.slice(-36);
  const viewWidth = 860;
  const viewHeight = 360;
  const left = 64;
  const right = 82;
  const top = 54;
  const height = 240;
  const width = viewWidth - left - right;
  const epsScale = minMax(chartPoints.map((point) => point.eps));
  const growthScale = minMax(chartPoints.map((point) => point.growthPct));
  const earningsLabel =
    view === "quarterly"
      ? t("stockDetail.dataPanel.chart.quarterlyEps")
      : t("stockDetail.dataPanel.chart.annualEps");

  if (!chartPoints.length || epsScale === null) {
    return <EmptyDataState message={t("stockDetail.dataPanel.empty.earningsChart")} />;
  }

  const lineScale = growthScale ?? { min: -1, max: 1 };
  const growthPath = buildNumericLinePath(
    chartPoints,
    (point) => point.growthPct,
    lineScale,
    left,
    top,
    width,
    height
  );
  const barWidth = Math.max(4, Math.min(18, width / Math.max(chartPoints.length, 1) - 4));
  const hoverPoint = hoverIndex === null ? null : chartPoints[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, chartPoints.length, left, width);
  const hoverEpsY =
    hoverPoint?.eps === null || hoverPoint?.eps === undefined
      ? null
      : chartY(hoverPoint.eps, epsScale.min, epsScale.max, top, height);
  const hoverGrowthY =
    hoverPoint?.growthPct === null || hoverPoint?.growthPct === undefined
      ? null
      : chartY(hoverPoint.growthPct, lineScale.min, lineScale.max, top, height);
  const hoverTipWidth = 190;
  const hoverTipHeight = 112;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverGrowthY ?? hoverEpsY ?? top + height / 2, hoverTipHeight, top, height);

  return (
    <div className="border border-omi-border-subtle bg-omi-surface px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-omi-text-muted">
          <span className="h-3 w-5 rounded-sm bg-omi-heat-border" />
          {earningsLabel}
        </span>
        <span className="inline-flex items-center gap-1 text-omi-text-muted">
          <span className="h-2 w-2 rounded-full border-2 border-omi-market-up-border" />
          {t("stockDetail.dataPanel.chart.yoyPct")}
        </span>
      </div>

      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[360px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, chartPoints.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2, 3].map((tick) => {
          const y = top + (tick / 3) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke={omiChartColors.grid} />;
        })}
        <text x={left} y={20} className="fill-omi-text-muted text-[10px]">
          {t("stockDetail.dataPanel.columns.epsNtd")}
        </text>
        <text x={left + width + right} y={20} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {t("stockDetail.dataPanel.chart.yoyPct")}
        </text>
        {chartPoints.map((point, index) => {
          const value = point.eps ?? epsScale.min;
          const x = chartX(index, chartPoints.length, left, width) - barWidth / 2;
          const y = chartY(value, epsScale.min, epsScale.max, top, height);

          return (
            <rect
              key={point.period}
              x={x}
              y={y}
              width={barWidth}
              height={top + height - y}
              fill={omiChartColors.heatMuted}
              opacity="0.78"
            />
          );
        })}
        {growthPath ? (
          <path d={growthPath} fill="none" stroke={omiChartColors.growth} strokeWidth="2.4" strokeLinecap="round" />
        ) : null}
        {chartPoints.map((point, index) => {
          if (point.growthPct === null || point.growthPct === undefined) return null;
          const x = chartX(index, chartPoints.length, left, width);
          const y = chartY(point.growthPct, lineScale.min, lineScale.max, top, height);
          return <circle key={`${point.period}-growth`} cx={x} cy={y} r={3} fill={omiChartColors.surface} stroke={omiChartColors.growth} strokeWidth="2" />;
        })}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatPrice(epsScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatPrice(epsScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-omi-text-muted text-[10px]">
          {formatPct(lineScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-omi-text-muted text-[10px]">
          {formatPct(lineScale.min)}
        </text>
        <text x={left} y={top + height + 28} className="fill-omi-text-muted text-[10px]">
          {chartPoints[0]?.label}
        </text>
        <text x={left + width} y={top + height + 28} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {chartPoints[chartPoints.length - 1]?.label}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke={omiChartColors.crosshair}
              strokeDasharray="4 4"
            />
            <rect x={hoverX - 34} y={top + height + 34} width={68} height={22} rx={3} fill={omiChartColors.tooltip} />
            <text x={hoverX} y={top + height + 49} textAnchor="middle" className="fill-omi-surface text-[11px] font-semibold">
              {hoverPoint.label}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill={omiChartColors.surface} stroke={omiChartColors.tooltipBorder} />
              <text x={12} y={20} className="fill-omi-text-muted text-[12px] font-semibold">
                {hoverPoint.label}
              </text>
              <rect x={12} y={34} width={10} height={10} fill={omiChartColors.heatMuted} />
              <text x={30} y={43} className="fill-omi-text-muted text-[12px]">
                EPS
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-omi-text text-[12px] font-semibold">
                {formatPrice(hoverPoint.eps)}
              </text>
              <circle cx={17} cy={62} r={4} fill={omiChartColors.growth} />
              <text x={30} y={66} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.columns.yoy")}
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className={`text-[12px] font-semibold ${valueTone(hoverPoint.growthPct).replace("text-", "fill-")}`}>
                {formatPct(hoverPoint.growthPct)}
              </text>
              <text x={30} y={86} className="fill-omi-text-muted text-[11px]">
                ROE {formatRatioPct(hoverPoint.roe)}
              </text>
              <text x={hoverTipWidth - 12} y={86} textAnchor="end" className="fill-omi-text-muted text-[11px]">
                ROA {formatRatioPct(hoverPoint.roa)}
              </text>
            </g>
          </g>
        ) : null}
        <rect x={left} y={top} width={width} height={height + 60} fill="transparent" pointerEvents="all" />
      </svg>
    </div>
  );
}

export function ShareholdingMixedChart({ points }: { points: ShareholdingSeriesPoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const t = useT();
  const viewWidth = 860;
  const viewHeight = 330;
  const left = 64;
  const right = 86;
  const top = 50;
  const height = 220;
  const width = viewWidth - left - right;
  const largeScale = minMax(points.map((point) => point.largeRatio));
  const closeScale = minMax(points.map((point) => point.close));
  const showClose = closeScale !== null && points.some((point) => point.close !== null);

  if (points.length === 0 || largeScale === null) {
    return <EmptyDataState message={t("stockDetail.dataPanel.empty.shareholdingTrend")} />;
  }

  const closePath =
    showClose && closeScale
      ? buildLinePath(points, "close", closeScale, left, top, width, height)
      : "";
  const barWidth = Math.max(2, Math.min(10, width / Math.max(points.length, 1) - 2));
  const hoverPoint = hoverIndex === null ? null : points[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, points.length, left, width);
  const hoverLargeY =
    hoverPoint?.largeRatio === null || hoverPoint?.largeRatio === undefined
      ? null
      : chartY(hoverPoint.largeRatio, largeScale.min, largeScale.max, top, height);
  const hoverCloseY =
    hoverPoint?.close === null || hoverPoint?.close === undefined || closeScale === null
      ? null
      : chartY(hoverPoint.close, closeScale.min, closeScale.max, top, height);
  const hoverPrimaryY = hoverCloseY ?? hoverLargeY ?? top + height / 2;
  const hoverTipWidth = 168;
  const hoverTipHeight = 82;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverPrimaryY, hoverTipHeight, top, height);

  return (
    <div className="border border-omi-border-subtle bg-omi-surface px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-omi-text-muted">
          <span className="h-3 w-5 rounded-sm bg-omi-heat-border" />
          {t("stockDetail.dataPanel.chart.largeHolderPct")}
        </span>
        <span className="inline-flex items-center gap-1 text-omi-text-muted">
          <span className="h-2 w-2 rounded-full border-2 border-omi-market-up-border" />
          {t("stockDetail.dataPanel.chart.closePrice")}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[330px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, points.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2, 3].map((tick) => {
          const y = top + (tick / 3) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke={omiChartColors.grid} />;
        })}
        <text x={left} y={18} className="fill-omi-text-muted text-[10px]">
          {t("stockDetail.dataPanel.chart.largeHolderPct")}
        </text>
        <text x={left + width + right} y={18} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {t("stockDetail.dataPanel.chart.closePrice")}
        </text>
        {points.map((point, index) => {
          const value = point.largeRatio ?? largeScale.min;
          const x = chartX(index, points.length, left, width) - barWidth / 2;
          const y = chartY(value, largeScale.min, largeScale.max, top, height);
          return (
            <rect
              key={point.date}
              x={x}
              y={y}
              width={barWidth}
              height={top + height - y}
              fill={omiChartColors.heatMuted}
              opacity="0.72"
            />
          );
        })}
        {closePath ? (
          <path d={closePath} fill="none" stroke={omiChartColors.growth} strokeWidth="2" strokeLinecap="round" />
        ) : null}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {largeScale.max.toFixed(2)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {largeScale.min.toFixed(2)}
        </text>
        {closeScale ? (
          <>
            <text x={left + width + 4} y={top + 4} className="fill-omi-text-muted text-[10px]">
              {formatPrice(closeScale.max)}
            </text>
            <text x={left + width + 4} y={top + height} className="fill-omi-text-muted text-[10px]">
              {formatPrice(closeScale.min)}
            </text>
          </>
        ) : null}
        <text x={left} y={top + height + 24} className="fill-omi-text-muted text-[10px]">
          {formatCompactDate(points[0]?.date)}
        </text>
        <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatCompactDate(points[points.length - 1]?.date)}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke={omiChartColors.crosshair}
              strokeDasharray="4 4"
            />
            {hoverLargeY !== null ? (
              <g>
                <rect x={8} y={hoverLargeY - 12} width={48} height={22} rx={3} fill={omiChartColors.tooltip} />
                <text
                  x={32}
                  y={hoverLargeY + 3}
                  textAnchor="middle"
                  className="fill-omi-surface text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.largeRatio)}
                </text>
                <line
                  x1={left}
                  x2={left + width}
                  y1={hoverLargeY}
                  y2={hoverLargeY}
                  stroke={omiChartColors.crosshair}
                  strokeDasharray="4 4"
                />
              </g>
            ) : null}
            {hoverCloseY !== null ? (
              <g>
                <rect
                  x={viewWidth - 58}
                  y={hoverCloseY - 12}
                  width={50}
                  height={22}
                  rx={3}
                  fill={omiChartColors.tooltip}
                />
                <text
                  x={viewWidth - 33}
                  y={hoverCloseY + 3}
                  textAnchor="middle"
                  className="fill-omi-surface text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.close)}
                </text>
              </g>
            ) : null}
            <rect x={hoverX - 34} y={top + height + 28} width={68} height={22} rx={3} fill={omiChartColors.tooltip} />
            <text
              x={hoverX}
              y={top + height + 43}
              textAnchor="middle"
              className="fill-omi-surface text-[11px] font-semibold"
            >
              {formatCompactDate(hoverPoint.date)}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill={omiChartColors.surface} stroke={omiChartColors.tooltipBorder} />
              <text x={12} y={20} className="fill-omi-text-muted text-[12px] font-semibold">
                {formatCompactDate(hoverPoint.date)}
              </text>
              <circle cx={16} cy={40} r={4} fill={omiChartColors.heatMuted} />
              <text x={28} y={44} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.chart.largeHolderPct")}
              </text>
              <text x={hoverTipWidth - 12} y={44} textAnchor="end" className="fill-omi-text text-[12px] font-semibold">
                {formatPrice(hoverPoint.largeRatio)}
              </text>
              <circle cx={16} cy={62} r={4} fill={omiChartColors.growth} />
              <text x={28} y={66} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.chart.closePrice")}
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-omi-text text-[12px] font-semibold">
                {formatPrice(hoverPoint.close)}
              </text>
            </g>
          </g>
        ) : null}
        <rect
          x={left}
          y={top}
          width={width}
          height={height + 54}
          fill="transparent"
          pointerEvents="all"
        />
      </svg>
    </div>
  );
}

export function ShareholdingRatioChart({ points }: { points: ShareholdingSeriesPoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const t = useT();
  const viewWidth = 860;
  const viewHeight = 300;
  const left = 64;
  const right = 72;
  const top = 44;
  const height = 196;
  const width = viewWidth - left - right;
  const largeScale = minMax(points.map((point) => point.largeRatio));
  const smallScale = minMax(points.map((point) => point.smallRatio));

  if (points.length === 0 || largeScale === null || smallScale === null) {
    return <EmptyDataState message={t("stockDetail.dataPanel.empty.shareholdingRatio")} />;
  }

  const largePath = buildLinePath(points, "largeRatio", largeScale, left, top, width, height);
  const smallPath = buildLinePath(points, "smallRatio", smallScale, left, top, width, height);
  const hoverPoint = hoverIndex === null ? null : points[hoverIndex] ?? null;
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, points.length, left, width);
  const hoverLargeY =
    hoverPoint?.largeRatio === null || hoverPoint?.largeRatio === undefined
      ? null
      : chartY(hoverPoint.largeRatio, largeScale.min, largeScale.max, top, height);
  const hoverSmallY =
    hoverPoint?.smallRatio === null || hoverPoint?.smallRatio === undefined
      ? null
      : chartY(hoverPoint.smallRatio, smallScale.min, smallScale.max, top, height);
  const hoverPrimaryY = hoverLargeY ?? hoverSmallY ?? top + height / 2;
  const hoverTipWidth = 182;
  const hoverTipHeight = 82;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverPrimaryY, hoverTipHeight, top, height);

  return (
    <div className="border border-omi-border-subtle bg-omi-surface px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-omi-text-muted">
          <span className="h-2 w-2 rounded-full border-2 border-omi-heat-border" />
          {t("stockDetail.dataPanel.chart.largeHolderPct")}
        </span>
        <span className="inline-flex items-center gap-1 text-omi-text-muted">
          <span className="h-2 w-2 rounded-full border-2 border-omi-market-up-border" />
          {t("stockDetail.dataPanel.chart.smallHolderPct")}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className="h-[300px] w-full"
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, points.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
        }}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {[0, 1, 2, 3].map((tick) => {
          const y = top + (tick / 3) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke={omiChartColors.grid} />;
        })}
        <path d={largePath} fill="none" stroke={omiChartColors.heatMuted} strokeWidth="2" strokeLinecap="round" />
        <path d={smallPath} fill="none" stroke={omiChartColors.growth} strokeWidth="2" strokeLinecap="round" />
        <text x={left} y={18} className="fill-omi-text-muted text-[10px]">
          {t("stockDetail.dataPanel.chart.largeHolderPct")}
        </text>
        <text x={left + width + right} y={18} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {t("stockDetail.dataPanel.chart.smallHolderPct")}
        </text>
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {largeScale.max.toFixed(2)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {largeScale.min.toFixed(2)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-omi-text-muted text-[10px]">
          {smallScale.max.toFixed(2)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-omi-text-muted text-[10px]">
          {smallScale.min.toFixed(2)}
        </text>
        <text x={left} y={top + height + 24} className="fill-omi-text-muted text-[10px]">
          {formatCompactDate(points[0]?.date)}
        </text>
        <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatCompactDate(points[points.length - 1]?.date)}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke={omiChartColors.crosshair}
              strokeDasharray="4 4"
            />
            {hoverLargeY !== null ? (
              <g>
                <rect x={8} y={hoverLargeY - 12} width={48} height={22} rx={3} fill={omiChartColors.tooltip} />
                <text
                  x={32}
                  y={hoverLargeY + 3}
                  textAnchor="middle"
                  className="fill-omi-surface text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.largeRatio)}
                </text>
                <line
                  x1={left}
                  x2={left + width}
                  y1={hoverLargeY}
                  y2={hoverLargeY}
                  stroke={omiChartColors.crosshair}
                  strokeDasharray="4 4"
                />
              </g>
            ) : null}
            {hoverSmallY !== null ? (
              <g>
                <rect
                  x={viewWidth - 58}
                  y={hoverSmallY - 12}
                  width={50}
                  height={22}
                  rx={3}
                  fill={omiChartColors.tooltip}
                />
                <text
                  x={viewWidth - 33}
                  y={hoverSmallY + 3}
                  textAnchor="middle"
                  className="fill-omi-surface text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.smallRatio)}
                </text>
              </g>
            ) : null}
            <rect x={hoverX - 34} y={top + height + 28} width={68} height={22} rx={3} fill={omiChartColors.tooltip} />
            <text
              x={hoverX}
              y={top + height + 43}
              textAnchor="middle"
              className="fill-omi-surface text-[11px] font-semibold"
            >
              {formatCompactDate(hoverPoint.date)}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill={omiChartColors.surface} stroke={omiChartColors.tooltipBorder} />
              <text x={12} y={20} className="fill-omi-text-muted text-[12px] font-semibold">
                {formatCompactDate(hoverPoint.date)}
              </text>
              <circle cx={16} cy={40} r={4} fill={omiChartColors.heatMuted} />
              <text x={28} y={44} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.chart.largeHolderPct")}
              </text>
              <text x={hoverTipWidth - 12} y={44} textAnchor="end" className="fill-omi-text text-[12px] font-semibold">
                {formatPrice(hoverPoint.largeRatio)}
              </text>
              <circle cx={16} cy={62} r={4} fill={omiChartColors.growth} />
              <text x={28} y={66} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.chart.smallHolderPct")}
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-omi-text text-[12px] font-semibold">
                {formatPrice(hoverPoint.smallRatio)}
              </text>
            </g>
          </g>
        ) : null}
        <rect
          x={left}
          y={top}
          width={width}
          height={height + 54}
          fill="transparent"
          pointerEvents="all"
        />
      </svg>
    </div>
  );
}

export function InstitutionalFlowChart({
  points,
  title,
  netKey,
  cumulativeKey,
  activeDate,
  showXAxisLabels = false,
  onHoverPointChange,
}: {
  points: InstitutionalSeriesPoint[];
  title: string;
  netKey: InstitutionalNetKey;
  cumulativeKey: InstitutionalCumulativeKey;
  activeDate?: string | null;
  showXAxisLabels?: boolean;
  onHoverPointChange?: (point: InstitutionalSeriesPoint | null) => void;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const t = useT();
  const chartPoints = points;
  const viewWidth = 860;
  const viewHeight = showXAxisLabels ? 150 : 126;
  const left = 64;
  const right = 72;
  const top = 24;
  const height = 88;
  const width = viewWidth - left - right;
  const netValues = chartPoints
    .map((point) => point[netKey])
    .filter((value): value is number => value !== null && value !== undefined);
  const cumulativeScale = minMax(chartPoints.map((point) => point[cumulativeKey])) ?? {
    min: -1,
    max: 1,
  };
  const netMax = Math.max(...netValues.map((value) => Math.abs(value)), 1);
  const netScale = { min: -netMax, max: netMax };
  const zeroY = chartY(0, netScale.min, netScale.max, top, height);
  const barWidth = Math.max(2, Math.min(9, width / Math.max(chartPoints.length, 1) - 2));
  const cumulativePath = buildNumericLinePath(
    chartPoints,
    (point) => point[cumulativeKey],
    cumulativeScale,
    left,
    top,
    width,
    height
  );
  const latestPoint = chartPoints[chartPoints.length - 1] ?? null;
  const hoverPoint = hoverIndex === null ? null : chartPoints[hoverIndex] ?? null;
  const activeIndex = activeDate
    ? chartPoints.findIndex((point) => point.date === activeDate)
    : -1;
  const guideIndex = hoverIndex ?? (activeIndex >= 0 ? activeIndex : null);
  const guideX =
    guideIndex === null ? null : chartX(guideIndex, chartPoints.length, left, width);
  const hoverX =
    hoverIndex === null ? null : chartX(hoverIndex, chartPoints.length, left, width);
  const hoverNetY =
    hoverPoint?.[netKey] === null || hoverPoint?.[netKey] === undefined
      ? null
      : chartY(hoverPoint[netKey], netScale.min, netScale.max, top, height);
  const hoverCumY =
    hoverPoint?.[cumulativeKey] === null || hoverPoint?.[cumulativeKey] === undefined
      ? null
      : chartY(hoverPoint[cumulativeKey], cumulativeScale.min, cumulativeScale.max, top, height);
  const hoverTipWidth = 182;
  const hoverTipHeight = 82;
  const hoverTipX = hoverX === null ? 0 : tooltipX(hoverX, hoverTipWidth, viewWidth);
  const hoverTipY = tooltipY(hoverCumY ?? hoverNetY ?? top + height / 2, hoverTipHeight, top, height);

  if (!chartPoints.length) {
    return (
      <EmptyDataState
        message={t("stockDetail.dataPanel.empty.historyFor", { title })}
      />
    );
  }

  return (
    <div className="border-t border-omi-border-subtle py-3 first:border-t-0">
      <div className="mb-2 flex items-center justify-between gap-4 text-xs">
        <div className="font-semibold text-omi-text">
          {title}
          <span className={`ml-2 ${valueTone(latestPoint?.[cumulativeKey])}`}>
            {t("stockDetail.dataPanel.chart.cumulativeLots", {
              value: formatSignedLots(latestPoint?.[cumulativeKey]),
            })}
          </span>
        </div>
        <div>
          <span className="text-omi-text-muted">{t("stockDetail.dataPanel.chart.netBuySell")}</span>
          <span className={valueTone(latestPoint?.[netKey])}>
            {formatSignedLots(latestPoint?.[netKey])}{t("stockDetail.dataPanel.units.lots")}
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${viewWidth} ${viewHeight}`}
        className={showXAxisLabels ? "h-[150px] w-full" : "h-[126px] w-full"}
        onMouseMove={(event) => {
          const nextIndex = nearestChartIndex(event, chartPoints.length, left, width, viewWidth);
          setHoverIndex((current) => (current === nextIndex ? current : nextIndex));
          onHoverPointChange?.(chartPoints[nextIndex] ?? null);
        }}
        onMouseLeave={() => {
          setHoverIndex(null);
          onHoverPointChange?.(null);
        }}
      >
        {[0, 1, 2].map((tick) => {
          const y = top + (tick / 2) * height;
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke={omiChartColors.grid} />;
        })}
        <line x1={left} x2={left + width} y1={zeroY} y2={zeroY} stroke={omiChartColors.crosshair} />
        {chartPoints.map((point, index) => {
          const value = point[netKey] ?? 0;
          const x = chartX(index, chartPoints.length, left, width) - barWidth / 2;
          const y = chartY(value, netScale.min, netScale.max, top, height);
          return (
            <rect
              key={point.date}
              x={x}
              y={Math.min(y, zeroY)}
              width={barWidth}
              height={Math.max(1, Math.abs(zeroY - y))}
              fill={value >= 0 ? omiChartColors.marketUpFlash : omiChartColors.marketDownFlash}
              opacity="0.78"
            />
          );
        })}
        {cumulativePath ? (
          <path d={cumulativePath} fill="none" stroke={omiChartColors.cumulative} strokeWidth="2" strokeLinecap="round" />
        ) : null}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatLots(netScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-omi-text-muted text-[10px]">
          {formatSignedLots(netScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-omi-text-muted text-[10px]">
          {formatLots(cumulativeScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-omi-text-muted text-[10px]">
          {formatSignedLots(cumulativeScale.min)}
        </text>
        {showXAxisLabels ? (
          <>
            <text x={left} y={top + height + 24} className="fill-omi-text-muted text-[10px]">
              {formatMonthDay(chartPoints[0]?.date)}
            </text>
            <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-omi-text-muted text-[10px]">
              {formatMonthDay(chartPoints[chartPoints.length - 1]?.date)}
            </text>
          </>
        ) : null}
        {guideX !== null ? (
          <g pointerEvents="none">
            <line
              x1={guideX}
              x2={guideX}
              y1={top}
              y2={top + height}
              stroke={omiChartColors.crosshair}
              strokeDasharray="4 4"
            />
          </g>
        ) : null}
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            {hoverNetY !== null ? (
              <g>
                <rect x={8} y={hoverNetY - 12} width={52} height={22} rx={3} fill={omiChartColors.tooltip} />
                <text x={34} y={hoverNetY + 3} textAnchor="middle" className="fill-omi-surface text-[11px] font-semibold">
                  {formatSignedLots(hoverPoint[netKey])}
                </text>
              </g>
            ) : null}
            {hoverCumY !== null ? (
              <g>
                <rect x={viewWidth - 62} y={hoverCumY - 12} width={54} height={22} rx={3} fill={omiChartColors.tooltip} />
                <text x={viewWidth - 35} y={hoverCumY + 3} textAnchor="middle" className="fill-omi-surface text-[11px] font-semibold">
                  {formatSignedLots(hoverPoint[cumulativeKey])}
                </text>
              </g>
            ) : null}
            {showXAxisLabels ? (
              <>
                <rect x={hoverX - 28} y={top + height + 28} width={56} height={20} rx={3} fill={omiChartColors.tooltip} />
                <text x={hoverX} y={top + height + 42} textAnchor="middle" className="fill-omi-surface text-[11px] font-semibold">
                  {formatMonthDay(hoverPoint.date)}
                </text>
              </>
            ) : null}
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill={omiChartColors.surface} stroke={omiChartColors.tooltipBorder} />
              <text x={12} y={20} className="fill-omi-text-muted text-[12px] font-semibold">
                {formatDate(hoverPoint.date)}
              </text>
              <rect x={12} y={34} width={8} height={8} fill={(hoverPoint[netKey] ?? 0) >= 0 ? omiChartColors.marketUpFlash : omiChartColors.marketDownFlash} />
              <text x={28} y={43} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.chart.netBuySellLots")}
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-omi-text text-[12px] font-semibold">
                {formatSignedLots(hoverPoint[netKey])}
              </text>
              <circle cx={16} cy={62} r={4} fill={omiChartColors.cumulative} />
              <text x={28} y={66} className="fill-omi-text-muted text-[12px]">
                {t("stockDetail.dataPanel.chart.cumulativeLotsColumn")}
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-omi-text text-[12px] font-semibold">
                {formatSignedLots(hoverPoint[cumulativeKey])}
              </text>
            </g>
          </g>
        ) : null}
        <rect x={left} y={top} width={width} height={height + 48} fill="transparent" pointerEvents="all" />
      </svg>
    </div>
  );
}

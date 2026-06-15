"use client";

import { LoadingDots } from "@/components/LoadingPlaceholders";
import PriceUpdatePulse from "@/components/PriceUpdatePulse";
import { fetchJson } from "@/lib/api";
import { getJobResultStatus } from "@/lib/jobs";
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

export function formatSignedContracts(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value)}口`;
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

  return new Intl.DateTimeFormat("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Taipei",
  }).format(date);
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

export function formatPanelJobProgress(label: string, job: JobRunRead) {
  const total = Math.max(job.progress_total || 1, 1);
  const current = Math.min(Math.max(job.progress_current || 0, 0), total);
  const status = getJobResultStatus(job) ?? job.status;

  if (status === "error") {
    return `${label}：補齊失敗，詳見左側更新狀態`;
  }

  if (status === "partial_success") {
    return `${label}：部分完成，詳見左側更新狀態`;
  }

  if (status === "success") {
    return `${label}：補齊完成，詳見左側更新狀態`;
  }

  return `${label}：補齊中，進度 ${current}/${total}，詳見左側更新狀態`;
}

export function formatBackfillOutcome(job: JobRunRead, label: string) {
  const status = getJobResultStatus(job);
  const insertedCount =
    readBackfillCount(job.result, "inserted_count") ??
    readBackfillCount(job.result, "refreshed_count");
  const skippedCount =
    readBackfillCount(job.result, "skipped_existing_count") ??
    readBackfillCount(job.result, "skipped_count");
  const errorCount = readBackfillCount(job.result, "error_count");
  const details = [
    insertedCount !== null && insertedCount > 0 ? `更新 ${insertedCount}` : null,
    skippedCount !== null && skippedCount > 0 ? `已存在 ${skippedCount}` : null,
    errorCount !== null && errorCount > 0 ? `失敗 ${errorCount}` : null,
  ].filter(Boolean);
  const suffix =
    status === "partial_success"
      ? "部分完成"
      : status === "skipped"
        ? "無需補齊"
        : status === "error"
          ? "失敗"
          : "補齊完成";

  return `${label}${suffix}${details.length ? `（${details.join("、")}）` : ""}`;
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
  if (value === null || value === undefined) return "text-slate-500";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
}

export type PriceLimitStatus = "limit_up" | "limit_down" | null;

export function estimatedPriceLimitStatus(value: number | null | undefined): PriceLimitStatus {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  if (value >= 9.5) return "limit_up";
  if (value <= -9.5) return "limit_down";
  return null;
}

export function priceLimitTone(status: PriceLimitStatus, fallback: number | null | undefined) {
  if (status === "limit_up") return "text-red-600";
  if (status === "limit_down") return "text-emerald-600";
  return valueTone(fallback);
}

export function priceLimitBoxClass(status: PriceLimitStatus) {
  if (status === "limit_up") {
    return "rounded-[4px] bg-red-500 px-3 py-2 text-white shadow-sm";
  }

  if (status === "limit_down") {
    return "rounded-[4px] bg-emerald-500 px-3 py-2 text-white shadow-sm";
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

export function technicalToneClass(tone: TechnicalTone) {
  if (tone === "positive") return "text-red-600";
  if (tone === "negative") return "text-emerald-600";
  if (tone === "warning") return "text-amber-600";
  return "text-slate-700";
}

export function semanticTechnicalTone(tone: string | null | undefined): TechnicalTone {
  if (tone === "positive" || tone === "negative" || tone === "warning") return tone;
  return "neutral";
}

export function semanticBadgeToneClass(tone: string | null | undefined) {
  if (tone === "positive") return "text-red-700 bg-red-50";
  if (tone === "negative") return "text-emerald-700 bg-emerald-50";
  if (tone === "warning") return "text-amber-700 bg-amber-50";
  return "text-slate-600 bg-slate-100";
}

export function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function mapBackendTechnicalReport(report: StockTechnicalReportRead): TechnicalReport {
  return {
    title: report.title,
    summary: report.summary,
    value: report.value,
    valueLabel: report.value_label,
    score: report.score,
    rows: report.rows.map((row) => ({
      title: row.label,
      description: row.description,
      value: row.display_value,
      pulseValue: numberValue(row.value),
      direction: row.direction,
      tone: semanticTechnicalTone(row.tone),
    })),
    badges: report.badges.map((badge) => ({
      label: badge.label,
      tone: semanticBadgeToneClass(badge.tone),
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
    <div className={`omi-technical-row omi-technical-row-${tone} flex items-start justify-between gap-4 border-t border-slate-100 py-2 first:border-t-0 first:pt-0`}>
      <div className="min-w-0">
        <div className="text-sm font-bold text-slate-950">{title}</div>
        <div className="mt-0.5 text-xs leading-4 text-slate-500">{description}</div>
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
  return (
    <>
      <div className="omi-technical-summary border-b border-slate-200 px-5 py-3">
        <div className="flex items-center justify-between gap-4">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            Technical
          </div>
          <LoadingDots label="Technical 分析讀取中" />
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
              className="omi-technical-loading-row flex items-start justify-between gap-4 border-t border-slate-100 py-2 first:border-t-0 first:pt-0"
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

        <div className="mt-3 border-t border-slate-200 pt-3">
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

export function overnightConfidenceLabel(value: string | null | undefined) {
  if (value === "high") return "高信心";
  if (value === "medium") return "中信心";
  if (value === "low") return "低信心";
  return "信心待確認";
}

export function OvernightImpactPanel({
  report,
  loadState,
}: {
  report: OvernightImpactRead | null;
  loadState: LoadState;
}) {
  if (loadState === "idle") return null;

  if (loadState === "loading") {
    return (
      <div className="mt-3 border-t border-slate-200 pt-3">
        <div className="flex items-center justify-between gap-3 text-xs">
          <div>
            <div className="font-bold uppercase tracking-[0.14em] text-slate-500">
              Overnight
            </div>
            <div className="mt-1 text-slate-500">美股隔夜影響讀取中</div>
          </div>
          <LoadingDots label="讀取中" />
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mt-3 border-t border-slate-200 pt-3">
        <div className="flex items-start justify-between gap-4 text-xs">
          <div>
            <div className="font-bold uppercase tracking-[0.14em] text-slate-500">
              Overnight
            </div>
            <div className="mt-1 text-sm font-bold text-slate-950">美股隔夜資料不足</div>
            <div className="mt-0.5 text-slate-500">暫不納入台股映射判斷</div>
          </div>
          <div className="text-right font-bold text-slate-400">-</div>
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
    <div className="mt-3 border-t border-slate-200 pt-3">
      <div className="omi-overnight-impact flex items-start justify-between gap-4 text-xs">
        <div className="min-w-0">
          <div className="font-bold uppercase tracking-[0.14em] text-slate-500">
            Overnight
          </div>
          <div className="mt-0.5 text-sm font-bold text-slate-950">{report.title}</div>
          <div className="mt-0.5 max-h-8 overflow-hidden leading-4 text-slate-500">{report.summary}</div>
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
          <div className="text-xs font-medium text-slate-500">{overnightConfidenceLabel(report.confidence)}</div>
        </div>
      </div>

      {driverRows.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {driverRows.map((item) => (
            <span
              key={item.key}
              className="inline-flex items-center gap-1 bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-600"
            >
              <span>{item.label}</span>
              <span className={valueTone(item.value)}>{formatPct(item.value)}</span>
            </span>
          ))}
        </div>
      ) : null}

      {hasWarning ? (
        <div className="mt-2 text-[11px] leading-4 text-amber-700">
          {report.as_of ? `資料日期 ${formatDate(report.as_of)}，` : ""}
          {report.warnings[0] ?? "資料完整度偏低，僅作參考"}
        </div>
      ) : null}
    </div>
  );
}

export function marketRegimeLabel(index: MarketIndexSnapshot | null | undefined) {
  if (!index || index.close === null || index.close === undefined) return "資料不足";

  if (index.price_vs_ma20 !== null && index.price_vs_ma20 !== undefined) {
    if (index.price_vs_ma20 > 1) return "站上 MA20";
    if (index.price_vs_ma20 < -1) return "跌破 MA20";
  }

  if (index.change_pct !== null && index.change_pct !== undefined) {
    if (index.change_pct > 0) return "短線偏多";
    if (index.change_pct < 0) return "短線偏弱";
  }

  return "中性震盪";
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
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
          Market
        </div>
        <div className="mt-2 flex items-end justify-between gap-4">
          <div>
            <div className="text-xl font-bold text-slate-950">{marketLabel}指數列表</div>
            {loadState === "loading" ? (
              <div className="mt-1 inline-flex items-center gap-2 text-xs text-slate-500">
                讀取中
                <LoadingDots label={`${marketLabel}指數列表讀取中`} />
              </div>
            ) : (
              <div className="mt-1 text-xs text-slate-500">{`${items.length} 檔指數`}</div>
            )}
          </div>
          <div className="text-right text-xs font-semibold text-slate-500">
            {marketLabel}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
        {items.length > 0 ? (
          items.map((item) => (
            <div
              key={`${item.market}-${item.rank}-${item.name}`}
              className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-slate-100 py-2 text-sm first:border-t-0"
            >
              <div className="min-w-0">
                <div className="truncate font-semibold text-slate-900">
                  {item.rank}. {item.name}
                </div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {item.trade_date ?? "-"}
                </div>
              </div>
              <div className="text-right font-semibold text-slate-950">
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
                className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-slate-100 py-2 first:border-t-0"
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
          <div className="py-10 text-center text-sm text-slate-500">
            尚無指數列表資料
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
  const isToday = timeframe === "today";
  const breadth = index?.breadth ?? null;
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
    <section className="border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            Index Data
          </div>
          <div className="mt-1 text-lg font-bold text-slate-950">指數詳細數據</div>
        </div>
        <div className="text-right text-xs text-slate-500">
          更新 {formatDateTime(index?.as_of)}
        </div>
      </div>

      <div className="grid gap-2 border-b border-slate-200 p-5 sm:grid-cols-2 xl:grid-cols-4">
        <IndexMetricCard
          label="開盤"
          value={formatPrice(open)}
          tone={valueTone(open !== null && reference !== null ? open - reference : null)}
        />
        <IndexMetricCard
          label="最高"
          value={formatPrice(high)}
          tone={valueTone(high !== null && reference !== null ? high - reference : null)}
        />
        <IndexMetricCard
          label="最低"
          value={formatPrice(low)}
          tone={valueTone(low !== null && reference !== null ? low - reference : null)}
        />
        <IndexMetricCard label="參考" value={formatPrice(reference)} />
        <IndexMetricCard label="成交金額(億)" value={formatTradeValueYi(tradeValue)} />
        <IndexMetricCard label="估計金額(億)" value={formatTradeValueYi(estimatedTradeValue)} />
        <IndexMetricCard label="上漲家" value={formatNumber(breadth?.advance_count)} tone="text-red-600" />
        <IndexMetricCard label="下跌家" value={formatNumber(breadth?.decline_count)} tone="text-emerald-600" />
        <IndexMetricCard label="漲停家" value={formatNumber(breadth?.limit_up_count)} tone="text-red-600" />
        <IndexMetricCard label="跌停家" value={formatNumber(breadth?.limit_down_count)} tone="text-emerald-600" />
        <IndexMetricCard label="平盤家" value={formatNumber(breadth?.unchanged_count)} />
        <IndexMetricCard label="總家數" value={formatNumber(breadth?.total_count)} />
      </div>

      <div className="border-b border-slate-200 px-5 py-4">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <div className="text-xs font-bold text-slate-950">籌碼日報</div>
            <div className="mt-0.5 text-xs text-slate-500">
              大盤期貨未平倉、法人買賣超與信用交易摘要
            </div>
          </div>
          <div className="text-xs text-slate-500">
            資料日 {marketChip?.trade_date ? formatDate(marketChip.trade_date) : "-"}
          </div>
        </div>
        {marketChipLoadState === "loading" ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="omi-skeleton h-3 w-24" />
                <div className="omi-skeleton mt-2 h-4 w-20" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <IndexMetricCard
              label="外資淨未平倉"
              value={formatSignedContracts(marketChip?.foreign_futures_net_oi)}
              tone={valueTone(marketChip?.foreign_futures_net_oi)}
            />
            <IndexMetricCard
              label="外資未平倉加減"
              value={formatSignedContracts(marketChip?.foreign_futures_net_oi_change)}
              tone={valueTone(marketChip?.foreign_futures_net_oi_change)}
            />
            <IndexMetricCard
              label="散戶淨未平倉"
              value={formatSignedContracts(marketChip?.retail_futures_net_oi)}
              tone={valueTone(marketChip?.retail_futures_net_oi)}
            />
            <IndexMetricCard
              label="散戶未平倉加減"
              value={formatSignedContracts(marketChip?.retail_futures_net_oi_change)}
              tone={valueTone(marketChip?.retail_futures_net_oi_change)}
            />
            <IndexMetricCard
              label="三大法人買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.total_institutional_net_value)}
              tone={valueTone(marketChip?.total_institutional_net_value)}
            />
            <IndexMetricCard
              label="外資買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.foreign_investor_net_value)}
              tone={valueTone(marketChip?.foreign_investor_net_value)}
            />
            <IndexMetricCard
              label="投信買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.investment_trust_net_value)}
              tone={valueTone(marketChip?.investment_trust_net_value)}
            />
            <IndexMetricCard
              label="自營商買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.dealer_net_value)}
              tone={valueTone(marketChip?.dealer_net_value)}
            />
            <IndexMetricCard
              label="官股買賣超(億)"
              value={formatSignedTradeValueYi(marketChip?.government_bank_net_value)}
              tone={valueTone(marketChip?.government_bank_net_value)}
            />
            <IndexMetricCard
              label="融資變動(億)"
              value={formatSignedTradeValueYi(marketChip?.margin_balance_change_value)}
              tone={valueTone(marketChip?.margin_balance_change_value)}
            />
            <IndexMetricCard
              label="融資變動(張)"
              value={formatSignedLots(marketChip?.margin_balance_change_shares)}
              tone={valueTone(marketChip?.margin_balance_change_shares)}
            />
            <IndexMetricCard
              label="融券變動(張)"
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

      <div className="px-5 py-3 text-xs text-slate-500">
        {breadth?.source
          ? `市場廣度來源 ${breadth.source}；貢獻排行為估算值`
          : "市場廣度待資料更新"}
      </div>
    </section>
  );
}

export function IndexMetricCard({
  label,
  value,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
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
  return (
    <div className="min-w-0">
      <div className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-slate-500">
        {title}
      </div>
      <div className="overflow-hidden border border-slate-200">
        {items.length > 0 ? (
          items.map((item) => (
            <div
              key={`${title}-${item.stock_id}`}
              className="grid grid-cols-[34px_minmax(0,1fr)_82px_88px] items-center border-b border-slate-100 px-3 py-2 text-xs last:border-b-0"
            >
              <div className="text-slate-500">#{item.rank}</div>
              <div className="min-w-0">
                <div className="truncate font-semibold text-slate-950">
                  {item.stock_id} {item.stock_name ?? ""}
                </div>
                <div className="mt-0.5 text-slate-500">
                  {formatPrice(item.close)} / {formatPct(item.change_pct)}
                </div>
              </div>
              <div className={`text-right font-bold ${tone}`}>
                {formatContributionPoint(item.contribution_points)}
              </div>
              <div className="text-right text-slate-600">
                {formatTradeValueYi(item.trade_value)}
              </div>
            </div>
          ))
        ) : (
          <div className="px-3 py-8 text-center text-sm text-slate-500">尚無資料</div>
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
  return (
    <div className="border-b border-slate-200 px-5 py-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
            Contribution
          </div>
          <div className="mt-1 text-base font-bold text-slate-950">個股貢獻排行</div>
        </div>
        <div className="text-right text-xs text-slate-500">
          {loadState === "loading"
            ? "讀取中"
            : contributions?.trade_date
              ? `${contributions.trade_date} · 點數估算`
              : "點數估算"}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ContributionColumn
          title="正貢獻"
          items={contributions?.positive ?? []}
          tone="text-red-600"
        />
        <ContributionColumn
          title="負貢獻"
          items={contributions?.negative ?? []}
          tone="text-emerald-600"
        />
      </div>
    </div>
  );
}

export function MetricRow({
  label,
  value,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-slate-100 py-2 text-xs">
      <span className="text-slate-500">{label}</span>
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
    <div className="border border-slate-200 bg-white px-3 py-2">
      <div className="text-xs font-bold text-slate-900">{title}</div>
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
        "omi-data-tab flex h-11 min-w-0 flex-1 items-center justify-center gap-2 border-r border-slate-200 text-sm font-semibold transition last:border-r-0",
        active
          ? "omi-data-tab-active bg-white text-slate-950"
          : "bg-slate-50 text-slate-500 hover:bg-white hover:text-slate-900",
      ].join(" ")}
    >
      <DataTabIcon type={tab.key} />
      <span>{tab.label}</span>
    </button>
  );
}

export function EmptyDataState({ message }: { message: string }) {
  return (
    <div className="border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
      {message}
    </div>
  );
}

export function DataPanelLoadingState({ message }: { message: string }) {
  return (
    <div className="omi-tab-panel border border-slate-200 bg-white px-4 py-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div className="inline-flex min-w-0 items-center gap-2 text-sm font-semibold text-slate-700">
          <span className="truncate">{message}</span>
          <LoadingDots label={message} />
        </div>
        <div className="h-1.5 w-20 overflow-hidden bg-slate-100">
          <div className="omi-loading-bar h-full w-1/2 bg-slate-900" />
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
      <div className="h-0.5 overflow-hidden bg-slate-100">
        <div className="omi-loading-bar h-full w-1/3 bg-red-700" />
      </div>
      {message ? (
        <div className="absolute right-0 top-2 max-w-[70%] truncate bg-white/90 px-2 py-1 text-[11px] font-medium text-slate-500 shadow-sm ring-1 ring-slate-200">
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
      <span className="w-24 shrink-0 text-right font-semibold text-slate-600">{label}</span>
      <div className="grid flex-1 grid-cols-6 overflow-hidden border border-slate-400">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={[
              "h-7 border-r border-slate-400 text-xs font-semibold last:border-r-0",
              value === option
                ? "bg-slate-700 text-white"
                : "bg-white text-slate-700 hover:bg-slate-50",
            ].join(" ")}
          >
            {option}
          </button>
        ))}
      </div>
      <span className="w-4 shrink-0 text-slate-500">{suffix}</span>
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

  if (!chartPoints.length || revenueScale === null) {
    return <EmptyDataState message="尚無營收圖表資料" />;
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
    <div className="border border-slate-200 bg-white px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-3 w-5 rounded-sm bg-orange-300" />
          {view === "monthly" ? "單月營收(億)" : view === "quarterly" ? "單季營收(億)" : "年度營收(億)"}
        </span>
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-red-400" />
          年增(%)
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
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <text x={left} y={20} className="fill-slate-500 text-[10px]">
          營收(億)
        </text>
        <text x={left + width + right} y={20} textAnchor="end" className="fill-slate-500 text-[10px]">
          年增(%)
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
              fill="#fdba74"
              opacity="0.76"
            />
          );
        })}
        {growthPath ? (
          <path d={growthPath} fill="none" stroke="#ff5b5b" strokeWidth="2.4" strokeLinecap="round" />
        ) : null}
        {chartPoints.map((point, index) => {
          if (point.growthPct === null || point.growthPct === undefined) return null;
          const x = chartX(index, chartPoints.length, left, width);
          const y = chartY(point.growthPct, lineScale.min, lineScale.max, top, height);
          return <circle key={`${point.period}-growth`} cx={x} cy={y} r={3} fill="white" stroke="#ff5b5b" strokeWidth="2" />;
        })}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatRevenueYiValue(revenueScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatRevenueYiValue(revenueScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
          {formatPct(lineScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
          {formatPct(lineScale.min)}
        </text>
        <text x={left} y={top + height + 28} className="fill-slate-500 text-[10px]">
          {chartPoints[0]?.label}
        </text>
        <text x={left + width} y={top + height + 28} textAnchor="end" className="fill-slate-500 text-[10px]">
          {chartPoints[chartPoints.length - 1]?.label}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            <rect x={hoverX - 34} y={top + height + 34} width={68} height={22} rx={3} fill="#6b7280" />
            <text x={hoverX} y={top + height + 49} textAnchor="middle" className="fill-white text-[11px] font-semibold">
              {hoverPoint.label}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {hoverPoint.label}
              </text>
              <rect x={12} y={34} width={10} height={10} fill="#fdba74" />
              <text x={30} y={43} className="fill-slate-600 text-[12px]">
                營收(億)
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatRevenueYiValue(hoverPoint.revenue)}
              </text>
              <circle cx={17} cy={62} r={4} fill="#ff5b5b" />
              <text x={30} y={66} className="fill-slate-600 text-[12px]">
                年增
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className={`text-[12px] font-semibold ${valueTone(hoverPoint.growthPct).replace("text-", "fill-")}`}>
                {formatPct(hoverPoint.growthPct)}
              </text>
              <text x={30} y={86} className="fill-slate-500 text-[11px]">
                月數 {hoverPoint.monthCount}
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

  if (!chartPoints.length || epsScale === null) {
    return <EmptyDataState message="尚無盈餘圖表資料" />;
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
    <div className="border border-slate-200 bg-white px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-3 w-5 rounded-sm bg-orange-300" />
          {view === "quarterly" ? "每股盈餘" : "年度EPS"}
        </span>
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-red-400" />
          年增(%)
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
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <text x={left} y={20} className="fill-slate-500 text-[10px]">
          EPS(元)
        </text>
        <text x={left + width + right} y={20} textAnchor="end" className="fill-slate-500 text-[10px]">
          年增(%)
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
              fill="#fdba74"
              opacity="0.78"
            />
          );
        })}
        {growthPath ? (
          <path d={growthPath} fill="none" stroke="#ff5b5b" strokeWidth="2.4" strokeLinecap="round" />
        ) : null}
        {chartPoints.map((point, index) => {
          if (point.growthPct === null || point.growthPct === undefined) return null;
          const x = chartX(index, chartPoints.length, left, width);
          const y = chartY(point.growthPct, lineScale.min, lineScale.max, top, height);
          return <circle key={`${point.period}-growth`} cx={x} cy={y} r={3} fill="white" stroke="#ff5b5b" strokeWidth="2" />;
        })}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatPrice(epsScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatPrice(epsScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
          {formatPct(lineScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
          {formatPct(lineScale.min)}
        </text>
        <text x={left} y={top + height + 28} className="fill-slate-500 text-[10px]">
          {chartPoints[0]?.label}
        </text>
        <text x={left + width} y={top + height + 28} textAnchor="end" className="fill-slate-500 text-[10px]">
          {chartPoints[chartPoints.length - 1]?.label}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            <rect x={hoverX - 34} y={top + height + 34} width={68} height={22} rx={3} fill="#6b7280" />
            <text x={hoverX} y={top + height + 49} textAnchor="middle" className="fill-white text-[11px] font-semibold">
              {hoverPoint.label}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {hoverPoint.label}
              </text>
              <rect x={12} y={34} width={10} height={10} fill="#fdba74" />
              <text x={30} y={43} className="fill-slate-600 text-[12px]">
                EPS
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatPrice(hoverPoint.eps)}
              </text>
              <circle cx={17} cy={62} r={4} fill="#ff5b5b" />
              <text x={30} y={66} className="fill-slate-600 text-[12px]">
                年增
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className={`text-[12px] font-semibold ${valueTone(hoverPoint.growthPct).replace("text-", "fill-")}`}>
                {formatPct(hoverPoint.growthPct)}
              </text>
              <text x={30} y={86} className="fill-slate-500 text-[11px]">
                ROE {formatRatioPct(hoverPoint.roe)}
              </text>
              <text x={hoverTipWidth - 12} y={86} textAnchor="end" className="fill-slate-500 text-[11px]">
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
    return <EmptyDataState message="尚無股權分散趨勢資料" />;
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
    <div className="border border-slate-200 bg-white px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-3 w-5 rounded-sm bg-orange-300" />
          大股東持股(%)
        </span>
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-red-400" />
          收盤價
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
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <text x={left} y={18} className="fill-slate-500 text-[10px]">
          大股東持股(%)
        </text>
        <text x={left + width + right} y={18} textAnchor="end" className="fill-slate-500 text-[10px]">
          收盤價
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
              fill="#fdba74"
              opacity="0.72"
            />
          );
        })}
        {closePath ? (
          <path d={closePath} fill="none" stroke="#ff5b5b" strokeWidth="2" strokeLinecap="round" />
        ) : null}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {largeScale.max.toFixed(2)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {largeScale.min.toFixed(2)}
        </text>
        {closeScale ? (
          <>
            <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
              {formatPrice(closeScale.max)}
            </text>
            <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
              {formatPrice(closeScale.min)}
            </text>
          </>
        ) : null}
        <text x={left} y={top + height + 24} className="fill-slate-500 text-[10px]">
          {formatCompactDate(points[0]?.date)}
        </text>
        <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatCompactDate(points[points.length - 1]?.date)}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            {hoverLargeY !== null ? (
              <g>
                <rect x={8} y={hoverLargeY - 12} width={48} height={22} rx={3} fill="#6b7280" />
                <text
                  x={32}
                  y={hoverLargeY + 3}
                  textAnchor="middle"
                  className="fill-white text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.largeRatio)}
                </text>
                <line
                  x1={left}
                  x2={left + width}
                  y1={hoverLargeY}
                  y2={hoverLargeY}
                  stroke="#94a3b8"
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
                  fill="#6b7280"
                />
                <text
                  x={viewWidth - 33}
                  y={hoverCloseY + 3}
                  textAnchor="middle"
                  className="fill-white text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.close)}
                </text>
              </g>
            ) : null}
            <rect x={hoverX - 34} y={top + height + 28} width={68} height={22} rx={3} fill="#6b7280" />
            <text
              x={hoverX}
              y={top + height + 43}
              textAnchor="middle"
              className="fill-white text-[11px] font-semibold"
            >
              {formatCompactDate(hoverPoint.date)}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {formatCompactDate(hoverPoint.date)}
              </text>
              <circle cx={16} cy={40} r={4} fill="#fdba74" />
              <text x={28} y={44} className="fill-slate-600 text-[12px]">
                大股東持股(%)
              </text>
              <text x={hoverTipWidth - 12} y={44} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatPrice(hoverPoint.largeRatio)}
              </text>
              <circle cx={16} cy={62} r={4} fill="#ff5b5b" />
              <text x={28} y={66} className="fill-slate-600 text-[12px]">
                收盤價
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
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
    return <EmptyDataState message="尚無大戶/小股東持股比例資料" />;
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
    <div className="border border-slate-200 bg-white px-4 py-5">
      <div className="mb-3 flex items-center justify-center gap-4 text-xs">
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-orange-300" />
          大股東持股(%)
        </span>
        <span className="inline-flex items-center gap-1 text-slate-600">
          <span className="h-2 w-2 rounded-full border-2 border-red-400" />
          小股東持股(%)
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
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <path d={largePath} fill="none" stroke="#fdba74" strokeWidth="2" strokeLinecap="round" />
        <path d={smallPath} fill="none" stroke="#ff5b5b" strokeWidth="2" strokeLinecap="round" />
        <text x={left} y={18} className="fill-slate-500 text-[10px]">
          大股東持股(%)
        </text>
        <text x={left + width + right} y={18} textAnchor="end" className="fill-slate-500 text-[10px]">
          小股東持股(%)
        </text>
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {largeScale.max.toFixed(2)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {largeScale.min.toFixed(2)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
          {smallScale.max.toFixed(2)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
          {smallScale.min.toFixed(2)}
        </text>
        <text x={left} y={top + height + 24} className="fill-slate-500 text-[10px]">
          {formatCompactDate(points[0]?.date)}
        </text>
        <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatCompactDate(points[points.length - 1]?.date)}
        </text>
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={top}
              y2={top + height}
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
            {hoverLargeY !== null ? (
              <g>
                <rect x={8} y={hoverLargeY - 12} width={48} height={22} rx={3} fill="#6b7280" />
                <text
                  x={32}
                  y={hoverLargeY + 3}
                  textAnchor="middle"
                  className="fill-white text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.largeRatio)}
                </text>
                <line
                  x1={left}
                  x2={left + width}
                  y1={hoverLargeY}
                  y2={hoverLargeY}
                  stroke="#94a3b8"
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
                  fill="#6b7280"
                />
                <text
                  x={viewWidth - 33}
                  y={hoverSmallY + 3}
                  textAnchor="middle"
                  className="fill-white text-[11px] font-semibold"
                >
                  {formatPrice(hoverPoint.smallRatio)}
                </text>
              </g>
            ) : null}
            <rect x={hoverX - 34} y={top + height + 28} width={68} height={22} rx={3} fill="#6b7280" />
            <text
              x={hoverX}
              y={top + height + 43}
              textAnchor="middle"
              className="fill-white text-[11px] font-semibold"
            >
              {formatCompactDate(hoverPoint.date)}
            </text>
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {formatCompactDate(hoverPoint.date)}
              </text>
              <circle cx={16} cy={40} r={4} fill="#fdba74" />
              <text x={28} y={44} className="fill-slate-600 text-[12px]">
                大股東持股(%)
              </text>
              <text x={hoverTipWidth - 12} y={44} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatPrice(hoverPoint.largeRatio)}
              </text>
              <circle cx={16} cy={62} r={4} fill="#ff5b5b" />
              <text x={28} y={66} className="fill-slate-600 text-[12px]">
                小股東持股(%)
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
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
    return <EmptyDataState message={`${title} 尚無歷史資料`} />;
  }

  return (
    <div className="border-t border-slate-200 py-3 first:border-t-0">
      <div className="mb-2 flex items-center justify-between gap-4 text-xs">
        <div className="font-semibold text-slate-900">
          {title}
          <span className={`ml-2 ${valueTone(latestPoint?.[cumulativeKey])}`}>
            累計 {formatSignedLots(latestPoint?.[cumulativeKey])}張
          </span>
        </div>
        <div>
          <span className="text-slate-500">買賣超：</span>
          <span className={valueTone(latestPoint?.[netKey])}>
            {formatSignedLots(latestPoint?.[netKey])}張
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
          return <line key={tick} x1={left} x2={left + width} y1={y} y2={y} stroke="#e2e8f0" />;
        })}
        <line x1={left} x2={left + width} y1={zeroY} y2={zeroY} stroke="#94a3b8" />
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
              fill={value >= 0 ? "#ef4444" : "#10b981"}
              opacity="0.78"
            />
          );
        })}
        {cumulativePath ? (
          <path d={cumulativePath} fill="none" stroke="#93c5fd" strokeWidth="2" strokeLinecap="round" />
        ) : null}
        <text x={left - 4} y={top + 4} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatLots(netScale.max)}
        </text>
        <text x={left - 4} y={top + height} textAnchor="end" className="fill-slate-500 text-[10px]">
          {formatSignedLots(netScale.min)}
        </text>
        <text x={left + width + 4} y={top + 4} className="fill-slate-500 text-[10px]">
          {formatLots(cumulativeScale.max)}
        </text>
        <text x={left + width + 4} y={top + height} className="fill-slate-500 text-[10px]">
          {formatSignedLots(cumulativeScale.min)}
        </text>
        {showXAxisLabels ? (
          <>
            <text x={left} y={top + height + 24} className="fill-slate-500 text-[10px]">
              {formatMonthDay(chartPoints[0]?.date)}
            </text>
            <text x={left + width} y={top + height + 24} textAnchor="end" className="fill-slate-500 text-[10px]">
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
              stroke="#94a3b8"
              strokeDasharray="4 4"
            />
          </g>
        ) : null}
        {hoverPoint && hoverX !== null ? (
          <g pointerEvents="none">
            {hoverNetY !== null ? (
              <g>
                <rect x={8} y={hoverNetY - 12} width={52} height={22} rx={3} fill="#6b7280" />
                <text x={34} y={hoverNetY + 3} textAnchor="middle" className="fill-white text-[11px] font-semibold">
                  {formatSignedLots(hoverPoint[netKey])}
                </text>
              </g>
            ) : null}
            {hoverCumY !== null ? (
              <g>
                <rect x={viewWidth - 62} y={hoverCumY - 12} width={54} height={22} rx={3} fill="#6b7280" />
                <text x={viewWidth - 35} y={hoverCumY + 3} textAnchor="middle" className="fill-white text-[11px] font-semibold">
                  {formatSignedLots(hoverPoint[cumulativeKey])}
                </text>
              </g>
            ) : null}
            {showXAxisLabels ? (
              <>
                <rect x={hoverX - 28} y={top + height + 28} width={56} height={20} rx={3} fill="#6b7280" />
                <text x={hoverX} y={top + height + 42} textAnchor="middle" className="fill-white text-[11px] font-semibold">
                  {formatMonthDay(hoverPoint.date)}
                </text>
              </>
            ) : null}
            <g transform={`translate(${hoverTipX} ${hoverTipY})`}>
              <rect width={hoverTipWidth} height={hoverTipHeight} rx={4} fill="white" stroke="#cbd5e1" />
              <text x={12} y={20} className="fill-slate-500 text-[12px] font-semibold">
                {formatDate(hoverPoint.date)}
              </text>
              <rect x={12} y={34} width={8} height={8} fill={(hoverPoint[netKey] ?? 0) >= 0 ? "#ef4444" : "#10b981"} />
              <text x={28} y={43} className="fill-slate-600 text-[12px]">
                買賣超(張)
              </text>
              <text x={hoverTipWidth - 12} y={43} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
                {formatSignedLots(hoverPoint[netKey])}
              </text>
              <circle cx={16} cy={62} r={4} fill="#93c5fd" />
              <text x={28} y={66} className="fill-slate-600 text-[12px]">
                累計(張)
              </text>
              <text x={hoverTipWidth - 12} y={66} textAnchor="end" className="fill-slate-900 text-[12px] font-semibold">
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

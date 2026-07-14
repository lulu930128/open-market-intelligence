"use client";

import {
  rankByLabel,
  rowStatusLabel,
  trendDirectionLabel,
  useT,
  type TranslationFunction,
} from "@/i18n";
import {
  getTaiwanIntradayXRatio,
  isTaiwanRegularSessionPoint,
} from "@/lib/taiwanMarketTime";
import {
  getUsIntradayXRatio,
  isUsRegularSessionPoint,
} from "@/lib/usMarketTime";
import type {
  RankingItem,
  USWatchlistRankingItemRead,
} from "@/types/market";

export function formatWatchlistFreshnessLabel(
  t: TranslationFunction,
  marketLabel: string,
  targetDate: string | null | undefined,
  staleCount: number | null | undefined,
  requestedCount: number | null | undefined
) {
  const dateText = targetDate
    ? t("dashboard.freshness.waitingMarketDate", { targetDate, marketLabel })
    : t("dashboard.freshness.waitingMarket", { marketLabel });

  if (
    staleCount !== null &&
    staleCount !== undefined &&
    requestedCount !== null &&
    requestedCount !== undefined &&
    requestedCount > 0
  ) {
    return t("dashboard.freshness.pendingBackfill", {
      dateText,
      staleCount,
      requestedCount,
    });
  }

  return dateText;
}

export function formatLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value / 1000));
}

export function statusLabel(t: TranslationFunction, status: string) {
  if (status === "pending") return "-";
  return rowStatusLabel(t, status);
}

export function rankLabel(t: TranslationFunction, rankBy: string) {
  return rankByLabel(t, rankBy);
}

export function trendLabel(
  t: TranslationFunction,
  value: number | null | undefined,
  limitStatus?: RankingItem["limit_status"]
) {
  if (limitStatus === "limit_up") return t("statusLabels.limitUp");
  if (limitStatus === "limit_down") return t("statusLabels.limitDown");
  return trendDirectionLabel(t, value);
}

export function trendClass(
  value: number | null | undefined,
  limitStatus?: RankingItem["limit_status"]
) {
  if (limitStatus === "limit_up") return "omi-ranking-trend-limit-up";
  if (limitStatus === "limit_down") return "omi-ranking-trend-limit-down";
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "omi-ranking-trend-neutral";
  }
  if (value > 0) return "omi-ranking-trend-up";
  if (value < 0) return "omi-ranking-trend-down";
  return "omi-ranking-trend-neutral";
}

function sparklineTone(
  latestPrice: number | null,
  previousClose: number | null,
  selected: boolean
) {
  if (latestPrice === null || previousClose === null || previousClose === 0) {
    return selected ? "stroke-omi-text-inverse-muted" : "stroke-omi-text-subtle";
  }

  if (latestPrice > previousClose) return "stroke-omi-market-up";
  if (latestPrice < previousClose) return "stroke-omi-market-down";
  return selected ? "stroke-omi-text-inverse-muted" : "stroke-omi-text-subtle";
}

function buildSparklinePath(
  points: Array<{ time: string; price: number }>,
  previousClose: number | null,
  getXRatio: (value: string | Date) => number = getTaiwanIntradayXRatio
) {
  const width = 92;
  const height = 28;
  const paddingX = 2;
  const paddingY = 4;
  const usableWidth = width - paddingX * 2;
  const usableHeight = height - paddingY * 2;
  const prices = [
    ...points.map((point) => point.price),
    ...(previousClose !== null ? [previousClose] : []),
  ];
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const range = maxPrice - minPrice || Math.max(maxPrice * 0.01, 1);
  const yMin = minPrice - range * 0.08;
  const yMax = maxPrice + range * 0.08;
  const yRange = yMax - yMin || 1;
  const path = points
    .map((point, index) => {
      const x = paddingX + getXRatio(point.time) * usableWidth;
      const y = paddingY + ((yMax - point.price) / yRange) * usableHeight;

      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
  const previousCloseY =
    previousClose === null
      ? null
      : paddingY + ((yMax - previousClose) / yRange) * usableHeight;
  const latestPoint = points[points.length - 1];
  const latestPointX = paddingX + getXRatio(latestPoint.time) * usableWidth;
  const latestPointY = paddingY + ((yMax - latestPoint.price) / yRange) * usableHeight;

  return { path, previousCloseY, latestPointX, latestPointY, width, height };
}

function sparklinePointTone(
  latestPrice: number | null,
  previousClose: number | null,
  selected: boolean
) {
  if (latestPrice !== null && previousClose !== null && previousClose !== 0) {
    if (latestPrice > previousClose) {
      return {
        core: selected ? "fill-omi-market-up-border" : "fill-omi-market-up",
        ring: selected ? "stroke-omi-market-up-border" : "stroke-omi-market-up",
      };
    }

    if (latestPrice < previousClose) {
      return {
        core: selected ? "fill-omi-market-down-border" : "fill-omi-market-down",
        ring: selected ? "stroke-omi-market-down-border" : "stroke-omi-market-down",
      };
    }
  }

  return {
    core: selected ? "fill-omi-text-inverse-muted" : "fill-omi-text-subtle",
    ring: selected ? "stroke-omi-text-inverse-muted" : "stroke-omi-text-inverse-muted",
  };
}

export function RankingSparkline({
  row,
  selected,
}: {
  row: RankingItem;
  selected: boolean;
}) {
  const t = useT();
  const points = (row.intraday_points ?? []).filter((point) => {
    return (
      point.time &&
      point.price !== null &&
      point.price !== undefined &&
      !Number.isNaN(point.price) &&
      isTaiwanRegularSessionPoint(point.time)
    );
  });

  if (points.length < 2) {
    return <span className="text-center text-xs text-omi-text-subtle">-</span>;
  }

  const previousClose = row.intraday_previous_close ?? null;
  const latestPrice = points[points.length - 1]?.price ?? null;
  const chart = buildSparklinePath(points, previousClose);
  const latestPoint = points[points.length - 1];
  const pointTone = sparklinePointTone(latestPrice, previousClose, selected);

  return (
    <svg
      viewBox={`0 0 ${chart.width} ${chart.height}`}
      className="h-8 w-[92px]"
      aria-label={t("dashboard.marketIndex.intradayTrend")}
    >
      <rect width={chart.width} height={chart.height} fill="transparent" />
      {chart.previousCloseY !== null ? (
        <line
          x1="2"
          x2={chart.width - 2}
          y1={chart.previousCloseY}
          y2={chart.previousCloseY}
          className={selected ? "stroke-omi-text-inverse-subtle" : "stroke-omi-border-subtle"}
          strokeDasharray="3 3"
        />
      ) : null}
      <path
        d={chart.path}
        fill="none"
        strokeWidth="1.8"
        className={sparklineTone(latestPrice, previousClose, selected)}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g
        key={`${latestPoint.time}-${latestPoint.price}`}
        className="omi-live-sparkline-point"
        pointerEvents="none"
      >
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="5.5"
          className={`omi-live-point-ring ${pointTone.ring}`}
        />
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="2.2"
          className={`omi-live-point-core ${pointTone.core}`}
        />
      </g>
    </svg>
  );
}

export function USRankingSparkline({
  row,
  selected,
}: {
  row: USWatchlistRankingItemRead;
  selected: boolean;
}) {
  const t = useT();
  const points = (row.intraday_points ?? []).filter((point) => {
    return (
      point.time &&
      point.price !== null &&
      point.price !== undefined &&
      !Number.isNaN(point.price) &&
      isUsRegularSessionPoint(point.time)
    );
  });

  if (points.length < 2) {
    return (
      <span className="text-center text-xs text-omi-text-subtle">
        {row.time ? t("statusLabels.intraday") : "-"}
      </span>
    );
  }

  const previousClose = row.intraday_previous_close ?? null;
  const latestPrice = points[points.length - 1]?.price ?? null;
  const chart = buildSparklinePath(points, previousClose, getUsIntradayXRatio);
  const latestPoint = points[points.length - 1];
  const pointTone = sparklinePointTone(latestPrice, previousClose, selected);

  return (
    <svg
      viewBox={`0 0 ${chart.width} ${chart.height}`}
      className="h-8 w-[92px]"
      aria-label="US intraday trend"
    >
      <rect width={chart.width} height={chart.height} fill="transparent" />
      {chart.previousCloseY !== null ? (
        <line
          x1="2"
          x2={chart.width - 2}
          y1={chart.previousCloseY}
          y2={chart.previousCloseY}
          className={selected ? "stroke-omi-text-inverse-subtle" : "stroke-omi-border-subtle"}
          strokeDasharray="3 3"
        />
      ) : null}
      <path
        d={chart.path}
        fill="none"
        strokeWidth="1.8"
        className={sparklineTone(latestPrice, previousClose, selected)}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <g
        key={`${latestPoint.time}-${latestPoint.price}`}
        className="omi-live-sparkline-point"
        pointerEvents="none"
      >
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="5.5"
          className={`omi-live-point-ring ${pointTone.ring}`}
        />
        <circle
          cx={chart.latestPointX}
          cy={chart.latestPointY}
          r="2.2"
          className={`omi-live-point-core ${pointTone.core}`}
        />
      </g>
    </svg>
  );
}

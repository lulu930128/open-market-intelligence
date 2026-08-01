import { finiteNumber } from "@/components/stock-detail/stockDetailFormatters";
import {
  professionalIntradayMinutes,
  shareholdingLevelRanges,
  type ProfessionalIntradayTimeframe,
  type ProfessionalTimeframe,
} from "@/components/stock-detail/stockDetailTypes";
import {
  TAIWAN_SESSION_END_MINUTES,
  TAIWAN_SESSION_START_MINUTES,
  getTaipeiMinutesOfDay,
  isTaiwanRegularSessionPoint,
} from "@/lib/taiwanMarketTime";
import type {
  ChartPoint,
  IntradayTrendPoint,
  InstitutionalTradeDailyRead,
  ShareholdingDistributionWeeklyRead,
} from "@/types/market";

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
  intervalMinutes: number,
  options: {
    discardOpeningReferencePrice?: number | null;
    includePostCloseSnapshot?: boolean;
    includeVolume?: boolean;
    priceOnly?: boolean;
  } = {}
): ChartPoint[] {
  const buckets = new Map<number, IntradayTrendPoint[]>();
  const sortedPoints = points
    .filter((point) => finiteNumber(point.price))
    .slice()
    .sort((left, right) => intradayTimeMs(left.time) - intradayTimeMs(right.time));
  const regularSessionPoints = sortedPoints.filter((point) =>
    isTaiwanRegularSessionPoint(point.time)
  );
  const lastRegularPoint = regularSessionPoints[regularSessionPoints.length - 1] ?? null;
  const postCloseSnapshot = options.includePostCloseSnapshot
    ? [...sortedPoints]
        .reverse()
        .find((point) => {
          const minutes = getTaipeiMinutesOfDay(point.time);

          return (
            minutes !== null &&
            minutes > TAIWAN_SESSION_END_MINUTES &&
            minutes <= TAIWAN_SESSION_END_MINUTES + 5
          );
        }) ?? null
    : null;
  const pointsWithClosingSnapshot =
    postCloseSnapshot && lastRegularPoint
      ? [
          ...regularSessionPoints,
          {
            ...postCloseSnapshot,
            time: lastRegularPoint.time,
          },
        ]
      : regularSessionPoints;
  const firstPoint = pointsWithClosingSnapshot[0] ?? null;
  const secondPoint = pointsWithClosingSnapshot[1] ?? null;
  const firstMinutes = firstPoint ? getTaipeiMinutesOfDay(firstPoint.time) : null;
  const secondMinutes = secondPoint ? getTaipeiMinutesOfDay(secondPoint.time) : null;
  const shouldDiscardOpeningReference =
    firstPoint !== null &&
    secondPoint !== null &&
    finiteNumber(options.discardOpeningReferencePrice) &&
    firstPoint.price === options.discardOpeningReferencePrice &&
    firstMinutes === TAIWAN_SESSION_START_MINUTES &&
    secondMinutes === TAIWAN_SESSION_START_MINUTES;
  const aggregationPoints = shouldDiscardOpeningReference
    ? pointsWithClosingSnapshot.slice(1)
    : pointsWithClosingSnapshot;

  aggregationPoints.forEach((point) => {
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
      const highs = bucketPoints
        .map((point) => (options.priceOnly ? point.price : point.high ?? point.price))
        .filter(finiteNumber);
      const lows = bucketPoints
        .map((point) => (options.priceOnly ? point.price : point.low ?? point.price))
        .filter(finiteNumber);
      const volume = bucketPoints.reduce((total, point) => {
        return total + (finiteNumber(point.volume) && point.volume > 0 ? point.volume : 0);
      }, 0);

      return {
        time: first.time,
        open: options.priceOnly ? first.price : first.open ?? first.price,
        high: highs.length ? Math.max(...highs) : last.price,
        low: lows.length ? Math.min(...lows) : last.price,
        close: last.price,
        volume: options.includeVolume === false || volume <= 0 ? null : volume,
        trade_value: null,
        transaction_count: null,
      };
    });
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

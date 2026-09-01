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
  getTaipeiDateKey,
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
    tradeDate?: string | null;
  } = {}
): ChartPoint[] {
  const buckets = new Map<number, IntradayTrendPoint[]>();
  const sortedPoints = points
    .filter((point) => finiteNumber(point.price))
    .slice()
    .sort((left, right) => intradayTimeMs(left.time) - intradayTimeMs(right.time));
  const pointDateKey = (point: IntradayTrendPoint) => {
    const value = new Date(point.time);
    return Number.isNaN(value.getTime()) ? null : getTaipeiDateKey(value);
  };
  const requestedTradeDate = options.tradeDate?.slice(0, 10) ?? null;
  const targetTradeDate =
    requestedTradeDate ??
    [...sortedPoints]
      .reverse()
      .map(pointDateKey)
      .find((value): value is string => value !== null) ??
    null;
  const scopedPoints = targetTradeDate
    ? sortedPoints.filter((point) => pointDateKey(point) === targetTradeDate)
    : [];
  const regularSessionPoints = scopedPoints.filter((point) =>
    isTaiwanRegularSessionPoint(point.time)
  );
  const lastRegularPoint = regularSessionPoints[regularSessionPoints.length - 1] ?? null;
  const postCloseSnapshot = options.includePostCloseSnapshot
    ? [...scopedPoints]
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
    firstMinutes !== null &&
    secondMinutes !== null &&
    Math.floor(firstMinutes) === TAIWAN_SESSION_START_MINUTES &&
    Math.floor(secondMinutes) === TAIWAN_SESSION_START_MINUTES;
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

export function resolveTodayHeadlineValues({
  backendPrice,
  backendChange,
  backendChangePct,
  currentPrice,
  currentReferenceClose,
  completedSessionPrice,
  completedSessionReferenceClose,
}: {
  backendPrice?: number | null;
  backendChange?: number | null;
  backendChangePct?: number | null;
  currentPrice: number | null | undefined;
  currentReferenceClose: number | null | undefined;
  completedSessionPrice: number | null | undefined;
  completedSessionReferenceClose: number | null | undefined;
}): readonly [
  price: number | null,
  change: number | null,
  changePct: number | null,
  source: "backend_headline" | "current_session" | "completed_session" | "unavailable",
] {
  const normalizedBackendPrice = finiteNumber(backendPrice) ? backendPrice : null;
  if (normalizedBackendPrice !== null) {
    return [
      normalizedBackendPrice,
      finiteNumber(backendChange) ? backendChange : null,
      finiteNumber(backendChangePct) ? backendChangePct : null,
      "backend_headline",
    ] as const;
  }

  const normalizedCurrentPrice = finiteNumber(currentPrice) ? currentPrice : null;
  const normalizedCurrentReference = finiteNumber(currentReferenceClose)
    ? currentReferenceClose
    : null;
  if (normalizedCurrentPrice !== null) {
    return [
      normalizedCurrentPrice,
      normalizedCurrentReference !== null
        ? normalizedCurrentPrice - normalizedCurrentReference
        : null,
      normalizedCurrentReference !== null && normalizedCurrentReference !== 0
        ? ((normalizedCurrentPrice - normalizedCurrentReference) /
            normalizedCurrentReference) *
          100
        : null,
      "current_session",
    ] as const;
  }

  const normalizedCompletedPrice = finiteNumber(completedSessionPrice)
    ? completedSessionPrice
    : null;
  const normalizedCompletedReference = finiteNumber(completedSessionReferenceClose)
    ? completedSessionReferenceClose
    : null;
  if (normalizedCompletedPrice !== null) {
    return [
      normalizedCompletedPrice,
      normalizedCompletedReference !== null
        ? normalizedCompletedPrice - normalizedCompletedReference
        : null,
      normalizedCompletedReference !== null && normalizedCompletedReference !== 0
        ? ((normalizedCompletedPrice - normalizedCompletedReference) /
            normalizedCompletedReference) *
          100
        : null,
      "completed_session",
    ] as const;
  }

  return [null, null, null, "unavailable"] as const;
}

export function resolveQuoteDepthHeadlineValues({
  allowIndicative,
  indicativeAvailable,
  indicativePrice,
  headlinePrice,
  headlineChange,
  headlineChangePct,
  legacyPrice,
  legacyChange,
  legacyChangePct,
  previousClose,
}: {
  allowIndicative: boolean;
  indicativeAvailable: boolean | undefined;
  indicativePrice: number | null | undefined;
  headlinePrice: number | null | undefined;
  headlineChange: number | null | undefined;
  headlineChangePct: number | null | undefined;
  legacyPrice: number | null | undefined;
  legacyChange: number | null | undefined;
  legacyChangePct: number | null | undefined;
  previousClose: number | null | undefined;
}): readonly [number | null, number | null, number | null] {
  const selectedIndicative =
    allowIndicative && indicativeAvailable && finiteNumber(indicativePrice)
      ? indicativePrice
      : null;
  if (selectedIndicative !== null) {
    const reference = finiteNumber(previousClose) ? previousClose : null;
    const change = reference !== null ? selectedIndicative - reference : null;
    return [
      selectedIndicative,
      change,
      change !== null && reference !== null && reference !== 0
        ? (change / reference) * 100
        : null,
    ] as const;
  }

  return [
    finiteNumber(headlinePrice)
      ? headlinePrice
      : finiteNumber(legacyPrice)
        ? legacyPrice
        : null,
    finiteNumber(headlineChange)
      ? headlineChange
      : finiteNumber(legacyChange)
        ? legacyChange
        : null,
    finiteNumber(headlineChangePct)
      ? headlineChangePct
      : finiteNumber(legacyChangePct)
        ? legacyChangePct
        : null,
  ] as const;
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

export function summarizeIntradayPoints(
  points: IntradayTrendPoint[],
  options: {
    discardOpeningReferencePrice?: number | null;
    ignorePostCloseOhlc?: boolean;
    tradeDate?: string | null;
  } = {}
) {
  const requestedTradeDate = options.tradeDate?.slice(0, 10) ?? null;
  const sortedPoints = points
    .filter((point) => point.price !== null && point.price !== undefined)
    .slice()
    .sort((left, right) => intradayTimeMs(left.time) - intradayTimeMs(right.time));
  const targetTradeDate =
    requestedTradeDate ??
    [...sortedPoints]
      .reverse()
      .map((point) => {
        const value = new Date(point.time);
        return Number.isNaN(value.getTime()) ? null : getTaipeiDateKey(value);
      })
      .find((value): value is string => value !== null) ??
    null;
  const scopedPoints = targetTradeDate
    ? sortedPoints.filter((point) => {
        const value = new Date(point.time);
        return !Number.isNaN(value.getTime()) && getTaipeiDateKey(value) === targetTradeDate;
      })
    : [];
  const firstPoint = scopedPoints[0] ?? null;
  const secondPoint = scopedPoints[1] ?? null;
  const shouldDiscardOpeningReference =
    firstPoint !== null &&
    secondPoint !== null &&
    finiteNumber(options.discardOpeningReferencePrice) &&
    firstPoint.price === options.discardOpeningReferencePrice &&
    Math.floor(getTaipeiMinutesOfDay(firstPoint.time) ?? -1) ===
      TAIWAN_SESSION_START_MINUTES &&
    Math.floor(getTaipeiMinutesOfDay(secondPoint.time) ?? -1) ===
      TAIWAN_SESSION_START_MINUTES;
  const withoutOpeningReference = shouldDiscardOpeningReference
    ? scopedPoints.slice(1)
    : scopedPoints;
  const validPoints = withoutOpeningReference.filter(
    (point) => point.source_event_type !== "opening_reference"
  );

  if (validPoints.length === 0) {
    return {
      open: null,
      high: null,
      low: null,
      volume: null,
    };
  }

  const sessionOpenPoint = validPoints[0];
  const isPostClosePoint = (point: IntradayTrendPoint) => {
    const minutes = getTaipeiMinutesOfDay(point.time);
    return (
      point.bar_type === "post_close_summary" ||
      (minutes !== null && minutes > TAIWAN_SESSION_END_MINUTES)
    );
  };
  const highs = validPoints.map((point) =>
    options.ignorePostCloseOhlc && isPostClosePoint(point)
      ? point.price
      : point.high ?? point.price
  );
  const lows = validPoints.map((point) =>
    options.ignorePostCloseOhlc && isPostClosePoint(point)
      ? point.price
      : point.low ?? point.price
  );
  const volumes = validPoints
    .map((point) => point.volume)
    .filter((value): value is number => value !== null && value !== undefined);

  return {
    open: sessionOpenPoint.open ?? sessionOpenPoint.price,
    high: Math.max(...highs),
    low: Math.min(...lows),
    volume: volumes.length > 0 ? volumes.reduce((total, value) => total + value, 0) : null,
  };
}

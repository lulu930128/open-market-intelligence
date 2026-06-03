"use client";

import { useEffect, useId, useMemo, useState } from "react";
import type { IntradayTrendPoint } from "@/types/market";
import {
  TAIWAN_SESSION_END_MINUTES,
  TAIWAN_SESSION_START_MINUTES,
  getTaipeiMinutesOfDay,
  getTaiwanIntradayXRatio,
  isTaiwanRegularSessionPoint,
} from "@/lib/taiwanMarketTime";

type Props = {
  points: IntradayTrendPoint[];
  previousClose: number | null;
  label: string;
  source: string;
  indicators?: IntradayIndicatorSettings;
  session?: IntradaySessionConfig;
  revealKey?: string;
  refreshIntervalMs?: number;
  updatedAt?: string | null;
};

type IntradayInterval = 1 | 5 | 15;
export type IntradayIndicatorKey = "volume" | "vwap" | "twap" | "ema" | "rsi" | "macd";
export type IntradayIndicatorSettings = Record<IntradayIndicatorKey, boolean>;
export type IntradaySessionConfig = {
  startMinutes: number;
  endMinutes: number;
  timeTicks: Array<{ label: string; minutes: number }>;
  getMinutesOfDay: (value: string | Date) => number | null;
  getXRatio: (value: string | Date) => number;
  isRegularSessionPoint: (value: string | Date) => boolean;
  volumeFormatter?: (value: number | null | undefined) => string;
};

type IntradayChartPoint = IntradayTrendPoint & {
  vwap: number | null;
  twap: number | null;
  emaFast: number | null;
  emaSlow: number | null;
  rsi: number | null;
  macd: number | null;
  macdSignal: number | null;
  macdHistogram: number | null;
};

const intervalOptions: Array<{ label: string; value: IntradayInterval }> = [
  { label: "1m", value: 1 },
  { label: "5m", value: 5 },
  { label: "15m", value: 15 },
];

export const defaultIntradayIndicators: IntradayIndicatorSettings = {
  volume: true,
  vwap: true,
  twap: true,
  ema: true,
  rsi: true,
  macd: true,
};

export const taiwanIntradaySession: IntradaySessionConfig = {
  startMinutes: TAIWAN_SESSION_START_MINUTES,
  endMinutes: TAIWAN_SESSION_END_MINUTES,
  timeTicks: [
    { label: "09:00", minutes: 9 * 60 },
    { label: "10:00", minutes: 10 * 60 },
    { label: "11:00", minutes: 11 * 60 },
    { label: "12:00", minutes: 12 * 60 },
    { label: "13:00", minutes: 13 * 60 },
    { label: "13:30", minutes: 13 * 60 + 30 },
  ],
  getMinutesOfDay: getTaipeiMinutesOfDay,
  getXRatio: getTaiwanIntradayXRatio,
  isRegularSessionPoint: isTaiwanRegularSessionPoint,
  volumeFormatter: formatLots,
};

export const intradayIndicatorOptions: Array<{
  key: IntradayIndicatorKey;
  label: string;
  description: string;
}> = [
  { key: "volume", label: "VOL", description: "盤中成交量" },
  { key: "vwap", label: "VWAP", description: "量價均價" },
  { key: "twap", label: "TWAP", description: "時間均價" },
  { key: "ema", label: "EMA", description: "EMA5 / EMA20" },
  { key: "rsi", label: "RSI", description: "RSI 14" },
  { key: "macd", label: "MACD", description: "12 / 26 / 9" },
];

const playedIntradayRevealKeys = new Set<string>();

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatSource(value: string) {
  if (value === "nstock_minute_stock_data_twse_mis_volume") return "分K走勢 + 交易所量";
  if (value === "nstock_minute_stock_data") return "分K走勢";
  if (value === "yahoo_finance_chart_twse_mis_volume") return "1 分鐘走勢 + 交易所量";
  if (value === "yahoo_finance_chart") return "1 分鐘走勢";
  if (value === "twse_mis_snapshot") return "即時快照";
  return "走勢資料";
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function validNumber(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && !Number.isNaN(value);
}

function average(values: Array<number | null | undefined>) {
  const valid = values.filter(validNumber);

  if (valid.length === 0) return null;

  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function formatLots(value: number | null | undefined) {
  if (!validNumber(value) || value <= 0) return "-";

  return new Intl.NumberFormat("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  }).format(value / 1000);
}

function getTaiwanPriceStep(price: number) {
  if (price >= 500) return 1;
  if (price >= 100) return 0.5;
  if (price >= 50) return 0.1;
  if (price >= 10) return 0.05;
  return 0.01;
}

function roundToStep(value: number, step: number, mode: "floor" | "ceil" | "round") {
  const scaled = value / step;

  if (mode === "floor") return Math.floor(scaled) * step;
  if (mode === "ceil") return Math.ceil(scaled) * step;

  return Math.round(scaled) * step;
}

function floorToTaiwanPriceStep(value: number) {
  return roundToStep(value, getTaiwanPriceStep(value), "floor");
}

function ceilToTaiwanPriceStep(value: number) {
  return roundToStep(value, getTaiwanPriceStep(value), "ceil");
}

function getNiceAxisInterval(range: number, referencePrice: number) {
  const baseStep = getTaiwanPriceStep(referencePrice);
  const rawStep = Math.max(range / 5, baseStep);
  const multipliers = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
  const multiplier = multipliers.find((item) => item * baseStep >= rawStep) ?? 1000;

  return multiplier * baseStep;
}

function nearlyEqual(a: number, b: number, tolerance: number) {
  return Math.abs(a - b) <= tolerance;
}

function uniqueTicks(values: number[]) {
  return values.reduce<number[]>((result, value) => {
    const rounded = Number(value.toFixed(4));
    const exists = result.some((item) => nearlyEqual(item, rounded, 0.0001));

    if (!exists) result.push(rounded);

    return result;
  }, []);
}

function buildPriceTicks(
  min: number,
  max: number,
  interval: number,
  hasFixedMax: boolean,
  hasFixedMin: boolean
) {
  const ticks = [max];
  let next = hasFixedMax ? roundToStep(max - interval, interval, "ceil") : max - interval;

  while (next > min + interval * 0.2) {
    ticks.push(next);
    next -= interval;
  }

  if (hasFixedMin) {
    ticks.push(min);
  } else if (ticks[ticks.length - 1] > min + interval * 0.2) {
    ticks.push(min);
  }

  return uniqueTicks(ticks).sort((a, b) => b - a);
}

function getPriceScale(
  prices: number[],
  previousClose: number | null,
  showLimitRange: boolean
) {
  const referencePrice = previousClose ?? prices[prices.length - 1] ?? 1;
  const hardMax = previousClose === null ? null : previousClose * 1.1;
  const hardMin = previousClose === null ? null : previousClose * 0.9;
  const limitUp = hardMax === null ? null : floorToTaiwanPriceStep(hardMax);
  const limitDown = hardMin === null ? null : ceilToTaiwanPriceStep(hardMin);
  const limitTolerance = getTaiwanPriceStep(referencePrice) * 0.51;
  const scaleValues = [...prices];

  if (previousClose !== null) scaleValues.push(previousClose);
  if (showLimitRange && limitUp !== null && limitDown !== null) {
    scaleValues.push(limitUp, limitDown);
  }

  const rawMin = Math.min(...scaleValues);
  const rawMax = Math.max(...scaleValues);
  const hitsLimitUp = limitUp !== null && rawMax >= limitUp - limitTolerance;
  const hitsLimitDown = limitDown !== null && rawMin <= limitDown + limitTolerance;
  const rawRange = rawMax - rawMin || Math.max(referencePrice * 0.02, 1);
  let paddedMin = rawMin - rawRange * 0.08;
  let paddedMax = rawMax + rawRange * 0.08;

  if (limitDown !== null && (showLimitRange || hitsLimitDown)) {
    paddedMin = limitDown;
  } else if (limitDown !== null) {
    paddedMin = Math.max(paddedMin, limitDown);
  }

  if (limitUp !== null && (showLimitRange || hitsLimitUp)) {
    paddedMax = limitUp;
  } else if (limitUp !== null) {
    paddedMax = Math.min(paddedMax, limitUp);
  }

  const interval = getNiceAxisInterval(paddedMax - paddedMin || rawRange, referencePrice);
  let min =
    limitDown !== null && (showLimitRange || hitsLimitDown)
      ? limitDown
      : roundToStep(paddedMin, interval, "floor");
  let max =
    limitUp !== null && (showLimitRange || hitsLimitUp)
      ? limitUp
      : roundToStep(paddedMax, interval, "ceil");

  if (limitUp !== null && max > limitUp) {
    max = limitUp;
  }

  if (limitDown !== null && min < limitDown) {
    min = limitDown;
  }

  if (min === max) {
    const nextMin = limitDown !== null ? Math.max(limitDown, min - interval) : min - interval;
    const nextMax = limitUp !== null ? Math.min(limitUp, max + interval) : max + interval;

    min = nextMin;
    max = nextMax;
  }

  const ticks = buildPriceTicks(
    min,
    max,
    interval,
    limitUp !== null && nearlyEqual(max, limitUp, limitTolerance),
    limitDown !== null && nearlyEqual(min, limitDown, limitTolerance)
  );

  return {
    min,
    max,
    ticks,
    interval,
    limitUp,
    limitDown,
    hardMax,
    hardMin,
    hitsLimitUp,
    hitsLimitDown,
  };
}

function priceToneClass(
  price: number,
  previousClose: number | null,
  limitUp: number | null,
  limitDown: number | null
) {
  const step = getTaiwanPriceStep(price) * 0.51;

  if (limitUp !== null && nearlyEqual(price, limitUp, step)) {
    return "fill-red-600 font-bold";
  }

  if (limitDown !== null && nearlyEqual(price, limitDown, step)) {
    return "fill-emerald-600 font-bold";
  }

  if (previousClose === null || price === previousClose) return "fill-slate-600";
  if (price > previousClose) return "fill-red-600";
  return "fill-emerald-600";
}

function pricePctToneClass(value: number) {
  if (value > 0) return "fill-red-600";
  if (value < 0) return "fill-emerald-600";
  return "fill-slate-700";
}

function formatPct(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function formatIndicator(value: number | null | undefined, digits = 2) {
  if (!validNumber(value)) return "-";
  return value.toFixed(digits);
}

function labelPosition(
  x: number,
  paddingLeft: number,
  paddingRight: number,
  width: number
) {
  const labelWidth = 84;
  const isNearRight = x > width - paddingRight - labelWidth;

  return {
    x: isNearRight ? x - 10 : x + 10,
    anchor: isNearRight ? "end" : "start",
  } as const;
}

function aggregateIntradayPoints(
  points: IntradayTrendPoint[],
  interval: IntradayInterval,
  session: IntradaySessionConfig
) {
  const regularPoints = points.filter((point) => {
    return (
      validNumber(point.price) &&
      session.isRegularSessionPoint(point.time)
    );
  });

  if (interval === 1) {
    return regularPoints.map((point) => ({
      ...point,
      open: point.open ?? point.price,
      high: point.high ?? point.price,
      low: point.low ?? point.price,
    }));
  }

  const buckets = new Map<number, IntradayTrendPoint[]>();

  regularPoints.forEach((point) => {
    const minutes = session.getMinutesOfDay(point.time);

    if (minutes === null) return;

    const bucket =
      session.startMinutes +
      Math.floor((minutes - session.startMinutes) / interval) * interval;
    const current = buckets.get(bucket) ?? [];

    current.push(point);
    buckets.set(bucket, current);
  });

  return Array.from(buckets.entries())
    .sort(([a], [b]) => a - b)
    .map(([, bucketPoints]) => {
      const first = bucketPoints[0];
      const last = bucketPoints[bucketPoints.length - 1];
      const highs = bucketPoints
        .map((point) => point.high ?? point.price)
        .filter(validNumber);
      const lows = bucketPoints
        .map((point) => point.low ?? point.price)
        .filter(validNumber);
      const volume = bucketPoints.reduce((sum, point) => {
        return sum + (validNumber(point.volume) && point.volume > 0 ? point.volume : 0);
      }, 0);

      return {
        time: first.time,
        price: last.price,
        volume: volume > 0 ? volume : null,
        open: first.open ?? first.price,
        high: highs.length > 0 ? Math.max(...highs) : last.price,
        low: lows.length > 0 ? Math.min(...lows) : last.price,
      };
    });
}

function calculateEma(values: number[], period: number) {
  let previousEma: number | null = null;
  const multiplier = 2 / (period + 1);

  return values.map((value, index) => {
    if (index + 1 < period) return null;

    if (previousEma === null) {
      previousEma = average(values.slice(index + 1 - period, index + 1));
      return previousEma;
    }

    previousEma = value * multiplier + previousEma * (1 - multiplier);
    return previousEma;
  });
}

function calculateNullableEma(values: Array<number | null>, period: number) {
  let previousEma: number | null = null;
  const multiplier = 2 / (period + 1);

  return values.map((value, index) => {
    if (!validNumber(value)) return null;

    if (previousEma === null) {
      const slice = values.slice(0, index + 1).filter(validNumber).slice(-period);

      if (slice.length < period) return null;

      previousEma = average(slice);
      return previousEma;
    }

    previousEma = value * multiplier + previousEma * (1 - multiplier);
    return previousEma;
  });
}

function calculateRsi(values: number[], period: number) {
  let averageGain: number | null = null;
  let averageLoss: number | null = null;

  return values.map((value, index) => {
    if (index === 0 || index < period) return null;

    const change = value - values[index - 1];
    const gain = Math.max(change, 0);
    const loss = Math.max(-change, 0);

    if (averageGain === null || averageLoss === null) {
      const changes = values.slice(index + 1 - period, index + 1).map((current, cursor) => {
        return current - values[index - period + cursor];
      });

      averageGain = changes.reduce((sum, item) => sum + Math.max(item, 0), 0) / period;
      averageLoss = changes.reduce((sum, item) => sum + Math.max(-item, 0), 0) / period;
    } else {
      averageGain = (averageGain * (period - 1) + gain) / period;
      averageLoss = (averageLoss * (period - 1) + loss) / period;
    }

    if (averageLoss === 0) return 100;

    const relativeStrength = averageGain / averageLoss;
    return 100 - 100 / (1 + relativeStrength);
  });
}

function enrichIntradayPoints(points: IntradayTrendPoint[]): IntradayChartPoint[] {
  const closes = points.map((point) => point.price);
  const emaFast = calculateEma(closes, 5);
  const emaSlow = calculateEma(closes, 20);
  const rsi = calculateRsi(closes, 14);
  const macdFast = calculateEma(closes, 12);
  const macdSlow = calculateEma(closes, 26);
  const macd = macdFast.map((fast, index) => {
    const slow = macdSlow[index];

    if (!validNumber(fast) || !validNumber(slow)) return null;
    return fast - slow;
  });
  const macdSignal = calculateNullableEma(macd, 9);
  let cumulativePrice = 0;
  let cumulativePriceVolume = 0;
  let cumulativeVolume = 0;
  let latestVwap: number | null = null;

  return points.map((point, index) => {
    cumulativePrice += point.price;

    const volume = validNumber(point.volume) && point.volume > 0 ? point.volume : 0;

    if (volume > 0) {
      cumulativePriceVolume += point.price * volume;
      cumulativeVolume += volume;
      latestVwap = cumulativePriceVolume / cumulativeVolume;
    }

    const histogram =
      validNumber(macd[index]) && validNumber(macdSignal[index])
        ? macd[index] - macdSignal[index]
        : null;

    return {
      ...point,
      vwap: latestVwap,
      twap: cumulativePrice / (index + 1),
      emaFast: emaFast[index],
      emaSlow: emaSlow[index],
      rsi: rsi[index],
      macd: macd[index],
      macdSignal: macdSignal[index],
      macdHistogram: histogram,
    };
  });
}

function buildLinePath(
  data: IntradayChartPoint[],
  getX: (point: IntradayChartPoint, index: number) => number,
  getY: (value: number) => number
) {
  return data
    .map((point, index) => {
      const x = getX(point, index).toFixed(2);
      const y = getY(point.price).toFixed(2);
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
}

function buildNullableLinePath(
  data: IntradayChartPoint[],
  getValue: (point: IntradayChartPoint) => number | null | undefined,
  getX: (point: IntradayChartPoint, index: number) => number,
  getY: (value: number) => number
) {
  let started = false;

  return data
    .map((point, index) => {
      const value = getValue(point);

      if (!validNumber(value)) {
        started = false;
        return "";
      }

      const x = getX(point, index).toFixed(2);
      const y = getY(value).toFixed(2);
      const command = started ? "L" : "M";

      started = true;
      return `${command} ${x} ${y}`;
    })
    .filter(Boolean)
    .join(" ");
}

function buildBaselineAreaPath(
  linePath: string,
  firstPointX: number,
  lastPointX: number,
  baselineY: number
) {
  return `${linePath} L ${lastPointX.toFixed(2)} ${baselineY.toFixed(
    2
  )} L ${firstPointX.toFixed(2)} ${baselineY.toFixed(2)} Z`;
}

export default function IntradayTrendChart({
  points,
  previousClose,
  label,
  source,
  indicators = defaultIntradayIndicators,
  session = taiwanIntradaySession,
  revealKey,
  refreshIntervalMs,
  updatedAt,
}: Props) {
  const chartId = useId();
  const safeChartId = chartId.replace(/[^a-zA-Z0-9_-]/g, "");
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [showLimitRange, setShowLimitRange] = useState(false);
  const [interval, setInterval] = useState<IntradayInterval>(1);
  const [activeRevealKey, setActiveRevealKey] = useState<string | null>(null);

  const data = useMemo(() => {
    return enrichIntradayPoints(aggregateIntradayPoints(points, interval, session));
  }, [points, interval, session]);

  const safeHoverIndex =
    hoverIndex !== null && hoverIndex >= 0 && hoverIndex < data.length ? hoverIndex : null;
  const stableRevealKey = revealKey ?? label;
  const dataReadyForReveal = data.length >= 2;

  useEffect(() => {
    if (!dataReadyForReveal) return;

    const timeoutId = window.setTimeout(() => {
      setActiveRevealKey((current) => {
        if (playedIntradayRevealKeys.has(stableRevealKey)) {
          return current === stableRevealKey ? current : null;
        }

        return stableRevealKey;
      });
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [dataReadyForReveal, stableRevealKey]);

  if (data.length < 2) {
    return (
      <div className="flex h-[420px] items-center justify-center border border-slate-200 bg-white text-sm text-slate-500">
        今日走勢資料不足
      </div>
    );
  }

  const width = 1000;
  const indicatorHeight = 48;
  const indicatorGap = 14;
  const paddingLeft = 58;
  const paddingRight = 90;
  const priceTop = 30;
  const priceHeight = 260;
  const volumeTop = 322;
  const volumeHeight = 62;
  const labelY = 406;
  const lowerPanelStartTop = 428;
  const lowerPanelKeys: Array<"rsi" | "macd"> = [];

  if (indicators.rsi) lowerPanelKeys.push("rsi");
  if (indicators.macd) lowerPanelKeys.push("macd");

  const rsiPanelIndex = lowerPanelKeys.indexOf("rsi");
  const macdPanelIndex = lowerPanelKeys.indexOf("macd");
  const rsiTop =
    rsiPanelIndex >= 0
      ? lowerPanelStartTop + rsiPanelIndex * (indicatorHeight + indicatorGap)
      : null;
  const macdTop =
    macdPanelIndex >= 0
      ? lowerPanelStartTop + macdPanelIndex * (indicatorHeight + indicatorGap)
      : null;
  const indicatorBottom =
    lowerPanelKeys.length > 0
      ? lowerPanelStartTop +
        (lowerPanelKeys.length - 1) * (indicatorHeight + indicatorGap) +
        indicatorHeight
      : volumeTop + volumeHeight;
  const height = lowerPanelKeys.length > 0 ? indicatorBottom + 28 : 420;
  const usableWidth = width - paddingLeft - paddingRight;
  const latestPrice = data[data.length - 1]?.price ?? null;
  const latestPoint = safeHoverIndex !== null ? data[safeHoverIndex] : data[data.length - 1];
  const change =
    latestPrice !== null && previousClose !== null ? latestPrice - previousClose : null;

  const priceValues = [
    ...data.map((point) => point.price),
    ...(indicators.vwap ? data.map((point) => point.vwap) : []),
    ...(indicators.twap ? data.map((point) => point.twap) : []),
    ...(indicators.ema ? data.flatMap((point) => [point.emaFast, point.emaSlow]) : []),
    ...(previousClose !== null ? [previousClose] : []),
  ].filter(validNumber);
  const priceScale = getPriceScale(priceValues, previousClose, showLimitRange);
  const yMin = priceScale.min;
  const yMax = priceScale.max;
  const yRange = yMax - yMin || 1;
  const limitTolerance = previousClose === null ? 0 : getTaiwanPriceStep(previousClose) * 0.51;
  const volumes = data
    .map((point) => point.volume)
    .filter(validNumber);
  const maxVolume = Math.max(...volumes, 1);
  const cumulativeVolumes = data.reduce<number[]>((result, point, index) => {
    const previous = index > 0 ? result[index - 1] : 0;
    const volume = validNumber(point.volume) && point.volume > 0 ? point.volume : 0;

    result.push(previous + volume);

    return result;
  }, []);
  const totalVolume = cumulativeVolumes[cumulativeVolumes.length - 1] ?? null;
  const displayedVolume =
    safeHoverIndex !== null ? cumulativeVolumes[safeHoverIndex] ?? null : totalVolume;
  const rangeHigh = data.reduce<{ index: number; value: number } | null>(
    (best, point, index) => {
      const value = point.high ?? point.price;

      if (!validNumber(value)) return best;
      if (best === null || value > best.value) return { index, value };

      return best;
    },
    null
  );
  const rangeLow = data.reduce<{ index: number; value: number } | null>(
    (best, point, index) => {
      const value = point.low ?? point.price;

      if (!validNumber(value)) return best;
      if (best === null || value < best.value) return { index, value };

      return best;
    },
    null
  );
  const rangeHighIsLimit =
    rangeHigh !== null &&
    priceScale.limitUp !== null &&
    nearlyEqual(rangeHigh.value, priceScale.limitUp, limitTolerance);
  const rangeLowIsLimit =
    rangeLow !== null &&
    priceScale.limitDown !== null &&
    nearlyEqual(rangeLow.value, priceScale.limitDown, limitTolerance);
  const macdValues = data
    .flatMap((point) => [point.macd, point.macdSignal, point.macdHistogram])
    .filter(validNumber);
  const macdAbsMax = Math.max(...macdValues.map((value) => Math.abs(value)), 1);

  function getPointX(point: IntradayChartPoint) {
    return paddingLeft + session.getXRatio(point.time) * usableWidth;
  }

  function getPriceY(value: number) {
    return priceTop + ((yMax - value) / yRange) * priceHeight;
  }

  function getVolumeY(value: number) {
    return volumeTop + volumeHeight - (value / maxVolume) * volumeHeight;
  }

  function getPanelY(top: number, value: number, min: number, max: number) {
    const range = max - min || 1;
    return top + ((max - value) / range) * indicatorHeight;
  }

  function handleMouseMove(event: React.MouseEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const localX = paddingLeft + ratio * usableWidth;
    const closest = data.reduce<{ index: number; distance: number } | null>(
      (best, point, index) => {
        const distance = Math.abs(getPointX(point) - localX);

        if (best === null || distance < best.distance) return { index, distance };

        return best;
      },
      null
    );

    setHoverIndex(closest?.index ?? null);
  }

  const linePath = buildLinePath(data, getPointX, getPriceY);
  const vwapPath = buildNullableLinePath(data, (point) => point.vwap, getPointX, getPriceY);
  const twapPath = buildNullableLinePath(data, (point) => point.twap, getPointX, getPriceY);
  const emaFastPath = buildNullableLinePath(data, (point) => point.emaFast, getPointX, getPriceY);
  const emaSlowPath = buildNullableLinePath(data, (point) => point.emaSlow, getPointX, getPriceY);
  const rsiPath =
    rsiTop !== null
      ? buildNullableLinePath(data, (point) => point.rsi, getPointX, (value) =>
          getPanelY(rsiTop, value, 0, 100)
        )
      : "";
  const macdPath =
    macdTop !== null
      ? buildNullableLinePath(data, (point) => point.macd, getPointX, (value) =>
          getPanelY(macdTop, value, -macdAbsMax, macdAbsMax)
        )
      : "";
  const macdSignalPath =
    macdTop !== null
      ? buildNullableLinePath(data, (point) => point.macdSignal, getPointX, (value) =>
          getPanelY(macdTop, value, -macdAbsMax, macdAbsMax)
        )
      : "";
  const firstPointX = getPointX(data[0]);
  const lastPointX = getPointX(data[data.length - 1]);
  const hoverX = safeHoverIndex !== null ? getPointX(data[safeHoverIndex]) : null;
  const previousCloseY = previousClose !== null ? getPriceY(previousClose) : null;
  const baselineY = previousCloseY ?? volumeTop;
  const areaPath = buildBaselineAreaPath(linePath, firstPointX, lastPointX, baselineY);
  const sessionMinutes = session.endMinutes - session.startMinutes;
  const chartAreaRight = width - paddingRight;
  const clipAboveId = `${safeChartId}-above`;
  const clipBelowId = `${safeChartId}-below`;
  const revealClipId = `${safeChartId}-reveal`;
  const revealCoverClass = `intraday-reveal-cover-${safeChartId}`;
  const revealAnimationName = `intraday-reveal-${safeChartId}`;
  const shouldShowRevealCover = activeRevealKey === stableRevealKey;
  const barWidth = clamp((usableWidth / sessionMinutes) * interval * 0.7, 1, 10);
  const timeTicks = session.timeTicks;
  const formatVolumeValue = session.volumeFormatter ?? formatLots;

  return (
    <div className="border border-slate-200 bg-white">
      <div className="flex min-h-16 items-start justify-between gap-4 border-b border-slate-200 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">今日走勢 / 成交量</div>
          <div className="mt-1 text-xs text-slate-500">
            {label} · {formatSource(source)} · {data.length} 點
          </div>
          {refreshIntervalMs ? (
            <div className="mt-1 text-xs text-slate-500">
              盤中每 {Math.round(refreshIntervalMs / 1000)} 秒更新
              {updatedAt ? `，最後更新 ${updatedAt}` : ""}
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="inline-flex border border-slate-300 bg-white">
              {intervalOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => {
                    setHoverIndex(null);
                    setInterval(option.value);
                  }}
                  className={[
                    "h-7 px-2.5 text-xs font-semibold transition",
                    interval === option.value
                      ? "bg-slate-900 text-white"
                      : "text-slate-600 hover:bg-slate-100",
                  ].join(" ")}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="grid shrink-0 grid-cols-2 gap-x-8 gap-y-2 text-right sm:grid-cols-4">
          <div>
            <span className="text-xs text-slate-400">昨收</span>
            <div className="mt-1 text-base font-bold text-slate-800">
              {formatPrice(previousClose)}
            </div>
          </div>
          <div>
            <span className="text-xs text-slate-400">最低</span>
            <div className="mt-1 text-base font-bold text-emerald-600">
              {formatPrice(rangeLow?.value)}
            </div>
          </div>
          <div>
            <span className="text-xs text-slate-400">最高</span>
            <div className="mt-1 text-base font-bold text-red-600">
              {formatPrice(rangeHigh?.value)}
            </div>
          </div>
          <div>
            <span className="text-xs text-slate-400">成交量(張)</span>
            <div className="mt-1 text-base font-bold text-slate-800">
              {formatVolumeValue(displayedVolume)}
            </div>
          </div>
          {indicators.vwap ? (
            <div>
              <span className="text-xs text-slate-400">VWAP</span>
              <div className="mt-1 text-base font-bold text-blue-700">
                {formatPrice(latestPoint?.vwap)}
              </div>
            </div>
          ) : null}
          {indicators.twap ? (
            <div>
              <span className="text-xs text-slate-400">TWAP</span>
              <div className="mt-1 text-base font-bold text-slate-800">
                {formatPrice(latestPoint?.twap)}
              </div>
            </div>
          ) : null}
          {indicators.ema ? (
            <div>
              <span className="text-xs text-slate-400">EMA5/20</span>
              <div className="mt-1 text-base font-bold text-slate-800">
                {formatPrice(latestPoint?.emaFast)} / {formatPrice(latestPoint?.emaSlow)}
              </div>
            </div>
          ) : null}
          {indicators.rsi ? (
            <div>
              <span className="text-xs text-slate-400">RSI</span>
              <div className="mt-1 text-base font-bold text-fuchsia-700">
                {formatIndicator(latestPoint?.rsi)}
              </div>
            </div>
          ) : null}
          {indicators.macd ? (
            <div>
              <span className="text-xs text-slate-400">MACD H</span>
              <div className="mt-1 text-base font-bold text-slate-800">
                {formatIndicator(latestPoint?.macdHistogram)}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }}>
        <rect x="0" y="0" width={width} height={height} className="fill-white" />
        <defs>
          <style>
            {`
              @keyframes ${revealAnimationName} {
                0% {
                  opacity: 1;
                  transform: translateX(0);
                }
                92% {
                  opacity: 1;
                }
                100% {
                  opacity: 0;
                  transform: translateX(${usableWidth}px);
                }
              }

              .${revealCoverClass} {
                animation: ${revealAnimationName} 1300ms cubic-bezier(0.22, 1, 0.36, 1) both;
                pointer-events: none;
                transform-box: fill-box;
              }

              @media (prefers-reduced-motion: reduce) {
                .${revealCoverClass} {
                  animation-duration: 1ms;
                }
              }
            `}
          </style>
          <clipPath id={clipAboveId}>
            <rect
              x={paddingLeft}
              y={priceTop}
              width={usableWidth}
              height={Math.max(0, baselineY - priceTop)}
            />
          </clipPath>
          <clipPath id={clipBelowId}>
            <rect
              x={paddingLeft}
              y={baselineY}
              width={usableWidth}
              height={Math.max(0, volumeTop - baselineY)}
            />
          </clipPath>
          <clipPath id={revealClipId}>
            <rect
              x={paddingLeft}
              y={priceTop}
              width={usableWidth}
              height={indicatorBottom - priceTop}
            />
          </clipPath>
        </defs>

        {priceScale.ticks.map((price) => {
          const y = getPriceY(price);
          const pct =
            previousClose !== null && previousClose !== 0
              ? ((price - previousClose) / previousClose) * 100
              : null;

          return (
            <g key={price}>
              <line
                x1={paddingLeft}
                x2={chartAreaRight}
                y1={y}
                y2={y}
                className="stroke-slate-100"
              />
              <text
                x={paddingLeft - 10}
                y={y + 4}
                textAnchor="end"
                className={`${priceToneClass(
                  price,
                  previousClose,
                  priceScale.limitUp,
                  priceScale.limitDown
                )} text-[11px]`}
              >
                {formatPrice(price)}
              </text>
              {pct !== null ? (
                <text
                  x={chartAreaRight + 8}
                  y={y + 4}
                  textAnchor="start"
                  className={`${pricePctToneClass(pct)} text-[11px]`}
                >
                  {formatPct(pct)}
                </text>
              ) : null}
            </g>
          );
        })}

        {timeTicks.map((tick) => {
          const ratio =
            (tick.minutes - session.startMinutes) /
            (session.endMinutes - session.startMinutes);
          const x = paddingLeft + ratio * usableWidth;

          return (
            <g key={tick.label}>
              <line
                x1={x}
                x2={x}
                y1={priceTop}
                y2={volumeTop + volumeHeight}
                className="stroke-slate-100"
              />
              <text
                x={x}
                y={labelY}
                textAnchor={tick.label === "09:00" ? "start" : tick.label === "13:30" ? "end" : "middle"}
                className="fill-slate-500 text-[11px]"
              >
                {tick.label}
              </text>
            </g>
          );
        })}

        {previousCloseY !== null ? (
          <g>
            <line
              x1={paddingLeft}
              x2={chartAreaRight}
              y1={previousCloseY}
              y2={previousCloseY}
              className="stroke-blue-500"
              strokeDasharray="4 4"
            />
            <text
              x={chartAreaRight + 8}
              y={previousCloseY - 6}
              textAnchor="start"
              className="fill-blue-600 text-[11px]"
            >
              昨收 {formatPrice(previousClose)}
            </text>
          </g>
        ) : null}

        {showLimitRange && priceScale.limitUp !== null ? (
          <g>
            <line
              x1={paddingLeft}
              x2={chartAreaRight}
              y1={getPriceY(priceScale.limitUp)}
              y2={getPriceY(priceScale.limitUp)}
              className="stroke-red-200"
              strokeDasharray="4 4"
            />
          </g>
        ) : null}

        {showLimitRange && priceScale.limitDown !== null ? (
          <g>
            <line
              x1={paddingLeft}
              x2={chartAreaRight}
              y1={getPriceY(priceScale.limitDown)}
              y2={getPriceY(priceScale.limitDown)}
              className="stroke-emerald-200"
              strokeDasharray="4 4"
            />
          </g>
        ) : null}

        {previousCloseY !== null ? (
          <>
            <path d={areaPath} className="fill-red-100 opacity-80" clipPath={`url(#${clipAboveId})`} />
            <path
              d={areaPath}
              className="fill-emerald-100 opacity-80"
              clipPath={`url(#${clipBelowId})`}
            />
            <path
              d={linePath}
              fill="none"
              strokeWidth="2.4"
              className="stroke-red-600"
              strokeLinecap="round"
              strokeLinejoin="round"
              clipPath={`url(#${clipAboveId})`}
            />
            <path
              d={linePath}
              fill="none"
              strokeWidth="2.4"
              className="stroke-emerald-600"
              strokeLinecap="round"
              strokeLinejoin="round"
              clipPath={`url(#${clipBelowId})`}
            />
          </>
        ) : (
          <path
            d={linePath}
            fill="none"
            strokeWidth="2.4"
            className={change !== null && change < 0 ? "stroke-emerald-600" : "stroke-red-600"}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {indicators.vwap && vwapPath ? (
          <path
            d={vwapPath}
            fill="none"
            strokeWidth="1.8"
            className="stroke-blue-600"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.twap && twapPath ? (
          <path
            d={twapPath}
            fill="none"
            strokeWidth="1.4"
            className="stroke-slate-500"
            strokeDasharray="5 4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ema && emaFastPath ? (
          <path
            d={emaFastPath}
            fill="none"
            strokeWidth="1.4"
            className="stroke-cyan-600"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ema && emaSlowPath ? (
          <path
            d={emaSlowPath}
            fill="none"
            strokeWidth="1.4"
            className="stroke-amber-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}

        {rangeHigh && !rangeHighIsLimit ? (
          <g>
            {(() => {
              const x = getPointX(data[rangeHigh.index]);
              const y = getPriceY(rangeHigh.value);
              const label = labelPosition(x, paddingLeft, paddingRight, width);
              const markerLabelY = clamp(y - 12, priceTop + 12, volumeTop - 8);

              return (
                <>
                  <circle cx={x} cy={y} r="3.5" className="fill-red-600" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={markerLabelY}
                    className="stroke-red-400"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={markerLabelY - 3}
                    textAnchor={label.anchor}
                    className="fill-red-600 text-[11px] font-semibold"
                  >
                    最高 {formatPrice(rangeHigh.value)}
                  </text>
                </>
              );
            })()}
          </g>
        ) : null}

        {rangeLow && !rangeLowIsLimit ? (
          <g>
            {(() => {
              const x = getPointX(data[rangeLow.index]);
              const y = getPriceY(rangeLow.value);
              const label = labelPosition(x, paddingLeft, paddingRight, width);
              const markerLabelY = clamp(y + 18, priceTop + 12, volumeTop - 8);

              return (
                <>
                  <circle cx={x} cy={y} r="3.5" className="fill-emerald-600" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={markerLabelY}
                    className="stroke-emerald-400"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={markerLabelY + 10}
                    textAnchor={label.anchor}
                    className="fill-emerald-600 text-[11px] font-semibold"
                  >
                    最低 {formatPrice(rangeLow.value)}
                  </text>
                </>
              );
            })()}
          </g>
        ) : null}

        {indicators.volume
          ? data.map((point, index) => {
              const volume = point.volume ?? 0;
              const volumeY = getVolumeY(volume);
              const volumeBarHeight = volumeTop + volumeHeight - volumeY;

              return (
                <rect
                  key={`${point.time}-${index}`}
                  x={getPointX(point) - barWidth / 2}
                  y={volumeY}
                  width={barWidth}
                  height={Math.max(volumeBarHeight, 1)}
                  className="fill-amber-300 opacity-70"
                />
              );
            })
          : null}

        {indicators.volume ? (
          <line
            x1={paddingLeft}
            x2={chartAreaRight}
            y1={volumeTop}
            y2={volumeTop}
            className="stroke-slate-100"
          />
        ) : null}

        {rsiTop !== null ? (
          <g>
            <line
              x1={paddingLeft}
              x2={chartAreaRight}
              y1={rsiTop}
              y2={rsiTop}
              className="stroke-slate-200"
            />
            <text
              x={paddingLeft - 10}
              y={rsiTop + 12}
              textAnchor="end"
              className="fill-slate-500 text-[11px]"
            >
              RSI
            </text>
            {[30, 50, 70].map((value) => {
              const y = getPanelY(rsiTop, value, 0, 100);

              return (
                <line
                  key={value}
                  x1={paddingLeft}
                  x2={chartAreaRight}
                  y1={y}
                  y2={y}
                  className={value === 50 ? "stroke-slate-200" : "stroke-slate-100"}
                  strokeDasharray={value === 50 ? undefined : "4 4"}
                />
              );
            })}
            {rsiPath ? (
              <path
                d={rsiPath}
                fill="none"
                strokeWidth="1.6"
                className="stroke-fuchsia-600"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null}
          </g>
        ) : null}

        {macdTop !== null ? (
          <g>
            <line
              x1={paddingLeft}
              x2={chartAreaRight}
              y1={macdTop}
              y2={macdTop}
              className="stroke-slate-200"
            />
            <text
              x={paddingLeft - 10}
              y={macdTop + 12}
              textAnchor="end"
              className="fill-slate-500 text-[11px]"
            >
              MACD
            </text>
            <line
              x1={paddingLeft}
              x2={chartAreaRight}
              y1={getPanelY(macdTop, 0, -macdAbsMax, macdAbsMax)}
              y2={getPanelY(macdTop, 0, -macdAbsMax, macdAbsMax)}
              className="stroke-slate-200"
            />
            {data.map((point, index) => {
              if (!validNumber(point.macdHistogram)) return null;

              const zeroY = getPanelY(macdTop, 0, -macdAbsMax, macdAbsMax);
              const valueY = getPanelY(macdTop, point.macdHistogram, -macdAbsMax, macdAbsMax);
              const y = Math.min(zeroY, valueY);
              const height = Math.max(Math.abs(zeroY - valueY), 1);

              return (
                <rect
                  key={`${point.time}-macd-${index}`}
                  x={getPointX(point) - barWidth / 2}
                  y={y}
                  width={barWidth}
                  height={height}
                  className={point.macdHistogram >= 0 ? "fill-red-200" : "fill-emerald-200"}
                />
              );
            })}
            {macdPath ? (
              <path
                d={macdPath}
                fill="none"
                strokeWidth="1.5"
                className="stroke-blue-600"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null}
            {macdSignalPath ? (
              <path
                d={macdSignalPath}
                fill="none"
                strokeWidth="1.5"
                className="stroke-amber-500"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null}
          </g>
        ) : null}

        {shouldShowRevealCover ? (
          <g
            key={activeRevealKey}
            className={revealCoverClass}
            clipPath={`url(#${revealClipId})`}
            aria-hidden="true"
            onAnimationStart={() => {
              playedIntradayRevealKeys.add(stableRevealKey);
            }}
            onAnimationEnd={() => {
              setActiveRevealKey((current) => (current === stableRevealKey ? null : current));
            }}
          >
            <rect
              x={paddingLeft}
              y={priceTop}
              width={usableWidth}
              height={indicatorBottom - priceTop}
              className="fill-white"
            />
          </g>
        ) : null}

        {hoverX !== null ? (
          <line
            x1={hoverX}
            x2={hoverX}
            y1={priceTop}
            y2={indicatorBottom}
            className="stroke-slate-400"
            strokeDasharray="4 4"
          />
        ) : null}

        <rect
          x={paddingLeft}
          y={priceTop}
          width={usableWidth}
          height={indicatorBottom - priceTop}
          fill="transparent"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIndex(null)}
        />
      </svg>

      <div className="flex items-center justify-end border-t border-slate-200 px-4 py-2">
        <button
          type="button"
          onClick={() => setShowLimitRange((value) => !value)}
          className={[
            "h-8 border px-3 text-xs font-semibold transition",
            showLimitRange
              ? "border-red-700 bg-red-700 text-white"
              : "border-slate-300 bg-white text-slate-700 hover:border-red-700 hover:text-red-700",
          ].join(" ")}
        >
          顯示漲跌停
        </button>
      </div>
    </div>
  );
}

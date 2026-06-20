"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { IntradayTrendPoint } from "@/types/market";
import { useT, type TranslationFunction } from "@/i18n";
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
  priceLimitEnabled?: boolean;
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

type HoverPriceGuideState = {
  y: number;
  snap: "high" | "low" | null;
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
  descriptionKey: string;
}> = [
  {
    key: "volume",
    label: "VOL",
    descriptionKey: "stockDetail.intraday.indicators.volume",
  },
  {
    key: "vwap",
    label: "VWAP",
    descriptionKey: "stockDetail.intraday.indicators.vwap",
  },
  {
    key: "twap",
    label: "TWAP",
    descriptionKey: "stockDetail.intraday.indicators.twap",
  },
  {
    key: "ema",
    label: "EMA",
    descriptionKey: "stockDetail.intraday.indicators.ema",
  },
  {
    key: "rsi",
    label: "RSI",
    descriptionKey: "stockDetail.intraday.indicators.rsi",
  },
  {
    key: "macd",
    label: "MACD",
    descriptionKey: "stockDetail.intraday.indicators.macd",
  },
];

const playedIntradayRevealKeys = new Set<string>();
const PRICE_GUIDE_SNAP_DISTANCE = 10;

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatSource(t: TranslationFunction, value: string) {
  if (value === "nstock_minute_stock_data_twse_mis_volume") {
    return t("stockDetail.intraday.sources.nstockMinuteWithVolume");
  }
  if (value === "nstock_minute_stock_data") {
    return t("stockDetail.intraday.sources.nstockMinute");
  }
  if (value === "yahoo_finance_chart_twse_mis_volume") {
    return t("stockDetail.intraday.sources.yahooWithVolume");
  }
  if (value === "yahoo_finance_chart") {
    return t("stockDetail.intraday.sources.yahoo");
  }
  if (value === "twse_mis_snapshot") {
    return t("stockDetail.intraday.sources.twseSnapshot");
  }
  return t("stockDetail.intraday.sources.fallback");
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
  showLimitRange: boolean,
  priceLimitEnabled: boolean
) {
  const referencePrice = previousClose ?? prices[prices.length - 1] ?? 1;
  const hardMax = priceLimitEnabled && previousClose !== null ? previousClose * 1.1 : null;
  const hardMin = priceLimitEnabled && previousClose !== null ? previousClose * 0.9 : null;
  const limitUp = hardMax === null ? null : floorToTaiwanPriceStep(hardMax);
  const limitDown = hardMin === null ? null : ceilToTaiwanPriceStep(hardMin);
  const limitTolerance = priceLimitEnabled ? getTaiwanPriceStep(referencePrice) * 0.51 : 0;
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
    return "fill-omi-market-up font-bold";
  }

  if (limitDown !== null && nearlyEqual(price, limitDown, step)) {
    return "fill-omi-market-down font-bold";
  }

  if (previousClose === null || price === previousClose) return "fill-omi-text-muted";
  if (price > previousClose) return "fill-omi-market-up";
  return "fill-omi-market-down";
}

function pricePctToneClass(value: number) {
  if (value > 0) return "fill-omi-market-up";
  if (value < 0) return "fill-omi-market-down";
  return "fill-omi-text";
}

function formatPct(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function priceGuideSnap(value: number | null, reference: number | null): HoverPriceGuideState["snap"] {
  if (!validNumber(value) || !validNumber(reference) || value === reference) return null;
  return value > reference ? "high" : "low";
}

function livePointTone(price: number | null, reference: number | null) {
  if (validNumber(price) && validNumber(reference) && reference !== 0) {
    if (price > reference) {
      return {
        core: "fill-omi-market-up",
        ring: "stroke-omi-market-up-border",
      };
    }

    if (price < reference) {
      return {
        core: "fill-omi-market-down",
        ring: "stroke-omi-market-down-border",
      };
    }
  }

  return {
    core: "fill-omi-text-muted",
    ring: "stroke-omi-border",
  };
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
  priceLimitEnabled = true,
}: Props) {
  const chartId = useId();
  const t = useT();
  const safeChartId = chartId.replace(/[^a-zA-Z0-9_-]/g, "");
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [hoverPriceGuide, setHoverPriceGuide] = useState<HoverPriceGuideState | null>(null);
  const [showLimitRange, setShowLimitRange] = useState(false);
  const [interval, setInterval] = useState<IntradayInterval>(1);
  const [activeRevealKey, setActiveRevealKey] = useState<string | null>(null);
  const revealCoverRef = useRef<HTMLDivElement | null>(null);

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

        playedIntradayRevealKeys.add(stableRevealKey);
        return stableRevealKey;
      });
    }, 0);

    return () => window.clearTimeout(timeoutId);
  }, [dataReadyForReveal, stableRevealKey]);

  useEffect(() => {
    if (activeRevealKey === null) return;

    const revealCover = revealCoverRef.current;
    if (revealCover === null) return;

    const durationMs = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 1440;
    const clearRevealCover = () => {
      setActiveRevealKey((current) => (current === activeRevealKey ? null : current));
    };
    const animation = revealCover.animate(
      [
        { opacity: 1, transform: "translateX(0)" },
        { opacity: 0, transform: "translateX(100%)" },
      ],
      {
        duration: durationMs,
        easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        fill: "forwards",
      }
    );
    const timeoutId = window.setTimeout(clearRevealCover, durationMs + 250);

    animation.addEventListener("finish", clearRevealCover, { once: true });

    return () => {
      animation.removeEventListener("finish", clearRevealCover);
      animation.cancel();
      window.clearTimeout(timeoutId);
    };
  }, [activeRevealKey]);

  if (data.length < 2) {
    return (
      <div className="flex h-[420px] items-center justify-center border border-omi-border-subtle bg-omi-surface text-sm text-omi-text-muted">
        {t("stockDetail.intraday.insufficient")}
      </div>
    );
  }

  const width = 1000;
  const indicatorHeight = 48;
  const indicatorGap = 14;
  const paddingLeft = 84;
  const paddingRight = 90;
  const priceTop = 30;
  const priceHeight = 260;
  const priceBottom = priceTop + priceHeight;
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
  const change =
    latestPrice !== null && previousClose !== null ? latestPrice - previousClose : null;

  const priceValues = [
    ...data.map((point) => point.price),
    ...(indicators.vwap ? data.map((point) => point.vwap) : []),
    ...(indicators.twap ? data.map((point) => point.twap) : []),
    ...(indicators.ema ? data.flatMap((point) => [point.emaFast, point.emaSlow]) : []),
    ...(previousClose !== null ? [previousClose] : []),
  ].filter(validNumber);
  const priceScale = getPriceScale(
    priceValues,
    previousClose,
    showLimitRange && priceLimitEnabled,
    priceLimitEnabled
  );
  const yMin = priceScale.min;
  const yMax = priceScale.max;
  const yRange = yMax - yMin || 1;
  const limitTolerance =
    previousClose === null || !priceLimitEnabled ? 0 : getTaiwanPriceStep(previousClose) * 0.51;
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
    const pointerY =
      priceTop + clamp((event.clientY - rect.top) / rect.height, 0, 1) * (indicatorBottom - priceTop);
    const closest = data.reduce<{ index: number; distance: number } | null>(
      (best, point, index) => {
        const distance = Math.abs(getPointX(point) - localX);

        if (best === null || distance < best.distance) return { index, distance };

        return best;
      },
      null
    );
    const safeIndex = closest?.index ?? null;

    setHoverIndex(safeIndex);

    if (safeIndex === null || pointerY < priceTop || pointerY > priceBottom) {
      setHoverPriceGuide(null);
      return;
    }

    const point = data[safeIndex];
    const high = point.high ?? point.price;
    const low = point.low ?? point.price;
    const candidates = [
      validNumber(high)
        ? { value: high, y: getPriceY(high), distance: Math.abs(pointerY - getPriceY(high)) }
        : null,
      validNumber(low)
        ? { value: low, y: getPriceY(low), distance: Math.abs(pointerY - getPriceY(low)) }
        : null,
    ].filter((candidate): candidate is { value: number; y: number; distance: number } =>
      candidate !== null
    );
    const nearest = candidates.reduce<(typeof candidates)[number] | null>(
      (best, candidate) =>
        best === null || candidate.distance < best.distance ? candidate : best,
      null
    );

    const pointerPrice = yMax - ((clamp(pointerY, priceTop, priceBottom) - priceTop) / priceHeight) * yRange;

    setHoverPriceGuide(
      nearest !== null && nearest.distance <= PRICE_GUIDE_SNAP_DISTANCE
        ? { y: nearest.y, snap: priceGuideSnap(nearest.value, previousClose) }
        : {
            y: clamp(pointerY, priceTop, priceBottom),
            snap: priceGuideSnap(pointerPrice, previousClose),
          }
    );
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
  const latestPoint = data[data.length - 1];
  const latestPointY = getPriceY(latestPoint.price);
  const latestPointTone = livePointTone(latestPoint.price, previousClose);
  const hoverX = safeHoverIndex !== null ? getPointX(data[safeHoverIndex]) : null;
  const hoverPriceGuideY =
    safeHoverIndex !== null && hoverPriceGuide !== null
      ? clamp(hoverPriceGuide.y, priceTop, priceBottom)
      : null;
  const hoverPriceGuideSnap =
    safeHoverIndex !== null && hoverPriceGuide !== null ? hoverPriceGuide.snap : null;
  const hoverPriceGuideValue =
    hoverPriceGuideY !== null
      ? yMax - ((hoverPriceGuideY - priceTop) / priceHeight) * yRange
      : null;
  const hoverPriceGuideLabel =
    hoverPriceGuideValue !== null ? formatPrice(hoverPriceGuideValue) : null;
  const hoverPriceGuideStrokeClass =
    hoverPriceGuideSnap === "high"
      ? "stroke-omi-market-up-flash"
      : hoverPriceGuideSnap === "low"
        ? "stroke-omi-market-down-flash"
        : "stroke-omi-text-muted";
  const hoverPriceGuideTextClass =
    hoverPriceGuideSnap === "high"
      ? "fill-omi-market-up-strong"
      : hoverPriceGuideSnap === "low"
        ? "fill-omi-market-down-strong"
        : "fill-omi-text";
  const previousCloseY = previousClose !== null ? getPriceY(previousClose) : null;
  const baselineY = previousCloseY ?? volumeTop;
  const areaPath = buildBaselineAreaPath(linePath, firstPointX, lastPointX, baselineY);
  const sessionMinutes = session.endMinutes - session.startMinutes;
  const chartAreaRight = width - paddingRight;
  const clipAboveId = `${safeChartId}-above`;
  const clipBelowId = `${safeChartId}-below`;
  const shouldShowRevealCover = activeRevealKey === stableRevealKey;
  const barWidth = clamp((usableWidth / sessionMinutes) * interval * 0.7, 1, 10);
  const timeTicks = session.timeTicks;
  const formatVolumeValue = session.volumeFormatter ?? formatLots;

  return (
    <div className="border border-omi-border-subtle bg-omi-surface">
      <div className="flex min-h-16 items-start justify-between gap-4 border-b border-omi-border-subtle px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-omi-text">
            {t("stockDetail.intraday.title")}
          </div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {label} · {formatSource(t, source)} ·{" "}
            {t("stockDetail.intraday.pointCount", { count: data.length })}
          </div>
          {refreshIntervalMs ? (
            <div className="mt-1 text-xs text-omi-text-muted">
              {t(
                updatedAt
                  ? "stockDetail.intraday.refreshEveryUpdated"
                  : "stockDetail.intraday.refreshEvery",
                {
                  seconds: Math.round(refreshIntervalMs / 1000),
                  updatedAt,
                }
              )}
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="inline-flex border border-omi-border bg-omi-surface">
              {intervalOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => {
                    setHoverIndex(null);
                    setHoverPriceGuide(null);
                    setInterval(option.value);
                  }}
                  className={[
                    "h-7 px-2.5 text-xs font-semibold transition",
                    interval === option.value
                      ? "bg-omi-control text-omi-text-inverse"
                      : "text-omi-text-muted hover:bg-omi-surface-muted",
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
            <span className="text-xs text-omi-text-subtle">
              {t("stockDetail.intraday.previousClose")}
            </span>
            <div className="mt-1 text-base font-bold text-omi-text">
              {formatPrice(previousClose)}
            </div>
          </div>
          <div>
            <span className="text-xs text-omi-text-subtle">
              {t("stockDetail.intraday.low")}
            </span>
            <div className="mt-1 text-base font-bold text-omi-market-down">
              {formatPrice(rangeLow?.value)}
            </div>
          </div>
          <div>
            <span className="text-xs text-omi-text-subtle">
              {t("stockDetail.intraday.high")}
            </span>
            <div className="mt-1 text-base font-bold text-omi-market-up">
              {formatPrice(rangeHigh?.value)}
            </div>
          </div>
          <div>
            <span className="text-xs text-omi-text-subtle">
              {t("stockDetail.intraday.volumeLots")}
            </span>
            <div className="mt-1 text-base font-bold text-omi-text">
              {formatVolumeValue(displayedVolume)}
            </div>
          </div>
        </div>
      </div>

      <div className="relative overflow-hidden">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }}>
        <rect x="0" y="0" width={width} height={height} className="fill-omi-surface" />
        <defs>
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
                className="stroke-omi-border-subtle"
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
                )} text-[12px] font-medium`}
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
                className="stroke-omi-border-subtle"
              />
              <text
                x={x}
                y={labelY}
                textAnchor={tick.label === "09:00" ? "start" : tick.label === "13:30" ? "end" : "middle"}
                className="fill-omi-text-muted text-[11px]"
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
              className="stroke-omi-chart-blue"
              strokeDasharray="4 4"
            />
            <text
              x={chartAreaRight + 8}
              y={previousCloseY - 6}
              textAnchor="start"
              className="fill-omi-chart-blue text-[11px]"
            >
              {t("stockDetail.intraday.previousCloseMarker", {
                value: formatPrice(previousClose),
              })}
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
              className="stroke-omi-market-up-border"
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
              className="stroke-omi-market-down-border"
              strokeDasharray="4 4"
            />
          </g>
        ) : null}

        {previousCloseY !== null ? (
          <>
            <path d={areaPath} className="fill-omi-market-up-soft opacity-80" clipPath={`url(#${clipAboveId})`} />
            <path
              d={areaPath}
              className="fill-omi-market-down-soft opacity-80"
              clipPath={`url(#${clipBelowId})`}
            />
            <path
              d={linePath}
              fill="none"
              strokeWidth="2.4"
              className="stroke-omi-market-up"
              strokeLinecap="round"
              strokeLinejoin="round"
              clipPath={`url(#${clipAboveId})`}
            />
            <path
              d={linePath}
              fill="none"
              strokeWidth="2.4"
              className="stroke-omi-market-down"
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
            className={change !== null && change < 0 ? "stroke-omi-market-down" : "stroke-omi-market-up"}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}

        {indicators.vwap && vwapPath ? (
          <path
            d={vwapPath}
            fill="none"
            strokeWidth="1.8"
            className="stroke-omi-chart-blue"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.twap && twapPath ? (
          <path
            d={twapPath}
            fill="none"
            strokeWidth="1.4"
            className="stroke-omi-text-muted"
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
            className="stroke-omi-chart-cyan"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ema && emaSlowPath ? (
          <path
            d={emaSlowPath}
            fill="none"
            strokeWidth="1.4"
            className="stroke-omi-chart-amber"
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
                  <circle cx={x} cy={y} r="3.5" className="fill-omi-market-up" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={markerLabelY}
                    className="stroke-omi-market-up-border"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={markerLabelY - 3}
                    textAnchor={label.anchor}
                    className="fill-omi-market-up text-[11px] font-semibold"
                  >
                    {t("stockDetail.intraday.highMarker", {
                      value: formatPrice(rangeHigh.value),
                    })}
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
                  <circle cx={x} cy={y} r="3.5" className="fill-omi-market-down" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={markerLabelY}
                    className="stroke-omi-market-down-border"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={markerLabelY + 10}
                    textAnchor={label.anchor}
                    className="fill-omi-market-down text-[11px] font-semibold"
                  >
                    {t("stockDetail.intraday.lowMarker", {
                      value: formatPrice(rangeLow.value),
                    })}
                  </text>
                </>
              );
            })()}
          </g>
        ) : null}

        <g key={`${latestPoint.time}-${latestPoint.price}`} pointerEvents="none">
          <circle
            cx={lastPointX}
            cy={latestPointY}
            r="8"
            className={`omi-live-point-ring ${latestPointTone.ring}`}
          />
          <circle
            cx={lastPointX}
            cy={latestPointY}
            r="3.2"
            className={`omi-live-point-core ${latestPointTone.core}`}
          />
        </g>

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
                  className="fill-omi-chart-amber-soft opacity-70"
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
            className="stroke-omi-border-subtle"
          />
        ) : null}

        {rsiTop !== null ? (
          <g>
            <line
              x1={paddingLeft}
              x2={chartAreaRight}
              y1={rsiTop}
              y2={rsiTop}
              className="stroke-omi-border-subtle"
            />
            <text
              x={paddingLeft - 10}
              y={rsiTop + 12}
              textAnchor="end"
              className="fill-omi-text-muted text-[11px]"
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
                  className={value === 50 ? "stroke-omi-border-subtle" : "stroke-omi-border-subtle"}
                  strokeDasharray={value === 50 ? undefined : "4 4"}
                />
              );
            })}
            {rsiPath ? (
              <path
                d={rsiPath}
                fill="none"
                strokeWidth="1.6"
                className="stroke-omi-chart-fuchsia"
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
              className="stroke-omi-border-subtle"
            />
            <text
              x={paddingLeft - 10}
              y={macdTop + 12}
              textAnchor="end"
              className="fill-omi-text-muted text-[11px]"
            >
              MACD
            </text>
            <line
              x1={paddingLeft}
              x2={chartAreaRight}
              y1={getPanelY(macdTop, 0, -macdAbsMax, macdAbsMax)}
              y2={getPanelY(macdTop, 0, -macdAbsMax, macdAbsMax)}
              className="stroke-omi-border-subtle"
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
                  className={point.macdHistogram >= 0 ? "fill-omi-market-up-border" : "fill-omi-market-down-border"}
                />
              );
            })}
            {macdPath ? (
              <path
                d={macdPath}
                fill="none"
                strokeWidth="1.5"
                className="stroke-omi-chart-blue"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null}
            {macdSignalPath ? (
              <path
                d={macdSignalPath}
                fill="none"
                strokeWidth="1.5"
                className="stroke-omi-chart-amber"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : null}
          </g>
        ) : null}

        {hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={priceTop}
              y2={indicatorBottom}
              className="stroke-omi-border-strong"
              strokeDasharray="4 4"
            />
            {hoverPriceGuideY !== null && hoverPriceGuideLabel !== null ? (
              <>
                <line
                  x1={paddingLeft}
                  x2={chartAreaRight}
                  y1={hoverPriceGuideY}
                  y2={hoverPriceGuideY}
                  className={hoverPriceGuideStrokeClass}
                  strokeDasharray="4 4"
                />
                <rect
                  x={4}
                  y={clamp(hoverPriceGuideY - 12, priceTop + 2, priceBottom - 24)}
                  width={paddingLeft - 10}
                  height={24}
                  rx={3}
                  className={`fill-omi-surface ${hoverPriceGuideStrokeClass}`}
                  strokeWidth="1.5"
                />
                <text
                  x={paddingLeft - 14}
                  y={clamp(hoverPriceGuideY + 4, priceTop + 18, priceBottom - 8)}
                  textAnchor="end"
                  className={`${hoverPriceGuideTextClass} text-[12px] font-semibold tabular-nums`}
                >
                  {formatPrice(hoverPriceGuideValue)}
                </text>
              </>
            ) : null}
          </g>
        ) : null}

        <rect
          x={paddingLeft}
          y={priceTop}
          width={usableWidth}
          height={indicatorBottom - priceTop}
          fill="transparent"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => {
            setHoverIndex(null);
            setHoverPriceGuide(null);
          }}
        />
        </svg>
        {shouldShowRevealCover ? (
          <div
            ref={revealCoverRef}
            key={activeRevealKey}
            className="pointer-events-none absolute inset-0 z-10 bg-omi-surface"
            aria-hidden="true"
            style={{
              willChange: "opacity, transform",
            }}
          />
        ) : null}
      </div>

      {priceLimitEnabled ? (
        <div className="flex items-center justify-end border-t border-omi-border-subtle px-4 py-2">
          <button
            type="button"
            onClick={() => setShowLimitRange((value) => !value)}
            className={[
              "h-8 border px-3 text-xs font-semibold transition",
              showLimitRange
                ? "border-omi-accent bg-omi-accent text-omi-text-inverse"
                : "border-omi-border bg-omi-surface text-omi-text hover:border-omi-accent hover:text-omi-danger",
            ].join(" ")}
          >
            {t("stockDetail.intraday.showPriceLimit")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

"use client";

import { useId, useMemo, useState } from "react";
import type { IntradayTrendPoint } from "@/types/market";
import {
  TAIWAN_SESSION_END_MINUTES,
  TAIWAN_SESSION_START_MINUTES,
  getTaiwanIntradayXRatio,
  isTaiwanRegularSessionPoint,
} from "@/lib/taiwanMarketTime";

type Props = {
  points: IntradayTrendPoint[];
  previousClose: number | null;
  label: string;
  source: string;
  refreshIntervalMs?: number;
  updatedAt?: string | null;
};

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

function buildLinePath(
  data: IntradayTrendPoint[],
  getX: (point: IntradayTrendPoint, index: number) => number,
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
  refreshIntervalMs,
  updatedAt,
}: Props) {
  const chartId = useId();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [showLimitRange, setShowLimitRange] = useState(false);

  const data = useMemo(() => {
    return points.filter((point) => {
      return (
        point.price !== null &&
        point.price !== undefined &&
        !Number.isNaN(point.price) &&
        isTaiwanRegularSessionPoint(point.time)
      );
    });
  }, [points]);

  const safeHoverIndex =
    hoverIndex !== null && hoverIndex >= 0 && hoverIndex < data.length ? hoverIndex : null;

  if (data.length < 2) {
    return (
      <div className="flex h-[420px] items-center justify-center border border-slate-200 bg-white text-sm text-slate-500">
        今日走勢資料不足
      </div>
    );
  }

  const width = 1000;
  const height = 420;
  const paddingLeft = 58;
  const paddingRight = 72;
  const priceTop = 30;
  const priceHeight = 260;
  const volumeTop = 322;
  const volumeHeight = 62;
  const labelY = 406;
  const usableWidth = width - paddingLeft - paddingRight;
  const latestPrice = data[data.length - 1]?.price ?? null;
  const change =
    latestPrice !== null && previousClose !== null ? latestPrice - previousClose : null;

  const priceValues = [
    ...data.map((point) => point.price),
    ...(previousClose !== null ? [previousClose] : []),
  ];
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

  function getPointX(point: IntradayTrendPoint) {
    return paddingLeft + getTaiwanIntradayXRatio(point.time) * usableWidth;
  }

  function getPriceY(value: number) {
    return priceTop + ((yMax - value) / yRange) * priceHeight;
  }

  function getVolumeY(value: number) {
    return volumeTop + volumeHeight - (value / maxVolume) * volumeHeight;
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
  const firstPointX = getPointX(data[0]);
  const lastPointX = getPointX(data[data.length - 1]);
  const hoverX = safeHoverIndex !== null ? getPointX(data[safeHoverIndex]) : null;
  const previousCloseY = previousClose !== null ? getPriceY(previousClose) : null;
  const baselineY = previousCloseY ?? volumeTop;
  const areaPath = buildBaselineAreaPath(linePath, firstPointX, lastPointX, baselineY);
  const sessionMinutes = TAIWAN_SESSION_END_MINUTES - TAIWAN_SESSION_START_MINUTES;
  const chartAreaRight = width - paddingRight;
  const clipAboveId = `${chartId}-above`.replace(/:/g, "");
  const clipBelowId = `${chartId}-below`.replace(/:/g, "");
  const timeTicks = [
    { label: "09:00", minutes: 9 * 60 },
    { label: "10:00", minutes: 10 * 60 },
    { label: "11:00", minutes: 11 * 60 },
    { label: "12:00", minutes: 12 * 60 },
    { label: "13:00", minutes: 13 * 60 },
    { label: "13:30", minutes: 13 * 60 + 30 },
  ];

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
              {formatLots(totalVolume)}
            </div>
          </div>
        </div>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="h-[420px] w-full">
        <rect x="0" y="0" width={width} height={height} className="fill-white" />
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
            (tick.minutes - TAIWAN_SESSION_START_MINUTES) /
            (TAIWAN_SESSION_END_MINUTES - TAIWAN_SESSION_START_MINUTES);
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

        {data.map((point, index) => {
          const volume = point.volume ?? 0;
          const volumeY = getVolumeY(volume);
          const volumeBarHeight = volumeTop + volumeHeight - volumeY;
          const barWidth = clamp((usableWidth / sessionMinutes) * 0.7, 1, 5);

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
        })}

        <line
          x1={paddingLeft}
          x2={chartAreaRight}
          y1={volumeTop}
          y2={volumeTop}
          className="stroke-slate-100"
        />

        {hoverX !== null ? (
          <line
            x1={hoverX}
            x2={hoverX}
            y1={priceTop}
            y2={volumeTop + volumeHeight}
            className="stroke-slate-400"
            strokeDasharray="4 4"
          />
        ) : null}

        <rect
          x={paddingLeft}
          y={priceTop}
          width={usableWidth}
          height={volumeTop + volumeHeight - priceTop}
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

"use client";

import { useMemo, useState } from "react";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";

type Props = {
  chartData: ChartPoint[];
  indicatorData?: StockIndicatorPoint[];
  label: string;
};

type MergedPoint = ChartPoint & {
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
  volumeMa20: number | null;
  changePct: number | null;
};

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  if (Math.abs(value) >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(1)}億`;
  }

  if (Math.abs(value) >= 10_000) {
    return `${(value / 10_000).toFixed(1)}萬`;
  }

  return new Intl.NumberFormat("zh-TW").format(value);
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function average(values: Array<number | null | undefined>) {
  const valid = values.filter((value): value is number => {
    return value !== null && value !== undefined && !Number.isNaN(value);
  });

  if (valid.length === 0) return null;

  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
}

function movingAverage(points: ChartPoint[], index: number, windowSize: number) {
  if (index + 1 < windowSize) return null;
  const slice = points.slice(index + 1 - windowSize, index + 1);
  return average(slice.map((point) => point.close));
}

function buildLinePath(
  data: MergedPoint[],
  getValue: (point: MergedPoint) => number | null,
  getX: (index: number) => number,
  getY: (value: number) => number
) {
  let path = "";
  let started = false;

  data.forEach((point, index) => {
    const value = getValue(point);

    if (value === null) {
      started = false;
      return;
    }

    const x = getX(index);
    const y = getY(value);

    if (!started) {
      path += `M ${x.toFixed(2)} ${y.toFixed(2)} `;
      started = true;
      return;
    }

    path += `L ${x.toFixed(2)} ${y.toFixed(2)} `;
  });

  return path.trim();
}

export default function StockKLineChart({ chartData, indicatorData = [], label }: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const data = useMemo<MergedPoint[]>(() => {
    const indicatorByTime = new Map<string, StockIndicatorPoint>();

    indicatorData.forEach((point) => {
      indicatorByTime.set(point.time, point);
    });

    return chartData.map((point, index) => {
      const indicator = indicatorByTime.get(point.time);

      return {
        ...point,
        ma5: indicator?.ma?.ma5 ?? movingAverage(chartData, index, 5),
        ma20: indicator?.ma?.ma20 ?? movingAverage(chartData, index, 20),
        ma60: indicator?.ma?.ma60 ?? movingAverage(chartData, index, 60),
        volumeMa20:
          indicator?.volume_ma?.volume_ma20 ??
          average(chartData.slice(Math.max(0, index - 19), index + 1).map((item) => item.volume)),
        changePct: indicator?.change_pct ?? null,
      };
    });
  }, [chartData, indicatorData]);

  const hoveredPoint =
    hoverIndex !== null ? data[hoverIndex] : data[data.length - 1] ?? null;

  if (data.length < 1) {
    return (
      <div className="flex h-[420px] items-center justify-center border border-slate-200 bg-white text-sm text-slate-500">
        K 線資料不足
      </div>
    );
  }

  const width = 1000;
  const height = 420;
  const paddingLeft = 58;
  const paddingRight = 28;
  const priceTop = 28;
  const priceHeight = 260;
  const volumeTop = 322;
  const volumeHeight = 62;
  const labelY = 406;
  const usableWidth = width - paddingLeft - paddingRight;

  const priceValues = data
    .flatMap((point) => [
      point.open,
      point.high,
      point.low,
      point.close,
      point.ma5,
      point.ma20,
      point.ma60,
    ])
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value);
    });

  const minPrice = priceValues.length > 0 ? Math.min(...priceValues) : 0;
  const maxPrice = priceValues.length > 0 ? Math.max(...priceValues) : 1;
  const pricePadding = (maxPrice - minPrice || 1) * 0.08;
  const yMin = minPrice - pricePadding;
  const yMax = maxPrice + pricePadding;
  const yRange = yMax - yMin || 1;

  const volumes = data
    .map((point) => point.volume)
    .filter((value): value is number => {
      return value !== null && value !== undefined && !Number.isNaN(value);
    });

  const maxVolume = Math.max(...volumes, 1);
  const candleWidth = clamp((usableWidth / data.length) * 0.58, 3, 12);

  function getX(index: number) {
    if (data.length <= 1) return paddingLeft;
    return paddingLeft + (index / (data.length - 1)) * usableWidth;
  }

  function getPriceY(value: number) {
    return priceTop + ((yMax - value) / yRange) * priceHeight;
  }

  function getVolumeY(value: number) {
    return volumeTop + volumeHeight - (value / maxVolume) * volumeHeight;
  }

  function handleMouseMove(event: React.MouseEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const localX = ((event.clientX - rect.left) / rect.width) * width;
    const ratio = (localX - paddingLeft) / usableWidth;
    const index = Math.round(ratio * (data.length - 1));
    setHoverIndex(clamp(index, 0, data.length - 1));
  }

  const ma5Path = buildLinePath(data, (point) => point.ma5, getX, getPriceY);
  const ma20Path = buildLinePath(data, (point) => point.ma20, getX, getPriceY);
  const ma60Path = buildLinePath(data, (point) => point.ma60, getX, getPriceY);
  const hoverX = hoverIndex !== null ? getX(hoverIndex) : null;

  return (
    <div className="border border-slate-200 bg-white">
      <div className="flex min-h-16 items-start justify-between gap-4 border-b border-slate-200 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">K 線 / 成交量</div>
          <div className="mt-1 text-xs text-slate-500">
            {label} · {data.length} 根 K 棒
          </div>
        </div>

        {hoveredPoint ? (
          <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-right text-xs">
            <div>
              <span className="text-slate-400">日期</span>
              <div className="font-semibold text-slate-800">{hoveredPoint.time}</div>
            </div>
            <div>
              <span className="text-slate-400">收盤</span>
              <div className="font-semibold text-slate-800">
                {formatPrice(hoveredPoint.close)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">漲跌</span>
              <div
                className={[
                  "font-semibold",
                  (hoveredPoint.changePct ?? 0) > 0
                    ? "text-red-600"
                    : (hoveredPoint.changePct ?? 0) < 0
                      ? "text-emerald-600"
                      : "text-slate-700",
                ].join(" ")}
              >
                {formatPct(hoveredPoint.changePct)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">開高低</span>
              <div className="font-semibold text-slate-800">
                {formatPrice(hoveredPoint.open)} / {formatPrice(hoveredPoint.high)} /{" "}
                {formatPrice(hoveredPoint.low)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">量</span>
              <div className="font-semibold text-slate-800">
                {formatNumber(hoveredPoint.volume)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">MA5/20</span>
              <div className="font-semibold text-slate-800">
                {formatPrice(hoveredPoint.ma5)} / {formatPrice(hoveredPoint.ma20)}
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="h-[420px] w-full">
        <rect x="0" y="0" width={width} height={height} className="fill-white" />

        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = priceTop + ratio * priceHeight;
          const price = yMax - ratio * yRange;

          return (
            <g key={ratio}>
              <line
                x1={paddingLeft}
                x2={width - paddingRight}
                y1={y}
                y2={y}
                className="stroke-slate-100"
              />
              <text
                x={paddingLeft - 10}
                y={y + 4}
                textAnchor="end"
                className="fill-slate-500 text-[11px]"
              >
                {formatPrice(price)}
              </text>
            </g>
          );
        })}

        {data.map((point, index) => {
          const open = point.open ?? point.close;
          const close = point.close ?? point.open;
          const high = point.high ?? Math.max(open ?? 0, close ?? 0);
          const low = point.low ?? Math.min(open ?? 0, close ?? 0);

          if (
            open === null ||
            open === undefined ||
            close === null ||
            close === undefined ||
            high === null ||
            high === undefined ||
            low === null ||
            low === undefined
          ) {
            return null;
          }

          const x = getX(index);
          const isUp = close >= open;
          const highY = getPriceY(high);
          const lowY = getPriceY(low);
          const openY = getPriceY(open);
          const closeY = getPriceY(close);
          const bodyY = Math.min(openY, closeY);
          const bodyHeight = Math.max(Math.abs(openY - closeY), 1.5);
          const volume = point.volume ?? 0;
          const volumeY = getVolumeY(volume);
          const volumeBarHeight = volumeTop + volumeHeight - volumeY;
          const candleClass = isUp
            ? "fill-red-600 stroke-red-600"
            : "fill-emerald-600 stroke-emerald-600";
          const volumeClass = isUp ? "fill-red-200" : "fill-emerald-200";

          return (
            <g key={`${point.time}-${index}`}>
              <line
                x1={x}
                x2={x}
                y1={highY}
                y2={lowY}
                className={candleClass}
                strokeWidth="1.5"
              />
              <rect
                x={x - candleWidth / 2}
                y={bodyY}
                width={candleWidth}
                height={bodyHeight}
                className={candleClass}
              />
              <rect
                x={x - candleWidth / 2}
                y={volumeY}
                width={candleWidth}
                height={Math.max(volumeBarHeight, 1)}
                className={volumeClass}
              />
            </g>
          );
        })}

        {ma5Path ? (
          <path
            d={ma5Path}
            fill="none"
            strokeWidth="2"
            className="stroke-blue-600"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {ma20Path ? (
          <path
            d={ma20Path}
            fill="none"
            strokeWidth="2"
            className="stroke-amber-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {ma60Path ? (
          <path
            d={ma60Path}
            fill="none"
            strokeWidth="1.6"
            className="stroke-purple-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}

        <line
          x1={paddingLeft}
          x2={width - paddingRight}
          y1={volumeTop}
          y2={volumeTop}
          className="stroke-slate-100"
        />
        <text
          x={paddingLeft - 10}
          y={volumeTop + 4}
          textAnchor="end"
          className="fill-slate-500 text-[11px]"
        >
          量
        </text>

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

        <text x={paddingLeft} y={labelY} textAnchor="start" className="fill-slate-500 text-[11px]">
          {data[0]?.time ?? "-"}
        </text>
        <text
          x={width - paddingRight}
          y={labelY}
          textAnchor="end"
          className="fill-slate-500 text-[11px]"
        >
          {data[data.length - 1]?.time ?? "-"}
        </text>

        <g transform={`translate(${paddingLeft}, 18)`}>
          <circle cx="0" cy="0" r="4" className="fill-blue-600" />
          <text x="10" y="4" className="fill-slate-600 text-[11px]">
            MA5
          </text>
          <circle cx="58" cy="0" r="4" className="fill-amber-500" />
          <text x="68" y="4" className="fill-slate-600 text-[11px]">
            MA20
          </text>
          <circle cx="126" cy="0" r="4" className="fill-purple-500" />
          <text x="136" y="4" className="fill-slate-600 text-[11px]">
            MA60
          </text>
        </g>

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
    </div>
  );
}

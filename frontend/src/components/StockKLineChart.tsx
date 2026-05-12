"use client";

import { useMemo, useState } from "react";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";

type Props = {
  chartData: ChartPoint[];
  indicatorData: StockIndicatorPoint[];
};

type MergedPoint = ChartPoint & {
  ma5: number | null;
  ma20: number | null;
  volumeMa5: number | null;
  volumeMa20: number | null;
  changePct: number | null;
};

function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return new Intl.NumberFormat("zh-TW").format(value);
}

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
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

    if (value === null || value === undefined) {
      started = false;
      return;
    }

    const x = getX(index);
    const y = getY(value);

    if (!started) {
      path += `M ${x.toFixed(2)} ${y.toFixed(2)} `;
      started = true;
    } else {
      path += `L ${x.toFixed(2)} ${y.toFixed(2)} `;
    }
  });

  return path.trim();
}

export default function StockKLineChart({ chartData, indicatorData }: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const data = useMemo<MergedPoint[]>(() => {
    const indicatorByTime = new Map<string, StockIndicatorPoint>();

    indicatorData.forEach((point) => {
      indicatorByTime.set(point.time, point);
    });

    return chartData.map((point) => {
      const indicator = indicatorByTime.get(point.time);

      return {
        ...point,
        ma5: indicator?.ma?.["ma5"] ?? null,
        ma20: indicator?.ma?.["ma20"] ?? null,
        volumeMa5: indicator?.volume_ma?.["volume_ma5"] ?? null,
        volumeMa20: indicator?.volume_ma?.["volume_ma20"] ?? null,
        changePct: indicator?.change_pct ?? null,
      };
    });
  }, [chartData, indicatorData]);

  const visibleData = useMemo(() => data.slice(-80), [data]);

  const hoveredPoint =
    hoverIndex !== null ? visibleData[hoverIndex] : visibleData[visibleData.length - 1];

  if (visibleData.length < 2) {
    return (
      <div className="flex h-72 items-center justify-center rounded-2xl bg-slate-50 text-sm text-slate-400">
        Not enough chart data.
      </div>
    );
  }

  const width = 980;
  const height = 360;

  const paddingLeft = 54;
  const paddingRight = 24;
  const priceTop = 20;
  const priceHeight = 210;
  const volumeTop = 260;
  const volumeHeight = 70;
  const bottomLabelY = 350;

  const priceValues = visibleData
    .flatMap((point) => [
      point.high,
      point.low,
      point.open,
      point.close,
      point.ma5,
      point.ma20,
    ])
    .filter((value): value is number => value !== null && value !== undefined);

  const minPrice = Math.min(...priceValues);
  const maxPrice = Math.max(...priceValues);
  const pricePadding = (maxPrice - minPrice || 1) * 0.08;
  const yMin = minPrice - pricePadding;
  const yMax = maxPrice + pricePadding;
  const yRange = yMax - yMin || 1;

  const volumes = visibleData
    .map((point) => point.volume)
    .filter((value): value is number => value !== null && value !== undefined);

  const maxVolume = Math.max(...volumes, 1);

  const usableWidth = width - paddingLeft - paddingRight;

  function getX(index: number) {
    if (visibleData.length <= 1) return paddingLeft;
    return paddingLeft + (index / (visibleData.length - 1)) * usableWidth;
  }

  function getPriceY(value: number) {
    return priceTop + ((yMax - value) / yRange) * priceHeight;
  }

  function getVolumeY(value: number) {
    return volumeTop + volumeHeight - (value / maxVolume) * volumeHeight;
  }

  const candleWidth = clamp((usableWidth / visibleData.length) * 0.55, 3, 10);

  const ma5Path = buildLinePath(
    visibleData,
    (point) => point.ma5,
    getX,
    getPriceY
  );

  const ma20Path = buildLinePath(
    visibleData,
    (point) => point.ma20,
    getX,
    getPriceY
  );

  function handleMouseMove(event: React.MouseEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const localX = ((event.clientX - rect.left) / rect.width) * width;
    const ratio = (localX - paddingLeft) / usableWidth;
    const index = Math.round(ratio * (visibleData.length - 1));
    setHoverIndex(clamp(index, 0, visibleData.length - 1));
  }

  const hoverX = hoverIndex !== null ? getX(hoverIndex) : null;

  return (
    <div className="rounded-2xl bg-slate-50 p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-700">K Line / Volume</p>
          <p className="mt-1 text-xs text-slate-400">
            顯示最近 {visibleData.length} 筆日 K，含 MA5 / MA20。
          </p>
        </div>

        {hoveredPoint ? (
          <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-right text-xs">
            <div>
              <span className="text-slate-400">Date</span>
              <div className="font-semibold text-slate-700">{hoveredPoint.time}</div>
            </div>
            <div>
              <span className="text-slate-400">Close</span>
              <div className="font-semibold text-slate-700">
                {formatPrice(hoveredPoint.close)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">Change</span>
              <div
                className={[
                  "font-semibold",
                  (hoveredPoint.changePct ?? 0) > 0
                    ? "text-rose-600"
                    : (hoveredPoint.changePct ?? 0) < 0
                      ? "text-emerald-600"
                      : "text-slate-600",
                ].join(" ")}
              >
                {formatPct(hoveredPoint.changePct)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">O/H/L</span>
              <div className="font-semibold text-slate-700">
                {formatPrice(hoveredPoint.open)} / {formatPrice(hoveredPoint.high)} /{" "}
                {formatPrice(hoveredPoint.low)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">Volume</span>
              <div className="font-semibold text-slate-700">
                {formatNumber(hoveredPoint.volume)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">MA</span>
              <div className="font-semibold text-slate-700">
                {formatPrice(hoveredPoint.ma5)} / {formatPrice(hoveredPoint.ma20)}
              </div>
            </div>
          </div>
        ) : null}
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="h-[360px] w-full">
        <rect x="0" y="0" width={width} height={height} rx="18" className="fill-white" />

        {/* Price grid */}
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
                className="fill-slate-400 text-[11px]"
              >
                {formatPrice(price)}
              </text>
            </g>
          );
        })}

        {/* Candles and volume */}
        {visibleData.map((point, index) => {
          const x = getX(index);

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
            ? "fill-rose-500 stroke-rose-500"
            : "fill-emerald-500 stroke-emerald-500";

          const volumeClass = isUp ? "fill-rose-200" : "fill-emerald-200";

          return (
            <g key={point.time}>
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
                rx="1"
                className={candleClass}
              />

              <rect
                x={x - candleWidth / 2}
                y={volumeY}
                width={candleWidth}
                height={Math.max(volumeBarHeight, 1)}
                rx="1"
                className={volumeClass}
              />
            </g>
          );
        })}

        {/* MA lines */}
        {ma5Path ? (
          <path
            d={ma5Path}
            fill="none"
            strokeWidth="2.2"
            className="stroke-indigo-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}

        {ma20Path ? (
          <path
            d={ma20Path}
            fill="none"
            strokeWidth="2.2"
            className="stroke-amber-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}

        {/* Volume grid */}
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
          className="fill-slate-400 text-[11px]"
        >
          Vol
        </text>

        {/* Hover line */}
        {hoverX !== null ? (
          <line
            x1={hoverX}
            x2={hoverX}
            y1={priceTop}
            y2={volumeTop + volumeHeight}
            className="stroke-slate-300"
            strokeDasharray="4 4"
          />
        ) : null}

        {/* x-axis labels */}
        <text
          x={paddingLeft}
          y={bottomLabelY}
          textAnchor="start"
          className="fill-slate-400 text-[11px]"
        >
          {visibleData[0]?.time ?? "-"}
        </text>

        <text
          x={width - paddingRight}
          y={bottomLabelY}
          textAnchor="end"
          className="fill-slate-400 text-[11px]"
        >
          {visibleData[visibleData.length - 1]?.time ?? "-"}
        </text>

        {/* Legend */}
        <g transform={`translate(${paddingLeft}, ${priceTop - 6})`}>
          <circle cx="0" cy="0" r="4" className="fill-indigo-500" />
          <text x="10" y="4" className="fill-slate-500 text-[11px]">
            MA5
          </text>
          <circle cx="58" cy="0" r="4" className="fill-amber-500" />
          <text x="68" y="4" className="fill-slate-500 text-[11px]">
            MA20
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
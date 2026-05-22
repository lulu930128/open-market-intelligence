"use client";

import { useMemo, useState } from "react";
import type { IntradayTrendPoint } from "@/types/market";

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

function formatTime(value: string) {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("zh-TW", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Taipei",
  }).format(date);
}

function formatSource(value: string) {
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
  getX: (index: number) => number,
  getY: (value: number) => number
) {
  return data
    .map((point, index) => {
      const x = getX(index).toFixed(2);
      const y = getY(point.price).toFixed(2);
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
}

export default function IntradayTrendChart({
  points,
  previousClose,
  label,
  source,
  refreshIntervalMs,
  updatedAt,
}: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const data = useMemo(() => {
    return points.filter((point) => {
      return point.price !== null && point.price !== undefined && !Number.isNaN(point.price);
    });
  }, [points]);

  const hoveredPoint =
    hoverIndex !== null ? data[hoverIndex] : data[data.length - 1] ?? null;

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
  const paddingRight = 28;
  const priceTop = 30;
  const priceHeight = 260;
  const volumeTop = 322;
  const volumeHeight = 62;
  const labelY = 406;
  const usableWidth = width - paddingLeft - paddingRight;
  const latestPrice = data[data.length - 1]?.price ?? null;
  const change =
    latestPrice !== null && previousClose !== null ? latestPrice - previousClose : null;
  const trendClass =
    change === null || change === 0
      ? "stroke-slate-700"
      : change > 0
        ? "stroke-red-600"
        : "stroke-emerald-600";
  const areaClass =
    change === null || change === 0
      ? "fill-slate-50"
      : change > 0
        ? "fill-red-50"
        : "fill-emerald-50";

  const priceValues = [
    ...data.map((point) => point.price),
    ...(previousClose !== null ? [previousClose] : []),
  ];
  const minPrice = Math.min(...priceValues);
  const maxPrice = Math.max(...priceValues);
  const pricePadding = (maxPrice - minPrice || 1) * 0.08;
  const yMin = minPrice - pricePadding;
  const yMax = maxPrice + pricePadding;
  const yRange = yMax - yMin || 1;
  const volumes = data
    .map((point) => point.volume)
    .filter(validNumber);
  const maxVolume = Math.max(...volumes, 1);
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

  const linePath = buildLinePath(data, getX, getPriceY);
  const areaPath = `${linePath} L ${getX(data.length - 1).toFixed(2)} ${volumeTop.toFixed(
    2
  )} L ${paddingLeft.toFixed(2)} ${volumeTop.toFixed(2)} Z`;
  const hoverX = hoverIndex !== null ? getX(hoverIndex) : null;
  const previousCloseY = previousClose !== null ? getPriceY(previousClose) : null;

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

        {hoveredPoint ? (
          <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-right text-xs">
            <div>
              <span className="text-slate-400">時間</span>
              <div className="font-semibold text-slate-800">{formatTime(hoveredPoint.time)}</div>
            </div>
            <div>
              <span className="text-slate-400">價格</span>
              <div className="font-semibold text-slate-800">
                {formatPrice(hoveredPoint.price)}
              </div>
            </div>
            <div>
              <span className="text-slate-400">量</span>
              <div className="font-semibold text-slate-800">
                {formatNumber(hoveredPoint.volume)}
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

        {previousCloseY !== null ? (
          <g>
            <line
              x1={paddingLeft}
              x2={width - paddingRight}
              y1={previousCloseY}
              y2={previousCloseY}
              className="stroke-slate-300"
              strokeDasharray="5 5"
            />
            <text
              x={width - paddingRight}
              y={previousCloseY - 6}
              textAnchor="end"
              className="fill-slate-400 text-[11px]"
            >
              昨收 {formatPrice(previousClose)}
            </text>
          </g>
        ) : null}

        <path d={areaPath} className={`${areaClass} opacity-80`} />
        <path
          d={linePath}
          fill="none"
          strokeWidth="2.4"
          className={trendClass}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {rangeHigh ? (
          <g>
            {(() => {
              const x = getX(rangeHigh.index);
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

        {rangeLow ? (
          <g>
            {(() => {
              const x = getX(rangeLow.index);
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
          const barWidth = clamp((usableWidth / data.length) * 0.55, 1, 5);

          return (
            <rect
              key={`${point.time}-${index}`}
              x={getX(index) - barWidth / 2}
              y={volumeY}
              width={barWidth}
              height={Math.max(volumeBarHeight, 1)}
              className="fill-slate-200"
            />
          );
        })}

        <line
          x1={paddingLeft}
          x2={width - paddingRight}
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

        <text x={paddingLeft} y={labelY} textAnchor="start" className="fill-slate-500 text-[11px]">
          {formatTime(data[0]?.time ?? "")}
        </text>
        <text
          x={width - paddingRight}
          y={labelY}
          textAnchor="end"
          className="fill-slate-500 text-[11px]"
        >
          {formatTime(data[data.length - 1]?.time ?? "")}
        </text>

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

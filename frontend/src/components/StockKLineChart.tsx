"use client";

import { type MouseEvent, useMemo, useState } from "react";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";

type Props = {
  chartData: ChartPoint[];
  indicatorData?: StockIndicatorPoint[];
  label: string;
  indicators: IndicatorSettings;
};

export type IndicatorSettings = {
  ma: boolean;
  bollinger: boolean;
  volume: boolean;
  rsi: boolean;
  macd: boolean;
  kd: boolean;
};

export type IndicatorKey = keyof IndicatorSettings;

type MergedPoint = ChartPoint & {
  ma5: number | null;
  ma20: number | null;
  ma60: number | null;
  volumeMa20: number | null;
  changePct: number | null;
  bbMiddle: number | null;
  bbUpper: number | null;
  bbLower: number | null;
  rsi14: number | null;
  macd: number | null;
  macdSignal: number | null;
  macdHistogram: number | null;
  k: number | null;
  d: number | null;
};

type Panel = {
  key: "volume" | "rsi" | "macd" | "kd";
  label: string;
  top: number;
  height: number;
};

export const indicatorOptions: Array<{ key: IndicatorKey; label: string; description: string }> = [
  { key: "ma", label: "MA", description: "MA5 / MA20 / MA60" },
  { key: "bollinger", label: "BOLL", description: "20MA +/- 2SD" },
  { key: "volume", label: "VOL", description: "成交量" },
  { key: "rsi", label: "RSI", description: "RSI 14" },
  { key: "macd", label: "MACD", description: "12 / 26 / 9" },
  { key: "kd", label: "KD", description: "KD 9 / 3" },
];

export const defaultIndicators: IndicatorSettings = {
  ma: true,
  bollinger: false,
  volume: true,
  rsi: false,
  macd: false,
  kd: false,
};

function formatPrice(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatLots(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("zh-TW").format(Math.round(value / 1000));
}

function formatTradeValue(value: number | null | undefined) {
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

function formatIndicator(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
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

function movingAverage(
  values: Array<number | null | undefined>,
  index: number,
  windowSize: number
): number | null {
  if (index + 1 < windowSize) return null;

  const slice = values.slice(index + 1 - windowSize, index + 1);

  if (slice.some((value) => !validNumber(value))) return null;

  return average(slice);
}

function standardDeviation(
  values: Array<number | null | undefined>,
  index: number,
  windowSize: number
): number | null {
  const mean = movingAverage(values, index, windowSize);

  if (mean === null) return null;

  const meanValue: number = mean;
  const slice = values.slice(index + 1 - windowSize, index + 1).filter(validNumber);

  if (slice.length < windowSize) return null;

  const variance =
    slice.reduce((sum, value) => sum + (value - meanValue) ** 2, 0) / windowSize;

  return Math.sqrt(variance);
}

function calculateChangePct(current: number | null | undefined, previous: number | null | undefined) {
  if (!validNumber(current) || !validNumber(previous) || previous === 0) return null;
  return ((current - previous) / previous) * 100;
}

function calculateRsi(closes: Array<number | null | undefined>, period = 14) {
  return closes.map((close, index) => {
    if (!validNumber(close) || index < period) return null;

    let gain = 0;
    let loss = 0;

    for (let cursor = index - period + 1; cursor <= index; cursor += 1) {
      const current = closes[cursor];
      const previous = closes[cursor - 1];

      if (!validNumber(current) || !validNumber(previous)) return null;

      const change = current - previous;
      if (change >= 0) gain += change;
      else loss += Math.abs(change);
    }

    const averageGain = gain / period;
    const averageLoss = loss / period;

    if (averageLoss === 0) return 100;
    if (averageGain === 0) return 0;

    const rs = averageGain / averageLoss;
    return 100 - 100 / (1 + rs);
  });
}

function calculateEma(values: Array<number | null | undefined>, period: number) {
  const multiplier = 2 / (period + 1);
  let previousEma: number | null = null;

  return values.map((value) => {
    if (!validNumber(value)) return null;

    if (previousEma === null) {
      previousEma = value;
      return value;
    }

    previousEma = value * multiplier + previousEma * (1 - multiplier);
    return previousEma;
  });
}

function calculateMacd(closes: Array<number | null | undefined>) {
  const ema12 = calculateEma(closes, 12);
  const ema26 = calculateEma(closes, 26);
  const macd = closes.map((_, index) => {
    if (!validNumber(ema12[index]) || !validNumber(ema26[index])) return null;
    return ema12[index] - ema26[index];
  });
  const signal = calculateEma(macd, 9);
  const histogram = macd.map((value, index) => {
    if (!validNumber(value) || !validNumber(signal[index])) return null;
    return value - signal[index];
  });

  return { macd, signal, histogram };
}

function calculateKd(points: ChartPoint[], period = 9) {
  let previousK = 50;
  let previousD = 50;

  return points.map((point, index) => {
    if (index + 1 < period || !validNumber(point.close)) {
      return { k: null, d: null };
    }

    const slice = points.slice(index + 1 - period, index + 1);
    const highs = slice.map((item) => item.high).filter(validNumber);
    const lows = slice.map((item) => item.low).filter(validNumber);

    if (highs.length < period || lows.length < period) {
      return { k: null, d: null };
    }

    const highest = Math.max(...highs);
    const lowest = Math.min(...lows);
    const rsv = highest === lowest ? 50 : ((point.close - lowest) / (highest - lowest)) * 100;
    const k = previousK * (2 / 3) + rsv * (1 / 3);
    const d = previousD * (2 / 3) + k * (1 / 3);

    previousK = k;
    previousD = d;

    return { k, d };
  });
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

    if (value === null || Number.isNaN(value)) {
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

function buildBandAreaPath(
  data: MergedPoint[],
  getUpper: (point: MergedPoint) => number | null,
  getLower: (point: MergedPoint) => number | null,
  getX: (index: number) => number,
  getY: (value: number) => number
) {
  const points = data
    .map((point, index) => ({
      index,
      upper: getUpper(point),
      lower: getLower(point),
    }))
    .filter((point): point is { index: number; upper: number; lower: number } => {
      return validNumber(point.upper) && validNumber(point.lower);
    });

  if (points.length < 2) return "";

  const upperPath = points
    .map((point, pathIndex) => {
      const prefix = pathIndex === 0 ? "M" : "L";
      return `${prefix} ${getX(point.index).toFixed(2)} ${getY(point.upper).toFixed(2)}`;
    })
    .join(" ");
  const lowerPath = points
    .slice()
    .reverse()
    .map((point) => {
      return `L ${getX(point.index).toFixed(2)} ${getY(point.lower).toFixed(2)}`;
    })
    .join(" ");

  return `${upperPath} ${lowerPath} Z`;
}

function valueTone(value: number | null | undefined) {
  if (!validNumber(value)) return "text-slate-700";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-emerald-600";
  return "text-slate-700";
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

export default function StockKLineChart({
  chartData,
  indicatorData = [],
  label,
  indicators,
}: Props) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const data = useMemo<MergedPoint[]>(() => {
    const indicatorByTime = new Map<string, StockIndicatorPoint>();

    indicatorData.forEach((point) => {
      indicatorByTime.set(point.time, point);
    });

    const closes = chartData.map((point) => point.close);
    const volumes = chartData.map((point) => point.volume);
    const rsi = calculateRsi(closes);
    const macd = calculateMacd(closes);
    const kd = calculateKd(chartData);

    return chartData.map((point, index) => {
      const indicator = indicatorByTime.get(point.time);
      const previousClose = chartData[index - 1]?.close;
      const ma20 = indicator?.ma?.ma20 ?? movingAverage(closes, index, 20);
      const standardDev20 = standardDeviation(closes, index, 20);

      return {
        ...point,
        ma5: indicator?.ma?.ma5 ?? movingAverage(closes, index, 5),
        ma20,
        ma60: indicator?.ma?.ma60 ?? movingAverage(closes, index, 60),
        volumeMa20: indicator?.volume_ma?.volume_ma20 ?? movingAverage(volumes, index, 20),
        changePct: indicator?.change_pct ?? calculateChangePct(point.close, previousClose),
        bbMiddle: ma20,
        bbUpper: ma20 !== null && standardDev20 !== null ? ma20 + standardDev20 * 2 : null,
        bbLower: ma20 !== null && standardDev20 !== null ? ma20 - standardDev20 * 2 : null,
        rsi14: rsi[index],
        macd: macd.macd[index],
        macdSignal: macd.signal[index],
        macdHistogram: macd.histogram[index],
        k: kd[index].k,
        d: kd[index].d,
      };
    });
  }, [chartData, indicatorData]);

  const safeHoverIndex =
    hoverIndex !== null && hoverIndex >= 0 && hoverIndex < data.length ? hoverIndex : null;
  const hoveredPoint =
    safeHoverIndex !== null ? data[safeHoverIndex] : data[data.length - 1] ?? null;

  if (data.length < 1) {
    return (
      <div className="flex h-[420px] items-center justify-center border border-slate-200 bg-white text-sm text-slate-500">
        K 線資料不足
      </div>
    );
  }

  const width = 1000;
  const paddingLeft = 58;
  const paddingRight = 28;
  const chartTop = 28;
  const priceHeight = 260;
  const panelGap = 24;
  const panelHeight = 72;
  const bottomPadding = 30;
  const usableWidth = width - paddingLeft - paddingRight;

  const panels: Panel[] = [];
  let nextPanelTop = chartTop + priceHeight + panelGap;

  function addPanel(enabled: boolean, key: Panel["key"], panelLabel: string) {
    if (!enabled) return;

    panels.push({
      key,
      label: panelLabel,
      top: nextPanelTop,
      height: panelHeight,
    });
    nextPanelTop += panelHeight + panelGap;
  }

  addPanel(indicators.volume, "volume", "成交量(張)");
  addPanel(indicators.rsi, "rsi", "RSI 14");
  addPanel(indicators.macd, "macd", "MACD");
  addPanel(indicators.kd, "kd", "KD");

  const height = Math.max(360, nextPanelTop - panelGap + bottomPadding);
  const labelY = height - 10;
  const priceBottom = chartTop + priceHeight;
  const plotBottom = panels.length > 0 ? panels[panels.length - 1].top + panelHeight : priceBottom;

  const priceValues = data
    .flatMap((point) => [
      point.open,
      point.high,
      point.low,
      point.close,
      indicators.ma ? point.ma5 : null,
      indicators.ma ? point.ma20 : null,
      indicators.ma ? point.ma60 : null,
      indicators.bollinger ? point.bbUpper : null,
      indicators.bollinger ? point.bbLower : null,
    ])
    .filter(validNumber);

  const minPrice = priceValues.length > 0 ? Math.min(...priceValues) : 0;
  const maxPrice = priceValues.length > 0 ? Math.max(...priceValues) : 1;
  const pricePadding = (maxPrice - minPrice || 1) * 0.08;
  const yMin = minPrice - pricePadding;
  const yMax = maxPrice + pricePadding;
  const yRange = yMax - yMin || 1;
  const volumes = data.map((point) => point.volume).filter(validNumber);
  const maxVolume = Math.max(...volumes, 1);
  const macdValues = data
    .flatMap((point) => [point.macd, point.macdSignal, point.macdHistogram])
    .filter(validNumber);
  const macdAbsMax = Math.max(...macdValues.map((value) => Math.abs(value)), 1);
  const candleWidth = clamp((usableWidth / data.length) * 0.58, 3, 12);
  const rangeHigh = data.reduce<{ index: number; value: number } | null>(
    (best, point, index) => {
      const value = point.high ?? point.close;

      if (!validNumber(value)) return best;
      if (best === null || value > best.value) return { index, value };

      return best;
    },
    null
  );
  const rangeLow = data.reduce<{ index: number; value: number } | null>(
    (best, point, index) => {
      const value = point.low ?? point.close;

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
    return chartTop + ((yMax - value) / yRange) * priceHeight;
  }

  function getPanelY(panel: Panel, value: number, min: number, max: number) {
    const range = max - min || 1;
    return panel.top + ((max - value) / range) * panel.height;
  }

  function getVolumeY(panel: Panel, value: number) {
    return panel.top + panel.height - (value / maxVolume) * panel.height;
  }

  function handleMouseMove(event: MouseEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const localX = paddingLeft + ratio * usableWidth;
    const dataRatio = (localX - paddingLeft) / usableWidth;
    const index = Math.round(dataRatio * (data.length - 1));
    setHoverIndex(clamp(index, 0, data.length - 1));
  }

  const ma5Path = buildLinePath(data, (point) => point.ma5, getX, getPriceY);
  const ma20Path = buildLinePath(data, (point) => point.ma20, getX, getPriceY);
  const ma60Path = buildLinePath(data, (point) => point.ma60, getX, getPriceY);
  const bbUpperPath = buildLinePath(data, (point) => point.bbUpper, getX, getPriceY);
  const bbMiddlePath = buildLinePath(data, (point) => point.bbMiddle, getX, getPriceY);
  const bbLowerPath = buildLinePath(data, (point) => point.bbLower, getX, getPriceY);
  const bbAreaPath = buildBandAreaPath(data, (point) => point.bbUpper, (point) => point.bbLower, getX, getPriceY);
  const hoverX = safeHoverIndex !== null ? getX(safeHoverIndex) : null;

  return (
    <div className="border border-slate-200 bg-white">
      <div className="flex min-h-16 items-start justify-between gap-4 border-b border-slate-200 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">K 線 / 技術指標</div>
          <div className="mt-1 text-xs text-slate-500">
            {label} · {data.length} 根 K 線
          </div>
        </div>

        <div className="flex items-start gap-4">
          {hoveredPoint ? (
            <div className="grid grid-cols-5 gap-x-4 gap-y-1 text-right text-xs">
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
                <div className={`font-semibold ${valueTone(hoveredPoint.changePct)}`}>
                  {formatPct(hoveredPoint.changePct)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">成交量(張)</span>
                <div className="font-semibold text-slate-800">
                  {formatLots(hoveredPoint.volume)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">成交金額</span>
                <div className="font-semibold text-slate-800">
                  {formatTradeValue(hoveredPoint.trade_value)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">MA5/20/60</span>
                <div className="font-semibold text-slate-800">
                  {formatPrice(hoveredPoint.ma5)} / {formatPrice(hoveredPoint.ma20)} /{" "}
                  {formatPrice(hoveredPoint.ma60)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">RSI</span>
                <div className="font-semibold text-slate-800">
                  {formatIndicator(hoveredPoint.rsi14)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">MACD</span>
                <div className={`font-semibold ${valueTone(hoveredPoint.macdHistogram)}`}>
                  {formatIndicator(hoveredPoint.macdHistogram)}
                </div>
              </div>
              <div>
                <span className="text-slate-400">K/D</span>
                <div className="font-semibold text-slate-800">
                  {formatIndicator(hoveredPoint.k)} / {formatIndicator(hoveredPoint.d)}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }}>
        <rect x="0" y="0" width={width} height={height} className="fill-white" />

        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = chartTop + ratio * priceHeight;
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

        {indicators.bollinger && bbAreaPath ? (
          <path d={bbAreaPath} className="fill-sky-100/70" />
        ) : null}

        {data.map((point, index) => {
          const open = point.open ?? point.close;
          const close = point.close ?? point.open;
          const high = point.high ?? Math.max(open ?? 0, close ?? 0);
          const low = point.low ?? Math.min(open ?? 0, close ?? 0);

          if (!validNumber(open) || !validNumber(close) || !validNumber(high) || !validNumber(low)) {
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
          const candleClass = isUp
            ? "fill-red-600 stroke-red-600"
            : "fill-emerald-600 stroke-emerald-600";

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
            </g>
          );
        })}

        {indicators.bollinger ? (
          <>
            {bbUpperPath ? (
              <path d={bbUpperPath} fill="none" strokeWidth="1.4" className="stroke-sky-500" />
            ) : null}
            {bbMiddlePath ? (
              <path d={bbMiddlePath} fill="none" strokeWidth="1.2" className="stroke-sky-400" strokeDasharray="4 4" />
            ) : null}
            {bbLowerPath ? (
              <path d={bbLowerPath} fill="none" strokeWidth="1.4" className="stroke-sky-500" />
            ) : null}
          </>
        ) : null}

        {indicators.ma && ma5Path ? (
          <path
            d={ma5Path}
            fill="none"
            strokeWidth="2"
            className="stroke-blue-600"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ma && ma20Path ? (
          <path
            d={ma20Path}
            fill="none"
            strokeWidth="2"
            className="stroke-amber-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ma && ma60Path ? (
          <path
            d={ma60Path}
            fill="none"
            strokeWidth="1.6"
            className="stroke-purple-500"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}

        {rangeHigh ? (
          <g>
            {(() => {
              const x = getX(rangeHigh.index);
              const y = getPriceY(rangeHigh.value);
              const label = labelPosition(x, paddingLeft, paddingRight, width);
              const labelY = clamp(y - 12, chartTop + 12, priceBottom - 8);

              return (
                <>
                  <circle cx={x} cy={y} r="3.5" className="fill-red-600" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={labelY}
                    className="stroke-red-400"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={labelY - 3}
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
              const labelY = clamp(y + 18, chartTop + 12, priceBottom - 8);

              return (
                <>
                  <circle cx={x} cy={y} r="3.5" className="fill-emerald-600" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={labelY}
                    className="stroke-emerald-400"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={labelY + 10}
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

        {panels.map((panel) => {
          const panelBottom = panel.top + panel.height;

          return (
            <g key={panel.key}>
              <line
                x1={paddingLeft}
                x2={width - paddingRight}
                y1={panel.top}
                y2={panel.top}
                className="stroke-slate-200"
              />
              <text
                x={paddingLeft - 10}
                y={panel.top + 12}
                textAnchor="end"
                className="fill-slate-500 text-[11px]"
              >
                {panel.label}
              </text>

              {panel.key === "volume" ? (
                <>
                  {data.map((point, index) => {
                    const open = point.open ?? point.close;
                    const close = point.close ?? point.open;
                    const volume = point.volume ?? 0;
                    const x = getX(index);
                    const isUp = validNumber(close) && validNumber(open) ? close >= open : true;
                    const y = getVolumeY(panel, volume);
                    const barHeight = panelBottom - y;

                    return (
                      <rect
                        key={`${point.time}-volume`}
                        x={x - candleWidth / 2}
                        y={y}
                        width={candleWidth}
                        height={Math.max(barHeight, 1)}
                        className={isUp ? "fill-red-200" : "fill-emerald-200"}
                      />
                    );
                  })}
                  <text
                    x={paddingLeft - 10}
                    y={panelBottom}
                    textAnchor="end"
                    className="fill-slate-400 text-[10px]"
                  >
                    0
                  </text>
                </>
              ) : null}

              {panel.key === "rsi" ? (
                <>
                  {[30, 50, 70].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 50 ? "stroke-slate-100" : "stroke-slate-200"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(data, (point) => point.rsi14, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-fuchsia-600"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "macd" ? (
                <>
                  <line
                    x1={paddingLeft}
                    x2={width - paddingRight}
                    y1={getPanelY(panel, 0, -macdAbsMax, macdAbsMax)}
                    y2={getPanelY(panel, 0, -macdAbsMax, macdAbsMax)}
                    className="stroke-slate-200"
                  />
                  {data.map((point, index) => {
                    if (!validNumber(point.macdHistogram)) return null;

                    const x = getX(index);
                    const zeroY = getPanelY(panel, 0, -macdAbsMax, macdAbsMax);
                    const valueY = getPanelY(panel, point.macdHistogram, -macdAbsMax, macdAbsMax);

                    return (
                      <rect
                        key={`${point.time}-macd-histogram`}
                        x={x - candleWidth / 2}
                        y={Math.min(zeroY, valueY)}
                        width={candleWidth}
                        height={Math.max(Math.abs(zeroY - valueY), 1)}
                        className={point.macdHistogram >= 0 ? "fill-red-200" : "fill-emerald-200"}
                      />
                    );
                  })}
                  <path
                    d={buildLinePath(data, (point) => point.macd, getX, (value) =>
                      getPanelY(panel, value, -macdAbsMax, macdAbsMax)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-blue-600"
                  />
                  <path
                    d={buildLinePath(data, (point) => point.macdSignal, getX, (value) =>
                      getPanelY(panel, value, -macdAbsMax, macdAbsMax)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-amber-500"
                  />
                </>
              ) : null}

              {panel.key === "kd" ? (
                <>
                  {[20, 50, 80].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 50 ? "stroke-slate-100" : "stroke-slate-200"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(data, (point) => point.k, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-blue-600"
                  />
                  <path
                    d={buildLinePath(data, (point) => point.d, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-amber-500"
                  />
                </>
              ) : null}
            </g>
          );
        })}

        {hoverX !== null ? (
          <line
            x1={hoverX}
            x2={hoverX}
            y1={chartTop}
            y2={plotBottom}
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
          {indicators.ma ? (
            <>
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
            </>
          ) : null}
          {indicators.bollinger ? (
            <>
              <rect x={190} y={-4} width={8} height={8} className="fill-sky-400" />
              <text x="204" y="4" className="fill-slate-600 text-[11px]">
                BOLL
              </text>
            </>
          ) : null}
        </g>

        <rect
          x={paddingLeft}
          y={chartTop}
          width={usableWidth}
          height={plotBottom - chartTop}
          fill="transparent"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIndex(null)}
        />
      </svg>
    </div>
  );
}

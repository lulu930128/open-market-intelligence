"use client";

import {
  type PointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { StateSurface } from "@/components/LoadingPlaceholders";
import {
  defaultIndicatorParameters,
  type IndicatorParameters,
  type IndicatorSettings,
} from "@/components/stock-k-line/indicatorCatalog";
import {
  buildChartSignals,
  clamp,
  projectStockKLineData,
  validNumber,
  type MergedPoint,
} from "@/components/stock-k-line/indicatorProjection";
import { useT } from "@/i18n";
import type { ChartPoint, StockIndicatorPoint } from "@/types/market";

export * from "@/components/stock-k-line/indicatorCatalog";

type Props = {
  chartData: ChartPoint[];
  indicatorData?: StockIndicatorPoint[];
  label: string;
  indicators: IndicatorSettings;
  indicatorParameters?: IndicatorParameters;
  benchmarkData?: ChartPoint[];
  benchmarkLabel?: string;
  revealKey?: string;
  volumePanelLabel?: string;
  volumeTooltipLabel?: string;
  volumeValueKey?: "volume" | "trade_value";
  volumeValueFormatter?: (value: number | null | undefined) => string;
  priceMaximumFractionDigits?: number;
  latestPreviousClose?: number | null;
};

type Panel = {
  key:
    | "volume"
    | "rsi"
    | "macd"
    | "kd"
    | "atr"
    | "adx"
    | "obv"
    | "mfi"
    | "cci"
    | "williamsR"
    | "roc"
    | "stochRsi"
    | "relativeStrength"
    | "beta"
    | "correlation";
  label: string;
  top: number;
  height: number;
};

type VisibleRangeState = {
  start: number;
  count: number;
  pinnedToLatest: boolean;
  dataKey: string | null;
};

type ChartDragState = {
  pointerId: number;
  startClientX: number;
  startVisibleStart: number;
};

type HoverPriceGuideState = {
  y: number;
  snap: "high" | "low" | null;
};

const playedKLineRevealKeys = new Set<string>();

const DEFAULT_VISIBLE_BARS = 80;
const MIN_VISIBLE_BARS = 20;
const PRICE_GUIDE_SNAP_DISTANCE = 10;

function formatPrice(value: number | null | undefined, maximumFractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";

  return value.toLocaleString("zh-TW", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
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

function numericRange(
  values: Array<number | null | undefined>,
  options?: { includeZero?: boolean; min?: number; max?: number }
) {
  const valid = values.filter(validNumber);

  if (options?.min !== undefined && options?.max !== undefined) {
    return { min: options.min, max: options.max };
  }

  if (valid.length === 0) {
    return { min: options?.min ?? 0, max: options?.max ?? 1 };
  }

  let min = options?.min ?? Math.min(...valid);
  let max = options?.max ?? Math.max(...valid);

  if (options?.includeZero) {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }

  const range = max - min || Math.max(Math.abs(max), 1);
  const padding = range * 0.08;

  return {
    min: options?.min ?? min - padding,
    max: options?.max ?? max + padding,
  };
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
  if (!validNumber(value)) return "text-omi-text";
  if (value > 0) return "text-omi-market-up";
  if (value < 0) return "text-omi-market-down";
  return "text-omi-text";
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
  indicatorParameters,
  benchmarkData = [],
  benchmarkLabel,
  revealKey,
  volumePanelLabel,
  volumeTooltipLabel,
  volumeValueKey = "volume",
  volumeValueFormatter = formatLots,
  priceMaximumFractionDigits = 2,
  latestPreviousClose = null,
}: Props) {
  const t = useT();
  const formatChartPrice = (value: number | null | undefined) =>
    formatPrice(value, priceMaximumFractionDigits);
  const resolvedVolumePanelLabel = volumePanelLabel ?? t("chart.kline.volumeLots");
  const resolvedVolumeTooltipLabel = volumeTooltipLabel ?? resolvedVolumePanelLabel;
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [hoverPriceGuide, setHoverPriceGuide] = useState<HoverPriceGuideState | null>(null);
  const [visibleRange, setVisibleRange] = useState<VisibleRangeState>({
    start: 0,
    count: DEFAULT_VISIBLE_BARS,
    pinnedToLatest: true,
    dataKey: null,
  });
  const [activeRevealKey, setActiveRevealKey] = useState<string | null>(null);
  const chartDragRef = useRef<ChartDragState | null>(null);
  const chartWheelAreaRef = useRef<SVGRectElement | null>(null);
  const revealCoverRef = useRef<HTMLDivElement | null>(null);
  const params = useMemo(
    () => ({
      ...defaultIndicatorParameters,
      ...(indicatorParameters ?? {}),
    }),
    [indicatorParameters]
  );
  const getVolumeMetric = (point: ChartPoint | MergedPoint) =>
    volumeValueKey === "trade_value" ? point.trade_value : point.volume;

  const data = useMemo(
    () =>
      projectStockKLineData({
        chartData,
        indicatorData,
        benchmarkData,
        params,
        latestPreviousClose,
      }),
    [benchmarkData, chartData, indicatorData, latestPreviousClose, params]
  );

  const dataKey = `${label}:${data.length}:${data[0]?.time ?? ""}:${data[data.length - 1]?.time ?? ""}`;
  const activeVisibleRange =
    visibleRange.dataKey === dataKey
      ? visibleRange
      : {
          ...visibleRange,
          start: 0,
          count: DEFAULT_VISIBLE_BARS,
          pinnedToLatest: true,
          dataKey,
        };
  const minVisibleBars = Math.min(MIN_VISIBLE_BARS, Math.max(data.length, 1));
  const maxVisibleBars = Math.max(minVisibleBars, data.length || minVisibleBars);
  const visibleBarCount = Math.round(
    clamp(activeVisibleRange.count, minVisibleBars, maxVisibleBars)
  );
  const maxVisibleStart = Math.max(0, data.length - visibleBarCount);
  const visibleStart = Math.round(
    clamp(
      activeVisibleRange.pinnedToLatest ? maxVisibleStart : activeVisibleRange.start,
      0,
      maxVisibleStart
    )
  );
  const visibleEnd = Math.min(data.length, visibleStart + visibleBarCount);
  const visibleData = data.slice(visibleStart, visibleEnd);
  const canMoveRange = data.length > visibleData.length;
  const visibleStep = Math.max(1, Math.round(visibleBarCount * 0.25));

  function updateVisibleCount(nextCount: number, anchorRatio = 1) {
    const count = Math.round(clamp(nextCount, minVisibleBars, maxVisibleBars));
    const safeAnchorRatio = clamp(anchorRatio, 0, 1);
    const focusedIndex = visibleStart + (visibleBarCount - 1) * safeAnchorRatio;
    const nextMaxStart = Math.max(0, data.length - count);
    const nextStart = Math.round(
      clamp(focusedIndex - (count - 1) * safeAnchorRatio, 0, nextMaxStart)
    );

    setHoverIndex(null);
    setHoverPriceGuide(null);
    setVisibleRange({
      start: nextStart,
      count,
      pinnedToLatest: nextStart === nextMaxStart,
      dataKey,
    });
  }

  function panVisibleBars(delta: number) {
    const nextStart = Math.round(clamp(visibleStart + delta, 0, maxVisibleStart));

    setHoverIndex(null);
    setHoverPriceGuide(null);
    setVisibleRange({
      start: nextStart,
      count: visibleBarCount,
      pinnedToLatest: nextStart === maxVisibleStart,
      dataKey,
    });
  }

  function jumpToLatest() {
    setHoverIndex(null);
    setHoverPriceGuide(null);
    setVisibleRange({
      start: maxVisibleStart,
      count: visibleBarCount,
      pinnedToLatest: true,
      dataKey,
    });
  }

  function showAllBars() {
    setHoverIndex(null);
    setHoverPriceGuide(null);
    setVisibleRange({
      start: 0,
      count: maxVisibleBars,
      pinnedToLatest: true,
      dataKey,
    });
  }

  const safeHoverIndex =
    hoverIndex !== null && hoverIndex >= 0 && hoverIndex < visibleData.length ? hoverIndex : null;
  const hoveredPoint =
    safeHoverIndex !== null
      ? visibleData[safeHoverIndex]
      : visibleData[visibleData.length - 1] ?? null;
  const stableRevealKey = revealKey ?? label;
  const dataReadyForReveal = data.length > 0;

  useEffect(() => {
    if (!dataReadyForReveal) return;

    const timeoutId = window.setTimeout(() => {
      setActiveRevealKey((current) => {
        if (playedKLineRevealKeys.has(stableRevealKey)) {
          return current === stableRevealKey ? current : null;
        }

        playedKLineRevealKeys.add(stableRevealKey);
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

  useEffect(() => {
    const target = chartWheelAreaRef.current;

    if (target === null || data.length < 1) return;

    const handleNativeWheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();

      if (!canMoveRange && visibleBarCount <= minVisibleBars) return;

      if (event.shiftKey && canMoveRange) {
        const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
        panVisibleBars(Math.sign(delta) * Math.max(1, Math.round(visibleBarCount * 0.08)));
        return;
      }

      if (Math.abs(event.deltaY) >= Math.abs(event.deltaX)) {
        const rect = target.getBoundingClientRect();
        const anchorRatio = clamp((event.clientX - rect.left) / rect.width, 0, 1);

        updateVisibleCount(visibleBarCount * (event.deltaY > 0 ? 1.18 : 0.82), anchorRatio);
        return;
      }

      const hasHorizontalIntent = Math.abs(event.deltaX) > Math.abs(event.deltaY);

      if (!hasHorizontalIntent || !canMoveRange) return;

      const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
      panVisibleBars(Math.sign(delta) * Math.max(1, Math.round(visibleBarCount * 0.08)));
    };

    target.addEventListener("wheel", handleNativeWheel, { passive: false });

    return () => {
      target.removeEventListener("wheel", handleNativeWheel);
    };
  });

  if (data.length < 1) {
    return (
      <div className="border border-omi-border-subtle bg-omi-surface p-4">
        <StateSurface
          title={t("chart.kline.insufficient")}
          tone="empty"
          className="h-[388px]"
        />
      </div>
    );
  }

  const width = 1000;
  const paddingLeft = 84;
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

  addPanel(indicators.volume, "volume", resolvedVolumePanelLabel);
  addPanel(indicators.rsi, "rsi", `RSI ${params.rsiPeriod}`);
  addPanel(indicators.macd, "macd", `MACD ${params.macdFast}/${params.macdSlow}/${params.macdSignal}`);
  addPanel(indicators.kd, "kd", `KD ${params.kdPeriod}`);
  addPanel(indicators.atr, "atr", `ATR ${params.atrPeriod}`);
  addPanel(indicators.adx, "adx", "ADX / DMI");
  addPanel(indicators.obv, "obv", "OBV");
  addPanel(indicators.mfi, "mfi", `MFI ${params.mfiPeriod}`);
  addPanel(indicators.cci, "cci", `CCI ${params.cciPeriod}`);
  addPanel(indicators.williamsR, "williamsR", "Williams %R");
  addPanel(indicators.roc, "roc", `ROC ${params.rocPeriod}`);
  addPanel(indicators.stochRsi, "stochRsi", "StochRSI");
  addPanel(
    indicators.relativeStrength,
    "relativeStrength",
    `RS ${params.relativeStrengthLookback}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`
  );
  addPanel(
    indicators.beta,
    "beta",
    `Beta ${params.betaPeriod}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`
  );
  addPanel(
    indicators.correlation,
    "correlation",
    `Corr ${params.correlationPeriod}${benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}`
  );

  const height = Math.max(360, nextPanelTop - panelGap + bottomPadding);
  const labelY = height - 10;
  const priceBottom = chartTop + priceHeight;
  const plotBottom = panels.length > 0 ? panels[panels.length - 1].top + panelHeight : priceBottom;

  const priceValues = visibleData
    .flatMap((point) => [
      point.open,
      point.high,
      point.low,
      point.close,
      indicators.ma ? point.ma5 : null,
      indicators.ma ? point.ma20 : null,
      indicators.ma ? point.ma60 : null,
      indicators.ema ? point.ema12 : null,
      indicators.ema ? point.ema26 : null,
      indicators.vwap ? point.vwap : null,
      indicators.psar ? point.psar : null,
      indicators.donchian ? point.donchianUpper : null,
      indicators.donchian ? point.donchianLower : null,
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
  const volumes = visibleData.map((point) => getVolumeMetric(point)).filter(validNumber);
  const maxVolume = Math.max(...volumes, 1);
  const macdValues = visibleData
    .flatMap((point) => [point.macd, point.macdSignal, point.macdHistogram])
    .filter(validNumber);
  const macdAbsMax = Math.max(...macdValues.map((value) => Math.abs(value)), 1);
  const atrRange = numericRange(visibleData.map((point) => point.atr14), { min: 0 });
  const obvRange = numericRange(
    visibleData.flatMap((point) => [point.obv, point.obvMa10]),
    { includeZero: true }
  );
  const cciRange = numericRange(
    [...visibleData.map((point) => point.cci20), -100, 0, 100],
    { includeZero: true }
  );
  const rocRange = numericRange(visibleData.map((point) => point.roc12), { includeZero: true });
  const relativeStrengthRange = numericRange(
    visibleData.map((point) => point.relativeStrength),
    { includeZero: true }
  );
  const betaRange = numericRange(visibleData.map((point) => point.beta), { includeZero: true });
  const correlationRange = { min: -1, max: 1 };
  const candleWidth = clamp((usableWidth / visibleData.length) * 0.58, 3, 12);
  const rangeHigh = visibleData.reduce<{ index: number; value: number } | null>(
    (best, point, index) => {
      const value = point.high ?? point.close;

      if (!validNumber(value)) return best;
      if (best === null || value > best.value) return { index, value };

      return best;
    },
    null
  );
  const rangeLow = visibleData.reduce<{ index: number; value: number } | null>(
    (best, point, index) => {
      const value = point.low ?? point.close;

      if (!validNumber(value)) return best;
      if (best === null || value < best.value) return { index, value };

      return best;
    },
    null
  );
  const visibleChartSignals = indicators.signals
    ? buildChartSignals(data)
        .filter((signal) => signal.index >= visibleStart && signal.index < visibleEnd)
        .map((signal) => ({
          ...signal,
          index: signal.index - visibleStart,
        }))
        .slice(-18)
    : [];

  function getX(index: number) {
    if (visibleData.length <= 1) return paddingLeft;
    return paddingLeft + (index / (visibleData.length - 1)) * usableWidth;
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

  function getPlotClientXRatio(target: SVGRectElement, clientX: number) {
    const rect = target.getBoundingClientRect();
    return clamp((clientX - rect.left) / rect.width, 0, 1);
  }

  function getPlotClientY(target: SVGRectElement, clientY: number) {
    const rect = target.getBoundingClientRect();
    const ratio = clamp((clientY - rect.top) / rect.height, 0, 1);

    return chartTop + ratio * (plotBottom - chartTop);
  }

  function updateHoverFromClientPoint(target: SVGRectElement, clientX: number, clientY: number) {
    const ratio = getPlotClientXRatio(target, clientX);
    const localX = paddingLeft + ratio * usableWidth;
    const dataRatio = (localX - paddingLeft) / usableWidth;
    const index = Math.round(dataRatio * (visibleData.length - 1));
    const safeIndex = clamp(index, 0, visibleData.length - 1);
    const pointerY = getPlotClientY(target, clientY);

    setHoverIndex(safeIndex);

    if (pointerY < chartTop || pointerY > priceBottom) {
      setHoverPriceGuide(null);
      return;
    }

    const point = visibleData[safeIndex];
    const open = point?.open ?? point?.close;
    const close = point?.close ?? point?.open;
    const high =
      point?.high ??
      (validNumber(open) && validNumber(close) ? Math.max(open, close) : null);
    const low =
      point?.low ??
      (validNumber(open) && validNumber(close) ? Math.min(open, close) : null);
    const candidates = [
      validNumber(high)
        ? { snap: "high" as const, y: getPriceY(high), distance: Math.abs(pointerY - getPriceY(high)) }
        : null,
      validNumber(low)
        ? { snap: "low" as const, y: getPriceY(low), distance: Math.abs(pointerY - getPriceY(low)) }
        : null,
    ].filter((candidate): candidate is { snap: "high" | "low"; y: number; distance: number } =>
      candidate !== null
    );
    const nearest = candidates.reduce<(typeof candidates)[number] | null>(
      (best, candidate) =>
        best === null || candidate.distance < best.distance ? candidate : best,
      null
    );

    setHoverPriceGuide(
      nearest !== null && nearest.distance <= PRICE_GUIDE_SNAP_DISTANCE
        ? { y: nearest.y, snap: nearest.snap }
        : { y: clamp(pointerY, chartTop, priceBottom), snap: null }
    );
  }

  function handlePointerDown(event: PointerEvent<SVGRectElement>) {
    if (!canMoveRange || event.button !== 0) return;

    chartDragRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startVisibleStart: visibleStart,
    };

    setHoverIndex(null);
    setHoverPriceGuide(null);
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<SVGRectElement>) {
    const current = chartDragRef.current;

    if (current === null || current.pointerId !== event.pointerId) {
      updateHoverFromClientPoint(event.currentTarget, event.clientX, event.clientY);
      return;
    }

    const deltaX = event.clientX - current.startClientX;

    event.preventDefault();

    const barSpacing = usableWidth / Math.max(visibleData.length - 1, 1);
    const nextStart = Math.round(
      clamp(current.startVisibleStart - deltaX / barSpacing, 0, maxVisibleStart)
    );

    setHoverIndex(null);
    setHoverPriceGuide(null);
    setVisibleRange({
      start: nextStart,
      count: visibleBarCount,
      pinnedToLatest: nextStart >= maxVisibleStart,
      dataKey,
    });
  }

  function handlePointerEnd(event: PointerEvent<SVGRectElement>) {
    const current = chartDragRef.current;

    if (current === null || current.pointerId !== event.pointerId) return;

    chartDragRef.current = null;

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  const ma5Path = buildLinePath(visibleData, (point) => point.ma5, getX, getPriceY);
  const ma20Path = buildLinePath(visibleData, (point) => point.ma20, getX, getPriceY);
  const ma60Path = buildLinePath(visibleData, (point) => point.ma60, getX, getPriceY);
  const ema12Path = buildLinePath(visibleData, (point) => point.ema12, getX, getPriceY);
  const ema26Path = buildLinePath(visibleData, (point) => point.ema26, getX, getPriceY);
  const vwapPath = buildLinePath(visibleData, (point) => point.vwap, getX, getPriceY);
  const bbUpperPath = buildLinePath(visibleData, (point) => point.bbUpper, getX, getPriceY);
  const bbMiddlePath = buildLinePath(visibleData, (point) => point.bbMiddle, getX, getPriceY);
  const bbLowerPath = buildLinePath(visibleData, (point) => point.bbLower, getX, getPriceY);
  const bbAreaPath = buildBandAreaPath(visibleData, (point) => point.bbUpper, (point) => point.bbLower, getX, getPriceY);
  const donchianUpperPath = buildLinePath(visibleData, (point) => point.donchianUpper, getX, getPriceY);
  const donchianLowerPath = buildLinePath(visibleData, (point) => point.donchianLower, getX, getPriceY);
  const donchianAreaPath = buildBandAreaPath(
    visibleData,
    (point) => point.donchianUpper,
    (point) => point.donchianLower,
    getX,
    getPriceY
  );
  const hoverX = safeHoverIndex !== null ? getX(safeHoverIndex) : null;
  const hoverPriceGuideY =
    safeHoverIndex !== null && hoverPriceGuide !== null
      ? clamp(hoverPriceGuide.y, chartTop, priceBottom)
      : null;
  const hoverPriceGuideSnap =
    safeHoverIndex !== null && hoverPriceGuide !== null ? hoverPriceGuide.snap : null;
  const hoverPriceGuideValue =
    hoverPriceGuideY !== null
      ? yMax - ((hoverPriceGuideY - chartTop) / priceHeight) * yRange
      : null;
  const hoverPriceGuideLabel =
    hoverPriceGuideValue !== null
      ? hoverPriceGuideSnap === "high"
        ? t("chart.kline.highGuide", { value: formatChartPrice(hoverPriceGuideValue) })
        : hoverPriceGuideSnap === "low"
          ? t("chart.kline.lowGuide", { value: formatChartPrice(hoverPriceGuideValue) })
          : formatChartPrice(hoverPriceGuideValue)
      : null;
  const hoverPriceGuideStrokeClass =
    hoverPriceGuideSnap === "high"
      ? "stroke-omi-market-up-flash"
      : hoverPriceGuideSnap === "low"
        ? "stroke-omi-market-down-flash"
        : "stroke-omi-text-muted";
  const hoverPriceGuideFillClass =
    hoverPriceGuideSnap === "high"
      ? "fill-omi-market-up-strong"
      : hoverPriceGuideSnap === "low"
        ? "fill-omi-market-down-strong"
        : "fill-omi-text";
  const shouldShowRevealCover = activeRevealKey === stableRevealKey;

  return (
    <div className="border border-omi-border-subtle bg-omi-surface">
      <div className="flex min-h-16 items-start justify-between gap-4 border-b border-omi-border-subtle px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-omi-text">{t("chart.kline.title")}</div>
          <div className="mt-1 text-xs text-omi-text-muted">
            {label} · {t("chart.kline.barCount", { count: data.length })}
          </div>
        </div>

        <div className="flex max-w-[760px] min-w-0 flex-col items-end gap-2">
          {hoveredPoint ? (
            <div className="grid min-h-[4.75rem] max-w-full grid-cols-[repeat(4,minmax(10.5rem,max-content))] gap-x-5 gap-y-1 overflow-x-auto pb-1 text-right text-xs [&>div>div]:whitespace-nowrap [&>div>div]:tabular-nums [&>div>span]:whitespace-nowrap [&>div]:min-w-[10.5rem] [&>div]:whitespace-nowrap">
              <div>
                <span className="text-omi-text-subtle">{t("chart.kline.date")}</span>
                <div className="font-semibold text-omi-text">{hoveredPoint.time}</div>
              </div>
              <div>
                <span className="text-omi-text-subtle">{t("chart.kline.close")}</span>
                <div className="font-semibold text-omi-text">
                  {formatChartPrice(hoveredPoint.close)}
                </div>
              </div>
              <div>
                <span className="text-omi-text-subtle">{t("chart.kline.change")}</span>
                <div className={`font-semibold ${valueTone(hoveredPoint.changePct)}`}>
                  {formatPct(hoveredPoint.changePct)}
                </div>
              </div>
              <div>
                <span className="text-omi-text-subtle">{resolvedVolumeTooltipLabel}</span>
                <div className="font-semibold text-omi-text">
                  {volumeValueFormatter(getVolumeMetric(hoveredPoint))}
                </div>
              </div>
              {volumeValueKey !== "trade_value" ? (
                <div>
                  <span className="text-omi-text-subtle">{t("chart.kline.tradeValue")}</span>
                  <div className="font-semibold text-omi-text">
                    {formatTradeValue(hoveredPoint.trade_value)}
                  </div>
                </div>
              ) : null}
              <div>
                <span className="text-omi-text-subtle">
                  MA{params.maShort}/{params.maMiddle}/{params.maLong}
                </span>
                <div className="font-semibold text-omi-text">
                  {formatChartPrice(hoveredPoint.ma5)} / {formatChartPrice(hoveredPoint.ma20)} /{" "}
                  {formatChartPrice(hoveredPoint.ma60)}
                </div>
              </div>
              {indicators.ema ? (
                <div>
                  <span className="text-omi-text-subtle">
                    EMA{params.emaFast}/{params.emaSlow}
                  </span>
                  <div className="font-semibold text-omi-text">
                    {formatChartPrice(hoveredPoint.ema12)} / {formatChartPrice(hoveredPoint.ema26)}
                  </div>
                </div>
              ) : null}
              {indicators.vwap ? (
                <div>
                  <span className="text-omi-text-subtle">VWAP</span>
                  <div className="font-semibold text-omi-text">
                    {formatChartPrice(hoveredPoint.vwap)}
                  </div>
                </div>
              ) : null}
              {indicators.psar ? (
                <div>
                  <span className="text-omi-text-subtle">SAR</span>
                  <div className="font-semibold text-omi-text">
                    {formatChartPrice(hoveredPoint.psar)}
                  </div>
                </div>
              ) : null}
              <div>
                <span className="text-omi-text-subtle">RSI</span>
                <div className="font-semibold text-omi-text">
                  {formatIndicator(hoveredPoint.rsi14)}
                </div>
              </div>
              <div>
                <span className="text-omi-text-subtle">MACD</span>
                <div className={`font-semibold ${valueTone(hoveredPoint.macdHistogram)}`}>
                  {formatIndicator(hoveredPoint.macdHistogram)}
                </div>
              </div>
              <div>
                <span className="text-omi-text-subtle">K/D</span>
                <div className="font-semibold text-omi-text">
                  {formatIndicator(hoveredPoint.k)} / {formatIndicator(hoveredPoint.d)}
                </div>
              </div>
              {indicators.atr ? (
                <div>
                  <span className="text-omi-text-subtle">ATR</span>
                  <div className="font-semibold text-omi-text">
                    {formatIndicator(hoveredPoint.atr14)}
                  </div>
                </div>
              ) : null}
              {indicators.adx ? (
                <div>
                  <span className="text-omi-text-subtle">ADX/+DI/-DI</span>
                  <div className="font-semibold text-omi-text">
                    {formatIndicator(hoveredPoint.adx14)} / {formatIndicator(hoveredPoint.plusDi14)} /{" "}
                    {formatIndicator(hoveredPoint.minusDi14)}
                  </div>
                </div>
              ) : null}
              {indicators.obv ? (
                <div>
                  <span className="text-omi-text-subtle">{t("chart.kline.obvLots")}</span>
                  <div className={`font-semibold ${valueTone(hoveredPoint.obv)}`}>
                    {formatLots(hoveredPoint.obv)}
                  </div>
                </div>
              ) : null}
              {indicators.mfi ? (
                <div>
                  <span className="text-omi-text-subtle">MFI</span>
                  <div className="font-semibold text-omi-text">
                    {formatIndicator(hoveredPoint.mfi14)}
                  </div>
                </div>
              ) : null}
              {indicators.cci ? (
                <div>
                  <span className="text-omi-text-subtle">CCI</span>
                  <div className={`font-semibold ${valueTone(hoveredPoint.cci20)}`}>
                    {formatIndicator(hoveredPoint.cci20)}
                  </div>
                </div>
              ) : null}
              {indicators.williamsR ? (
                <div>
                  <span className="text-omi-text-subtle">Williams %R</span>
                  <div className="font-semibold text-omi-text">
                    {formatIndicator(hoveredPoint.williamsR14)}
                  </div>
                </div>
              ) : null}
              {indicators.roc ? (
                <div>
                  <span className="text-omi-text-subtle">ROC</span>
                  <div className={`font-semibold ${valueTone(hoveredPoint.roc12)}`}>
                    {formatPct(hoveredPoint.roc12)}
                  </div>
                </div>
              ) : null}
              {indicators.stochRsi ? (
                <div>
                  <span className="text-omi-text-subtle">StochRSI K/D</span>
                  <div className="font-semibold text-omi-text">
                    {formatIndicator(hoveredPoint.stochRsiK)} / {formatIndicator(hoveredPoint.stochRsiD)}
                  </div>
                </div>
              ) : null}
              {indicators.relativeStrength ? (
                <div>
                  <span className="text-omi-text-subtle">
                    RS{params.relativeStrengthLookback}
                    {benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}
                  </span>
                  <div className={`font-semibold ${valueTone(hoveredPoint.relativeStrength)}`}>
                    {formatPct(hoveredPoint.relativeStrength)}
                  </div>
                </div>
              ) : null}
              {indicators.beta ? (
                <div>
                  <span className="text-omi-text-subtle">
                    Beta{params.betaPeriod}
                    {benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}
                  </span>
                  <div className="font-semibold text-omi-text">
                    {formatIndicator(hoveredPoint.beta)}
                  </div>
                </div>
              ) : null}
              {indicators.correlation ? (
                <div>
                  <span className="text-omi-text-subtle">
                    Corr{params.correlationPeriod}
                    {benchmarkLabel ? ` vs ${benchmarkLabel}` : ""}
                  </span>
                  <div className={`font-semibold ${valueTone(hoveredPoint.correlation)}`}>
                    {formatIndicator(hoveredPoint.correlation)}
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="min-h-[4.75rem]" aria-hidden="true" />
          )}
          <div className="flex w-full flex-wrap items-center justify-end gap-2 text-xs">
            <span className="whitespace-nowrap text-omi-text-muted">
              {visibleStart + 1}-{visibleEnd} / {data.length}
            </span>
            <button
              type="button"
              aria-label={t("chart.kline.panLeft")}
              title={t("chart.kline.panLeft")}
              onClick={() => panVisibleBars(-visibleStep)}
              disabled={!canMoveRange || visibleStart <= 0}
              className="h-7 w-7 border border-omi-border bg-omi-surface font-semibold text-omi-text hover:border-omi-border-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
            >
              &lt;
            </button>
            <button
              type="button"
              aria-label={t("chart.kline.panRight")}
              title={t("chart.kline.panRight")}
              onClick={() => panVisibleBars(visibleStep)}
              disabled={!canMoveRange || visibleStart >= maxVisibleStart}
              className="h-7 w-7 border border-omi-border bg-omi-surface font-semibold text-omi-text hover:border-omi-border-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
            >
              &gt;
            </button>
            <button
              type="button"
              aria-label={t("chart.kline.zoomIn")}
              title={t("chart.kline.zoomIn")}
              onClick={() => updateVisibleCount(visibleBarCount * 0.72)}
              disabled={visibleBarCount <= minVisibleBars}
              className="h-7 w-7 border border-omi-border bg-omi-surface font-semibold text-omi-text hover:border-omi-border-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
            >
              +
            </button>
            <button
              type="button"
              aria-label={t("chart.kline.zoomOut")}
              title={t("chart.kline.zoomOut")}
              onClick={() => updateVisibleCount(visibleBarCount * 1.38)}
              disabled={visibleBarCount >= maxVisibleBars}
              className="h-7 w-7 border border-omi-border bg-omi-surface font-semibold text-omi-text hover:border-omi-border-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
            >
              -
            </button>
            <button
              type="button"
              aria-label={t("chart.kline.jumpLatest")}
              title={t("chart.kline.jumpLatest")}
              onClick={jumpToLatest}
              disabled={!canMoveRange || visibleStart >= maxVisibleStart}
              className="h-7 border border-omi-border bg-omi-surface px-2 font-semibold text-omi-text hover:border-omi-border-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
            >
              {t("chart.kline.latest")}
            </button>
            <button
              type="button"
              onClick={showAllBars}
              disabled={visibleBarCount >= maxVisibleBars}
              className="h-7 border border-omi-border bg-omi-surface px-2 font-semibold text-omi-text hover:border-omi-border-strong disabled:cursor-not-allowed disabled:text-omi-text-inverse-muted"
            >
              {t("chart.kline.all")}
            </button>
            <input
              type="range"
              min={0}
              max={maxVisibleStart}
              step={1}
              value={visibleStart}
              aria-label={t("chart.kline.visibleRange")}
              disabled={!canMoveRange}
              onChange={(event) => {
                const nextStart = Number(event.target.value);

                setHoverIndex(null);
                setHoverPriceGuide(null);
                setVisibleRange({
                  start: nextStart,
                  count: visibleBarCount,
                  pinnedToLatest: nextStart >= maxVisibleStart,
                  dataKey,
                });
              }}
              className="h-7 w-40 accent-slate-900 disabled:opacity-40"
            />
          </div>
        </div>
      </div>

      <div className="relative overflow-hidden">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }}>
        <rect x="0" y="0" width={width} height={height} className="fill-omi-surface" />

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
                className="stroke-omi-border-subtle"
              />
              <text
                x={paddingLeft - 10}
                y={y + 4}
                textAnchor="end"
                className="fill-omi-text-muted text-[12px] font-medium"
              >
                {formatChartPrice(price)}
              </text>
            </g>
          );
        })}

        {indicators.bollinger && bbAreaPath ? (
          <path d={bbAreaPath} className="fill-omi-chart-sky-soft/70" />
        ) : null}

        {indicators.donchian && donchianAreaPath ? (
          <path d={donchianAreaPath} className="fill-omi-chart-lime-soft/50" />
        ) : null}

        {visibleData.map((point, index) => {
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
            ? "fill-omi-market-up stroke-omi-market-up"
            : "fill-omi-market-down stroke-omi-market-down";

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
              <path d={bbUpperPath} fill="none" strokeWidth="1.4" className="stroke-omi-chart-sky" />
            ) : null}
            {bbMiddlePath ? (
              <path d={bbMiddlePath} fill="none" strokeWidth="1.2" className="stroke-omi-chart-sky" strokeDasharray="4 4" />
            ) : null}
            {bbLowerPath ? (
              <path d={bbLowerPath} fill="none" strokeWidth="1.4" className="stroke-omi-chart-sky" />
            ) : null}
          </>
        ) : null}

        {indicators.donchian ? (
          <>
            {donchianUpperPath ? (
              <path d={donchianUpperPath} fill="none" strokeWidth="1.3" className="stroke-omi-chart-lime" />
            ) : null}
            {donchianLowerPath ? (
              <path d={donchianLowerPath} fill="none" strokeWidth="1.3" className="stroke-omi-chart-lime" />
            ) : null}
          </>
        ) : null}

        {indicators.ma && ma5Path ? (
          <path
            d={ma5Path}
            fill="none"
            strokeWidth="2"
            className="stroke-omi-chart-blue"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ma && ma20Path ? (
          <path
            d={ma20Path}
            fill="none"
            strokeWidth="2"
            className="stroke-omi-chart-amber"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ma && ma60Path ? (
          <path
            d={ma60Path}
            fill="none"
            strokeWidth="1.6"
            className="stroke-omi-chart-purple"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ema && ema12Path ? (
          <path
            d={ema12Path}
            fill="none"
            strokeWidth="1.8"
            className="stroke-omi-chart-cyan"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.ema && ema26Path ? (
          <path
            d={ema26Path}
            fill="none"
            strokeWidth="1.8"
            className="stroke-omi-chart-rose"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.vwap && vwapPath ? (
          <path
            d={vwapPath}
            fill="none"
            strokeWidth="2"
            className="stroke-omi-text"
            strokeDasharray="6 4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ) : null}
        {indicators.psar
          ? visibleData.map((point, index) => {
              if (!validNumber(point.psar)) return null;

              return (
                <circle
                  key={`${point.time}-psar`}
                  cx={getX(index)}
                  cy={getPriceY(point.psar)}
                  r="2.5"
                  className="fill-omi-chart-violet"
                />
              );
            })
          : null}

        {rangeHigh ? (
          <g>
            {(() => {
              const x = getX(rangeHigh.index);
              const y = getPriceY(rangeHigh.value);
              const label = labelPosition(x, paddingLeft, paddingRight, width);
              const labelY = clamp(y - 12, chartTop + 12, priceBottom - 8);

              return (
                <>
                  <circle cx={x} cy={y} r="3.5" className="fill-omi-market-up" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={labelY}
                    className="stroke-omi-market-up-border"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={labelY - 3}
                    textAnchor={label.anchor}
                    className="fill-omi-market-up text-[11px] font-semibold"
                  >
                    {t("chart.kline.highMarker", {
                      value: formatChartPrice(rangeHigh.value),
                    })}
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
                  <circle cx={x} cy={y} r="3.5" className="fill-omi-market-down" />
                  <line
                    x1={x}
                    x2={label.x}
                    y1={y}
                    y2={labelY}
                    className="stroke-omi-market-down-border"
                    strokeDasharray="3 3"
                  />
                  <text
                    x={label.x}
                    y={labelY + 10}
                    textAnchor={label.anchor}
                    className="fill-omi-market-down text-[11px] font-semibold"
                  >
                    {t("chart.kline.lowMarker", {
                      value: formatChartPrice(rangeLow.value),
                    })}
                  </text>
                </>
              );
            })()}
          </g>
        ) : null}

        {visibleChartSignals.map((signal) => {
          const x = getX(signal.index);
          const y = clamp(
            getPriceY(signal.price) + (signal.direction === "bearish" ? 18 : -18),
            chartTop + 16,
            priceBottom - 8
          );
          const labelWidth = Math.max(signal.label.length * 12 + 12, 54);
          const label = labelPosition(x, paddingLeft, paddingRight, width);
          const labelX = label.anchor === "end" ? x - 10 : x + 10;
          const rectX = label.anchor === "end" ? labelX - labelWidth : labelX;
          const tone =
            signal.direction === "bullish"
              ? "fill-omi-market-up"
              : signal.direction === "bearish"
                ? "fill-omi-market-down"
                : "fill-omi-chart-violet";

          return (
            <g key={signal.key}>
              <line
                x1={x}
                x2={labelX}
                y1={getPriceY(signal.price)}
                y2={y}
                className="stroke-omi-border"
                strokeDasharray="3 3"
              />
              <circle cx={x} cy={getPriceY(signal.price)} r="3" className={tone} />
              <rect
                x={rectX}
                y={y - 10}
                width={labelWidth}
                height="18"
                rx="2"
                className={tone}
              />
              <text
                x={label.anchor === "end" ? labelX - 6 : labelX + 6}
                y={y + 3}
                textAnchor={label.anchor}
                className="fill-omi-surface text-[10px] font-semibold"
              >
                {signal.label}
              </text>
              <title>{`${visibleData[signal.index]?.time ?? ""} ${signal.label}`}</title>
            </g>
          );
        })}

        {panels.map((panel) => {
          const panelBottom = panel.top + panel.height;

          return (
            <g key={panel.key}>
              <line
                x1={paddingLeft}
                x2={width - paddingRight}
                y1={panel.top}
                y2={panel.top}
                className="stroke-omi-border-subtle"
              />
              <text
                x={paddingLeft - 10}
                y={panel.top + 12}
                textAnchor="end"
                className="fill-omi-text-muted text-[11px]"
              >
                {panel.label}
              </text>

              {panel.key === "volume" ? (
                <>
                  {visibleData.map((point, index) => {
                    const open = point.open ?? point.close;
                    const close = point.close ?? point.open;
                    const volume = getVolumeMetric(point);
                    if (!validNumber(volume)) return null;

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
                        className={isUp ? "fill-omi-market-up-border" : "fill-omi-market-down-border"}
                      />
                    );
                  })}
                  <text
                    x={paddingLeft - 10}
                    y={panelBottom}
                    textAnchor="end"
                    className="fill-omi-text-subtle text-[10px]"
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
                      className={value === 50 ? "stroke-omi-border-subtle" : "stroke-omi-border-subtle"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.rsi14, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-fuchsia"
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
                    className="stroke-omi-border-subtle"
                  />
                  {visibleData.map((point, index) => {
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
                        className={point.macdHistogram >= 0 ? "fill-omi-market-up-border" : "fill-omi-market-down-border"}
                      />
                    );
                  })}
                  <path
                    d={buildLinePath(visibleData, (point) => point.macd, getX, (value) =>
                      getPanelY(panel, value, -macdAbsMax, macdAbsMax)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-omi-chart-blue"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.macdSignal, getX, (value) =>
                      getPanelY(panel, value, -macdAbsMax, macdAbsMax)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-omi-chart-amber"
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
                      className={value === 50 ? "stroke-omi-border-subtle" : "stroke-omi-border-subtle"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.k, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-omi-chart-blue"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.d, getX, (value) => getPanelY(panel, value, 0, 100))}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-omi-chart-amber"
                  />
                </>
              ) : null}

              {panel.key === "atr" ? (
                <>
                  <text
                    x={paddingLeft - 10}
                    y={panel.top + panel.height}
                    textAnchor="end"
                    className="fill-omi-text-subtle text-[10px]"
                  >
                    0
                  </text>
                  <path
                    d={buildLinePath(visibleData, (point) => point.atr14, getX, (value) =>
                      getPanelY(panel, value, atrRange.min, atrRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-orange"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "adx" ? (
                <>
                  {[20, 25, 50].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 25 ? "stroke-omi-border" : "stroke-omi-border-subtle"}
                      strokeDasharray={value === 25 ? "4 4" : undefined}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.adx14, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-violet"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.plusDi14, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.5"
                    className="stroke-omi-market-up-flash"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.minusDi14, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.5"
                    className="stroke-omi-market-down-flash"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "obv" ? (
                <>
                  {obvRange.min < 0 && obvRange.max > 0 ? (
                    <line
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, 0, obvRange.min, obvRange.max)}
                      y2={getPanelY(panel, 0, obvRange.min, obvRange.max)}
                      className="stroke-omi-border-subtle"
                    />
                  ) : null}
                  <path
                    d={buildLinePath(visibleData, (point) => point.obv, getX, (value) =>
                      getPanelY(panel, value, obvRange.min, obvRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-text"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.obvMa10, getX, (value) =>
                      getPanelY(panel, value, obvRange.min, obvRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.5"
                    className="stroke-omi-chart-amber"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "mfi" ? (
                <>
                  {[20, 50, 80].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 50 ? "stroke-omi-border-subtle" : "stroke-omi-border-subtle"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.mfi14, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-teal"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "cci" ? (
                <>
                  {[-100, 0, 100].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, cciRange.min, cciRange.max)}
                      y2={getPanelY(panel, value, cciRange.min, cciRange.max)}
                      className={value === 0 ? "stroke-omi-border-subtle" : "stroke-omi-border"}
                      strokeDasharray={value === 0 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.cci20, getX, (value) =>
                      getPanelY(panel, value, cciRange.min, cciRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-indigo"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "williamsR" ? (
                <>
                  {[-80, -50, -20].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, -100, 0)}
                      y2={getPanelY(panel, value, -100, 0)}
                      className={value === -50 ? "stroke-omi-border-subtle" : "stroke-omi-border-subtle"}
                      strokeDasharray={value === -50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.williamsR14, getX, (value) =>
                      getPanelY(panel, value, -100, 0)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-pink"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "roc" ? (
                <>
                  <line
                    x1={paddingLeft}
                    x2={width - paddingRight}
                    y1={getPanelY(panel, 0, rocRange.min, rocRange.max)}
                    y2={getPanelY(panel, 0, rocRange.min, rocRange.max)}
                    className="stroke-omi-border-subtle"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.roc12, getX, (value) =>
                      getPanelY(panel, value, rocRange.min, rocRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-cyan"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "stochRsi" ? (
                <>
                  {[20, 50, 80].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, 0, 100)}
                      y2={getPanelY(panel, value, 0, 100)}
                      className={value === 50 ? "stroke-omi-border-subtle" : "stroke-omi-border-subtle"}
                      strokeDasharray={value === 50 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.stochRsiK, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-omi-chart-blue"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.stochRsiD, getX, (value) =>
                      getPanelY(panel, value, 0, 100)
                    )}
                    fill="none"
                    strokeWidth="1.7"
                    className="stroke-omi-chart-amber"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "relativeStrength" ? (
                <>
                  <line
                    x1={paddingLeft}
                    x2={width - paddingRight}
                    y1={getPanelY(panel, 0, relativeStrengthRange.min, relativeStrengthRange.max)}
                    y2={getPanelY(panel, 0, relativeStrengthRange.min, relativeStrengthRange.max)}
                    className="stroke-omi-border-subtle"
                  />
                  <path
                    d={buildLinePath(visibleData, (point) => point.relativeStrength, getX, (value) =>
                      getPanelY(panel, value, relativeStrengthRange.min, relativeStrengthRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-violet"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "beta" ? (
                <>
                  <line
                    x1={paddingLeft}
                    x2={width - paddingRight}
                    y1={getPanelY(panel, 0, betaRange.min, betaRange.max)}
                    y2={getPanelY(panel, 0, betaRange.min, betaRange.max)}
                    className="stroke-omi-border-subtle"
                  />
                  {betaRange.min <= 1 && betaRange.max >= 1 ? (
                    <line
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, 1, betaRange.min, betaRange.max)}
                      y2={getPanelY(panel, 1, betaRange.min, betaRange.max)}
                      className="stroke-omi-border"
                      strokeDasharray="4 4"
                    />
                  ) : null}
                  <path
                    d={buildLinePath(visibleData, (point) => point.beta, getX, (value) =>
                      getPanelY(panel, value, betaRange.min, betaRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-teal"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}

              {panel.key === "correlation" ? (
                <>
                  {[-0.5, 0, 0.5].map((value) => (
                    <line
                      key={value}
                      x1={paddingLeft}
                      x2={width - paddingRight}
                      y1={getPanelY(panel, value, correlationRange.min, correlationRange.max)}
                      y2={getPanelY(panel, value, correlationRange.min, correlationRange.max)}
                      className={value === 0 ? "stroke-omi-border" : "stroke-omi-border-subtle"}
                      strokeDasharray={value === 0 ? undefined : "4 4"}
                    />
                  ))}
                  <path
                    d={buildLinePath(visibleData, (point) => point.correlation, getX, (value) =>
                      getPanelY(panel, value, correlationRange.min, correlationRange.max)
                    )}
                    fill="none"
                    strokeWidth="1.8"
                    className="stroke-omi-chart-sky"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </>
              ) : null}
            </g>
          );
        })}

        {hoverX !== null ? (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={chartTop}
              y2={plotBottom}
              className="stroke-omi-border-strong"
              strokeDasharray="4 4"
            />
            {hoverPriceGuideY !== null && hoverPriceGuideLabel !== null ? (
              <>
                <line
                  x1={paddingLeft}
                  x2={width - paddingRight}
                  y1={hoverPriceGuideY}
                  y2={hoverPriceGuideY}
                  className={hoverPriceGuideStrokeClass}
                  strokeDasharray="4 4"
                />
                <rect
                  x={4}
                  y={clamp(hoverPriceGuideY - 12, chartTop + 2, priceBottom - 24)}
                  width={paddingLeft - 10}
                  height={24}
                  rx={3}
                  className={hoverPriceGuideFillClass}
                />
                <text
                  x={paddingLeft - 14}
                  y={clamp(hoverPriceGuideY + 4, chartTop + 18, priceBottom - 8)}
                  textAnchor="end"
                  className="fill-omi-surface text-[12px] font-semibold tabular-nums"
                >
                  {hoverPriceGuideLabel}
                </text>
              </>
            ) : null}
          </g>
        ) : null}

        <text x={paddingLeft} y={labelY} textAnchor="start" className="fill-omi-text-muted text-[11px]">
          {visibleData[0]?.time ?? "-"}
        </text>
        <text
          x={width - paddingRight}
          y={labelY}
          textAnchor="end"
          className="fill-omi-text-muted text-[11px]"
        >
          {visibleData[visibleData.length - 1]?.time ?? "-"}
        </text>

        <g transform={`translate(${paddingLeft}, 18)`}>
          {indicators.ma ? (
            <>
              <circle cx="0" cy="0" r="4" className="fill-omi-chart-blue" />
              <text x="10" y="4" className="fill-omi-text-muted text-[11px]">
                MA{params.maShort}
              </text>
              <circle cx="58" cy="0" r="4" className="fill-omi-chart-amber" />
              <text x="68" y="4" className="fill-omi-text-muted text-[11px]">
                MA{params.maMiddle}
              </text>
              <circle cx="126" cy="0" r="4" className="fill-omi-chart-purple" />
              <text x="136" y="4" className="fill-omi-text-muted text-[11px]">
                MA{params.maLong}
              </text>
            </>
          ) : null}
          {indicators.bollinger ? (
            <>
              <rect x={190} y={-4} width={8} height={8} className="fill-omi-chart-sky" />
              <text x="204" y="4" className="fill-omi-text-muted text-[11px]">
                BOLL
              </text>
            </>
          ) : null}
          {indicators.ema ? (
            <>
              <circle cx="248" cy="0" r="4" className="fill-omi-chart-cyan" />
              <text x="258" y="4" className="fill-omi-text-muted text-[11px]">
                EMA{params.emaFast}
              </text>
              <circle cx="318" cy="0" r="4" className="fill-omi-chart-rose" />
              <text x="328" y="4" className="fill-omi-text-muted text-[11px]">
                EMA{params.emaSlow}
              </text>
            </>
          ) : null}
          {indicators.vwap ? (
            <>
              <circle cx="388" cy="0" r="4" className="fill-omi-text" />
              <text x="398" y="4" className="fill-omi-text-muted text-[11px]">
                VWAP
              </text>
            </>
          ) : null}
          {indicators.psar ? (
            <>
              <circle cx="452" cy="0" r="4" className="fill-omi-chart-violet" />
              <text x="462" y="4" className="fill-omi-text-muted text-[11px]">
                SAR
              </text>
            </>
          ) : null}
          {indicators.donchian ? (
            <>
              <rect x={506} y={-4} width={8} height={8} className="fill-omi-chart-lime" />
              <text x="520" y="4" className="fill-omi-text-muted text-[11px]">
                DONCH
              </text>
            </>
          ) : null}
        </g>

        <rect
          ref={chartWheelAreaRef}
          x={paddingLeft}
          y={chartTop}
          width={usableWidth}
          height={plotBottom - chartTop}
          fill="transparent"
          pointerEvents="all"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
          onPointerLeave={(event) => {
            const current = chartDragRef.current;

            if (current === null || current.pointerId !== event.pointerId) {
              setHoverIndex(null);
              setHoverPriceGuide(null);
            }
          }}
          onContextMenu={(event) => {
            if (chartDragRef.current !== null) {
              event.preventDefault();
            }
          }}
          style={{
            touchAction: "pan-y",
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
    </div>
  );
}

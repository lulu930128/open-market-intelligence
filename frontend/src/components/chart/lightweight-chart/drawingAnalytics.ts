import type { ChartPoint } from "@/types/market";
import {
  translateDrawing,
  formatDrawingUnitCount,
  finiteNumber,
  formatDrawingPrice,
  formatSignedDrawingPrice,
  formatDrawingPercent,
  formatDrawingRatioPercent,
  parseDrawingTimeMs,
  formatDurationLabel,
  formatCompactVolume,
  type DrawingAnalysisI18n,
  type ChartDrawingPoint,
  type ChartDrawingContext,
  type ChartDrawingDerivedMetrics,
  type ChartDrawingAnchoredVwapAnalysis,
  type ChartDrawingVolumeProfileLevel,
  type ChartDrawingVolumeProfileAnalysis,
  type ChartDrawingFibonacciLevel,
  type ChartDrawingFibonacciAnalysis,
  type ChartDrawingOmiSummary,
  type ChartDrawingLineAnalysis,
  type ChartDrawingZoneAnalysis,
  type ChartDrawing,
  type ProjectedMeasurementStats,
} from "@/components/chart/lightweight-chart/drawingModel";
import {
  fibonacciAnalysisRatios,
  drawingVolumeProfileRows,
  drawingValueAreaTargetPct,
  formatFibonacciRatio,
} from "@/components/chart/lightweight-chart/drawingGeometry";

export function medianFinite(values: number[]) {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);

  if (sorted.length === 0) return null;

  const middle = Math.floor(sorted.length / 2);

  return sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
}

export function pointClose(point: ChartPoint | null | undefined) {
  if (!point) return null;
  if (finiteNumber(point.close)) return point.close;
  if (finiteNumber(point.open)) return point.open;

  return null;
}

export function lineValueAtIndex(
  startPrice: number,
  endPrice: number,
  startIndex: number,
  endIndex: number,
  targetIndex: number
) {
  if (startIndex === endIndex) return endPrice;

  return startPrice + ((targetIndex - startIndex) / (endIndex - startIndex)) * (endPrice - startPrice);
}

export function estimateLineAnalysisTolerance(chartData: ChartPoint[], referencePrice: number) {
  const recentRanges = chartData.slice(-120).flatMap((point) => {
    if (!finiteNumber(point.high) || !finiteNumber(point.low)) return [];
    const range = point.high - point.low;

    return range > 0 ? [range] : [];
  });
  const medianRange = medianFinite(recentRanges);
  const priceTolerance = Math.abs(referencePrice) * 0.003;
  const rangeTolerance = finiteNumber(medianRange) ? medianRange * 0.25 : 0;
  const rawTolerance = Math.max(priceTolerance, rangeTolerance, 0.01);
  const cap = Math.abs(referencePrice) > 0 ? Math.abs(referencePrice) * 0.02 : rawTolerance;

  return Math.min(rawTolerance, cap);
}

export function candleTouchesPrice(point: ChartPoint, price: number, tolerance: number) {
  if (finiteNumber(point.high) && finiteNumber(point.low)) {
    return point.low - tolerance <= price && point.high + tolerance >= price;
  }

  const close = pointClose(point);

  return finiteNumber(close) ? Math.abs(close - price) <= tolerance : false;
}

export function lineAnalysisRole(distance: number | null, tolerance: number | null): ChartDrawingLineAnalysis["role"] {
  if (!finiteNumber(distance) || !finiteNumber(tolerance)) return "unknown";
  if (Math.abs(distance) <= tolerance) return "neutral";

  return distance > 0 ? "support" : "resistance";
}

export function lineAnalysisStatusLabel(
  status: ChartDrawingLineAnalysis["status"],
  i18n?: DrawingAnalysisI18n
) {
  switch (status) {
    case "testing":
      return translateDrawing(i18n, "lineStatus.testing", "測試線位");
    case "above":
      return translateDrawing(i18n, "lineStatus.above", "站在線上");
    case "below":
      return translateDrawing(i18n, "lineStatus.below", "跌在線下");
    case "breakout":
      return translateDrawing(i18n, "lineStatus.breakout", "突破");
    case "breakdown":
      return translateDrawing(i18n, "lineStatus.breakdown", "跌破");
    case "retest_support":
      return translateDrawing(i18n, "lineStatus.retestSupport", "回踩支撐");
    case "retest_resistance":
      return translateDrawing(i18n, "lineStatus.retestResistance", "反壓回測");
    default:
      return translateDrawing(i18n, "lineStatus.unknown", "資料不足");
  }
}

export function lineAnalysisRoleLabel(
  role: ChartDrawingLineAnalysis["role"],
  i18n?: DrawingAnalysisI18n
) {
  switch (role) {
    case "support":
      return translateDrawing(i18n, "lineRole.support", "支撐");
    case "resistance":
      return translateDrawing(i18n, "lineRole.resistance", "壓力");
    case "neutral":
      return translateDrawing(i18n, "lineRole.neutral", "測試中");
    default:
      return translateDrawing(i18n, "lineRole.unknown", "未判定");
  }
}

export function buildLineAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData: ChartPoint[] | undefined,
  i18n?: DrawingAnalysisI18n
): ChartDrawingLineAnalysis | null {
  if (type !== "horizontal" && type !== "trend" && type !== "ray") return null;
  if (!chartData || chartData.length === 0) return null;

  const first = points[0] ?? null;
  const second = points[1] ?? first;
  const firstIndex = first ? timeIndex.get(first.time) : undefined;
  const secondIndex = second ? timeIndex.get(second.time) : undefined;
  const latestIndex = chartData.length - 1;
  const latestPoint = chartData[latestIndex] ?? null;
  const previousPoint = latestIndex > 0 ? chartData[latestIndex - 1] : null;
  const latestPrice = pointClose(latestPoint);
  const previousPrice = pointClose(previousPoint);

  if (!first || !finiteNumber(first.price) || !latestPoint || !finiteNumber(latestPrice)) {
    return null;
  }

  const projectedPrice =
    type === "horizontal"
      ? first.price
      : finiteNumber(first.price) &&
          finiteNumber(second?.price) &&
          firstIndex !== undefined &&
          secondIndex !== undefined
        ? lineValueAtIndex(first.price, second.price, firstIndex, secondIndex, latestIndex)
        : null;

  if (!finiteNumber(projectedPrice)) return null;

  const previousProjectedPrice =
    type === "horizontal"
      ? first.price
      : finiteNumber(first.price) &&
          finiteNumber(second?.price) &&
          firstIndex !== undefined &&
          secondIndex !== undefined &&
          previousPoint
        ? lineValueAtIndex(first.price, second.price, firstIndex, secondIndex, latestIndex - 1)
        : null;
  const tolerance = estimateLineAnalysisTolerance(chartData, projectedPrice);
  const distance = latestPrice - projectedPrice;
  const distancePct = projectedPrice !== 0 ? (distance / projectedPrice) * 100 : null;
  const latestTouches = candleTouchesPrice(latestPoint, projectedPrice, tolerance);
  const previousDistance =
    finiteNumber(previousPrice) && finiteNumber(previousProjectedPrice)
      ? previousPrice - previousProjectedPrice
      : null;
  const role = lineAnalysisRole(distance, tolerance);
  let status: ChartDrawingLineAnalysis["status"] = "unknown";

  if (Math.abs(distance) <= tolerance || latestTouches) {
    status = "testing";
  }

  if (
    finiteNumber(previousDistance) &&
    previousDistance <= tolerance &&
    distance > tolerance
  ) {
    status = "breakout";
  } else if (
    finiteNumber(previousDistance) &&
    previousDistance >= -tolerance &&
    distance < -tolerance
  ) {
    status = "breakdown";
  } else if (distance > tolerance && latestTouches) {
    status = "retest_support";
  } else if (distance < -tolerance && latestTouches) {
    status = "retest_resistance";
  } else if (status === "unknown") {
    status = distance > 0 ? "above" : distance < 0 ? "below" : "testing";
  }

  let touchCount = 0;
  let inTouchCluster = false;
  let lastTouchTime: string | null = null;
  let lastCrossTime: string | null = null;
  let previousSign: -1 | 0 | 1 | null = null;

  chartData.forEach((point, index) => {
    const close = pointClose(point);
    const linePrice =
      type === "horizontal"
        ? first.price
        : finiteNumber(first.price) &&
            finiteNumber(second?.price) &&
            firstIndex !== undefined &&
            secondIndex !== undefined
          ? lineValueAtIndex(first.price, second.price, firstIndex, secondIndex, index)
          : null;

    if (!finiteNumber(linePrice) || !finiteNumber(close)) return;

    const pointDistance = close - linePrice;
    const sign =
      Math.abs(pointDistance) <= tolerance ? 0 : pointDistance > 0 ? 1 : -1;
    const touches = candleTouchesPrice(point, linePrice, tolerance);

    if (touches) {
      if (!inTouchCluster) {
        touchCount += 1;
      }
      inTouchCluster = true;
      lastTouchTime = point.time;
    } else {
      inTouchCluster = false;
    }

    if (
      previousSign !== null &&
      sign !== 0 &&
      previousSign !== 0 &&
      sign !== previousSign
    ) {
      lastCrossTime = point.time;
    }

    if (sign !== 0) {
      previousSign = sign;
    }
  });

  return {
    version: 1,
    kind: type === "horizontal" ? "horizontal" : "trend",
    role,
    status,
    levelPrice: type === "horizontal" ? first.price : null,
    projectedPrice,
    latestPrice,
    latestTime: latestPoint.time,
    distance,
    distancePct,
    tolerance,
    touchCount,
    lastTouchTime,
    lastCrossTime,
    labels: {
      role: lineAnalysisRoleLabel(role, i18n),
      status: lineAnalysisStatusLabel(status, i18n),
      level: formatDrawingPrice(projectedPrice),
      distance: formatSignedDrawingPrice(distance),
      distancePct: formatDrawingRatioPercent(distancePct),
      tolerance: `±${formatDrawingPrice(tolerance)}`,
      touchCount: formatDrawingUnitCount(touchCount, "times", "次", i18n),
      lastTouch: lastTouchTime ?? "-",
    },
  };
}

export function zoneAnalysisRoleLabel(
  role: ChartDrawingZoneAnalysis["role"],
  i18n?: DrawingAnalysisI18n
) {
  switch (role) {
    case "support_zone":
      return translateDrawing(i18n, "zoneRole.supportZone", "支撐帶");
    case "resistance_zone":
      return translateDrawing(i18n, "zoneRole.resistanceZone", "壓力帶");
    case "range":
      return translateDrawing(i18n, "zoneRole.range", "區間內");
    default:
      return translateDrawing(i18n, "zoneRole.unknown", "未判定");
  }
}

export function zoneAnalysisStatusLabel(
  status: ChartDrawingZoneAnalysis["status"],
  i18n?: DrawingAnalysisI18n
) {
  switch (status) {
    case "inside_zone":
      return translateDrawing(i18n, "zoneStatus.insideZone", "區間內");
    case "above_zone":
      return translateDrawing(i18n, "zoneStatus.aboveZone", "站上區間");
    case "below_zone":
      return translateDrawing(i18n, "zoneStatus.belowZone", "跌破區間");
    case "breakout_up":
      return translateDrawing(i18n, "zoneStatus.breakoutUp", "向上突破");
    case "breakdown_down":
      return translateDrawing(i18n, "zoneStatus.breakdownDown", "向下跌破");
    case "testing_upper":
      return translateDrawing(i18n, "zoneStatus.testingUpper", "測試上緣");
    case "testing_lower":
      return translateDrawing(i18n, "zoneStatus.testingLower", "測試下緣");
    default:
      return translateDrawing(i18n, "zoneStatus.unknown", "資料不足");
  }
}

export function zoneCompressionLabel(
  state: ChartDrawingZoneAnalysis["compressionState"],
  i18n?: DrawingAnalysisI18n
) {
  switch (state) {
    case "compressing":
      return translateDrawing(i18n, "zoneCompression.compressing", "壓縮");
    case "expanding":
      return translateDrawing(i18n, "zoneCompression.expanding", "擴張");
    case "neutral":
      return translateDrawing(i18n, "zoneCompression.neutral", "一般");
    default:
      return translateDrawing(i18n, "zoneCompression.unknown", "不足");
  }
}

export function countBoundaryTouches(
  rows: ChartPoint[],
  price: number,
  tolerance: number
) {
  let count = 0;
  let inCluster = false;
  let lastTouchTime: string | null = null;

  rows.forEach((point) => {
    const touches = candleTouchesPrice(point, price, tolerance);

    if (touches) {
      if (!inCluster) {
        count += 1;
      }
      inCluster = true;
      lastTouchTime = point.time;
      return;
    }

    inCluster = false;
  });

  return { count, lastTouchTime };
}

export function buildZoneAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData: ChartPoint[] | undefined,
  i18n?: DrawingAnalysisI18n
): ChartDrawingZoneAnalysis | null {
  if (type !== "rectangle" && type !== "priceRange") return null;
  if (!chartData || chartData.length === 0) return null;

  const first = points[0] ?? null;
  const second = points[1] ?? null;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const previousPoint = chartData.length > 1 ? chartData[chartData.length - 2] : null;
  const latestPrice = pointClose(latestPoint);
  const previousPrice = pointClose(previousPoint);

  if (!first || !second || !latestPoint || !finiteNumber(latestPrice)) return null;

  const upperPrice = Math.max(first.price, second.price);
  const lowerPrice = Math.min(first.price, second.price);
  const width = upperPrice - lowerPrice;

  if (!Number.isFinite(width) || width <= 0) return null;

  const midPrice = (upperPrice + lowerPrice) / 2;
  const widthPct = lowerPrice !== 0 ? (width / lowerPrice) * 100 : null;
  const positionPct = ((latestPrice - lowerPrice) / width) * 100;
  const distanceToUpper = latestPrice - upperPrice;
  const distanceToLower = latestPrice - lowerPrice;
  const tolerance = estimateLineAnalysisTolerance(chartData, midPrice);
  const previousAbove = finiteNumber(previousPrice) ? previousPrice > upperPrice + tolerance : false;
  const previousBelow = finiteNumber(previousPrice) ? previousPrice < lowerPrice - tolerance : false;
  let status: ChartDrawingZoneAnalysis["status"] = "unknown";

  if (latestPrice > upperPrice + tolerance) {
    status = previousAbove ? "above_zone" : "breakout_up";
  } else if (latestPrice < lowerPrice - tolerance) {
    status = previousBelow ? "below_zone" : "breakdown_down";
  } else if (Math.abs(latestPrice - upperPrice) <= tolerance) {
    status = "testing_upper";
  } else if (Math.abs(latestPrice - lowerPrice) <= tolerance) {
    status = "testing_lower";
  } else {
    status = "inside_zone";
  }

  const role: ChartDrawingZoneAnalysis["role"] =
    status === "above_zone" || status === "breakout_up"
      ? "support_zone"
      : status === "below_zone" || status === "breakdown_down"
        ? "resistance_zone"
        : "range";
  const firstIndex = first ? timeIndex.get(first.time) : undefined;
  const secondIndex = second ? timeIndex.get(second.time) : undefined;
  const fromIndex =
    firstIndex !== undefined && secondIndex !== undefined
      ? Math.max(0, Math.min(firstIndex, secondIndex))
      : 0;
  const rowsForTouches = chartData.slice(fromIndex);
  const upperTouches = countBoundaryTouches(rowsForTouches, upperPrice, tolerance);
  const lowerTouches = countBoundaryTouches(rowsForTouches, lowerPrice, tolerance);
  const recentRows = chartData.slice(-20);
  const recentHigh = Math.max(
    ...recentRows.flatMap((point) => (finiteNumber(point.high) ? [point.high] : []))
  );
  const recentLow = Math.min(
    ...recentRows.flatMap((point) => (finiteNumber(point.low) ? [point.low] : []))
  );
  const recentRange =
    Number.isFinite(recentHigh) && Number.isFinite(recentLow) ? recentHigh - recentLow : null;
  const compressionRatio =
    finiteNumber(recentRange) && width > 0 ? Math.max(0, recentRange / width) : null;
  const compressionState: ChartDrawingZoneAnalysis["compressionState"] =
    status === "breakout_up" || status === "breakdown_down"
      ? "expanding"
      : !finiteNumber(compressionRatio)
        ? "unknown"
        : status === "inside_zone" && compressionRatio <= 0.35
          ? "compressing"
          : compressionRatio >= 0.85
            ? "expanding"
            : "neutral";

  return {
    version: 1,
    kind: type === "priceRange" ? "price_range" : "rectangle",
    role,
    status,
    upperPrice,
    lowerPrice,
    midPrice,
    latestPrice,
    latestTime: latestPoint.time,
    width,
    widthPct,
    positionPct,
    distanceToUpper,
    distanceToLower,
    tolerance,
    upperTouchCount: upperTouches.count,
    lowerTouchCount: lowerTouches.count,
    lastUpperTouchTime: upperTouches.lastTouchTime,
    lastLowerTouchTime: lowerTouches.lastTouchTime,
    compressionRatio,
    compressionState,
    labels: {
      role: zoneAnalysisRoleLabel(role, i18n),
      status: zoneAnalysisStatusLabel(status, i18n),
      upper: formatDrawingPrice(upperPrice),
      lower: formatDrawingPrice(lowerPrice),
      mid: formatDrawingPrice(midPrice),
      width: formatDrawingPrice(width),
      widthPct: formatDrawingRatioPercent(widthPct),
      position: formatDrawingRatioPercent(positionPct),
      distanceToUpper: formatSignedDrawingPrice(distanceToUpper),
      distanceToLower: formatSignedDrawingPrice(distanceToLower),
      tolerance: `±${formatDrawingPrice(tolerance)}`,
      upperTouches: formatDrawingUnitCount(upperTouches.count, "times", "次", i18n),
      lowerTouches: formatDrawingUnitCount(lowerTouches.count, "times", "次", i18n),
      compression: finiteNumber(compressionRatio)
        ? translateDrawing(i18n, "zoneCompression.withPercent", "{label} {percent}", {
            label: zoneCompressionLabel(compressionState, i18n),
            percent: formatDrawingPercent(compressionRatio * 100),
          })
        : zoneCompressionLabel(compressionState, i18n),
    },
  };
}

export function fibonacciTrendLabel(
  trend: ChartDrawingFibonacciAnalysis["trend"],
  i18n?: DrawingAnalysisI18n
) {
  switch (trend) {
    case "upswing":
      return translateDrawing(i18n, "fibonacciTrend.upswing", "上升波");
    case "downswing":
      return translateDrawing(i18n, "fibonacciTrend.downswing", "下降波");
    case "flat":
      return translateDrawing(i18n, "fibonacciTrend.flat", "橫向");
    default:
      return translateDrawing(i18n, "fibonacciTrend.unknown", "未判定");
  }
}

export function fibonacciStatusLabel(
  status: ChartDrawingFibonacciAnalysis["status"],
  i18n?: DrawingAnalysisI18n
) {
  switch (status) {
    case "inside_range":
      return translateDrawing(i18n, "fibonacciStatus.insideRange", "錨點區間內");
    case "above_anchor":
      return translateDrawing(i18n, "fibonacciStatus.aboveAnchor", "站上錨點");
    case "below_anchor":
      return translateDrawing(i18n, "fibonacciStatus.belowAnchor", "跌破錨點");
    case "near_level":
      return translateDrawing(i18n, "fibonacciStatus.nearLevel", "貼近位階");
    default:
      return translateDrawing(i18n, "fibonacciStatus.unknown", "資料不足");
  }
}

export function fibonacciLevelKind(ratio: number): ChartDrawingFibonacciLevel["kind"] {
  if (ratio === 0 || ratio === 1) return "anchor";
  if (ratio < 0 || ratio > 1) return "extension";

  return "retracement";
}

export function buildFibonacciAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  chartData: ChartPoint[] | undefined,
  i18n?: DrawingAnalysisI18n
): ChartDrawingFibonacciAnalysis | null {
  if (type !== "fibonacci") return null;
  if (!chartData || chartData.length === 0) return null;

  const first = points[0] ?? null;
  const second = points[1] ?? null;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const latestPrice = pointClose(latestPoint);

  if (!first || !second || !latestPoint || !finiteNumber(latestPrice)) return null;

  const priceDiff = second.price - first.price;
  const range = Math.abs(priceDiff);

  if (!Number.isFinite(range) || range <= 0) return null;

  const anchorHighPrice = Math.max(first.price, second.price);
  const anchorLowPrice = Math.min(first.price, second.price);
  const trend: ChartDrawingFibonacciAnalysis["trend"] =
    priceDiff > 0 ? "upswing" : priceDiff < 0 ? "downswing" : "flat";
  const tolerance = estimateLineAnalysisTolerance(chartData, latestPrice);
  const rawLevels = fibonacciAnalysisRatios.map((ratio) => {
    const price = first.price + priceDiff * ratio;
    const distance = latestPrice - price;
    const distancePct = price !== 0 ? (distance / price) * 100 : null;

    return {
      ratio,
      kind: fibonacciLevelKind(ratio),
      price,
      distance,
      distancePct,
    };
  });
  const nearestRaw = rawLevels.reduce<(typeof rawLevels)[number] | null>((nearest, level) => {
    if (!nearest) return level;

    return Math.abs(level.distance) < Math.abs(nearest.distance) ? level : nearest;
  }, null);
  const nearestRatio = nearestRaw?.ratio ?? null;
  const nearestDistance = nearestRaw?.distance ?? null;
  const nearestDistancePct = nearestRaw?.distancePct ?? null;
  const positionPct = (latestPrice - first.price) / priceDiff * 100;
  const rangePositionPct = (latestPrice - anchorLowPrice) / range * 100;
  const extensionPct =
    latestPrice > anchorHighPrice
      ? ((latestPrice - anchorHighPrice) / range) * 100
      : latestPrice < anchorLowPrice
        ? ((anchorLowPrice - latestPrice) / range) * 100
        : 0;
  const status: ChartDrawingFibonacciAnalysis["status"] =
    finiteNumber(nearestDistance) && Math.abs(nearestDistance) <= tolerance
      ? "near_level"
      : latestPrice > anchorHighPrice + tolerance
        ? "above_anchor"
        : latestPrice < anchorLowPrice - tolerance
          ? "below_anchor"
          : "inside_range";
  const levels: ChartDrawingFibonacciLevel[] = rawLevels.map((level) => ({
    ...level,
    isNearest: level.ratio === nearestRatio,
    label: formatFibonacciRatio(level.ratio),
    priceLabel: formatDrawingPrice(level.price),
    distanceLabel: formatSignedDrawingPrice(level.distance),
    distancePctLabel: formatDrawingRatioPercent(level.distancePct),
  }));
  const nearestLabel =
    nearestRaw === null
      ? "-"
      : `${formatFibonacciRatio(nearestRaw.ratio)} ${formatDrawingPrice(nearestRaw.price)}`;

  return {
    version: 1,
    trend,
    status,
    anchorStartPrice: first.price,
    anchorEndPrice: second.price,
    anchorHighPrice,
    anchorLowPrice,
    latestPrice,
    latestTime: latestPoint.time,
    range,
    positionPct,
    rangePositionPct,
    extensionPct,
    nearestRatio,
    nearestPrice: nearestRaw?.price ?? null,
    nearestDistance,
    nearestDistancePct,
    tolerance,
    levels,
    labels: {
      trend: fibonacciTrendLabel(trend, i18n),
      status: fibonacciStatusLabel(status, i18n),
      range: formatDrawingPrice(range),
      position: formatDrawingRatioPercent(positionPct),
      rangePosition: formatDrawingRatioPercent(rangePositionPct),
      extension: formatDrawingRatioPercent(extensionPct),
      nearest: nearestLabel,
      nearestDistance: finiteNumber(nearestDistance) ? formatSignedDrawingPrice(nearestDistance) : "-",
      nearestDistancePct: formatDrawingRatioPercent(nearestDistancePct),
      tolerance: `±${formatDrawingPrice(tolerance)}`,
    },
  };
}

export function chartPointTypicalPrice(point: ChartPoint) {
  if (finiteNumber(point.high) && finiteNumber(point.low) && finiteNumber(point.close)) {
    return (point.high + point.low + point.close) / 3;
  }

  return pointClose(point);
}

export function chartPointVolume(point: ChartPoint) {
  if (finiteNumber(point.volume) && point.volume > 0) return point.volume;
  if (finiteNumber(point.trade_value) && point.trade_value > 0) return point.trade_value;

  return null;
}

export function anchoredVwapStatusLabel(
  status: ChartDrawingAnchoredVwapAnalysis["status"],
  i18n?: DrawingAnalysisI18n
) {
  switch (status) {
    case "above_vwap":
      return translateDrawing(i18n, "anchoredVwapStatus.aboveVwap", "站上 VWAP");
    case "below_vwap":
      return translateDrawing(i18n, "anchoredVwapStatus.belowVwap", "跌破 VWAP");
    case "testing_vwap":
      return translateDrawing(i18n, "anchoredVwapStatus.testingVwap", "測試 VWAP");
    default:
      return translateDrawing(i18n, "anchoredVwapStatus.unknown", "資料不足");
  }
}

export function buildAnchoredVwapAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData: ChartPoint[] | undefined,
  i18n?: DrawingAnalysisI18n
): ChartDrawingAnchoredVwapAnalysis | null {
  if (type !== "anchorVwap") return null;
  if (!chartData || chartData.length === 0) return null;

  const anchor = points[0] ?? null;
  const anchorIndex = anchor ? timeIndex.get(anchor.time) : undefined;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const latestPrice = pointClose(latestPoint);

  if (!anchor || anchorIndex === undefined || !latestPoint || !finiteNumber(latestPrice)) {
    return null;
  }

  let cumulativeVolume = 0;
  let cumulativeTypicalValue = 0;
  let firstVwap: number | null = null;
  let latestVwap: number | null = null;
  let validBars = 0;

  for (let index = anchorIndex; index < chartData.length; index += 1) {
    const point = chartData[index];
    const typicalPrice = chartPointTypicalPrice(point);
    const volume = chartPointVolume(point);

    if (!finiteNumber(typicalPrice) || !finiteNumber(volume) || volume <= 0) continue;

    cumulativeVolume += volume;
    cumulativeTypicalValue += typicalPrice * volume;
    validBars += 1;
    latestVwap = cumulativeTypicalValue / cumulativeVolume;

    if (!finiteNumber(firstVwap)) {
      firstVwap = latestVwap;
    }
  }

  if (!finiteNumber(latestVwap) || cumulativeVolume <= 0 || validBars === 0) return null;

  const distance = latestPrice - latestVwap;
  const distancePct = latestVwap !== 0 ? (distance / latestVwap) * 100 : null;
  const vwapChange =
    finiteNumber(firstVwap) && finiteNumber(latestVwap) ? latestVwap - firstVwap : null;
  const vwapChangePct =
    finiteNumber(vwapChange) && finiteNumber(firstVwap) && firstVwap !== 0
      ? (vwapChange / firstVwap) * 100
      : null;
  const tolerance = estimateLineAnalysisTolerance(chartData.slice(anchorIndex), latestVwap);
  const status: ChartDrawingAnchoredVwapAnalysis["status"] =
    Math.abs(distance) <= tolerance
      ? "testing_vwap"
      : distance > 0
        ? "above_vwap"
        : "below_vwap";

  return {
    version: 1,
    anchorTime: anchor.time,
    anchorPrice: anchor.price,
    latestTime: latestPoint.time,
    latestPrice,
    latestVwap,
    firstVwap,
    distance,
    distancePct,
    vwapChange,
    vwapChangePct,
    barCount: validBars,
    cumulativeVolume,
    cumulativeTypicalValue,
    status,
    labels: {
      status: anchoredVwapStatusLabel(status, i18n),
      vwap: formatDrawingPrice(latestVwap),
      distance: formatSignedDrawingPrice(distance),
      distancePct: formatDrawingRatioPercent(distancePct),
      vwapChange: finiteNumber(vwapChange) ? formatSignedDrawingPrice(vwapChange) : "-",
      vwapChangePct: formatDrawingRatioPercent(vwapChangePct),
      barCount: formatDrawingUnitCount(validBars, "bars", "根", i18n),
      cumulativeVolume: formatCompactVolume(cumulativeVolume, i18n),
    },
  };
}

export function volumeProfilePositionLabel(
  position: ChartDrawingVolumeProfileAnalysis["latestPosition"],
  i18n?: DrawingAnalysisI18n
) {
  switch (position) {
    case "above_value_area":
      return translateDrawing(i18n, "volumeProfilePosition.aboveValueArea", "價值區上方");
    case "inside_value_area":
      return translateDrawing(i18n, "volumeProfilePosition.insideValueArea", "價值區內");
    case "below_value_area":
      return translateDrawing(i18n, "volumeProfilePosition.belowValueArea", "價值區下方");
    default:
      return translateDrawing(i18n, "volumeProfilePosition.unknown", "資料不足");
  }
}

export function buildVolumeProfileAnalysis(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData: ChartPoint[] | undefined,
  i18n?: DrawingAnalysisI18n
): ChartDrawingVolumeProfileAnalysis | null {
  if (type !== "volumeProfileRange") return null;
  if (!chartData || chartData.length === 0) return null;

  const first = points[0] ?? null;
  const second = points[1] ?? null;
  const firstIndex = first ? timeIndex.get(first.time) : undefined;
  const secondIndex = second ? timeIndex.get(second.time) : undefined;
  const latestPoint = chartData[chartData.length - 1] ?? null;
  const latestPrice = pointClose(latestPoint);

  if (!first || !second || firstIndex === undefined || secondIndex === undefined) return null;

  const fromIndex = Math.max(0, Math.min(firstIndex, secondIndex));
  const toIndex = Math.min(chartData.length - 1, Math.max(firstIndex, secondIndex));
  const priceHigh = Math.max(first.price, second.price);
  const priceLow = Math.min(first.price, second.price);
  const priceRange = priceHigh - priceLow;

  if (!Number.isFinite(priceRange) || priceRange <= 0) return null;

  const rowCount = drawingVolumeProfileRows;
  const binSize = priceRange / rowCount;
  const bins = Array.from({ length: rowCount }, (_, index) => ({
    index,
    buyVolume: 0,
    sellVolume: 0,
    totalVolume: 0,
  }));

  for (let index = fromIndex; index <= toIndex; index += 1) {
    const point = chartData[index];
    const volume = chartPointVolume(point);

    if (
      !finiteNumber(volume) ||
      volume <= 0 ||
      !finiteNumber(point.open) ||
      !finiteNumber(point.close) ||
      !finiteNumber(point.high) ||
      !finiteNumber(point.low)
    ) {
      continue;
    }

    const overlapLow = Math.max(point.low, priceLow);
    const overlapHigh = Math.min(point.high, priceHigh);

    if (overlapHigh < overlapLow) continue;

    const startBin = Math.max(
      0,
      Math.min(rowCount - 1, Math.floor((overlapLow - priceLow) / binSize))
    );
    const endBin = Math.max(
      startBin,
      Math.min(rowCount - 1, Math.floor((overlapHigh - priceLow) / binSize))
    );
    const share = volume / (endBin - startBin + 1);
    const side = point.close >= point.open ? "buyVolume" : "sellVolume";

    for (let binIndex = startBin; binIndex <= endBin; binIndex += 1) {
      bins[binIndex][side] += share;
      bins[binIndex].totalVolume += share;
    }
  }

  const totalVolume = bins.reduce((sum, bin) => sum + bin.totalVolume, 0);

  if (!Number.isFinite(totalVolume) || totalVolume <= 0) return null;

  const buyVolume = bins.reduce((sum, bin) => sum + bin.buyVolume, 0);
  const sellVolume = bins.reduce((sum, bin) => sum + bin.sellVolume, 0);
  const pocBin = bins.reduce((best, bin) => (bin.totalVolume > best.totalVolume ? bin : best), bins[0]);
  let valueAreaLowIndex = pocBin.index;
  let valueAreaHighIndex = pocBin.index;
  let valueAreaVolume = pocBin.totalVolume;
  const targetVolume = totalVolume * (drawingValueAreaTargetPct / 100);

  while (
    valueAreaVolume < targetVolume &&
    (valueAreaLowIndex > 0 || valueAreaHighIndex < rowCount - 1)
  ) {
    const nextLower = valueAreaLowIndex > 0 ? bins[valueAreaLowIndex - 1] : null;
    const nextUpper = valueAreaHighIndex < rowCount - 1 ? bins[valueAreaHighIndex + 1] : null;
    const lowerVolume = nextLower?.totalVolume ?? -1;
    const upperVolume = nextUpper?.totalVolume ?? -1;

    if (upperVolume >= lowerVolume && nextUpper) {
      valueAreaHighIndex += 1;
      valueAreaVolume += nextUpper.totalVolume;
    } else if (nextLower) {
      valueAreaLowIndex -= 1;
      valueAreaVolume += nextLower.totalVolume;
    } else {
      break;
    }
  }

  const valueAreaLow = priceLow + valueAreaLowIndex * binSize;
  const valueAreaHigh = priceLow + (valueAreaHighIndex + 1) * binSize;
  const valueAreaVolumePct = (valueAreaVolume / totalVolume) * 100;
  const pocPrice = priceLow + (pocBin.index + 0.5) * binSize;
  const latestPosition: ChartDrawingVolumeProfileAnalysis["latestPosition"] =
    !finiteNumber(latestPrice)
      ? "unknown"
      : latestPrice > valueAreaHigh
        ? "above_value_area"
        : latestPrice < valueAreaLow
          ? "below_value_area"
          : "inside_value_area";
  const imbalancePct = totalVolume > 0 ? ((buyVolume - sellVolume) / totalVolume) * 100 : null;
  const levels: ChartDrawingVolumeProfileLevel[] = bins.map((bin) => {
    const priceMin = priceLow + bin.index * binSize;
    const priceMax = priceMin + binSize;
    const centerPrice = (priceMin + priceMax) / 2;

    return {
      index: bin.index,
      priceMin,
      priceMax,
      centerPrice,
      buyVolume: bin.buyVolume,
      sellVolume: bin.sellVolume,
      totalVolume: bin.totalVolume,
      totalPct: (bin.totalVolume / totalVolume) * 100,
      inValueArea: bin.index >= valueAreaLowIndex && bin.index <= valueAreaHighIndex,
      isPoc: bin.index === pocBin.index,
      label: formatDrawingPrice(centerPrice),
      volumeLabel: formatCompactVolume(bin.totalVolume, i18n),
    };
  });

  return {
    version: 1,
    rowCount,
    startTime: chartData[fromIndex]?.time ?? first.time,
    endTime: chartData[toIndex]?.time ?? second.time,
    priceHigh,
    priceLow,
    totalVolume,
    buyVolume,
    sellVolume,
    pocPrice,
    pocVolume: pocBin.totalVolume,
    valueAreaHigh,
    valueAreaLow,
    valueAreaVolumePct,
    latestPrice: latestPrice ?? null,
    latestPosition,
    imbalancePct,
    levels,
    labels: {
      totalVolume: formatCompactVolume(totalVolume, i18n),
      poc: `${formatDrawingPrice(pocPrice)} / ${formatCompactVolume(pocBin.totalVolume, i18n)}`,
      valueArea: `${formatDrawingPrice(valueAreaLow)} - ${formatDrawingPrice(valueAreaHigh)}`,
      valueAreaVolumePct: formatDrawingRatioPercent(valueAreaVolumePct),
      latestPosition: volumeProfilePositionLabel(latestPosition, i18n),
      imbalance: formatDrawingRatioPercent(imbalancePct),
    },
  };
}

export function buildDrawingDerivedMetrics(
  type: ChartDrawing["type"],
  points: ChartDrawingPoint[],
  timeIndex: Map<string, number>,
  chartData?: ChartPoint[],
  i18n?: DrawingAnalysisI18n
): ChartDrawingDerivedMetrics {
  const first = points[0] ?? null;
  const second = points[1] ?? first;
  const anchorCount =
    type === "horizontal" || type === "anchorVwap"
      ? Math.min(points.length, 1)
      : type === "riskReward"
        ? Math.min(points.length, 3)
      : Math.min(points.length, 2);
  const startPrice = first?.price ?? null;
  const endPrice = second?.price ?? null;
  const priceDiff =
    finiteNumber(startPrice) &&
    finiteNumber(endPrice) &&
    type !== "horizontal" &&
    type !== "anchorVwap"
      ? endPrice - startPrice
      : null;
  const priceDiffAbs = finiteNumber(priceDiff) ? Math.abs(priceDiff) : null;
  const percentChange =
    finiteNumber(priceDiff) && finiteNumber(startPrice) && startPrice !== 0
      ? (priceDiff / startPrice) * 100
      : null;
  const highPrice =
    finiteNumber(startPrice) && finiteNumber(endPrice)
      ? Math.max(startPrice, endPrice)
      : startPrice ?? endPrice ?? null;
  const lowPrice =
    finiteNumber(startPrice) && finiteNumber(endPrice)
      ? Math.min(startPrice, endPrice)
      : startPrice ?? endPrice ?? null;
  const midPrice =
    finiteNumber(highPrice) && finiteNumber(lowPrice) ? (highPrice + lowPrice) / 2 : null;
  const rangePct =
    finiteNumber(highPrice) && finiteNumber(lowPrice) && lowPrice !== 0
      ? ((highPrice - lowPrice) / lowPrice) * 100
      : null;
  const firstIndex = first ? timeIndex.get(first.time) : undefined;
  const secondIndex = second ? timeIndex.get(second.time) : undefined;
  const barCount =
    firstIndex !== undefined &&
    secondIndex !== undefined &&
    type !== "horizontal" &&
    type !== "anchorVwap"
      ? Math.abs(secondIndex - firstIndex)
      : null;
  const startTimeMs = first ? parseDrawingTimeMs(first.time) : null;
  const endTimeMs = second ? parseDrawingTimeMs(second.time) : null;
  const durationMinutes =
    finiteNumber(startTimeMs) &&
    finiteNumber(endTimeMs) &&
    type !== "horizontal" &&
    type !== "anchorVwap"
      ? Math.abs(endTimeMs - startTimeMs) / 60000
      : null;
  const durationDays = finiteNumber(durationMinutes) ? durationMinutes / 1440 : null;
  const slopePerBar =
    finiteNumber(priceDiff) && finiteNumber(barCount) && barCount > 0
      ? priceDiff / barCount
      : null;
  const slopePctPerBar =
    finiteNumber(percentChange) && finiteNumber(barCount) && barCount > 0
      ? percentChange / barCount
      : null;
  const direction =
    !finiteNumber(priceDiff) ? "unknown" : priceDiff > 0 ? "up" : priceDiff < 0 ? "down" : "flat";
  const durationLabel = formatDurationLabel(durationDays, durationMinutes, i18n);
  const lineAnalysis = buildLineAnalysis(type, points, timeIndex, chartData, i18n);
  const zoneAnalysis = buildZoneAnalysis(type, points, timeIndex, chartData, i18n);
  const fibonacciAnalysis = buildFibonacciAnalysis(type, points, chartData, i18n);
  const anchoredVwapAnalysis = buildAnchoredVwapAnalysis(type, points, timeIndex, chartData, i18n);
  const volumeProfileAnalysis = buildVolumeProfileAnalysis(type, points, timeIndex, chartData, i18n);

  return {
    version: 1,
    anchorCount,
    startTime: first?.time ?? null,
    endTime: second?.time ?? null,
    startPrice,
    endPrice,
    highPrice,
    lowPrice,
    midPrice,
    priceDiff,
    priceDiffAbs,
    percentChange,
    rangePct,
    barCount,
    durationDays,
    durationMinutes,
    slopePerBar,
    slopePctPerBar,
    direction,
    lineAnalysis,
    zoneAnalysis,
    fibonacciAnalysis,
    anchoredVwapAnalysis,
    volumeProfileAnalysis,
    labels: {
      priceDiff: finiteNumber(priceDiff) ? formatSignedDrawingPrice(priceDiff) : "-",
      percentChange: formatDrawingRatioPercent(percentChange),
      rangePct: formatDrawingRatioPercent(rangePct),
      bars: barCount === null ? null : formatDrawingUnitCount(barCount, "bars", "根", i18n),
      duration: durationLabel,
      high: finiteNumber(highPrice) ? formatDrawingPrice(highPrice) : "-",
      low: finiteNumber(lowPrice) ? formatDrawingPrice(lowPrice) : "-",
      mid: finiteNumber(midPrice) ? formatDrawingPrice(midPrice) : "-",
      slope:
        finiteNumber(slopePerBar) && finiteNumber(slopePctPerBar)
          ? translateDrawing(i18n, "units.slopePerBar", "{price} / 根 ({percent} / 根)", {
              price: formatSignedDrawingPrice(slopePerBar),
              percent: formatDrawingPercent(slopePctPerBar),
            })
          : null,
    },
  };
}

export function drawingTypeLabel(type: ChartDrawing["type"], i18n?: DrawingAnalysisI18n) {
  switch (type) {
    case "horizontal":
      return translateDrawing(i18n, "drawingTypes.horizontal", "水平線");
    case "trend":
      return translateDrawing(i18n, "drawingTypes.trend", "趨勢線");
    case "ray":
      return translateDrawing(i18n, "drawingTypes.ray", "射線");
    case "rectangle":
      return translateDrawing(i18n, "drawingTypes.rectangle", "區間框");
    case "fibonacci":
      return "Fib";
    case "anchorVwap":
      return "Anchored VWAP";
    case "volumeProfileRange":
      return "VP Range";
    case "measure":
      return translateDrawing(i18n, "drawingTypes.measure", "量測");
    case "priceRange":
      return translateDrawing(i18n, "drawingTypes.priceRange", "價幅");
    case "riskReward":
      return translateDrawing(i18n, "drawingTypes.riskReward", "上下限");
    default:
      return translateDrawing(i18n, "drawingTypes.default", "畫線");
  }
}

export function buildDrawingOmiSummary(
  drawing: Pick<ChartDrawing, "type" | "points">,
  metrics: ChartDrawingDerivedMetrics,
  context: ChartDrawingContext,
  i18n?: DrawingAnalysisI18n
): ChartDrawingOmiSummary {
  const typeLabel = drawingTypeLabel(drawing.type, i18n);
  const subject =
    context.symbol
      ? `${context.symbol}`
      : context.label ?? translateDrawing(i18n, "summary.defaultSubject", "目前標的");
  const separator = translateDrawing(i18n, "summary.separator", "，");
  const tags = [drawing.type, metrics.direction, context.timeframe ?? null].filter(
    (value): value is string => Boolean(value)
  );
  if (metrics.lineAnalysis?.role && metrics.lineAnalysis.role !== "unknown") {
    tags.push(metrics.lineAnalysis.role);
  }
  if (metrics.lineAnalysis?.status && metrics.lineAnalysis.status !== "unknown") {
    tags.push(metrics.lineAnalysis.status);
  }
  if (metrics.zoneAnalysis?.role && metrics.zoneAnalysis.role !== "unknown") {
    tags.push(metrics.zoneAnalysis.role);
  }
  if (metrics.zoneAnalysis?.status && metrics.zoneAnalysis.status !== "unknown") {
    tags.push(metrics.zoneAnalysis.status);
  }
  if (metrics.fibonacciAnalysis?.trend && metrics.fibonacciAnalysis.trend !== "unknown") {
    tags.push(metrics.fibonacciAnalysis.trend);
  }
  if (metrics.fibonacciAnalysis?.status && metrics.fibonacciAnalysis.status !== "unknown") {
    tags.push(metrics.fibonacciAnalysis.status);
  }
  if (metrics.anchoredVwapAnalysis?.status && metrics.anchoredVwapAnalysis.status !== "unknown") {
    tags.push(metrics.anchoredVwapAnalysis.status);
  }
  if (
    metrics.volumeProfileAnalysis?.latestPosition &&
    metrics.volumeProfileAnalysis.latestPosition !== "unknown"
  ) {
    tags.push(metrics.volumeProfileAnalysis.latestPosition);
  }
  const textParts = [
    `${subject} ${typeLabel}`,
    metrics.startTime && metrics.endTime && metrics.startTime !== metrics.endTime
      ? translateDrawing(i18n, "summary.range", "{start} 到 {end}", {
          start: metrics.startTime,
          end: metrics.endTime,
        })
      : metrics.startTime ?? null,
    finiteNumber(metrics.priceDiff)
      ? `${metrics.labels.priceDiff} / ${metrics.labels.percentChange}`
      : null,
    metrics.labels.bars,
    metrics.labels.duration,
    metrics.lineAnalysis
      ? translateDrawing(i18n, "summary.lineDetail", "{role}，{status}，距線 {distancePct}", {
          role: metrics.lineAnalysis.labels.role,
          status: metrics.lineAnalysis.labels.status,
          distancePct: metrics.lineAnalysis.labels.distancePct,
        })
      : null,
    metrics.zoneAnalysis
      ? translateDrawing(i18n, "summary.zoneDetail", "{role}，{status}，區間位置 {position}", {
          role: metrics.zoneAnalysis.labels.role,
          status: metrics.zoneAnalysis.labels.status,
          position: metrics.zoneAnalysis.labels.position,
        })
      : null,
    metrics.fibonacciAnalysis
      ? translateDrawing(
          i18n,
          "summary.fibonacciDetail",
          "{trend}，{status}，最近 {nearest}，距離 {distancePct}",
          {
            trend: metrics.fibonacciAnalysis.labels.trend,
            status: metrics.fibonacciAnalysis.labels.status,
            nearest: metrics.fibonacciAnalysis.labels.nearest,
            distancePct: metrics.fibonacciAnalysis.labels.nearestDistancePct,
          }
        )
      : null,
    metrics.anchoredVwapAnalysis
      ? translateDrawing(
          i18n,
          "summary.anchoredVwapDetail",
          "{status}，VWAP {vwap}，距離 {distancePct}",
          {
            status: metrics.anchoredVwapAnalysis.labels.status,
            vwap: metrics.anchoredVwapAnalysis.labels.vwap,
            distancePct: metrics.anchoredVwapAnalysis.labels.distancePct,
          }
        )
      : null,
    metrics.volumeProfileAnalysis
      ? translateDrawing(
          i18n,
          "summary.volumeProfileDetail",
          "POC {poc}，VA {valueArea}，現價 {position}",
          {
            poc: metrics.volumeProfileAnalysis.labels.poc,
            valueArea: metrics.volumeProfileAnalysis.labels.valueArea,
            position: metrics.volumeProfileAnalysis.labels.latestPosition,
          }
        )
      : null,
  ].filter((value): value is string => Boolean(value));
  const directionLabel =
    metrics.direction === "up"
      ? translateDrawing(i18n, "summary.directionUp", "上行")
      : metrics.direction === "down"
        ? translateDrawing(i18n, "summary.directionDown", "下行")
        : translateDrawing(i18n, "summary.directionData", "資料");

  return {
    title: translateDrawing(i18n, "summary.title", "{type} {direction}", {
      type: typeLabel,
      direction: directionLabel,
    }),
    text: textParts.join(separator),
    tags,
    facts: {
      symbol: context.symbol ?? null,
      market: context.market ?? null,
      timeframe: context.timeframe ?? null,
      type: drawing.type,
      direction: metrics.direction,
      startTime: metrics.startTime,
      endTime: metrics.endTime,
      startPrice: metrics.startPrice,
      endPrice: metrics.endPrice,
      highPrice: metrics.highPrice,
      lowPrice: metrics.lowPrice,
      priceDiff: metrics.priceDiff,
      percentChange: metrics.percentChange,
      rangePct: metrics.rangePct,
      barCount: metrics.barCount,
      durationDays: metrics.durationDays,
      slopePerBar: metrics.slopePerBar,
      slopePctPerBar: metrics.slopePctPerBar,
      lineRole: metrics.lineAnalysis?.role ?? null,
      lineStatus: metrics.lineAnalysis?.status ?? null,
      lineProjectedPrice: metrics.lineAnalysis?.projectedPrice ?? null,
      lineDistance: metrics.lineAnalysis?.distance ?? null,
      lineDistancePct: metrics.lineAnalysis?.distancePct ?? null,
      lineTouchCount: metrics.lineAnalysis?.touchCount ?? null,
      lineLastTouchTime: metrics.lineAnalysis?.lastTouchTime ?? null,
      lineLastCrossTime: metrics.lineAnalysis?.lastCrossTime ?? null,
      zoneRole: metrics.zoneAnalysis?.role ?? null,
      zoneStatus: metrics.zoneAnalysis?.status ?? null,
      zoneUpperPrice: metrics.zoneAnalysis?.upperPrice ?? null,
      zoneLowerPrice: metrics.zoneAnalysis?.lowerPrice ?? null,
      zoneMidPrice: metrics.zoneAnalysis?.midPrice ?? null,
      zoneWidth: metrics.zoneAnalysis?.width ?? null,
      zoneWidthPct: metrics.zoneAnalysis?.widthPct ?? null,
      zonePositionPct: metrics.zoneAnalysis?.positionPct ?? null,
      zoneDistanceToUpper: metrics.zoneAnalysis?.distanceToUpper ?? null,
      zoneDistanceToLower: metrics.zoneAnalysis?.distanceToLower ?? null,
      zoneTolerance: metrics.zoneAnalysis?.tolerance ?? null,
      zoneUpperTouchCount: metrics.zoneAnalysis?.upperTouchCount ?? null,
      zoneLowerTouchCount: metrics.zoneAnalysis?.lowerTouchCount ?? null,
      zoneLastUpperTouchTime: metrics.zoneAnalysis?.lastUpperTouchTime ?? null,
      zoneLastLowerTouchTime: metrics.zoneAnalysis?.lastLowerTouchTime ?? null,
      zoneCompressionRatio: metrics.zoneAnalysis?.compressionRatio ?? null,
      zoneCompressionState: metrics.zoneAnalysis?.compressionState ?? null,
      fibTrend: metrics.fibonacciAnalysis?.trend ?? null,
      fibStatus: metrics.fibonacciAnalysis?.status ?? null,
      fibAnchorStartPrice: metrics.fibonacciAnalysis?.anchorStartPrice ?? null,
      fibAnchorEndPrice: metrics.fibonacciAnalysis?.anchorEndPrice ?? null,
      fibAnchorHighPrice: metrics.fibonacciAnalysis?.anchorHighPrice ?? null,
      fibAnchorLowPrice: metrics.fibonacciAnalysis?.anchorLowPrice ?? null,
      fibRange: metrics.fibonacciAnalysis?.range ?? null,
      fibPositionPct: metrics.fibonacciAnalysis?.positionPct ?? null,
      fibRangePositionPct: metrics.fibonacciAnalysis?.rangePositionPct ?? null,
      fibExtensionPct: metrics.fibonacciAnalysis?.extensionPct ?? null,
      fibNearestRatio: metrics.fibonacciAnalysis?.nearestRatio ?? null,
      fibNearestPrice: metrics.fibonacciAnalysis?.nearestPrice ?? null,
      fibNearestDistance: metrics.fibonacciAnalysis?.nearestDistance ?? null,
      fibNearestDistancePct: metrics.fibonacciAnalysis?.nearestDistancePct ?? null,
      fibTolerance: metrics.fibonacciAnalysis?.tolerance ?? null,
      fibLevels:
        metrics.fibonacciAnalysis?.levels
          .map((level) => `${level.label}:${level.priceLabel}`)
          .join("; ") ?? null,
      anchoredVwapAnchorTime: metrics.anchoredVwapAnalysis?.anchorTime ?? null,
      anchoredVwapAnchorPrice: metrics.anchoredVwapAnalysis?.anchorPrice ?? null,
      anchoredVwapLatestVwap: metrics.anchoredVwapAnalysis?.latestVwap ?? null,
      anchoredVwapDistance: metrics.anchoredVwapAnalysis?.distance ?? null,
      anchoredVwapDistancePct: metrics.anchoredVwapAnalysis?.distancePct ?? null,
      anchoredVwapChange: metrics.anchoredVwapAnalysis?.vwapChange ?? null,
      anchoredVwapChangePct: metrics.anchoredVwapAnalysis?.vwapChangePct ?? null,
      anchoredVwapBarCount: metrics.anchoredVwapAnalysis?.barCount ?? null,
      anchoredVwapCumulativeVolume: metrics.anchoredVwapAnalysis?.cumulativeVolume ?? null,
      anchoredVwapStatus: metrics.anchoredVwapAnalysis?.status ?? null,
      vpStartTime: metrics.volumeProfileAnalysis?.startTime ?? null,
      vpEndTime: metrics.volumeProfileAnalysis?.endTime ?? null,
      vpPriceHigh: metrics.volumeProfileAnalysis?.priceHigh ?? null,
      vpPriceLow: metrics.volumeProfileAnalysis?.priceLow ?? null,
      vpTotalVolume: metrics.volumeProfileAnalysis?.totalVolume ?? null,
      vpBuyVolume: metrics.volumeProfileAnalysis?.buyVolume ?? null,
      vpSellVolume: metrics.volumeProfileAnalysis?.sellVolume ?? null,
      vpPocPrice: metrics.volumeProfileAnalysis?.pocPrice ?? null,
      vpPocVolume: metrics.volumeProfileAnalysis?.pocVolume ?? null,
      vpValueAreaHigh: metrics.volumeProfileAnalysis?.valueAreaHigh ?? null,
      vpValueAreaLow: metrics.volumeProfileAnalysis?.valueAreaLow ?? null,
      vpValueAreaVolumePct: metrics.volumeProfileAnalysis?.valueAreaVolumePct ?? null,
      vpLatestPosition: metrics.volumeProfileAnalysis?.latestPosition ?? null,
      vpImbalancePct: metrics.volumeProfileAnalysis?.imbalancePct ?? null,
      vpTopLevels:
        metrics.volumeProfileAnalysis?.levels
          .filter((level) => level.totalVolume > 0)
          .toSorted((left, right) => right.totalVolume - left.totalVolume)
          .slice(0, 5)
          .map((level) => `${level.label}:${level.volumeLabel}`)
          .join("; ") ?? null,
    },
  };
}

export function attachDrawingAnalytics(
  drawing: ChartDrawing,
  timeIndex: Map<string, number>,
  context: ChartDrawingContext,
  chartData?: ChartPoint[],
  i18n?: DrawingAnalysisI18n
): ChartDrawing {
  const derivedMetrics = buildDrawingDerivedMetrics(
    drawing.type,
    drawing.points,
    timeIndex,
    chartData,
    i18n
  );
  const nextContext: ChartDrawingContext = {
    ...drawing.context,
    ...context,
    updatedAt: new Date().toISOString(),
  };

  return {
    ...drawing,
    context: nextContext,
    derivedMetrics,
    omiSummary: buildDrawingOmiSummary(drawing, derivedMetrics, nextContext, i18n),
  };
}

export function measurementStatsFromMetrics(metrics: ChartDrawingDerivedMetrics): ProjectedMeasurementStats {
  return {
    tone:
      metrics.direction === "up" ? "up" : metrics.direction === "down" ? "down" : "flat",
    priceDiffLabel: metrics.labels.priceDiff,
    percentLabel: metrics.labels.percentChange,
    barsLabel: metrics.labels.bars,
    highLabel: metrics.labels.high,
    lowLabel: metrics.labels.low,
  };
}

export function buildMeasurementStats(
  first: ChartDrawingPoint,
  second: ChartDrawingPoint,
  timeIndex: Map<string, number>,
  i18n?: DrawingAnalysisI18n
): ProjectedMeasurementStats {
  return measurementStatsFromMetrics(
    buildDrawingDerivedMetrics("measure", [first, second], timeIndex, undefined, i18n)
  );
}

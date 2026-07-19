import { omiChartColors } from "@/lib/themeColors";
import {
  formatDrawingPrice,
  riskRewardMinimumPriceGap,
  type ChartDrawing,
  type DrawingAnchor,
  type DrawingCoordinate,
  type ProjectedDrawing,
  type ProjectedFibonacciLevel,
  type DrawingDragState,
} from "@/components/chart/lightweight-chart/drawingModel";

export function extendRayToViewport(
  first: DrawingCoordinate,
  second: DrawingCoordinate,
  width: number,
  height: number
): [DrawingCoordinate, DrawingCoordinate] {
  const viewportWidth = Math.max(width, 1);
  const viewportHeight = Math.max(height, 1);

  if (Math.abs(second.x - first.x) < 0.001) {
    return [
      first,
      { x: first.x, y: second.y >= first.y ? viewportHeight : 0 },
    ];
  }

  const slope = (second.y - first.y) / (second.x - first.x);
  const targetX = second.x >= first.x ? viewportWidth : 0;

  return [
    first,
    { x: targetX, y: first.y + (targetX - first.x) * slope },
  ];
}

export function rectangleBounds(
  points: readonly [DrawingCoordinate, DrawingCoordinate, ...DrawingCoordinate[]]
) {
  const xValues = points.map((point) => point.x);
  const yValues = points.map((point) => point.y);
  const minX = Math.min(...xValues);
  const maxX = Math.max(...xValues);
  const minY = Math.min(...yValues);
  const maxY = Math.max(...yValues);

  return {
    x: minX,
    y: minY,
    width: Math.abs(maxX - minX),
    height: Math.abs(maxY - minY),
  };
}

export function coordinateDistance(first: DrawingCoordinate, second: DrawingCoordinate) {
  return Math.hypot(first.x - second.x, first.y - second.y);
}

export function distanceToSegment(
  point: DrawingCoordinate,
  first: DrawingCoordinate,
  second: DrawingCoordinate
) {
  const dx = second.x - first.x;
  const dy = second.y - first.y;
  const lengthSquare = dx * dx + dy * dy;

  if (lengthSquare < 0.001) return coordinateDistance(point, first);

  const ratio = Math.max(
    0,
    Math.min(1, ((point.x - first.x) * dx + (point.y - first.y) * dy) / lengthSquare)
  );
  const projection = {
    x: first.x + ratio * dx,
    y: first.y + ratio * dy,
  };

  return coordinateDistance(point, projection);
}

export function expandedRectangleContains(
  point: DrawingCoordinate,
  bounds: ReturnType<typeof rectangleBounds>,
  padding: number
) {
  return (
    point.x >= bounds.x - padding &&
    point.x <= bounds.x + bounds.width + padding &&
    point.y >= bounds.y - padding &&
    point.y <= bounds.y + bounds.height + padding
  );
}

export function isProjectedDrawingHit(
  point: DrawingCoordinate,
  projectedDrawing: ProjectedDrawing,
  padding = 9
) {
  const points = projectedDrawing.anchorPoints ?? projectedDrawing.points;

  if (
    projectedDrawing.drawing.type === "rectangle" ||
    projectedDrawing.drawing.type === "priceRange" ||
    projectedDrawing.drawing.type === "volumeProfileRange"
  ) {
    return expandedRectangleContains(point, rectangleBounds(points), padding);
  }

  if (projectedDrawing.drawing.type === "riskReward") {
    const entry = points[0];
    const target = points[1];
    const stop = points[2];

    if (!entry || !target || !stop) return false;

    if (expandedRectangleContains(point, rectangleBounds(points), padding)) return true;

    const left = Math.min(entry.x, target.x, stop.x);
    const right = Math.max(entry.x, target.x, stop.x);
    const insideWidth = point.x >= left - padding && point.x <= right + padding;

    if (!insideWidth) return false;

    return (
      Math.abs(point.y - entry.y) <= padding ||
      Math.abs(point.y - target.y) <= padding ||
      Math.abs(point.y - stop.y) <= padding
    );
  }

  if (projectedDrawing.drawing.type === "anchorVwap") {
    if (coordinateDistance(point, points[0]) <= padding + 3) return true;

    const line = projectedDrawing.anchoredVwapLine ?? [];

    for (let index = 1; index < line.length; index += 1) {
      if (distanceToSegment(point, line[index - 1], line[index]) <= padding) return true;
    }

    return false;
  }

  if (projectedDrawing.drawing.type === "fibonacci" && projectedDrawing.fibonacciLevels) {
    const bounds = rectangleBounds(points);
    const insideHorizontalRange =
      point.x >= bounds.x - padding && point.x <= bounds.x + bounds.width + padding;

    return (
      insideHorizontalRange &&
      projectedDrawing.fibonacciLevels.some((level) => Math.abs(point.y - level.y) <= padding)
    );
  }

  return distanceToSegment(point, projectedDrawing.points[0], projectedDrawing.points[1]) <= padding;
}

export function lockCoordinateToNearestAngle(
  origin: DrawingCoordinate,
  current: DrawingCoordinate
): DrawingCoordinate {
  const dx = current.x - origin.x;
  const dy = current.y - origin.y;
  const distance = Math.hypot(dx, dy);

  if (distance < 0.001) return current;

  const angleStep = Math.PI / 4;
  const snappedAngle = Math.round(Math.atan2(dy, dx) / angleStep) * angleStep;

  return {
    x: origin.x + Math.cos(snappedAngle) * distance,
    y: origin.y + Math.sin(snappedAngle) * distance,
  };
}

export const fibonacciRatios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
export const fibonacciAnalysisRatios = [-0.618, -0.272, ...fibonacciRatios, 1.272, 1.618] as const;
export const drawingVolumeProfileRows = 24;
export const drawingValueAreaTargetPct = 70;
export const selectedDrawingColor = omiChartColors.marketUp;
export const hoveredDrawingColor = omiChartColors.info;
export const drawingHandleBorderColor = omiChartColors.surface;

export function formatFibonacciRatio(ratio: number) {
  if (ratio === 0 || ratio === 1) return `${ratio * 100}%`;
  if (ratio === 0.5) return "50%";

  return `${(ratio * 100).toFixed(1)}%`;
}

export function buildFibonacciLevels(
  first: DrawingCoordinate,
  second: DrawingCoordinate,
  firstPrice: number,
  secondPrice: number
): ProjectedFibonacciLevel[] {
  return fibonacciRatios.map((ratio) => {
    const y = first.y + (second.y - first.y) * ratio;
    const price = firstPrice + (secondPrice - firstPrice) * ratio;

    return {
      ratio,
      y,
      label: formatFibonacciRatio(ratio),
      priceLabel: formatDrawingPrice(price),
    };
  });
}

export function applyDrawingDragToDrawings(
  sourceDrawings: ChartDrawing[],
  dragState: DrawingDragState,
  anchor: DrawingAnchor
) {
  return sourceDrawings.map((drawing) => {
    if (drawing.id !== dragState.drawingId) return drawing;

    if (drawing.type === "horizontal" || dragState.mode === "horizontal") {
      const basePoint = drawing.points[0] ?? anchor;

      return {
        ...drawing,
        points: [
          {
            time: basePoint.time,
            price: anchor.price,
            logical: basePoint.logical,
          },
        ],
      };
    }

    if (drawing.type === "riskReward") {
      const points = drawing.points.slice(0, 3);
      const pointIndex = dragState.pointIndex;

      if (!points[0] || !points[1] || !points[2]) return drawing;

      const nextPoint = { time: anchor.time, price: anchor.price, logical: anchor.logical };

      if (dragState.mode === "riskRewardWidth") {
        return {
          ...drawing,
          points: [
            points[0],
            { ...points[1], time: anchor.time, logical: anchor.logical },
            { ...points[2], time: anchor.time, logical: anchor.logical },
          ],
        };
      }

      if (pointIndex === 0) {
        return {
          ...drawing,
          points: [nextPoint, points[1], points[2]],
        };
      }

      if (pointIndex === 1 || pointIndex === 2) {
        const entryPrice = points[0].price;
        const minGap = riskRewardMinimumPriceGap(entryPrice);
        const nextPrice =
          pointIndex === 1
            ? Math.max(anchor.price, entryPrice + minGap)
            : Math.min(anchor.price, entryPrice - minGap);
        const nextPoints = [...points];

        nextPoints[pointIndex] = {
          ...points[pointIndex],
          price: nextPrice,
        };

        return {
          ...drawing,
          points: nextPoints,
        };
      }
    }

    return {
      ...drawing,
      points: drawing.points.map((point, index) =>
        index === dragState.pointIndex
          ? { time: anchor.time, price: anchor.price, logical: anchor.logical }
          : point
      ),
    };
  });
}

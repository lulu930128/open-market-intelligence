import type { ShareholdingSeriesPoint } from "@/components/stock-detail/stockDetailTypes";
import type { MouseEvent as ReactMouseEvent } from "react";

export function minMax(values: Array<number | null | undefined>) {
  const validValues = values.filter(
    (value): value is number =>
      value !== null && value !== undefined && !Number.isNaN(value)
  );

  if (!validValues.length) return null;

  const min = Math.min(...validValues);
  const max = Math.max(...validValues);
  const padding = Math.max((max - min) * 0.12, max === min ? Math.max(Math.abs(max) * 0.08, 1) : 0);

  return {
    min: min - padding,
    max: max + padding,
  };
}

export function chartX(index: number, count: number, left: number, width: number) {
  if (count <= 1) return left + width / 2;
  return left + (index / (count - 1)) * width;
}

export function chartY(value: number, min: number, max: number, top: number, height: number) {
  if (max === min) return top + height / 2;
  return top + ((max - value) / (max - min)) * height;
}

export function buildLinePath(
  points: ShareholdingSeriesPoint[],
  valueKey: keyof Pick<ShareholdingSeriesPoint, "largeRatio" | "smallRatio" | "close">,
  scale: { min: number; max: number },
  left: number,
  top: number,
  width: number,
  height: number
) {
  let hasStarted = false;

  return points
    .map((point, index) => {
      const value = point[valueKey];
      if (value === null || value === undefined || Number.isNaN(value)) return null;

      const x = chartX(index, points.length, left, width);
      const y = chartY(value, scale.min, scale.max, top, height);
      const command = hasStarted ? "L" : "M";
      hasStarted = true;
      return `${command} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

export function buildNumericLinePath<T>(
  points: T[],
  getValue: (point: T) => number | null | undefined,
  scale: { min: number; max: number },
  left: number,
  top: number,
  width: number,
  height: number
) {
  let hasStarted = false;

  return points
    .map((point, index) => {
      const value = getValue(point);
      if (value === null || value === undefined || Number.isNaN(value)) return null;

      const x = chartX(index, points.length, left, width);
      const y = chartY(value, scale.min, scale.max, top, height);
      const command = hasStarted ? "L" : "M";
      hasStarted = true;
      return `${command} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .filter(Boolean)
    .join(" ");
}

export function chartEventViewX(event: ReactMouseEvent<SVGSVGElement>, viewWidth: number) {
  const svg = event.currentTarget;
  const screenMatrix = typeof svg.getScreenCTM === "function" ? svg.getScreenCTM() : null;

  if (screenMatrix && typeof DOMPoint !== "undefined") {
    return new DOMPoint(event.clientX, event.clientY).matrixTransform(screenMatrix.inverse()).x;
  }

  const rect = svg.getBoundingClientRect();
  if (rect.width <= 0) return 0;

  return ((event.clientX - rect.left) / rect.width) * viewWidth;
}

export function nearestChartIndex(
  event: ReactMouseEvent<SVGSVGElement>,
  pointCount: number,
  left: number,
  width: number,
  viewWidth: number
) {
  if (pointCount <= 1) return 0;

  const viewX = chartEventViewX(event, viewWidth);
  const clampedX = Math.max(left, Math.min(left + width, viewX));
  const ratio = (clampedX - left) / width;
  return Math.max(0, Math.min(pointCount - 1, Math.round(ratio * (pointCount - 1))));
}

export function tooltipX(x: number, tooltipWidth: number, viewWidth: number) {
  const padding = 8;
  const gap = 16;
  const rightX = x + gap;

  if (rightX + tooltipWidth <= viewWidth - padding) {
    return rightX;
  }

  return Math.max(padding, x - tooltipWidth - gap);
}

export function tooltipY(y: number, tooltipHeight: number, top: number, height: number) {
  return Math.max(8, Math.min(top + height - tooltipHeight - 8, y - tooltipHeight / 2));
}

"use client";

import type {
  ChartDrawing,
  ChartDrawingTool,
  ChartTimeMode,
} from "@/components/LightweightKLineChart";
import { omiChartColors } from "@/lib/themeColors";
import type { ChartDrawingSnapshotWrite } from "@/types/market";

export type ChartDrawingStorageState = {
  key: string;
  drawings: ChartDrawing[];
};

export type ChartDrawingSnapshot = {
  drawings: ChartDrawing[];
  selectedDrawingId: string | null;
};

export type ChartDrawingHistoryState = {
  key: string;
  past: ChartDrawingSnapshot[];
  future: ChartDrawingSnapshot[];
};

export const chartDrawingSyncDelayMs = 700;

export const professionalChartDrawingToolOptions: Array<{
  key: ChartDrawingTool;
  label: string;
  labelKey: string;
}> = [
  { key: "cursor", label: "Cursor", labelKey: "chart.drawingTools.cursor" },
  { key: "horizontal", label: "Horizontal", labelKey: "chart.drawingTools.horizontal" },
  { key: "trend", label: "Trend", labelKey: "chart.drawingTools.trend" },
  { key: "ray", label: "Ray", labelKey: "chart.drawingTools.ray" },
  { key: "rectangle", label: "Range", labelKey: "chart.drawingTools.rectangle" },
  { key: "fibonacci", label: "Fib", labelKey: "chart.drawingTools.fibonacci" },
  { key: "anchorVwap", label: "AVWAP", labelKey: "chart.drawingTools.anchorVwap" },
  {
    key: "volumeProfileRange",
    label: "Volume profile",
    labelKey: "chart.drawingTools.volumeProfileRange",
  },
  { key: "measure", label: "Measure", labelKey: "chart.drawingTools.measure" },
  { key: "priceRange", label: "Price range %", labelKey: "chart.drawingTools.priceRange" },
];

export const professionalChartDrawingToolOptionMap = new Map(
  professionalChartDrawingToolOptions.map((option) => [option.key, option])
);

export const professionalChartDrawingToolGroups: Array<{
  key: string;
  tools: ChartDrawingTool[];
}> = [
  { key: "base", tools: ["cursor"] },
  { key: "line", tools: ["horizontal", "trend", "ray"] },
  { key: "area", tools: ["rectangle", "fibonacci", "anchorVwap", "volumeProfileRange"] },
  { key: "measure", tools: ["measure", "priceRange"] },
];

export function chartDrawingApiPath(market: string, symbol: string, timeframe: string) {
  return `/api/market/chart-drawings/${encodeURIComponent(market)}/${encodeURIComponent(
    symbol
  )}/${encodeURIComponent(timeframe)}`;
}

export function buildChartDrawingSummarySnapshot({
  drawings,
  market,
  selectedDrawingId,
  stockName,
  symbol,
  timeframe,
  timeMode,
}: {
  drawings: ChartDrawing[];
  market: string;
  selectedDrawingId: string | null;
  stockName: string | null;
  symbol: string;
  timeframe: string;
  timeMode: ChartTimeMode;
}): Record<string, unknown> {
  const drawingsToSave = drawings.slice(-200);
  const byType = drawingsToSave.reduce<Record<string, number>>((accumulator, drawing) => {
    accumulator[drawing.type] = (accumulator[drawing.type] ?? 0) + 1;
    return accumulator;
  }, {});

  return {
    version: 1,
    generated_at: new Date().toISOString(),
    market,
    symbol,
    stock_name: stockName,
    timeframe,
    time_mode: timeMode,
    drawing_count: drawingsToSave.length,
    selected_drawing_id: selectedDrawingId,
    by_type: byType,
    items: drawingsToSave.map((drawing) => ({
      id: drawing.id,
      type: drawing.type,
      context: drawing.context ?? null,
      derived_metrics: drawing.derivedMetrics ?? null,
      omi_summary: drawing.omiSummary ?? null,
    })),
  };
}

export function buildChartDrawingSnapshotPayload({
  drawings,
  market,
  selectedDrawingId,
  source,
  stockName,
  symbol,
  timeframe,
  timeMode,
}: {
  drawings: ChartDrawing[];
  market: string;
  selectedDrawingId: string | null;
  source: string;
  stockName: string | null;
  symbol: string;
  timeframe: string;
  timeMode: ChartTimeMode;
}): ChartDrawingSnapshotWrite {
  const drawingsToSave = drawings.slice(-200);

  return {
    label: stockName ?? symbol,
    time_mode: timeMode,
    selected_drawing_id: normalizeChartDrawingSelection(drawingsToSave, selectedDrawingId),
    drawings: drawingsToSave as unknown as Array<Record<string, unknown>>,
    summary: buildChartDrawingSummarySnapshot({
      drawings: drawingsToSave,
      market,
      selectedDrawingId,
      stockName,
      symbol,
      timeframe,
      timeMode,
    }),
    source,
  };
}

function isChartDrawingType(value: unknown): value is ChartDrawing["type"] {
  return (
    value === "horizontal" ||
    value === "trend" ||
    value === "ray" ||
    value === "rectangle" ||
    value === "fibonacci" ||
    value === "anchorVwap" ||
    value === "volumeProfileRange" ||
    value === "measure" ||
    value === "priceRange"
  );
}

export function normalizeStoredChartDrawings(value: unknown): ChartDrawing[] {
  if (!Array.isArray(value)) return [];

  return value
    .flatMap((item): ChartDrawing[] => {
      if (!item || typeof item !== "object") return [];

      const candidate = item as Partial<ChartDrawing>;
      const type = candidate.type;
      const points = Array.isArray(candidate.points)
        ? candidate.points.filter(
            (point): point is ChartDrawing["points"][number] =>
              Boolean(point) &&
              typeof point === "object" &&
              typeof point.time === "string" &&
              typeof point.price === "number" &&
              Number.isFinite(point.price)
          )
        : [];

      if (
        typeof candidate.id !== "string" ||
        !isChartDrawingType(type) ||
        points.length === 0
      ) {
        return [];
      }

      const pointCount = type === "horizontal" || type === "anchorVwap" ? 1 : 2;
      if (points.length < pointCount) return [];

      const normalizedDrawing: ChartDrawing = {
        id: candidate.id,
        type,
        points: points.slice(0, pointCount),
        color: typeof candidate.color === "string" ? candidate.color : omiChartColors.text,
        createdAt:
          typeof candidate.createdAt === "string" ? candidate.createdAt : new Date().toISOString(),
      };

      if (candidate.context && typeof candidate.context === "object") {
        normalizedDrawing.context = candidate.context as ChartDrawing["context"];
      }

      if (
        candidate.derivedMetrics &&
        typeof candidate.derivedMetrics === "object" &&
        candidate.derivedMetrics.version === 1
      ) {
        normalizedDrawing.derivedMetrics =
          candidate.derivedMetrics as ChartDrawing["derivedMetrics"];
      }

      if (candidate.omiSummary && typeof candidate.omiSummary === "object") {
        normalizedDrawing.omiSummary = candidate.omiSummary as ChartDrawing["omiSummary"];
      }

      return [normalizedDrawing];
    })
    .slice(-200);
}

export function loadChartDrawings(storageKey: string): ChartDrawing[] {
  if (typeof window === "undefined") return [];

  try {
    const raw = window.localStorage.getItem(storageKey);

    if (!raw) return [];

    return normalizeStoredChartDrawings(JSON.parse(raw));
  } catch {
    return [];
  }
}

export function saveChartDrawings(storageKey: string, drawings: ChartDrawing[]) {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(storageKey, JSON.stringify(drawings.slice(-200)));
  } catch {
    // Best-effort local draft storage; chart drawing should never break the market view.
  }
}

export function serializeChartDrawings(drawings: ChartDrawing[]) {
  return JSON.stringify(drawings);
}

export function normalizeChartDrawingSelection(
  drawings: ChartDrawing[],
  selectedDrawingId: string | null
) {
  return drawings.some((drawing) => drawing.id === selectedDrawingId)
    ? selectedDrawingId
    : null;
}

export function createChartDrawingSnapshot(
  drawings: ChartDrawing[],
  selectedDrawingId: string | null
): ChartDrawingSnapshot {
  const normalizedDrawings = drawings.slice(-200);

  return {
    drawings: normalizedDrawings,
    selectedDrawingId: normalizeChartDrawingSelection(
      normalizedDrawings,
      selectedDrawingId
    ),
  };
}

export function chartDrawingSnapshotsEqual(
  first: ChartDrawingSnapshot,
  second: ChartDrawingSnapshot
) {
  return (
    first.selectedDrawingId === second.selectedDrawingId &&
    serializeChartDrawings(first.drawings) === serializeChartDrawings(second.drawings)
  );
}

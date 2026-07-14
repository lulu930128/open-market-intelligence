"use client";

import type { TranslationFunction } from "@/i18n";
import type { OmiChartColors } from "@/lib/themeColors";
import {
  drawingModeBadgeWidth,
  drawingToolModeLabel,
  measurementToneColor,
  type ChartDrawing,
  type ChartDrawingTool,
  type DrawingAnalysisI18n,
  type DrawingCoordinate,
  type DrawingDragState,
  type ProjectedDraftDrawing,
  type ProjectedDrawing,
} from "@/components/chart/lightweight-chart/drawingModel";
import { rectangleBounds } from "@/components/chart/lightweight-chart/drawingGeometry";
import type {
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";

const riskRewardReadyDistancePx = 3;
const riskRewardGhostHandleOffsetPx = 18;

type ChartDrawingLayerProps = {
  drawingHandleBorderColor: string;
  drawingI18n: DrawingAnalysisI18n;
  drawingTool: ChartDrawingTool;
  handleDrawingContextMenu: (
    event: ReactMouseEvent<SVGElement>,
    drawingId: string
  ) => void;
  handleDrawingPointerEnter: (drawingId: string) => void;
  handleDrawingPointerLeave: (drawingId: string) => void;
  hoveredDrawingColor: string;
  hoveredDrawingId: string | null;
  omiChartColors: OmiChartColors;
  overlaySize: {
    width: number;
    height: number;
  };
  projectedDraftDrawing: ProjectedDraftDrawing | null;
  projectedDrawings: ProjectedDrawing[];
  readableDrawingColor: (color: string, type: ChartDrawing["type"]) => string;
  selectedDrawingColor: string;
  selectedDrawingId: string | null;
  snapCoordinate: DrawingCoordinate | null;
  startDrawingDrag: (
    event: ReactPointerEvent<SVGElement>,
    drawing: ChartDrawing,
    mode: DrawingDragState["mode"],
    pointIndex?: 0 | 1 | 2,
    projectedPointCoordinates?: DrawingCoordinate[]
  ) => void;
  t: TranslationFunction;
};

export default function ChartDrawingLayer({
  drawingHandleBorderColor,
  drawingI18n,
  drawingTool,
  handleDrawingContextMenu,
  handleDrawingPointerEnter,
  handleDrawingPointerLeave,
  hoveredDrawingColor,
  hoveredDrawingId,
  omiChartColors,
  overlaySize,
  projectedDraftDrawing,
  projectedDrawings,
  readableDrawingColor,
  selectedDrawingColor,
  selectedDrawingId,
  snapCoordinate,
  startDrawingDrag,
  t,
}: ChartDrawingLayerProps) {
  const draftRectangleBox =
    projectedDraftDrawing?.type === "rectangle" ||
    projectedDraftDrawing?.type === "volumeProfileRange"
      ? rectangleBounds(projectedDraftDrawing.anchorPoints ?? projectedDraftDrawing.points)
      : null;
  const draftPriceRangeBox =
    projectedDraftDrawing?.type === "priceRange"
      ? rectangleBounds(projectedDraftDrawing.anchorPoints ?? projectedDraftDrawing.points)
      : null;

  return (
    <>
          {projectedDrawings.map(({ drawing, label: drawingLabel, points, anchorPoints, anchoredVwapLine, fibonacciLevels, volumeProfileBins, measurementStats, riskRewardStats }) => {
            const selected = drawing.id === selectedDrawingId;
            const hovered = drawing.id === hoveredDrawingId;
            const active = selected || hovered;
            const stroke = selected
              ? selectedDrawingColor
              : hovered
                ? hoveredDrawingColor
                : readableDrawingColor(drawing.color, drawing.type);
            const lineWidth = selected ? 2.5 : hovered ? 2.1 : 1.5;
            const handles = anchorPoints ?? points;
            const zoneAnalysis = drawing.derivedMetrics?.zoneAnalysis ?? null;
            const fibonacciAnalysis = drawing.derivedMetrics?.fibonacciAnalysis ?? null;
            const anchoredVwapAnalysis = drawing.derivedMetrics?.anchoredVwapAnalysis ?? null;
            const volumeProfileAnalysis = drawing.derivedMetrics?.volumeProfileAnalysis ?? null;

            if (drawing.type === "anchorVwap") {
              const linePoints = (anchoredVwapLine ?? []).map((point) => `${point.x},${point.y}`).join(" ");
              const lastLinePoint = anchoredVwapLine?.[anchoredVwapLine.length - 1] ?? points[0];
              const labelWidth = 132;
              const labelX = Math.max(8, Math.min(lastLinePoint.x + 10, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(lastLinePoint.y - 22, overlaySize.height - 38));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  {linePoints ? (
                    <>
                      <polyline
                        points={linePoints}
                        fill="none"
                        stroke="transparent"
                        strokeWidth={14}
                        className="cursor-move"
                        pointerEvents="stroke"
                        onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                        onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                      />
                      <polyline
                        points={linePoints}
                        fill="none"
                        stroke={stroke}
                        strokeWidth={selected ? 2.4 : hovered ? 2 : 1.6}
                        strokeDasharray="7 4"
                        opacity={active ? 0.96 : 0.82}
                        pointerEvents="none"
                      />
                    </>
                  ) : null}
                  <circle
                    cx={points[0].x}
                    cy={points[0].y}
                    r={11}
                    fill="transparent"
                    className="cursor-grab"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "point", 0, handles)}
                  />
                  <circle
                    cx={points[0].x}
                    cy={points[0].y}
                    r={active ? 4.8 : 4.2}
                    fill={stroke}
                    stroke={drawingHandleBorderColor}
                    strokeWidth={1.2}
                    pointerEvents="none"
                  />
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={30} rx={3} fill={omiChartColors.surface} stroke={stroke} opacity={0.95} />
                    <text x={10} y={13} className="fill-omi-text text-[10px] font-bold tabular-nums">
                      AVWAP {anchoredVwapAnalysis?.labels.vwap ?? drawingLabel}
                    </text>
                    <text x={10} y={25} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      {anchoredVwapAnalysis?.labels.status ?? t("chart.selectedDrawing.anchoredVwap")}
                    </text>
                  </g>
                </g>
              );
            }

            if (drawing.type === "riskReward" && riskRewardStats && points.length >= 3) {
              const entry = points[0];
              const target = points[1];
              const stop = points[2];

              if (!stop) return null;

              const left = entry.x;
              const right = Math.max(target.x, stop.x, entry.x + 16);
              const width = right - left;
              const targetReady = Math.abs(target.y - entry.y) >= riskRewardReadyDistancePx;
              const stopReady = Math.abs(stop.y - entry.y) >= riskRewardReadyDistancePx;
              const hasVerticalRange = targetReady || stopReady;
              const targetHandle = {
                ...target,
                x: right,
                y: targetReady ? target.y : entry.y - riskRewardGhostHandleOffsetPx,
              };
              const stopHandle = {
                ...stop,
                x: right,
                y: stopReady ? stop.y : entry.y + riskRewardGhostHandleOffsetPx,
              };
              const rewardTop = Math.min(entry.y, target.y);
              const rewardHeight = Math.max(1, Math.abs(entry.y - target.y));
              const riskTop = Math.min(entry.y, stop.y);
              const riskHeight = Math.max(1, Math.abs(entry.y - stop.y));
              const rangeTop = Math.min(target.y, stop.y, entry.y);
              const rangeBottom = Math.max(target.y, stop.y, entry.y);
              const interactionTop = hasVerticalRange
                ? rangeTop
                : entry.y - riskRewardGhostHandleOffsetPx - 8;
              const interactionHeight = hasVerticalRange
                ? Math.max(12, rangeBottom - rangeTop)
                : riskRewardGhostHandleOffsetPx * 2 + 16;
              const targetColor = omiChartColors.marketDown;
              const stopColor = omiChartColors.marketUp;
              const actionStroke = selected
                ? selectedDrawingColor
                : hovered
                  ? hoveredDrawingColor
                  : stroke;
              const labelWidth = 116;
              const ratioLabelWidth = 126;
              const rewardLabelX = Math.max(
                8,
                Math.min(left + 8, overlaySize.width - labelWidth - 8)
              );
              const rewardLabelY = Math.max(
                18,
                Math.min(rewardTop + 8, overlaySize.height - 24)
              );
              const riskLabelX = Math.max(
                8,
                Math.min(left + 8, overlaySize.width - labelWidth - 8)
              );
              const riskLabelY = Math.max(
                18,
                Math.min(riskTop + riskHeight - 26, overlaySize.height - 24)
              );
              const ratioLabelX = Math.max(
                8,
                Math.min(entry.x - ratioLabelWidth / 2, overlaySize.width - ratioLabelWidth - 8)
              );
              const ratioLabelY = Math.max(18, Math.min(entry.y - 11, overlaySize.height - 24));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  {targetReady ? (
                    <rect
                      x={left}
                      y={rewardTop}
                      width={width}
                      height={rewardHeight}
                      fill={targetColor}
                      opacity={active ? 0.22 : 0.16}
                      pointerEvents="none"
                    />
                  ) : null}
                  {stopReady ? (
                    <rect
                      x={left}
                      y={riskTop}
                      width={width}
                      height={riskHeight}
                      fill={stopColor}
                      opacity={active ? 0.22 : 0.16}
                      pointerEvents="none"
                    />
                  ) : null}
                  <rect
                    x={left}
                    y={interactionTop}
                    width={width}
                    height={interactionHeight}
                    fill="transparent"
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line", 0, handles)}
                  />
                  {hasVerticalRange ? (
                    <rect
                      x={left}
                      y={rangeTop}
                      width={width}
                      height={Math.max(1, rangeBottom - rangeTop)}
                      fill="none"
                      stroke={actionStroke}
                      strokeWidth={lineWidth}
                      strokeDasharray={selected ? undefined : "6 4"}
                      pointerEvents="none"
                    />
                  ) : null}
                  <line
                    x1={left}
                    y1={entry.y}
                    x2={left + width}
                    y2={entry.y}
                    stroke={actionStroke}
                    strokeWidth={lineWidth}
                    strokeDasharray="4 4"
                    pointerEvents="none"
                  />
                  {targetReady ? (
                    <line
                      x1={left}
                      y1={target.y}
                      x2={left + width}
                      y2={target.y}
                      stroke={targetColor}
                      strokeWidth={1.2}
                      pointerEvents="none"
                    />
                  ) : null}
                  {stopReady ? (
                    <line
                      x1={left}
                      y1={stop.y}
                      x2={left + width}
                      y2={stop.y}
                      stroke={stopColor}
                      strokeWidth={1.2}
                      pointerEvents="none"
                    />
                  ) : null}
                  {active
                    ? [
                        { handle: targetHandle, index: 1 as const, color: targetColor, ready: targetReady },
                        { handle: stopHandle, index: 2 as const, color: stopColor, ready: stopReady },
                      ].map(({ handle, index, color, ready }) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-ns-resize"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index, handles)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={color}
                            opacity={ready ? 1 : 0.72}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  {active ? (
                    <g key={`${drawing.id}-width-handle`}>
                      <circle
                        cx={left + width}
                        cy={entry.y}
                        r={11}
                        fill="transparent"
                        className="cursor-ew-resize"
                        pointerEvents="all"
                        onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                        onPointerDown={(event) =>
                          startDrawingDrag(event, drawing, "riskRewardWidth", 1, handles)
                        }
                      />
                      <rect
                        x={left + width - 4}
                        y={entry.y - 4}
                        width={8}
                        height={8}
                        rx={2}
                        fill={actionStroke}
                        stroke={drawingHandleBorderColor}
                        strokeWidth={1.2}
                        pointerEvents="none"
                      />
                    </g>
                  ) : null}
                  {targetReady ? (
                    <g transform={`translate(${rewardLabelX}, ${rewardLabelY})`} pointerEvents="none">
                      <rect width={labelWidth} height={20} rx={3} fill={targetColor} opacity={0.9} />
                      <text x={labelWidth / 2} y={13} textAnchor="middle" className="fill-white text-[10px] font-bold tabular-nums">
                        {t("chart.drawingAnalysis.riskReward.target")} {riskRewardStats.rewardLabel}
                      </text>
                    </g>
                  ) : null}
                  {targetReady && stopReady ? (
                    <g transform={`translate(${ratioLabelX}, ${ratioLabelY})`} pointerEvents="none">
                      <rect width={ratioLabelWidth} height={20} rx={3} fill={omiChartColors.surface} stroke={actionStroke} opacity={0.95} />
                      <text x={ratioLabelWidth / 2} y={13} textAnchor="middle" className="fill-omi-text text-[10px] font-bold tabular-nums">
                        {t("chart.drawingAnalysis.riskReward.ratio")}: {riskRewardStats.ratioLabel}
                      </text>
                    </g>
                  ) : null}
                  {stopReady ? (
                    <g transform={`translate(${riskLabelX}, ${riskLabelY})`} pointerEvents="none">
                      <rect width={labelWidth} height={20} rx={3} fill={stopColor} opacity={0.9} />
                      <text x={labelWidth / 2} y={13} textAnchor="middle" className="fill-white text-[10px] font-bold tabular-nums">
                        {t("chart.drawingAnalysis.riskReward.stop")} {riskRewardStats.riskLabel}
                      </text>
                    </g>
                  ) : null}
                </g>
              );
            }

            if (drawing.type === "measure" && measurementStats) {
              const tone = measurementToneColor(measurementStats.tone);
              const actionStroke = selected
                ? selectedDrawingColor
                : hovered
                  ? hoveredDrawingColor
                  : tone;
              const labelWidth = 148;
              const labelX = Math.max(
                8,
                Math.min((points[0].x + points[1].x) / 2 + 10, overlaySize.width - labelWidth - 8)
              );
              const labelY = Math.max(18, Math.min((points[0].y + points[1].y) / 2 - 24, overlaySize.height - 52));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <line
                    x1={points[0].x}
                    y1={points[0].y}
                    x2={points[1].x}
                    y2={points[1].y}
                    stroke="transparent"
                    strokeWidth={14}
                    className="cursor-move"
                    pointerEvents="stroke"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line", 0, handles)}
                  />
                  <line
                    x1={points[0].x}
                    y1={points[0].y}
                    x2={points[1].x}
                    y2={points[1].y}
                    stroke={actionStroke}
                    strokeWidth={lineWidth}
                    strokeDasharray="6 4"
                    pointerEvents="none"
                  />
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1, handles)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={actionStroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={38} rx={3} fill={omiChartColors.surface} stroke={actionStroke} opacity={0.96} />
                    <text x={10} y={15} className="fill-omi-text text-[10px] font-bold tabular-nums">
                      {t("chart.selectedDrawing.priceDiff")} {measurementStats.priceDiffLabel} ({measurementStats.percentLabel})
                    </text>
                    <text x={10} y={30} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      {measurementStats.barsLabel ?? t("chart.selectedDrawing.spanEmpty")} · {t("chart.selectedDrawing.high")} {measurementStats.highLabel} / {t("chart.selectedDrawing.low")} {measurementStats.lowLabel}
                    </text>
                  </g>
                </g>
              );
            }

            if (drawing.type === "priceRange" && measurementStats) {
              const tone = measurementToneColor(measurementStats.tone);
              const actionStroke = selected
                ? selectedDrawingColor
                : hovered
                  ? hoveredDrawingColor
                  : tone;
              const box = rectangleBounds(handles);
              const labelWidth = zoneAnalysis ? 152 : 136;
              const labelHeight = zoneAnalysis ? 52 : 38;
              const labelX = Math.max(8, Math.min(box.x + box.width + 8, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(box.y + 8, overlaySize.height - labelHeight - 14));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill={tone}
                    opacity={active ? 0.12 : 0.08}
                    pointerEvents="none"
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="transparent"
                    stroke="transparent"
                    strokeWidth={12}
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line", 0, handles)}
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="none"
                    stroke={actionStroke}
                    strokeWidth={lineWidth}
                    strokeDasharray="5 4"
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y}
                    x2={box.x + box.width}
                    y2={box.y}
                    stroke={actionStroke}
                    strokeWidth={1}
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y + box.height}
                    x2={box.x + box.width}
                    y2={box.y + box.height}
                    stroke={actionStroke}
                    strokeWidth={1}
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y + box.height / 2}
                    x2={box.x + box.width}
                    y2={box.y + box.height / 2}
                    stroke={actionStroke}
                    strokeWidth={1}
                    strokeDasharray="3 4"
                    opacity={0.72}
                    pointerEvents="none"
                  />
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1, handles)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={actionStroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={labelHeight} rx={3} fill={omiChartColors.surface} stroke={actionStroke} opacity={0.96} />
                    <text x={10} y={15} className="fill-omi-text text-[10px] font-bold tabular-nums">
                      {measurementStats.priceDiffLabel} ({measurementStats.percentLabel})
                    </text>
                    <text x={10} y={30} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      {t("chart.selectedDrawing.high")} {measurementStats.highLabel} / {t("chart.selectedDrawing.low")} {measurementStats.lowLabel}
                    </text>
                    {zoneAnalysis ? (
                      <text x={10} y={45} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                        {zoneAnalysis.labels.status} · {t("chart.selectedDrawing.position")} {zoneAnalysis.labels.position}
                      </text>
                    ) : null}
                  </g>
                </g>
              );
            }

            if (drawing.type === "volumeProfileRange") {
              const box = rectangleBounds(handles);
              const profileBins = volumeProfileBins ?? [];
              const labelWidth = 150;
              const labelHeight = 46;
              const labelX = Math.max(8, Math.min(box.x + box.width + 8, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(box.y + 8, overlaySize.height - labelHeight - 14));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill={stroke}
                    opacity={active ? 0.08 : 0.045}
                    pointerEvents="none"
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="transparent"
                    stroke="transparent"
                    strokeWidth={12}
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line", 0, handles)}
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={lineWidth}
                    strokeDasharray={selected ? undefined : "6 4"}
                    pointerEvents="none"
                  />
                  {profileBins.map((bin) => (
                    <g key={bin.id} pointerEvents="none">
                      <rect
                        x={bin.x}
                        y={bin.y}
                        width={bin.width}
                        height={bin.height}
                        fill={omiChartColors.text}
                        opacity={bin.poc ? 0.12 : bin.valueArea ? 0.065 : 0.035}
                      />
                      <rect
                        x={bin.x}
                        y={bin.y}
                        width={bin.sellWidth}
                        height={bin.height}
                        fill={omiChartColors.marketDown}
                        opacity={bin.poc ? 0.44 : bin.valueArea ? 0.3 : 0.2}
                      />
                      <rect
                        x={bin.x + bin.sellWidth}
                        y={bin.y}
                        width={bin.buyWidth}
                        height={bin.height}
                        fill={omiChartColors.marketUp}
                        opacity={bin.poc ? 0.44 : bin.valueArea ? 0.3 : 0.2}
                      />
                      {bin.poc ? (
                        <line
                          x1={box.x}
                          y1={bin.y + bin.height / 2}
                          x2={box.x + box.width}
                          y2={bin.y + bin.height / 2}
                          stroke={stroke}
                          strokeDasharray="4 4"
                          strokeWidth={1}
                          opacity={0.42}
                        />
                      ) : null}
                    </g>
                  ))}
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1, handles)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={stroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  <g transform={`translate(${labelX}, ${labelY})`} pointerEvents="none">
                    <rect width={labelWidth} height={labelHeight} rx={3} fill={omiChartColors.surface} stroke={stroke} opacity={0.95} />
                    <text x={10} y={14} className="fill-omi-text text-[10px] font-bold tabular-nums">
                      POC {volumeProfileAnalysis?.labels.poc ?? "-"}
                    </text>
                    <text x={10} y={28} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      VA {volumeProfileAnalysis?.labels.valueArea ?? "-"}
                    </text>
                    <text x={10} y={41} className="fill-omi-text-muted text-[10px] font-semibold tabular-nums">
                      {volumeProfileAnalysis?.labels.latestPosition ?? t("chart.drawingTools.volumeProfileRange")}
                    </text>
                  </g>
                </g>
              );
            }

            if (drawing.type === "rectangle") {
              const box = rectangleBounds(handles);
              const labelWidth = zoneAnalysis ? 132 : 108;
              const labelHeight = zoneAnalysis ? 34 : 18;
              const labelX = Math.max(8, Math.min(box.x + box.width + 8, overlaySize.width - labelWidth - 8));
              const labelY = Math.max(18, Math.min(box.y + 8, overlaySize.height - labelHeight - 14));

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill={stroke}
                    opacity={active ? 0.1 : 0.07}
                    pointerEvents="none"
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="transparent"
                    stroke="transparent"
                    strokeWidth={12}
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line", 0, handles)}
                  />
                  <rect
                    x={box.x}
                    y={box.y}
                    width={box.width}
                    height={box.height}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={lineWidth}
                    strokeDasharray={selected ? undefined : "6 4"}
                    pointerEvents="none"
                  />
                  <line
                    x1={box.x}
                    y1={box.y + box.height / 2}
                    x2={box.x + box.width}
                    y2={box.y + box.height / 2}
                    stroke={stroke}
                    strokeWidth={1}
                    strokeDasharray="3 4"
                    opacity={0.72}
                    pointerEvents="none"
                  />
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1, handles)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={stroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                  <g
                    transform={`translate(${labelX}, ${labelY})`}
                    pointerEvents="none"
                  >
                    <rect width={labelWidth} height={labelHeight} rx={3} fill={omiChartColors.surface} stroke={stroke} opacity={0.94} />
                    <text
                      x={labelWidth / 2}
                      y={12}
                      textAnchor="middle"
                      className="fill-omi-text text-[10px] font-bold tabular-nums"
                    >
                      {zoneAnalysis ? zoneAnalysis.labels.role : drawingLabel}
                    </text>
                    {zoneAnalysis ? (
                      <text
                        x={labelWidth / 2}
                        y={27}
                        textAnchor="middle"
                        className="fill-omi-text-muted text-[10px] font-semibold tabular-nums"
                      >
                        {zoneAnalysis.labels.status} · {zoneAnalysis.labels.position}
                      </text>
                    ) : null}
                  </g>
                </g>
              );
            }

            if (drawing.type === "fibonacci" && fibonacciLevels) {
              const minY = Math.min(handles[0].y, handles[1].y);
              const maxY = Math.max(handles[0].y, handles[1].y);

              return (
                <g
                  key={drawing.id}
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
                >
                  <rect
                    x={0}
                    y={minY}
                    width={overlaySize.width}
                    height={Math.max(1, maxY - minY)}
                    fill={stroke}
                    opacity={active ? 0.07 : 0.04}
                    pointerEvents="none"
                  />
                  <rect
                    x={0}
                    y={minY}
                    width={overlaySize.width}
                    height={Math.max(12, maxY - minY)}
                    fill="transparent"
                    className="cursor-move"
                    pointerEvents="all"
                    onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                    onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                    onPointerDown={(event) => startDrawingDrag(event, drawing, "line", 0, handles)}
                  />
                  {fibonacciLevels.map((level) => {
                    const nearest = fibonacciAnalysis?.nearestRatio === level.ratio;

                    return (
                    <g key={`${drawing.id}-fib-${level.ratio}`} pointerEvents="none">
                      <line
                        x1={0}
                        y1={level.y}
                        x2={overlaySize.width}
                        y2={level.y}
                        stroke={stroke}
                        strokeWidth={
                          nearest && active
                            ? Math.max(lineWidth, 2)
                            : level.ratio === 0 || level.ratio === 1
                              ? lineWidth
                              : 1
                        }
                        strokeDasharray={level.ratio === 0 || level.ratio === 1 ? undefined : "5 4"}
                        opacity={nearest && active ? 0.96 : level.ratio === 0 || level.ratio === 1 ? 0.95 : 0.72}
                      />
                      <g transform={`translate(${Math.max(8, overlaySize.width - 104)}, ${Math.max(14, level.y - 9)})`}>
                        <rect
                          width={96}
                          height={18}
                          rx={3}
                          fill={nearest && active ? omiChartColors.heatSoft : omiChartColors.surface}
                          stroke={stroke}
                          opacity={nearest && active ? 0.98 : 0.92}
                        />
                        <text
                          x={48}
                          y={12}
                          textAnchor="middle"
                          className="fill-omi-text text-[10px] font-bold tabular-nums"
                        >
                          {level.label} {level.priceLabel}
                        </text>
                      </g>
                    </g>
                    );
                  })}
                  {active
                    ? handles.map((handle, index) => (
                        <g key={`${drawing.id}-handle-${index}`}>
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={11}
                            fill="transparent"
                            className="cursor-grab"
                            pointerEvents="all"
                            onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                            onPointerDown={(event) =>
                              startDrawingDrag(event, drawing, "point", index as 0 | 1, handles)
                            }
                          />
                          <circle
                            cx={handle.x}
                            cy={handle.y}
                            r={selected ? 4.6 : 4.2}
                            fill={stroke}
                            stroke={drawingHandleBorderColor}
                            strokeWidth={1.2}
                            pointerEvents="none"
                          />
                        </g>
                      ))
                    : null}
                </g>
              );
            }

            return (
              <g
                key={drawing.id}
                onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                onPointerEnter={() => handleDrawingPointerEnter(drawing.id)}
                onPointerLeave={() => handleDrawingPointerLeave(drawing.id)}
              >
                <line
                  x1={points[0].x}
                  y1={points[0].y}
                  x2={points[1].x}
                  y2={points[1].y}
                  stroke="transparent"
                  strokeWidth={12}
                  className={drawing.type === "horizontal" ? "cursor-ns-resize" : "cursor-move"}
                  pointerEvents="stroke"
                  onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                  onPointerOver={() => handleDrawingPointerEnter(drawing.id)}
                  onPointerDown={(event) => {
                    if (drawing.type === "horizontal") {
                      startDrawingDrag(event, drawing, "horizontal", 0, handles);
                    } else {
                      startDrawingDrag(event, drawing, "line", 0, handles);
                    }
                  }}
                />
                <line
                  x1={points[0].x}
                  y1={points[0].y}
                  x2={points[1].x}
                  y2={points[1].y}
                  stroke={stroke}
                  strokeWidth={lineWidth}
                  strokeDasharray={drawing.type === "horizontal" ? "5 4" : undefined}
                  pointerEvents="none"
                />
                {active ? (
                  <>
                    {handles.map((handle, index) => (
                      <g key={`${drawing.id}-handle-${index}`}>
                        <circle
                          cx={handle.x}
                          cy={handle.y}
                          r={11}
                          fill="transparent"
                          className={drawing.type === "horizontal" ? "cursor-ns-resize" : "cursor-grab"}
                          pointerEvents="all"
                          onContextMenu={(event) => handleDrawingContextMenu(event, drawing.id)}
                          onPointerDown={(event) =>
                            startDrawingDrag(
                              event,
                              drawing,
                              drawing.type === "horizontal" ? "horizontal" : "point",
                              index as 0 | 1,
                              handles
                            )
                          }
                        />
                        <circle
                          cx={handle.x}
                          cy={handle.y}
                          r={selected ? 4.6 : 4.2}
                          fill={stroke}
                          stroke={drawingHandleBorderColor}
                          strokeWidth={1.2}
                          pointerEvents="none"
                        />
                      </g>
                    ))}
                  </>
                ) : null}
                <g transform={`translate(${Math.max(8, Math.min(points[1].x + 8, overlaySize.width - 74))}, ${Math.max(16, points[1].y - 8)})`}>
                  <rect width={66} height={18} rx={3} fill={omiChartColors.surface} stroke={stroke} opacity={0.94} />
                  <text
                    x={33}
                    y={12}
                    textAnchor="middle"
                    className="fill-omi-text text-[10px] font-bold tabular-nums"
                  >
                    {drawingLabel}
                  </text>
                </g>
              </g>
            );
          })}
          {projectedDraftDrawing ? (
            projectedDraftDrawing.type === "riskReward" ? (
              (() => {
                const entry = projectedDraftDrawing.points[0];
                const widthPoint = projectedDraftDrawing.points[1];

                if (!entry || !widthPoint) return null;

                const hasWidth = Math.abs(widthPoint.x - entry.x) >= 8;

                return (
                  <g pointerEvents="none">
                    {hasWidth ? (
                      <line
                        x1={entry.x}
                        y1={entry.y}
                        x2={widthPoint.x}
                        y2={entry.y}
                        stroke={omiChartColors.textMuted}
                        strokeWidth={1.5}
                        strokeDasharray="4 4"
                      />
                    ) : null}
                    <circle
                      cx={entry.x}
                      cy={entry.y}
                      r={4.4}
                      fill={omiChartColors.textMuted}
                      stroke={omiChartColors.surface}
                      strokeWidth={1.2}
                    />
                    {hasWidth ? (
                      <rect
                        x={widthPoint.x - 4}
                        y={entry.y - 4}
                        width={8}
                        height={8}
                        rx={2}
                        fill={omiChartColors.textMuted}
                        stroke={omiChartColors.surface}
                        strokeWidth={1.2}
                      />
                    ) : null}
                  </g>
                );
              })()
            ) : draftRectangleBox ? (
              <rect
                x={draftRectangleBox.x}
                y={draftRectangleBox.y}
                width={draftRectangleBox.width}
                height={draftRectangleBox.height}
                fill={omiChartColors.marketUp}
                opacity={0.06}
                stroke={omiChartColors.marketUp}
                strokeWidth={1.5}
                strokeDasharray="5 4"
                pointerEvents="none"
              />
            ) : draftPriceRangeBox && projectedDraftDrawing.measurementStats ? (
              <g pointerEvents="none">
                <rect
                  x={draftPriceRangeBox.x}
                  y={draftPriceRangeBox.y}
                  width={draftPriceRangeBox.width}
                  height={draftPriceRangeBox.height}
                  fill={measurementToneColor(projectedDraftDrawing.measurementStats.tone)}
                  opacity={0.08}
                  stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)}
                  strokeWidth={1.5}
                  strokeDasharray="5 4"
                />
                <g
                  transform={`translate(${Math.max(
                    8,
                    Math.min(draftPriceRangeBox.x + draftPriceRangeBox.width + 8, overlaySize.width - 132)
                  )}, ${Math.max(18, Math.min(draftPriceRangeBox.y + 8, overlaySize.height - 40))})`}
                >
                  <rect width={124} height={24} rx={3} fill={omiChartColors.surface} stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)} opacity={0.94} />
                  <text x={10} y={16} className="fill-omi-text text-[10px] font-bold tabular-nums">
                    {projectedDraftDrawing.measurementStats.priceDiffLabel} ({projectedDraftDrawing.measurementStats.percentLabel})
                  </text>
                </g>
              </g>
            ) : projectedDraftDrawing.type === "fibonacci" && projectedDraftDrawing.fibonacciLevels ? (
              <g pointerEvents="none">
                {projectedDraftDrawing.fibonacciLevels.map((level) => (
                  <line
                    key={`draft-fib-${level.ratio}`}
                    x1={0}
                    y1={level.y}
                    x2={overlaySize.width}
                    y2={level.y}
                    stroke={omiChartColors.marketUp}
                    strokeWidth={1.25}
                    strokeDasharray="5 4"
                    opacity={0.7}
                  />
                ))}
              </g>
            ) : projectedDraftDrawing.type === "measure" && projectedDraftDrawing.measurementStats ? (
              <g pointerEvents="none">
                <line
                  x1={projectedDraftDrawing.points[0].x}
                  y1={projectedDraftDrawing.points[0].y}
                  x2={projectedDraftDrawing.points[1].x}
                  y2={projectedDraftDrawing.points[1].y}
                  stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)}
                  strokeWidth={1.5}
                  strokeDasharray="5 4"
                />
                <g
                  transform={`translate(${Math.max(
                    8,
                    Math.min(
                      (projectedDraftDrawing.points[0].x + projectedDraftDrawing.points[1].x) / 2 + 10,
                      overlaySize.width - 150
                    )
                  )}, ${Math.max(
                    18,
                    Math.min(
                      (projectedDraftDrawing.points[0].y + projectedDraftDrawing.points[1].y) / 2 - 22,
                      overlaySize.height - 40
                    )
                  )})`}
                >
                  <rect width={142} height={24} rx={3} fill={omiChartColors.surface} stroke={measurementToneColor(projectedDraftDrawing.measurementStats.tone)} opacity={0.94} />
                  <text x={10} y={16} className="fill-omi-text text-[10px] font-bold tabular-nums">
                    {projectedDraftDrawing.measurementStats.priceDiffLabel} ({projectedDraftDrawing.measurementStats.percentLabel})
                  </text>
                </g>
              </g>
            ) : (
              <line
                x1={projectedDraftDrawing.points[0].x}
                y1={projectedDraftDrawing.points[0].y}
                x2={projectedDraftDrawing.points[1].x}
                y2={projectedDraftDrawing.points[1].y}
                stroke={omiChartColors.marketUp}
                strokeWidth={1.5}
                strokeDasharray="5 4"
                pointerEvents="none"
              />
            )
          ) : null}
          {snapCoordinate ? (
            <circle
              cx={snapCoordinate.x}
              cy={snapCoordinate.y}
              r={5}
              fill={omiChartColors.marketUp}
              stroke={omiChartColors.surface}
              strokeWidth={2}
              pointerEvents="none"
            />
          ) : null}
          {drawingTool !== "cursor" ? (
            <g transform="translate(12, 12)" pointerEvents="none">
              <rect width={drawingModeBadgeWidth(drawingTool)} height={24} rx={3} fill={omiChartColors.text} opacity={0.92} />
              <text x={12} y={16} className="fill-omi-surface text-[11px] font-bold">
                {drawingToolModeLabel(drawingTool, drawingI18n)}
              </text>
            </g>
          ) : null}
    </>
  );
}

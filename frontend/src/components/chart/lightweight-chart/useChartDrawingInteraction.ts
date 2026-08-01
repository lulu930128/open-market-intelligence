"use client";

import type { ChartPoint } from "@/types/market";
import type { IChartApi, LogicalRange } from "lightweight-charts";
import {
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  chartTime,
  createDrawingId,
  drawingSnapDistancePx,
  drawingTimeFromChartTime,
  finiteNumber,
  isRiskRewardDrawingTool,
  isTwoPointDrawingTool,
  isTwoPointDrawingType,
  type ChartDrawing,
  type ChartDrawingPoint,
  type ChartDrawingTool,
  type ChartTimeMode,
  type DrawingAnchor,
  type DrawingCoordinate,
  type DrawingDragState,
  type PointerAnchor,
  type PriceCoordinateApi,
  type ProjectedDrawing,
} from "@/components/chart/lightweight-chart/drawingModel";
import {
  applyDrawingDragToDrawings,
  isProjectedDrawingHit,
  lockCoordinateToNearestAngle,
} from "@/components/chart/lightweight-chart/drawingGeometry";

const riskRewardMinimumWidthPx = 24;

type UseChartDrawingInteractionArgs = {
  applyChartPointerInteractivity: (interactive: boolean) => void;
  attachActiveDrawingAnalytics: (drawing: ChartDrawing) => ChartDrawing;
  attachActiveDrawingsAnalytics: (drawings: ChartDrawing[]) => ChartDrawing[];
  beginChartInteraction: () => void;
  chartData: ChartPoint[];
  chartRef: RefObject<IChartApi | null>;
  coordinateToDrawingPoint: (coordinate: DrawingCoordinate) => ChartDrawingPoint | null;
  drawingLogicalFromCoordinateX: (coordinateX: number) => number | null;
  drawingPointToCoordinate: (point: ChartDrawingPoint) => DrawingCoordinate | null;
  drawings: ChartDrawing[];
  drawingTimeFromCoordinateX: (coordinateX: number) => string | null;
  drawingTool: ChartDrawingTool;
  endChartInteraction: () => void;
  mainSeriesRef: RefObject<PriceCoordinateApi | null>;
  onDrawingsChange?: (drawings: ChartDrawing[]) => void;
  onDrawingStateChange?: (
    drawings: ChartDrawing[],
    selectedDrawingId: string | null
  ) => void;
  onSelectedDrawingChange?: (drawingId: string | null) => void;
  overlaySvgRef: RefObject<SVGSVGElement | null>;
  projectedDrawings: ProjectedDrawing[];
  rememberVisibleLogicalRange: () => LogicalRange | null;
  restoreChartPointerInteractivity: () => void;
  restoreVisibleLogicalRange: (range: LogicalRange | null | undefined) => void;
  selectedDrawingId: string | null;
  themeDrawingDefaultColor: (type: ChartDrawing["type"]) => string;
  timeMode: ChartTimeMode;
};

export function useChartDrawingInteraction({
  applyChartPointerInteractivity,
  attachActiveDrawingAnalytics,
  attachActiveDrawingsAnalytics,
  beginChartInteraction,
  chartData,
  chartRef,
  coordinateToDrawingPoint,
  drawingLogicalFromCoordinateX,
  drawingPointToCoordinate,
  drawings,
  drawingTimeFromCoordinateX,
  drawingTool,
  endChartInteraction,
  mainSeriesRef,
  onDrawingsChange,
  onDrawingStateChange,
  onSelectedDrawingChange,
  overlaySvgRef,
  projectedDrawings,
  rememberVisibleLogicalRange,
  restoreChartPointerInteractivity,
  restoreVisibleLogicalRange,
  selectedDrawingId,
  themeDrawingDefaultColor,
  timeMode,
}: UseChartDrawingInteractionArgs) {
  const dragStateRef = useRef<DrawingDragState | null>(null);
  const [draftAnchor, setDraftAnchor] = useState<DrawingAnchor | null>(null);
  const [riskRewardDraftPointerId, setRiskRewardDraftPointerId] = useState<number | null>(null);
  const [hoverAnchor, setHoverAnchor] = useState<DrawingAnchor | null>(null);
  const [snapCoordinate, setSnapCoordinate] = useState<DrawingCoordinate | null>(null);
  const [dragPreviewDrawings, setDragPreviewDrawings] = useState<ChartDrawing[] | null>(null);
  const [hoveredDrawingId, setHoveredDrawingId] = useState<string | null>(null);

  const drawingIdSet = useMemo(
    () => new Set(drawings.map((drawing) => drawing.id)),
    [drawings]
  );
  const activeDrawings = useMemo(() => {
    if (!dragPreviewDrawings) return drawings;

    return dragPreviewDrawings.every((drawing) => drawingIdSet.has(drawing.id))
      ? dragPreviewDrawings
      : drawings;
  }, [dragPreviewDrawings, drawingIdSet, drawings]);

  function pointerCoordinateFromEvent(event: { clientX: number; clientY: number }): DrawingCoordinate | null {
    const target = overlaySvgRef.current;

    if (!target) return null;

    const rect = target.getBoundingClientRect();

    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  function snapAnchorToHighLow(anchor: DrawingAnchor, x: number, y: number): PointerAnchor {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;

    if (!chart || !series || chartData.length === 0) {
      return { ...anchor, x, y, snapped: false };
    }

    let best:
      | {
          anchor: PointerAnchor;
          score: number;
        }
      | null = null;

    for (const point of chartData) {
      const pointX = chart.timeScale().timeToCoordinate(chartTime(point.time, timeMode));

      if (pointX === null) continue;

      const candidates = [
        { price: point.high, time: point.time },
        { price: point.low, time: point.time },
      ];

      for (const candidate of candidates) {
        if (!finiteNumber(candidate.price)) continue;

        const pointY = series.priceToCoordinate(candidate.price);

        if (pointY === null) continue;

        const dx = Math.abs(pointX - x);
        const dy = Math.abs(pointY - y);

        if (dx > drawingSnapDistancePx || dy > drawingSnapDistancePx) continue;

        const score = dx + dy;

        if (!best || score < best.score) {
          const candidateTime = drawingTimeFromChartTime(
            chartTime(candidate.time, timeMode),
            timeMode
          );

          best = {
            score,
            anchor: {
              time: candidateTime,
              price: candidate.price,
              x: pointX,
              y: pointY,
              snapped: true,
            },
          };
        }
      }
    }

    return best?.anchor ?? { ...anchor, x, y, snapped: false };
  }

  function anchorFromPointer<T extends SVGElement>(
    event: ReactPointerEvent<T>,
    options: { snap?: boolean } = {}
  ): PointerAnchor | null {
    const chart = chartRef.current;
    const series = mainSeriesRef.current;
    const coordinate = pointerCoordinateFromEvent(event);

    if (!chart || !series || !coordinate) return null;

    const price = series.coordinateToPrice(coordinate.y);
    const time = drawingTimeFromCoordinateX(coordinate.x);
    const logical = drawingLogicalFromCoordinateX(coordinate.x);

    if (time === null || price === null || !Number.isFinite(price)) return null;

    const anchor = {
      time,
      price,
      logical: logical ?? undefined,
    };

    if (options.snap === false) {
      return {
        ...anchor,
        ...coordinate,
        snapped: false,
      };
    }

    return snapAnchorToHighLow(anchor, coordinate.x, coordinate.y);
  }

  function riskRewardWidthAnchorFromPointer<T extends SVGElement>(
    event: ReactPointerEvent<T>,
    entryCoordinate: DrawingCoordinate | null | undefined,
    options: { clampToMinimum?: boolean } = {}
  ): PointerAnchor | null {
    const coordinate = pointerCoordinateFromEvent(event);

    if (!coordinate || !entryCoordinate) return null;

    const minimumX = entryCoordinate.x + riskRewardMinimumWidthPx;
    if (!options.clampToMinimum && coordinate.x < minimumX) return null;

    const x = Math.max(coordinate.x, minimumX);
    const y = entryCoordinate.y;
    const point = coordinateToDrawingPoint({ x, y });

    if (!point) return null;

    return {
      ...point,
      x,
      y,
      snapped: false,
    };
  }

  function constrainAnchorToAngle(
    anchor: PointerAnchor,
    originCoordinate: DrawingCoordinate | null | undefined
  ): PointerAnchor {
    if (!originCoordinate) return anchor;

    const lockedCoordinate = lockCoordinateToNearestAngle(originCoordinate, anchor);
    const lockedPoint = coordinateToDrawingPoint(lockedCoordinate);

    if (!lockedPoint) return anchor;

    return {
      ...lockedPoint,
      x: lockedCoordinate.x,
      y: lockedCoordinate.y,
      snapped: false,
    };
  }

  const commitDrawingState = useCallback((nextDrawings: ChartDrawing[], nextSelectedDrawingId: string | null) => {
    if (onDrawingStateChange) {
      onDrawingStateChange(nextDrawings, nextSelectedDrawingId);
      return;
    }

    onDrawingsChange?.(nextDrawings);
    onSelectedDrawingChange?.(nextSelectedDrawingId);
  }, [onDrawingStateChange, onDrawingsChange, onSelectedDrawingChange]);

  function commitDrawing(type: ChartDrawing["type"], points: ChartDrawingPoint[]) {
    if ((!onDrawingStateChange && !onDrawingsChange) || points.length === 0) return;

    const visibleRange = rememberVisibleLogicalRange();
    const nextDrawing = attachActiveDrawingAnalytics({
      id: createDrawingId(),
      type,
      points,
      color: themeDrawingDefaultColor(type),
      createdAt: new Date().toISOString(),
    });

    commitDrawingState([...drawings, nextDrawing], nextDrawing.id);
    restoreVisibleLogicalRange(visibleRange);
  }

  function buildDefaultRiskRewardPoints(
    anchor: DrawingAnchor,
    widthAnchor: DrawingAnchor
  ): [ChartDrawingPoint, ChartDrawingPoint, ChartDrawingPoint] {
    return [
      {
        time: anchor.time,
        price: anchor.price,
        logical: anchor.logical,
      },
      {
        time: widthAnchor.time,
        price: anchor.price,
        logical: widthAnchor.logical,
      },
      {
        time: widthAnchor.time,
        price: anchor.price,
        logical: widthAnchor.logical,
      },
    ];
  }

  const deleteDrawing = useCallback((drawingId: string) => {
    const visibleRange = rememberVisibleLogicalRange();
    const nextSelectedDrawingId = selectedDrawingId === drawingId ? null : selectedDrawingId;

    commitDrawingState(
      drawings.filter((drawing) => drawing.id !== drawingId),
      nextSelectedDrawingId
    );

    restoreVisibleLogicalRange(visibleRange);
  }, [
    commitDrawingState,
    drawings,
    rememberVisibleLogicalRange,
    restoreVisibleLogicalRange,
    selectedDrawingId,
  ]);

  function handleDrawingContextMenu(event: ReactMouseEvent<SVGElement>, drawingId: string) {
    event.preventDefault();
    event.stopPropagation();
    deleteDrawing(drawingId);
  }

  function applyActiveDrawingDrag(
    sourceDrawings: ChartDrawing[],
    dragState: DrawingDragState,
    anchor: DrawingAnchor | null,
    pointerCoordinate: DrawingCoordinate | null
  ) {
    if (dragState.mode !== "line") {
      return anchor ? applyDrawingDragToDrawings(sourceDrawings, dragState, anchor) : sourceDrawings;
    }

    if (
      !dragState.startCoordinate ||
      !pointerCoordinate ||
      !dragState.originCoordinates ||
      dragState.originCoordinates.length < 2
    ) {
      return sourceDrawings;
    }

    const dx = pointerCoordinate.x - dragState.startCoordinate.x;
    const dy = pointerCoordinate.y - dragState.startCoordinate.y;
    const [originFirst, originSecond] = dragState.originCoordinates;

    if (!originFirst || !originSecond) return sourceDrawings;

    return sourceDrawings.map((drawing) => {
      if (drawing.id !== dragState.drawingId) return drawing;

      if (drawing.type === "riskReward") {
        const [originEntry, originTarget, originStop] = dragState.originCoordinates ?? [];

        if (!originEntry || !originTarget || !originStop) return drawing;

        const entry = coordinateToDrawingPoint({
          x: originEntry.x + dx,
          y: originEntry.y + dy,
        });
        const target = coordinateToDrawingPoint({
          x: originTarget.x + dx,
          y: originTarget.y + dy,
        });
        const stop = coordinateToDrawingPoint({
          x: originStop.x + dx,
          y: originStop.y + dy,
        });

        if (!entry || !target || !stop) return drawing;

        return {
          ...drawing,
          points: [entry, target, stop],
        };
      }

      if (!isTwoPointDrawingType(drawing.type)) return drawing;

      const first = coordinateToDrawingPoint({
        x: originFirst.x + dx,
        y: originFirst.y + dy,
      });
      const second = coordinateToDrawingPoint({
        x: originSecond.x + dx,
        y: originSecond.y + dy,
      });

      if (!first || !second) return drawing;

      return {
        ...drawing,
        points: [first, second],
      };
    });
  }

  function handleDrawingPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;

    beginChartInteraction();

    if (drawingTool === "cursor") {
      const pointerCoordinate = pointerCoordinateFromEvent(event);
      const hitDrawingId = pointerCoordinate ? findHoveredDrawingId(pointerCoordinate) : null;

      if (!hitDrawingId) {
        setHoveredDrawingId(null);
        onSelectedDrawingChange?.(null);
      }

      return;
    }

    if (drawingTool === "riskReward" && draftAnchor) {
      const entryCoordinate = drawingPointToCoordinate(draftAnchor);
      const widthAnchor = riskRewardWidthAnchorFromPointer(event, entryCoordinate);

      event.currentTarget.setPointerCapture(event.pointerId);
      setHoverAnchor(widthAnchor ?? draftAnchor);
      setRiskRewardDraftPointerId(event.pointerId);
      setSnapCoordinate(widthAnchor ? { x: widthAnchor.x, y: widthAnchor.y } : null);
      return;
    }

    let anchor = anchorFromPointer(event, { snap: !event.altKey });

    if (!anchor) return;

    if (event.shiftKey && draftAnchor) {
      anchor = constrainAnchorToAngle(anchor, drawingPointToCoordinate(draftAnchor));
    }

    setSnapCoordinate(anchor.snapped ? { x: anchor.x, y: anchor.y } : null);

    if (drawingTool === "anchorVwap") {
      commitDrawing("anchorVwap", [anchor]);
      setDraftAnchor(null);
      setHoverAnchor(null);
      return;
    }

    if (drawingTool === "horizontal") {
      commitDrawing("horizontal", [anchor]);
      setDraftAnchor(null);
      setHoverAnchor(null);
      return;
    }

    if (drawingTool === "riskReward") {
      event.currentTarget.setPointerCapture(event.pointerId);
      setDraftAnchor(anchor);
      setHoverAnchor(anchor);
      setRiskRewardDraftPointerId(event.pointerId);
      return;
    }

    if (!isTwoPointDrawingTool(drawingTool)) return;

    if (!draftAnchor) {
      setDraftAnchor(anchor);
      setHoverAnchor(anchor);
      return;
    }

    commitDrawing(drawingTool, [draftAnchor, anchor]);
    setDraftAnchor(null);
    setHoverAnchor(null);
  }

  function handleDrawingPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (riskRewardDraftPointerId !== null && event.pointerId === riskRewardDraftPointerId && draftAnchor) {
      const entryCoordinate = drawingPointToCoordinate(draftAnchor);
      const widthAnchor = riskRewardWidthAnchorFromPointer(event, entryCoordinate);

      if (widthAnchor) {
        setHoverAnchor(widthAnchor);
        setSnapCoordinate({ x: widthAnchor.x, y: widthAnchor.y });
      } else {
        setHoverAnchor(draftAnchor);
        setSnapCoordinate(null);
      }

      return;
    }

    const dragState = dragStateRef.current;

    if (dragState) {
      const pointerCoordinate = pointerCoordinateFromEvent(event);
      let anchor =
        dragState.mode === "line"
          ? null
          : dragState.mode === "riskRewardWidth"
            ? riskRewardWidthAnchorFromPointer(event, dragState.oppositeCoordinate, {
                clampToMinimum: true,
              })
            : anchorFromPointer(event, { snap: !event.altKey });

      if (dragState.mode !== "line" && !anchor) return;

      if (anchor && event.shiftKey && dragState.mode === "point") {
        anchor = constrainAnchorToAngle(anchor, dragState.oppositeCoordinate);
      }

      setSnapCoordinate(anchor?.snapped ? { x: anchor.x, y: anchor.y } : null);
      setDragPreviewDrawings((current) =>
        applyActiveDrawingDrag(
          current ?? drawings,
          dragState,
          anchor,
          pointerCoordinate
        )
      );
      return;
    }

    const pointerCoordinate = pointerCoordinateFromEvent(event);

    if (!draftAnchor) {
      const nextHoveredDrawingId = pointerCoordinate ? findHoveredDrawingId(pointerCoordinate) : null;
      setHoveredDrawingId((current) =>
        current === nextHoveredDrawingId ? current : nextHoveredDrawingId
      );
    }

    if (!isTwoPointDrawingTool(drawingTool) || !draftAnchor) return;

    let anchor = anchorFromPointer(event, { snap: !event.altKey });

    if (anchor) {
      if (event.shiftKey) {
        anchor = constrainAnchorToAngle(anchor, drawingPointToCoordinate(draftAnchor));
      }

      setHoverAnchor(anchor);
      setSnapCoordinate(anchor.snapped ? { x: anchor.x, y: anchor.y } : null);
    }
  }

  function handleDrawingOverlayPointerLeave() {
    if (riskRewardDraftPointerId === null) {
      setHoverAnchor(null);
      setSnapCoordinate(null);
    }
  }

  function startDrawingDrag(
    event: ReactPointerEvent<SVGElement>,
    drawing: ChartDrawing,
    mode: DrawingDragState["mode"],
    pointIndex: 0 | 1 | 2 = 0,
    projectedPointCoordinates: DrawingCoordinate[] = []
  ) {
    if (event.button !== 0) return;

    beginChartInteraction();
    applyChartPointerInteractivity(false);
    event.preventDefault();
    event.stopPropagation();

    const startCoordinate = pointerCoordinateFromEvent(event);
    const visibleRange = rememberVisibleLogicalRange();
    const pointCoordinates = projectedPointCoordinates;
    const originCoordinates =
      mode === "line" ? pointCoordinates : undefined;
    const oppositeCoordinate =
      mode === "riskRewardWidth" && pointCoordinates.length >= 1
        ? pointCoordinates[0]
        : mode === "point" && pointCoordinates.length >= 2
        ? pointCoordinates[pointIndex === 0 ? 1 : 0]
        : undefined;

    if (mode === "line" && (!startCoordinate || !originCoordinates || originCoordinates.length < 2)) {
      return;
    }

    event.currentTarget.setPointerCapture(event.pointerId);
    dragStateRef.current = {
      drawingId: drawing.id,
      mode,
      pointIndex,
      pointerId: event.pointerId,
      startCoordinate: mode === "line" ? startCoordinate ?? undefined : undefined,
      originCoordinates,
      oppositeCoordinate,
      visibleLogicalRange: visibleRange ?? undefined,
    };
    setDraftAnchor(null);
    setHoverAnchor(null);
    setDragPreviewDrawings(activeDrawings);
    selectDrawing(drawing.id);
  }

  function finishDrawingDrag(event: ReactPointerEvent<SVGSVGElement>) {
    if (riskRewardDraftPointerId !== null && event.pointerId === riskRewardDraftPointerId && draftAnchor) {
      const entryCoordinate = drawingPointToCoordinate(draftAnchor);
      const widthAnchor = riskRewardWidthAnchorFromPointer(event, entryCoordinate);

      if (!widthAnchor) {
        setHoverAnchor(draftAnchor);
        setRiskRewardDraftPointerId(null);
        setSnapCoordinate(null);
        endChartInteraction();
        restoreChartPointerInteractivity();
        return;
      }

      commitDrawing("riskReward", buildDefaultRiskRewardPoints(draftAnchor, widthAnchor));
      setDraftAnchor(null);
      setHoverAnchor(null);
      setRiskRewardDraftPointerId(null);
      setSnapCoordinate(null);
      endChartInteraction();
      restoreChartPointerInteractivity();
      return;
    }

    const dragState = dragStateRef.current;

    if (!dragState) return;

    const pointerCoordinate = pointerCoordinateFromEvent(event);
    let anchor =
      dragState.mode === "line"
        ? null
        : dragState.mode === "riskRewardWidth"
          ? riskRewardWidthAnchorFromPointer(event, dragState.oppositeCoordinate, {
              clampToMinimum: true,
            })
          : anchorFromPointer(event, { snap: !event.altKey });

    if (anchor && event.shiftKey && dragState.mode === "point") {
      anchor = constrainAnchorToAngle(anchor, dragState.oppositeCoordinate);
    }

    const sourceDrawings = dragPreviewDrawings ?? drawings;
    const nextDrawings = attachActiveDrawingsAnalytics(
      applyActiveDrawingDrag(sourceDrawings, dragState, anchor, pointerCoordinate)
    );
    const visibleRange = dragState.visibleLogicalRange ?? rememberVisibleLogicalRange();

    commitDrawingState(nextDrawings, dragState.drawingId);
    dragStateRef.current = null;
    setDragPreviewDrawings(null);
    setSnapCoordinate(null);
    restoreVisibleLogicalRange(visibleRange);
    restoreChartPointerInteractivity();
  }

  function selectDrawing(drawingId: string) {
    onSelectedDrawingChange?.(drawingId);
  }

  function clearDrawingDraft() {
    dragStateRef.current = null;
    setDraftAnchor(null);
    setRiskRewardDraftPointerId(null);
    setHoverAnchor(null);
    setHoveredDrawingId(null);
    setSnapCoordinate(null);
    setDragPreviewDrawings(null);
  }

  function handleDrawingPointerEnter(drawingId: string) {
    setHoveredDrawingId(drawingId);
  }

  function handleDrawingPointerLeave(drawingId: string) {
    setHoveredDrawingId((current) => (current === drawingId ? null : current));
  }

  const findHoveredDrawingId = useCallback((coordinate: DrawingCoordinate) => {
    for (let index = projectedDrawings.length - 1; index >= 0; index -= 1) {
      const projectedDrawing = projectedDrawings[index];

      if (isProjectedDrawingHit(coordinate, projectedDrawing)) {
        return projectedDrawing.drawing.id;
      }
    }

    return null;
  }, [projectedDrawings]);

  useEffect(() => {
    if (drawingTool !== "cursor" || projectedDrawings.length === 0) {
      return undefined;
    }

    function handleWindowPointerMove(event: PointerEvent) {
      if (dragStateRef.current) return;

      const overlay = overlaySvgRef.current;

      if (!overlay) return;

      const rect = overlay.getBoundingClientRect();
      const coordinate = {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
      const isInside =
        coordinate.x >= 0 &&
        coordinate.x <= rect.width &&
        coordinate.y >= 0 &&
        coordinate.y <= rect.height;
      const nextHoveredDrawingId = isInside ? findHoveredDrawingId(coordinate) : null;

      setHoveredDrawingId((current) =>
        current === nextHoveredDrawingId ? current : nextHoveredDrawingId
      );
    }

    window.addEventListener("pointermove", handleWindowPointerMove);

    return () => window.removeEventListener("pointermove", handleWindowPointerMove);
  }, [drawingTool, findHoveredDrawingId, overlaySvgRef, projectedDrawings.length]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();

      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;

      if (event.key === "Escape") {
        if (!draftAnchor && !dragStateRef.current && !selectedDrawingId) return;

        event.preventDefault();
        clearDrawingDraft();
        if (!draftAnchor && selectedDrawingId) {
          onSelectedDrawingChange?.(null);
        }
        return;
      }

      if (!selectedDrawingId) return;
      if (event.key !== "Delete" && event.key !== "Backspace") return;

      event.preventDefault();
      deleteDrawing(selectedDrawingId);
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deleteDrawing, draftAnchor, onSelectedDrawingChange, selectedDrawingId]);

  useEffect(() => {
    if (!isTwoPointDrawingTool(drawingTool) && !isRiskRewardDrawingTool(drawingTool)) {
      const timer = window.setTimeout(() => {
        setDraftAnchor(null);
        setRiskRewardDraftPointerId(null);
        setHoverAnchor(null);
        setHoveredDrawingId(null);
      }, 0);

      return () => window.clearTimeout(timer);
    }

    return undefined;
  }, [drawingTool]);

  function handleChartSelectionPointerDown(event: ReactPointerEvent<HTMLElement>) {
    if (drawingTool !== "cursor") return;

    const pointerCoordinate = pointerCoordinateFromEvent(event);
    const hitDrawingId = pointerCoordinate ? findHoveredDrawingId(pointerCoordinate) : null;

    if (hitDrawingId) {
      setHoveredDrawingId(hitDrawingId);
      onSelectedDrawingChange?.(hitDrawingId);
      return;
    }

    setHoveredDrawingId(null);
    onSelectedDrawingChange?.(null);
  }

  return {
    activeDrawings,
    draftAnchor,
    dragPreviewDrawings,
    finishDrawingDrag,
    handleChartSelectionPointerDown,
    handleDrawingContextMenu,
    handleDrawingOverlayPointerLeave,
    handleDrawingPointerDown,
    handleDrawingPointerEnter,
    handleDrawingPointerLeave,
    handleDrawingPointerMove,
    hoverAnchor,
    hoveredDrawingId,
    snapCoordinate,
    startDrawingDrag,
  };
}

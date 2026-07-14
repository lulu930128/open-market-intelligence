"use client";

import type { ChartDrawing } from "@/components/LightweightKLineChart";
import type { ProfessionalTimeframe } from "@/components/stock-detail/StockDetailDataViews";
import { isProfessionalIntradayTimeframe } from "@/components/stock-detail/StockDetailDataViews";
import {
  buildChartDrawingSnapshotPayload,
  chartDrawingApiPath,
  chartDrawingSnapshotsEqual,
  chartDrawingSyncDelayMs,
  createChartDrawingSnapshot,
  loadChartDrawings,
  normalizeChartDrawingSelection,
  normalizeStoredChartDrawings,
  saveChartDrawings,
  serializeChartDrawings,
  type ChartDrawingHistoryState,
  type ChartDrawingStorageState,
} from "@/components/professionalChartDrawing";
import { fetchJson, requestJson } from "@/lib/api";
import type { ChartDrawingSnapshotRead } from "@/types/market";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type UseChartDrawingPersistenceOptions = {
  active: boolean;
  clearConfirmationMessage: string;
  market: string | null;
  stockId: string | null;
  stockName: string | null;
  timeframe: ProfessionalTimeframe;
};

function chartDrawingStorageKey(stockId: string | null, timeframe: ProfessionalTimeframe) {
  return `omi:tw:chart-drawings:v1:${stockId ?? "empty"}:${timeframe}`;
}

function chartDrawingTimeMode(timeframe: ProfessionalTimeframe) {
  return isProfessionalIntradayTimeframe(timeframe) ? "intraday" : "date";
}

export function useChartDrawingPersistence({
  active,
  clearConfirmationMessage,
  market,
  stockId,
  stockName,
  timeframe,
}: UseChartDrawingPersistenceOptions) {
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawingState, setDrawingState] = useState<ChartDrawingStorageState>({
    key: "",
    drawings: [],
  });
  const [historyState, setHistoryState] = useState<ChartDrawingHistoryState>({
    key: "",
    past: [],
    future: [],
  });
  const syncTimerRef = useRef<number | null>(null);
  const storageKey = chartDrawingStorageKey(stockId, timeframe);
  const storedDrawings = useMemo(() => loadChartDrawings(storageKey), [storageKey]);
  const drawings = drawingState.key === storageKey ? drawingState.drawings : storedDrawings;
  const history =
    historyState.key === storageKey
      ? historyState
      : { key: storageKey, past: [], future: [] };
  const activeSelectedDrawingId = normalizeChartDrawingSelection(
    drawings,
    selectedDrawingId
  );
  const canUndo = history.past.length > 0;
  const canRedo = history.future.length > 0;

  const queueRemoteSave = useCallback(
    (drawingsToSave: ChartDrawing[], selectedDrawingIdToSave: string | null) => {
      if (typeof window === "undefined" || !stockId || !market) return;

      const path = chartDrawingApiPath(market, stockId, timeframe);
      const payload = buildChartDrawingSnapshotPayload({
        drawings: drawingsToSave,
        market,
        selectedDrawingId: selectedDrawingIdToSave,
        source: "frontend.professional_chart",
        stockName,
        symbol: stockId,
        timeframe,
        timeMode: chartDrawingTimeMode(timeframe),
      });

      if (syncTimerRef.current) {
        window.clearTimeout(syncTimerRef.current);
      }

      syncTimerRef.current = window.setTimeout(() => {
        void requestJson<ChartDrawingSnapshotRead>(path, {
          method: "PUT",
          body: JSON.stringify(payload),
        }).catch(() => {
          // Local storage remains the source of recovery when remote sync is unavailable.
        });
      }, chartDrawingSyncDelayMs);
    },
    [market, stockId, stockName, timeframe]
  );

  const storeDrawings = useCallback(
    (
      drawingsToSave: ChartDrawing[],
      selectedDrawingIdToSave = activeSelectedDrawingId
    ) => {
      setDrawingState({ key: storageKey, drawings: drawingsToSave });
      saveChartDrawings(storageKey, drawingsToSave);
      queueRemoteSave(drawingsToSave, selectedDrawingIdToSave);
    },
    [activeSelectedDrawingId, queueRemoteSave, storageKey]
  );

  useEffect(() => {
    return () => {
      if (syncTimerRef.current && typeof window !== "undefined") {
        window.clearTimeout(syncTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!active || !stockId || !market) return;

    let cancelled = false;
    const remoteMarket = market;
    const remoteStockId = stockId;
    const localDrawings = loadChartDrawings(storageKey);
    const normalizedLocalSelection = normalizeChartDrawingSelection(
      localDrawings,
      activeSelectedDrawingId
    );

    if (localDrawings.length > 0) {
      queueRemoteSave(localDrawings, normalizedLocalSelection);
      return () => {
        cancelled = true;
      };
    }

    async function loadRemoteDrawings() {
      try {
        const snapshot = await fetchJson<ChartDrawingSnapshotRead>(
          chartDrawingApiPath(remoteMarket, remoteStockId, timeframe)
        );
        if (cancelled) return;

        const remoteDrawings = normalizeStoredChartDrawings(snapshot.drawings);
        if (remoteDrawings.length === 0) return;

        const remoteSelection = normalizeChartDrawingSelection(
          remoteDrawings,
          snapshot.selected_drawing_id
        );
        setDrawingState({ key: storageKey, drawings: remoteDrawings });
        saveChartDrawings(storageKey, remoteDrawings);
        setSelectedDrawingId(remoteSelection);
      } catch {
        // A missing snapshot means this chart has not been saved remotely yet.
      }
    }

    void loadRemoteDrawings();

    return () => {
      cancelled = true;
    };
  }, [
    active,
    activeSelectedDrawingId,
    market,
    queueRemoteSave,
    stockId,
    storageKey,
    timeframe,
  ]);

  const updateDrawingState = useCallback(
    (
      nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
      nextSelectedDrawingId?: string | null,
      options: { recordHistory?: boolean } = {}
    ) => {
      const nextDrawings =
        typeof nextValue === "function" ? nextValue(drawings) : nextValue;
      const currentSnapshot = createChartDrawingSnapshot(
        drawings,
        activeSelectedDrawingId
      );
      const nextSnapshot = createChartDrawingSnapshot(
        nextDrawings,
        nextSelectedDrawingId === undefined
          ? activeSelectedDrawingId
          : nextSelectedDrawingId
      );

      if (chartDrawingSnapshotsEqual(currentSnapshot, nextSnapshot)) return;

      if (
        serializeChartDrawings(currentSnapshot.drawings) ===
        serializeChartDrawings(nextSnapshot.drawings)
      ) {
        setSelectedDrawingId(nextSnapshot.selectedDrawingId);
        return;
      }

      if (options.recordHistory !== false) {
        const currentPast = historyState.key === storageKey ? historyState.past : [];
        setHistoryState({
          key: storageKey,
          past: [...currentPast, currentSnapshot].slice(-50),
          future: [],
        });
      }

      storeDrawings(nextSnapshot.drawings, nextSnapshot.selectedDrawingId);
      setSelectedDrawingId(nextSnapshot.selectedDrawingId);
    },
    [
      activeSelectedDrawingId,
      drawings,
      historyState.key,
      historyState.past,
      storageKey,
      storeDrawings,
    ]
  );

  const updateDrawings = useCallback(
    (
      nextValue: ChartDrawing[] | ((current: ChartDrawing[]) => ChartDrawing[]),
      options: { recordHistory?: boolean } = {}
    ) => updateDrawingState(nextValue, undefined, options),
    [updateDrawingState]
  );

  const undo = useCallback(() => {
    if (!canUndo) return;

    const previousSnapshot = history.past[history.past.length - 1];
    if (!previousSnapshot) return;

    setHistoryState({
      key: storageKey,
      past: history.past.slice(0, -1),
      future: [
        createChartDrawingSnapshot(drawings, activeSelectedDrawingId),
        ...history.future,
      ].slice(0, 50),
    });
    storeDrawings(previousSnapshot.drawings, previousSnapshot.selectedDrawingId);
    setSelectedDrawingId(previousSnapshot.selectedDrawingId);
  }, [
    activeSelectedDrawingId,
    canUndo,
    drawings,
    history.future,
    history.past,
    storageKey,
    storeDrawings,
  ]);

  const redo = useCallback(() => {
    if (!canRedo) return;

    const nextSnapshot = history.future[0];
    if (!nextSnapshot) return;

    setHistoryState({
      key: storageKey,
      past: [
        ...history.past,
        createChartDrawingSnapshot(drawings, activeSelectedDrawingId),
      ].slice(-50),
      future: history.future.slice(1),
    });
    storeDrawings(nextSnapshot.drawings, nextSnapshot.selectedDrawingId);
    setSelectedDrawingId(nextSnapshot.selectedDrawingId);
  }, [
    activeSelectedDrawingId,
    canRedo,
    drawings,
    history.future,
    history.past,
    storageKey,
    storeDrawings,
  ]);

  const deleteSelected = useCallback(() => {
    if (!activeSelectedDrawingId) return;

    updateDrawings((current) =>
      current.filter((drawing) => drawing.id !== activeSelectedDrawingId)
    );
    setSelectedDrawingId(null);
  }, [activeSelectedDrawingId, updateDrawings]);

  const clear = useCallback(() => {
    if (drawings.length === 0 || !window.confirm(clearConfirmationMessage)) return;

    updateDrawings([]);
    setSelectedDrawingId(null);
  }, [clearConfirmationMessage, drawings.length, updateDrawings]);

  useEffect(() => {
    if (!active) return;

    function handleHistoryKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName.toLowerCase();

      if (tagName === "input" || tagName === "textarea" || target?.isContentEditable) return;
      if (!event.ctrlKey && !event.metaKey) return;

      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        if (!canUndo) return;
        event.preventDefault();
        undo();
        return;
      }

      if (key === "y" || (key === "z" && event.shiftKey)) {
        if (!canRedo) return;
        event.preventDefault();
        redo();
      }
    }

    window.addEventListener("keydown", handleHistoryKeyDown);
    return () => window.removeEventListener("keydown", handleHistoryKeyDown);
  }, [active, canRedo, canUndo, redo, undo]);

  return {
    state: {
      activeSelectedDrawingId,
      canRedo,
      canUndo,
      drawings,
      history,
    },
    actions: {
      clear,
      deleteSelected,
      redo,
      setSelectedDrawingId,
      undo,
      updateDrawingState,
      updateDrawings,
    },
  };
}

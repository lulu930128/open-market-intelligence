"use client";

import { useSyncExternalStore } from "react";

type ChartMode = "line" | "candles";
const storageKey = "omi.intraday.chart-mode.v1";
const changeEvent = "omi-intraday-chart-mode";
let memoryMode: ChartMode | null = null;

function readMode(): ChartMode {
  if (memoryMode !== null) return memoryMode;
  try {
    const saved = window.localStorage.getItem(storageKey);
    if (saved === "line" || saved === "candles") return saved;
  } catch {
    // Storage may be blocked; the preference still works for this page lifetime.
  }
  return "line";
}

function subscribe(onChange: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== storageKey && event.key !== null) return;
    memoryMode = null;
    onChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(changeEvent, onChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(changeEvent, onChange);
  };
}

function setMode(mode: ChartMode) {
  memoryMode = mode;
  try {
    window.localStorage.setItem(storageKey, mode);
  } catch {
    // Optional persistence must not prevent switching the chart.
  }
  window.dispatchEvent(new Event(changeEvent));
}

export function useIntradayChartMode() {
  const mode = useSyncExternalStore(subscribe, readMode, () => "line" as const);
  return [mode, setMode] as const;
}

"use client";

import { useSyncExternalStore } from "react";

// This is a UI invalidation token, never a calculation-parameter authority.
let revision = 0;
const listeners = new Set<() => void>();
const storageKey = "omi:technical-settings-changed";

function invalidate() {
  revision += 1;
  listeners.forEach((listener) => listener());
}

function onStorage(event: StorageEvent) {
  if (event.key === storageKey) invalidate();
}

function subscribe(listener: () => void) {
  if (listeners.size === 0) window.addEventListener("storage", onStorage);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}

export function notifyTechnicalSettingsChanged() {
  invalidate();
  try {
    window.localStorage.setItem(storageKey, `${Date.now()}:${revision}`);
  } catch {
    // Same-window invalidation still works when browser storage is disabled.
  }
}

export function useTechnicalSettingsRevision() {
  return useSyncExternalStore(subscribe, () => revision, () => 0);
}

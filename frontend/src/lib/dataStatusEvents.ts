"use client";

export type DataStatusMarket = "all" | "tw" | "us" | "jp" | "kr" | "crypto" | "other";
export type DataStatusLevel = "info" | "success" | "warning" | "error";

export type DataStatusEvent = {
  id: string;
  market: Exclude<DataStatusMarket, "all">;
  level: DataStatusLevel;
  title: string;
  message: string;
  source: string;
  contextKey?: string;
  contextLabel?: string;
  dedupeKey?: string;
  createdAt: string;
};

export type DataStatusFocus = {
  market: Exclude<DataStatusMarket, "all">;
  contextKey: string;
  label: string;
  source?: string;
};

type DataStatusEventInput = Omit<DataStatusEvent, "id" | "createdAt">;

const DATA_STATUS_EVENT_NAME = "omi:data-status-event";
const DATA_STATUS_FOCUS_EVENT_NAME = "omi:data-status-focus";
const MAX_DATA_STATUS_EVENTS = 50;

let dataStatusEvents: DataStatusEvent[] = [];
let dataStatusEventSequence = 0;
let dataStatusFocus: DataStatusFocus | null = null;

function matchesMarket(event: DataStatusEvent, market: DataStatusMarket) {
  return market === "all" || event.market === market;
}

export function getDataStatusEvents(market: DataStatusMarket = "all") {
  return dataStatusEvents.filter((event) => matchesMarket(event, market));
}

export function getDataStatusFocus(market: DataStatusMarket = "all") {
  if (!dataStatusFocus) return null;
  return market === "all" || dataStatusFocus.market === market ? dataStatusFocus : null;
}

export function emitDataStatusEvent(input: DataStatusEventInput) {
  if (typeof window === "undefined") return null;

  dataStatusEventSequence += 1;
  const event: DataStatusEvent = {
    ...input,
    id: `${Date.now()}-${dataStatusEventSequence}`,
    createdAt: new Date().toISOString(),
  };

  const previousEvents = event.dedupeKey
    ? dataStatusEvents.filter((item) => item.dedupeKey !== event.dedupeKey)
    : dataStatusEvents;
  dataStatusEvents = [event, ...previousEvents].slice(0, MAX_DATA_STATUS_EVENTS);
  window.dispatchEvent(new CustomEvent(DATA_STATUS_EVENT_NAME, { detail: event }));

  return event;
}

export function setDataStatusFocus(input: DataStatusFocus) {
  if (typeof window === "undefined") return null;

  dataStatusFocus = input;
  window.dispatchEvent(new CustomEvent(DATA_STATUS_FOCUS_EVENT_NAME, { detail: input }));
  return input;
}

export function clearDataStatusFocus(contextKey?: string) {
  if (typeof window === "undefined") return;
  if (contextKey && dataStatusFocus?.contextKey !== contextKey) return;

  dataStatusFocus = null;
  window.dispatchEvent(new CustomEvent(DATA_STATUS_FOCUS_EVENT_NAME, { detail: null }));
}

export function subscribeDataStatusEvents(
  market: DataStatusMarket,
  onEventsChange: (events: DataStatusEvent[]) => void
) {
  if (typeof window === "undefined") return () => {};

  const handleEvent = () => {
    onEventsChange(getDataStatusEvents(market));
  };

  window.addEventListener(DATA_STATUS_EVENT_NAME, handleEvent);
  handleEvent();

  return () => {
    window.removeEventListener(DATA_STATUS_EVENT_NAME, handleEvent);
  };
}

export function subscribeDataStatusFocus(
  market: DataStatusMarket,
  onFocusChange: (focus: DataStatusFocus | null) => void
) {
  if (typeof window === "undefined") return () => {};

  const handleEvent = () => {
    onFocusChange(getDataStatusFocus(market));
  };

  window.addEventListener(DATA_STATUS_FOCUS_EVENT_NAME, handleEvent);
  handleEvent();

  return () => {
    window.removeEventListener(DATA_STATUS_FOCUS_EVENT_NAME, handleEvent);
  };
}

"use client";

export type DataStatusMarket = "all" | "tw" | "us" | "jp" | "crypto" | "other";
export type DataStatusLevel = "info" | "success" | "warning" | "error";

export type DataStatusEvent = {
  id: string;
  market: Exclude<DataStatusMarket, "all">;
  level: DataStatusLevel;
  title: string;
  message: string;
  source: string;
  createdAt: string;
};

type DataStatusEventInput = Omit<DataStatusEvent, "id" | "createdAt">;

const DATA_STATUS_EVENT_NAME = "omi:data-status-event";
const MAX_DATA_STATUS_EVENTS = 50;

let dataStatusEvents: DataStatusEvent[] = [];
let dataStatusEventSequence = 0;

function matchesMarket(event: DataStatusEvent, market: DataStatusMarket) {
  return market === "all" || event.market === market;
}

export function getDataStatusEvents(market: DataStatusMarket = "all") {
  return dataStatusEvents.filter((event) => matchesMarket(event, market));
}

export function emitDataStatusEvent(input: DataStatusEventInput) {
  if (typeof window === "undefined") return null;

  dataStatusEventSequence += 1;
  const event: DataStatusEvent = {
    ...input,
    id: `${Date.now()}-${dataStatusEventSequence}`,
    createdAt: new Date().toISOString(),
  };

  dataStatusEvents = [event, ...dataStatusEvents].slice(0, MAX_DATA_STATUS_EVENTS);
  window.dispatchEvent(new CustomEvent(DATA_STATUS_EVENT_NAME, { detail: event }));

  return event;
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

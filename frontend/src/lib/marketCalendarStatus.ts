import { fetchJson } from "@/lib/api";

export type MarketCalendarReleaseWindow = {
  key: string;
  label: string;
  release_time: string;
  release_at: string;
  next_release_at: string;
  expected_trade_date: string | null;
  status: string;
  is_released: boolean;
};

export type MarketCalendarSession = {
  preopen_time?: string | null;
  open_time: string;
  close_time: string;
  next_session_start_at: string;
  is_polling_window: boolean;
  is_after_close: boolean;
};

export type MarketCalendarMarketStatus = {
  market: "tw" | "us" | string;
  timezone: string;
  checked_at: string;
  date: string;
  is_trading_day: boolean;
  phase: string;
  reason: string;
  holiday_name: string | null;
  previous_trading_day: string;
  next_trading_day: string;
  session: MarketCalendarSession;
  release_windows: Record<string, MarketCalendarReleaseWindow>;
};

export type MarketCalendarStatusEnvelope = {
  kind: "market_calendar_status";
  generated_at: string;
  markets: Partial<Record<"tw" | "us", MarketCalendarMarketStatus>>;
};

const snapshots: Partial<Record<"tw" | "us", MarketCalendarMarketStatus>> = {};

export function setMarketCalendarStatusSnapshot(
  market: "tw" | "us",
  status: MarketCalendarMarketStatus | null | undefined
) {
  if (!status) return;

  snapshots[market] = status;
}

export function setMarketCalendarStatusEnvelope(
  envelope: MarketCalendarStatusEnvelope | null | undefined
) {
  if (!envelope?.markets) return;

  setMarketCalendarStatusSnapshot("tw", envelope.markets.tw);
  setMarketCalendarStatusSnapshot("us", envelope.markets.us);
}

export function getMarketCalendarStatusSnapshot(market: "tw" | "us") {
  return snapshots[market] ?? null;
}

export async function refreshMarketCalendarStatus(market: "all" | "tw" | "us" = "all") {
  const envelope = await fetchJson<MarketCalendarStatusEnvelope>(
    "/api/market/calendar-status",
    { market }
  );
  setMarketCalendarStatusEnvelope(envelope);
  return envelope;
}

export function msUntilIsoTime(value: string | null | undefined, now = new Date()) {
  if (!value) return null;

  const targetMs = Date.parse(value);
  if (!Number.isFinite(targetMs)) return null;

  return Math.max(1_000, targetMs - now.getTime());
}

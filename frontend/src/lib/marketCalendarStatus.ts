import { fetchJson } from "@/lib/api";

export type MarketCode = "tw" | "us" | "jp" | "kr";

export type MarketCalendarReleaseWindow = {
  key: string;
  label: string;
  release_time: string;
  release_at: string;
  next_release_at: string;
  expected_trade_date: string | null;
  expected_data_key?: string | null;
  status: string;
  is_released: boolean;
  assumption?: string | null;
};

export type MarketCalendarSession = {
  preopen_time?: string | null;
  pre_market_open_time?: string | null;
  open_time: string;
  close_time: string;
  after_hours_close_time?: string | null;
  lunch_start_time?: string | null;
  lunch_end_time?: string | null;
  next_session_start_at: string;
  is_polling_window: boolean;
  is_extended_polling_window?: boolean;
  is_after_close: boolean;
};

export type MarketCalendarPresentationSession = {
  trade_date: string;
  state: string;
  is_current_trading_day: boolean;
  rollover_time: string;
  next_transition_at: string;
};

export type MarketCalendarMarketStatus = {
  market: MarketCode | string;
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
  presentation_session?: MarketCalendarPresentationSession | null;
  release_windows: Record<string, MarketCalendarReleaseWindow>;
  calendar_source?: string | null;
  calendar_verified_years?: number[];
  calendar_limit?: string | null;
  calendar_cache_status?: "current" | "degraded" | "stale" | "fallback" | string;
  calendar_last_refreshed_at?: string | null;
  calendar_source_url?: string | null;
  calendar_warning?: string | null;
};

export type MarketCalendarStatusEnvelope = {
  kind: "market_calendar_status";
  generated_at: string;
  markets: Partial<Record<MarketCode, MarketCalendarMarketStatus>>;
};

const snapshots: Partial<Record<MarketCode, MarketCalendarMarketStatus>> = {};

export function setMarketCalendarStatusSnapshot(
  market: MarketCode,
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
  setMarketCalendarStatusSnapshot("jp", envelope.markets.jp);
  setMarketCalendarStatusSnapshot("kr", envelope.markets.kr);
}

export function getMarketCalendarStatusSnapshot(market: MarketCode) {
  return snapshots[market] ?? null;
}

export async function refreshMarketCalendarStatus(
  market: "all" | MarketCode = "all"
) {
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

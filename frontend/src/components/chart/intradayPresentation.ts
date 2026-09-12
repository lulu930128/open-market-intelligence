import type { IntradayTrendPoint, TaiwanStockQuoteDepthRead } from "@/types/market";

/** Display-only values supplied by a session-level owner, never derived from bars. */
export type IntradaySessionStats = {
  open: number | null;
  high: number | null;
  low: number | null;
  totalVolume: number | null;
  lastTradeVolume: number | null;
  volumeUnit: string;
  source: string | null;
  asOf: string | null;
  status: string;
};

export function taiwanIntradaySessionStats(
  quote: TaiwanStockQuoteDepthRead | null,
  tradeDate: string | null,
): IntradaySessionStats | null {
  if (!quote || !tradeDate || quote.trade_date !== tradeDate) return null;
  return {
    open: quote.open_price,
    high: quote.high_price,
    low: quote.low_price,
    totalVolume: quote.volume_status === "unavailable" ? null : quote.total_volume_lots,
    lastTradeVolume:
      quote.actual_trade_occurred === true && quote.last_trade_volume_status === "available"
        ? quote.last_trade_volume_lots ?? null
        : null,
    volumeUnit: "lots",
    source: quote.source,
    asOf: quote.quote_time,
    status: quote.freshness.status,
  };
}

export function intradayCandle(point: IntradayTrendPoint) {
  const { open, high, low } = point;
  const close = point.close ?? point.price;
  if (
    point.synthetic || point.display_eligible === false ||
    point.bar_type?.endsWith("_marker") || point.bar_type === "post_close_summary" ||
    typeof open !== "number" || !Number.isFinite(open) ||
    typeof high !== "number" || !Number.isFinite(high) ||
    typeof low !== "number" || !Number.isFinite(low) ||
    !Number.isFinite(close) || low > Math.min(open, close) || high < Math.max(open, close)
  ) return null;
  return { open, high, low, close };
}

export function intradayBarIsForming(point: IntradayTrendPoint) {
  return point.is_partial === true || point.finalized === false ||
    point.finalization === "provisional" || point.finalization === "partial";
}

/** Keep the timestamp's supplied session offset; do not reinterpret it in host time. */
export function compactIntradayTimestamp(value: string | null | undefined) {
  if (!value) return "—";
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)/);
  return match ? `${match[2]}/${match[3]} ${match[4]}` : value;
}

export function selectIntradayTimeTicks<T extends { minutes: number }>(
  ticks: T[], startMinutes: number, endMinutes: number, width: number,
): T[] {
  if (ticks.length < 3) return ticks;
  const selected = [ticks[0]];
  const last = ticks[ticks.length - 1];
  const pixelsPerMinute = width / Math.max(1, endMinutes - startMinutes);
  for (const tick of ticks.slice(1, -1)) {
    if ((tick.minutes - selected[selected.length - 1].minutes) * pixelsPerMinute >= 60 &&
      (last.minutes - tick.minutes) * pixelsPerMinute >= 60) selected.push(tick);
  }
  return [...selected, last];
}

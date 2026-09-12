import { expect, test } from "@playwright/test";
import { aggregateIntradayPoints, taiwanIntradaySession } from "@/components/IntradayTrendChart";
import { compactIntradayTimestamp, intradayBarIsForming, intradayCandle, selectIntradayTimeTicks, taiwanIntradaySessionStats } from "@/components/chart/intradayPresentation";
import type { IntradayTrendPoint, TaiwanStockQuoteDepthRead } from "@/types/market";

const bar: IntradayTrendPoint = {
  time: "2026-09-11T09:00:00+08:00", price: 101, close: 101,
  open: 100, high: 103, low: 99, volume: 5000,
  synthetic: false, finalized: true, finalization: "final",
};

test("candles require actual valid OHLC and exclude quote and close markers", () => {
  expect(intradayCandle(bar)).toEqual({ open: 100, high: 103, low: 99, close: 101 });
  for (const patch of [{ open: null }, { high: NaN }, { low: 102 }, { high: 100 }, { synthetic: true }, { bar_type: "session_close_marker" }, { bar_type: "official_close_marker" }, { display_eligible: false }]) {
    expect(intradayCandle({ ...bar, ...patch })).toBeNull();
  }
  expect(intradayCandle({ ...bar, open: 101, high: 101, low: 101 })).not.toBeNull();
});

test("line aggregation never manufactures candles from price-only points", () => {
  const quote = { ...bar, time: "2026-09-11T09:01:00+08:00", open: null, high: null, low: null };
  for (const interval of [1, 5, 15] as const) {
    const result = aggregateIntradayPoints([quote], interval, taiwanIntradaySession);
    expect(result[0].price).toBe(101);
    expect(intradayCandle(result[0])).toBeNull();
  }
  const mixed = aggregateIntradayPoints([bar, quote], 5, taiwanIntradaySession);
  expect(intradayCandle(mixed[0])).toBeNull();
});

test("interval candles preserve OHLC, partial state and separate close events", () => {
  const partial = { ...bar, time: "2026-09-11T09:01:00+08:00", open: 101, high: 105, close: 104, price: 104, finalized: false, finalization: "provisional" };
  const marker = { ...bar, time: "2026-09-11T13:30:00+08:00", bar_type: "official_close_marker", indicator_eligible: false, display_eligible: true };
  const result = aggregateIntradayPoints([bar, partial, marker], 5, taiwanIntradaySession);
  expect(result).toHaveLength(2);
  expect(intradayCandle(result[0])).toEqual({ open: 100, high: 105, low: 99, close: 104 });
  expect(intradayBarIsForming(result[0])).toBe(true);
  expect(intradayCandle(result[1])).toBeNull();
});

const quote = {
  stock_id: "2330", trade_date: "2026-09-11", open_price: 2430, high_price: 2430, low_price: 2405,
  total_volume_lots: 18053, last_trade_volume_lots: 3747,
  volume_status: "available", last_trade_volume_status: "available", actual_trade_occurred: true,
  source: "fixture", quote_time: "2026-09-11T13:30:00+08:00", freshness: { status: "stale" },
} as TaiwanStockQuoteDepthRead;

test("session summary preserves quote identity, lots, missing, zero and stale", () => {
  expect(taiwanIntradaySessionStats(quote, "2026-09-12")).toBeNull();
  expect(taiwanIntradaySessionStats(quote, null)).toBeNull();
  expect(taiwanIntradaySessionStats(quote, "2026-09-11")).toMatchObject({ totalVolume: 18053, lastTradeVolume: 3747, status: "stale" });
  expect(taiwanIntradaySessionStats({ ...quote, total_volume_lots: 0 }, "2026-09-11")?.totalVolume).toBe(0);
  expect(taiwanIntradaySessionStats({ ...quote, volume_status: "unavailable", actual_trade_occurred: false }, "2026-09-11")).toMatchObject({ totalVolume: null, lastTradeVolume: null });
});

test("timestamp formatting preserves the source date and time", () => {
  expect(compactIntradayTimestamp("2026-09-11T16:00:00-04:00")).toBe("09/11 16:00:00");
  expect(compactIntradayTimestamp(null)).toBe("—");
});

test("narrow time axes reserve space for the closing label", () => {
  const ticks = selectIntradayTimeTicks(taiwanIntradaySession.timeTicks, 540, 810, 230);
  expect(ticks.map((tick) => tick.label)).toEqual(["09:00", "11:00", "13:30"]);
  expect(selectIntradayTimeTicks(taiwanIntradaySession.timeTicks, 540, 810, 800)).toHaveLength(6);
});

test("aggregated volume distinguishes confirmed zero from missing", () => {
  expect(aggregateIntradayPoints([{ ...bar, volume: 0 }], 5, taiwanIntradaySession)[0].volume).toBe(0);
  expect(aggregateIntradayPoints([bar, { ...bar, volume: null }], 5, taiwanIntradaySession)[0].volume).toBeNull();
});

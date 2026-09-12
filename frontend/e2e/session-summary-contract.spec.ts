import { expect, test } from "@playwright/test";
import { sessionSummaryMatches, type TaiwanSessionSummary, type SessionMetric } from "../src/components/chart/useTaiwanSessionSummary";

function payload(): TaiwanSessionSummary {
  const metric: SessionMetric = { value: null, unit: "TWD", status: "unavailable", estimated: false,
    method: "test", trade_date: "2026-09-11", as_of: null, source: "test", scope: "regular",
    freshness: "stale", coverage: "partial", sample_days: null, limitations: [] };
  return { contract_version: "tw.chart.session_summary.v1", instrument_id: "2330", trade_date: "2026-09-11",
    base_interval: "1m", series_revision: "test", presentation_session_state: "previous_session",
    official_close_status: "confirmed_latest_session", reference_type: "prior_regular_close", limitations: [],
    metrics: Object.fromEntries(["open", "high", "low", "reference", "average", "volume", "turnover", "last_volume", "previous_volume", "bid", "ask", "range_pct", "relative_volume", "vwap_distance_pct"].map(key => [key, { ...metric }])) };
}

test("summary accepts explicit missing and zero without changing stale status", () => {
  const data = payload(); data.metrics.volume.value = 0;
  expect(sessionSummaryMatches(data, "2330", "2026-09-11")).toBeTruthy();
  expect(data.metrics.volume.freshness).toBe("stale");
});

test("summary rejects another stock, date or selected chart interval", () => {
  const data = payload();
  expect(sessionSummaryMatches(data, "2317", "2026-09-11")).toBeFalsy();
  expect(sessionSummaryMatches(data, "2330", "2026-09-10")).toBeFalsy();
  expect(sessionSummaryMatches({ ...data, base_interval: "5m" } as unknown as TaiwanSessionSummary, "2330", "2026-09-11")).toBeFalsy();
});

test("malformed summary must not be presented as ready", () => {
  const data = payload(); data.metrics.average.value = Number.NaN;
  expect(sessionSummaryMatches(data, "2330", "2026-09-11")).toBeFalsy();
  delete data.metrics.average;
  expect(sessionSummaryMatches(data, "2330", "2026-09-11")).toBeFalsy();
});

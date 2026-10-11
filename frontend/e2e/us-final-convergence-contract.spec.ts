import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";

import {
  projectUSCurrentSessionHeadline,
  projectUSIntradayIndicatorPoint,
  usDailySnapshotRevision,
  projectUSVisibleDailyChartPoints,
} from "../src/components/stock-detail/usStockDetailCanonicalProjection";
import { usTruthResponse } from "./fixtures/usMarketTruth";
import { projectUSMarketTapeSnapshot } from "../src/components/market-dashboard/tape/usMarketTapeCanonicalProjection";
import type {
  IntradayTrendPoint,
  IntradayTrendResponse,
  USMarketIndexItemRead,
  USOhlcChartRead,
} from "../src/types/market";

test("provisional Daily is display-only and the actual Tape reader ignores it", async () => {
  const chart = {
    timeframe: "daily", point_count: 2,
    points: [{ time: "2026-10-06", close: 100 }, { time: "2026-10-07", close: 120 }],
    intraday_overlay: { point: { time: "2026-10-08", close: 10000 }, finalization: "provisional" },
  } as USOhlcChartRead;
  const visible = projectUSVisibleDailyChartPoints(chart);
  expect(visible.map((point) => point.close)).toEqual([100, 120, 10000]);
  expect(chart.points.map((point) => point.close)).toEqual([100, 120]);
  expect(chart.point_count).toBe(2);
  const source = readFileSync("src/components/market-dashboard/tape/useRegionalMarketTapeState.ts", "utf8");
  const reader = source.slice(source.indexOf("async function fetchUsMarketTapeReferenceSnapshot"), source.indexOf("async function fetchJpMarketTapeSnapshot"));
  const average = source.slice(source.indexOf("function averageLastNumbers"), source.indexOf("function sumJpIntradayVolume"));
  const script = ts.transpileModule(`${average}\n${reader}\nfetchUsMarketTapeReferenceSnapshot({symbol: "^GSPC"});`, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
  const result = await runInNewContext(script, { fetchJson: async () => chart });
  expect(result).toMatchObject({ close: 120, previousClose: 100, change: 20, ma20: 110, pointCount: 2, asOf: "2026-10-07" });
  chart.intraday_overlay = null;
  expect(projectUSVisibleDailyChartPoints(chart)).toBe(chart.points);
});

test("supplemental partial failure preserves successful fields and a later retry can succeed", async () => {
  const source = readFileSync("src/components/USStockDetailPanel.tsx", "utf8");
  const loader = source.slice(source.indexOf("async function fetchUsSupplementalData("), source.indexOf("const usIntradaySession:"));
  let fail = true;
  const requests: string[] = [];
  const fetch = async (path: string) => {
    requests.push(path);
    if (path.endsWith("/financials") && fail) throw new Error("fixture 503");
    return path.endsWith("/facts") ? [{ metric: "revenue" }] : { fixture: path };
  };
  const script = ts.transpileModule(`${loader}\nfetchUsSupplementalData("AAPL", "financials");`, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
  const partial = await runInNewContext(script, { fetchJson: fetch, fetchOptionalJson: fetch });
  expect(partial.factData).toEqual([{ metric: "revenue" }]);
  expect(partial.fundamentalData).toBeTruthy();
  expect(partial.financialData).toBeUndefined();
  expect(partial.requestErrors).toHaveLength(1);
  fail = false;
  const retried = await runInNewContext(script, { fetchJson: fetch, fetchOptionalJson: fetch });
  expect(retried.financialData).toBeTruthy();
  expect(retried.requestErrors).toHaveLength(0);
  expect(requests.filter((path) => path.endsWith("/financials"))).toHaveLength(2);
});

test("diagnostic metadata updates keep callback identity stable and use the latest label", () => {
  const source = readFileSync("src/components/USStockDetailPanel.tsx", "utf8").replace(/\r\n/g, "\n");
  const owner = source.slice(source.indexOf("  const dataStatusContextRef ="), source.indexOf("  const publishIntradaySourceStatus ="));
  const script = ts.transpileModule(`
    function render(selectedSymbol, dataStatusSource, dataStatusContextKey, dataStatusContextLabel) {
      ${owner}
      return publishDetailDataStatus;
    }
    render;
  `, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
  // Minimal hook host: test the actual callback/dependency contract, not DOM behavior.
  let ref: { current: unknown } | undefined;
  let callback: ((...args: unknown[]) => void) | undefined;
  const events: Array<{ contextLabel: string }> = [];
  const render = runInNewContext(script, {
    useRef: (value: unknown) => (ref ??= { current: value }),
    useEffect: (effect: () => void) => effect(),
    useCallback: (fn: (...args: unknown[]) => void, dependencies: unknown[]) => {
      expect(dependencies).toHaveLength(0);
      return callback ??= fn;
    },
    emitDataStatusEvent: (event: { contextLabel: string }) => events.push(event),
  });
  const before = render("AAPL", "detail", "us:AAPL", "AAPL");
  const after = render("AAPL", "detail", "us:AAPL", "AAPL Apple Inc.");
  expect(after).toBe(before);
  after("request failed", "fixture error");
  expect(events[0].contextLabel).toBe("AAPL Apple Inc.");
  const selectionStart = source.indexOf("    const generation = requestSeq.current + 1;");
  const selectionEnd = source.indexOf("  useEffect(() => {\n    if (!selectedSymbol || timeframe !== \"today\") return;", selectionStart);
  expect(selectionStart).toBeGreaterThan(0);
  expect(selectionEnd).toBeGreaterThan(selectionStart);
  const selection = source.slice(selectionStart, selectionEnd);
  expect(selection).not.toContain("dataStatusContextLabel");
});

test("US headline presents backend selected close and linked metrics without rebuilding price truth", () => {
  const truth = usTruthResponse("MSFT");
  expect(projectUSCurrentSessionHeadline(truth)).toMatchObject({
    latestPrice: 516.17, referencePrice: 497.93,
    tradeDate: "2026-09-25", referenceTradeDate: "2026-09-24",
    change: 18.24, changePct: Number(truth.change_metrics[0].percent_change),
  });
  // Metric precision/rounding is owned by the backend, not local subtraction.
  truth.change_metrics[0].absolute_change = "18.2401";
  expect(projectUSCurrentSessionHeadline(truth).change).toBe(18.2401);
  truth.change_metrics[0].observation_id = "unrelated-quote";
  expect(projectUSCurrentSessionHeadline(truth).change).toBeNull();
});

test("US headline keeps unavailable and malformed evidence unknown", () => {
  const truth = usTruthResponse("MSFT");
  truth.headline_observation!.display_usable = false;
  expect(projectUSCurrentSessionHeadline(truth)).toMatchObject({ latestPrice: null, change: null });
  truth.headline_observation!.display_usable = true;
  truth.headline_observation!.price = "";
  expect(projectUSCurrentSessionHeadline(truth).latestPrice).toBeNull();
  truth.headline_observation!.price = "516.17";
  truth.comparison_references[0].calculation_eligible = false;
  expect(projectUSCurrentSessionHeadline(truth)).toMatchObject({ referencePrice: 497.93, change: null });
  truth.comparison_references[0].reference_trade_date = null;
  expect(projectUSCurrentSessionHeadline(truth).referencePrice).toBeNull();
  expect(projectUSCurrentSessionHeadline(null)).toMatchObject({ latestPrice: null, referencePrice: null, change: null });
});

test("Daily invalidation consumes backend daily and calendar revisions, not quote ticks", () => {
  const truth = usTruthResponse("MSFT");
  const revision = usDailySnapshotRevision(truth);
  truth.truth_revision = "d".repeat(64);
  truth.evaluated_at = "2026-09-27T06:01:00Z";
  expect(usDailySnapshotRevision(truth)).toBe(revision);
  truth.component_revisions.daily_revision = "e".repeat(64);
  expect(usDailySnapshotRevision(truth)).not.toBe(revision);
  const corrected = usDailySnapshotRevision(truth);
  truth.component_revisions.calendar_revision = "f".repeat(64);
  expect(usDailySnapshotRevision(truth)).not.toBe(corrected);
});

test("US market tape projects backend headline metrics instead of Daily D-2", () => {
  const reference = {
    symbol: "^GSPC",
    displaySymbol: "SPX",
    name: "S&P 500",
    exchange: "CBOE",
    note: "Large-cap benchmark",
    close: 190,
    change: 10,
    changePct: 5.5555555556,
    priceVsMa20: null,
    volume: null,
    pointCount: 60,
    asOf: "2026-09-03",
    source: "daily" as const,
    previousClose: 180,
    referenceTradeDate: "2026-09-02",
    truthRevision: null,
    ma20: 185,
  };
  const headline = {
    contract_version: "omi.market.us_index_item.v1",
    canonical_symbol: "^GSPC",
    label: "S&P 500",
    instrument_type: "index",
    value: "200",
    previous_close: "190",
    change: "10",
    change_pct: "5.2631578947",
    trade_date: "2026-09-04",
    event_at: "2026-09-04T14:30:00Z",
    observation_kind: "current_session_trade",
    comparison_purpose: "headline_change",
    reference_trade_date: "2026-09-03",
    reference_kind: "completed_daily",
    selected_provider: "test",
    selected_source: "test.quote",
    selection_reason: "CURRENT_SESSION_SELECTED",
    fallback_used: false,
    freshness_status: "live",
    provider_snapshot_freshness: "fresh",
    trade_recency: "current",
    current_for_requested_session: true,
    facts_usable: true,
    decision_usable: true,
    truth_revision: "a".repeat(64),
    observation_id: "test-observation",
    limitations: [],
  } satisfies USMarketIndexItemRead;

  const projected = projectUSMarketTapeSnapshot(reference, headline, "market_closed");

  expect(projected).toMatchObject({
    close: 200,
    previousClose: 190,
    change: 10,
    referenceTradeDate: "2026-09-03",
    source: "market_truth",
    truthRevision: "a".repeat(64),
    marketSession: "market_closed",
  });
  expect(projected?.change).not.toBe(20);
});

test("intraday indicator projection preserves backend metadata and usability", () => {
  const point = {
    time: "2026-09-04T14:31:00Z",
    price: 210.5,
    volume: 42,
    open: 210,
    high: 211,
    low: 209.5,
    technical_algorithm_version: "backend.test.v9",
    price_basis: "backend_price_basis",
    calculation_role: "backend_role",
    bar_status: "backend_partial",
    decision_usable: false,
    volume_based_decision_usable: false,
    vwap_value: 210.2,
    twap_value: 210.1,
  } satisfies IntradayTrendPoint;
  const response = {
    stock_id: "TSM",
    symbol: "TSM",
    source: "backend.source",
    previous_close: 209,
    point_count: 1,
    points: [point],
    technical_algorithm_version: "backend.root.v3",
    technical_parameter_contract: { rsi_period: 7, session_reset: false },
  } satisfies IntradayTrendResponse;

  const projected = projectUSIntradayIndicatorPoint(point, response);

  expect(projected.algorithm_version).toBe("backend.test.v9");
  expect(projected.parameter_contract).toEqual({ rsi_period: 7, session_reset: false });
  expect(projected.price_basis).toBe("backend_price_basis");
  expect(projected.bar_status).toBe("backend_partial");
  expect(projected.decision_usable).toBe(false);
  expect(projected.volume_based_decision_usable).toBe(false);
  expect(projected.vwap).toBe(210.2);
  expect(projected.twap).toBe(210.1);
});

import { expect, test } from "@playwright/test";

import {
  projectUSCurrentSessionHeadline,
  projectUSIntradayIndicatorPoint,
  usDailySnapshotRevision,
} from "../src/components/stock-detail/usStockDetailCanonicalProjection";
import { usTruthResponse } from "./fixtures/usMarketTruth";
import { projectUSMarketTapeSnapshot } from "../src/components/market-dashboard/tape/usMarketTapeCanonicalProjection";
import type {
  IntradayTrendPoint,
  IntradayTrendResponse,
  USMarketIndexItemRead,
} from "../src/types/market";

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

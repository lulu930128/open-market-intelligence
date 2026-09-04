import { expect, test } from "@playwright/test";

import {
  projectUSCurrentSessionHeadline,
  projectUSIntradayIndicatorPoint,
  selectMonotonicUSHeadlineQuote,
} from "../src/components/stock-detail/usStockDetailCanonicalProjection";
import { projectUSMarketTapeSnapshot } from "../src/components/market-dashboard/tape/usMarketTapeCanonicalProjection";
import type {
  IntradayTrendPoint,
  IntradayTrendResponse,
  USMarketIndexItemRead,
  USResolvedQuoteSnapshot,
} from "../src/types/market";

function quote(symbol: string, eventAt: string, price: string): USResolvedQuoteSnapshot {
  return {
    kind: "resolved_quote",
    schema_version: "omi.market.quote.snapshot.v1",
    compatibility_schema_versions: [],
    status: "current",
    selected_provider: "test",
    selected_source: "test.quote",
    selected_session: "regular",
    selected_event_at: eventAt,
    fallback_used: false,
    selection_reason: null,
    facts_usable: true,
    research_usable: true,
    limitations: [],
    candidates: [],
    quote: {
      market: "US",
      symbol,
      venue: null,
      instrument_type: "stock",
      trade_date: eventAt.slice(0, 10),
      currency: "USD",
      state: "trade",
      trade_state: "trade_observed",
      last_trade_price: price,
      open_price: null,
      high_price: null,
      low_price: null,
      previous_close: null,
      event_at: eventAt,
      received_at: eventAt,
      fetched_at: eventAt,
    },
  };
}

test("headline quote accepts only same-symbol monotonic evidence", () => {
  const newer = quote("TSM", "2026-09-04T14:31:00Z", "210.50");
  const older = quote("TSM", "2026-09-04T14:30:00Z", "209.00");

  expect(
    selectMonotonicUSHeadlineQuote(newer, older, {
      expectedSymbol: "TSM",
      currentGeneration: 1,
      candidateGeneration: 2,
    }).snapshot
  ).toBe(newer);
  expect(
    selectMonotonicUSHeadlineQuote(older, newer, {
      expectedSymbol: "TSM",
      currentGeneration: 2,
      candidateGeneration: 1,
    }).snapshot
  ).toBe(newer);
  expect(
    selectMonotonicUSHeadlineQuote(newer, quote("MU", "2026-09-04T14:32:00Z", "120"), {
      expectedSymbol: "TSM",
      currentGeneration: 1,
      candidateGeneration: 3,
    }).snapshot
  ).toBe(newer);

  const missing = { ...newer, selected_event_at: null, quote: null };
  expect(
    selectMonotonicUSHeadlineQuote(newer, missing, {
      expectedSymbol: "TSM",
      currentGeneration: 2,
      candidateGeneration: 3,
    }).snapshot
  ).toBe(missing);
  expect(
    selectMonotonicUSHeadlineQuote(newer, missing, {
      expectedSymbol: "TSM",
      currentGeneration: 3,
      candidateGeneration: 2,
    }).snapshot
  ).toBe(newer);
  expect(
    selectMonotonicUSHeadlineQuote(missing, older, {
      expectedSymbol: "TSM",
      currentGeneration: 3,
      candidateGeneration: 2,
    }).snapshot
  ).toBe(missing);
});

test("US current-session headline uses only the canonical change reference", () => {
  const projected = projectUSCurrentSessionHeadline({
    currentObservationPrice: 200,
    quotePrice: 201,
    changeReferencePrice: 190,
    changeReferenceTradeDate: "2026-09-03",
    changeReferenceType: "headline_change",
    changeReferenceStatus: "current",
  });

  expect(projected.latestPrice).toBe(200);
  expect(projected.referencePrice).toBe(190);
  expect(projected.referenceTradeDate).toBe("2026-09-03");
  expect(projected.change).toBe(10);
  expect(projected.changePct).toBeCloseTo(5.2631578947);

  expect(
    projectUSCurrentSessionHeadline({
      currentObservationPrice: 200,
      quotePrice: null,
      changeReferencePrice: 180,
      changeReferenceTradeDate: "2026-09-02",
      changeReferenceType: "unavailable",
      changeReferenceStatus: "missing",
    })
  ).toMatchObject({ referencePrice: null, change: null, changePct: null });
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

  const projected = projectUSMarketTapeSnapshot(reference, headline);

  expect(projected).toMatchObject({
    close: 200,
    previousClose: 190,
    change: 10,
    referenceTradeDate: "2026-09-03",
    source: "market_truth",
    truthRevision: "a".repeat(64),
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

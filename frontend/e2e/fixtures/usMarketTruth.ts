import type { USMarketTruthRead } from "../../src/types/usMarketTruth";

export function usTruthResponse(
  symbol: string,
  overrides: Partial<USMarketTruthRead> = {}
): USMarketTruthRead {
  return {
    contract_version: "omi.market.us_truth_snapshot.v1",
    instrument: { market: "US", symbol },
    evaluated_at: "2026-09-27T06:00:00Z",
    market_phase: "market_closed",
    truth_revision: "a".repeat(64),
    component_revisions: { daily_revision: "b".repeat(64), calendar_revision: "c".repeat(64) },
    headline_observation: {
      observation_id: "daily-final",
      kind: "close",
      price: "516.17",
      trade_date: "2026-09-25",
      event_at: "2026-09-25T20:00:00Z",
      freshness: "fresh",
      display_usable: true,
      selected_provider: "fixture",
      selected_source: "fixture.daily",
      limitations: [],
    },
    comparison_references: [{
      reference_id: "prior-close",
      purpose: "headline_change",
      price: "497.93",
      reference_trade_date: "2026-09-24",
      calculation_eligible: true,
      display_usable: true,
    }],
    change_metrics: [{
      purpose: "headline_change",
      observation_id: "daily-final",
      reference_id: "prior-close",
      absolute_change: "18.24",
      percent_change: "3.6631655051914928",
      display_usable: true,
    }],
    ...overrides,
  };
}

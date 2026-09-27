/** Fields consumed from the existing omi.market.us_truth_snapshot.v1 contract. */
export type USMarketTruthRead = {
  contract_version: "omi.market.us_truth_snapshot.v1";
  instrument: { market: "US"; symbol: string };
  evaluated_at: string;
  truth_revision: string;
  market_phase: string;
  component_revisions: {
    daily_revision: string | null;
    calendar_revision: string;
  };
  headline_observation: {
    observation_id: string;
    kind: string;
    price: string | null;
    trade_date: string | null;
    event_at: string;
    freshness: string;
    display_usable: boolean;
    selected_provider: string;
    selected_source: string;
    limitations: string[];
  } | null;
  comparison_references: Array<{
    reference_id: string;
    purpose: string;
    price: string | null;
    reference_trade_date: string | null;
    calculation_eligible: boolean;
    display_usable: boolean;
  }>;
  change_metrics: Array<{
    purpose: string;
    observation_id: string | null;
    reference_id: string | null;
    absolute_change: string | null;
    percent_change: string | null;
    display_usable: boolean;
  }>;
};

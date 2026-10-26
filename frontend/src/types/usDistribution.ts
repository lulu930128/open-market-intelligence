export type USDistributionCounts = {
  universe: number; evaluated: number; observed_price: number; comparable: number;
  up: number; down: number; flat: number; unknown: number; no_trade: number;
  fresh: number; stale: number; missing: number; partial: number; not_covered: number;
};

export type USDistributionGroup = {
  group_id: string; dimension: "sector" | "industry"; provider: string | null;
  sector: string | null; industry: string | null; classification_status: "known" | "unknown";
  counts: USDistributionCounts; avg_return_pct: number | null; median_return_pct: number | null;
  price_coverage_ratio: number | null; comparable_coverage_ratio: number | null;
  taxonomy: "SIC" | "provider_reported" | null;
  relative_strength_pct: number | null; turnover_value: number | null; turnover_status: string;
  members_truncated: boolean;
  members: Array<{
    symbol: string; direction: string; return_pct: number | null; price_status: string;
    classification: { provider: string; fetched_at: string; effective_date: null } | null;
    price_lineage: Array<{ provider: string; source: string; event_at: string | null; fetched_at: string | null; finalization: string }>;
  }>;
};

export type USSectorDistribution = {
  schema_version: "us.market.sector_distribution.v1";
  status: "partial" | "unavailable"; market: "US";
  as_of: string | null; expected_trade_date: string; reference_trade_date: string;
  evaluated_at: string; data_mode: "eod_market_snapshot"; sample_only: boolean;
  freshness_status: "current" | "stale" | "missing";
  counts: USDistributionCounts;
  coverage: { universe_count: number | null; evaluated_count: number; not_covered_count: number | null;
    over_budget_count: number; query_symbol_limit: number | null; truncated: boolean;
    inventory_current_count: number; inventory_stale_count: number; inventory_missing_count: number;
    price_coverage_ratio: number | null; comparable_coverage_ratio: number | null };
  classification_coverage: { mapped_count: number | null; sector_count: number | null; industry_count: number | null;
    unknown_count: number | null; coverage_ratio: number | null; as_of: string | null };
  sectors: USDistributionGroup[]; industries: USDistributionGroup[]; hot_groups: USDistributionGroup[];
  limitations: string[];
};

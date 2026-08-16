export type USSecDerivedValueRead = {
  metric_code: string;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  period: string | null;
  period_end: string | null;
  value: string | null;
  unit: string | null;
  status: string;
  derivation: string;
  formula: string | null;
  input_fact_ids: string[];
  issue_codes: string[];
};

export type USSecCanonicalValueRead = {
  metric_code: string;
  value: string;
  unit: string | null;
  currency: string | null;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  period_scope: string;
  period_start: string | null;
  period_end: string | null;
  duration_days: number | null;
  status: string;
  revision_kind: string;
  source_fact_id: string;
  taxonomy: string;
  tag: string;
  raw_unit: string;
  reported_fiscal_year: number | null;
  reported_fiscal_period: string | null;
  form: string | null;
  filed_date: string | null;
  accession_number: string | null;
  frame: string | null;
  source_url: string | null;
  issue_codes: string[];
};

export type USSecFinancialContractRead = {
  contract_version: "omi.financial.v1" | string;
  target: {
    market: "US" | string;
    symbol: string;
    cik: string | null;
    entity_name: string | null;
    currency?: string | null;
  };
  as_of: string;
  mode: string;
  as_reported: {
    status: string;
    latest_filing?: {
      accession_number: string | null;
      filed_date: string | null;
    };
    facts: USSecCanonicalValueRead[];
  };
  normalized: {
    status: string;
    facts: USSecCanonicalValueRead[];
    metrics: Record<string, USSecCanonicalValueRead[]>;
  };
  derived: {
    status: string;
    quarterly: Record<string, USSecDerivedValueRead[]>;
    ttm: Record<string, USSecDerivedValueRead>;
    free_cash_flow?: USSecDerivedValueRead[];
    ratios: USSecDerivedValueRead[];
    growth: USSecDerivedValueRead[];
    annual_reconciliations: USSecDerivedValueRead[];
    latest_balance?: Record<string, USSecDerivedValueRead>;
    debt_total?: USSecDerivedValueRead | null;
    net_debt?: USSecDerivedValueRead | null;
  };
  valuation: {
    status: string;
    pe_ttm: string | null;
    price: string | null;
    price_as_of: string | null;
    price_basis?: string | null;
    financial_basis: string;
    input_fact_ids: string[];
    issue_codes: string[];
  };
  quality: {
    freshness: string;
    filing_freshness: {
      status?: string;
      basis?: string;
      local_accession_number?: string | null;
      expected_accession_number?: string | null;
      latest_filing_date?: string | null;
      last_checked_at?: string | null;
      decision_usable?: boolean;
      issue_codes?: string[];
    };
    continuity: string;
    semantic_validity: string;
    supplemental_semantic_validity?: string;
    completeness: string;
    decision_usable: boolean;
    issues: string[];
    decision_blocking_issues?: string[];
    non_blocking_issues?: string[];
    revenue_continuity: Record<string, unknown>;
  };
  source_refs: Array<Record<string, unknown>>;
};

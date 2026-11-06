export type Direction = "long" | "short" | "both";
export type ResearchMarket = "TW" | "US";
export type Money = string | number;
export type ResearchStrategy = {
  version: string; direction: 1 | -1; mode: "aggressive" | "confirmed";
  entry_rule: "next_open" | "at_or_above" | "at_or_below";
  entry_price: number; stop_price: number; targets: { price: number; fraction: number }[];
  shares: number; thesis: string; counter_evidence: string[];
  paper_eligibility: string; qualification_refs: string[];
};
export type SetupEvaluation = {
  status: string; gross_risk?: Money; net_stop_loss?: Money | null;
  setup?: { entry: Money; stop: Money; targets: Money[]; quantity: number };
  target_scenarios?: { gross_rr: Money; net_rr: Money | null }[];
  missing_costs?: string[]; reason_codes?: string[]; limitations?: string[];
};
export type ResearchProposal = {
  market: ResearchMarket;
  creation_id: string; revision_id: string; revision: number; supersedes: string | null;
  symbol: string; strategy: ResearchStrategy; costs: { version: string; [key: string]: unknown };
  recorded_at: string; effective_at: string; change_reason: string; evidence_hash: string;
  initial_risk_amount: number; calendar_verified: boolean; planned_trade_dates: string[];
  evidence: { as_of_trade_date: string; cutoff: string; price_basis: string;
    items: { source_ref: string; source_available_at: string; received_at: string;
      data_revision: string; snapshot_json: string }[] };
};
export type ProposalRead = {
  workflow_origin?: "USER_NOMINATION" | "AI_NOMINATION" | "OMI_SCREEN";
  currency?: "TWD" | "USD"; promotion_supported?: boolean;
  status: string; proposal: ResearchProposal; setup_evaluation: SetupEvaluation | null;
  valid_from_date: string | null; valid_until_date: string | null;
  eligibility: Record<string, unknown> | null;
};
export type ProposalList = { as_of: string; items: ProposalRead[]; limit: number; offset: number; has_more: boolean };
export type ProposalSummary = {
  creation_id: string; revision_id: string; revision: number; market: ResearchMarket; symbol: string;
  stock_name: string | null; direction: "long" | "short"; status: "proposed" | "scheduled";
  workflow_origin: "USER_NOMINATION" | "AI_NOMINATION" | "OMI_SCREEN" | null;
  as_of_trade_date: string; cutoff: string; recorded_at: string; effective_at: string;
  assessment_status: string | null; reason_codes: string[]; evidence_hash: string;
};
export type ProposalSummaryList = {
  projection: "research.proposal_list.summary.v1"; evidence_included: false; execution_ready: false;
  as_of: string; items: ProposalSummary[]; limit: number; offset: number; has_more: boolean;
};
export type RevisionList = { creation_id: string; as_of: string; revisions: ProposalRead[] };
export type ProposalPromotion = {
  creation_id: string; revision_id: string; status: "PROMOTED" | "DATA_BLOCKED";
  reason_codes: string[]; warnings: string[]; execution_ready: false;
  candidate: { id: string; revision: number; digest: string; lifecycle: string;
    created: boolean; validation_reasons: string[] } | null;
};
export type NominationResult = {
  status: string; nomination_origin: string; coverage: Record<string, unknown>;
  scenarios: { stock_id: string; direction: string; status: string; reason_codes: string[];
    proposal: ProposalRead | null }[];
};
export type ResearchMonitor = {
  creation_id: string; revision_id: string; status: string; checked_at: string;
  valid_from_date: string; valid_until_date: string; reason_codes: string[];
  price_condition: string; confirmation: string; confirmation_basis: string;
  setup_evaluation: SetupEvaluation | null; eligibility: Record<string, unknown> | null;
  quote: { trade_date?: string; quote_time?: string; received_at?: string; source?: string;
    price_semantics?: string; trade_state?: string; freshness?: { status?: string };
    evidence?: { value: Money | null; source_at: string; revision: string } | null };
  observation_id: string; limitations: string[]; execution_ready: false;
};
export type NominationSnapshot = {
  identity?: { market: ResearchMarket; symbol: string; venue: string };
  price_map?: { payload?: { stock_id?: string; stock_name?: string | null } };
  request?: { nomination_origin?: string; horizon_sessions?: number };
  assessment?: { status?: string; reason_codes?: string[] };
  selected_zones?: { lower_bound: number; upper_bound: number; zone_id: string }[];
  discovery?: { scope?: string; membership_count?: number; sample_only?: boolean; research_sample_only?: boolean;
    coverage?: { quality_status?: string } };
};
export type ProposalDeletion = { creation_id: string; revision_id: string; deleted_at: string; status: "deleted" };

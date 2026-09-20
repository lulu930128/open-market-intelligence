export type SessionMetric = {
  value: number | null;
  unit: string;
  status: "available" | "partial" | "unavailable";
  estimated: boolean;
  method: string;
  trade_date: string | null;
  as_of: string | null;
  source: string;
  scope: string;
  freshness: string | null;
  coverage: string | null;
  sample_days: number | null;
  limitations: string[];
};

export type ChartSessionSummary = {
  contract_version: "tw.chart.session_summary.v1" | "us.chart.session_summary.v1";
  instrument_id: string;
  trade_date: string | null;
  base_interval: "1m";
  series_revision: string;
  session_scope?: "regular" | "extended" | "all";
  presentation_session_state?: string | null;
  official_close_status?: string | null;
  reference_type: string | null;
  metrics: Record<string, SessionMetric>;
  limitations: string[];
};

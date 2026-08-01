export type USCorporateEventRead = {
  event_id: string;
  event_uid: string;
  symbol: string;
  company_name: string | null;
  exchange: string | null;
  country: string;
  currency: string | null;
  event_type: "earnings" | "dividend" | "split" | string;
  event_subtype: string | null;
  title: string;
  description: string | null;
  event_status: string;
  verification_status: string;
  event_date: string;
  event_time: string | null;
  event_datetime_utc: string | null;
  timezone: string;
  market_session: string;
  is_all_day: boolean;
  days_until: number | null;
  fiscal_year: number | null;
  fiscal_quarter: string | null;
  fiscal_period_end: string | null;
  estimated_eps: number | null;
  declaration_date: string | null;
  ex_date: string | null;
  record_date: string | null;
  payment_date: string | null;
  dividend_amount: number | null;
  dividend_currency: string | null;
  split_from: number | null;
  split_to: number | null;
  split_ratio: number | null;
  source: string;
  source_type: string;
  source_event_id: string | null;
  source_url: string | null;
  first_seen_at: string;
  last_seen_at: string;
  fetched_at: string;
  freshness: string;
  data_mode: string;
  is_stale: boolean;
  missing_fields: string[];
  warnings: string[];
};

export type USCorporateEventSourceRead = {
  source: string;
  status:
    | "current"
    | "degraded"
    | "stale"
    | "missing"
    | "provider_not_configured"
    | "watchlist_only"
    | string;
  freshness: "current" | "stale" | "missing" | string;
  coverage: string;
  fetched_at: string | null;
  entry_count: number;
  warning: string | null;
};

export type USCorporateEventListRead = {
  kind: string;
  generated_at: string;
  as_of: string;
  timezone: string;
  date_from: string;
  date_to: string;
  symbol: string | null;
  event_types: string[];
  offset: number;
  limit: number;
  total_count: number;
  result_count: number;
  warning: string | null;
  sources: Record<string, USCorporateEventSourceRead>;
  results: USCorporateEventRead[];
};

export type USCorporateEventSummaryRead = {
  symbol: string;
  checked_at: string;
  as_of: string;
  timezone: string;
  reminder_days: number;
  cache_status: string;
  cache_fetched_at: string | null;
  warning: string | null;
  result_count: number;
  results: USCorporateEventRead[];
};

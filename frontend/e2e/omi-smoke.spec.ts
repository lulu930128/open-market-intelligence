import { expect, test, type Page, type Route } from "@playwright/test";

function chartPoints() {
  return Array.from({ length: 72 }, (_, index) => {
    const date = new Date(Date.UTC(2026, 2, 2 + index));
    const close = 800 + index * 2;

    return {
      time: date.toISOString().slice(0, 10),
      open: close - 4,
      high: close + 8,
      low: close - 10,
      close,
      volume: 20_000 + index * 100,
      trade_value: 1_000_000 + index * 10_000,
      transaction_count: 1_000 + index,
    };
  });
}

const points = chartPoints();

function seededTaiwanWatchlistTree() {
  return [
    {
      id: 7,
      parent_id: null,
      group_name: "科技股",
      description: "Playwright ranking fixture",
      sort_order: 0,
      is_active: true,
      children: [
        {
          id: 8,
          parent_id: 7,
          group_name: "半導體",
          description: null,
          sort_order: 0,
          is_active: true,
          children: [],
        },
      ],
    },
  ];
}

function seededTaiwanWatchlistItems() {
  const timestamp = "2026-06-15T09:30:00+08:00";

  return [
    {
      id: 70,
      group_id: 7,
      stock_id: "2330",
      stock_name: "台積電",
      market: "TWSE",
      instrument_type: "stock",
      note: null,
      priority: 0,
      tags: "core",
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
    {
      id: 80,
      group_id: 8,
      stock_id: "2303",
      stock_name: "聯電",
      market: "TWSE",
      instrument_type: "stock",
      note: null,
      priority: 0,
      tags: null,
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
    {
      id: 71,
      group_id: 7,
      stock_id: "9999",
      stock_name: "停用測試股",
      market: "TWSE",
      instrument_type: "stock",
      note: null,
      priority: 0,
      tags: null,
      enabled: false,
      created_at: timestamp,
      updated_at: timestamp,
    },
  ];
}

function seededTaiwanRankingRows() {
  return [
    {
      rank: 1,
      stock_id: "2330",
      stock_name: "台積電",
      time: "2026-06-15T09:30:00+08:00",
      close: 1015,
      volume: 98_000,
      change: 15,
      previous_close: 1000,
      change_pct: 1.5,
      limit_status: null,
      score: 82,
      status: "success",
      signal_count: 1,
      signal_keys: ["trend_up"],
      primary_signal_key: "trend_up",
      primary_signal_label: "趨勢向上",
      indicator_snapshot: {},
      context_snapshot: {},
      intraday_previous_close: 1000,
      intraday_points: [
        { time: "2026-06-15T09:00:00+08:00", price: 1005 },
        { time: "2026-06-15T09:30:00+08:00", price: 1015 },
      ],
      error_message: null,
    },
    {
      rank: 2,
      stock_id: "2303",
      stock_name: "聯電",
      time: "2026-06-15T09:30:00+08:00",
      close: 52.4,
      volume: 64_000,
      change: -0.6,
      previous_close: 53,
      change_pct: -1.13,
      limit_status: null,
      score: 45,
      status: "success",
      signal_count: 0,
      signal_keys: [],
      primary_signal_key: null,
      primary_signal_label: null,
      indicator_snapshot: {},
      context_snapshot: {},
      intraday_previous_close: 53,
      intraday_points: [
        { time: "2026-06-15T09:00:00+08:00", price: 52.8 },
        { time: "2026-06-15T09:30:00+08:00", price: 52.4 },
      ],
      error_message: null,
    },
  ];
}

function seededUsWatchlistTree() {
  return [
    {
      id: 17,
      parent_id: null,
      group_name: "Mega Cap Tech",
      description: "Playwright regional ranking fixture",
      sort_order: 0,
      is_active: true,
      children: [],
    },
  ];
}

function seededUsWatchlistItems() {
  const timestamp = "2026-06-15T09:30:00-04:00";

  return [
    {
      id: 170,
      group_id: 17,
      symbol: "AAPL",
      security_name: "Apple Inc.",
      exchange: "NASDAQ",
      asset_type: "stock",
      note: null,
      priority: 0,
      tags: "core",
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
    {
      id: 171,
      group_id: 17,
      symbol: "MSFT",
      security_name: "Microsoft Corp.",
      exchange: "NASDAQ",
      asset_type: "stock",
      note: null,
      priority: 0,
      tags: null,
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
  ];
}

function seededUsRankingRows() {
  return [
    {
      rank: 1,
      symbol: "AAPL",
      security_name: "Apple Inc.",
      exchange: "NASDAQ",
      asset_type: "stock",
      group_id: 17,
      trade_date: "2026-06-15",
      time: "2026-06-15T09:30:00-04:00",
      session: "regular",
      close: 214.5,
      previous_close: 210.5,
      change: 4,
      change_pct: 1.9,
      volume: 1_250_000,
      status: "success",
      source: "playwright.fixture",
      has_extended_hours: false,
      intraday_previous_close: 210.5,
      intraday_points: [
        { time: "2026-06-15T09:00:00-04:00", price: 211 },
        { time: "2026-06-15T09:30:00-04:00", price: 214.5 },
      ],
      error_message: null,
    },
    {
      rank: 2,
      symbol: "MSFT",
      security_name: "Microsoft Corp.",
      exchange: "NASDAQ",
      asset_type: "stock",
      group_id: 17,
      trade_date: "2026-06-15",
      time: "2026-06-15T09:30:00-04:00",
      session: "regular",
      close: 476.25,
      previous_close: 480,
      change: -3.75,
      change_pct: -0.78,
      volume: 980_000,
      status: "success",
      source: "playwright.fixture",
      has_extended_hours: false,
      intraday_previous_close: 480,
      intraday_points: [
        { time: "2026-06-15T09:00:00-04:00", price: 479 },
        { time: "2026-06-15T09:30:00-04:00", price: 476.25 },
      ],
      error_message: null,
    },
  ];
}

function seededJpWatchlistTree() {
  return [
    {
      id: 27,
      parent_id: null,
      group_name: "Japan Core",
      description: "Playwright Japan ranking fixture",
      sort_order: 0,
      is_active: true,
      children: [],
    },
  ];
}

function seededJpWatchlistItems() {
  const timestamp = "2026-06-15T09:30:00+09:00";

  return [
    {
      id: 270,
      group_id: 27,
      symbol: "7203.T",
      local_code: "7203",
      security_name: "Toyota Motor",
      exchange: "TSE",
      market_segment: "Prime",
      sector_33_name: "Transportation Equipment",
      asset_type: "stock",
      note: null,
      priority: 0,
      tags: "core",
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
    {
      id: 271,
      group_id: 27,
      symbol: "6758.T",
      local_code: "6758",
      security_name: "Sony Group",
      exchange: "TSE",
      market_segment: "Prime",
      sector_33_name: "Electric Appliances",
      asset_type: "stock",
      note: null,
      priority: 0,
      tags: null,
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
  ];
}

function seededJpRankingRows() {
  return [
    {
      rank: 1,
      symbol: "7203.T",
      security_name: "Toyota Motor",
      exchange: "TSE",
      market_segment: "Prime",
      sector_33_name: "Transportation Equipment",
      asset_type: "stock",
      group_id: 27,
      trade_date: "2026-06-15",
      close: 2850.5,
      previous_close: 2800.5,
      change: 50,
      change_pct: 1.79,
      volume: 4_200_000,
      status: "success",
      source: "playwright.fixture",
      error_message: null,
    },
    {
      rank: 2,
      symbol: "6758.T",
      security_name: "Sony Group",
      exchange: "TSE",
      market_segment: "Prime",
      sector_33_name: "Electric Appliances",
      asset_type: "stock",
      group_id: 27,
      trade_date: "2026-06-15",
      close: 3725,
      previous_close: 3750,
      change: -25,
      change_pct: -0.67,
      volume: 3_100_000,
      status: "success",
      source: "playwright.fixture",
      error_message: null,
    },
  ];
}

function seededKrWatchlistTree() {
  return [
    {
      id: 37,
      parent_id: null,
      group_name: "Korea Core",
      description: "Playwright Korea ranking fixture",
      sort_order: 0,
      is_active: true,
      children: [],
    },
  ];
}

function seededKrWatchlistItems() {
  const timestamp = "2026-06-15T09:30:00+09:00";

  return [
    {
      id: 370,
      group_id: 37,
      symbol: "005930.KS",
      local_code: "005930",
      security_name: "Samsung Electronics",
      security_name_kr: null,
      exchange: "KRX",
      market_segment: "KOSPI",
      sector: "Technology",
      industry: "Semiconductors",
      asset_type: "stock",
      note: null,
      priority: 0,
      tags: "core",
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
    {
      id: 371,
      group_id: 37,
      symbol: "000660.KS",
      local_code: "000660",
      security_name: "SK Hynix",
      security_name_kr: null,
      exchange: "KRX",
      market_segment: "KOSPI",
      sector: "Technology",
      industry: "Semiconductors",
      asset_type: "stock",
      note: null,
      priority: 0,
      tags: null,
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    },
  ];
}

function seededKrRankingRows() {
  return [
    {
      rank: 1,
      symbol: "005930.KS",
      security_name: "Samsung Electronics",
      exchange: "KRX",
      market_segment: "KOSPI",
      sector: "Technology",
      industry: "Semiconductors",
      asset_type: "stock",
      group_id: 37,
      trade_date: "2026-06-15",
      close: 76500,
      previous_close: 75000,
      change: 1500,
      change_pct: 2,
      volume: 12_500_000,
      status: "success",
      source: "playwright.fixture",
      error_message: null,
    },
    {
      rank: 2,
      symbol: "000660.KS",
      security_name: "SK Hynix",
      exchange: "KRX",
      market_segment: "KOSPI",
      sector: "Technology",
      industry: "Semiconductors",
      asset_type: "stock",
      group_id: 37,
      trade_date: "2026-06-15",
      close: 198500,
      previous_close: 200000,
      change: -1500,
      change_pct: -0.75,
      volume: 5_800_000,
      status: "success",
      source: "playwright.fixture",
      error_message: null,
    },
  ];
}

function seededCryptoWatchlistTree() {
  return [
    {
      id: 1,
      parent_id: null,
      group_name: "主流幣",
      description: "Playwright crypto workspace fixture",
      sort_order: 100,
      is_active: true,
      children: [],
    },
  ];
}

function seededCryptoWatchlistItems() {
  const timestamp = "2026-06-15T09:30:00Z";
  return ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "TON", "LINK"].map(
    (asset, index) => ({
      id: index + 1,
      group_id: 1,
      asset,
      asset_name: asset === "BTC" ? "Bitcoin" : asset,
      note: null,
      priority: (index + 1) * 10,
      tags: null,
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    })
  );
}

function seededCryptoWorkspaceSummary() {
  const watchlisted = new Set(["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "TON", "LINK"]);
  const assets = ["BTC", "ETH", "USDT", "SOL", "BNB", "XRP", "DOGE", "TON", "LINK"].map(
    (asset) => ({
      asset,
      name: asset === "BTC" ? "Bitcoin" : asset,
      priority: asset === "BTC" ? "core" : "major",
      default_subscription_mode: asset === "BTC" ? "always_on" : "on_select",
      subscription_mode: asset === "BTC" ? "always_on" : "on_select",
      subscription_resources: {},
      watchlisted: watchlisted.has(asset),
      instrument_count: asset === "USDT" ? 1 : 4,
      spot_instrument_count: asset === "USDT" ? 1 : 2,
      derivative_instrument_count: asset === "USDT" ? 0 : 2,
      maturity: asset === "BTC" ? "ready" : "stale",
      as_of: "2026-06-15T09:30:00Z",
      core_summary: {},
      context_summary: {},
      advanced_summary: {},
      slots: [],
    })
  );
  return {
    kind: "crypto_workspace_summary",
    generated_at: "2026-06-15T09:30:00Z",
    registry_count: 9,
    watchlist_count: 8,
    summary: {
      asset_count: 9,
      watchlist_count: 8,
      always_on_count: 1,
      on_select_count: 8,
      ready_count: 1,
      partial_count: 0,
      stale_count: 8,
      missing_count: 0,
    },
    runtime: { realtime: { running: true }, auto_refresh: { running: true } },
    assets,
    warnings: [],
  };
}

function ohlcResponse(stockId: string) {
  return {
    stock_id: stockId,
    timeframe: "daily",
    bars: 180,
    lookback_days: 260,
    from_date: points[0].time,
    to_date: points[points.length - 1].time,
    point_count: points.length,
    points,
    backfill: null,
  };
}

function stockOhlcResponse(stockId: string) {
  const basePrice = stockId === "2303" ? 50 : 1_000;
  const stockPoints = Array.from({ length: 180 }, (_, index) => {
    const date = new Date(Date.UTC(2026, 0, 16 + index));
    const close = basePrice + index * (stockId === "2303" ? 0.02 : 0.5);

    return {
      time: date.toISOString().slice(0, 10),
      open: close - 0.5,
      high: close + 1,
      low: close - 1,
      close,
      volume: 20_000 + index * 100,
      trade_value: 1_000_000 + index * 10_000,
      transaction_count: 1_000 + index,
    };
  });

  return {
    stock_id: stockId,
    timeframe: "daily",
    bars: 180,
    lookback_days: 260,
    from_date: stockPoints[0].time,
    to_date: stockPoints[stockPoints.length - 1].time,
    point_count: stockPoints.length,
    points: stockPoints,
    intraday_overlay: null,
    volume_unit: "shares",
    backfill: null,
  };
}

function stockMasterResponse(stockId: string) {
  const timestamp = "2026-06-15T09:30:00+08:00";

  return {
    id: stockId === "2303" ? 2303 : 2330,
    stock_id: stockId,
    stock_name: stockId === "2303" ? "United Microelectronics" : "TSMC",
    market: "TWSE",
    instrument_type: "stock",
    industry: "Semiconductors",
    category: null,
    is_active: true,
    notes: null,
    first_seen_at: timestamp,
    last_seen_at: timestamp,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function nextSessionPlanResponse(stockId: string) {
  return {
    kind: "tw_stock_next_session_plan",
    version: "tw_next_session_plan_v1",
    market: "TWSE",
    stock_id: stockId,
    stock_name: stockId === "2303" ? "United Microelectronics" : "TSMC",
    instrument_type: "stock",
    currency: "TWD",
    price_unit: "TWD_per_share",
    status: "ready",
    generated_at: "2026-06-15T16:00:00+08:00",
    as_of_trade_date: "2026-06-15",
    target_trade_date: "2026-06-16",
    target_session_state: "upcoming",
    as_of_close: 138,
    methodology: {
      id: "tw_next_session_sma_transition",
      version: "1.0.0",
      price_series: "raw_unadjusted_completed_daily_close",
      candidate_price_semantics: "hypothetical_target_session_close",
      transition_formula: "mean(last_N_minus_1_completed_closes)",
      projected_ma_formula: "(sum(last_N_minus_1_closes)+candidate_close)/N",
      comparison_rule:
        "candidate_close_gte_transition_price_iff_candidate_close_gte_projected_ma",
    },
    freshness: {
      status: "current",
      expected_trade_date: "2026-06-15",
      latest_trade_date: "2026-06-15",
      calendar_day_lag: 0,
      trading_day_lag: 0,
      release_time: "15:15",
      release_timezone: "Asia/Taipei",
      checked_at: "2026-06-15T16:00:00+08:00",
    },
    history: {
      requested_limit: 250,
      raw_row_count: 80,
      distinct_trade_date_count: 80,
      duplicate_trade_date_count: 0,
      valid_close_count: 80,
      first_trade_date: "2026-02-20",
      latest_trade_date: "2026-06-15",
      source_ids: [1],
      max_gap_days: 10,
    },
    readiness: {
      status: "ready",
      decision_usable: true,
      reason_codes: [],
      available_level_keys: ["ma20_transition", "ma60_transition"],
      missing_level_keys: [],
    },
    levels: [
      {
        key: "ma20_transition",
        period: 20,
        transition_price: 142,
        current_ma: 143,
        projected_ma_if_flat: 141.8,
        drift_if_flat: -1.2,
        dropped_close: 162,
        as_of_close_relation: "below",
        role_at_as_of_close: "reclaim",
        move_from_as_of_close_pct: 2.9,
        required_close_count: 19,
        available_close_count: 19,
        window_start_date: "2026-05-19",
        window_end_date: "2026-06-15",
        candidate_price_semantics: "hypothetical_target_session_close",
        comparison_rule:
          "candidate_close_gte_transition_price_means_candidate_close_gte_projected_ma",
      },
      {
        key: "ma60_transition",
        period: 60,
        transition_price: 150,
        current_ma: 151,
        projected_ma_if_flat: 149.8,
        drift_if_flat: -1.2,
        dropped_close: 210,
        as_of_close_relation: "below",
        role_at_as_of_close: "reclaim",
        move_from_as_of_close_pct: 8.7,
        required_close_count: 59,
        available_close_count: 59,
        window_start_date: "2026-03-20",
        window_end_date: "2026-06-15",
        candidate_price_semantics: "hypothetical_target_session_close",
        comparison_rule:
          "candidate_close_gte_transition_price_means_candidate_close_gte_projected_ma",
      },
    ],
    known_range: {
      period: 20,
      support: 128.5,
      resistance: 184.78,
      previous_session_low: 136,
      previous_session_high: 141,
      previous_session_close: 138,
      window_start_date: "2026-05-19",
      window_end_date: "2026-06-15",
      method: "last_20_completed_session_high_low_including_as_of",
    },
    scenario_zones: [
      {
        key: "below_both",
        lower_bound: null,
        upper_bound: 142,
        lower_bound_rule: null,
        upper_bound_rule: "exclusive",
        at_or_above_level_keys: [],
        below_level_keys: ["ma20_transition", "ma60_transition"],
      },
      {
        key: "between_transition_levels",
        lower_bound: 142,
        upper_bound: 150,
        lower_bound_rule: "inclusive",
        upper_bound_rule: "exclusive",
        at_or_above_level_keys: ["ma20_transition"],
        below_level_keys: ["ma60_transition"],
      },
      {
        key: "at_or_above_both",
        lower_bound: 150,
        upper_bound: null,
        lower_bound_rule: "inclusive",
        upper_bound_rule: null,
        at_or_above_level_keys: ["ma20_transition", "ma60_transition"],
        below_level_keys: [],
      },
    ],
    corporate_action_adjustment: {
      status: "not_applied",
      event_check: "not_performed",
      price_series: "raw_unadjusted_completed_daily_close",
    },
    missing: [],
    warning_codes: [],
    warnings: [],
    limitation_codes: [
      "conditional_level_not_price_forecast",
      "corporate_action_adjustment_not_applied",
      "transition_price_not_tick_rounded",
    ],
    limitations: [],
    source_refs: [
      { type: "table", name: "market_daily_price" },
      { type: "derived", name: "app.market.next_session_plan" },
    ],
  };
}

function corporateEventHistoryResponse(stockId: string) {
  const event = (
    eventId: string,
    eventType: "ex_dividend" | "financial_report" | "investor_conference",
    startDate: string,
    title: string
  ) => ({
    event_id: eventId,
    event_type: eventType,
    timing_status: "actual",
    provider: eventType === "ex_dividend" ? "twse" : "mops",
    market: "TWSE",
    source_name: "Playwright fixture",
    source_url: "https://example.com/corporate-events",
    stock_id: stockId,
    stock_name: "TSMC",
    start_date: startDate,
    end_date: startDate,
    start_time: null,
    title,
    summary: null,
    location: null,
    cash_dividend: eventType === "ex_dividend" ? 5 : null,
    stock_dividend_ratio: null,
    financial_report_related: eventType === "financial_report",
    related_event_id: null,
    company_url: null,
    video_url: null,
    status: "past",
    days_until: -30,
  });
  const results = [
    event("event-ex-dividend", "ex_dividend", "2026-06-10", "Ex-dividend date"),
    event("event-financial", "financial_report", "2026-05-08", "Financial report"),
    event("event-conference", "investor_conference", "2026-06-12", "Investor conference"),
  ];

  return {
    stock_id: stockId,
    checked_at: "2026-07-22T12:00:00+08:00",
    history_years: 5,
    cache_status: "current",
    cache_fetched_at: "2026-07-22T11:55:00+08:00",
    coverage_start: "2022-01-01",
    coverage_end: "2026-07-19",
    warning: null,
    total_count: results.length,
    result_count: results.length,
    results,
  };
}

function usCorporateEventResponse(symbol = "AAPL") {
  return {
    event_id: `us:${symbol}:earnings:2026-06-30`,
    event_uid: `us:${symbol}:earnings:2026-06-30`,
    symbol,
    company_name: symbol === "AAPL" ? "Apple Inc." : symbol,
    exchange: "NASDAQ",
    country: "US",
    currency: "USD",
    event_type: "earnings",
    event_subtype: "quarterly_earnings",
    title: `${symbol} Earnings`,
    description: null,
    event_status: "scheduled",
    verification_status: "third_party",
    event_date: "2026-07-31",
    event_time: null,
    event_datetime_utc: null,
    timezone: "America/New_York",
    market_session: "unknown",
    is_all_day: true,
    days_until: 2,
    fiscal_year: 2026,
    fiscal_quarter: null,
    fiscal_period_end: "2026-06-30",
    estimated_eps: 1.42,
    declaration_date: null,
    ex_date: null,
    record_date: null,
    payment_date: null,
    dividend_amount: null,
    dividend_currency: null,
    split_from: null,
    split_to: null,
    split_ratio: null,
    source: "alphavantage",
    source_type: "provider_api",
    source_event_id: null,
    source_url: "https://example.com/us-earnings",
    first_seen_at: "2026-07-29T08:00:00Z",
    last_seen_at: "2026-07-29T08:00:00Z",
    fetched_at: "2026-07-29T08:00:00Z",
    freshness: "fresh",
    data_mode: "cached",
    is_stale: false,
    missing_fields: ["event_time"],
    warnings: ["The provider does not supply a reliable earnings release time."],
  };
}

function usCorporateEventSummaryResponse(
  symbol = "AAPL",
  results: ReturnType<typeof usCorporateEventResponse>[] = []
) {
  return {
    symbol,
    checked_at: "2026-07-29T08:05:00Z",
    as_of: "2026-07-29",
    timezone: "America/New_York",
    reminder_days: 7,
    cache_status: "current",
    cache_fetched_at: "2026-07-29T08:00:00Z",
    warning: null,
    result_count: results.length,
    results,
  };
}

function usCorporateEventListResponse() {
  const results = [usCorporateEventResponse()];
  return {
    kind: "us_corporate_events",
    generated_at: "2026-07-29T08:05:00Z",
    as_of: "2026-07-29",
    timezone: "America/New_York",
    date_from: "2026-07-29",
    date_to: "2026-10-27",
    symbol: null,
    event_types: [],
    offset: 0,
    limit: 1000,
    total_count: results.length,
    result_count: results.length,
    warning: null,
    sources: {
      alphavantage_earnings: {
        source: "Alpha Vantage Earnings Calendar",
        status: "current",
        freshness: "current",
        coverage: "us_market_3month",
        fetched_at: "2026-07-29T08:00:00Z",
        entry_count: results.length,
        warning: null,
      },
      alphavantage_actions: {
        source: "Alpha Vantage Corporate Actions",
        status: "watchlist_only",
        freshness: "current",
        coverage: "cached_symbols_only",
        fetched_at: "2026-07-29T08:00:00Z",
        entry_count: 0,
        warning: "Coverage is limited to cached symbols.",
      },
    },
    results,
  };
}

function emptyTaiwanCorporateEventListResponse() {
  return {
    kind: "taiwan_corporate_events",
    generated_at: "2026-07-29T16:05:00+08:00",
    as_of: "2026-07-29",
    date_from: "2026-07-29",
    date_to: "2026-10-27",
    stock_id: null,
    market: null,
    event_types: [],
    result_count: 0,
    warning: null,
    sources: {},
    results: [],
  };
}

function intradayResponse(stockId: string) {
  const latestPrice = stockId === "2303" ? 52.4 : 1_015;
  const previousClose = stockId === "2303" ? 53 : 1_000;

  return {
    stock_id: stockId,
    symbol: stockId,
    source: "playwright.fixture",
    trade_date: "2026-06-15",
    previous_close: previousClose,
    point_count: 2,
    points: [
      {
        time: "2026-06-15T09:00:00+08:00",
        price: previousClose,
        volume: 1_000,
        accumulated_volume: 1_000,
      },
      {
        time: "2026-06-15T09:30:00+08:00",
        price: latestPrice,
        volume: 2_000,
        accumulated_volume: 3_000,
      },
    ],
    history_price_source: "playwright.fixture",
    latest_history_time: "2026-06-15T09:30:00+08:00",
    latest_history_price: latestPrice,
    latest_actual_trade_time: "2026-06-15T09:30:00+08:00",
    latest_actual_trade_price: latestPrice,
    current_price_source: "twse_mis_snapshot_z",
    lag_seconds: 0,
    current_trade_available: true,
    current_trade_unavailable_reason: null,
    current_price_applied_to_history: true,
    capabilities: {
      supports_volume: true,
      supports_vwap: true,
      supports_price_limit: true,
      supports_quote_depth: true,
    },
    current_observation: {
      value: latestPrice,
      observed_at: "2026-06-15T09:30:00+08:00",
      confirmed_at: "2026-06-15T09:30:00+08:00",
      price_semantics: "actual_trade",
      provider: "playwright.fixture",
      freshness_status: "current",
      decision_usable: true,
    },
  };
}

function quoteDepthResponse(stockId: string) {
  const lastPrice = stockId === "2303" ? 52.4 : 1_015;
  const previousClose = stockId === "2303" ? 53 : 1_000;
  const tick = stockId === "2303" ? 0.1 : 5;
  const change = lastPrice - previousClose;

  return {
    stock_id: stockId,
    stock_name: stockId === "2303" ? "United Microelectronics" : "TSMC",
    market: "TWSE",
    provider: "playwright.fixture",
    source: "twse_mis_quote_depth",
    source_url: null,
    exchange_channel: stockId,
    session_phase: "regular_live",
    phase_label: "Regular",
    trade_date: "2026-06-15",
    quote_time: "2026-06-15T09:30:00+08:00",
    fetched_at: "2026-06-15T09:30:01+08:00",
    last_price: lastPrice,
    previous_close: previousClose,
    open_price: previousClose,
    high_price: lastPrice + tick,
    low_price: previousClose - tick,
    change,
    change_pct: (change / previousClose) * 100,
    total_volume_lots: 12_000,
    cumulative_volume_lots: 12_000,
    cumulative_volume_shares: 12_000_000,
    last_trade_volume_lots: 320,
    last_trade_volume_shares: 320_000,
    lot_size: 1_000,
    volume_unit: "lots",
    canonical_volume_unit: "shares",
    provider_volume_unit: "lots",
    volume_semantics: "session_cumulative_provider_volume",
    volume_scope: "regular_session_board_lot_cumulative",
    volume_source: "twse_mis",
    volume_source_field: "v",
    volume_status: "available",
    provider_volume_available: true,
    last_trade_volume_semantics: "provider_reported_last_match_volume",
    last_trade_volume_source_field: "tv",
    last_trade_volume_status: "available",
    official_daily_volume_shares: 12_300_000,
    official_daily_volume_trade_date: "2026-06-15",
    official_daily_volume_source: "market_daily_price",
    official_daily_volume_scope: "official_daily_aggregate",
    volume_includes_odd_lot: false,
    volume_includes_after_hours: false,
    volume_includes_closing_auction: null,
    volume_reconciliation: {
      reference_dataset: "market_daily_price",
      reference_source: "market_daily_price",
      reference_trade_date: "2026-06-15",
      reference_volume_shares: 12_300_000,
      reference_volume_scope: "official_daily_aggregate",
      snapshot_trade_date: "2026-06-15",
      snapshot_volume_shares: 12_000_000,
      snapshot_volume_scope: "regular_session_board_lot_cumulative",
      difference_shares: -300_000,
      difference_pct: -2.439,
      difference_semantics: "informational_cross_scope_difference",
      tolerance_pct: null,
      status: "scope_different",
      reason: "provider_and_official_volume_scopes_differ",
      decision_usable: false,
    },
    volume_decision_usable: false,
    best_bid_price: lastPrice - tick,
    best_bid_size_lots: stockId === "2303" ? null : 100,
    best_ask_price: lastPrice + tick,
    best_ask_size_lots: 120,
    bid_total_size_lots: stockId === "2303" ? null : 500,
    ask_total_size_lots: 600,
    spread: tick * 2,
    spread_pct: ((tick * 2) / lastPrice) * 100,
    bid_levels:
      stockId === "2303"
        ? []
        : Array.from({ length: 5 }, (_, index) => ({
            level: index + 1,
            price: lastPrice - tick * (index + 1),
            size_lots: 100 - index * 10,
          })),
    ask_levels: Array.from({ length: 5 }, (_, index) => ({
      level: index + 1,
      price: lastPrice + tick * (index + 1),
      size_lots: 120 - index * 10,
    })),
    depth_available: true,
    freshness: {
      status: "live",
      is_live: true,
      is_stale: false,
      age_seconds: 1,
      expected_trade_date: "2026-06-15",
      message: `Live quote for ${stockId}`,
      source_error: null,
    },
  };
}

function usMarketResearchResponse(symbol: string) {
  const quality = {
    status: "partial",
    facts_usable: true,
    decision_usable: false,
    bar_count: 220,
    facts_minimum_bars: 60,
    decision_minimum_bars: 200,
    corporate_action_coverage: "unknown",
    freshness_status: "current",
    reason_codes: ["CORPORATE_ACTION_COVERAGE_UNKNOWN"],
  };

  return {
    kind: "us_market_research",
    schema_version: "omi.us_market.research.v1",
    market: "US",
    symbol,
    status: "partial",
    as_of: "2026-08-21",
    technical_indicators: {
      kind: "technical_indicators",
      schema_version: "omi.technical_indicators.v1",
      algorithm_version: "playwright.fixture.v1",
      market: "US",
      symbol,
      timeframe: "1d",
      price_basis: "unadjusted",
      status: "partial",
      as_of: "2026-08-21",
      bar_count: 220,
      current: {
        time: "2026-08-21",
        close: 226.8,
        change_pct: 0.42,
        volume: 48_000_000,
        moving_averages: { ma5: 224.5, ma20: 219.3, ma60: 211.7 },
        price_vs_ma20_pct: 3.42,
        volume_vs_ma20_pct: 8.1,
      },
      quality,
    },
    technical_structure: {
      kind: "technical_structure",
      schema_version: "omi.technical_structure.v1",
      status: "partial",
      as_of: "2026-08-21",
      selected_title: "Bullish stack",
      trend_state: "bullish_stack",
      breakout_state: "inside_range",
      metrics: {
        price_vs_ma20_pct: 3.42,
        volume_vs_ma20_pct: 8.1,
        day_change_pct: 0.42,
      },
      quality,
    },
    corporate_action_coverage: {
      status: "unknown",
      observed_event_count: 0,
      completeness_checkpoint: null,
    },
    market_coverage: { full_market_ready: false },
    missing: ["corporate_action_completeness"],
    warnings: ["Playwright fixture keeps decision usability fail-closed."],
  };
}

function realtimeQuoteStreamResponse(stockId: string) {
  const price = stockId === "2303" ? 52.4 : 1_015;
  return {
    projection_scope: "presentation_only",
    canonical_truth: false,
    decision_usable: false,
    research_usable: false,
    provider_specific: true,
    kind: "taiwan_realtime_quote_stream",
    contract_version: "omi.tw.realtime_stream.v2",
    stock_id: stockId,
    provider: "kgi_superpy",
    source: "kgi_superpy_quote_all",
    status: "live",
    active_leases: 1,
    sequence: 2,
    generated_at: "2026-06-15T01:30:02Z",
    event_time: "2026-06-15T09:30:02+08:00",
    received_at: "2026-06-15T01:30:02Z",
    session_phase: "regular",
    selection_reason: "active_kgi_viewer_or_acceptance_lease",
    fallback_used: false,
    is_stale: false,
    capability_status: {
      recent_trades: "available",
      auction_observations: "empty",
      minute_kbars: "available",
      depth_metrics: "available",
      depth: "available",
      latency: "available",
    },
    limits: {
      recent_trades: 60,
      auction_observations: 120,
      minute_kbars: 120,
    },
    recent_trades: [
      {
        event_id: `trade:${stockId}:2`,
        sequence: 2,
        event_time: "2026-06-15T09:30:02+08:00",
        received_at: "2026-06-15T01:30:02Z",
        manager_ingested_at: "2026-06-15T01:30:02.010Z",
        session_phase: "regular",
        provider_delay_raw: 10,
        provider_delay_unit: "unknown",
        price,
        volume_lots: 12,
        total_volume_lots: 12_000,
        amount: price * 12,
        price_direction: "up",
        direction_semantics: "price_change_from_previous_observed_trade",
      },
    ],
    auction_observations: [],
    minute_kbars: [],
    depth_metrics: {
      event_time: "2026-06-15T09:30:02+08:00",
      received_at: "2026-06-15T01:30:02Z",
      best_bid_price: price - 0.1,
      best_ask_price: price + 0.1,
      spread: 0.2,
      spread_pct: (0.2 / price) * 100,
      top5_bid_volume_lots: 500,
      top5_ask_volume_lots: 450,
      top5_imbalance: 50 / 950,
      top5_imbalance_formula:
        "(bid_volume_lots-ask_volume_lots)/(bid_volume_lots+ask_volume_lots)",
      diff_bid_volume_lots: [5, 2, 0, -1, 3],
      diff_ask_volume_lots: [-2, 1, 0, 2, -3],
      simtrade: false,
    },
    depth: {
      provider: "kgi_superpy",
      source: "kgi_superpy_quote_all",
      capability: "level_5",
      state: "available",
      event_time: "2026-06-15T09:30:02+08:00",
      received_at: "2026-06-15T01:30:02Z",
      manager_ingested_at: "2026-06-15T01:30:02.010Z",
      stream_sampled_at: "2026-06-15T01:30:02.020Z",
      freshness_status: "live",
      is_stale: false,
      age_seconds: 0.02,
      bid_levels: Array.from({ length: 5 }, (_, index) => ({
        level: index + 1,
        price: price - 0.1 * (index + 1),
        price_state: "limit_price",
        size_shares: (100 - index * 10) * 1_000,
        size_lots: 100 - index * 10,
      })),
      ask_levels: Array.from({ length: 5 }, (_, index) => ({
        level: index + 1,
        price: price + 0.1 * (index + 1),
        price_state: "limit_price",
        size_shares: (120 - index * 10) * 1_000,
        size_lots: 120 - index * 10,
      })),
    },
    latency: {
      event_at: "2026-06-15T09:30:02+08:00",
      bridge_received_at: "2026-06-15T01:30:02Z",
      manager_ingested_at: "2026-06-15T01:30:02.010Z",
      stream_sampled_at: "2026-06-15T01:30:02.020Z",
      event_to_bridge_ms: 0,
      bridge_to_manager_ms: 10,
      manager_to_stream_ms: 10,
      event_to_stream_ms: 20,
      provider_delay_raw: 10,
      provider_delay_unit: "unknown",
      provider_delay_semantics: "provider_reported_raw_value_unit_not_verified",
    },
    diagnostic_counters: {
      callback_count: 2,
      baseline_only_count: 1,
      cumulative_advanced_count: 1,
      same_cumulative_count: 0,
      decreasing_cumulative_count: 0,
      missing_cumulative_count: 0,
      invalid_cumulative_count: 0,
      trade_addition_count: 1,
      auction_addition_count: 0,
      trade_signature_suppression_count: 0,
      auction_signature_suppression_count: 0,
      non_trade_suppression_count: 0,
      trial_leak_count: 0,
      cross_date_rejected_count: 0,
    },
    diagnostic_events: [],
    warnings: [],
  };
}

function emptyQuoteReplayResponse(stockId: string) {
  const requiredSlots = ["08:30", "08:50", "08:55", "08:58", "08:59"];
  return {
    kind: "taiwan_quote_contract_replay",
    stock_id: stockId,
    trade_date: null,
    timezone: "UTC+08:00",
    required_slots: requiredSlots,
    required_count: requiredSlots.length,
    captured_count: 0,
    coverage_ratio: 0,
    complete: false,
    missing_slots: requiredSlots,
    snapshots: requiredSlots.map((captureSlot) => ({
      capture_slot: captureSlot,
      status: "missing",
      quote: null,
    })),
    source: "taiwan_quote_contract_snapshot",
    replay_semantics: "persisted_fixed_slot_evidence_projected_to_current_public_contract",
    read_path_side_effects: false,
  };
}

function brokerBranchSummaryResponse(stockId: string, days: number) {
  const timestamp = "2026-06-15T09:30:00+08:00";
  const branchRow = {
    id: 1,
    source_id: 1,
    raw_result_id: 1,
    trade_date: "2026-06-15",
    stock_id: stockId,
    stock_name: stockId === "2303" ? "United Microelectronics" : "TSMC",
    branch_code: "9A00",
    branch_name: "Fixture Branch",
    buy_lots: 120,
    sell_lots: 40,
    net_lots: 80,
    buy_avg_price: 1_010,
    sell_avg_price: 1_008,
    buy_rank: 1,
    sell_rank: 1,
    source_label: "Fixture",
    created_at: timestamp,
    updated_at: timestamp,
  };

  return {
    stock_id: stockId,
    stock_name: stockId === "2303" ? "United Microelectronics" : "TSMC",
    trade_date: "2026-06-15",
    source_name: "playwright.fixture",
    source_url: "https://example.test/branches",
    source_label: "Fixture",
    is_latest: true,
    requested_days: days,
    available_days: days,
    trade_dates: ["2026-06-15"],
    is_partial: false,
    row_count: 1,
    buy_top: [branchRow],
    sell_top: [{ ...branchRow, net_lots: -40 }],
  };
}

function calendarStatus() {
  const status = {
    market: "tw",
    timezone: "Asia/Taipei",
    checked_at: "2026-06-15T09:30:00+08:00",
    date: "2026-06-15",
    is_trading_day: true,
    phase: "regular",
    reason: "regular_session",
    holiday_name: null,
    previous_trading_day: "2026-06-12",
    next_trading_day: "2026-06-16",
    session: {
      preopen_time: "2026-06-15T08:30:00+08:00",
      open_time: "2026-06-15T09:00:00+08:00",
      close_time: "2026-06-15T13:30:00+08:00",
      next_session_start_at: "2026-06-16T09:00:00+08:00",
      is_polling_window: true,
      is_after_close: false,
    },
    release_windows: {},
  };

  return {
    kind: "market_calendar_status",
    generated_at: "2026-06-15T09:30:00+08:00",
    markets: {
      tw: status,
      us: { ...status, market: "us", timezone: "America/New_York" },
    },
  };
}

function taiwanDailyPriceReleaseStatus(isReleased: boolean) {
  const base = calendarStatus();
  const checkedAt = isReleased
    ? "2026-07-21T15:15:01+08:00"
    : "2026-07-21T15:14:00+08:00";

  return {
    ...base,
    generated_at: checkedAt,
    markets: {
      ...base.markets,
      tw: {
        ...base.markets.tw,
        checked_at: checkedAt,
        date: "2026-07-21",
        phase: "post_close",
        reason: "post_close",
        previous_trading_day: "2026-07-20",
        next_trading_day: "2026-07-22",
        session: {
          preopen_time: "2026-07-21T08:30:00+08:00",
          open_time: "2026-07-21T09:00:00+08:00",
          close_time: "2026-07-21T13:30:00+08:00",
          next_session_start_at: "2026-07-22T09:00:00+08:00",
          is_polling_window: false,
          is_after_close: true,
        },
        release_windows: {
          market_daily_price: {
            key: "market_daily_price",
            label: "Taiwan daily price",
            release_time: "15:15",
            release_at: "2026-07-21T15:15:00+08:00",
            next_release_at: "2026-07-22T15:15:00+08:00",
            expected_trade_date: "2026-07-21",
            status: isReleased ? "released" : "pending",
            is_released: isReleased,
          },
        },
      },
    },
  };
}

function marketIndexSummaryResponse(close: number) {
  const previousClose = close - 10;

  return {
    as_of: "2026-06-15T09:30:00+08:00",
    source: "playwright.fixture",
    indices: [
      {
        index_id: "TAIEX",
        label: "加權指數",
        short_label: "TAIEX",
        market: "TWSE",
        symbol: "TAIEX",
        source: "playwright.fixture",
        as_of: "2026-06-15T09:30:00+08:00",
        time: "2026-06-15T09:30:00+08:00",
        open: previousClose,
        high: close + 5,
        low: previousClose - 5,
        close,
        previous_close: previousClose,
        change: 10,
        change_pct: (10 / previousClose) * 100,
        volume: 1_200_000,
        estimated_volume: null,
        trade_value: 120_000_000_000,
        estimated_trade_value: null,
        ma20: close - 20,
        price_vs_ma20: 1.2,
        point_count: 60,
        points: [],
        breadth: {
          advance_count: 600,
          decline_count: 220,
          unchanged_count: 80,
          total_count: 900,
          trade_value: 120_000_000_000,
        },
        error_message: null,
      },
    ],
  };
}

function emptyRadarResponse(path: string, mode = "action") {
  const groupId = Number(path.match(/groups\/(\d+)\/radar/)?.[1] ?? 0);
  const market = path.includes("/us-market/")
    ? "us"
    : path.includes("/jp-market/")
      ? "jp"
      : path.includes("/kr-market/")
        ? "kr"
        : "tw";

  return {
    group_id: groupId,
    include_children: true,
    mode,
    max_results: 8,
    market,
    scope_label: null,
    data_limitations: [],
    requested_stock_count: 0,
    ranked_count: 0,
    matched_count: 0,
    radar_count: 0,
    no_data_count: 0,
    error_count: 0,
    trade_date: "2026-06-15",
    target_trade_date: "2026-06-15",
    is_current: true,
    current_stock_count: 0,
    stale_stock_count: 0,
    buckets: [],
    results: [],
    ...(market === "tw"
      ? {
          radar_engine: {
            active_version: "radar_v2.0",
            active_config_hash: "playwright-active-v2",
            shadow_version: "radar_v2.0-shadow",
            shadow_config_hash: "playwright-shadow-v2",
            mode: "active",
            rollback_version: "radar_v1.0",
            technical_direction_owner: "backend",
            cross_market_context_mode: "display_only",
            legacy_status: "frozen",
            legacy_frozen_at: "2026-08-01",
          },
          radar_v2_summary: {
            evaluated_count: 0,
            universe_evaluated_count: 0,
            universe_scope: "complete_calculation_universe",
            direction_changed_count: 0,
            bucket_changed_count: 0,
            conflict_count: 0,
            insufficient_count: 0,
            market_regime: "mixed",
            market_regime_clarity: 0.5,
            market_limitations: [],
            readiness: {
              operational_status: "active",
              validation_status: "unverified",
              backtest_status: "missing",
              completed_backtest_count: 0,
              outcome_count: 0,
              finalized_outcome_count: 0,
              pending_outcome_count: 0,
              limitations: [],
            },
            cross_market_context: {
              enabled: true,
              mode: "display_only",
              snapshot_count: 0,
              decision_usable_count: 0,
              status_counts: {},
              snapshot_ids: [],
              methodology_versions: [],
              relation_snapshot_versions: [],
              ranking_effect: "none",
              missing_count: 0,
            },
          },
        }
      : {}),
  };
}

function seededRadarResponse(url: URL, label: string) {
  const path = url.pathname;
  const empty = emptyRadarResponse(path, url.searchParams.get("mode") ?? "action");
  const stockId = path.includes("/us-market/")
    ? "AAPL"
    : path.includes("/jp-market/")
      ? "7203.T"
      : path.includes("/kr-market/")
        ? "005930.KS"
        : "2330";

  return {
    ...empty,
    requested_stock_count: 1,
    ranked_count: 1,
    matched_count: 1,
    radar_count: 1,
    current_stock_count: 1,
    buckets: [
      {
        key: empty.mode === "risk" ? "selloff_risk" : "momentum",
        label,
        description: label,
        count: 1,
      },
    ],
    results: [
      {
        rank: 1,
        source_rank: 1,
        bucket: empty.mode === "risk" ? "selloff_risk" : "momentum",
        bucket_label: label,
        urgency: "medium",
        priority_score: 80,
        technical_evidence_score: 75,
        technical_score: 75,
        technical_grade: "medium",
        technical_grade_label: "Medium",
        technical_grade_description: label,
        direction: empty.mode === "risk" ? "bearish" : "bullish",
        direction_label: empty.mode === "risk" ? "Bearish" : "Bullish",
        setup_label: label,
        timing_label: "Watch",
        risk_label: "Bounded",
        factor_scores: {},
        price_levels: {},
        technical_notes: [label],
        action_label: label,
        reason: label,
        stock_id: stockId,
        stock_name: label,
        time: "2026-06-15T09:30:00+08:00",
        trade_date: "2026-06-15",
        close: 100,
        volume: 1_000,
        change: 1,
        previous_close: 99,
        change_pct: 1.01,
        limit_status: null,
        score: 75,
        status: "ok",
        signal_count: 1,
        signal_keys: ["fixture"],
        matched_signal_keys: ["fixture"],
        matched_signal_labels: [label],
        signal_labels: [label],
        primary_signal_key: "fixture",
        primary_signal_label: label,
        indicator_snapshot: {},
        context_snapshot:
          stockId === "2330"
            ? {
                cross_market: {
                  status: "ready",
                  decision_usable: true,
                  snapshot_id: "cmctx:2330:e2e",
                  methodology_version: "cross_market.relation_context.v2",
                  relation_snapshot_version: "relation_registry:42:v1",
                  coverage: { coverage_ratio: 1 },
                  limitations: ["latest_local_cache_projection_not_materialized_snapshot"],
                },
              }
            : {},
        context_signals:
          stockId === "2330"
            ? [
                {
                  key: "cross_market_context",
                  source: "跨市場",
                  label: "外部順風",
                  tone: "positive",
                  stance: "confirm",
                  value_label: "+3.50%",
                  description: "ADR parity supportive",
                  context_status: "ready",
                  snapshot_id: "cmctx:2330:e2e",
                  methodology_version: "cross_market.relation_context.v2",
                  relation_snapshot_version: "relation_registry:42:v1",
                  coverage: { coverage_ratio: 1 },
                  limitations: ["latest_local_cache_projection_not_materialized_snapshot"],
                  decision_usable: true,
                },
              ]
            : [],
        context_summary: label,
        context_score: 0,
        stale: false,
        error_message: null,
      },
    ],
  };
}

function radarV2OutcomeSummary(snapshotDate: string, status = "evaluated") {
  return {
    status,
    group_id: 7,
    mode: "action",
    snapshot_date: snapshotDate,
    horizon_trading_days: 1,
    rule_version: "radar_v2.0",
    outcome_contract_version: "outcome_v2.0",
    total_count: 1,
    finalized_count: status === "evaluated" ? 1 : 0,
    pending_count: status === "pending" ? 1 : 0,
    latest_available_trade_date: "2026-06-14",
    last_reconciled_at: "2026-06-14T10:30:00Z",
    pending_reason_counts:
      status === "pending" ? { awaiting_daily_bar: 1 } : {},
    summary_state_counts: {
      [status === "pending" ? "pending" : "close_confirmed"]: 1,
    },
    items: [],
    data_limitations: [],
  };
}

function radarV2OutcomeItem(
  rank: number,
  state: "close_confirmed" | "reversed"
) {
  const stockId = `${7000 + rank}`;
  return {
    evaluation_id: rank,
    stock_id: stockId,
    stock_name: `測試股 ${rank}`,
    source_rank: rank,
    status: "finalized",
    summary_state: state,
    horizon_end_trade_date: "2026-06-14",
    signal_close_return_pct: state === "reversed" ? -2 : 2,
    signal_mfe_pct: state === "reversed" ? 0 : 3,
    signal_mae_pct: state === "reversed" ? -4 : -1,
    outcome_quality: "final",
    pending_reason: null,
    limitations:
      rank === 1
        ? [
            { code: "entry_proxy_not_execution" },
            { code: "daily_ohlc_path_unordered" },
          ]
        : [],
  };
}

function radarV2OutcomeDetailSummary(snapshotDate: string) {
  const items = Array.from({ length: 30 }, (_, index) =>
    radarV2OutcomeItem(
      index + 1,
      index === 29 ? "reversed" : "close_confirmed"
    )
  );
  return {
    ...radarV2OutcomeSummary(snapshotDate),
    total_count: 30,
    finalized_count: 30,
    summary_state_counts: { close_confirmed: 29, reversed: 1 },
    items,
  };
}

function noRadarV2OutcomeSummary() {
  return {
    status: "no_snapshot",
    group_id: 7,
    mode: "action",
    snapshot_date: null,
    horizon_trading_days: 1,
    rule_version: "radar_v2.0",
    outcome_contract_version: "outcome_v2.0",
    total_count: 0,
    finalized_count: 0,
    pending_count: 0,
    latest_available_trade_date: null,
    last_reconciled_at: null,
    pending_reason_counts: {},
    summary_state_counts: {},
    items: [],
    data_limitations: [],
  };
}

function emptyRankingResponse(url: URL) {
  const groupId = Number(url.searchParams.get("group_id") ?? 0);
  const rankBy = url.searchParams.get("rank_by") ?? "none";

  return {
    group_id: groupId,
    include_children: true,
    rank_by: rankBy,
    sort_order: url.searchParams.get("sort_order") ?? "asc",
    requested_symbol_count: 0,
    ranked_count: 0,
    no_data_count: 0,
    error_count: 0,
    trade_date: "2026-06-15",
    target_trade_date: "2026-06-15",
    is_current: true,
    current_symbol_count: 0,
    stale_symbol_count: 0,
    results: [],
  };
}

function emptyTaiwanRankingBatch(url: URL) {
  const groupId = Number(url.pathname.match(/groups\/(\d+)/)?.[1] ?? 0);

  return {
    group_id: groupId,
    include_children: true,
    rank_by: url.searchParams.get("rank_by") ?? "watchlist",
    sort_order: url.searchParams.get("sort_order") ?? "asc",
    offset: Number(url.searchParams.get("offset") ?? 0),
    batch_size: Number(url.searchParams.get("batch_size") ?? 20),
    total_stock_count: 0,
    requested_stock_count: 0,
    ranked_count: 0,
    no_data_count: 0,
    error_count: 0,
    trade_date: "2026-06-15",
    target_trade_date: "2026-06-15",
    is_current: true,
    current_stock_count: 0,
    stale_stock_count: 0,
    has_more: false,
    results: [],
  };
}

function emptyTaiwanRankingResponse(url: URL) {
  const batch = emptyTaiwanRankingBatch(url);

  return {
    group_id: batch.group_id,
    include_children: batch.include_children,
    rank_by: batch.rank_by,
    sort_order: batch.sort_order,
    requested_stock_count: batch.requested_stock_count,
    ranked_count: batch.ranked_count,
    no_data_count: batch.no_data_count,
    error_count: batch.error_count,
    trade_date: batch.trade_date,
    target_trade_date: batch.target_trade_date,
    is_current: batch.is_current,
    current_stock_count: batch.current_stock_count,
    stale_stock_count: batch.stale_stock_count,
    results: batch.results,
  };
}

function seededTaiwanRankingBatch(
  url: URL,
  rows: ReturnType<typeof seededTaiwanRankingRows>
) {
  const empty = emptyTaiwanRankingBatch(url);
  const offset = empty.offset;
  const batchSize = empty.batch_size;
  const results = rows.slice(offset, offset + batchSize);

  return {
    ...empty,
    total_stock_count: rows.length,
    requested_stock_count: results.length,
    ranked_count: results.length,
    current_stock_count: results.length,
    has_more: offset + results.length < rows.length,
    results,
  };
}

function seededUsRankingResponse(
  url: URL,
  rows: ReturnType<typeof seededUsRankingRows>
) {
  return {
    ...emptyRankingResponse(url),
    group_id: Number(url.searchParams.get("group_id") ?? 17),
    requested_symbol_count: rows.length,
    ranked_count: rows.length,
    current_symbol_count: rows.length,
    results: rows,
  };
}

function seededJpRankingResponse(
  url: URL,
  rows: ReturnType<typeof seededJpRankingRows>
) {
  return {
    ...emptyRankingResponse(url),
    group_id: Number(url.searchParams.get("group_id") ?? 27),
    requested_symbol_count: rows.length,
    ranked_count: rows.length,
    current_symbol_count: rows.length,
    results: rows,
  };
}

function seededKrRankingResponse(
  url: URL,
  rows: ReturnType<typeof seededKrRankingRows>
) {
  return {
    ...emptyRankingResponse(url),
    group_id: Number(url.searchParams.get("group_id") ?? 37),
    requested_symbol_count: rows.length,
    ranked_count: rows.length,
    current_symbol_count: rows.length,
    results: rows,
  };
}

function usOhlcResponse(symbol: string) {
  return {
    symbol,
    timeframe: "daily",
    bars: 60,
    lookback_days: 120,
    from_date: points[0].time,
    to_date: points[points.length - 1].time,
    point_count: points.length,
    points: points.map(({ time, open, high, low, close, volume }) => ({
      time,
      open,
      high,
      low,
      close,
      volume,
    })),
    backfill: null,
    intraday_overlay: null,
  };
}

function usIntradayResponse(symbol: string) {
  return {
    stock_id: symbol,
    symbol,
    source: "playwright.fixture",
    session_scope: "regular",
    session_phase: "regular",
    has_extended_hours: false,
    previous_close: 940,
    point_count: 2,
    points: [
      { time: "2026-06-15T09:00:00-04:00", price: 942, volume: 1000 },
      { time: "2026-06-15T09:30:00-04:00", price: 948, volume: 1200 },
    ],
    warnings: [],
  };
}

function regionalOhlcResponse(symbol: string) {
  return {
    symbol,
    timeframe: "daily",
    bars: 60,
    lookback_days: 120,
    from_date: points[0].time,
    to_date: points[points.length - 1].time,
    point_count: points.length,
    points: points.map(({ time, open, high, low, close, volume }) => ({
      time,
      open,
      high,
      low,
      close,
      volume,
    })),
    backfill: null,
  };
}

function regionalIntradayResponse(symbol: string) {
  return {
    stock_id: symbol,
    symbol,
    source: "playwright.fixture",
    session_scope: "regular",
    session_phase: "regular",
    has_extended_hours: false,
    previous_close: 940,
    point_count: 2,
    points: [
      { time: "2026-06-15T09:00:00+09:00", price: 942, volume: 1000 },
      { time: "2026-06-15T09:30:00+09:00", price: 948, volume: 1200 },
    ],
    warnings: [],
  };
}

function krIndexOhlcResponse(indexId: string) {
  const chart = regionalOhlcResponse(indexId);

  return {
    ...chart,
    index_id: indexId,
    provider_symbol: indexId === "KOSDAQ" ? "^KQ11" : "^KS11",
    name: indexId === "KOSDAQ" ? "KOSDAQ Composite" : "KOSPI Composite",
    short_name: indexId,
  };
}

function krIndexBreadthResponse(indexId: string) {
  return {
    index_id: indexId,
    market_segment: indexId,
    trade_date: "2026-06-15",
    advance_count: 520,
    decline_count: 310,
    unchanged_count: 70,
    total_count: 900,
    positive_ratio: 57.78,
    advance_decline_ratio: 1.68,
    average_change_pct: 0.42,
    trade_value: 12_500_000_000,
    source: "playwright.fixture",
    status: "success",
    coverage_note: null,
  };
}

function emptyKrWatchlistReadiness(groupId: number | null) {
  return {
    kind: "kr_watchlist_readiness",
    group_id: groupId,
    include_children: true,
    enabled_only: true,
    expected_daily_price_date: "2026-06-15",
    summary: {
      requested_symbol_count: 0,
      ready_count: 0,
      partial_count: 0,
      no_data_count: 0,
      daily_current_count: 0,
      daily_stale_count: 0,
      daily_empty_count: 0,
      investor_available_count: 0,
      fundamental_available_count: 0,
    },
    results: [],
  };
}

function emptyUsSecInsiderTransactions(symbol: string) {
  return {
    contract_version: "omi.sec.insiders.v1",
    symbol,
    cik: null,
    status: "missing",
    as_of: null,
    freshness: {
      status: "missing",
      last_checked_at: null,
      last_success_at: null,
      latest_filing_date: null,
      latest_accession_number: null,
      basis: "sec_ownership_filing_observation",
      observation_window_hours: 24,
    },
    summary: {
      filing_count: 0,
      amendment_count: 0,
      transaction_count: 0,
      open_market_purchase_count: 0,
      open_market_sale_count: 0,
      open_market_purchase_shares: null,
      open_market_sale_shares: null,
      other_transaction_count: 0,
      latest_transaction_date: null,
    },
    transactions: [],
    quality: {
      issue_codes: [],
      warnings: [],
      limitations: [
        "Form 4 reports changes and row-level post-transaction amounts; without Forms 3 and 5, this contract does not claim a complete current insider position.",
      ],
    },
    source_refs: [],
    pagination: { limit: 100, returned_count: 0, next_cursor: null },
  };
}

function emptyUsSecInstitutionalHoldings(symbol: string) {
  return {
    contract_version: "omi.sec.13f.v1",
    symbol,
    cik: null,
    status: "missing",
    as_of: null,
    freshness: {
      status: "missing",
      latest_release_period: null,
      reason: "No approved CUSIP-to-symbol projection is available for this symbol.",
    },
    summary: {},
    quarters: [],
    managers: [],
    quality: {
      decision_usable: false,
      limitations: [
        "Form 13F is a delayed quarterly filing and is not a current-position feed.",
      ],
    },
    source_refs: [],
  };
}

function completedRefreshJob() {
  const timestamp = "2026-06-15T09:30:00+08:00";

  return {
    id: 1,
    job_type: "watchlist_refresh_latest",
    status: "success",
    target: "group:7",
    progress_current: 2,
    progress_total: 2,
    message: "Playwright refresh fixture completed.",
    error_message: null,
    request: {},
    result: { status: "success", error_count: 0 },
    created_at: timestamp,
    started_at: timestamp,
    ended_at: timestamp,
    updated_at: timestamp,
  };
}

async function fulfillJson(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function fulfillOmiStream(route: Route) {
  const chunks = [
    ["status", { stage: "question_understanding", message: "已辨識測試問題。" }],
    ["evidence", { source_count: 2, trust_level: "high" }],
    [
      "final",
      {
        kind: "omi_decision",
        contract_version: "omi.decision.v4",
        ok: true,
        request_status: "completed",
        target: { type: "tw_stock", id: "2330", market: "TW" },
        mode: { requested: "brief", effective: "brief", response: "analysis" },
        status: {
          readiness: {
            facts_ready: true,
            analysis_ready: true,
            answer_ready: true,
            decision_ready: true,
          },
        },
        answer: {
          headline: "測試回答：目前偏多但等待確認",
          stance: "偏多",
          confidence: "中",
          summary: ["測試資料已讀取", "價位仍需突破確認"],
          detail: "測試回答已直接取自 canonical envelope。",
          source: "playwright.fixture",
        },
        decision: {
          intent: "entry_decision",
          action_plan: [{ label: "現在", text: "先觀察，不追價。" }],
          scenarios: [],
          counter_evidence: [],
          risks: ["跌破短線支撐則失效。"],
          data_limits: [],
        },
        evidence: {
          slots: {
            quote: {
              status: "ready",
              freshness: { status: "daily_close" },
              usability: "usable",
            },
          },
          source_refs: [{ name: "playwright.fixture" }],
        },
        limitations: { missing: [], warnings: [], provider_failures: [] },
        execution: { tool_runs: [] },
        continuation: { resolution: {}, next_context: {} },
        error: {},
      },
    ],
    ["done", { ok: true, transport_ok: true, request_status: "completed" }],
  ];
  const body = chunks
    .map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");

  await route.fulfill({
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-store",
    },
    body,
  });
}

type MockOmiApiOptions = {
  portfolioHoldingsPayload?: unknown;
  taiwanWatchlistTree?: ReturnType<typeof seededTaiwanWatchlistTree>;
  taiwanWatchlistItems?: ReturnType<typeof seededTaiwanWatchlistItems>;
  taiwanRankingRows?: ReturnType<typeof seededTaiwanRankingRows>;
  usWatchlistTree?: ReturnType<typeof seededUsWatchlistTree>;
  usWatchlistItems?: ReturnType<typeof seededUsWatchlistItems>;
  usRankingRows?: ReturnType<typeof seededUsRankingRows>;
  jpWatchlistTree?: ReturnType<typeof seededJpWatchlistTree>;
  jpWatchlistItems?: ReturnType<typeof seededJpWatchlistItems>;
  jpRankingRows?: ReturnType<typeof seededJpRankingRows>;
  krWatchlistTree?: ReturnType<typeof seededKrWatchlistTree>;
  krWatchlistItems?: ReturnType<typeof seededKrWatchlistItems>;
  krRankingRows?: ReturnType<typeof seededKrRankingRows>;
  regionalRankingResponder?: (context: {
    market: "us" | "jp" | "kr";
    requestNumber: number;
    url: URL;
  }) =>
    | Promise<{ body: unknown; delayMs?: number; status?: number } | null>
    | { body: unknown; delayMs?: number; status?: number }
    | null;
  radarResponder?: (context: {
    market: "tw" | "us" | "jp" | "kr";
    groupId: number;
    requestNumber: number;
    url: URL;
  }) =>
    | Promise<{ body: unknown; delayMs?: number; status?: number } | null>
    | { body: unknown; delayMs?: number; status?: number }
    | null;
  marketTapeResponder?: (context: {
    market: "tw" | "us" | "jp" | "kr";
    kind: "summary" | "ohlc" | "intraday" | "breadth";
    target: string;
    requestNumber: number;
    url: URL;
  }) =>
    | Promise<{ body: unknown; delayMs?: number; status?: number } | null>
    | { body: unknown; delayMs?: number; status?: number }
    | null;
  apiResponder?: (context: {
    method: string;
    path: string;
    requestNumber: number;
    url: URL;
  }) =>
    | Promise<{ body: unknown; delayMs?: number; status?: number } | null>
    | { body: unknown; delayMs?: number; status?: number }
    | null;
  apiRequests?: Array<{
    body: unknown;
    method: string;
    path: string;
    search: string;
  }>;
  omiAskRequests?: unknown[];
  taiwanRadarV2OutcomeLatest?: unknown;
  taiwanRadarV2OutcomeHistory?: unknown[];
  taiwanRadarV2OutcomeSnapshots?: Record<string, unknown>;
};

async function mockOmiApi(page: Page, options: MockOmiApiOptions = {}) {
  const portfolioHoldingsPayload = options.portfolioHoldingsPayload ?? [];
  const taiwanWatchlistTree = options.taiwanWatchlistTree ?? [];
  const taiwanWatchlistItems = options.taiwanWatchlistItems ?? [];
  const taiwanRankingRows = options.taiwanRankingRows ?? [];
  const usWatchlistTree = options.usWatchlistTree ?? [];
  const usWatchlistItems = options.usWatchlistItems ?? [];
  const usRankingRows = options.usRankingRows ?? [];
  const jpWatchlistTree = options.jpWatchlistTree ?? [];
  const jpWatchlistItems = options.jpWatchlistItems ?? [];
  const jpRankingRows = options.jpRankingRows ?? [];
  const krWatchlistTree = options.krWatchlistTree ?? [];
  const krWatchlistItems = options.krWatchlistItems ?? [];
  const krRankingRows = options.krRankingRows ?? [];
  const regionalRankingRequestCounts = { us: 0, jp: 0, kr: 0 };
  const radarRequestCounts = { tw: 0, us: 0, jp: 0, kr: 0 };
  const marketTapeRequestCounts = new Map<string, number>();
  const apiRequestCounts = new Map<string, number>();

  async function tryFulfillMarketTape(
    route: Route,
    url: URL,
    market: "tw" | "us" | "jp" | "kr",
    kind: "summary" | "ohlc" | "intraday" | "breadth",
    target: string
  ) {
    const key = `${market}:${kind}:${target}`;
    const requestNumber = (marketTapeRequestCounts.get(key) ?? 0) + 1;
    marketTapeRequestCounts.set(key, requestNumber);
    const customResponse = await options.marketTapeResponder?.({
      market,
      kind,
      target,
      requestNumber,
      url,
    });

    if (!customResponse) return false;

    if (customResponse.delayMs) {
      await new Promise((resolve) => setTimeout(resolve, customResponse.delayMs));
    }
    await route.fulfill({
      status: customResponse.status ?? 200,
      contentType: "application/json",
      body: JSON.stringify(customResponse.body),
    });
    return true;
  }

  await page.route("**/omi-data/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    const requestBody = route.request().postDataJSON() ?? null;
    const requestKey = `${method}:${path}`;
    const requestNumber = (apiRequestCounts.get(requestKey) ?? 0) + 1;
    apiRequestCounts.set(requestKey, requestNumber);
    options.apiRequests?.push({
      body: requestBody,
      method,
      path,
      search: url.search,
    });

    const customApiResponse = await options.apiResponder?.({
      method,
      path,
      requestNumber,
      url,
    });
    if (customApiResponse) {
      if (customApiResponse.delayMs) {
        await new Promise((resolve) => setTimeout(resolve, customApiResponse.delayMs));
      }
      await route.fulfill({
        status: customApiResponse.status ?? 200,
        contentType: "application/json",
        body: JSON.stringify(customApiResponse.body),
      });
      return;
    }

    if (path.endsWith("/system/readyz")) {
      await fulfillJson(route, {
        status: "ready",
        checks: { runtime: "ok", database: "ok" },
      });
      return;
    }

    if (path.endsWith("/system/health")) {
      await fulfillJson(route, { status: "ok" });
      return;
    }

    if (path.endsWith("/ai/ask/stream")) {
      options.omiAskRequests?.push(route.request().postDataJSON());
      await fulfillOmiStream(route);
      return;
    }

    if (path.includes("/market/calendar-status")) {
      await fulfillJson(route, calendarStatus());
      return;
    }

    if (path.includes("/market/indices/summary/refresh-job")) {
      await fulfillJson(route, completedRefreshJob());
      return;
    }

    if (path.includes("/market/indices/summary")) {
      if (await tryFulfillMarketTape(route, url, "tw", "summary", "summary")) return;
      await fulfillJson(route, marketIndexSummaryResponse(861));
      return;
    }

    if (path.includes("/market/tw-futures/latest")) {
      await fulfillJson(route, []);
      return;
    }

    if (/\/market\/tw-futures\/[^/]+\/daily\/refresh$/.test(path)) {
      await fulfillJson(route, completedRefreshJob());
      return;
    }

    if (/\/market\/tw-futures\/[^/]+\/(?:intraday|daily)$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    if (path.includes("/jp-market/overview")) {
      await fulfillJson(route, {
        kind: "jp_market_overview",
        generated_at: "2026-06-15T15:30:00+09:00",
        expected_trade_date: "2026-06-15",
        calendar_status: {},
        coverage: {
          scope: "playwright_fixture",
          active_stock_count: 0,
          observed_symbol_count: 0,
          current_symbol_count: 0,
          stale_symbol_count: 0,
          missing_symbol_count: 0,
          active_coverage_ratio: 0,
          observed_current_ratio: 0,
          status: "empty",
          is_partial: true,
        },
        watchlist_coverage: {},
        breadth: {
          trade_date: null,
          advance_count: 0,
          decline_count: 0,
          unchanged_count: 0,
          no_comparison_count: 0,
          total_count: 0,
          coverage_count: 0,
          source: "playwright.fixture",
          is_partial: true,
        },
        sectors: [],
        indices: [],
        top_gainers: [],
        top_losers: [],
        source_health: {},
        refresh_recommended: false,
        refresh_scope: "none",
        warnings: [],
      });
      return;
    }

    if (path.includes("/market/indices/list")) {
      await fulfillJson(route, {
        market: "TWSE",
        source: "playwright.fixture",
        as_of: "2026-06-15T09:30:00+08:00",
        count: 0,
        items: [],
      });
      return;
    }

    if (path.includes("/market/indices/TAIEX/contributions")) {
      await fulfillJson(route, {
        index_id: "TAIEX",
        market: "TWSE",
        source: "playwright.fixture",
        method: "fixture",
        as_of: "2026-06-15T09:30:00+08:00",
        trade_date: "2026-06-15",
        index_close: 861,
        index_change: 12,
        total_market_value: null,
        positive: [],
        negative: [],
      });
      return;
    }

    if (path.includes("/market/indices/TAIEX/intraday")) {
      await fulfillJson(route, {
        stock_id: "TAIEX",
        symbol: "^TWII",
        source: "twse_index_5s_twse_mis_snapshot",
        trade_date: "2026-06-15",
        previous_close: 849,
        interval: "1m",
        source_interval: "5s",
        effective_interval: "1m",
        source_point_count: 3_242,
        point_count: 2,
        capabilities: {
          supports_volume: false,
          supports_vwap: false,
          supports_price_limit: false,
          supports_quote_depth: false,
        },
        current_observation: {
          value: 861,
          observed_at: "2026-06-15T13:30:00+08:00",
          confirmed_at: "2026-06-15T13:33:00+08:00",
          price_semantics: "official_index_close",
          provider: "playwright.fixture",
          freshness_status: "post_close_final",
          decision_usable: true,
        },
        points: [
          {
            time: "2026-06-15T09:00:00+08:00",
            price: 850,
            volume: null,
            open: 850,
            high: 850,
            low: 850,
            bar_type: "regular_interval",
            display_eligible: true,
            indicator_eligible: true,
          },
          {
            time: "2026-06-15T13:30:00+08:00",
            price: 861,
            volume: null,
            open: 861,
            high: 861,
            low: 861,
            bar_type: "official_close_marker",
            display_eligible: true,
            indicator_eligible: true,
          },
        ],
      });
      return;
    }

    if (path.includes("/market/indices/TAIEX/ohlc")) {
      await fulfillJson(route, ohlcResponse("TAIEX"));
      return;
    }

    const taiwanOhlcMatch = path.match(/\/market\/ohlc\/([^/]+)$/);
    if (taiwanOhlcMatch) {
      await fulfillJson(route, stockOhlcResponse(decodeURIComponent(taiwanOhlcMatch[1])));
      return;
    }

    const taiwanIndicatorMatch = path.match(/\/market\/indicators\/([^/]+)\/daily$/);
    if (taiwanIndicatorMatch) {
      await fulfillJson(route, []);
      return;
    }

    const taiwanIntradayHistoryMatch = path.match(/\/market\/intraday\/([^/]+)\/history$/);
    if (taiwanIntradayHistoryMatch) {
      const stockId = decodeURIComponent(taiwanIntradayHistoryMatch[1]);
      await fulfillJson(route, {
        stock_id: stockId,
        symbol: stockId,
        interval: url.searchParams.get("interval") ?? "5m",
        range: url.searchParams.get("range") ?? "auto",
        provider: "playwright.fixture",
        source: "playwright.fixture",
        from_time: null,
        to_time: null,
        point_count: 0,
        cached_count: 0,
        refreshed_count: 0,
        points: [],
      });
      return;
    }

    const taiwanIntradayMatch = path.match(/\/market\/intraday\/([^/]+)$/);
    if (taiwanIntradayMatch) {
      await fulfillJson(route, intradayResponse(decodeURIComponent(taiwanIntradayMatch[1])));
      return;
    }

    if (path.endsWith("/market/realtime-quote-leases") && method === "POST") {
      const payload = route.request().postDataJSON() as { stock_id?: string };
      await fulfillJson(route, {
        lease_id: `playwright-${payload.stock_id ?? "unknown"}`,
        stock_id: payload.stock_id ?? "unknown",
        provider: "kgi_superpy",
        status: "live",
        expires_in_seconds: 60,
        fallback_source: "twse_mis_quote_depth",
        message: "Playwright fixture lease",
        error: null,
      });
      return;
    }

    const taiwanQuoteLeaseMatch = path.match(
      /\/market\/realtime-quote-leases\/([^/]+)$/
    );
    if (taiwanQuoteLeaseMatch && method === "PATCH") {
      const stockId = decodeURIComponent(taiwanQuoteLeaseMatch[1]).replace(
        /^playwright-/,
        ""
      );
      await fulfillJson(route, {
        lease_id: decodeURIComponent(taiwanQuoteLeaseMatch[1]),
        stock_id: stockId,
        provider: "kgi_superpy",
        status: "live",
        expires_in_seconds: 60,
        fallback_source: "twse_mis_quote_depth",
        message: "Playwright fixture heartbeat",
        error: null,
      });
      return;
    }
    if (taiwanQuoteLeaseMatch && method === "DELETE") {
      await route.fulfill({ status: 204, body: "" });
      return;
    }

    if (/\/market\/realtime-quotes\/[^/]+\/stream$/.test(path)) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Playwright uses snapshot fallback" }),
      });
      return;
    }

    const taiwanQuoteDepthMatch = path.match(/\/market\/quote-depth\/([^/]+)$/);
    const taiwanQuoteReplayMatch = path.match(
      /\/market\/quote-depth\/([^/]+)\/replay$/
    );
    if (taiwanQuoteReplayMatch) {
      await fulfillJson(
        route,
        emptyQuoteReplayResponse(decodeURIComponent(taiwanQuoteReplayMatch[1]))
      );
      return;
    }
    if (taiwanQuoteDepthMatch) {
      await fulfillJson(route, quoteDepthResponse(decodeURIComponent(taiwanQuoteDepthMatch[1])));
      return;
    }

    const taiwanNextSessionPlanMatch = path.match(
      /\/market\/technical\/([^/]+)\/next-session-plan$/
    );
    if (taiwanNextSessionPlanMatch) {
      await fulfillJson(
        route,
        nextSessionPlanResponse(
          decodeURIComponent(taiwanNextSessionPlanMatch[1])
        )
      );
      return;
    }

    const taiwanTechnicalMatch = path.match(/\/market\/technical\/([^/]+)$/);
    if (taiwanTechnicalMatch) {
      const stockId = decodeURIComponent(taiwanTechnicalMatch[1]);
      await fulfillJson(route, {
        kind: "stock_technical_report",
        stock_id: stockId,
        timeframe: url.searchParams.get("timeframe") ?? "daily",
        phase: "regular",
        confidence: "medium",
        generated_at: "2026-06-15T09:30:00+08:00",
        title: "空方趨勢延續",
        summary: "3/3 均線下方，超賣但尚未止跌，放量下跌",
        score: 1,
        value: -25.31,
        value_label: "vs MA20",
        rows: [
          {
            key: "institutional_flow",
            label: "法人籌碼",
            description: "最近三大法人合計，融資餘額 -254",
            display_value: "-165張",
            value: -165,
            direction: -165,
            tone: "negative",
          },
        ],
        badges: [],
        data: {
          current_state: {
            version: "tw_technical_current_state_v1",
            headline: {
              key: "bearish_trend",
              label: "空方趨勢延續",
              tone: "negative",
            },
            qualifier: {
              key: "oversold_not_reversed",
              label: "超賣但尚未止跌",
              tone: "warning",
            },
            summary: "失守 3/3 條均線；超賣但尚未止跌；放量下跌",
            position: {
              price: 138,
              label: "失守 MA5/MA20/MA60",
              below_count: 3,
              above_count: 0,
              available_count: 3,
              order: ["ma5", "ma60", "ma20"],
              order_label: "MA5 139.6 < MA60 149.28 < MA20 184.78",
              alignment: "mixed",
              alignment_label: "均線排列轉換中",
              distance_pct: {
                ma5: -1.15,
                ma20: -25.31,
                ma60: -7.56,
              },
            },
            levels: [
              {
                key: "support20",
                role: "risk",
                label: "20 日低點",
                price: 128.5,
                move_required_pct: -6.88,
                reference_distance_pct: 7.42,
                tone: "negative",
              },
              {
                key: "ma5",
                role: "reclaim",
                label: "MA5",
                price: 139.6,
                move_required_pct: 1.16,
                reference_distance_pct: -1.15,
                tone: "warning",
              },
              {
                key: "ma60",
                role: "reclaim",
                label: "MA60",
                price: 149.28,
                move_required_pct: 8.17,
                reference_distance_pct: -7.56,
                tone: "warning",
              },
              {
                key: "ma20",
                role: "reclaim",
                label: "MA20",
                price: 184.78,
                move_required_pct: 33.9,
                reference_distance_pct: -25.31,
                tone: "warning",
              },
            ],
            evidence: [
              {
                key: "trend",
                label: "趨勢證據",
                state_key: "bearish_trend",
                state_label: "空方趨勢延續",
                tone: "negative",
                summary: "ADX 30.09，-DI 31.94 高於 +DI 22.63；收盤失守 3/3 條均線。",
                metrics: { adx14: 30.09, plus_di14: 22.63, minus_di14: 31.94 },
              },
              {
                key: "momentum",
                label: "動能與超賣",
                state_key: "oversold_not_reversed",
                state_label: "超賣但尚未止跌",
                tone: "warning",
                summary: "RSI 24.86，MACD 柱 -8.54，ROC12 -35.81%。",
                metrics: { rsi14: 24.86, macd_hist: -8.54, roc12: -35.81 },
              },
              {
                key: "volume",
                label: "量價確認",
                state_key: "down_on_high_volume",
                state_label: "放量下跌",
                tone: "negative",
                summary: "日跌 -8.00%，量能為 20 日均量 1.56 倍。",
                metrics: { change_pct: -8, volume_ratio20: 1.56 },
              },
              {
                key: "risk",
                label: "風險與區間",
                state_key: "near_range_bottom",
                state_label: "接近20日區間底部",
                tone: "warning",
                summary: "位於 20 日區間 7.42% 分位，ATR 12.48%。",
                metrics: { donchian_position20_pct: 7.42, atr14_pct: 12.48 },
              },
            ],
            next_conditions: [
              {
                key: "first_reclaim",
                label: "先站回 MA5",
                tone: "warning",
                level_key: "ma5",
                price: 139.6,
              },
              {
                key: "structure_repair",
                label: "站回 MA60",
                tone: "warning",
                level_key: "ma60",
                price: 149.28,
              },
              {
                key: "risk_break",
                label: "跌破 20 日低點",
                tone: "negative",
                level_key: "support20",
                price: 128.5,
              },
            ],
          },
        },
        missing: [],
        warnings: [],
        source_refs: [],
      });
      return;
    }

    const taiwanStockMatch = path.match(/\/stocks\/([^/]+)$/);
    if (taiwanStockMatch) {
      const stockId = decodeURIComponent(taiwanStockMatch[1]);
      const watchlistItem = taiwanWatchlistItems.find(
        (candidate) => candidate.stock_id === stockId
      );
      const stockMaster = stockMasterResponse(stockId);
      await fulfillJson(route, {
        ...stockMaster,
        stock_name: watchlistItem?.stock_name ?? stockMaster.stock_name,
        market: watchlistItem?.market ?? stockMaster.market,
        instrument_type: watchlistItem?.instrument_type ?? stockMaster.instrument_type,
      });
      return;
    }

    const taiwanRealtimeQuoteMatch = path.match(
      /\/market\/realtime-quotes\/([^/]+)$/
    );
    if (taiwanRealtimeQuoteMatch) {
      await fulfillJson(
        route,
        realtimeQuoteStreamResponse(
          decodeURIComponent(taiwanRealtimeQuoteMatch[1])
        )
      );
      return;
    }

    if (/\/market\/(?:institutional|margin|revenue)\/[^/]+\/latest$/.test(path)) {
      await fulfillJson(route, null);
      return;
    }

    if (/\/market\/overnight-impact\/[^/]+$/.test(path)) {
      await fulfillJson(route, null);
      return;
    }

    if (/\/us-market\/ohlc\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "SPY");
      if (await tryFulfillMarketTape(route, url, "us", "ohlc", symbol)) return;
      await fulfillJson(route, usOhlcResponse(symbol));
      return;
    }

    if (/\/us-market\/intraday\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "SPY");
      if (await tryFulfillMarketTape(route, url, "us", "intraday", symbol)) return;
      await fulfillJson(route, usIntradayResponse(symbol));
      return;
    }

    const usStockMatch = path.match(/\/us-market\/stocks\/([^/]+)$/);
    if (usStockMatch) {
      const symbol = decodeURIComponent(usStockMatch[1]);
      const item = usWatchlistItems.find((candidate) => candidate.symbol === symbol);
      if (item) {
        await fulfillJson(route, {
          id: item.id,
          symbol: item.symbol,
          security_name: item.security_name,
          exchange: item.exchange,
          asset_type: item.asset_type,
          listing_source: "playwright.fixture",
          market_category: null,
          financial_status: null,
          cqs_symbol: null,
          nasdaq_symbol: item.symbol,
          cik: null,
          sec_company_name: null,
          is_etf: false,
          is_test_issue: false,
          round_lot_size: 100,
          is_active: item.enabled,
          first_seen_at: item.created_at,
          last_seen_at: item.updated_at,
          created_at: item.created_at,
          updated_at: item.updated_at,
        });
        return;
      }
    }

    if (/\/us-market\/sec\/[^/]+\/facts$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    if (/\/us-market\/sec\/[^/]+\/fundamentals$/.test(path)) {
      await fulfillJson(route, null);
      return;
    }

    if (/\/us-market\/sec\/[^/]+\/financials$/.test(path)) {
      await fulfillJson(route, null);
      return;
    }

    const usSecInsiderMatch = path.match(
      /\/us-market\/sec\/([^/]+)\/insider-transactions$/
    );
    if (usSecInsiderMatch) {
      await fulfillJson(
        route,
        emptyUsSecInsiderTransactions(decodeURIComponent(usSecInsiderMatch[1]))
      );
      return;
    }

    const usSecInstitutionalMatch = path.match(
      /\/us-market\/sec\/([^/]+)\/institutional-holdings$/
    );
    if (usSecInstitutionalMatch) {
      await fulfillJson(
        route,
        emptyUsSecInstitutionalHoldings(decodeURIComponent(usSecInstitutionalMatch[1]))
      );
      return;
    }

    if (/\/us-market\/profiles\/[^/]+$/.test(path)) {
      await fulfillJson(route, null);
      return;
    }

    if (/\/us-market\/corporate-actions\/[^/]+$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    const usCorporateEventSummaryMatch = path.match(
      /\/us-market\/corporate-events\/([^/]+)\/summary$/
    );
    if (usCorporateEventSummaryMatch) {
      await fulfillJson(
        route,
        usCorporateEventSummaryResponse(
          decodeURIComponent(usCorporateEventSummaryMatch[1])
        )
      );
      return;
    }

    if (/\/us-market\/short-volume\/[^/]+\/history$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    if (/\/jp-market\/ohlc\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "^N225");
      if (await tryFulfillMarketTape(route, url, "jp", "ohlc", symbol)) return;
      await fulfillJson(route, regionalOhlcResponse(symbol));
      return;
    }

    if (/\/jp-market\/intraday\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "^N225");
      if (await tryFulfillMarketTape(route, url, "jp", "intraday", symbol)) return;
      await fulfillJson(route, regionalIntradayResponse(symbol));
      return;
    }

    const jpStockMatch = path.match(/\/jp-market\/stocks\/([^/]+)$/);
    if (jpStockMatch) {
      const symbol = decodeURIComponent(jpStockMatch[1]);
      const item = jpWatchlistItems.find((candidate) => candidate.symbol === symbol);
      if (item) {
        await fulfillJson(route, {
          id: item.id,
          symbol: item.symbol,
          local_code: item.local_code,
          security_name: item.security_name,
          exchange: item.exchange,
          market_segment: item.market_segment,
          sector_33_code: null,
          sector_33_name: item.sector_33_name,
          sector_17_code: null,
          sector_17_name: null,
          size_code: null,
          size_name: null,
          asset_type: item.asset_type,
          listing_source: "playwright.fixture",
          currency: "JPY",
          exchange_timezone_name: "Asia/Tokyo",
          is_active: item.enabled,
          first_seen_at: item.created_at,
          last_seen_at: item.updated_at,
          created_at: item.created_at,
          updated_at: item.updated_at,
        });
        return;
      }
    }

    if (/\/jp-market\/resources\/[^/]+\/summary$/.test(path)) {
      await fulfillJson(route, null);
      return;
    }

    const jpFundamentalMatch = path.match(/\/jp-market\/fundamentals\/([^/]+)$/);
    if (jpFundamentalMatch) {
      const symbol = decodeURIComponent(jpFundamentalMatch[1]);
      const timestamp = "2026-06-15T09:30:00+09:00";
      await fulfillJson(route, {
        id: 1,
        provider: "playwright.fixture",
        symbol,
        company_name: null,
        exchange: null,
        sector: null,
        industry: null,
        currency: "JPY",
        market_cap: null,
        enterprise_value: null,
        trailing_pe: null,
        forward_pe: null,
        price_to_book: null,
        dividend_yield: null,
        beta: null,
        disclosed_date: "2026-06-15",
        fiscal_period: null,
        fiscal_year_end: null,
        document_type: null,
        eps_ttm: null,
        forward_eps: null,
        revenue_ttm: null,
        net_sales: null,
        operating_profit: null,
        ordinary_profit: null,
        profit: null,
        forecast_net_sales: null,
        forecast_operating_profit: null,
        forecast_ordinary_profit: null,
        forecast_profit: null,
        gross_margin: null,
        operating_margin: null,
        profit_margin: null,
        return_on_equity: null,
        return_on_assets: null,
        revenue_growth: null,
        earnings_growth: null,
        total_assets: null,
        equity: null,
        equity_to_asset_ratio: null,
        total_cash: null,
        total_debt: null,
        operating_cash_flow: null,
        investing_cash_flow: null,
        financing_cash_flow: null,
        debt_to_equity: null,
        current_ratio: null,
        quick_ratio: null,
        shares_outstanding: null,
        book_value: null,
        earnings_date: null,
        ex_dividend_date: null,
        source_url: null,
        raw_payload_hash: null,
        fetched_at: timestamp,
        created_at: timestamp,
        updated_at: timestamp,
      });
      return;
    }

    const krIndexOhlcMatch = path.match(/\/kr-market\/indices\/([^/]+)\/ohlc$/);
    if (krIndexOhlcMatch) {
      const indexId = decodeURIComponent(krIndexOhlcMatch[1]);
      if (await tryFulfillMarketTape(route, url, "kr", "ohlc", indexId)) return;
      await fulfillJson(route, krIndexOhlcResponse(indexId));
      return;
    }

    if (/\/kr-market\/ohlc\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "005930.KS");
      await fulfillJson(route, regionalOhlcResponse(symbol));
      return;
    }

    const krIndexIntradayMatch = path.match(/\/kr-market\/indices\/([^/]+)\/intraday$/);
    if (krIndexIntradayMatch) {
      const indexId = decodeURIComponent(krIndexIntradayMatch[1]);
      if (await tryFulfillMarketTape(route, url, "kr", "intraday", indexId)) return;
      await fulfillJson(route, regionalIntradayResponse(indexId));
      return;
    }

    const krIndexBreadthMatch = path.match(/\/kr-market\/indices\/([^/]+)\/breadth$/);
    if (krIndexBreadthMatch) {
      const indexId = decodeURIComponent(krIndexBreadthMatch[1]);
      if (await tryFulfillMarketTape(route, url, "kr", "breadth", indexId)) return;
      await fulfillJson(route, krIndexBreadthResponse(indexId));
      return;
    }

    const krStockMatch = path.match(/\/kr-market\/stocks\/([^/]+)$/);
    if (krStockMatch) {
      const symbol = decodeURIComponent(krStockMatch[1]);
      const item = krWatchlistItems.find((candidate) => candidate.symbol === symbol);
      if (item) {
        await fulfillJson(route, {
          id: item.id,
          symbol: item.symbol,
          local_code: item.local_code,
          security_name: item.security_name,
          security_name_kr: item.security_name_kr,
          exchange: item.exchange,
          market_segment: item.market_segment,
          sector: item.sector,
          industry: item.industry,
          asset_type: item.asset_type,
          listing_source: "playwright.fixture",
          currency: "KRW",
          exchange_timezone_name: "Asia/Seoul",
          is_active: item.enabled,
          first_seen_at: item.created_at,
          last_seen_at: item.updated_at,
          created_at: item.created_at,
          updated_at: item.updated_at,
        });
        return;
      }
      if (["KOSPI", "KOSDAQ", "KOSPI200"].includes(symbol)) {
        const timestamp = "2026-06-15T09:30:00+09:00";
        await fulfillJson(route, {
          id: 0,
          symbol,
          local_code: symbol,
          security_name: symbol === "KOSDAQ" ? "KOSDAQ Composite" : symbol,
          security_name_kr: null,
          exchange: "KRX",
          market_segment: symbol === "KOSDAQ" ? "KOSDAQ" : "KOSPI",
          sector: null,
          industry: null,
          asset_type: "index",
          listing_source: "playwright.fixture",
          currency: "KRW",
          exchange_timezone_name: "Asia/Seoul",
          is_active: true,
          first_seen_at: timestamp,
          last_seen_at: timestamp,
          created_at: timestamp,
          updated_at: timestamp,
        });
        return;
      }
    }

    if (/\/kr-market\/resources\/[^/]+\/summary$/.test(path)) {
      await fulfillJson(route, null);
      return;
    }

    if (path.endsWith("/kr-market/fundamentals")) {
      await fulfillJson(route, []);
      return;
    }

    if (/\/kr-market\/investors\/[^/]+\/history$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    if (path.endsWith("/kr-market/source-health")) {
      await fulfillJson(route, null);
      return;
    }

    if (path.endsWith("/kr-market/watchlists/readiness")) {
      await fulfillJson(
        route,
        emptyKrWatchlistReadiness(
          url.searchParams.has("group_id") ? Number(url.searchParams.get("group_id")) : null
        )
      );
      return;
    }

    if (path.endsWith("/settings/market-data-subscriptions")) {
      await fulfillJson(route, {
        kind: "market_data_subscriptions",
        version: "v1",
        source: "playwright.fixture",
        items: [],
      });
      return;
    }

    if (path.endsWith("/crypto-market/watchlists/tree")) {
      await fulfillJson(route, seededCryptoWatchlistTree());
      return;
    }

    if (path.endsWith("/crypto-market/watchlists/items")) {
      await fulfillJson(route, seededCryptoWatchlistItems());
      return;
    }

    if (path.endsWith("/crypto-market/workspace-summary")) {
      await fulfillJson(route, seededCryptoWorkspaceSummary());
      return;
    }

    if (path.endsWith("/crypto-market/provider-contract")) {
      await fulfillJson(route, {
        kind: "crypto_provider_contract",
        market: "crypto",
        assets: [],
        instruments: [],
        ohlcv_intervals: {},
        providers: {},
      });
      return;
    }

    if (
      path.endsWith("/crypto-market/realtime/status") ||
      path.endsWith("/crypto-market/auto-refresh/status")
    ) {
      await fulfillJson(route, null);
      return;
    }

    if (path.endsWith("/crypto-market/source-health")) {
      await fulfillJson(route, {
        generated_at: "2026-06-15T09:30:00+08:00",
        summary: {
          entry_count: 0,
          ok_count: 0,
          empty_count: 0,
          stale_count: 0,
          error_count: 0,
          disabled_count: 0,
        },
        entries: [],
      });
      return;
    }

    if (path.includes("/crypto-market/")) {
      await fulfillJson(route, []);
      return;
    }

    if (path.endsWith("/resource-market/provider-contract")) {
      await fulfillJson(route, {
        kind: "resource_provider_contract",
        market: "resource",
        execution_enabled: false,
        ai_execution_enabled: false,
        trade_candidate_symbols: [],
        notes: [],
        root_folders: [],
        providers: {},
        instruments: [],
      });
      return;
    }

    if (path.endsWith("/resource-market/source-health")) {
      await fulfillJson(route, {
        kind: "resource_source_health",
        generated_at: "2026-06-15T09:30:00+08:00",
        filters: {},
        summary: {
          entry_count: 0,
          ok_count: 0,
          empty_count: 0,
          stale_count: 0,
          delayed_count: 0,
          error_count: 0,
          disabled_count: 0,
        },
        entries: [],
      });
      return;
    }

    if (path.includes("/resource-market/")) {
      await fulfillJson(route, []);
      return;
    }

    if (path.includes("/market/indicators/")) {
      await fulfillJson(route, []);
      return;
    }

    if (path.includes("/market/quote-depth/")) {
      await fulfillJson(route, {
        stock_id: "2330",
        stock_name: "台積電",
        market: "TWSE",
        provider: "twse_mis",
        source: "twse_mis_quote_depth",
        source_url: "https://mis.twse.com.tw/stock/api/getStockInfo.jsp",
        exchange_channel: "tse_2330.tw",
        session_phase: "regular_live",
        phase_label: "即時",
        trade_date: "2026-06-15",
        quote_time: "2026-06-15T09:30:00+08:00",
        fetched_at: "2026-06-15T09:30:01+08:00",
        last_price: 861,
        previous_close: 849,
        open_price: 852,
        high_price: 864,
        low_price: 850,
        change: 12,
        change_pct: 1.41,
        total_volume_lots: 1280,
        best_bid_price: 860,
        best_bid_size_lots: 12,
        best_ask_price: 861,
        best_ask_size_lots: 8,
        bid_total_size_lots: 63,
        ask_total_size_lots: 54,
        spread: 1,
        spread_pct: 0.12,
        bid_levels: [
          { level: 1, price: 860, size_lots: 12 },
          { level: 2, price: 859, size_lots: 14 },
          { level: 3, price: 858, size_lots: 10 },
          { level: 4, price: 857, size_lots: 16 },
          { level: 5, price: 856, size_lots: 11 },
        ],
        ask_levels: [
          { level: 1, price: 861, size_lots: 8 },
          { level: 2, price: 862, size_lots: 9 },
          { level: 3, price: 863, size_lots: 15 },
          { level: 4, price: 864, size_lots: 13 },
          { level: 5, price: 865, size_lots: 9 },
        ],
        depth_available: true,
        freshness: {
          status: "live",
          is_live: true,
          is_stale: false,
          age_seconds: 1,
          expected_trade_date: "2026-06-15",
          message: "五檔即時更新中。",
          source_error: null,
        },
      });
      return;
    }

    if (path.includes("/market/technical/")) {
      await fulfillJson(route, {
        stock_id: "2330",
        timeframe: "daily",
        as_of: "2026-06-15",
        summary: "測試技術摘要",
        signals: [],
      });
      return;
    }

    if (
      /\/(?:us-market|jp-market|kr-market)\/watchlists\/groups\/\d+\/radar$/.test(path) ||
      /\/(?:wl|watchlists)\/groups\/\d+\/radar$/.test(path)
    ) {
      const market = path.includes("/us-market/")
        ? "us"
        : path.includes("/jp-market/")
          ? "jp"
          : path.includes("/kr-market/")
            ? "kr"
            : "tw";
      const groupId = Number(path.match(/groups\/(\d+)\/radar/)?.[1] ?? 0);
      radarRequestCounts[market] += 1;
      const customResponse = await options.radarResponder?.({
        market,
        groupId,
        requestNumber: radarRequestCounts[market],
        url,
      });

      if (customResponse) {
        if (customResponse.delayMs) {
          await new Promise((resolve) => setTimeout(resolve, customResponse.delayMs));
        }
        await route.fulfill({
          status: customResponse.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(customResponse.body),
        });
        return;
      }

      await fulfillJson(
        route,
        emptyRadarResponse(path, url.searchParams.get("mode") ?? "action")
      );
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/radar\/v2\/outcomes\/latest$/.test(path)) {
      const snapshotDate = url.searchParams.get("snapshot_date");
      await fulfillJson(
        route,
        (snapshotDate
          ? options.taiwanRadarV2OutcomeSnapshots?.[snapshotDate]
          : options.taiwanRadarV2OutcomeLatest) ?? noRadarV2OutcomeSummary()
      );
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/radar\/v2\/outcomes\/history$/.test(path)) {
      await fulfillJson(route, options.taiwanRadarV2OutcomeHistory ?? []);
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/radar\/outcomes(?:\/|$)/.test(path)) {
      throw new Error(`Unexpected frozen Radar v1 request: ${route.request().method()} ${path}`);
    }

    if (/\/(?:us-market|jp-market|kr-market)\/watchlists\/ranking$/.test(path)) {
      const market = path.includes("/us-market/")
        ? "us"
        : path.includes("/jp-market/")
          ? "jp"
          : "kr";
      regionalRankingRequestCounts[market] += 1;
      const customResponse = await options.regionalRankingResponder?.({
        market,
        requestNumber: regionalRankingRequestCounts[market],
        url,
      });

      if (customResponse) {
        if (customResponse.delayMs) {
          await new Promise((resolve) => setTimeout(resolve, customResponse.delayMs));
        }
        await route.fulfill({
          status: customResponse.status ?? 200,
          contentType: "application/json",
          body: JSON.stringify(customResponse.body),
        });
        return;
      }

      await fulfillJson(
        route,
        market === "us" && usRankingRows.length > 0
          ? seededUsRankingResponse(url, usRankingRows)
          : market === "jp" && jpRankingRows.length > 0
            ? seededJpRankingResponse(url, jpRankingRows)
            : market === "kr" && krRankingRows.length > 0
              ? seededKrRankingResponse(url, krRankingRows)
              : emptyRankingResponse(url)
      );
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/rankings\/latest-batch$/.test(path)) {
      await fulfillJson(
        route,
        taiwanRankingRows.length > 0
          ? seededTaiwanRankingBatch(url, taiwanRankingRows)
          : emptyTaiwanRankingBatch(url)
      );
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/rankings\/latest$/.test(path)) {
      await fulfillJson(route, emptyTaiwanRankingResponse(url));
      return;
    }

    const taiwanSelectionRefreshMatch = path.match(/\/market\/selection-refresh\/([^/]+)$/);
    if (taiwanSelectionRefreshMatch) {
      await fulfillJson(route, completedRefreshJob());
      return;
    }

    const taiwanChipCoverageMatch = path.match(/\/market\/chips\/([^/]+)\/coverage$/);
    if (taiwanChipCoverageMatch) {
      const stockId = decodeURIComponent(taiwanChipCoverageMatch[1]);
      await fulfillJson(route, {
        stock_id: stockId,
        shareholding_latest_date: null,
        shareholding_week_count: 0,
        shareholding_row_count: 0,
        margin_latest_trade_date: null,
        margin_row_count: 0,
        has_shareholding: false,
        has_margin: false,
      });
      return;
    }

    if (/\/market\/shareholding\/[^/]+\/history$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    if (/\/market\/(?:margin|institutional|revenue|financials)\/[^/]+\/history$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    const taiwanBrokerBranchMatch = path.match(
      /\/market\/broker-branches\/([^/]+)\/daily$/
    );
    if (taiwanBrokerBranchMatch) {
      const stockId = decodeURIComponent(taiwanBrokerBranchMatch[1]);
      const days = Number(url.searchParams.get("days") ?? "1");
      await fulfillJson(route, brokerBranchSummaryResponse(stockId, days));
      return;
    }

    if (path.includes("/market/market-chips/refresh")) {
      await fulfillJson(route, completedRefreshJob());
      return;
    }

    if (path.includes("/market/market-chips/latest")) {
      await fulfillJson(route, {
        id: 1,
        index_id: "TAIEX",
        market: "TWSE",
        trade_date: "2026-06-15",
        close_value: 861,
        price_change: 12,
        price_change_pct: 1.4,
        trade_value: null,
        foreign_futures_net_oi: null,
        foreign_futures_net_oi_change: null,
        retail_futures_net_oi: null,
        retail_futures_net_oi_change: null,
        total_institutional_net_value: null,
        foreign_investor_net_value: null,
        investment_trust_net_value: null,
        dealer_net_value: null,
        dealer_self_net_value: null,
        dealer_hedge_net_value: null,
        government_bank_net_value: null,
        margin_balance_change_value: null,
        margin_balance_change_shares: null,
        short_balance_change_shares: null,
        source_grade: "fixture",
        source_details: null,
        created_at: "2026-06-15T09:30:00+08:00",
        updated_at: "2026-06-15T09:30:00+08:00",
      });
      return;
    }

    if (path.includes("/chart-drawings/")) {
      await fulfillJson(route, {
        id: 1,
        market: "TW",
        symbol: "2330",
        timeframe: "daily",
        label: null,
        time_mode: "date",
        selected_drawing_id: null,
        drawing_count: 0,
        drawings: [],
        summary: null,
        source: "playwright",
        created_at: "2026-06-15T09:30:00+08:00",
        updated_at: "2026-06-15T09:30:00+08:00",
      });
      return;
    }

    if (path.includes("/portfolio/holdings")) {
      await fulfillJson(route, portfolioHoldingsPayload);
      return;
    }

    if (path.includes("/settings/refresh-execution")) {
      const policy = {
        observed_stock_refresh_interval_seconds: 3600,
        subresource_refresh_interval_seconds: 3600,
        market_refresh_interval_seconds: 3600,
      };
      await fulfillJson(route, {
        kind: "refresh_execution_settings",
        version: "refresh_execution_settings.v1",
        source: "playwright.fixture",
        markets: {
          tw: policy,
          us: policy,
          jp: policy,
          kr: policy,
        },
      });
      return;
    }

    if (path.includes("/wl/tree")) {
      await fulfillJson(route, taiwanWatchlistTree);
      return;
    }

    if (path.includes("/wl/items")) {
      await fulfillJson(route, taiwanWatchlistItems);
      return;
    }

    if (path.includes("/us-market/watchlists/tree")) {
      await fulfillJson(route, usWatchlistTree);
      return;
    }

    if (path.includes("/us-market/watchlists/items")) {
      await fulfillJson(route, usWatchlistItems);
      return;
    }

    const usMarketResearchMatch = path.match(/\/us-market\/research\/([^/]+)$/);
    if (usMarketResearchMatch) {
      await fulfillJson(
        route,
        usMarketResearchResponse(decodeURIComponent(usMarketResearchMatch[1]))
      );
      return;
    }

    if (path.includes("/jp-market/watchlists/tree")) {
      await fulfillJson(route, jpWatchlistTree);
      return;
    }

    if (path.includes("/jp-market/watchlists/items")) {
      await fulfillJson(route, jpWatchlistItems);
      return;
    }

    if (path.includes("/kr-market/watchlists/tree")) {
      await fulfillJson(route, krWatchlistTree);
      return;
    }

    if (path.includes("/kr-market/watchlists/items")) {
      await fulfillJson(route, krWatchlistItems);
      return;
    }

    if (/\/wl\/groups\/\d+\/refresh-latest$/.test(path)) {
      await fulfillJson(route, completedRefreshJob());
      return;
    }

    if (/\/jobs\/\d+$/.test(path)) {
      await fulfillJson(route, completedRefreshJob());
      return;
    }

    if (path.endsWith("/jobs")) {
      await fulfillJson(route, []);
      return;
    }

    throw new Error(`Unhandled mocked OMI API route: ${route.request().method()} ${path}`);
  });
}

test.describe("OMI dashboard smoke", () => {
  test("backend mutation failure remains visible after redirect", async ({ page }) => {
    await mockOmiApi(page, {
      apiResponder: ({ path }) =>
        path.endsWith("/system/readyz")
          ? { status: 404, body: { detail: "Not Found" } }
          : null,
    });
    await page.goto("/?omi_error=timeout", { waitUntil: "domcontentloaded" });

    const banner = page.getByTestId("backend-connection-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("操作未完成");
    await expect(banner.getByRole("button", { name: "重新整理" })).toBeVisible();
    await expect
      .poll(() => new URL(page.url()).searchParams.has("omi_error"))
      .toBe(false);
  });

  test("OMI dock streams a mocked answer", async ({ page }) => {
    await mockOmiApi(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "Market Dashboard" })).toBeVisible();
    await expect(page.getByRole("button", { name: "開啟 OMI 即時問答" })).toBeVisible();
    await page.getByRole("button", { name: "開啟 OMI 即時問答" }).click();
    await page.getByPlaceholder("輸入問題...").fill("現在可以買嗎？");
    await page.getByRole("button", { name: "送出" }).click();

    await expect(page.getByText("測試回答：目前偏多但等待確認")).toBeVisible();
    await expect(page.getByRole("button", { name: "查看 OMI 處理訊號" })).toContainText("完成");
  });

  test("OMI context payload follows Taiwan and Korea index selection", async ({ page }) => {
    const omiAskRequests: unknown[] = [];
    await mockOmiApi(page, {
      omiAskRequests,
      krWatchlistTree: seededKrWatchlistTree(),
      krWatchlistItems: seededKrWatchlistItems(),
      krRankingRows: seededKrRankingRows(),
    });

    async function askCurrentContext(question: string) {
      const composer = page.getByPlaceholder("輸入問題...");
      await expect(async () => {
        if (await composer.isVisible()) return;
        await page.getByRole("button", { name: "開啟 OMI 即時問答" }).click();
        await expect(composer).toBeVisible({ timeout: 1_000 });
      }).toPass({ timeout: 5_000 });
      await expect(composer).toBeVisible();
      await composer.fill(question);
      await page.getByRole("button", { name: "送出" }).click();
      await expect(page.getByText("測試回答：目前偏多但等待確認")).toBeVisible();
    }

    await page.goto("/?stock_id=TAIEX", { waitUntil: "domcontentloaded" });
    await askCurrentContext("台股指數目前狀態？");

    await page.goto("/?market=kr&kr_symbol=KOSDAQ", {
      waitUntil: "domcontentloaded",
    });
    await askCurrentContext("韓股指數目前狀態？");

    expect(omiAskRequests).toHaveLength(2);
    expect(omiAskRequests[0]).toMatchObject({
      contract_version: "omi.decision.v4",
      output: "decision_with_evidence",
      caller_profile: "frontend_readonly",
      target: {
        type: "tw_index",
        id: "TAIEX",
        market: "TW",
      },
      conversation_context: {
        ui_context: {
          market: "tw",
          selected_index_id: "TAIEX",
        },
      },
    });
    expect(omiAskRequests[1]).toMatchObject({
      contract_version: "omi.decision.v4",
      output: "decision_with_evidence",
      caller_profile: "frontend_readonly",
      target: {
        type: "kr_index",
        id: "KOSDAQ",
        market: "KR",
      },
      conversation_context: {
        ui_context: {
          market: "kr",
          selected_symbol: "KOSDAQ",
        },
      },
    });
  });

  test("Taiwan market tape ignores an older summary after manual reload", async ({ page }) => {
    let resolveFirstSummaryStarted!: () => void;
    let releaseFirstSummary!: () => void;
    const firstSummaryStarted = new Promise<void>((resolve) => {
      resolveFirstSummaryStarted = resolve;
    });
    const firstSummaryResponse = new Promise<{
      body: unknown;
      status: number;
    }>((resolve) => {
      releaseFirstSummary = () =>
        resolve({ body: marketIndexSummaryResponse(1_111), status: 200 });
    });

    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      marketTapeResponder: ({ market, kind, requestNumber }) => {
        if (market !== "tw" || kind !== "summary") return null;
        if (requestNumber === 1) {
          resolveFirstSummaryStarted();
          return firstSummaryResponse;
        }
        if (requestNumber >= 2) {
          return { body: marketIndexSummaryResponse(2_222), status: 200 };
        }
        return null;
      },
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await firstSummaryStarted;

    await page.locator('[data-watchlist-group-id="7"]').click();
    const dashboardReload = page.getByTestId("watchlist-ranking-reload");
    await expect(dashboardReload).toBeEnabled();
    await dashboardReload.click();

    const tape = page.getByTestId("market-tape-tw");
    await expect(tape).toHaveAttribute("data-load-state", "success");
    await expect(tape).toContainText("2,222");

    releaseFirstSummary();
    await page.waitForTimeout(100);
    await expect(tape).toHaveAttribute("data-load-state", "success");
    await expect(tape).toContainText("2,222");
    await expect(tape).not.toContainText("1,111");
  });

  test("US market tape preserves request params and ignores a stale context failure", async ({
    page,
  }) => {
    const tapeCalls: Array<{
      market: string;
      kind: string;
      target: string;
      requestNumber: number;
      url: URL;
    }> = [];
    let resolveStaleRequestStarted!: () => void;
    let releaseStaleRequest!: () => void;
    const staleRequestStarted = new Promise<void>((resolve) => {
      resolveStaleRequestStarted = resolve;
    });
    const staleResponse = new Promise<{
      body: unknown;
      status: number;
    }>((resolve) => {
      releaseStaleRequest = () =>
        resolve({ body: { detail: "stale context failure" }, status: 500 });
    });

    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      usRankingRows: seededUsRankingRows(),
      marketTapeResponder: (context) => {
        tapeCalls.push(context);
        if (
          context.market === "us" &&
          context.kind === "ohlc" &&
          context.target !== "^GSPC" &&
          context.target !== "^DJI" &&
          context.requestNumber === 1
        ) {
          resolveStaleRequestStarted();
          return staleResponse;
        }
        return null;
      },
    });
    await page.goto("/?market=us&group_id=17&symbol=AAPL", {
      waitUntil: "domcontentloaded",
    });
    await staleRequestStarted;

    await page.getByText("美股指數", { exact: true }).click();
    await page.getByRole("button", { name: /DJI 道瓊指數/ }).click();
    expect(new URL(page.url()).searchParams.get("symbol")).toBe("^DJI");

    const tape = page.getByTestId("market-tape-us");
    await expect(tape).toHaveAttribute("data-load-state", "success");
    await expect(tape.getByText("道瓊指數", { exact: true })).toBeVisible();

    releaseStaleRequest();
    await page.waitForTimeout(100);
    await expect(tape).toHaveAttribute("data-load-state", "success");
    await expect(tape.getByText("道瓊指數", { exact: true })).toBeVisible();

    const djiOhlc = tapeCalls.find(
      (call) => call.market === "us" && call.kind === "ohlc" && call.target === "^DJI"
    );
    expect(djiOhlc).toBeDefined();
    expect(djiOhlc?.url.searchParams.get("timeframe")).toBe("daily");
    expect(djiOhlc?.url.searchParams.get("bars")).toBe("60");
    expect(djiOhlc?.url.searchParams.get("ensure_history")).toBe("false");
    expect(djiOhlc?.url.searchParams.get("outputsize")).toBe("compact");
    expect(djiOhlc?.url.searchParams.get("provider")).toBeNull();
    expect(
      tapeCalls.some(
        (call) => call.market === "us" && call.kind === "intraday" && call.target === "^DJI"
      )
    ).toBe(true);
  });

  test("US market tape reloads after leaving and returning to the market", async ({ page }) => {
    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      marketTapeResponder: ({ market, kind, target, requestNumber }) => {
        if (
          market === "us" &&
          kind === "ohlc" &&
          target === "^GSPC" &&
          requestNumber === 1
        ) {
          return { body: { detail: "initial market tape failure" }, status: 500 };
        }
        return null;
      },
    });
    await page.goto("/?market=us", { waitUntil: "domcontentloaded" });

    const tape = page.getByTestId("market-tape-us");
    await expect(tape).toHaveAttribute("data-load-state", "error");

    await page.getByRole("link", { name: "台股", exact: true }).click();
    await page.getByRole("link", { name: "美股", exact: true }).click();

    await expect(tape).toHaveAttribute("data-load-state", "success");
    await expect(tape.getByText("S&P 500", { exact: true })).toBeVisible();
  });

  test("US stock detail routes intraday failures into the update status center", async ({
    page,
  }) => {
    const timeoutDetail = "fixture intraday timeout";
    let resolveIntradayFailureObserved: () => void = () => undefined;
    const intradayFailureObserved = new Promise<void>((resolve) => {
      resolveIntradayFailureObserved = resolve;
    });

    await page.clock.setFixedTime(new Date("2026-07-14T15:00:00Z"));
    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      apiResponder: ({ path }) => {
        if (path.endsWith("/us-market/intraday/AAPL")) {
          resolveIntradayFailureObserved();
          return { body: { detail: timeoutDetail }, status: 504 };
        }
        return null;
      },
    });
    await page.goto("/?market=us&group_id=17&symbol=AAPL", {
      waitUntil: "domcontentloaded",
    });

    const detailPanel = page.getByTestId("us-stock-kline-panel");
    await expect(detailPanel).toBeVisible();
    const todayTimeframe = detailPanel.getByRole("button", { name: "今日", exact: true });
    await expect(async () => {
      await todayTimeframe.click();
      await expect(todayTimeframe).toHaveClass(/omi-timeframe-tab-active/, {
        timeout: 750,
      });
    }).toPass({ timeout: 5_000 });
    await intradayFailureObserved;

    const sidebar = page.getByRole("complementary").first();
    const statusToggle = sidebar.getByRole("button", { name: /更新狀態/ });
    await expect(statusToggle.locator(".omi-job-status-pill-attention")).toContainText(
      /補失敗 [1-9]\d*/,
      { timeout: 10_000 }
    );
    await expect(page.getByText(new RegExp(timeoutDetail))).toHaveCount(0);

    await statusToggle.click();
    await expect(sidebar.getByText(new RegExp(timeoutDetail))).toBeVisible();
    await expect(page.getByRole("heading", { name: /^AAPL(?:\s|$)/ })).toBeVisible();
  });

  test("US professional indicator menu uses the shared layout and parameter controls", async ({
    page,
  }) => {
    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      usRankingRows: seededUsRankingRows(),
    });
    await page.goto("/?market=us&group_id=17&symbol=AAPL", {
      waitUntil: "domcontentloaded",
    });

    const overviewPanel = page.getByTestId("us-stock-kline-panel");
    await expect(overviewPanel).toBeVisible();
    await overviewPanel.getByRole("button", { name: "放大", exact: true }).click();
    await expect(page.getByTestId("professional-chart-panel")).toBeVisible();

    await page.getByTestId("chart-indicator-menu-toggle").click();
    const menu = page.getByTestId("technical-indicator-menu");
    await expect(menu).toBeVisible();
    await expect(menu.getByText("快速組合", { exact: true })).toHaveCount(1);
    await expect(menu.getByText("參數", { exact: true })).toHaveCount(1);
    await expect(menu.locator('input[type="number"]')).not.toHaveCount(0);
    await expect(menu.locator('[data-indicator-option="ma"]')).toBeChecked();
  });

  test("Taiwan index professional chart shell renders", async ({ page }) => {
    await mockOmiApi(page);
    await page.goto("/?market=tw&stock_id=TAIEX", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "TAIEX 加權指數" })).toBeVisible();
    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-stock-id",
      "TAIEX"
    );
    const todayTimeframe = page.getByTestId("timeframe-today");
    await expect(async () => {
      await todayTimeframe.click();
      await expect(todayTimeframe).toHaveClass(/omi-timeframe-tab-active/, {
        timeout: 750,
      });
    }).toPass({ timeout: 5_000 });
    const todaySurface = page.getByTestId("today-intraday-surface");
    const todayChart = todaySurface.getByTestId("intraday-trend-chart");
    await expect(todaySurface).toBeVisible();
    await expect(todayChart).toHaveAttribute("data-rendered-point-count", "2");
    await expect(todayChart).toHaveAttribute("data-volume-rendered", "false");
    await expect(page.getByTestId("today-header-price")).toContainText("861");
    expect(await todayChart.locator("svg *").count()).toBeLessThan(500);
    await page.getByTestId("chart-indicator-menu-toggle").click();
    const todayIndicatorMenu = page.getByTestId("intraday-indicator-menu");
    await expect(todayIndicatorMenu.locator('[data-indicator-option="volume"]')).toHaveCount(0);
    await expect(todayIndicatorMenu.locator('[data-indicator-option="vwap"]')).toHaveCount(0);
    await page.getByTestId("chart-indicator-menu-toggle").click();
    await page.getByTestId("timeframe-daily").click();
    await expect(page.getByRole("button", { name: "放大" }).first()).toBeEnabled();
    await page.getByRole("button", { name: "放大" }).first().click();

    await expect(page.getByRole("button", { name: "總覽" })).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible();
  });

  test("Taiwan stock overnight report renders ADR TWD parity", async ({ page }) => {
    await mockOmiApi(page, {
      apiResponder: ({ path }) =>
        path.endsWith("/market/overnight-impact/2330")
          ? {
              body: {
                kind: "us_overnight_tw_impact",
                stock_id: "2330",
                stock_name: "台積電",
                as_of: "2026-06-05",
                generated_at: "2026-06-08T12:00:00Z",
                stance: "risk_on",
                title: "Fixture overnight report",
                summary: "Fixture overnight summary",
                score: 20,
                weighted_change_pct: 1,
                confidence: "high",
                tw_mapping: {
                  stock_id: "2330",
                  stock_name: "台積電",
                  market: "TWSE",
                  industry: "24",
                  category: null,
                  profiles: ["semiconductor", "technology"],
                  reason: "fixture",
                },
                adr_parity: {
                  kind: "tw_adr_parity",
                  status: "ready",
                  is_current: true,
                  stock_id: "2330",
                  stock_name: "台積電",
                  mapping: {
                    stock_id: "2330",
                    stock_name: "台積電",
                    adr_symbol: "TSM",
                    adr_name: "TSMC ADR",
                    adr_exchange: "NYSE",
                    local_shares_per_adr: 5,
                    source_label: "TSMC 2025 Form 20-F",
                    source_url: "https://www.sec.gov/example",
                    verified_on: "2026-07-22",
                  },
                  mapping_resolution: {
                    selected_source: "registry",
                    registry_status: "ready",
                    shadow_status: "match",
                    shadow_differences: [],
                    relation_id: 42,
                    relation_version: 1,
                    relation_valid_from: "2026-07-22",
                    relation_valid_to: null,
                    relation_verified_at: "2026-07-22T00:00:00Z",
                    evidence_ids: [84],
                    registry_schema_version: "cross_market.relation_registry.v1",
                    warnings: [],
                    limitations: [],
                  },
                  formula: "adr_close_usd * usd_twd / local_shares_per_adr",
                  adr_close_usd: 200,
                  adr_trade_date: "2026-06-05",
                  adr_provider: "yahoo_chart",
                  expected_adr_trade_date: "2026-06-05",
                  usd_twd: 32.5,
                  fx_source_symbol: "USD-TWD",
                  fx_provider: "yahoo_chart",
                  fx_as_of: "2026-06-08T08:00:00Z",
                  fx_age_seconds: 14_400,
                  fx_freshness: {
                    purpose: "adr_alignment",
                    status: "current",
                    usable: true,
                    session_status: "open",
                    expected_data_date: "2026-06-05",
                    actual_data_date: "2026-06-05",
                    refresh_eligible: false,
                    reason_codes: ["fx_matches_adr_trade_date"],
                  },
                  tw_reference_price_twd: 1_000,
                  tw_reference_trade_date: "2026-06-05",
                  target_tw_trade_date: "2026-06-08",
                  implied_tw_price_twd: 1_300,
                  implied_gap_pct: 30,
                  parity_adr_price_usd: 153.8462,
                  tw_comparison_price_twd: 1_250,
                  tw_comparison_trade_date: "2026-06-08",
                  tw_comparison_as_of: null,
                  tw_comparison_source: "market_daily_price",
                  tw_session_phase: "daily_close",
                  comparison_mode: "target_session_review",
                  remaining_gap_pct: 4,
                  missing: [],
                  warnings: [],
                  source_refs: [],
                  freshness: {},
                },
                cross_market_context: {
                  kind: "cross_market_target_context",
                  schema_version: "cross_market.context.v1",
                  target: {
                    market: "TW",
                    instrument_type: "stock",
                    canonical_symbol: "TW:2330",
                    provider_symbol: "2330",
                    exchange: "TWSE",
                    currency: "TWD",
                  },
                  status: "ready",
                  decision_usable: true,
                  as_of: "2026-06-05",
                  decision_at: "2026-06-08T12:00:00Z",
                  methodology_version: "cross_market.relation_context.v2",
                  relation_snapshot_version: "relation_registry:42:v1",
                  snapshot_id: "cmctx:fixture",
                  summary: {
                    stance: "supportive",
                    score: 30,
                    confidence: "high",
                    title: "ADR 隱含價高於台股對齊基準",
                    reason_codes: ["direct_adr_parity"],
                  },
                  direct_equivalents: [],
                  signals: [
                    {
                      signal_id: "adr_parity:TW:2330:42:1",
                      relation_id: 42,
                      relation_version: 1,
                      source: {
                        market: "US",
                        instrument_type: "adr",
                        canonical_symbol: "US:TSM",
                        provider_symbol: "TSM",
                        exchange: "NYSE",
                        currency: "USD",
                      },
                      target: {
                        market: "TW",
                        instrument_type: "stock",
                        canonical_symbol: "TW:2330",
                        provider_symbol: "2330",
                        exchange: "TWSE",
                        currency: "TWD",
                      },
                      bucket: "direct_equivalent",
                      relation_type: "same_equity_dr",
                      calculation: {
                        kind: "adr_implied_gap",
                        implied_gap_pct: 30,
                      },
                      direction: "supportive",
                      configured_weight: 1,
                      quality_multiplier: 1,
                      effective_weight: 1,
                      normalized_weight: 1,
                      contribution: 30,
                      status: "ready",
                      decision_usable: true,
                      confidence_tier: "A",
                      freshness: {},
                      evidence_refs: ["cross_market_relation_evidence:84"],
                      source_refs: [],
                      warnings: [],
                      limitations: [
                        "latest_local_cache_projection_not_materialized_snapshot",
                      ],
                      excluded_reason: null,
                    },
                  ],
                  bucket_scores: { direct_equivalent: 30 },
                  coverage: {
                    configured_signal_count: 1,
                    available_signal_count: 1,
                    decision_usable_signal_count: 1,
                    configured_weight: 1,
                    available_weight: 1,
                    decision_usable_weight: 1,
                    coverage_ratio: 1,
                    excluded_by_reason: {},
                  },
                  freshness: { read_path_provider_refresh: false },
                  missing: [],
                  warnings: [],
                  limitations: [
                    "latest_local_cache_projection_not_materialized_snapshot",
                  ],
                  source_refs: [],
                  evidence_passport: {
                    relation_ids: [42],
                    evidence_ids: [84],
                    mapping_source: "registry",
                  },
                },
                fx_flow_context: {
                  kind: "tw_fx_foreign_flow_context",
                  status: "ready",
                  is_current: true,
                  stock_id: "2330",
                  signal: "confirmed_outflow",
                  signal_horizon_days: 5,
                  causality: "confirmation_not_causation",
                  fx: {
                    status: "ready",
                    source_symbol: "USD-TWD",
                    provider: "yahoo_chart",
                    usd_twd: 32.375,
                    data_date: "2026-06-08",
                    as_of: "2026-06-08T08:00:00Z",
                    age_seconds: 14_400,
                    history_points: 21,
                    usd_twd_change_1d_pct: 0.31,
                    usd_twd_change_5d_pct: 0.76,
                    usd_twd_change_20d_pct: 2.12,
                    twd_change_1d_pct: -0.31,
                    twd_change_5d_pct: -0.75,
                    twd_change_20d_pct: -2.08,
                    regime: "twd_weakening",
                  },
                  market_foreign: {
                    scope: "market",
                    status: "ready",
                    state: "outflow",
                    state_basis_days: 5,
                    trade_date: "2026-06-08",
                    expected_trade_date: "2026-06-08",
                    windows: [
                      {
                        days: 1,
                        available_days: 1,
                        net_value_twd: -10_000_000_000,
                        turnover_twd: 1_000_000_000_000,
                        turnover_ratio_pct: -1,
                        net_shares: null,
                      },
                      {
                        days: 5,
                        available_days: 5,
                        net_value_twd: -50_000_000_000,
                        turnover_twd: 5_000_000_000_000,
                        turnover_ratio_pct: -1,
                        net_shares: null,
                      },
                      {
                        days: 20,
                        available_days: 20,
                        net_value_twd: -200_000_000_000,
                        turnover_twd: 20_000_000_000_000,
                        turnover_ratio_pct: -1,
                        net_shares: null,
                      },
                    ],
                  },
                  stock_foreign: {
                    scope: "stock",
                    status: "ready",
                    state: "outflow",
                    state_basis_days: 5,
                    trade_date: "2026-06-08",
                    expected_trade_date: "2026-06-08",
                    windows: [
                      {
                        days: 1,
                        available_days: 1,
                        net_value_twd: null,
                        turnover_twd: null,
                        turnover_ratio_pct: null,
                        net_shares: -1_100_000,
                      },
                      {
                        days: 5,
                        available_days: 5,
                        net_value_twd: null,
                        turnover_twd: null,
                        turnover_ratio_pct: null,
                        net_shares: -5_500_000,
                      },
                      {
                        days: 20,
                        available_days: 20,
                        net_value_twd: null,
                        turnover_twd: null,
                        turnover_ratio_pct: null,
                        net_shares: -22_000_000,
                      },
                    ],
                  },
                  missing: [],
                  warnings: [],
                  source_refs: [],
                  freshness: {},
                },
                factors: [],
                baskets: [],
                missing: [],
                warnings: [],
                source_refs: [],
                freshness: {},
                evidence_passport: {},
              },
            }
          : null,
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    const crossMarket = page.getByTestId("cross-market-context-strip");
    const crossMarketToggle = page.getByTestId("cross-market-context-toggle");
    const crossMarketDetails = page.getByTestId("cross-market-context-details");
    const overnightDisclosure = page.getByTestId("tw-overnight-impact-disclosure");
    await expect(overnightDisclosure).toContainText("Overnight · 市場背景");
    await expect(overnightDisclosure).not.toHaveAttribute("open", "");
    await expect(crossMarket).toBeVisible();
    await expect(
      crossMarket.evaluate(
        (node) =>
          node.closest('[data-testid="tw-overnight-impact-disclosure"]') === null
      )
    ).resolves.toBe(true);
    await expect(crossMarket).not.toHaveAttribute("open", "");
    await expect(crossMarketDetails).toBeHidden();
    await expect(crossMarketToggle).toContainText("個股跨市場映射");
    await expect(crossMarketToggle).toContainText("TSM → 2330 · 直接等價");
    await expect(crossMarketToggle).toContainText("外部相對支撐");
    await expect(crossMarketToggle).toContainText("映射分數");
    await expect(crossMarketToggle).toContainText("+30.00%");
    await expect(crossMarketToggle).toContainText("可用");

    await crossMarketToggle.click();

    await expect(crossMarket).toHaveAttribute("open", "");
    await expect(crossMarketDetails).toBeVisible();
    await expect(crossMarket).toContainText("TSM · 直接等價");
    await expect(crossMarket).toContainText("可用 1/1");
    await expect(crossMarket).toContainText("已審核 Registry");
    await expect(crossMarket).toContainText("relation_registry:42:v1");
    await expect(crossMarket).toContainText("尚非可回放的 point-in-time snapshot");

    const parity = page.getByTestId("adr-parity-strip");
    const parityToggle = page.getByTestId("adr-parity-toggle");
    const parityDetails = page.getByTestId("adr-parity-details");
    await expect(parity).toBeVisible();
    await expect(parity).not.toHaveAttribute("open", "");
    await expect(parityDetails).toBeHidden();
    await expect(parity).toContainText("ADR 台幣對照");
    await expect(parityToggle).toContainText("NT$1,300");
    await expect(parityToggle).toContainText("高於基準 +30.00%");

    await parityToggle.click();

    await expect(parity).toHaveAttribute("open", "");
    await expect(parityDetails).toBeVisible();
    await expect(parity).toContainText("TSM US$200");
    await expect(parity).toContainText("USD/TWD 32.50");
    await expect(parity).toContainText("高於台股基準 +30.00%");
    await expect(parity).toContainText("匯率 2026-06-05");
    await expect(parity).toContainText("較台股對照仍高 +4.00%");

    const fxFlow = page.getByTestId("fx-flow-context-strip");
    const fxFlowToggle = page.getByTestId("fx-flow-context-toggle");
    const fxFlowDetails = page.getByTestId("fx-flow-context-details");
    await expect(fxFlow).toBeHidden();
    await overnightDisclosure.locator(":scope > summary").click();
    await expect(overnightDisclosure).toHaveAttribute("open", "");
    await expect(fxFlow).toBeVisible();
    await expect(fxFlow).not.toHaveAttribute("open", "");
    await expect(fxFlowDetails).toBeHidden();
    await expect(fxFlowToggle).toContainText("匯率與外資");
    await expect(fxFlowToggle).toContainText("USD/TWD 32.375");
    await expect(fxFlowToggle).toContainText("台幣偏弱 -0.75%");
    await expect(fxFlowToggle).toContainText("資金流出確認");

    await fxFlowToggle.click();

    await expect(fxFlow).toHaveAttribute("open", "");
    await expect(fxFlowDetails).toBeVisible();
    await expect(fxFlow).toContainText("1日 -0.31% · 5日 -0.75% · 20日 -2.08%");
    await expect(fxFlow).toContainText("5日 -500億");
    await expect(fxFlow).toContainText("5日 -5,500張");
    await expect(fxFlow).toContainText("不代表台幣升貶單向造成外資買賣");
  });

  test("Taiwan overnight context executes one bounded refresh job then rereads", async ({
    page,
  }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    const reportBody = (shouldExecute: boolean) => ({
      kind: "us_overnight_tw_impact",
      stock_id: "2330",
      stock_name: "台積電",
      as_of: "2026-08-07",
      generated_at: "2026-08-10T12:00:00Z",
      stance: "neutral",
      title: "Fixture bounded refresh",
      summary: shouldExecute ? "等待跨市場更新" : "跨市場資料已更新",
      score: 0,
      weighted_change_pct: 0,
      confidence: "medium",
      tw_mapping: {
        stock_id: "2330",
        stock_name: "台積電",
        market: "TWSE",
        industry: "24",
        category: null,
        profiles: ["semiconductor"],
        reason: "fixture",
      },
      adr_parity: null,
      cross_market_context: null,
      fx_flow_context: null,
      refresh_decision: {
        status: shouldExecute ? "planned" : "not_needed",
        should_execute: shouldExecute,
        reason: shouldExecute
          ? "executable_cross_market_sources_available"
          : "cross_market_sources_current",
        planned_source_count: shouldExecute ? 1 : 0,
        deferred_source_count: 0,
        cooldown_source_count: 0,
      },
      refresh_plan: {},
      factors: [],
      baskets: [],
      missing: [],
      warnings: [],
      source_refs: [],
      freshness: {},
      evidence_passport: {},
    });
    const completedJob = {
      id: 91,
      job_type: "cross_market.context_refresh",
      status: "success",
      target: "2330",
      progress_current: 1,
      progress_total: 1,
      message: "Bounded cross-market refresh complete.",
      error_message: null,
      request: {},
      result: { status: "success", success_count: 1, failed_count: 0 },
      created_at: "2026-08-10T12:00:00Z",
      started_at: "2026-08-10T12:00:01Z",
      ended_at: "2026-08-10T12:00:02Z",
      updated_at: "2026-08-10T12:00:02Z",
    };

    await mockOmiApi(page, {
      apiRequests,
      apiResponder: ({ method, path, requestNumber }) => {
        if (method === "GET" && path.endsWith("/market/overnight-impact/2330")) {
          return { body: reportBody(requestNumber === 1) };
        }
        if (method === "POST" && path.endsWith("/market/cross-market/refresh")) {
          return { body: completedJob };
        }
        if (method === "GET" && path.endsWith("/jobs/91")) {
          return { body: completedJob };
        }
        return null;
      },
    });

    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect.poll(
      () =>
        apiRequests.filter(
          (request) =>
            request.method === "GET" &&
            request.path.endsWith("/market/overnight-impact/2330")
        ).length
    ).toBe(2);
    const refreshRequests = apiRequests.filter(
      (request) =>
        request.method === "POST" &&
        request.path.endsWith("/market/cross-market/refresh")
    );
    expect(refreshRequests).toHaveLength(1);
    expect(refreshRequests[0]?.search).toContain("stock_ids=2330");
    expect(refreshRequests[0]?.search).toContain("max_symbols=1");
    expect(refreshRequests[0]?.search).toContain("max_runtime_seconds=120");
  });

  test("Taiwan overnight context renders noncausal proxy residual", async ({ page }) => {
    await mockOmiApi(page, {
      apiResponder: ({ path }) =>
        path.endsWith("/market/overnight-impact/2330")
          ? {
              body: {
                kind: "us_overnight_tw_impact",
                stock_id: "2330",
                stock_name: "台積電",
                as_of: "2026-08-07",
                generated_at: "2026-08-09T13:00:00Z",
                stance: "neutral",
                title: "Fixture proxy context",
                summary: "Fixture proxy context",
                score: 0,
                weighted_change_pct: 0,
                confidence: "medium",
                tw_mapping: null,
                adr_parity: null,
                cross_market_context: {
                  kind: "cross_market_target_context",
                  schema_version: "cross_market.context.v1",
                  target: {
                    market: "TW",
                    instrument_type: "stock",
                    canonical_symbol: "TW:2330",
                    provider_symbol: "2330",
                    exchange: "TWSE",
                    currency: "TWD",
                  },
                  status: "ready",
                  decision_usable: true,
                  as_of: "2026-08-07",
                  decision_at: "2026-08-09T13:00:00Z",
                  methodology_version: "cross_market.relation_context.v2",
                  relation_snapshot_version: "relation_registry:77:v1",
                  snapshot_id: "cmctx:proxy-fixture",
                  summary: {
                    stance: "adverse",
                    score: -0.24,
                    confidence: "medium",
                    title: "產業 proxy residual 偏弱",
                    reason_codes: ["industry_peer_residual_negative"],
                  },
                  direct_equivalents: [],
                  signals: [
                    {
                      signal_id: "proxy_residual:TW:2330:77:v1",
                      relation_id: 77,
                      relation_version: 1,
                      source: {
                        market: "US",
                        instrument_type: "stock",
                        canonical_symbol: "US:MU",
                        provider_symbol: "MU",
                        exchange: "NASDAQ",
                        currency: "USD",
                      },
                      target: {
                        market: "TW",
                        instrument_type: "stock",
                        canonical_symbol: "TW:2330",
                        provider_symbol: "2330",
                        exchange: "TWSE",
                        currency: "TWD",
                      },
                      bucket: "industry_peer",
                      relation_type: "industry_peer",
                      relation_subtype: "dram_memory_cycle_proxy",
                      event_context: "unresolved",
                      calculation: {
                        kind: "benchmark_residual",
                        raw_return_pct: 5,
                        benchmark_return_pct: 6,
                        excess_return_pct: -1,
                      },
                      direction: "adverse",
                      configured_weight: 0.4,
                      quality_multiplier: 0.6,
                      effective_weight: 0.24,
                      normalized_weight: 1,
                      contribution: -0.24,
                      status: "ready",
                      decision_usable: true,
                      confidence_tier: "C",
                      freshness: {},
                      evidence_refs: ["cross_market_relation_evidence:88"],
                      source_refs: [],
                      warnings: ["event_context_unresolved"],
                      limitations: [
                        "industry_proxy_not_company_causality",
                        "event_context_unresolved",
                      ],
                      excluded_reason: null,
                    },
                  ],
                  bucket_scores: { industry_peer: -0.24 },
                  coverage: {
                    configured_signal_count: 1,
                    available_signal_count: 1,
                    decision_usable_signal_count: 1,
                    configured_weight: 0.4,
                    available_weight: 0.4,
                    decision_usable_weight: 0.4,
                    coverage_ratio: 1,
                    excluded_by_reason: {},
                  },
                  freshness: { read_path_provider_refresh: false },
                  missing: [],
                  warnings: ["event_context_unresolved"],
                  limitations: [
                    "industry_proxy_not_company_causality",
                    "event_context_unresolved",
                  ],
                  source_refs: [],
                  evidence_passport: {
                    relation_ids: [77],
                    evidence_ids: [88],
                    mapping_source: "registry",
                  },
                },
                fx_flow_context: null,
                factors: [],
                baskets: [],
                missing: [],
                warnings: [],
                source_refs: [],
                freshness: {},
                evidence_passport: {},
              },
            }
          : null,
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    const context = page.getByTestId("cross-market-context-strip");
    const toggle = page.getByTestId("cross-market-context-toggle");
    await expect(toggle).toContainText("MU → 2330 · 同業代理（非因果）");
    await expect(toggle).toContainText("外部相對壓力");
    await expect(toggle).toContainText("關係信心 Tier C");
    await expect(toggle).toContainText("映射分數");
    await expect(toggle).toContainText("-0.24%");
    await toggle.click();
    await expect(context).toContainText("MU · 同業代理（非因果）");
    await expect(context).toContainText("來源 +5.00%");
    await expect(context).toContainText("基準 +6.00%");
    await expect(context).toContainText("Residual -1.00%");
    await expect(context).toContainText("基礎 0.40 × 品質 0.60 = 有效 0.24");
    await expect(context).toContainText("主要訊號貢獻");
    await expect(context).toContainText("-0.24%");
    await expect(context).toContainText("不代表兩家公司有供應、客戶或持股關係");
  });

  test("Taiwan professional mode stays focused when selecting another security", async ({
    page,
  }) => {
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
    });
    await page.goto("/?market=tw&group_id=7&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByTestId("stock-detail-expand")).toBeEnabled();
    await page.getByTestId("stock-detail-expand").click();
    await expect(page.getByTestId("professional-chart-panel")).toBeVisible();
    await expect(page.getByTestId("market-tape-tw")).toBeHidden();

    const indexButton = page.getByRole("button", { name: /TAIEX 加權指數/ }).first();
    if (!(await indexButton.isVisible())) {
      await page.getByRole("button", { name: "切換加權指數資料夾" }).click();
    }
    await indexButton.click();

    await expect(page).toHaveURL(/stock_id=TAIEX/);
    await expect(page.getByTestId("professional-chart-panel")).toBeVisible();
    await expect(page.getByRole("button", { name: "總覽" })).toBeVisible();
    await expect(page.getByTestId("market-tape-tw")).toBeHidden();
  });

  test("TPEX today uses the shared intraday surface without post-close pollution", async ({
    page,
  }) => {
    const tpexSummary = marketIndexSummaryResponse(103);
    tpexSummary.indices[0] = {
      ...tpexSummary.indices[0],
      index_id: "TPEX",
      label: "櫃買指數",
      short_label: "TPEX",
      market: "TPEX",
      symbol: "^TWOII",
      breadth: {
        advance_count: 4,
        decline_count: 3,
        unchanged_count: 1,
        total_count: 8,
        trade_value: 120_000_000_000,
      },
    };
    await mockOmiApi(page, {
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/indices/summary")) {
          return { body: tpexSummary };
        }
        if (path.endsWith("/market/indices/TPEX/ohlc")) {
          return { body: ohlcResponse("TPEX") };
        }
        if (path.endsWith("/market/indices/TPEX/contributions")) {
          return {
            body: {
              index_id: "TPEX",
              market: "TPEX",
              source: "playwright.fixture",
              method: "fixture",
              as_of: "2026-06-15T09:02:00+08:00",
              trade_date: "2026-06-15",
              index_close: 101,
              index_change: 1,
              total_market_value: null,
              positive: [],
              negative: [],
            },
          };
        }
        if (path.endsWith("/market/indices/TPEX/intraday")) {
          return {
            body: {
              stock_id: "TPEX",
              index_id: "TPEX",
              market: "TPEX",
              symbol: "^TWOII",
              source: "tpex_index_5s_twse_mis_snapshot",
              trade_date: "2026-06-15",
              previous_close: 100,
              interval: "1m",
              source_interval: "5s",
              effective_interval: "1m",
              source_point_count: 9,
              point_count: 4,
              capabilities: {
                supports_volume: false,
                supports_vwap: false,
                supports_price_limit: false,
                supports_quote_depth: false,
              },
              current_observation: {
                value: 103,
                observed_at: "2026-06-15T13:30:00+08:00",
                confirmed_at: "2026-06-15T13:33:00+08:00",
                price_semantics: "official_index_close",
                provider: "playwright.fixture",
                freshness_status: "post_close_final",
                decision_usable: true,
              },
              points: [
                {
                  time: "2026-06-15T09:00:00+08:00",
                  price: 102,
                  volume: null,
                  open: 101,
                  high: 102,
                  low: 101,
                  bar_type: "regular_interval",
                  display_eligible: true,
                  indicator_eligible: true,
                },
                {
                  time: "2026-06-15T09:01:00+08:00",
                  price: 100,
                  volume: null,
                  open: 102,
                  high: 102,
                  low: 100,
                  bar_type: "regular_interval",
                  display_eligible: true,
                  indicator_eligible: true,
                },
                {
                  time: "2026-06-15T09:02:00+08:00",
                  price: 101,
                  volume: null,
                  open: 101,
                  high: 101,
                  low: 101,
                  bar_type: "regular_interval",
                  display_eligible: true,
                  indicator_eligible: true,
                },
                {
                  time: "2026-06-15T13:30:00+08:00",
                  price: 103,
                  volume: null,
                  open: 103,
                  high: 103,
                  low: 103,
                  bar_type: "official_close_marker",
                  display_eligible: true,
                  indicator_eligible: true,
                },
              ],
            },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=TPEX", {
      waitUntil: "domcontentloaded",
    });

    const todayTimeframe = page.getByTestId("timeframe-today");
    await todayTimeframe.click();
    await expect(todayTimeframe).toHaveClass(/omi-timeframe-tab-active/);

    const chart = page.getByTestId("today-intraday-surface");
    await expect(chart).toBeVisible();
    await expect(chart).toHaveAttribute("data-point-count", "4");
    await expect(chart.getByTestId("intraday-trend-chart")).toHaveAttribute(
      "data-rendered-point-count",
      "4"
    );
    await expect(chart.getByTestId("intraday-trend-chart")).toHaveAttribute(
      "data-volume-rendered",
      "false"
    );
    await expect(page.getByTestId("today-header-price")).toContainText("103");
    expect(await chart.locator("svg *").count()).toBeLessThan(500);
    await expect(chart).toContainText("13:30");
    await expect(chart).not.toContainText("2026/06/14");
    await expect(chart).not.toContainText("999");
    await expect(chart).toContainText("櫃買 5 秒走勢 + MIS 收盤確認");
    await expect(page.getByTestId("index-detail-open")).toContainText("101");
    await expect(page.getByTestId("index-detail-open")).not.toContainText("100");
    await expect(page.getByTestId("market-tape-tpex-breadth-ratio")).toContainText("50");
    await expect(page.getByTestId("market-tape-tpex-breadth-coverage")).toContainText("8/8");
    await expect(page.getByTestId("professional-chart-panel")).toHaveCount(0);
    await expect(page.getByTestId("stock-detail-expand")).toHaveCount(0);

    await page.getByTestId("chart-indicator-menu-toggle").click();
    const indicatorMenu = page.getByTestId("intraday-indicator-menu");
    await expect(indicatorMenu).toBeVisible();
    await expect(indicatorMenu.locator('[data-indicator-option="volume"]')).toHaveCount(0);
    await expect(indicatorMenu.locator('[data-indicator-option="vwap"]')).toHaveCount(0);
    await expect(indicatorMenu.locator('[data-indicator-option="twap"]')).toHaveCount(1);
  });

  test("TPEX snapshot-only fallback settles as unavailable instead of loading forever", async ({
    page,
  }) => {
    await mockOmiApi(page, {
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/indices/TPEX/ohlc")) {
          return { body: ohlcResponse("TPEX") };
        }
        if (path.endsWith("/market/indices/TPEX/contributions")) {
          return {
            body: {
              index_id: "TPEX",
              market: "TPEX",
              source: "playwright.fixture",
              method: "fixture",
              as_of: "2026-06-15T13:33:00+08:00",
              trade_date: "2026-06-15",
              index_close: 103,
              index_change: 3,
              total_market_value: null,
              positive: [],
              negative: [],
            },
          };
        }
        if (path.endsWith("/market/indices/TPEX/intraday")) {
          return {
            body: {
              stock_id: "TPEX",
              symbol: "^TWOII",
              source: "twse_mis_index_snapshot",
              trade_date: "2026-06-15",
              coverage_status: "single_snapshot",
              is_partial: true,
              previous_close: 100,
              point_count: 1,
              capabilities: {
                supports_volume: false,
                supports_vwap: false,
                supports_price_limit: false,
                supports_quote_depth: false,
              },
              current_observation: {
                value: 103,
                observed_at: "2026-06-15T13:30:00+08:00",
                confirmed_at: "2026-06-15T13:33:00+08:00",
                price_semantics: "official_index_close",
                provider: "playwright.fixture",
                freshness_status: "post_close_final",
                decision_usable: true,
              },
              warnings: ["Only a post-close snapshot is available."],
              points: [
                {
                  time: "2026-06-15T13:30:00+08:00",
                  price: 103,
                  volume: null,
                  open: 103,
                  high: 103,
                  low: 103,
                  bar_type: "official_close_marker",
                  display_eligible: true,
                  indicator_eligible: true,
                },
              ],
            },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=TPEX", {
      waitUntil: "domcontentloaded",
    });

    await page.getByTestId("timeframe-today").click();

    const empty = page.getByTestId("today-intraday-surface");
    await expect(empty).toBeVisible();
    await expect(empty.getByTestId("intraday-trend-empty")).toHaveAttribute(
      "data-rendered-point-count",
      "1"
    );
    await expect(empty.locator('[aria-busy="true"]')).toHaveCount(0);
  });

  test("Taiwan stock detail ignores stale chart and quote responses after selection changes", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/ohlc/2330")) {
          return { body: stockOhlcResponse("2330"), delayMs: 800 };
        }
        if (path.endsWith("/market/quote-depth/2330")) {
          return { body: quoteDepthResponse("2330"), delayMs: 900 };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&group_id=7&stock_id=2330&radar_mode=action", {
      waitUntil: "domcontentloaded",
    });

    await page.locator('[data-watchlist-group-id="7"]').click();
    const umcRankingLink = page.locator('[data-ranking-stock-id="2303"]');
    await expect(umcRankingLink).toBeVisible();
    await umcRankingLink.click();

    const stockDetail = page.getByTestId("stock-detail-panel");
    await expect(page.getByRole("heading", { level: 2 }).filter({ hasText: "2303" })).toBeVisible();
    await expect(stockDetail).toHaveAttribute("data-chart-stock-id", "2303");
    await expect(stockDetail).toHaveAttribute("data-chart-load-state", "success");
    const chartCard = page.getByTestId("stock-chart-card");
    const quoteDepthPanel = page.getByTestId("quote-depth-panel");
    const technicalCurrentState = page.getByTestId("tw-technical-current-state");
    await expect(technicalCurrentState).toBeVisible();
    await expect(page.getByTestId("tw-technical-position-count")).toContainText("3/3");
    await expect(technicalCurrentState).toContainText("修復與風險階梯");
    await expect(technicalCurrentState).toContainText("20 日低點／風險線");
    await expect(technicalCurrentState).toContainText("站回 MA5");
    await expect(technicalCurrentState).toContainText("站回 MA60");
    await expect(technicalCurrentState).toContainText("站回 MA20");

    await expect(quoteDepthPanel).toContainText("52.4");
    await expect(chartCard).toContainText("成交量(股)");
    await expect(page.getByTestId("quote-volume-summary")).toHaveCount(0);
    await expect(page.getByTestId("quote-recent-trades")).toContainText("即時成交");
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("52.4");
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("12 張");
    await expect(page.getByTestId("quote-depth-bid-empty")).toHaveCount(0);
    await expect(page.getByTestId("quote-depth-book-column")).toContainText("52.3");
    await expect(page.getByTestId("quote-depth-mode-replay")).toBeEnabled();
    await expect(page.getByTestId("quote-depth-mode-replay")).toHaveText("試撮");
    await expect(page.getByTestId("quote-depth-replay-coverage")).toHaveText(
      "目前標的無試撮快照"
    );
    await expect
      .poll(async () => {
        const bookBox = await page.getByTestId("quote-depth-book-column").boundingBox();
        const summaryBox = await page
          .getByTestId("quote-depth-summary-column")
          .boundingBox();
        if (!bookBox || !summaryBox) return false;
        return (
          Math.abs(bookBox.y - summaryBox.y) <= 1 &&
          summaryBox.x >= bookBox.x + bookBox.width &&
          summaryBox.width > bookBox.width
        );
      })
      .toBe(true);
    await expect
      .poll(async () => {
        const chartBox = await chartCard.boundingBox();
        const quoteDepthBox = await quoteDepthPanel.boundingBox();
        if (!chartBox || !quoteDepthBox) return false;
        return quoteDepthBox.y >= chartBox.y + chartBox.height;
      })
      .toBe(true);

    await page.waitForTimeout(1_000);
    await expect(stockDetail).toHaveAttribute("data-chart-stock-id", "2303");
    await expect(quoteDepthPanel).toContainText("52.4");
    await page.getByTestId("timeframe-today").click();
    const stockTodayChart = page
      .getByTestId("today-intraday-surface")
      .getByTestId("intraday-trend-chart");
    await expect(stockTodayChart).toBeVisible();
    await expect(stockTodayChart).toHaveAttribute("data-volume-rendered", "true");
    await expect(page.getByTestId("intraday-current-price-status")).toContainText(
      "MIS 成交 09:30:00"
    );
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan quote depth replays only persisted auction snapshots", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    const liveQuote = quoteDepthResponse("2330");
    const auctionQuote = {
      ...liveQuote,
      session_phase: "preopen_auction",
      instrument_phase: "preopen_auction",
      phase_label: "試撮",
      quote_time: "2026-06-15T08:59:55+08:00",
      fetched_at: "2026-06-15T08:59:56+08:00",
      last_price: null,
      change: null,
      change_pct: null,
      total_volume_lots: null,
      indicative_match_available: true,
      indicative_match_price: 1_010,
      indicative_match_volume_lots: 2_046,
      indicative_match_price_source_field: "pz",
      indicative_match_volume_source_field: "ps",
      freshness: {
        ...liveQuote.freshness,
        status: "snapshot",
        is_live: false,
        message: "Captured auction snapshot",
      },
    };
    const closingAuctionQuote = {
      ...auctionQuote,
      session_phase: "closing_auction",
      instrument_phase: "closing_auction",
      phase_label: "收盤撮合",
      quote_time: "2026-06-15T13:28:55+08:00",
      fetched_at: "2026-06-15T13:28:56+08:00",
      indicative_match_price: 1_015,
      indicative_match_volume_lots: 3_120,
    };
    await mockOmiApi(page, {
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/quote-depth/2330/replay")) {
          return {
            body: {
              kind: "taiwan_quote_contract_replay",
              stock_id: "2330",
              trade_date: "2026-06-15",
              timezone: "UTC+08:00",
              required_slots: ["08:59", "13:28"],
              required_count: 2,
              captured_count: 2,
              coverage_ratio: 1,
              complete: true,
              missing_slots: [],
              snapshots: [
                {
                  capture_slot: "08:59",
                  status: "captured",
                  scheduled_at: "2026-06-15T08:59:00+08:00",
                  captured_at: "2026-06-15T08:59:56+08:00",
                  quote_time: "2026-06-15T08:59:55+08:00",
                  freshness_status: "snapshot",
                  refresh_outcome: "updated",
                  error: null,
                  quote: auctionQuote,
                },
                {
                  capture_slot: "13:28",
                  status: "captured",
                  scheduled_at: "2026-06-15T13:28:00+08:00",
                  captured_at: "2026-06-15T13:28:56+08:00",
                  quote_time: "2026-06-15T13:28:55+08:00",
                  freshness_status: "snapshot",
                  refresh_outcome: "updated",
                  error: null,
                  quote: closingAuctionQuote,
                },
              ],
              source: "taiwan_quote_contract_snapshot",
              replay_semantics:
                "persisted_fixed_slot_evidence_projected_to_current_public_contract",
              read_path_side_effects: false,
            },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    const panel = page.getByTestId("quote-depth-panel");
    await expect(page.getByTestId("quote-depth-mode-replay")).toBeEnabled();
    await expect(page.getByTestId("quote-depth-replay-coverage")).toContainText(
      "2 筆試撮快照"
    );
    await page.getByTestId("quote-depth-mode-replay").click();
    await expect(panel).toContainText("試撮快照 13:28");
    await expect(panel).toContainText("保存回放");
    await expect(page.getByTestId("quote-auction-details")).toContainText("試撮明細");
    await expect(page.getByTestId("quote-auction-detail-row")).toHaveCount(2);
    await expect(page.getByTestId("quote-auction-details")).toContainText("1,010");
    await expect(page.getByTestId("quote-auction-details")).toContainText("2,046 張");
    await expect(page.getByTestId("quote-auction-details")).toContainText("1,015");
    await expect(page.getByTestId("quote-auction-details")).toContainText("3,120 張");
    await expect(page.getByTestId("quote-volume-summary")).toHaveCount(0);
    await expect
      .poll(async () => {
        const bookBox = await page.getByTestId("quote-depth-book-column").boundingBox();
        const auctionBox = await page
          .getByTestId("quote-depth-summary-column")
          .boundingBox();
        if (!bookBox || !auctionBox) return false;
        return (
          Math.abs(bookBox.y - auctionBox.y) <= 1 &&
          auctionBox.x >= bookBox.x + bookBox.width &&
          auctionBox.width / bookBox.width >= 1.2 &&
          auctionBox.width / bookBox.width <= 1.35 &&
          Math.abs(bookBox.height - auctionBox.height) <= 1
        );
      })
      .toBe(true);

    await page.setViewportSize({ width: 900, height: 900 });
    await expect
      .poll(async () => {
        const bookBox = await page.getByTestId("quote-depth-book-column").boundingBox();
        const auctionBox = await page
          .getByTestId("quote-depth-summary-column")
          .boundingBox();
        if (!bookBox || !auctionBox) return false;
        return auctionBox.y >= bookBox.y + bookBox.height;
      })
      .toBe(true);

    await page.getByTestId("quote-depth-mode-live").click();
    await expect(panel).toContainText("Regular");
    await expect(panel).not.toContainText("保存回放");
  });

  test("Taiwan quote depth prioritizes the realtime trade tape", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await mockOmiApi(page);
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    const panel = page.getByTestId("quote-depth-panel");
    await panel.scrollIntoViewIfNeeded();
    await expect(page.getByTestId("quote-depth-mode-live")).toHaveText("即時成交");
    await expect(page.getByTestId("quote-depth-mode-replay")).toHaveText("試撮");
    await expect(page.getByTestId("quote-recent-trades-status")).toHaveText("即時");
    await expect(panel).toContainText("KGI SUPERPY · PRESENTATION STREAM");
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("1,015");
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("12 張");
    await expect(page.getByTestId("quote-volume-summary")).toHaveCount(0);
    await expect
      .poll(async () => {
        const bookBox = await page.getByTestId("quote-depth-book-column").boundingBox();
        const tradeBox = await page
          .getByTestId("quote-depth-summary-column")
          .boundingBox();
        if (!bookBox || !tradeBox) return false;
        return (
          Math.abs(bookBox.y - tradeBox.y) <= 1 &&
          tradeBox.x >= bookBox.x + bookBox.width &&
          tradeBox.width / bookBox.width >= 1.2 &&
          tradeBox.width / bookBox.width <= 1.35 &&
          Math.abs(bookBox.height - tradeBox.height) <= 1
        );
      })
      .toBe(true);
  });

  test("Taiwan quote depth renders realtime stream before the GET baseline completes", async ({
    page,
  }) => {
    let quoteDepthRequestFinished = false;
    page.on("requestfinished", (request) => {
      if (new URL(request.url()).pathname.endsWith("/market/quote-depth/2330")) {
        quoteDepthRequestFinished = true;
      }
    });
    await mockOmiApi(page, {
      apiResponder: ({ path }) =>
        path.endsWith("/market/quote-depth/2330")
          ? { body: quoteDepthResponse("2330"), delayMs: 3_000 }
          : null,
    });
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    const panel = page.getByTestId("quote-depth-panel");
    await expect(panel).toContainText("KGI SUPERPY · PRESENTATION STREAM", {
      timeout: 2_000,
    });
    await expect(panel).toContainText("1,014.9", { timeout: 2_000 });
    expect(quoteDepthRequestFinished).toBe(false);
  });

  test("Taiwan quote depth keeps realtime stream usable when the GET baseline fails", async ({
    page,
  }) => {
    await mockOmiApi(page, {
      apiResponder: ({ path }) =>
        path.endsWith("/market/quote-depth/2330")
          ? { body: { detail: "fixture baseline unavailable" }, status: 503 }
          : null,
    });
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    const panel = page.getByTestId("quote-depth-panel");
    await expect(panel).toContainText("KGI SUPERPY · PRESENTATION STREAM");
    await expect(panel).toContainText("1,014.9");
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("1,015");
    await expect(panel).not.toContainText("五檔資料讀取失敗");
  });

  test("Taiwan quote depth keeps five placeholder levels in live and auction views", async ({
    page,
  }) => {
    const quoteWithoutDepth = {
      ...quoteDepthResponse("2330"),
      bid_levels: [],
      ask_levels: [],
      best_bid_price: null,
      best_bid_size_lots: null,
      best_ask_price: null,
      best_ask_size_lots: null,
      bid_total_size_lots: null,
      ask_total_size_lots: null,
      depth_available: false,
    };
    const streamWithoutDepth = {
      ...realtimeQuoteStreamResponse("2330"),
      capability_status: {
        ...realtimeQuoteStreamResponse("2330").capability_status,
        depth: "empty",
      },
      depth: null,
    };
    const replayWithoutDepth = {
      ...emptyQuoteReplayResponse("2330"),
      trade_date: "2026-06-15",
      captured_count: 1,
      coverage_ratio: 0.2,
      missing_slots: ["08:30", "08:50", "08:55", "08:58"],
      snapshots: [
        {
          capture_slot: "08:59",
          status: "captured",
          scheduled_at: "2026-06-15T08:59:00+08:00",
          captured_at: "2026-06-15T08:59:56+08:00",
          quote_time: "2026-06-15T08:59:55+08:00",
          freshness_status: "snapshot",
          refresh_outcome: "updated",
          error: null,
          quote: {
            ...quoteWithoutDepth,
            session_phase: "preopen_auction",
            instrument_phase: "preopen_auction",
            phase_label: "試撮",
            quote_time: "2026-06-15T08:59:55+08:00",
          },
        },
      ],
    };
    await mockOmiApi(page, {
      apiResponder: ({ path }) => {
        if (path.includes("/market/quote-depth/2330/replay")) {
          return { body: replayWithoutDepth };
        }
        if (path.endsWith("/market/quote-depth/2330")) {
          return { body: quoteWithoutDepth };
        }
        if (path.endsWith("/market/realtime-quotes/2330")) {
          return { body: streamWithoutDepth };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    const book = page.getByTestId("quote-depth-book-column");
    await expect(page.getByTestId("quote-depth-bid-row")).toHaveCount(5);
    await expect(page.getByTestId("quote-depth-ask-row")).toHaveCount(5);
    await expect(book.getByText("Open", { exact: true })).toHaveCount(0);
    await expect(book.getByText("High", { exact: true })).toHaveCount(0);
    await expect(book.getByText("Low", { exact: true })).toHaveCount(0);
    await expect(book.getByText("Volume", { exact: true })).toHaveCount(0);

    for (const side of ["bid", "ask"] as const) {
      for (let level = 1; level <= 5; level += 1) {
        await expect(
          page.getByTestId(`quote-depth-${side}-level-${level}-price`)
        ).toHaveText("-");
        await expect(
          page.getByTestId(`quote-depth-${side}-level-${level}-size`)
        ).toHaveText("-");
      }
    }

    await expect(page.getByTestId("quote-depth-replay-coverage")).toContainText(
      "1 筆試撮快照"
    );
    await page.getByTestId("quote-depth-mode-replay").click();
    await expect(page.getByTestId("quote-depth-mode-replay")).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await expect(page.getByTestId("quote-depth-bid-row")).toHaveCount(5);
    await expect(page.getByTestId("quote-depth-ask-row")).toHaveCount(5);
    await expect(page.getByTestId("quote-depth-bid-level-1-price")).toHaveText("-");
    await expect(page.getByTestId("quote-depth-ask-level-5-size")).toHaveText("-");
  });

  test("Taiwan quote depth isolates stream and GET state across rapid symbol switches", async ({
    page,
  }) => {
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      apiResponder: ({ path }) =>
        path.endsWith("/market/quote-depth/2303")
          ? { body: quoteDepthResponse("2303"), delayMs: 3_000 }
          : null,
    });
    await page.goto("/?market=tw&group_id=7&stock_id=2330&radar_mode=action", {
      waitUntil: "domcontentloaded",
    });

    await page.locator('[data-watchlist-group-id="7"]').click();
    await expect(page.locator('[data-ranking-stock-id="2303"]')).toBeVisible();
    await page.locator('[data-ranking-stock-id="2330"]').click();
    const panel = page.getByTestId("quote-depth-panel");
    await expect(panel).toContainText("KGI SUPERPY · PRESENTATION STREAM");
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("1,015");

    await page.locator('[data-ranking-stock-id="2303"]').click();
    await expect(page.getByRole("heading", { level: 2 }).filter({ hasText: "2303" })).toBeVisible();
    await expect(panel).toContainText("KGI SUPERPY · PRESENTATION STREAM", {
      timeout: 2_000,
    });
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("52.4", {
      timeout: 2_000,
    });
    await expect(panel).not.toContainText("1,015");

    await page.locator('[data-ranking-stock-id="2330"]').click();
    await expect(page.getByRole("heading", { level: 2 }).filter({ hasText: "2330" })).toBeVisible();
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("1,015", {
      timeout: 2_000,
    });
    await expect(panel).not.toContainText("52.4");

    await page.waitForTimeout(3_200);
    await expect(page.getByTestId("quote-recent-trade-row")).toContainText("1,015");
    await expect(panel).not.toContainText("52.4");
  });

  test("Taiwan quote depth switches the right column to live auction details", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    const auctionQuote = {
      ...quoteDepthResponse("2330"),
      session_phase: "preopen_auction",
      instrument_phase: "preopen_auction",
      phase_label: "試撮",
      quote_time: "2026-06-15T08:59:55+08:00",
      indicative_match_available: true,
      indicative_match_price: 1_015,
      indicative_match_volume_lots: 2_046,
    };
    const auctionStream = {
      ...realtimeQuoteStreamResponse("2330"),
      event_time: "2026-06-15T08:59:55+08:00",
      capability_status: {
        ...realtimeQuoteStreamResponse("2330").capability_status,
        auction_observations: "available",
      },
      auction_observations: [
        {
          event_id: "auction:2330:1",
          sequence: 1,
          event_time: "2026-06-15T08:59:55+08:00",
          received_at: "2026-06-15T00:59:55Z",
          indicative_match_price: 1_015,
          indicative_match_volume_lots: 2_046,
          best_bid_price: 1_010,
          best_ask_price: 1_020,
          top5_bid_volume_lots: 3_135,
          top5_ask_volume_lots: 2_180,
          top5_imbalance: 0.18,
          diff_bid_volume_lots: [5, 2, 0, -1, 3],
          diff_ask_volume_lots: [-2, 1, 0, 2, -3],
          semantics: "indicative_auction_observation_not_formal_trade",
        },
      ],
    };
    await mockOmiApi(page, {
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/quote-depth/2330")) return { body: auctionQuote };
        if (path.endsWith("/market/realtime-quotes/2330")) return { body: auctionStream };
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    await expect(page.getByTestId("quote-depth-panel")).toContainText("試撮");
    await expect(page.getByTestId("quote-recent-trades-status")).toHaveText("即時");
    await page.getByTestId("quote-depth-mode-replay").click();
    await expect(page.getByTestId("quote-depth-mode-replay")).toHaveText("試撮");
    await expect(page.getByTestId("quote-auction-status")).toHaveText("即時");
    const auctionRow = page.getByTestId("quote-auction-detail-row");
    await expect(auctionRow).toContainText("08:59:55");
    await expect(auctionRow).toContainText("1,010");
    await expect(auctionRow).toContainText("1,020");
    await expect(auctionRow).toContainText("1,015");
    await expect(auctionRow).toContainText("2,046 張");
    await expect(page.getByTestId("quote-volume-summary")).toHaveCount(0);
  });

  test("Taiwan intermediate desktop keeps Technical directly reachable", async ({ page }) => {
    await page.setViewportSize({ width: 1256, height: 900 });
    await mockOmiApi(page);
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    const jump = page.getByTestId("technical-compact-jump");
    const technical = page.getByTestId("stock-detail-secondary-panel");
    await expect(jump).toBeVisible();
    await expect(jump).toContainText("Technical");
    await jump.click();
    await expect(technical).toBeInViewport();
  });

  test("Taiwan daily technical panel separates finalized and provisional states", async ({
    page,
  }) => {
    const technicalState = (price: number, label: string) => ({
      version: "tw_technical_current_state_v1",
      headline: { key: label, label, tone: "neutral" },
      qualifier: { key: "neutral", label: "中性", tone: "neutral" },
      summary: `${label}摘要`,
      position: {
        price,
        label,
        below_count: 0,
        above_count: 3,
        available_count: 3,
        order: ["ma5", "ma20", "ma60"],
        order_label: "MA5 > MA20 > MA60",
        alignment: "bullish",
        alignment_label: "多頭排列",
        distance_pct: {},
      },
      levels: [],
      evidence: [],
      next_conditions: [],
    });
    await mockOmiApi(page, {
      apiResponder: ({ path }) =>
        path.endsWith("/market/technical/3711")
          ? {
              body: {
                kind: "tw_stock_technical_report",
                stock_id: "3711",
                timeframe: "daily",
                phase: "daily_intraday",
                confidence: "medium",
                generated_at: "2026-08-27T14:00:00+08:00",
                title: "正式完成狀態",
                summary: "正式完成摘要",
                score: 1,
                value: -2,
                value_label: "vs MA20",
                rows: [],
                badges: [],
                data: {
                  decision_state: technicalState(592, "正式完成狀態"),
                  decision_state_time: "2026-08-26",
                  decision_state_status: "official_daily_finalized",
                  current_state: technicalState(605, "今日暫估狀態"),
                  current_state_time: "2026-08-27",
                  current_state_status: "provisional_close",
                  current_state_decision_usable: false,
                  current_observation: {
                    status: "provisional_close",
                    time: "2026-08-27",
                    decision_usable: false,
                    official_daily_confirmed: false,
                    current_state: technicalState(605, "今日暫估狀態"),
                  },
                  price_context: {
                    daily_indicator_time: "2026-08-26",
                  },
                },
                missing: [],
                warnings: ["Provisional observation is not decision-usable."],
                source_refs: [],
              },
            }
          : null,
    });
    await page.goto("/?market=tw&stock_id=3711", {
      waitUntil: "domcontentloaded",
    });

    const technicalPanel = page.getByTestId("stock-detail-secondary-panel");
    await expect(technicalPanel).toHaveAttribute(
      "data-decision-state-status",
      "official_daily_finalized"
    );
    await expect(technicalPanel.locator(".omi-technical-summary")).toContainText(
      "正式完成狀態"
    );
    await expect(technicalPanel.locator(".omi-technical-summary")).not.toContainText(
      "今日暫估狀態"
    );
    const provisional = page.getByTestId("tw-technical-provisional-section");
    await expect(provisional).toContainText("今日暫估觀察");
    await expect(provisional).toContainText("今日暫估狀態");
    await expect(provisional).toContainText("605");
    await expect(provisional).toContainText("不可作正式決策");
  });

  test("Taiwan technical sections collapse below the fixed structure header", async ({
    page,
  }) => {
    await mockOmiApi(page, {
      apiResponder: ({ path }) =>
        path.endsWith("/market/overnight-impact/2330")
          ? {
              body: {
                kind: "us_overnight_tw_impact",
                stock_id: "2330",
                stock_name: "台積電",
                as_of: "2026-08-07",
                generated_at: "2026-08-09T13:00:00Z",
                stance: "risk_on",
                title: "Fixture overnight report",
                summary: "Fixture overnight summary",
                score: 20,
                weighted_change_pct: 1,
                confidence: "high",
                tw_mapping: null,
                adr_parity: null,
                cross_market_context: null,
                fx_flow_context: null,
                factors: [],
                baskets: [],
                missing: [],
                warnings: [],
                source_refs: [],
                freshness: {},
                evidence_passport: {},
              },
            }
          : null,
    });
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    const technicalContext = page.getByTestId("tw-technical-context");
    const technicalHeader = page.locator(".omi-technical-summary").last();
    const ladder = page.getByTestId("tw-technical-ladder-disclosure");
    const nextConditions = page.getByTestId(
      "tw-technical-next-conditions-disclosure"
    );
    const evidence = page.getByTestId("tw-technical-evidence-disclosure");
    const plan = page.getByTestId("tw-next-session-plan");
    const planDisclosure = page.getByTestId("tw-next-session-plan-disclosure");
    const overnightDisclosure = page.getByTestId(
      "tw-overnight-impact-disclosure"
    );
    const overnightEyebrow = page
      .getByText("Overnight · 市場背景", { exact: true })
      .last();

    await expect(technicalHeader).toBeVisible();
    await expect(technicalHeader.locator("details")).toHaveCount(0);
    for (const disclosure of [
      ladder,
      nextConditions,
      evidence,
      planDisclosure,
      overnightDisclosure,
    ]) {
      await expect(disclosure).toBeVisible();
      await expect(disclosure).not.toHaveAttribute("open", "");
    }
    await expect(technicalContext).not.toHaveAttribute("open", "");
    await expect(technicalContext).not.toBeVisible();

    await ladder.locator("summary").click();
    await expect(ladder).toHaveAttribute("open", "");
    await expect(ladder.locator("[data-level-key]").first()).toBeVisible();

    await nextConditions.locator("summary").click();
    await expect(nextConditions).toHaveAttribute("open", "");
    await expect(nextConditions.locator("ol")).toBeVisible();

    await evidence.locator("summary").first().click();
    await expect(evidence).toHaveAttribute("open", "");
    const trendEvidence = page.getByTestId("tw-technical-evidence-trend");
    await expect(trendEvidence).toBeVisible();
    await expect(trendEvidence).not.toHaveAttribute("open", "");
    expect(
      await trendEvidence
        .locator("summary > span")
        .last()
        .evaluate((indicator) => getComputedStyle(indicator).transform)
    ).toBe("none");
    await expect(technicalContext).toBeVisible();
    await evidence.locator("summary").first().click();
    await expect(evidence).not.toHaveAttribute("open", "");
    await expect(technicalContext).not.toBeVisible();

    await expect(plan).toBeVisible();
    await expect(plan).toHaveAttribute("data-decision-usable", "true");
    await expect(plan.getByTestId("tw-next-session-plan-status")).toHaveText(
      "可使用"
    );
    await expect(plan.getByTestId("tw-next-session-level-ma20")).toContainText(
      "142"
    );
    await expect(plan.getByTestId("tw-next-session-level-ma60")).toContainText(
      "150"
    );
    await expect(
      plan.getByTestId("tw-next-session-zone-between_transition_levels")
    ).toContainText("142 – 150");
    await expect(plan.getByTestId("tw-next-session-level-ma20")).not.toBeVisible();
    await planDisclosure.locator("summary").click();
    await expect(planDisclosure).toHaveAttribute("open", "");
    await expect(plan.getByTestId("tw-next-session-level-ma20")).toBeVisible();

    await expect(overnightEyebrow).toBeVisible();
    await overnightDisclosure.locator("summary").click();
    await expect(overnightDisclosure).toHaveAttribute("open", "");

    const planHandle = await plan.elementHandle();
    const overnightHandle = await overnightEyebrow.elementHandle();
    expect(planHandle).not.toBeNull();
    expect(overnightHandle).not.toBeNull();
    expect(
      await technicalContext.evaluate(
        (contextNode, planNode) =>
          Boolean(
            contextNode.compareDocumentPosition(planNode as Node) &
              Node.DOCUMENT_POSITION_FOLLOWING
          ),
        planHandle
      )
    ).toBe(true);
    expect(
      await plan.evaluate(
        (planNode, overnightNode) =>
          Boolean(
            planNode.compareDocumentPosition(overnightNode as Node) &
              Node.DOCUMENT_POSITION_FOLLOWING
          ),
        overnightHandle
      )
    ).toBe(true);
  });

  test("Taiwan daily technical panel routes signal chips to evidence or source data", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/institutional/2478/latest")) {
          return {
            body: {
              trade_date: "2026-07-23",
              stock_id: "2478",
              stock_name: "Fixture",
              total_institutional_net: 434_000,
            },
          };
        }
        if (path.endsWith("/market/institutional/2478/history")) {
          return {
            body: [
              {
                id: 1,
                source_id: 1,
                raw_result_id: 1,
                trade_date: "2026-07-23",
                stock_id: "2478",
                stock_name: "Fixture",
                foreign_investor_buy: 1_200_000,
                foreign_investor_sell: 900_000,
                foreign_investor_net: 300_000,
                foreign_dealer_buy: null,
                foreign_dealer_sell: null,
                foreign_dealer_net: null,
                investment_trust_buy: 300_000,
                investment_trust_sell: 200_000,
                investment_trust_net: 100_000,
                dealer_self_buy: null,
                dealer_self_sell: null,
                dealer_self_net: null,
                dealer_hedge_buy: null,
                dealer_hedge_sell: null,
                dealer_hedge_net: null,
                dealer_buy: 84_000,
                dealer_sell: 50_000,
                dealer_net: 34_000,
                total_institutional_net: 434_000,
                created_at: "2026-07-23T15:00:00+08:00",
                updated_at: "2026-07-23T15:00:00+08:00",
              },
            ],
          };
        }
        if (path.endsWith("/market/institutional/2478/holding-ratios")) {
          return {
            body: {
              stock_id: "2478",
              stock_name: "Fixture",
              trade_date: "2026-07-23",
              foreign_investor_ratio: 12.4,
              investment_trust_ratio: 1.8,
              dealer_ratio: 0.6,
              source_name: "Fixture",
              source_url: "https://example.com/fixture",
              fetched_at: "2026-07-23T15:00:00+08:00",
              history: [],
            },
          };
        }
        if (path.endsWith("/market/margin/2478/latest")) {
          return {
            body: {
              trade_date: "2026-07-23",
              stock_id: "2478",
              stock_name: "Fixture",
              margin_previous_balance: 1_172,
              margin_today_balance: 1_000,
            },
          };
        }
        if (path.endsWith("/market/margin/2478/history")) {
          return {
            body: [
              {
                trade_date: "2026-07-23",
                stock_id: "2478",
                stock_name: "Fixture",
                margin_previous_balance: 1_172,
                margin_today_balance: 1_000,
              },
            ],
          };
        }
        if (path.endsWith("/market/revenue/2478/latest")) {
          return {
            body: {
              report_date: "2026-07-10",
              period: "2026-06",
              stock_id: "2478",
              stock_name: "Fixture",
              year_over_year_pct: 28.14,
            },
          };
        }
        if (path.endsWith("/market/revenue/2478/history")) {
          return {
            body: [
              {
                id: 1,
                source_id: 1,
                raw_result_id: 1,
                report_date: "2026-06-10",
                period: "2026-05",
                stock_id: "2478",
                stock_name: "Fixture",
                market: "TWSE",
                industry: "Semiconductors",
                monthly_revenue: 900_000_000,
                previous_month_revenue: 850_000_000,
                previous_year_month_revenue: 760_000_000,
                month_over_month_pct: 5.88,
                year_over_year_pct: 18.42,
                cumulative_revenue: 4_300_000_000,
                previous_year_cumulative_revenue: 3_800_000_000,
                cumulative_year_over_year_pct: 13.16,
                note: null,
                created_at: "2026-06-10T10:00:00+08:00",
                updated_at: "2026-06-10T10:00:00+08:00",
              },
              {
                id: 2,
                source_id: 1,
                raw_result_id: 2,
                report_date: "2026-07-10",
                period: "2026-06",
                stock_id: "2478",
                stock_name: "Fixture",
                market: "TWSE",
                industry: "Semiconductors",
                monthly_revenue: 1_050_000_000,
                previous_month_revenue: 900_000_000,
                previous_year_month_revenue: 819_400_000,
                month_over_month_pct: 16.67,
                year_over_year_pct: 28.14,
                cumulative_revenue: 5_350_000_000,
                previous_year_cumulative_revenue: 4_619_400_000,
                cumulative_year_over_year_pct: 15.82,
                note: null,
                created_at: "2026-07-10T10:00:00+08:00",
                updated_at: "2026-07-10T10:00:00+08:00",
              },
            ],
          };
        }
        if (path.endsWith("/market/overnight-impact/2478")) {
          return {
            body: {
              kind: "us_overnight_tw_impact",
              stock_id: "2478",
              stock_name: "Fixture",
              as_of: "2026-07-22",
              generated_at: "2026-07-23T08:00:00+08:00",
              stance: "neutral",
              title: "美股隔夜中性，科技股方向未明",
              summary: "2026-07-22 美股隔夜映射為中性，加權變動 -0.10%",
              score: 0,
              weighted_change_pct: -0.1,
              confidence: "high",
              tw_mapping: {
                stock_id: "2478",
                stock_name: "Fixture",
                market: "TWSE",
                industry: "Semiconductors",
                category: null,
                profiles: ["technology"],
                reason: "fixture",
              },
              factors: [],
              baskets: [],
              missing: [],
              warnings: [],
              source_refs: [],
              freshness: {},
              evidence_passport: {},
            },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2478", { waitUntil: "domcontentloaded" });

    const technicalCurrentState = page.getByTestId("tw-technical-current-state");
    await expect(technicalCurrentState).toBeVisible();
    await expect(page.getByTestId("tw-technical-position-count")).toContainText("3/3");
    await expect(technicalCurrentState).toContainText("修復與風險階梯");
    await expect(technicalCurrentState).toContainText("20 日低點／風險線");
    await expect(technicalCurrentState).toContainText("站回 MA5");
    await expect(technicalCurrentState).toContainText("站回 MA60");
    await expect(technicalCurrentState).toContainText("站回 MA20");

    const coreSignals = page.getByTestId("tw-signal-chip-group-technical");
    const contextSignals = page.getByTestId("tw-signal-chip-group-context");
    await expect(coreSignals).toContainText("核心訊號");
    await expect(contextSignals).toContainText("背景脈絡");
    await expect(page.getByTestId("tw-signal-chip-classification")).toHaveCount(0);
    await expect(page.getByTestId("tw-signal-chip-structure")).toContainText(
      "結構：3/3 均線下方"
    );
    await expect(page.getByTestId("tw-signal-chip-momentum")).toContainText(
      "動能：超賣但尚未止跌"
    );
    await expect(page.getByTestId("tw-signal-chip-volume")).toContainText(
      "量價：放量下跌"
    );
    await expect(page.getByTestId("tw-signal-chip-risk")).toContainText(
      "風險：距20日低 -6.88%"
    );
    await expect(page.getByTestId("tw-signal-chip-institutional")).toContainText(
      "籌碼：單日 +434張"
    );
    const marginSignal = page.getByTestId("tw-signal-chip-margin");
    await expect(marginSignal).toContainText("融資：餘額變化 -172");
    await expect(marginSignal).toHaveClass(/omi-signal-chip-neutral/);
    await expect(page.getByTestId("tw-signal-chip-revenue")).toContainText(
      "營收：YoY +28.14%"
    );
    await expect(page.getByTestId("tw-signal-chip-overnight")).toContainText(
      "隔夜：隔夜中性 -0.10%"
    );
    await expect(page.getByTestId("tw-signal-chip-market-relative")).toContainText(
      "pp"
    );

    const trendEvidence = page.getByTestId("tw-technical-evidence-trend");
    const evidenceDisclosure = page.getByTestId(
      "tw-technical-evidence-disclosure"
    );
    await expect(evidenceDisclosure).not.toHaveAttribute("open", "");
    await expect(trendEvidence).not.toHaveAttribute("open", "");
    await page.getByTestId("tw-signal-chip-structure").click();
    await expect(evidenceDisclosure).toHaveAttribute("open", "");
    await expect(trendEvidence).toHaveAttribute("open", "");
    await expect(trendEvidence).toContainText("ADX 30.09");

    const technicalContext = page.getByTestId("tw-technical-context");
    await expect(technicalContext).not.toHaveAttribute("open", "");
    const dataPanel = page.getByTestId("tw-stock-detail-data-panel");
    const institutionalTab = dataPanel.locator('[data-data-tab="institutional"]');
    await page.getByTestId("tw-signal-chip-institutional").click();
    await expect(technicalContext).not.toHaveAttribute("open", "");
    await expect(institutionalTab).toHaveClass(/omi-data-tab-active/);
    await expect(institutionalTab).toBeFocused();

    const chipTab = dataPanel.locator('[data-data-tab="chips"]');
    await page.getByTestId("tw-signal-chip-margin").click();
    await expect(chipTab).toHaveClass(/omi-data-tab-active/);
    await expect(chipTab).toBeFocused();

    const revenueTab = dataPanel.locator('[data-data-tab="revenue"]');
    await page.getByTestId("tw-signal-chip-revenue").click();
    await expect(revenueTab).toHaveClass(/omi-data-tab-active/);
    await expect(revenueTab).toBeFocused();

    await page.getByTestId("tw-signal-chip-overnight").click();
    await expect(technicalContext).toHaveAttribute("open", "");
    await expect(technicalContext).toContainText("法人籌碼");
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan earnings keeps guidance in a centered contract dialog", async ({ page }) => {
    const financialRows = [
      [2025, 1, "2025Q1", 13.95],
      [2025, 2, "2025Q2", 29.31],
      [2025, 3, "2025Q3", 46.75],
      [2025, 4, "2025Q4", 66.26],
      [2026, 1, "2026Q1", 22.08],
    ].map(([fiscalYear, quarter, period, eps], index) => ({
      id: index + 1,
      source_id: 1,
      raw_result_id: index + 1,
      report_date: `${fiscalYear}-${
        ({ 1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31" } as const)[
          Number(quarter) as 1 | 2 | 3 | 4
        ]
      }`,
      released_at: null,
      filed_at: null,
      fiscal_year: fiscalYear,
      quarter,
      period,
      stock_id: "2330",
      stock_name: "台積電",
      market: "TWSE",
      revenue: null,
      gross_profit: null,
      operating_income: null,
      net_income: null,
      net_income_attributable_parent: null,
      eps,
      total_assets: null,
      total_equity: null,
      parent_equity: null,
      book_value_per_share: null,
      roe: null,
      roa: null,
      period_scope: Number(quarter) === 4 ? "annual" : "ytd",
      months_covered: Number(quarter) * 3,
      flow_semantics: "source_reported",
      eps_semantics: "source_reported_ytd_or_annual",
      raw_eps: eps,
      single_quarter_eps: null,
      adjusted_eps_ytd: eps,
      ttm_eps: null,
      source_restated_status: "official",
      share_basis_status: "normalized",
      date_semantics_status: "valid",
      normalization_status: "ready",
      valuation_status: "ready",
      decision_usable: true,
      normalization_warnings: [],
      created_at: "2026-05-15T13:30:00+08:00",
      updated_at: "2026-05-15T13:30:00+08:00",
    }));
    const singleQuarterValues = [13.95, 15.36, 17.44, 19.51, 22.08];
    const normalizedFacts = financialRows.map((row, index) => ({
      source_fact_id: `2330-${row.period}`,
      period: row.period,
      period_scope: row.period_scope,
      period_end: row.report_date,
      metric_code: "basic_eps",
      normalized_value: row.eps,
      normalized_unit: "TWD_per_share",
      adjustment_factor: 1,
      comparison_basis_id: "2330-official-presentation-basis-through-2026Q1",
      normalization_status: "unchanged",
      normalization_version: "tw-financial-normalization-v1",
      normalization_mode: "current_comparable",
      decision_usable: true,
      action_ids: [],
      issue_codes: [],
      known_at: "2026-05-15T13:30:00+08:00",
      singleQuarterValue: singleQuarterValues[index],
    }));

    await mockOmiApi(page, {
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/financials/2330/history")) {
          return { body: financialRows };
        }
        if (path.endsWith("/market/financials/2330/contract")) {
          return {
            body: {
              contract_version: "omi.financial.v1",
              target: { market: "TW", stock_id: "2330" },
              as_of: "2026-08-07T13:30:00+08:00",
              mode: "current_comparable",
              as_reported: { status: "available" },
              normalized: {
                status: "ready",
                facts: normalizedFacts.map((fact) =>
                  Object.fromEntries(
                    Object.entries(fact).filter(([key]) => key !== "singleQuarterValue")
                  )
                ),
                comparison_basis_id:
                  "2330-official-presentation-basis-through-2026Q1",
                normalization_version: "tw-financial-normalization-v1",
              },
              derived: {
                status: "ready",
                single_quarter_eps: normalizedFacts.map((fact) => ({
                  metric_code: "basic_eps",
                  period: fact.period,
                  period_end: fact.period_end,
                  value: fact.singleQuarterValue,
                  unit: "TWD_per_share",
                  status: "ready",
                  comparison_basis_id: fact.comparison_basis_id,
                  normalization_version: fact.normalization_version,
                  input_fact_ids: [fact.source_fact_id],
                  action_ids: [],
                  issue_codes: [],
                  known_at: fact.known_at,
                })),
                annual_reconciliations: [],
                ttm_eps: 74.39,
                ttm_eps_exact: "74.39",
                ttm_eps_status: "ready",
                ttm_periods: ["2025Q2", "2025Q3", "2025Q4", "2026Q1"],
              },
              valuation: {
                status: "ready",
                pe_ttm: 31.86,
                pe_ttm_exact: "31.86",
                price: 2370,
                price_as_of: "2026-08-07T13:30:00+08:00",
                price_basis: "latest_completed_daily_close:market_daily_price",
                price_resolution_status: "ready",
                expected_price_trade_date: "2026-08-07",
                price_trade_date: "2026-08-07",
                price_source: "TWSE OpenAPI Daily Trading",
                decision_usable: true,
              },
              basis_assessment: null,
              quality: {
                freshness: "current",
                continuity: "complete",
                semantic_validity: "valid",
                decision_usable: true,
                issues: [],
                revenue_continuity: {
                  status: "complete",
                  missing_periods: [],
                  duplicate_periods: [],
                  decision_usable: true,
                  issues: [],
                },
              },
              source_refs: [
                {
                  type: "table",
                  name: "tw_financial_normalized_fact",
                  source_name: "MOPS official filings",
                  source_reliability: "official",
                  filing_id: "2330-2026Q1",
                },
                {
                  type: "table",
                  name: "market_daily_price",
                  source_name: "TWSE OpenAPI Daily Trading",
                  source_reliability: "official",
                  raw_result_id: 2370,
                },
              ],
            },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    const dataPanel = page.getByTestId("tw-stock-detail-data-panel");
    const earningsTab = dataPanel.locator('[data-data-tab="earnings"]');
    await earningsTab.click();
    await expect(earningsTab).toHaveClass(/omi-data-tab-active/);
    await expect(page.getByTestId("financial-normalized-summary")).toBeVisible();
    await expect(page.getByTestId("earnings-data-guide-trigger")).toBeVisible();
    await expect(
      page.getByText("EPS 為來源揭露的年初至今累計或全年值")
    ).toHaveCount(0);

    await page.getByTestId("earnings-data-guide-trigger").click();
    const dialog = page.getByTestId("earnings-data-guide-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("盈餘資料說明");
    await expect(dialog).toContainText("可進行同基準比較");
    await expect(dialog).toContainText(
      "EPS 為來源揭露的年初至今累計或全年值"
    );
    await expect(dialog).toContainText("2330-official-presentation-basis-through-2026Q1");
    await expect(dialog).toContainText("TWSE OpenAPI Daily Trading");

    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId("earnings-data-guide-trigger")).toBeFocused();
  });

  test("Taiwan professional chart syncs local drawings and preserves clear undo history", async ({
    page,
  }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "omi:tw:chart-drawings:v1:2330:daily",
        JSON.stringify([
          {
            id: "fixture-horizontal",
            type: "horizontal",
            points: [{ time: "2026-06-15", price: 1_010 }],
            color: "#f4f4f5",
            createdAt: "2026-06-15T09:30:00+08:00",
          },
        ])
      );
    });
    await mockOmiApi(page, { apiRequests });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    const stockDetail = page.getByTestId("stock-detail-panel");
    await expect(stockDetail).toHaveAttribute("data-chart-load-state", "success");
    await expect(page.getByTestId("stock-detail-expand")).toBeEnabled();
    await page.getByTestId("stock-detail-expand").click();
    await expect(page.getByTestId("professional-chart-panel")).toBeVisible();

    const drawingWrites = () =>
      apiRequests.filter(
        (request) =>
          request.method === "PUT" && request.path.includes("/market/chart-drawings/")
      );
    await expect.poll(() => drawingWrites().length).toBe(1);
    expect((drawingWrites()[0].body as { drawings: unknown[] }).drawings).toHaveLength(1);

    page.once("dialog", (dialog) => dialog.accept());
    await page.getByTestId("chart-drawing-clear").click();
    await expect.poll(() => drawingWrites().length).toBe(2);
    expect((drawingWrites()[1].body as { drawings: unknown[] }).drawings).toHaveLength(0);

    await expect(page.getByTestId("chart-drawing-undo")).toBeEnabled();
    await page.getByTestId("chart-drawing-undo").click();
    await expect.poll(() => drawingWrites().length).toBe(3);
    expect((drawingWrites()[2].body as { drawings: unknown[] }).drawings).toHaveLength(1);
  });

  test("Taiwan professional chart creates and undoes a horizontal drawing", async ({ page }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    await mockOmiApi(page, { apiRequests });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    await page.getByTestId("stock-detail-expand").click();

    const chart = page.getByTestId("lightweight-kline-chart");
    const overlay = page.getByTestId("lightweight-chart-overlay");
    await expect(chart).toHaveAttribute("data-drawing-count", "0");
    await expect(overlay).toBeVisible();

    const overlayBox = await overlay.boundingBox();
    expect(overlayBox?.width ?? 0).toBeGreaterThan(300);
    expect(overlayBox?.height ?? 0).toBeGreaterThan(300);

    await page.getByRole("button", { name: "水平", exact: true }).click();
    await expect(chart).toHaveAttribute("data-drawing-tool", "horizontal");
    await overlay.click({
      position: {
        x: Math.round((overlayBox?.width ?? 600) * 0.45),
        y: Math.round((overlayBox?.height ?? 600) * 0.42),
      },
    });
    await expect(chart).toHaveAttribute("data-drawing-count", "1");

    const drawingWrites = () =>
      apiRequests.filter(
        (request) =>
          request.method === "PUT" && request.path.includes("/market/chart-drawings/")
      );
    await expect.poll(() => drawingWrites().length).toBe(1);
    expect((drawingWrites()[0].body as { drawings: unknown[] }).drawings).toHaveLength(1);

    await page.getByTestId("chart-drawing-undo").click();
    await expect(chart).toHaveAttribute("data-drawing-count", "0");
    await expect.poll(() => drawingWrites().length).toBe(2);
    expect((drawingWrites()[1].body as { drawings: unknown[] }).drawings).toHaveLength(0);
  });

  test("Taiwan professional chart removes and restores an active technical indicator", async ({
    page,
  }) => {
    await mockOmiApi(page);
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    await page.getByTestId("stock-detail-expand").click();

    const chart = page.getByTestId("lightweight-kline-chart");
    const activeIndicators = async () =>
      (await chart.getAttribute("data-active-indicators"))?.split(",") ?? [];
    expect(await activeIndicators()).toContain("ma");

    await page.getByTestId("chart-indicator-menu-toggle").click();
    const movingAverageToggle = page.locator('[data-indicator-option="ma"]');
    await expect(movingAverageToggle).toBeChecked();

    await movingAverageToggle.uncheck();
    await expect(movingAverageToggle).not.toBeChecked();
    await expect.poll(async () => (await activeIndicators()).includes("ma")).toBe(false);

    await movingAverageToggle.check();
    await expect(movingAverageToggle).toBeChecked();
    await expect.poll(async () => (await activeIndicators()).includes("ma")).toBe(true);
  });

  test("Taiwan K-line toggles unified corporate event markers in overview and professional mode", async ({
    page,
  }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    await mockOmiApi(page, {
      apiRequests,
      apiResponder: ({ path }) =>
        path.endsWith("/market/tw-corporate-events/history/2330")
          ? { body: corporateEventHistoryResponse("2330") }
          : null,
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    await page.getByTestId("chart-indicator-menu-toggle").click();

    const corporateEventToggle = page.locator(
      '[data-indicator-option="event:corporate_events"]'
    );
    await expect(page.locator('[data-indicator-option^="event:"]')).toHaveCount(1);
    await expect(corporateEventToggle).not.toBeChecked();
    await corporateEventToggle.check();
    await expect(
      page.locator('[data-chart-event-marker="ex_dividend"]').first()
    ).toBeVisible();
    await expect(
      page.locator('[data-chart-event-marker="financial_report"]').first()
    ).toBeVisible();
    await expect(
      page.locator('[data-chart-event-marker="investor_conference"]').first()
    ).toBeVisible();
    const markerGeometry = async () =>
      page.locator('[data-chart-event-marker]').evaluateAll((groups) =>
        groups.map((group) => {
          const line = group.querySelector("line");
          const rect = group.querySelector("rect");

          return {
            anchorY: Number(line?.getAttribute("y1")),
            connectorY: Number(line?.getAttribute("y2")),
            height: Number(rect?.getAttribute("height")),
            width: Number(rect?.getAttribute("width")),
            x: Number(rect?.getAttribute("x")),
            y: Number(rect?.getAttribute("y")),
          };
        })
      );
    const expectCompactNonOverlappingMarkers = (
      markers: Awaited<ReturnType<typeof markerGeometry>>
    ) => {
      expect(markers).toHaveLength(3);
      expect(markers.every((marker) => Math.abs(marker.anchorY - marker.connectorY) < 120))
        .toBe(true);

      for (let leftIndex = 0; leftIndex < markers.length; leftIndex += 1) {
        for (let rightIndex = leftIndex + 1; rightIndex < markers.length; rightIndex += 1) {
          const left = markers[leftIndex];
          const right = markers[rightIndex];
          const overlaps =
            left.x < right.x + right.width &&
            left.x + left.width > right.x &&
            left.y < right.y + right.height &&
            left.y + left.height > right.y;
          expect(overlaps).toBe(false);
        }
      }
    };
    expectCompactNonOverlappingMarkers(await markerGeometry());

    await page.getByTestId("stock-detail-expand").click();
    const professionalChart = page.getByTestId("lightweight-kline-chart");
    await expect(professionalChart).toHaveAttribute("data-event-marker-count", "3");
    await expect(
      page.locator('[data-chart-event-marker="ex_dividend"]').first()
    ).toBeVisible();
    expectCompactNonOverlappingMarkers(await markerGeometry());

    await page.getByTestId("chart-indicator-menu-toggle").click();
    await corporateEventToggle.uncheck();
    await expect(professionalChart).toHaveAttribute("data-event-marker-count", "0");
    expect(
      apiRequests.filter((request) =>
        request.path.endsWith("/market/tw-corporate-events/history/2330")
      )
    ).toHaveLength(1);
  });

  test("Taiwan professional chart safely switches between intraday and duplicate daily timestamps", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    const duplicateDailyPoints = [
      {
        time: "2026-07-16",
        open: 1_000,
        high: 1_010,
        low: 995,
        close: 1_005,
        volume: 20_000,
        trade_value: 20_100_000,
        transaction_count: 1_000,
      },
      {
        time: "2026-07-17",
        open: 1_005,
        high: 1_020,
        low: 1_000,
        close: 1_015,
        volume: 21_000,
        trade_value: 21_315_000,
        transaction_count: 1_050,
      },
      {
        time: "2026-07-17T13:30:00+08:00",
        open: 1_006,
        high: 1_025,
        low: 1_002,
        close: 1_020,
        volume: 22_000,
        trade_value: 22_440_000,
        transaction_count: 1_100,
      },
    ];

    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      apiResponder: ({ path, url }) => {
        if (path.endsWith("/market/ohlc/2330")) {
          return {
            body: {
              ...stockOhlcResponse("2330"),
              from_date: "2026-07-16",
              to_date: "2026-07-17",
              point_count: 180,
              points: duplicateDailyPoints,
            },
          };
        }

        if (path.endsWith("/market/intraday/2330/history")) {
          const points = [
            {
              time: "2026-07-17T09:00:00",
              open: 1_005,
              high: 1_008,
              low: 1_004,
              close: 1_007,
              volume: 1_000,
            },
            {
              time: "2026-07-17T09:01:00",
              open: 1_007,
              high: 1_010,
              low: 1_006,
              close: 1_009,
              volume: 1_200,
            },
          ];

          return {
            body: {
              stock_id: "2330",
              symbol: "2330",
              interval: url.searchParams.get("interval") ?? "1m",
              range: "auto",
              provider: "playwright.fixture",
              source: "playwright.fixture",
              from_time: points[0].time,
              to_time: points[points.length - 1].time,
              point_count: points.length,
              cached_count: points.length,
              refreshed_count: 0,
              points,
            },
          };
        }

        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    await page.getByTestId("stock-detail-expand").click();

    const chart = page.getByTestId("lightweight-kline-chart");
    await expect(chart).toHaveAttribute("data-time-mode", "date");
    await expect(chart).toHaveAttribute("data-source-point-count", "3");
    await expect(chart).toHaveAttribute("data-chart-point-count", "2");

    await page.getByRole("button", { name: "1分", exact: true }).click();
    await expect(chart).toHaveAttribute("data-time-mode", "intraday");
    await expect(chart).toHaveAttribute("data-source-point-count", "2");
    await expect(chart).toHaveAttribute("data-chart-point-count", "2");

    await page.getByRole("button", { name: "日K", exact: true }).click();
    await expect(chart).toHaveAttribute("data-time-mode", "date");
    await expect(chart).toHaveAttribute("data-source-point-count", "3");
    await expect(chart).toHaveAttribute("data-chart-point-count", "2");
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan chart reads stay pure when cached history is short", async ({
    page,
  }) => {
    let backfillRequested = false;
    const fullOhlc = stockOhlcResponse("2330");
    const initialPoints = fullOhlc.points.slice(-1);
    const backfillJob = {
      ...completedRefreshJob(),
      id: 501,
      job_type: "market.twse_daily_price_backfill",
      target: "2330",
      progress_current: 1,
      progress_total: 1,
      message: "Taiwan daily history backfill completed.",
    };

    await mockOmiApi(page, {
      apiResponder: ({ method, path }) => {
        if (method === "GET" && path.endsWith("/market/ohlc/2330")) {
          return {
            body: backfillRequested
              ? fullOhlc
              : {
                  ...fullOhlc,
                  from_date: initialPoints[0]?.time,
                  to_date: initialPoints[0]?.time,
                  point_count: initialPoints.length,
                  points: initialPoints,
                },
          };
        }
        if (method === "POST" && path.endsWith("/market/backfill/twse/2330")) {
          backfillRequested = true;
          return { body: backfillJob };
        }
        if (method === "GET" && path.endsWith("/jobs/501")) {
          return { body: backfillJob };
        }
        if (method === "GET" && path.endsWith("/jobs")) {
          return { body: backfillRequested ? [backfillJob] : [] };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    const detailPanel = page.getByTestId("stock-detail-panel");
    await expect(detailPanel).toHaveAttribute("data-chart-load-state", "success");
    expect(backfillRequested).toBe(false);
    await expect(detailPanel).not.toContainText("詳見左側更新狀態");
    await expect(detailPanel).not.toContainText("日K：補齊");
  });

  test("Taiwan professional chart keeps the last drawing deleted while remote sync is stale", async ({
    page,
  }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    let remoteDrawings: unknown[] = [];
    await mockOmiApi(page, {
      apiRequests,
      apiResponder: ({ method, path }) =>
        method === "GET" && path.includes("/market/chart-drawings/")
          ? {
              body: {
                id: 1,
                market: "TW",
                symbol: "2330",
                timeframe: "daily",
                label: "台積電",
                time_mode: "date",
                selected_drawing_id: null,
                drawing_count: remoteDrawings.length,
                drawings: remoteDrawings,
                summary: null,
                source: "playwright-stale-snapshot",
                created_at: "2026-06-15T09:30:00+08:00",
                updated_at: "2026-06-15T09:30:00+08:00",
              },
            }
          : null,
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    await page.getByTestId("stock-detail-expand").click();

    const chart = page.getByTestId("lightweight-kline-chart");
    const overlay = page.getByTestId("lightweight-chart-overlay");
    await expect(chart).toHaveAttribute("data-drawing-count", "0");
    await expect.poll(
      () =>
        apiRequests.filter(
          (request) =>
            request.method === "GET" && request.path.includes("/market/chart-drawings/")
        ).length
    ).toBe(1);

    const overlayBox = await overlay.boundingBox();
    expect(overlayBox).not.toBeNull();
    await page.locator('[data-drawing-tool-option="riskReward"]').click();
    await expect(chart).toHaveAttribute("data-drawing-tool", "riskReward");
    await page.mouse.move(
      (overlayBox?.x ?? 0) + (overlayBox?.width ?? 600) * 0.48,
      (overlayBox?.y ?? 0) + (overlayBox?.height ?? 600) * 0.42
    );
    await page.mouse.down();
    await expect(chart).toHaveAttribute("data-drawing-draft", "active");
    await page.mouse.move(
      (overlayBox?.x ?? 0) + (overlayBox?.width ?? 600) * 0.64,
      (overlayBox?.y ?? 0) + (overlayBox?.height ?? 600) * 0.42,
      { steps: 6 }
    );
    await page.mouse.up();
    await expect(chart).toHaveAttribute("data-drawing-count", "1");

    const drawingWrites = () =>
      apiRequests.filter(
        (request) =>
          request.method === "PUT" && request.path.includes("/market/chart-drawings/")
      );
    await expect.poll(() => drawingWrites().length).toBe(1);
    remoteDrawings = (drawingWrites()[0].body as { drawings: unknown[] }).drawings;
    expect(remoteDrawings).toHaveLength(1);

    await expect(page.getByTestId("chart-drawing-delete")).toBeEnabled();
    await page.getByTestId("chart-drawing-delete").click();
    await expect(chart).toHaveAttribute("data-drawing-count", "0");
    await page.waitForTimeout(1_000);
    await expect(chart).toHaveAttribute("data-drawing-count", "0");
    await expect.poll(() => drawingWrites().length).toBe(2);
    expect((drawingWrites()[1].body as { drawings: unknown[] }).drawings).toHaveLength(0);
  });

  test("Taiwan professional Fib follows chart panning and price scaling", async ({
    page,
  }) => {
    await mockOmiApi(page);
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    await page.getByTestId("stock-detail-expand").click();

    const chart = page.getByTestId("lightweight-kline-chart");
    const overlay = page.getByTestId("lightweight-chart-overlay");
    const overlayBox = await overlay.boundingBox();
    expect(overlayBox).not.toBeNull();

    await page.locator('[data-drawing-tool-option="fibonacci"]').click();
    await overlay.click({
      position: {
        x: Math.round((overlayBox?.width ?? 600) * 0.28),
        y: Math.round((overlayBox?.height ?? 600) * 0.3),
      },
    });
    await overlay.click({
      position: {
        x: Math.round((overlayBox?.width ?? 600) * 0.66),
        y: Math.round((overlayBox?.height ?? 600) * 0.62),
      },
    });
    await expect(chart).toHaveAttribute("data-drawing-count", "1");

    const fibonacci = overlay.locator('[data-drawing-type="fibonacci"]');
    await expect(fibonacci).toBeVisible();
    const fibonacciLeft = Number(await fibonacci.getAttribute("data-fibonacci-left"));
    const fibonacciRight = Number(await fibonacci.getAttribute("data-fibonacci-right"));
    expect(fibonacciLeft).toBeGreaterThan(0);
    expect(fibonacciRight).toBeLessThan(overlayBox?.width ?? 600);
    expect(fibonacciRight - fibonacciLeft).toBeGreaterThan(100);

    const fibonacciLineXs = await fibonacci.locator("line").evaluateAll((lines) =>
      lines.map((line) => ({
        x1: Number(line.getAttribute("x1")),
        x2: Number(line.getAttribute("x2")),
      }))
    );
    expect(fibonacciLineXs).toHaveLength(7);
    fibonacciLineXs.forEach(({ x1, x2 }) => {
      expect(x1).toBeCloseTo(fibonacciLeft, 1);
      expect(x2).toBeCloseTo(fibonacciRight, 1);
    });

    await page.locator('[data-drawing-tool-option="cursor"]').click();
    await page.mouse.move(
      (overlayBox?.x ?? 0) + (overlayBox?.width ?? 600) * 0.65,
      (overlayBox?.y ?? 0) + (overlayBox?.height ?? 600) * 0.55
    );
    await page.mouse.down();
    await page.mouse.move(
      (overlayBox?.x ?? 0) + (overlayBox?.width ?? 600) * 0.78,
      (overlayBox?.y ?? 0) + (overlayBox?.height ?? 600) * 0.55,
      { steps: 8 }
    );
    await page.mouse.up();

    await expect.poll(async () => {
      const nextLeft = Number(await fibonacci.getAttribute("data-fibonacci-left"));
      return Math.abs(nextLeft - fibonacciLeft);
    }).toBeGreaterThan(5);

    const fibonacciLineYsBeforePriceDrag = await fibonacci
      .locator("line")
      .evaluateAll((lines) => lines.map((line) => Number(line.getAttribute("y1"))));
    await page.mouse.move(
      (overlayBox?.x ?? 0) + (overlayBox?.width ?? 600) - 18,
      (overlayBox?.y ?? 0) + (overlayBox?.height ?? 600) * 0.3
    );
    await page.mouse.down();
    await page.mouse.move(
      (overlayBox?.x ?? 0) + (overlayBox?.width ?? 600) - 18,
      (overlayBox?.y ?? 0) + (overlayBox?.height ?? 600) * 0.44,
      { steps: 8 }
    );
    await page.mouse.up();

    await expect.poll(async () => {
      const nextLineYs = await fibonacci
        .locator("line")
        .evaluateAll((lines) => lines.map((line) => Number(line.getAttribute("y1"))));
      return Math.max(
        ...nextLineYs.map((nextY, index) =>
          Math.abs(nextY - fibonacciLineYsBeforePriceDrag[index])
        )
      );
    }).toBeGreaterThan(5);
  });

  test("Taiwan branch data tab reuses each days cache key", async ({ page }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    await mockOmiApi(page, { apiRequests });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    await page.locator('[data-data-tab="branch"]').click();

    const branchRequests = () =>
      apiRequests.filter((request) =>
        request.path.includes("/market/broker-branches/2330/daily")
      );
    await expect.poll(() => branchRequests().length).toBe(1);
    expect(branchRequests()[0].search).toContain("days=1");
    await expect(page.locator('[data-branch-days="5"]')).toBeVisible();

    await page.locator('[data-data-tab="chips"]').click();
    await page.locator('[data-data-tab="branch"]').click();
    await expect(page.locator('[data-branch-days="5"]')).toBeVisible();
    expect(branchRequests()).toHaveLength(1);

    await page.locator('[data-branch-days="5"]').click();
    await expect.poll(() => branchRequests().length).toBe(2);
    expect(branchRequests()[1].search).toContain("days=5");
  });

  test("Taiwan institutional tab lazily loads and displays holding ratios", async ({
    page,
  }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    const institutionalRows = [
      { tradeDate: "2026-06-13", foreignNet: -2_000_000 },
      { tradeDate: "2026-06-15", foreignNet: 3_000_000 },
    ].map(({ tradeDate, foreignNet }, index) => ({
      id: index + 1,
      source_id: 1,
      raw_result_id: index + 1,
      trade_date: tradeDate,
      stock_id: "2330",
      stock_name: "台積電",
      foreign_investor_buy: 10_000_000,
      foreign_investor_sell: 10_000_000 - foreignNet,
      foreign_investor_net: foreignNet,
      foreign_dealer_buy: null,
      foreign_dealer_sell: null,
      foreign_dealer_net: null,
      investment_trust_buy: 2_000_000,
      investment_trust_sell: 1_000_000,
      investment_trust_net: 1_000_000,
      dealer_self_buy: null,
      dealer_self_sell: null,
      dealer_self_net: null,
      dealer_hedge_buy: null,
      dealer_hedge_sell: null,
      dealer_hedge_net: null,
      dealer_buy: 1_000_000,
      dealer_sell: 1_500_000,
      dealer_net: -500_000,
      total_institutional_net: foreignNet + 500_000,
      created_at: `${tradeDate}T14:30:00+08:00`,
      updated_at: `${tradeDate}T14:30:00+08:00`,
    }));
    await mockOmiApi(page, {
      apiRequests,
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/institutional/2330/history")) {
          return { body: institutionalRows };
        }
        if (path.endsWith("/market/institutional/2330/holding-ratios")) {
          return {
            body: {
              stock_id: "2330",
              stock_name: "台積電",
              trade_date: "2026-06-15",
              foreign_investor_ratio: 69.33,
              investment_trust_ratio: 3.61,
              dealer_ratio: 1.38,
              source_name: "nStock",
              source_url: "https://www.nstock.tw/stock_info?status=8&stock_id=2330",
              fetched_at: "2026-06-15T14:30:00Z",
              history: [
                {
                  trade_date: "2026-06-13",
                  foreign_investor_ratio: 69.2,
                  investment_trust_ratio: 3.55,
                  dealer_ratio: 1.31,
                },
                {
                  trade_date: "2026-06-15",
                  foreign_investor_ratio: 69.33,
                  investment_trust_ratio: 3.61,
                  dealer_ratio: 1.38,
                },
              ],
            },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute(
      "data-chart-load-state",
      "success"
    );
    const holdingRatioRequests = () =>
      apiRequests.filter((request) =>
        request.path.endsWith("/market/institutional/2330/holding-ratios")
      );
    expect(holdingRatioRequests()).toHaveLength(0);

    await page.locator('[data-data-tab="institutional"]').click();
    await expect.poll(() => holdingRatioRequests().length).toBe(1);
    await expect(page.getByText("69.33%", { exact: true })).toBeVisible();
    await expect(page.getByText("3.61%", { exact: true })).toBeVisible();
    await expect(page.getByText("1.38%", { exact: true })).toBeVisible();
    await expect(page.getByText(/實際持股比例 · nStock/)).toBeVisible();

    await page.locator('[data-data-tab="chips"]').click();
    await page.locator('[data-data-tab="institutional"]').click();
    await expect(page.getByText("69.33%", { exact: true })).toBeVisible();
    expect(holdingRatioRequests()).toHaveLength(1);
  });

  test("Taiwan watchlist exposes market-wide foreign flow ranking", async ({ page }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    const rankedRows = seededTaiwanRankingRows().map((row, index) => ({
      ...row,
      rank: index + 1,
      market_rank: index === 0 ? 36 : 204,
      rank_value: index === 0 ? 5_332_894 : -1_250_000,
      rank_trade_date: "2026-07-17",
    }));
    await mockOmiApi(page, {
      apiRequests,
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      apiResponder: ({ path, url }) => {
        if (
          /\/(?:wl|watchlists)\/groups\/7\/rankings\/latest$/.test(path) &&
          url.searchParams.get("rank_by") === "foreign_net"
        ) {
          return {
            body: {
              group_id: 7,
              include_children: true,
              rank_by: "foreign_net",
              sort_order: "desc",
              rank_scope: "tw_market",
              rank_trade_date: "2026-07-17",
              rank_universe_count: 1846,
              requested_stock_count: 2,
              ranked_count: 2,
              no_data_count: 0,
              error_count: 0,
              trade_date: "2026-06-15",
              target_trade_date: "2026-06-15",
              is_current: true,
              current_stock_count: 2,
              stale_stock_count: 0,
              results: rankedRows,
            },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    await page.locator('[data-watchlist-group-id="7"]').click();
    await expect(page).toHaveURL(/group_id=7/);

    const rankSelect = page.locator('select:has(option[value="foreign_net"])');
    await rankSelect.selectOption("foreign_net");
    await expect
      .poll(
        () =>
          apiRequests.filter(
            (request) =>
              /\/(?:wl|watchlists)\/groups\/7\/rankings\/latest$/.test(
                request.path
              ) &&
              request.search.includes("rank_by=foreign_net")
          ).length
      )
      .toBe(1);

    await expect(page.getByText(/全市場 外資買賣超 排名/)).toBeVisible();
    await expect(page.getByText(/有效母體 1846 檔/)).toBeVisible();
    const firstRow = page.locator('[data-ranking-stock-id="2330"]');
    await expect(firstRow).toContainText("#36");
    await expect(firstRow).toContainText("5,333");
    await expect(page.getByText("外資超(張)", { exact: true })).toBeVisible();
  });

  test("Taiwan stale ranking keeps the selected sort order visible", async ({ page }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    const sortedRows = seededTaiwanRankingRows()
      .slice()
      .reverse()
      .map((row, index) => ({ ...row, rank: index + 1 }));
    await page.clock.setFixedTime(new Date("2026-07-21T10:00:00Z"));
    await mockOmiApi(page, {
      apiRequests,
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      apiResponder: ({ path, url }) => {
        if (
          /\/(?:wl|watchlists)\/groups\/7\/rankings\/latest$/.test(path) &&
          url.searchParams.get("rank_by") === "score"
        ) {
          return {
            body: {
              group_id: 7,
              include_children: true,
              rank_by: "score",
              sort_order: "desc",
              requested_stock_count: 2,
              ranked_count: 2,
              no_data_count: 0,
              error_count: 0,
              trade_date: "2026-06-14",
              target_trade_date: "2026-06-15",
              is_current: false,
              current_stock_count: 0,
              stale_stock_count: 2,
              results: sortedRows,
            },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&stock_id=2330", { waitUntil: "domcontentloaded" });

    await page.locator('[data-watchlist-group-id="7"]').click();
    const rankSelect = page.locator('select:has(option[value="score"])');
    await rankSelect.selectOption("score");

    await expect(page.locator("[data-ranking-stock-id]").first()).toHaveAttribute(
      "data-ranking-stock-id",
      "2303"
    );
    await expect(rankSelect).toHaveValue("score");
    await expect(page.getByText(/待補 2\/2 檔.*2026-06-15/)).toBeVisible();

    const refreshRequests = () =>
      apiRequests.filter(
        (request) =>
          request.method === "POST" &&
          /\/wl\/groups\/7\/refresh-latest$/.test(request.path)
      );
    await expect.poll(() => refreshRequests().length).toBe(1);
    const refreshParams = new URLSearchParams(refreshRequests()[0].search);
    expect(refreshParams.get("include_today")).toBe("false");
    expect(refreshParams.get("include_children")).toBe("true");
    expect(refreshParams.get("enabled_only")).toBe("true");
  });

  test("Taiwan ranking refreshes once when the daily price release becomes ready", async ({
    page,
  }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    let dailyPriceReleased = false;

    await page.clock.install({
      time: new Date("2026-07-21T15:14:00+08:00"),
    });
    await mockOmiApi(page, {
      apiRequests,
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      apiResponder: ({ path }) =>
        path.includes("/market/calendar-status")
          ? { body: taiwanDailyPriceReleaseStatus(dailyPriceReleased) }
          : null,
    });
    await page.goto("/?market=tw&group_id=7&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });
    await page.clock.runFor(1_000);

    const refreshRequests = () =>
      apiRequests.filter(
        (request) =>
          request.method === "POST" &&
          /\/wl\/groups\/7\/refresh-latest$/.test(request.path)
      );
    await expect(page.locator("[data-ranking-stock-id]").first()).toBeVisible();
    await expect
      .poll(
        () =>
          apiRequests.filter((request) =>
            request.path.includes("/market/calendar-status")
          ).length
      )
      .toBeGreaterThan(0);
    expect(refreshRequests()).toHaveLength(0);

    dailyPriceReleased = true;
    await page.clock.runFor(61_000);

    await expect.poll(() => refreshRequests().length).toBe(1);
    const refreshParams = new URLSearchParams(refreshRequests()[0].search);
    expect(refreshParams.get("include_today")).toBe("true");
  });

  test("Taiwan detail reads do not trigger implicit backfill or companion reloads", async ({
    page,
  }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    let detailBackfillCompleted = false;

    await mockOmiApi(page, {
      apiRequests,
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      apiResponder: ({ method, path }) => {
        if (path.endsWith("/market/ohlc/2330")) {
          const response = stockOhlcResponse("2330");
          if (!detailBackfillCompleted) {
            const points = response.points.slice(0, 2);
            return {
              body: {
                ...response,
                from_date: points[0].time,
                to_date: points[points.length - 1].time,
                point_count: points.length,
                points,
              },
            };
          }
          return { body: response };
        }

        if (method === "POST" && path.endsWith("/market/backfill/twse/2330")) {
          detailBackfillCompleted = true;
          return { body: completedRefreshJob() };
        }

        return null;
      },
    });
    await page.goto("/?market=tw&group_id=7&stock_id=2330", {
      waitUntil: "domcontentloaded",
    });

    const parentRankingRequests = () =>
      apiRequests.filter((request) =>
        /\/(?:wl|watchlists)\/groups\/7\/rankings\/latest-batch$/.test(request.path)
      );
    const detailBackfillRequests = () =>
      apiRequests.filter(
        (request) =>
          request.method === "POST" &&
          request.path.endsWith("/market/backfill/twse/2330")
      );
    const uncachedRadarRequests = () =>
      apiRequests.filter(
        (request) =>
          /\/(?:wl|watchlists)\/groups\/7\/radar$/.test(request.path) &&
          new URLSearchParams(request.search).get("prefer_snapshot") === "false"
      );

    await page.locator('[data-watchlist-group-id="7"]').click();
    await expect(page.locator('[data-ranking-stock-id="2330"]')).toBeVisible();
    expect(detailBackfillRequests()).toHaveLength(0);
    expect(parentRankingRequests().length).toBeLessThanOrEqual(1);
    expect(uncachedRadarRequests()).toHaveLength(0);
  });

  test("regional stale refresh can be retried after a failed job", async ({ page }) => {
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    const rankingRows = seededUsRankingRows();
    let refreshAttempt = 0;

    await mockOmiApi(page, {
      apiRequests,
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      usRankingRows: rankingRows,
      regionalRankingResponder: ({ market, url }) =>
        market === "us"
          ? {
              body: {
                ...seededUsRankingResponse(url, rankingRows),
                trade_date: "2026-07-17",
                target_trade_date: "2026-07-20",
                is_current: false,
                current_symbol_count: 0,
                stale_symbol_count: rankingRows.length,
              },
            }
          : null,
      apiResponder: ({ method, path }) => {
        if (
          method === "POST" &&
          /\/us-market\/watchlists\/groups\/\d+\/refresh-daily$/.test(path)
        ) {
          refreshAttempt += 1;
          return {
            body:
              refreshAttempt === 1
                ? {
                    ...completedRefreshJob(),
                    status: "error",
                    message: "Playwright refresh fixture failed.",
                    error_message: "temporary provider failure",
                    result: { status: "error", error_count: 1 },
                  }
                : completedRefreshJob(),
          };
        }
        if (path.endsWith("/jobs/1")) {
          return {
            body:
              refreshAttempt === 1
                ? {
                    ...completedRefreshJob(),
                    status: "error",
                    message: "Playwright refresh fixture failed.",
                    error_message: "temporary provider failure",
                    result: { status: "error", error_count: 1 },
                  }
                : completedRefreshJob(),
          };
        }
        return null;
      },
    });
    await page.goto("/?market=us&group_id=17", { waitUntil: "domcontentloaded" });

    const refreshRequests = () =>
      apiRequests.filter(
        (request) =>
          request.method === "POST" &&
          /\/us-market\/watchlists\/groups\/\d+\/refresh-daily$/.test(request.path)
      );

    await expect.poll(() => refreshRequests().length).toBe(1);
    await page.getByTestId("watchlist-ranking-reload").click();
    await expect.poll(() => refreshRequests().length).toBe(2);
  });

  test("malformed portfolio payload stays contained", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const portfolioResponsePromise = page.waitForResponse((response) =>
      new URL(response.url()).pathname.includes("/portfolio/holdings")
    );
    await mockOmiApi(page, { portfolioHoldingsPayload: { unexpected: true } });
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const portfolioResponse = await portfolioResponsePromise;

    await expect(page.getByRole("heading", { name: "Market Dashboard" })).toBeVisible();
    expect(await portfolioResponse.json()).toEqual({ unexpected: true });
    const sidebar = page.getByRole("complementary").first();
    const statusToggle = sidebar.getByRole("button", { name: /更新狀態/ });
    await expect(page.getByText("持股讀取失敗，詳情請看更新狀態。")).toBeVisible();
    await expect(statusToggle.locator(".omi-job-status-pill-attention")).toContainText("1");
    await expect(page.getByText("持股資料格式錯誤，請重新整理。")).toHaveCount(0);
    await statusToggle.click();
    await expect(sidebar.getByText("持股資料讀取失敗")).toBeVisible();
    await expect(sidebar.getByText("持股資料格式錯誤，請重新整理。")).toBeVisible();
    await expect(page.getByRole("button", { name: "開啟 OMI 即時問答" })).toBeVisible();
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan watchlist ranking preserves nested rows and selection links", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    const group = page.locator('[data-watchlist-group-id="7"]');
    await expect(group).toContainText("科技股");
    await group.click();
    await expect(page).toHaveURL(/group_id=7/);

    const rankingRows = page.locator("[data-ranking-stock-id]");
    const tsmcRow = page.locator('[data-ranking-stock-id="2330"]');
    const umcRow = page.locator('[data-ranking-stock-id="2303"]');
    await expect(rankingRows).toHaveCount(2);
    await expect(tsmcRow).toContainText("2330 台積電");
    await expect(tsmcRow).toContainText("1,015");
    await expect(tsmcRow).toContainText("+1.50%");
    await expect(tsmcRow).toHaveAttribute("href", /group_id=7.*stock_id=2330/);
    await expect(umcRow).toContainText("2303 聯電");
    await expect(page.locator('[data-ranking-stock-id="9999"]')).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });

  test("US watchlist ranking renders the extracted regional panel", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      usRankingRows: seededUsRankingRows(),
    });
    await page.goto("/?market=us", { waitUntil: "domcontentloaded" });

    await page.getByRole("button", { name: "Reload" }).first().click();
    const rankingResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname.endsWith("/us-market/watchlists/ranking")
    );
    await page.getByText("Mega Cap Tech", { exact: true }).first().click();
    await rankingResponse;
    const rankingRows = page.locator("[data-ranking-symbol]");
    const appleRow = page.locator('[data-ranking-symbol="AAPL"]');
    await expect(rankingRows).toHaveCount(2);
    await expect(appleRow).toContainText("AAPL Apple Inc.");
    await expect(appleRow).toContainText("214.5");
    await expect(appleRow).toContainText("+1.90%");
    await expect(appleRow).toHaveAttribute("href", /market=us.*symbol=AAPL/);
    await expect(page.locator('[data-ranking-symbol="MSFT"]')).toContainText(
      "MSFT Microsoft Corp."
    );
    expect(pageErrors).toEqual([]);
  });

  test("US stock selection clears the previous K-line before the next symbol loads", async ({
    page,
  }) => {
    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      usRankingRows: seededUsRankingRows(),
      apiResponder: ({ path }) =>
        path.endsWith("/us-market/ohlc/MSFT")
          ? { body: usOhlcResponse("MSFT"), delayMs: 1_200 }
          : null,
    });
    await page.goto("/?market=us&group_id=17&symbol=AAPL", {
      waitUntil: "domcontentloaded",
    });

    const chartPanel = page.getByTestId("us-stock-kline-panel");
    await expect(chartPanel.getByRole("img")).toBeVisible();

    await page.locator('[data-ranking-symbol="MSFT"]').click();
    await expect(page).toHaveURL(/market=us.*symbol=MSFT/);
    const loadingSurface = chartPanel.locator('.omi-state-surface[aria-busy="true"]');
    await expect(loadingSurface).toBeVisible();
    await expect(chartPanel.getByRole("img")).toHaveCount(0);

    await expect(loadingSurface).toHaveCount(0);
    await expect(chartPanel.getByRole("img")).toBeVisible();
  });

  test("market selection keeps the current cross-market query contract", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      usRankingRows: seededUsRankingRows(),
      jpWatchlistTree: seededJpWatchlistTree(),
      jpWatchlistItems: seededJpWatchlistItems(),
      jpRankingRows: seededJpRankingRows(),
      krWatchlistTree: seededKrWatchlistTree(),
      krWatchlistItems: seededKrWatchlistItems(),
      krRankingRows: seededKrRankingRows(),
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await page.locator('[data-watchlist-group-id="7"]').click();
    const indexButton = page.getByRole("button", { name: /TAIEX 加權指數/ }).first();
    if (!(await indexButton.isVisible())) {
      await page.getByRole("button", { name: "切換加權指數資料夾" }).click();
    }
    await indexButton.click();
    await expect(page).toHaveURL(
      /\?market=tw&group_id=7&stock_id=TAIEX&radar_mode=action$/
    );

    const futuresButton = page.getByRole("button", { name: /台指期/ }).first();
    await futuresButton.click();
    await expect(page).toHaveURL(/\?market=tw&futures=TXF$/);

    await page.getByRole("link", { name: "美股", exact: true }).click();
    await page.getByRole("button", { name: "Reload" }).first().click();
    const usSidebar = page.getByRole("complementary");
    const usGroupLabel = usSidebar.getByText("Mega Cap Tech", { exact: true }).last();
    await usGroupLabel.click();
    const appleButton = page.getByRole("button", { name: /AAPL Apple Inc\./ }).first();
    if (!(await appleButton.isVisible())) {
      await usGroupLabel.locator("..").getByRole("button").click();
    }
    await appleButton.click();
    await expect(page).toHaveURL(/\?market=us&symbol=AAPL$/);

    await page.getByRole("link", { name: "日股", exact: true }).click();
    await page.getByRole("button", { name: "Reload" }).first().click();
    const jpSidebar = page.getByRole("complementary");
    const jpGroupLabel = jpSidebar.getByText("Japan Core", { exact: true }).last();
    await jpGroupLabel.click();
    const toyotaButton = page
      .getByRole("button", { name: /7203\.T Toyota Motor/ })
      .first();
    if (!(await toyotaButton.isVisible())) {
      await jpGroupLabel.locator("..").getByRole("button").click();
    }
    await toyotaButton.click();
    await expect(page).toHaveURL(
      /\?market=jp&group_id=27&jp_symbol=7203\.T$/
    );

    await page.getByRole("link", { name: "韓股", exact: true }).click();
    await expect(page).toHaveURL(/\?market=kr(?:&group_id=\d+)?$/);
    const krMarketEntryUrl = page.url();
    await page.getByRole("button", { name: "Reload" }).first().click();
    const krSidebar = page.getByRole("complementary");
    const krGroupLabel = krSidebar.getByText("Korea Core", { exact: true }).last();
    await krGroupLabel.click();
    const samsungButton = page
      .getByRole("button", { name: /005930\.KS Samsung Electronics/ })
      .first();
    if (!(await samsungButton.isVisible())) {
      await krGroupLabel.locator("..").getByRole("button").click();
    }
    await samsungButton.click();
    await expect(page).toHaveURL(
      /\?market=kr&group_id=37&kr_symbol=005930\.KS$/
    );
    await expect(samsungButton.locator("..")).toHaveClass(/omi-sidebar-selected/);

    await page.goBack();
    await expect(page).toHaveURL(/\?market=kr&group_id=37$/);
    await expect(samsungButton.locator("..")).not.toHaveClass(/omi-sidebar-selected/);

    await page.goBack();
    await expect(page).toHaveURL(krMarketEntryUrl);

    await page.goBack();
    await expect(page).toHaveURL(
      /\?market=jp&group_id=27&jp_symbol=7203\.T$/
    );
    const restoredToyotaButton = page
      .getByRole("button", { name: /7203\.T Toyota Motor/ })
      .first();
    if (!(await restoredToyotaButton.isVisible())) {
      const restoredJpGroupLabel = page
        .getByRole("complementary")
        .getByText("Japan Core", { exact: true })
        .last();
      await restoredJpGroupLabel.locator("..").getByRole("button").click();
    }
    await expect(restoredToyotaButton.locator("..")).toHaveClass(/omi-sidebar-selected/);

    await page.goForward();
    await expect(page).toHaveURL(krMarketEntryUrl);
    await page.goForward();
    await expect(page).toHaveURL(/\?market=kr&group_id=37$/);
    await page.goForward();
    await expect(page).toHaveURL(
      /\?market=kr&group_id=37&kr_symbol=005930\.KS$/
    );
    const restoredSamsungButton = page
      .getByRole("button", { name: /005930\.KS Samsung Electronics/ })
      .first();
    if (!(await restoredSamsungButton.isVisible())) {
      const restoredKrGroupLabel = page
        .getByRole("complementary")
        .getByText("Korea Core", { exact: true })
        .last();
      await restoredKrGroupLabel.locator("..").getByRole("button").click();
    }
    await expect(restoredSamsungButton.locator("..")).toHaveClass(
      /omi-sidebar-selected/
    );
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan selection restores the visible instrument with browser history", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await page.locator('[data-watchlist-group-id="7"]').click();
    const indexButton = page.getByRole("button", { name: /TAIEX/ }).first();
    if (!(await indexButton.isVisible())) {
      await page.getByRole("button", { name: "切換加權指數資料夾" }).click();
    }
    const futuresButton = page.getByRole("button", { name: /TXF/ }).first();

    await indexButton.click();
    await expect(page).toHaveURL(
      /\?market=tw&group_id=7&stock_id=TAIEX&radar_mode=action$/
    );
    await expect(indexButton).toHaveClass(/omi-sidebar-selected/);

    await futuresButton.click();
    await expect(page).toHaveURL(/\?market=tw&futures=TXF$/);
    await expect(futuresButton).toHaveClass(/omi-sidebar-selected/);

    await page.goBack();
    await expect(page).toHaveURL(
      /\?market=tw&group_id=7&stock_id=TAIEX&radar_mode=action$/
    );
    await expect(indexButton).toHaveClass(/omi-sidebar-selected/);

    await page.goForward();
    await expect(page).toHaveURL(/\?market=tw&futures=TXF$/);
    await expect(futuresButton).toHaveClass(/omi-sidebar-selected/);
    expect(pageErrors).toEqual([]);
  });

  test("crypto and resource selections stay inside the crypto route", async ({ page }) => {
    const pageErrors: string[] = [];
    let resourceAutoRefreshRequests = 0;
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page);
    await page.route("**/settings/market-data-subscriptions", async (route) => {
      await fulfillJson(route, {
        kind: "market_data_subscriptions",
        version: "v1",
        source: "playwright.fixture",
        items: [
          {
            key: "currency:twd_to_foreign:TWD-USD",
            market: "resource",
            group: "twd_to_foreign",
            label: "台幣／美元",
            mode: "on_select",
            resources: { quote: true, ohlcv: true },
            intervals: {
              quote_seconds: 60,
              ohlcv_seconds: 300,
              selected_quote_seconds: 5,
              background_quote_seconds: 300,
            },
          },
        ],
      });
    });
    await page.route("**/resource-market/refresh?**", async (route) => {
      resourceAutoRefreshRequests += 1;
      await fulfillJson(route, {
        status: "success",
        resource: "snapshot",
        requested_count: 1,
        refreshed_count: 2,
        skipped_count: 0,
        error_count: 0,
        results: [
          {
            status: "success",
            resource: "quote",
            requested_count: 1,
            refreshed_count: 1,
            skipped_count: 0,
            error_count: 0,
          },
          {
            status: "success",
            resource: "ohlcv",
            interval: "1m",
            requested_count: 1,
            refreshed_count: 1,
            skipped_count: 0,
            error_count: 0,
          },
        ],
      });
    });
    await page.route("**/resource-market/quotes/latest?**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("symbols") !== "TWD-USD") {
        await route.fallback();
        return;
      }

      await fulfillJson(route, [
        {
          id: 1,
          provider: "yahoo_chart",
          exchange: "FX",
          symbol: "TWD-USD",
          provider_symbol: "TWDUSD=X",
          name: "台幣／美元",
          root_folder: "currency",
          group: "twd_to_foreign",
          asset_class: "foreign_exchange",
          base_asset: "TWD",
          quote_asset: "USD",
          instrument_type: "spot",
          contract_key: "spot",
          contract_month: null,
          last_price: 0.031087,
          bid_price: null,
          ask_price: null,
          open_price: 0.03102,
          high_price: 0.031095,
          low_price: 0.030998,
          previous_close: 0.031,
          price_change: 0.000087,
          price_change_pct: 0.280645,
          volume: null,
          open_interest: null,
          event_time: "2026-07-15T11:30:00+08:00",
          source_url: null,
          fetched_at: "2026-07-15T11:30:01+08:00",
          created_at: "2026-07-15T11:30:01+08:00",
          updated_at: "2026-07-15T11:30:01+08:00",
        },
      ]);
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await page.locator('a[href="/?market=crypto"]').click();
    await expect(page).toHaveURL(/\?market=crypto$/);
    const cryptoHistoryLength = await page.evaluate(() => window.history.length);

    await expect(page.getByTestId("crypto-sidebar-workspace-summary")).toContainText(
      "資產庫 9 · 即時 1 · 待更新 8"
    );
    await expect(page.getByTestId("crypto-sidebar-maturity-BTC")).toHaveText("即時");
    await expect(page.getByTestId("crypto-sidebar-maturity-ETH")).toHaveText("待更");
    await expect(page.getByTestId("crypto-sidebar-maturity-BTC")).toBeVisible();
    await expect(page.getByTestId("crypto-sidebar-maturity-ETH")).toBeVisible();
    await expect(page.getByRole("button", { name: "Reload" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "重載" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "刷新核心資料" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "更新報價/K線" })).toHaveCount(0);

    await expect(page.getByTestId("currency-sidebar-group-twd_to_foreign")).toBeVisible();
    await expect(page.getByTestId("currency-sidebar-group-foreign_to_twd")).toBeVisible();
    await expect(page.getByTestId("currency-sidebar-group-foreign_to_foreign")).toBeVisible();
    await expect(page.getByTestId("currency-sidebar-instrument-TWD-JPY")).toBeVisible();
    await expect(page.getByTestId("currency-sidebar-instrument-USD-TWD")).toBeVisible();
    await expect(page.getByTestId("currency-sidebar-instrument-EUR-USD")).toBeVisible();

    const currencyButton = page.getByTestId("currency-sidebar-instrument-TWD-USD");
    await expect(currencyButton).toBeVisible();
    await expect(currencyButton.locator("div").nth(1)).toHaveCSS("font-size", "14px");
    const currencySymbol = "TWD-USD";
    await currencyButton.click();
    await expect(currencyButton).toHaveClass(/omi-sidebar-selected/);
    await expect(
      page.getByRole("heading", { level: 2 }).filter({ hasText: currencySymbol }).first()
    ).toBeVisible();
    await expect(page.getByText("0.031087", { exact: true }).first()).toBeVisible();
    await expect.poll(() => resourceAutoRefreshRequests).toBeGreaterThanOrEqual(1);
    await expect(page).toHaveURL(/\?market=crypto$/);

    const resourceButton = page
      .locator('[data-testid^="resource-sidebar-instrument-"]')
      .first();
    await expect(resourceButton).toBeVisible();
    const resourceTestId = await resourceButton.getAttribute("data-testid");
    expect(resourceTestId).not.toBeNull();
    const resourceSymbol = resourceTestId!.replace("resource-sidebar-instrument-", "");
    await resourceButton.click();
    await expect(resourceButton).toHaveClass(/omi-sidebar-selected/);
    await expect(
      page.getByRole("heading", { level: 2 }).filter({ hasText: resourceSymbol }).first()
    ).toBeVisible();
    await expect(page).toHaveURL(/\?market=crypto$/);
    expect(await page.evaluate(() => window.history.length)).toBe(cryptoHistoryLength);
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan radar mode reload and browser history stay synchronized", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      radarResponder: ({ market, requestNumber, url }) =>
        market === "tw"
          ? {
              body: seededRadarResponse(
                url,
                `${url.searchParams.get("mode") ?? "action"}-request-${requestNumber}`
              ),
            }
          : null,
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    const initialRadarResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return /\/(?:wl|watchlists)\/groups\/7\/radar$/.test(url.pathname) &&
        url.searchParams.get("mode") === "action";
    });
    await page.locator('[data-watchlist-group-id="7"]').click();
    await initialRadarResponse;
    await expect(page.getByTestId("watchlist-radar-result-2330")).toBeVisible();

    const riskRadarResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return /\/(?:wl|watchlists)\/groups\/7\/radar$/.test(url.pathname) &&
        url.searchParams.get("mode") === "risk";
    });
    await page.getByTestId("watchlist-radar-mode-risk").click();
    await riskRadarResponse;
    await expect(page).toHaveURL(/\?market=tw&group_id=7&radar_mode=risk$/);
    await expect(page.getByTestId("watchlist-radar-mode-risk")).toHaveAttribute(
      "aria-disabled",
      "true"
    );

    const reloadResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return /\/(?:wl|watchlists)\/groups\/7\/radar$/.test(url.pathname) &&
        url.searchParams.get("mode") === "risk";
    });
    await page.getByTestId("watchlist-radar-reload").click();
    await reloadResponse;

    const restoredActionResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return /\/(?:wl|watchlists)\/groups\/7\/radar$/.test(url.pathname) &&
        url.searchParams.get("mode") === "action";
    });
    await page.goBack();
    await restoredActionResponse;
    await expect(page).toHaveURL(/\?market=tw&group_id=7&radar_mode=action$/);
    await expect(page.getByTestId("watchlist-radar-mode-action")).toHaveAttribute(
      "aria-disabled",
      "true"
    );

    const restoredRiskResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return /\/(?:wl|watchlists)\/groups\/7\/radar$/.test(url.pathname) &&
        url.searchParams.get("mode") === "risk";
    });
    await page.goForward();
    await restoredRiskResponse;
    await expect(page).toHaveURL(/\?market=tw&group_id=7&radar_mode=risk$/);
    await expect(page.getByTestId("watchlist-radar-mode-risk")).toHaveAttribute(
      "aria-disabled",
      "true"
    );
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan radar can reload after an API error", async ({ page }) => {
    const pageErrors: string[] = [];
    let recoverRadar = false;
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      radarResponder: ({ market, url }) => {
        if (market !== "tw") return null;
        return recoverRadar
          ? { body: seededRadarResponse(url, "radar-recovered") }
          : { body: { detail: "radar fixture failure" }, status: 503 };
      },
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    const failedResponse = page.waitForResponse((response) =>
      /\/(?:wl|watchlists)\/groups\/7\/radar$/.test(
        new URL(response.url()).pathname
      )
    );
    await page.locator('[data-watchlist-group-id="7"]').click();
    expect((await failedResponse).status()).toBe(503);

    recoverRadar = true;
    const recoveredResponse = page.waitForResponse((response) =>
      /\/(?:wl|watchlists)\/groups\/7\/radar$/.test(
        new URL(response.url()).pathname
      )
    );
    await page.getByTestId("watchlist-radar-reload").click();
    await recoveredResponse;
    await expect(page.getByTestId("watchlist-radar-result-2330")).toContainText(
      "radar-recovered"
    );
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan radar uses v2 outcome history without v1 writes", async ({ page }) => {
    const pageErrors: string[] = [];
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    const reconcileJob = {
      ...completedRefreshJob(),
      id: 901,
      job_type: "watchlist.radar_v2.outcome_reconcile",
      target: "group:7",
      result: {
        status: "success",
        finalized_count: 4,
        remaining_due_count: 0,
        error_count: 0,
      },
    };
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      apiRequests,
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      radarResponder: ({ market, url }) => {
        if (market !== "tw") return null;
        expect(url.searchParams.get("version")).toBe("v2");
        return { body: seededRadarResponse(url, "history-radar") };
      },
      taiwanRadarV2OutcomeLatest: radarV2OutcomeSummary("2026-06-14"),
      taiwanRadarV2OutcomeHistory: [
        radarV2OutcomeSummary("2026-06-14"),
        radarV2OutcomeSummary("2026-06-13", "pending"),
      ],
      taiwanRadarV2OutcomeSnapshots: {
        "2026-06-13": radarV2OutcomeDetailSummary("2026-06-13"),
        "2026-06-14": radarV2OutcomeDetailSummary("2026-06-14"),
      },
      apiResponder: ({ method, path }) => {
        if (
          method === "POST" &&
          /\/(?:wl|watchlists)\/groups\/7\/radar\/v2\/outcomes\/reconcile$/.test(path)
        ) {
          return { body: reconcileJob };
        }
        if (path.endsWith("/jobs/901")) {
          return { body: reconcileJob };
        }
        return null;
      },
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await page.locator('[data-watchlist-group-id="7"]').click();
    await expect(page.getByTestId("watchlist-radar-result-2330")).toBeVisible();
    await expect(
      page.getByTestId("watchlist-radar-context-2330-cross_market_context")
    ).toContainText("外部順風");
    await expect(page.getByTestId("watchlist-radar-v2-outcome-summary")).toHaveCount(0);
    const radarHeaderButtons = page
      .getByTestId("watchlist-radar-controls")
      .locator("button");
    await expect(radarHeaderButtons).toHaveCount(2);
    await expect(radarHeaderButtons.nth(0)).toHaveAttribute(
      "data-testid",
      "watchlist-radar-history-open"
    );
    await expect(radarHeaderButtons.nth(1)).toHaveAttribute(
      "data-testid",
      "watchlist-radar-reload"
    );
    const historyResponse = page.waitForResponse((response) =>
      /\/(?:wl|watchlists)\/groups\/7\/radar\/v2\/outcomes\/history$/.test(
        new URL(response.url()).pathname
      )
    );
    await page.getByTestId("watchlist-radar-history-open").click();
    const response = await historyResponse;
    expect(new URL(response.url()).searchParams.get("horizon_trading_days")).toBe("1");
    await expect(page.getByTestId("watchlist-radar-history-dialog")).toBeVisible();
    const detailResponse = page.waitForResponse((candidate) =>
      /\/(?:wl|watchlists)\/groups\/7\/radar\/v2\/outcomes\/latest$/.test(
        new URL(candidate.url()).pathname
      ) && new URL(candidate.url()).searchParams.get("snapshot_date") === "2026-06-13"
    );
    await page.getByTestId("watchlist-radar-v2-history-snapshot-2026-06-13").click();
    const selectedDetailResponse = await detailResponse;
    expect(
      new URL(selectedDetailResponse.url()).searchParams.get("item_limit")
    ).toBe("200");
    await expect(
      page.getByTestId("watchlist-radar-v2-history-items").locator(":scope > article")
    ).toHaveCount(30);
    await expect(
      page.getByTestId("watchlist-radar-v2-history-item-30-7030")
    ).toContainText("方向反轉");
    const firstOutcome = page.getByTestId("watchlist-radar-v2-history-item-1-7001");
    await expect(firstOutcome).toContainText("T+1 收盤變動");
    await expect(firstOutcome).toContainText("最大不利幅度");
    await expect(firstOutcome.locator(".text-omi-danger")).toContainText("1.00%");
    await expect(firstOutcome).toContainText("資料限制 2 項");
    await expect(firstOutcome.getByText("entry_proxy_not_execution")).not.toBeVisible();

    const reconcileResponse = page.waitForResponse((candidate) =>
      /\/(?:wl|watchlists)\/groups\/7\/radar\/v2\/outcomes\/reconcile$/.test(
        new URL(candidate.url()).pathname
      )
    );
    await page.getByTestId("watchlist-radar-history-reconcile").click();
    const completedReconcileResponse = await reconcileResponse;
    const reconcileUrl = new URL(completedReconcileResponse.url());
    expect(reconcileUrl.searchParams.get("mode")).toBe("action");
    expect(reconcileUrl.searchParams.get("limit")).toBe("200");
    await expect.poll(
      () =>
        apiRequests.filter((request) => request.path.endsWith("/jobs/901"))
          .length
    ).toBeGreaterThan(0);
    await expect(page.getByTestId("watchlist-radar-history-reconcile")).toHaveText(
      "檢查結果"
    );
    await expect(page.getByTestId("watchlist-radar-history-dialog")).toBeVisible();
    expect(pageErrors).toEqual([]);
  });

  test("regional radar preserves mode and ignores a stale response", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      usRankingRows: seededUsRankingRows(),
      radarResponder: ({ market, url }) => {
        if (market !== "us") return null;
        const mode = url.searchParams.get("mode") ?? "action";
        return {
          body: seededRadarResponse(
            url,
            mode === "risk" ? "current-risk-response" : "stale-action-response"
          ),
          delayMs: mode === "risk" ? 10 : 350,
        };
      },
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await page.locator('a[href="/?market=us"]').click();
    await page.getByRole("button", { name: "Reload" }).first().click();
    const usSidebar = page.getByRole("complementary");
    const usGroupLabel = usSidebar.getByText("Mega Cap Tech", { exact: true }).last();
    const staleActionRequest = page.waitForRequest((request) => {
      const url = new URL(request.url());
      return /\/us-market\/watchlists\/groups\/17\/radar$/.test(url.pathname) &&
        url.searchParams.get("mode") === "action";
    });
    const staleActionResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return /\/us-market\/watchlists\/groups\/17\/radar$/.test(url.pathname) &&
        url.searchParams.get("mode") === "action";
    });
    await usGroupLabel.click();
    await staleActionRequest;

    const currentRiskResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return /\/us-market\/watchlists\/groups\/17\/radar$/.test(url.pathname) &&
        url.searchParams.get("mode") === "risk";
    });
    await page.getByTestId("watchlist-radar-mode-risk").click();
    await currentRiskResponse;
    await expect(page).toHaveURL(/\?market=us&group_id=17&radar_mode=risk$/);
    await expect(page.getByTestId("watchlist-radar-result-AAPL")).toContainText(
      "current-risk-response"
    );
    const radarHeaderActions = page.getByTestId("watchlist-radar-header-actions");
    const radarControls = radarHeaderActions.getByTestId("watchlist-radar-controls");
    const radarNotice = radarHeaderActions.getByTestId("watchlist-radar-notice");
    await expect(radarNotice).toContainText("此雷達僅使用 OHLCV");
    const [controlsBox, noticeBox] = await Promise.all([
      radarControls.boundingBox(),
      radarNotice.boundingBox(),
    ]);
    expect(controlsBox).not.toBeNull();
    expect(noticeBox).not.toBeNull();
    expect(noticeBox!.y).toBeGreaterThanOrEqual(controlsBox!.y + controlsBox!.height);

    await staleActionResponse;
    await expect(page.getByTestId("watchlist-radar-result-AAPL")).toContainText(
      "current-risk-response"
    );
    await page.getByTestId("watchlist-radar-result-AAPL").getByRole("button").click();
    await expect(page).toHaveURL(/\?market=us&symbol=AAPL&radar_mode=risk$/);
    expect(pageErrors).toEqual([]);
  });

  test("Japan ranking stays intact when switching to an empty Korea watchlist", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      jpWatchlistTree: seededJpWatchlistTree(),
      jpWatchlistItems: seededJpWatchlistItems(),
      jpRankingRows: seededJpRankingRows(),
      krWatchlistTree: seededKrWatchlistTree(),
    });
    await page.goto("/?market=jp", { waitUntil: "domcontentloaded" });

    await page.getByRole("button", { name: "Reload" }).first().click();
    const japanRankingResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname.endsWith("/jp-market/watchlists/ranking")
    );
    await page.getByText("Japan Core", { exact: true }).first().click();
    await japanRankingResponse;
    const toyotaRow = page.locator('[data-ranking-symbol="7203.T"]');
    await expect(page.locator("[data-ranking-symbol]")).toHaveCount(2);
    await expect(toyotaRow).toContainText("7203.T Toyota Motor");
    await expect(toyotaRow).toContainText("2,850.5");
    await expect(toyotaRow).toContainText("+1.79%");
    await expect(toyotaRow).toHaveAttribute("href", /market=jp.*jp_symbol=7203.T/);

    await page.locator('a[href="/?market=kr"]').click();
    await expect(page).toHaveURL(/market=kr/);
    const koreaRankingResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname.endsWith("/kr-market/watchlists/ranking");
    });
    await page.getByRole("button", { name: "Reload" }).first().click();
    await page.getByText("Korea Core", { exact: true }).first().click();
    await koreaRankingResponse;

    const koreaPanel = page
      .getByRole("heading", { name: "Korea Core" })
      .locator("xpath=ancestor::section[1]");
    await expect(koreaPanel.locator("select")).toBeVisible();
    await expect(koreaPanel.getByRole("button", { name: "Reload" })).toBeEnabled();
    await expect(page.locator("[data-ranking-symbol]")).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });

  test("Japan ranking can reload after an API error", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      jpWatchlistTree: seededJpWatchlistTree(),
      jpWatchlistItems: seededJpWatchlistItems(),
      regionalRankingResponder: ({ market, requestNumber, url }) => {
        if (market !== "jp") return null;
        if (requestNumber === 1) {
          return {
            status: 503,
            body: { detail: "Playwright ranking failure" },
          };
        }
        return { body: seededJpRankingResponse(url, seededJpRankingRows()) };
      },
    });
    await page.goto("/?market=jp", { waitUntil: "domcontentloaded" });

    const failedResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname.endsWith("/jp-market/watchlists/ranking") &&
        response.status() === 503
    );
    await page.getByRole("button", { name: "Reload" }).first().click();
    await page.getByText("Japan Core", { exact: true }).first().click();
    await failedResponse;

    const japanPanel = page
      .getByRole("heading", { name: "Japan Core" })
      .locator("xpath=ancestor::section[1]");
    const rankingReload = japanPanel.getByRole("button", { name: "Reload" });
    await expect(rankingReload).toBeEnabled();
    await rankingReload.click();
    await expect(page.locator('[data-ranking-symbol="7203.T"]')).toContainText("2,850.5");
    expect(pageErrors).toEqual([]);
  });

  test("calendar switches between Taiwan and US while Japan and Korea remain planned", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      apiRequests,
      apiResponder: ({ path }) => {
        if (path.endsWith("/market/tw-corporate-events")) {
          return { body: emptyTaiwanCorporateEventListResponse() };
        }
        if (path.endsWith("/us-market/corporate-events")) {
          return { body: usCorporateEventListResponse() };
        }
        return null;
      },
    });
    await page.goto("/?market=tw", { waitUntil: "domcontentloaded" });

    await page.getByRole("button", { name: /開啟設定|Open settings/ }).click();
    await page.getByRole("button", { name: /行事曆|Calendar/ }).click();

    const japanButton = page.getByTestId("calendar-market-jp");
    const koreaButton = page.getByTestId("calendar-market-kr");
    await expect(japanButton).toBeDisabled();
    await expect(koreaButton).toBeDisabled();
    await expect(japanButton).toContainText(/規劃中|Planned/);
    await expect(koreaButton).toContainText(/規劃中|Planned/);

    const usResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname.endsWith("/us-market/corporate-events")
    );
    await page.getByTestId("calendar-market-us").click();
    await usResponse;
    await expect(page.getByText("AAPL Apple Inc.", { exact: true })).toBeVisible();
    await expect(page.getByText(/Alpha Vantage Earnings Calendar/)).toBeVisible();
    expect(
      apiRequests.filter(
        (request) =>
          request.path.includes("/jp-market/corporate-events") ||
          request.path.includes("/kr-market/corporate-events")
      )
    ).toHaveLength(0);
    expect(pageErrors).toEqual([]);
  });

  test("US stock detail shows a cached corporate event within seven days", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      usRankingRows: seededUsRankingRows(),
      apiResponder: ({ path }) =>
        path.endsWith("/us-market/corporate-events/AAPL/summary")
          ? {
              body: usCorporateEventSummaryResponse("AAPL", [
                usCorporateEventResponse("AAPL"),
              ]),
            }
          : null,
    });
    await page.goto("/?market=us&group_id=17&symbol=AAPL", {
      waitUntil: "domcontentloaded",
    });

    const reminder = page.getByTestId("us-upcoming-corporate-event");
    await expect(reminder).toBeVisible();
    await expect(reminder).toContainText("2026-07-31");
    expect(pageErrors).toEqual([]);
  });

  test("Korea ranking ignores a stale response after rank mode changes", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const staleRows = seededKrRankingRows().map((row) =>
      row.symbol === "005930.KS"
        ? { ...row, close: 11100, change: -900, change_pct: -7.5 }
        : row
    );
    const currentRows = seededKrRankingRows().map((row) =>
      row.symbol === "005930.KS"
        ? { ...row, close: 77700, change: 2700, change_pct: 3.6 }
        : row
    );
    await mockOmiApi(page, {
      krWatchlistTree: seededKrWatchlistTree(),
      krWatchlistItems: seededKrWatchlistItems(),
      regionalRankingResponder: ({ market, url }) => {
        if (market !== "kr") return null;
        if (url.searchParams.get("rank_by") === "none") {
          return {
            delayMs: 900,
            body: seededKrRankingResponse(url, staleRows),
          };
        }
        return { body: seededKrRankingResponse(url, currentRows) };
      },
    });
    await page.goto("/?market=kr", { waitUntil: "domcontentloaded" });

    const staleResponse = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname.endsWith("/kr-market/watchlists/ranking") &&
        url.searchParams.get("rank_by") === "none"
      );
    });
    const initialRequest = page.waitForRequest((request) => {
      const url = new URL(request.url());
      return (
        url.pathname.endsWith("/kr-market/watchlists/ranking") &&
        url.searchParams.get("rank_by") === "none"
      );
    });
    await page.getByRole("button", { name: "Reload" }).first().click();
    await page.getByText("Korea Core", { exact: true }).first().click();
    await initialRequest;

    const koreaPanel = page
      .getByRole("heading", { name: "Korea Core" })
      .locator("xpath=ancestor::section[1]");
    await koreaPanel.locator("select").selectOption("change_pct");
    const samsungRow = page.locator('[data-ranking-symbol="005930.KS"]');
    await expect(samsungRow).toContainText("77,700");
    await expect(samsungRow).toContainText("+3.60%");

    await staleResponse;
    await expect(samsungRow).toContainText("77,700");
    await expect(samsungRow).toContainText("+3.60%");
    expect(pageErrors).toEqual([]);
  });

  test("Taiwan ETF selection renders the ETF work surface and bounded refresh", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    const apiRequests: NonNullable<MockOmiApiOptions["apiRequests"]> = [];
    const timestamp = "2026-08-09T12:00:00+08:00";
    const baseOverview = {
      stock_id: "0050",
      stock_name: "元大台灣50",
      market: "TWSE",
      instrument_type: "etf",
      status: "missing",
      capabilities: {
        price_chart: true,
        technical_analysis: true,
        quote_depth: true,
        institutional_flow: true,
        broker_branch: true,
        etf_profile: true,
        daily_close_nav: true,
        intraday_estimated_nav: true,
        pcf: true,
        component_exposure: true,
        holdings: false,
        company_revenue: false,
        company_financials: false,
      },
      profile: null,
      daily_nav: null,
      pcf: null,
      intraday_nav: null,
      valuation: {
        status: "missing",
        basis: "daily_close",
        market_price: {
          value: null,
          as_of_date: null,
          observed_at: null,
          fetched_at: null,
          source: null,
          source_url: null,
          basis: "daily_close",
          status: "missing",
          issue_codes: ["daily_market_price_missing"],
        },
        nav: {
          value: null,
          as_of_date: null,
          observed_at: null,
          fetched_at: null,
          source: null,
          source_url: null,
          basis: "daily_nav",
          status: "missing",
          issue_codes: ["daily_nav_missing"],
        },
        premium_discount_pct: null,
        premium_discount_status: "input_missing",
        aligned: false,
        issue_codes: ["daily_market_price_missing", "daily_nav_missing"],
      },
      strategy: {
        management_style: "unknown",
        benchmark_role: "unknown",
        benchmark_name: null,
      },
      resource_states: {
        market_price: {
          applicable: true,
          connector_supported: true,
          status: "missing",
          reason_code: "daily_market_price_missing",
          as_of_date: null,
          observed_at: null,
          source: null,
        },
        daily_nav: {
          applicable: true,
          connector_supported: true,
          status: "missing",
          reason_code: "daily_nav_missing",
          as_of_date: null,
          observed_at: null,
          source: null,
        },
        intraday_nav: {
          applicable: true,
          connector_supported: true,
          status: "missing",
          reason_code: "intraday_nav_cache_missing",
          as_of_date: null,
          observed_at: null,
          source: null,
        },
        pcf_summary: {
          applicable: true,
          connector_supported: true,
          status: "missing",
          reason_code: "pcf_cache_missing",
          as_of_date: null,
          observed_at: null,
          source: null,
        },
        pcf_component_basket: {
          applicable: true,
          connector_supported: true,
          status: "missing",
          reason_code: "pcf_component_basket_missing",
          as_of_date: null,
          observed_at: null,
          source: null,
        },
        fund_holdings: {
          applicable: true,
          connector_supported: false,
          status: "provider_not_connected",
          reason_code: "fund_holdings_provider_not_connected",
          as_of_date: null,
          observed_at: null,
          source: null,
        },
      },
      freshness: {
        status: "missing",
        timezone: "Asia/Taipei",
        nav_release_time: "21:00",
        expected_nav_date: "2026-08-07",
        latest_nav_date: null,
        nav_is_current: false,
        profile_report_date: null,
        expected_pcf_date: "2026-08-10",
        latest_pcf_date: null,
        pcf_status: "missing",
        expected_inav_date: "2026-08-07",
        latest_inav_at: null,
        inav_status: "missing",
        inav_age_seconds: null,
        session_phase: "market_closed",
        refresh_recommended: true,
        checked_at: timestamp,
      },
      sources: [],
      warnings: ["尚無 ETF 基本資料 cache。"],
      refresh: null,
    };
    const refreshedOverview = {
      ...baseOverview,
      status: "current",
      profile: {
        report_date: "2026-08-08",
        fund_short_name: "元大台灣50",
        fund_name: "元大台灣卓越50證券投資信託基金",
        fund_name_en: "Yuanta Taiwan Top 50 ETF",
        fund_type: "國內成分證券指數股票型基金",
        benchmark_name: "臺灣50指數",
        is_customized_index: false,
        investment_scope: "股票投資",
        has_performance_benchmark: true,
        performance_benchmark_name: "臺灣50指數",
        has_foreign_components: false,
        tax_id: "00938563",
        established_date: "2003-06-25",
        listed_date: "2003-06-30",
        fund_manager: "測試經理人",
        issued_units: 1_234_000,
        custodian: "測試銀行",
        issuer_name: "元大投信",
        source: "twse_openapi",
        source_url: "https://openapi.twse.com.tw/v1/opendata/t187ap47_L",
        fetched_at: timestamp,
      },
      daily_nav: {
        nav_date: "2026-08-07",
        issuer_name: "元大投信",
        fund_name: "元大台灣50",
        nav: 102.76,
        previous_nav: 103.04,
        nav_change: -0.28,
        nav_change_pct: -0.27,
        close_price: 102.85,
        premium_discount_pct: 0.09,
        benchmark_name: "臺灣50指數",
        benchmark_date: "2026-08-07",
        benchmark_close: 41098.32,
        benchmark_previous_close: 41212.45,
        benchmark_change: -114.13,
        benchmark_change_pct: -0.28,
        source: "mops",
        source_url: "https://mopsov.twse.com.tw/mops/web/ajax_t78sb35",
        fetched_at: timestamp,
      },
      pcf: {
        effective_date: "2026-08-10",
        reference_date: "2026-08-07",
        fund_id: "1066",
        fund_name: "元大台灣50",
        full_name: "元大台灣卓越50證券投資信託基金",
        name_en: "Yuanta/P-shares Taiwan Top 50 ETF",
        total_net_assets: 2_305_206_923_456,
        issued_units: 22_433_000_000,
        unit_nav: 102.76,
        creation_unit: 500_000,
        estimated_creation_value: 51_379_818,
        estimated_cash_component: 51_496,
        unit_change: 0,
        actual_cash_component: 52_052,
        redemption_method: "in_kind",
        component_count: 2,
        components: [
          {
            source_section: "in_kind",
            asset_type: "stock",
            symbol: "2330",
            name: "台積電",
            name_en: "Taiwan Semiconductor Manufacturing Co.",
            contract_month: null,
            quantity: 18_000,
            weight_pct: null,
            cash_in_lieu: "N",
            minimum_creation: true,
            order_index: 0,
          },
          {
            source_section: "in_kind",
            asset_type: "stock",
            symbol: "1216",
            name: "統一",
            name_en: "UNI-PRESIDENT ENTERPRISES CORP.",
            contract_month: null,
            quantity: 2_581,
            weight_pct: null,
            cash_in_lieu: "N",
            minimum_creation: true,
            order_index: 1,
          },
        ],
        source_updated_at: "2026-08-07T07:47:38Z",
        source: "yuanta_etfs",
        source_url: "https://www.yuantaetfs.com/tradeInfo/pcf/0050",
        fetched_at: timestamp,
      },
      intraday_nav: {
        observed_at: "2026-08-07T05:31:00Z",
        fund_short_name: "元大台灣50",
        investment_area: "D",
        estimated_nav: 102.76,
        nav_change: -0.28,
        market_price: 102.85,
        price_change: -0.45,
        premium_discount_pct: 0.087583,
        source: "yuanta_etfs",
        source_url: "https://www.yuantaetfs.com/tradeInfo/comparison/0050/realtime",
        fetched_at: timestamp,
      },
      valuation: {
        status: "current",
        basis: "daily_close",
        market_price: {
          value: 102.85,
          as_of_date: "2026-08-07",
          observed_at: null,
          fetched_at: timestamp,
          source: "twse_daily_price",
          source_url: "https://www.twse.com.tw/",
          basis: "daily_close",
          status: "current",
          issue_codes: [],
        },
        nav: {
          value: 102.76,
          as_of_date: "2026-08-07",
          observed_at: null,
          fetched_at: timestamp,
          source: "mops",
          source_url: "https://mopsov.twse.com.tw/mops/web/ajax_t78sb35",
          basis: "daily_nav",
          status: "current",
          issue_codes: [],
        },
        premium_discount_pct: 0.087583,
        premium_discount_status: "ready",
        aligned: true,
        issue_codes: [],
      },
      strategy: {
        management_style: "passive",
        benchmark_role: "tracked_index",
        benchmark_name: "臺灣50指數",
      },
      resource_states: {
        ...baseOverview.resource_states,
        market_price: {
          ...baseOverview.resource_states.market_price,
          status: "current",
          reason_code: null,
          as_of_date: "2026-08-07",
          source: "twse_daily_price",
        },
        daily_nav: {
          ...baseOverview.resource_states.daily_nav,
          status: "current",
          reason_code: null,
          as_of_date: "2026-08-07",
          source: "mops",
        },
        intraday_nav: {
          ...baseOverview.resource_states.intraday_nav,
          status: "closed",
          reason_code: null,
          observed_at: "2026-08-07T05:31:00Z",
          source: "yuanta_etfs",
        },
        pcf_summary: {
          ...baseOverview.resource_states.pcf_summary,
          status: "current",
          reason_code: null,
          as_of_date: "2026-08-10",
          source: "yuanta_etfs",
        },
        pcf_component_basket: {
          ...baseOverview.resource_states.pcf_component_basket,
          status: "current",
          reason_code: null,
          as_of_date: "2026-08-10",
          source: "yuanta_etfs",
        },
      },
      freshness: {
        ...baseOverview.freshness,
        status: "current",
        latest_nav_date: "2026-08-07",
        nav_is_current: true,
        profile_report_date: "2026-08-08",
        latest_pcf_date: "2026-08-10",
        pcf_status: "current",
        latest_inav_at: "2026-08-07T05:31:00Z",
        inav_status: "closed",
        inav_age_seconds: null,
        refresh_recommended: false,
      },
      warnings: [],
      refresh: {
        requested_resources: [
          "profile",
          "daily_close_nav",
          "pcf",
          "intraday_estimated_nav",
        ],
        refreshed_resources: [
          "profile",
          "daily_close_nav",
          "pcf",
          "intraday_estimated_nav",
        ],
        request_count: 8,
        target_nav_date: "2026-08-07",
        target_pcf_date: "2026-08-10",
        inav_observed_at: "2026-08-07T05:31:00Z",
        errors: {},
      },
    };
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      apiRequests,
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: [
        {
          id: 500,
          group_id: 7,
          stock_id: "0050",
          stock_name: "元大台灣50",
          market: "TWSE",
          instrument_type: "etf",
          note: null,
          priority: 0,
          tags: "ETF",
          enabled: true,
          created_at: timestamp,
          updated_at: timestamp,
        },
      ],
      apiResponder: ({ method, path }) => {
        if (path.endsWith("/market/etfs/0050/overview")) {
          return { body: baseOverview };
        }
        if (method === "POST" && path.endsWith("/market/etfs/0050/refresh")) {
          return { body: refreshedOverview };
        }
        if (path.endsWith("/market/institutional/0050/holding-ratios")) {
          return {
            status: 404,
            body: { detail: "ETF institutional holding ratios unavailable" },
          };
        }
        return null;
      },
    });
    await page.goto("/?market=tw&group_id=7&stock_id=0050", {
      waitUntil: "domcontentloaded",
    });

    const panel = page.getByTestId("tw-etf-data-panel");
    const dataPanel = page.getByTestId("tw-stock-detail-data-panel");
    const chipsTab = dataPanel.locator('[data-data-tab="chips"]');
    const institutionalTab = dataPanel.locator('[data-data-tab="institutional"]');
    const branchTab = dataPanel.locator('[data-data-tab="branch"]');
    const etfTab = dataPanel.locator('[data-data-tab="etf"]');
    await expect(panel).toBeVisible();
    await expect(chipsTab).toBeVisible();
    await expect(institutionalTab).toBeVisible();
    await expect(branchTab).toBeVisible();
    await expect(etfTab).toBeVisible();
    await expect(etfTab).toHaveAttribute("aria-selected", "true");
    await expect(panel).toContainText("102.7600");
    await expect(panel).toContainText("+0.09%");
    await expect(panel).toContainText("臺灣50指數");
    await expect(panel).toContainText("盤後日資料");
    await expect(panel).toContainText("盤中 iNAV · 前一交易時段");
    await expect(panel).toContainText("申購買回資料（PCF）");
    await expect(panel).toContainText("基金持股 · 來源尚未接入");
    await expect(panel).toContainText("台積電");
    await expect(page.getByText("營收資料", { exact: false })).toHaveCount(0);
    await expect(dataPanel.locator('[data-data-tab="revenue"]')).toHaveCount(0);
    await expect(dataPanel.locator('[data-data-tab="earnings"]')).toHaveCount(0);
    expect(
      apiRequests.filter(
        (request) =>
          request.method === "POST" &&
          request.path.endsWith("/market/etfs/0050/refresh")
      )
    ).toHaveLength(1);
    expect(
      apiRequests.find(
        (request) =>
          request.method === "POST" &&
          request.path.endsWith("/market/etfs/0050/refresh")
      )?.body
    ).toEqual({
      refresh_profile: true,
      refresh_nav: true,
      refresh_pcf: true,
      refresh_inav: true,
    });

    expect(
      apiRequests.filter(
        (request) =>
          request.method === "POST" &&
          request.path.endsWith("/market/selection-refresh/0050")
      )
    ).toHaveLength(0);

    await chipsTab.click();
    await expect(chipsTab).toHaveAttribute("aria-selected", "true");
    await expect(panel).toHaveCount(0);
    expect(
      apiRequests.filter(
        (request) =>
          request.method === "POST" &&
          request.path.endsWith("/market/selection-refresh/0050") &&
          request.search.includes("profile=chips")
      )
    ).toHaveLength(0);

    await institutionalTab.click();
    await expect(institutionalTab).toHaveAttribute("aria-selected", "true");
    await expect
      .poll(() =>
        apiRequests.some((request) =>
          request.path.endsWith("/market/institutional/0050/history")
        )
      )
      .toBe(true);

    await branchTab.click();
    await expect(branchTab).toHaveAttribute("aria-selected", "true");
    await expect
      .poll(() =>
        apiRequests.some((request) =>
          request.path.endsWith("/market/broker-branches/0050/daily")
        )
      )
      .toBe(true);

    expect(
      apiRequests.filter(
        (request) =>
          request.path.includes("/market/revenue/0050") ||
          request.path.includes("/market/financials/0050")
      )
    ).toHaveLength(0);

    await etfTab.click();
    await expect(etfTab).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("tw-etf-data-panel")).toBeVisible();
    expect(pageErrors).toEqual([]);
  });
});

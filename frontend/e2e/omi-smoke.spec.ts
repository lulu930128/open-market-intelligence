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

function emptyRadarResponse(path: string) {
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
    mode: "action",
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
        kind: "omi.ai.ask.v2",
        analysis: {
          human_answer: {
            kind: "consumer_market_answer",
            headline: "測試回答：目前偏多但等待確認",
            stance_label: "偏多",
            confidence_label: "中",
            summary: ["測試資料已讀取", "價位仍需突破確認"],
            action_plan: [{ label: "現在", text: "先觀察，不追價。" }],
            risks: ["跌破短線支撐則失效。"],
            data_limits: [],
          },
        },
        source_refs: [{ name: "playwright.fixture" }],
      },
    ],
    ["done", { ok: true }],
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

  await page.route("**/omi-data/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (path.endsWith("/ai/ask/stream")) {
      await fulfillOmiStream(route);
      return;
    }

    if (path.includes("/market/calendar-status")) {
      await fulfillJson(route, calendarStatus());
      return;
    }

    if (path.includes("/market/indices/summary")) {
      await fulfillJson(route, {
        as_of: "2026-06-15T09:30:00+08:00",
        indices: [
          {
            index_id: "TAIEX",
            name: "加權指數",
            close: 861,
            change: 12,
            change_pct: 1.4,
            volume: 1_200_000,
            advancers: 600,
            decliners: 220,
            market_breadth_pct: 72,
          },
        ],
      });
      return;
    }

    if (path.includes("/market/tw-futures/latest")) {
      await fulfillJson(route, []);
      return;
    }

    if (/\/market\/tw-futures\/[^/]+\/(?:intraday|daily)$/.test(path)) {
      await fulfillJson(route, []);
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
        trade_date: "2026-06-15",
        reference_price: 849,
        latest_price: 861,
        previous_close: 849,
        points: [],
      });
      return;
    }

    if (path.includes("/market/indices/TAIEX/ohlc")) {
      await fulfillJson(route, ohlcResponse("TAIEX"));
      return;
    }

    if (path.includes("/market/ohlc/2330")) {
      await fulfillJson(route, ohlcResponse("2330"));
      return;
    }

    if (/\/us-market\/ohlc\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "SPY");
      await fulfillJson(route, usOhlcResponse(symbol));
      return;
    }

    if (/\/us-market\/intraday\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "SPY");
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

    if (/\/us-market\/profiles\/[^/]+$/.test(path)) {
      await fulfillJson(route, null);
      return;
    }

    if (/\/us-market\/corporate-actions\/[^/]+$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    if (/\/us-market\/short-volume\/[^/]+\/history$/.test(path)) {
      await fulfillJson(route, []);
      return;
    }

    if (/\/jp-market\/ohlc\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "^N225");
      await fulfillJson(route, regionalOhlcResponse(symbol));
      return;
    }

    if (/\/jp-market\/intraday\//.test(path)) {
      const symbol = decodeURIComponent(path.split("/").at(-1) ?? "^N225");
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
      await fulfillJson(route, regionalIntradayResponse(indexId));
      return;
    }

    const krIndexBreadthMatch = path.match(/\/kr-market\/indices\/([^/]+)\/breadth$/);
    if (krIndexBreadthMatch) {
      const indexId = decodeURIComponent(krIndexBreadthMatch[1]);
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
      await fulfillJson(route, emptyRadarResponse(path));
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/radar\/outcomes\/latest$/.test(path)) {
      await fulfillJson(route, null);
      return;
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

  test("Taiwan index professional chart shell renders", async ({ page }) => {
    await mockOmiApi(page);
    await page.goto("/?stock_id=TAIEX", { waitUntil: "domcontentloaded" });

    await expect(page.getByRole("heading", { name: "TAIEX 加權指數" })).toBeVisible();
    await expect(page.getByRole("button", { name: "放大" }).first()).toBeEnabled();
    await page.getByRole("button", { name: "放大" }).first().click();

    await expect(page.getByRole("button", { name: "總覽" })).toBeVisible();
    await expect(page.locator("canvas").first()).toBeVisible();
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
    await expect(page.getByText("持股資料格式錯誤，請重新整理。")).toBeVisible();
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
    await expect(page).toHaveURL(/\?market=kr$/);

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
    await expect(page).toHaveURL(/\?market=kr$/);
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
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page);
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await page.locator('a[href="/?market=crypto"]').click();
    await expect(page).toHaveURL(/\?market=crypto$/);
    const cryptoHistoryLength = await page.evaluate(() => window.history.length);

    const currencyButton = page
      .locator('[data-testid^="currency-sidebar-instrument-"]')
      .first();
    await expect(currencyButton).toBeVisible();
    const currencySymbol = (await currencyButton.innerText()).split("\n")[0].trim();
    await currencyButton.click();
    await expect(currencyButton).toHaveClass(/omi-sidebar-selected/);
    await expect(
      page.getByRole("heading", { level: 2 }).filter({ hasText: currencySymbol }).first()
    ).toBeVisible();
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
});

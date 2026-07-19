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

function intradayResponse(stockId: string) {
  const latestPrice = stockId === "2303" ? 52.4 : 1_015;
  const previousClose = stockId === "2303" ? 53 : 1_000;

  return {
    stock_id: stockId,
    symbol: stockId,
    source: "playwright.fixture",
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
    best_bid_price: lastPrice - tick,
    best_bid_size_lots: 100,
    best_ask_price: lastPrice + tick,
    best_ask_size_lots: 120,
    bid_total_size_lots: 500,
    ask_total_size_lots: 600,
    spread: tick * 2,
    spread_pct: ((tick * 2) / lastPrice) * 100,
    bid_levels: Array.from({ length: 5 }, (_, index) => ({
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
        context_snapshot: {},
        context_signals: [],
        context_summary: label,
        context_score: 0,
        stale: false,
        error_message: null,
      },
    ],
  };
}

function radarSnapshot(id: number, snapshotDate: string, mode = "action") {
  return {
    id,
    group_id: 7,
    include_children: true,
    enabled_only: true,
    mode,
    max_results: 20,
    calculation_limit: 100,
    radar_rule_version: "playwright.v1",
    snapshot_date: snapshotDate,
    trade_date: snapshotDate,
    target_trade_date: snapshotDate,
    is_current: true,
    current_stock_count: 1,
    stale_stock_count: 0,
    requested_stock_count: 1,
    ranked_count: 1,
    matched_count: 1,
    radar_count: 1,
    no_data_count: 0,
    error_count: 0,
    buckets: [],
    data_limitations: [],
    created_at: `${snapshotDate}T14:00:00+08:00`,
    updated_at: `${snapshotDate}T14:00:00+08:00`,
  };
}

function radarOutcomeSummary(
  id: number,
  snapshotDate: string,
  status = "evaluated"
) {
  return {
    status,
    snapshot: radarSnapshot(id, snapshotDate),
    evaluated_at: `${snapshotDate}T15:00:00+08:00`,
    total_count: 1,
    hit_count: status === "evaluated" ? 1 : 0,
    miss_count: 0,
    neutral_count: 0,
    unevaluable_count: 0,
    pending_count: status === "pending" ? 1 : 0,
    avg_close_return_pct: status === "evaluated" ? 1.25 : null,
    avg_max_favorable_pct: status === "evaluated" ? 2.5 : null,
    avg_max_adverse_pct: status === "evaluated" ? -0.5 : null,
    bucket_summaries: [],
    items: [],
    data_limitations: [],
  };
}

function noRadarOutcomeSummary() {
  return {
    status: "no_snapshot",
    snapshot: null,
    evaluated_at: null,
    total_count: 0,
    hit_count: 0,
    miss_count: 0,
    neutral_count: 0,
    unevaluable_count: 0,
    pending_count: 0,
    avg_close_return_pct: null,
    avg_max_favorable_pct: null,
    avg_max_adverse_pct: null,
    bucket_summaries: [],
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
  taiwanRadarOutcomeLatest?: unknown;
  taiwanRadarOutcomeHistory?: unknown[];
  taiwanRadarOutcomeEvaluation?: unknown;
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

    if (path.includes("/market/indices/summary")) {
      if (await tryFulfillMarketTape(route, url, "tw", "summary", "summary")) return;
      await fulfillJson(route, marketIndexSummaryResponse(861));
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

    const taiwanQuoteDepthMatch = path.match(/\/market\/quote-depth\/([^/]+)$/);
    if (taiwanQuoteDepthMatch) {
      await fulfillJson(route, quoteDepthResponse(decodeURIComponent(taiwanQuoteDepthMatch[1])));
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
        title: "Fixture technical report",
        summary: `Technical fixture for ${stockId}`,
        score: 1,
        value: 1,
        value_label: "fixture",
        rows: [],
        badges: [],
        data: {},
        missing: [],
        warnings: [],
        source_refs: [],
      });
      return;
    }

    const taiwanStockMatch = path.match(/\/stocks\/([^/]+)$/);
    if (taiwanStockMatch) {
      await fulfillJson(route, stockMasterResponse(decodeURIComponent(taiwanStockMatch[1])));
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

    if (/\/(?:wl|watchlists)\/groups\/\d+\/radar\/outcomes\/latest$/.test(path)) {
      await fulfillJson(
        route,
        options.taiwanRadarOutcomeLatest ?? noRadarOutcomeSummary()
      );
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/radar\/outcomes\/history$/.test(path)) {
      await fulfillJson(route, options.taiwanRadarOutcomeHistory ?? []);
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/radar\/outcomes\/evaluate$/.test(path)) {
      if (options.taiwanRadarOutcomeEvaluation === undefined) {
        throw new Error(`Unexpected radar outcome evaluation: ${route.request().method()} ${path}`);
      }
      await fulfillJson(route, options.taiwanRadarOutcomeEvaluation);
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
          context.target === "^IXIC" &&
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
    expect(djiOhlc?.url.searchParams.get("ensure_history")).toBe("true");
    expect(djiOhlc?.url.searchParams.get("outputsize")).toBe("compact");
    expect(djiOhlc?.url.searchParams.get("provider")).toBe("yahoo_chart");
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

    await page.clock.setFixedTime(new Date("2026-07-14T15:00:00Z"));
    await mockOmiApi(page, {
      usWatchlistTree: seededUsWatchlistTree(),
      usWatchlistItems: seededUsWatchlistItems(),
      apiResponder: ({ path, requestNumber }) => {
        if (path.endsWith("/us-market/intraday/AAPL") && requestNumber >= 2) {
          return { body: { detail: timeoutDetail }, status: 504 };
        }
        return null;
      },
    });
    await page.goto("/?market=us&group_id=17&symbol=AAPL", {
      waitUntil: "domcontentloaded",
    });

    await page.getByRole("button", { name: "今日", exact: true }).first().click();

    const sidebar = page.getByRole("complementary").first();
    const statusToggle = sidebar.getByRole("button", { name: /更新狀態/ });
    await expect(statusToggle.locator(".omi-job-status-pill-attention")).toContainText("1", {
      timeout: 10_000,
    });
    await expect(page.getByText(new RegExp(timeoutDetail))).toHaveCount(0);

    await statusToggle.click();
    await expect(sidebar.getByText(new RegExp(timeoutDetail))).toBeVisible();
    await expect(page.getByRole("heading", { name: /^AAPL(?:\s|$)/ })).toBeVisible();
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

    const umcRankingLink = page.locator('[data-ranking-stock-id="2303"]');
    await expect(umcRankingLink).toBeVisible();
    await umcRankingLink.click();

    const stockDetail = page.getByTestId("stock-detail-panel");
    await expect(page.getByRole("heading", { level: 2 }).filter({ hasText: "2303" })).toBeVisible();
    await expect(stockDetail).toHaveAttribute("data-chart-stock-id", "2303");
    await expect(stockDetail).toHaveAttribute("data-chart-load-state", "success");
    await expect(page.getByTestId("quote-depth-panel")).toContainText("52.4");

    await page.waitForTimeout(1_000);
    await expect(stockDetail).toHaveAttribute("data-chart-stock-id", "2303");
    await expect(page.getByTestId("quote-depth-panel")).toContainText("52.4");
    expect(pageErrors).toEqual([]);
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
    await page.mouse.move(
      (overlayBox?.x ?? 0) + (overlayBox?.width ?? 600) * 0.48,
      (overlayBox?.y ?? 0) + (overlayBox?.height ?? 600) * 0.42
    );
    await page.mouse.down();
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

  test("Taiwan radar history evaluates the selected snapshot", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await mockOmiApi(page, {
      taiwanWatchlistTree: seededTaiwanWatchlistTree(),
      taiwanWatchlistItems: seededTaiwanWatchlistItems(),
      taiwanRankingRows: seededTaiwanRankingRows(),
      radarResponder: ({ market, url }) =>
        market === "tw" ? { body: seededRadarResponse(url, "history-radar") } : null,
      taiwanRadarOutcomeLatest: radarOutcomeSummary(102, "2026-06-14"),
      taiwanRadarOutcomeHistory: [
        radarOutcomeSummary(102, "2026-06-14"),
        radarOutcomeSummary(101, "2026-06-13", "pending"),
      ],
      taiwanRadarOutcomeEvaluation: radarOutcomeSummary(101, "2026-06-13"),
    });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    await page.locator('[data-watchlist-group-id="7"]').click();
    await expect(page.getByTestId("watchlist-radar-result-2330")).toBeVisible();
    const historyResponse = page.waitForResponse((response) =>
      /\/(?:wl|watchlists)\/groups\/7\/radar\/outcomes\/history$/.test(
        new URL(response.url()).pathname
      )
    );
    await page.getByTestId("watchlist-radar-history-open").click();
    await historyResponse;
    await expect(page.getByTestId("watchlist-radar-history-dialog")).toBeVisible();
    await page.getByTestId("watchlist-radar-history-snapshot-101").click();

    const evaluationRequest = page.waitForRequest((request) =>
      /\/(?:wl|watchlists)\/groups\/7\/radar\/outcomes\/evaluate$/.test(
        new URL(request.url()).pathname
      )
    );
    await page.getByTestId("watchlist-radar-history-evaluate-selected").click();
    const request = await evaluationRequest;
    const evaluationUrl = new URL(request.url());
    expect(evaluationUrl.searchParams.get("mode")).toBe("action");
    expect(evaluationUrl.searchParams.get("snapshot_run_id")).toBe("101");
    expect(request.postData()).toBeNull();
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

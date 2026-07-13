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
};

async function mockOmiApi(page: Page, options: MockOmiApiOptions = {}) {
  const portfolioHoldingsPayload = options.portfolioHoldingsPayload ?? [];

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

    if (/\/(?:us-market|jp-market|kr-market)\/watchlists\/ranking$/.test(path)) {
      await fulfillJson(route, emptyRankingResponse(url));
      return;
    }

    if (/\/(?:wl|watchlists)\/groups\/\d+\/rankings\/latest-batch$/.test(path)) {
      await fulfillJson(route, emptyTaiwanRankingBatch(url));
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

    if (path.includes("/wl/tree") || path.includes("/wl/items") || path.includes("/jobs")) {
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
});

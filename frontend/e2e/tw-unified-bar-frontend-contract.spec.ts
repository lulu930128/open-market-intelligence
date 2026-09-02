import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
  projectBackendIntradayPoints,
} from "@/components/IntradayTrendChart";
import { formatChartDate } from "@/components/chart/lightweight-chart/drawingModel";
import { projectTaiwanBarSeries } from "@/components/stock-detail/useTaiwanStockChartData";
import type { IntradayTrendPoint, TaiwanBarSeriesRead } from "@/types/market";

test("Taiwan chart data hook has one Bar/Technical route with no index branch", () => {
  const source = readFileSync(
    join(
      process.cwd(),
      "src/components/stock-detail/useTaiwanStockChartData.ts"
    ),
    "utf8"
  );

  expect(source).toContain("/api/market/chart/${effectStockId}");
  expect(source).toContain("/api/market/bars/${benchmarkIndexId}");
  expect(source).toContain("INDEX_DAILY_CHART_BARS = 300");
  expect(source).not.toContain("/api/market/indices/");
  expect(source).not.toContain("/api/market/intraday/");
  expect(source).not.toContain("/api/market/ohlc/");
  expect(source).not.toContain("aggregateProfessionalIntradayBars");
  expect(source).not.toContain("aggregateIntradayPoints");

  const pageSource = readFileSync(join(process.cwd(), "src/app/page.tsx"), "utf8");
  expect(pageSource).toContain(
    'taiwanIndexProductIds.has(stockId.toUpperCase()) ? "300" : "260"'
  );
});

test("Taiwan canonical Bar projection preserves missing quantities", () => {
  const series = {
    bar_states: [
      {
        start_at: "2026-09-01T09:00:00+08:00",
        technical_eligible: false,
      },
    ],
    bars: [
      {
        interval: "1m",
        start_at: "2026-09-01T09:00:00+08:00",
        end_at: "2026-09-01T09:01:00+08:00",
        open_price: "100.0",
        high_price: "101.0",
        low_price: "99.0",
        close_price: "100.5",
        volume: null,
        turnover_value: null,
        trade_count: null,
        finalization: "provisional",
      },
    ],
  } as TaiwanBarSeriesRead;

  const point = projectTaiwanBarSeries(series)[0];

  expect(point.volume).toBeNull();
  expect(point.trade_value).toBeNull();
  expect(point.indicator_eligible).toBe(false);
  expect(point.is_partial).toBe(true);
});

test("Taiwan backend-authoritative intraday projection does not calculate fallback", () => {
  const point: IntradayTrendPoint = {
    time: "2026-09-01T09:00:00+08:00",
    price: 100,
    open: 99,
    high: 101,
    low: 98,
    close: 100,
    volume: 10,
    ema_fast: null,
    ema_slow: null,
    rsi_value: null,
    macd_value: null,
    macd_signal_value: null,
    macd_histogram_value: null,
  };

  const projected = projectBackendIntradayPoints([point])[0];

  expect(projected.emaFast).toBeNull();
  expect(projected.rsi).toBeNull();
  expect(projected.macd).toBeNull();
  expect(projected.vwap).toBeNull();
  expect(projected.twap).toBeNull();
});

test("Taiwan date presentation follows daily weekly monthly periods", () => {
  expect(formatChartDate("2026-09-01", "daily")).toBe("2026/09/01");
  expect(formatChartDate("2026-09-01", "weekly")).toBe("2026/09/01 週");
  expect(formatChartDate("2026-09-01", "monthly")).toBe("2026/09");

  const stockDetailSource = readFileSync(
    join(process.cwd(), "src/components/StockDetailPanel.tsx"),
    "utf8"
  );
  expect(stockDetailSource).toContain(
    "timeLabelFormatter={chartTimeLabelFormatter}"
  );
});

test("Today empty state keeps quote and canonical history as separate states", () => {
  const source = readFileSync(
    join(process.cwd(), "src/components/IntradayTrendChart.tsx"),
    "utf8"
  );

  expect(source).toContain("currentObservation");
  expect(source).toContain("historyStatus");
  expect(source).toContain("stockDetail.intraday.historyWarming");
});

test("Taiwan technical report retries after the quote timestamp stops advancing", () => {
  const source = readFileSync(
    join(
      process.cwd(),
      "src/components/stock-detail/useTaiwanTechnicalReport.ts"
    ),
    "utf8"
  );

  expect(source).toContain("TAIWAN_TECHNICAL_REPORT_REFRESH_MS = 60_000");
  expect(source).toContain("void loadTechnicalReport().finally(scheduleRefresh)");
  expect(source).toContain("window.setTimeout");
  expect(source).toContain("window.clearTimeout");
  expect(source).not.toContain("todayUpdatedAt");
  expect(source).not.toContain("setReport(null)");
});

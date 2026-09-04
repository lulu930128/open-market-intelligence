import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
  aggregateIntradayPoints,
  projectBackendIntradayPoints,
  taiwanIntradaySession,
} from "@/components/IntradayTrendChart";
import { formatChartDate } from "@/components/chart/lightweight-chart/drawingModel";
import {
  isTodayPresentationCacheEligible,
  projectTaiwanBarSeries,
  shouldRecoverTodayFullSnapshot,
  snapshotPhaseForCoverage,
} from "@/components/stock-detail/useTaiwanStockChartData";
import type {
  IntradayTrendPoint,
  TaiwanBarSeriesRead,
  TaiwanChartBarSeriesRead,
} from "@/types/market";

test("Taiwan chart data hook reads Bars first and Technical by revision", () => {
  const source = readFileSync(
    join(
      process.cwd(),
      "src/components/stock-detail/useTaiwanStockChartData.ts"
    ),
    "utf8"
  );

  expect(source).toContain("/api/market/bars/${effectStockId}");
  expect(source).toContain("/api/market/technical/${effectStockId}/series");
  expect(source).toContain("expected_snapshot_revision: expectedRevision");
  expect(source).toContain("expected_series_revision: expectedRevision");
  expect(source).toContain("bars.current_session_coverage?.snapshot_revision");
  expect(source).toContain("/api/market/bars/${benchmarkIndexId}");
  expect(source).toContain("INDEX_DAILY_CHART_BARS = 300");
  expect(source).not.toContain("/api/market/indices/");
  expect(source).not.toContain("/api/market/intraday/");
  expect(source).not.toContain("requestJson");
  expect(source).not.toContain("fetchJson<MarketIntradayChartRead>");
  expect(source).not.toContain("/api/market/ohlc/");
  expect(source).not.toContain("aggregateProfessionalIntradayBars");
  expect(source).not.toContain("aggregateIntradayPoints");
  expect(source).not.toContain("/api/market/chart/${effectStockId}");

  const pageSource = readFileSync(join(process.cwd(), "src/app/page.tsx"), "utf8");
  expect(pageSource).not.toContain("initialChartBundle");
  expect(pageSource).not.toContain("/api/market/chart/");
});

test("Today presentation cache is bounded and never owns dataset repair", () => {
  const source = readFileSync(
    join(
      process.cwd(),
      "src/components/stock-detail/useTaiwanStockChartData.ts"
    ),
    "utf8"
  );

  expect(source).toContain("TODAY_PRESENTATION_CACHE_MAX_SYMBOLS = 10");
  expect(source).toContain("todayPresentationCacheRef");
  expect(source).toContain("setTodayState(cachedTodayState)");
  expect(source).toContain('getMarketCalendarStatusSnapshot("tw")');
  expect(source).toContain("entry.state.tradeDate === expectedTradeDate");
  expect(source).not.toContain("repair_recommended");
  expect(source).not.toContain("minimum_bar_count");
  expect(source).not.toContain("history/refresh");
});

test("Today legacy coverage fallback only promotes complete snapshots", () => {
  expect(snapshotPhaseForCoverage("complete_prefix")).toBe("ready");
  expect(snapshotPhaseForCoverage("complete_session")).toBe("ready");
  expect(snapshotPhaseForCoverage("partial_prefix")).toBe("warming");
  expect(snapshotPhaseForCoverage("sparse")).toBe("warming");
  expect(snapshotPhaseForCoverage("trailing_window")).toBe("warming");
  expect(snapshotPhaseForCoverage("partial_window")).toBe("warming");
  expect(snapshotPhaseForCoverage("missing")).toBe("warming");
});

test("Today presentation cache rejects warming and short snapshots", () => {
  const point = {
    time: "2026-09-03T09:00:00+08:00",
    price: 100,
    volume: 10,
  } as IntradayTrendPoint;

  expect(
    isTodayPresentationCacheEligible({
      snapshotPhase: "warming",
      tradeDate: "2026-09-03",
      trend: [point, { ...point, time: "2026-09-03T09:01:00+08:00" }],
    })
  ).toBe(false);
  expect(
    isTodayPresentationCacheEligible({
      snapshotPhase: "ready",
      tradeDate: "2026-09-03",
      trend: [point],
    })
  ).toBe(false);
  expect(
    isTodayPresentationCacheEligible({
      snapshotPhase: "degraded",
      tradeDate: "2026-09-03",
      trend: [point, { ...point, time: "2026-09-03T09:01:00+08:00" }],
    })
  ).toBe(true);
});

test("Today window requests recover when the canonical snapshot change is ambiguous", () => {
  const readySnapshot = {
    phase: "ready" as const,
    revision: "b".repeat(64),
    barCount: 5,
    availableFrom: "2026-09-03T09:00:00+08:00",
    availableTo: "2026-09-03T09:05:00+08:00",
    reasonCodes: ["TW_CHART_SNAPSHOT_COMPLETE"],
  };

  expect(
    shouldRecoverTodayFullSnapshot({
      fullSnapshot: false,
      mergedPointCount: 2,
      returnedPointCount: 2,
      next: readySnapshot,
      previous: {
        snapshotPhase: "warming",
        snapshotRevision: "a".repeat(64),
        snapshotAvailableFrom: "2026-09-03T13:10:00+08:00",
      },
    })
  ).toBe(true);
  expect(
    shouldRecoverTodayFullSnapshot({
      fullSnapshot: false,
      mergedPointCount: 5,
      returnedPointCount: 2,
      next: readySnapshot,
      previous: {
        snapshotPhase: "ready",
        snapshotRevision: readySnapshot.revision,
        snapshotAvailableFrom: readySnapshot.availableFrom,
      },
    })
  ).toBe(false);
  expect(
    shouldRecoverTodayFullSnapshot({
      fullSnapshot: true,
      mergedPointCount: 5,
      returnedPointCount: 5,
      next: readySnapshot,
      previous: null,
    })
  ).toBe(false);

  expect(
    shouldRecoverTodayFullSnapshot({
      fullSnapshot: false,
      mergedPointCount: 5,
      returnedPointCount: 2,
      next: { ...readySnapshot, revision: "c".repeat(64) },
      previous: {
        snapshotPhase: "ready",
        snapshotRevision: readySnapshot.revision,
        snapshotAvailableFrom: readySnapshot.availableFrom,
      },
    })
  ).toBe(true);
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

test("Taiwan formal close presentation event survives Today filtering without indicator use", () => {
  const series = {
    bar_states: [],
    bars: [],
    presentation_events: [
      {
        contract_version: "tw.bar.chart_presentation_event.v1",
        event_type: "session_close_marker",
        event_at: "2026-09-04T13:30:00+08:00",
        price: "588",
        price_semantics: "session_close",
        market_session: "closing_auction",
        finalization: "final",
        authority: "exchange",
        official: false,
        provider: "twse_mis",
        source: "twse_mis_public_quote",
        volume: null,
        display_eligible: true,
        technical_eligible: false,
      },
    ],
  } as unknown as TaiwanChartBarSeriesRead;

  const marker = projectTaiwanBarSeries(series)[0];
  const markerTrend = {
    ...marker,
    price: marker.close,
  } as IntradayTrendPoint;
  expect(marker.time).toBe("2026-09-04T13:30:00+08:00");
  expect(marker.close).toBe(588);
  expect(marker.bar_type).toBe("session_close_marker");
  expect(marker.indicator_eligible).toBe(false);
  expect(
    aggregateIntradayPoints(
      [markerTrend],
      1,
      taiwanIntradaySession,
      "2026-09-04"
    )
  ).toHaveLength(1);
  expect(
    aggregateIntradayPoints(
      [markerTrend],
      5,
      taiwanIntradaySession,
      "2026-09-04"
    )[0].bar_type
  ).toBe("session_close_marker");
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
  expect(source).toContain(
    't("stockDetail.intraday.historyWarmingDescription")'
  );
  expect(source).not.toContain("status: historyStatus");
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

import { expect, test } from "@playwright/test";

import { formatStockKLineVolumeRaw } from "@/components/StockKLineChart";
import { defaultIndicatorParameters } from "@/components/stock-k-line/indicatorCatalog";
import {
  indicatorProjectionScope,
} from "@/components/stock-k-line/indicatorAuthority";
import { projectStockKLineData } from "@/components/stock-k-line/indicatorProjection";
import { mapBackendTechnicalReport } from "@/components/stock-detail/TechnicalDataViews";
import {
  aggregateIntradayPoints,
  enrichIntradayPoints,
  taiwanIntradaySession,
} from "@/components/IntradayTrendChart";
import {
  resolveQuoteDepthHeadlineValues,
  resolveTodayHeadlineValues,
} from "@/components/stock-detail/stockDetailAnalytics";
import type { ChartPoint, StockTechnicalReportRead } from "@/types/market";

function chartPoints(): ChartPoint[] {
  return Array.from({ length: 40 }, (_, index) => {
    const close = 100 + index;
    const time = new Date(Date.UTC(2026, 5, 1 + index))
      .toISOString()
      .slice(0, 10);
    return {
      time,
      open: close - 1,
      high: close + 2,
      low: close - 2,
      close,
      volume: 1_000_000 + index * 10_000,
      trade_value: null,
      transaction_count: null,
    };
  });
}

function technicalState(price: number, label: string) {
  return {
    version: "tw_technical_current_state_v1",
    headline: { key: label, label, tone: "neutral" },
    qualifier: { key: "neutral", label: "中性", tone: "neutral" },
    summary: `${label} summary`,
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
  };
}

test("Taiwan canonical indicators fail closed when backend evidence is absent", () => {
  const points = chartPoints();
  const scope = indicatorProjectionScope([], points, {
    indicators: { rsi: true, macd: true },
    parameters: defaultIndicatorParameters,
    canonicalAuthority: "backend",
  });

  expect(scope).toBe("backend_unavailable");

  const backendOwned = projectStockKLineData({
    chartData: points,
    indicatorData: [],
    benchmarkData: [],
    params: defaultIndicatorParameters,
    latestPreviousClose: null,
    allowCanonicalFallback: false,
  });
  const presentationOwned = projectStockKLineData({
    chartData: points,
    indicatorData: [],
    benchmarkData: [],
    params: defaultIndicatorParameters,
    latestPreviousClose: null,
    allowCanonicalFallback: true,
  });

  expect(backendOwned.at(-1)?.ma20).toBeNull();
  expect(backendOwned.at(-1)?.rsi14).toBeNull();
  expect(backendOwned.at(-1)?.macd).toBeNull();
  expect(presentationOwned.at(-1)?.ma20).not.toBeNull();
  expect(presentationOwned.at(-1)?.rsi14).not.toBeNull();
  expect(presentationOwned.at(-1)?.macd).not.toBeNull();
});

test("unknown stock-chart volume units keep the provider value unchanged", () => {
  expect(formatStockKLineVolumeRaw(11_658_860)).toBe("11,658,860");
  expect(formatStockKLineVolumeRaw(null)).toBe("-");
});

test("today headline never mixes a missing price with another session change", () => {
  expect(
    resolveTodayHeadlineValues({
      backendPrice: 584,
      backendChange: -37,
      backendChangePct: (-37 / 621) * 100,
      currentPrice: 580,
      currentReferenceClose: 621,
      completedSessionPrice: 584,
      completedSessionReferenceClose: 621,
    })
  ).toEqual([584, -37, (-37 / 621) * 100, "backend_headline"]);

  expect(
    resolveTodayHeadlineValues({
      currentPrice: null,
      currentReferenceClose: 592,
      completedSessionPrice: null,
      completedSessionReferenceClose: 591,
    })
  ).toEqual([null, null, null, "unavailable"]);

  expect(
    resolveTodayHeadlineValues({
      currentPrice: null,
      currentReferenceClose: 592,
      completedSessionPrice: 605,
      completedSessionReferenceClose: 592,
    })
  ).toEqual([605, 13, (13 / 592) * 100, "completed_session"]);
});

test("quote depth prefers backend headline and ignores stale indicative data after close", () => {
  expect(
    resolveQuoteDepthHeadlineValues({
      allowIndicative: false,
      indicativeAvailable: true,
      indicativePrice: 601,
      headlinePrice: 584,
      headlineChange: -37,
      headlineChangePct: (-37 / 621) * 100,
      legacyPrice: 580,
      legacyChange: -41,
      legacyChangePct: (-41 / 621) * 100,
      previousClose: 621,
    })
  ).toEqual([584, -37, (-37 / 621) * 100]);

  expect(
    resolveQuoteDepthHeadlineValues({
      allowIndicative: true,
      indicativeAvailable: true,
      indicativePrice: 601,
      headlinePrice: 584,
      headlineChange: -37,
      headlineChangePct: (-37 / 621) * 100,
      legacyPrice: 580,
      legacyChange: -41,
      legacyChangePct: (-41 / 621) * 100,
      previousClose: 621,
    })
  ).toEqual([601, -20, (-20 / 621) * 100]);
});

test("close marker stays visible but separate from interval indicators", () => {
  const aggregated = aggregateIntradayPoints(
    [
      {
        time: "2026-08-31T13:25:00+08:00",
        price: 580,
        volume: 1000,
        open: 579,
        high: 581,
        low: 579,
        bar_type: "closing_auction",
        display_eligible: true,
        indicator_eligible: true,
      },
      {
        time: "2026-08-31T13:26:00+08:00",
        price: 581,
        volume: 1000,
        open: 580,
        high: 582,
        low: 580,
        bar_type: "closing_auction",
        display_eligible: true,
        indicator_eligible: true,
      },
      {
        time: "2026-08-31T13:30:00+08:00",
        price: 584,
        volume: null,
        open: 584,
        high: 584,
        low: 584,
        bar_type: "official_close_marker",
        price_semantics: "official_close",
        display_eligible: true,
        indicator_eligible: false,
      },
    ],
    5,
    taiwanIntradaySession,
    "2026-08-31"
  );

  expect(aggregated).toHaveLength(2);
  expect(aggregated[0].price).toBe(581);
  expect(aggregated[0].indicator_eligible).toBe(true);
  expect(aggregated[1].bar_type).toBe("official_close_marker");
  expect(aggregated[1].price).toBe(584);
  expect(aggregated[1].indicator_eligible).toBe(false);

  const enriched = enrichIntradayPoints(aggregated);
  expect(enriched[1].twap).toBeNull();
  expect(enriched[1].vwap).toBeNull();
  expect(enriched[1].emaFast).toBeNull();
});

test("Taiwan technical mapping keeps finalized decision and provisional observation separate", () => {
  const report: StockTechnicalReportRead = {
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
    warnings: ["Provisional current observation is not decision-usable."],
    source_refs: [],
  };

  const mapped = mapBackendTechnicalReport(report);

  expect(mapped.decisionState?.position.price).toBe(592);
  expect(mapped.decisionStateTime).toBe("2026-08-26");
  expect(mapped.currentObservation?.currentState?.position.price).toBe(605);
  expect(mapped.currentObservation?.decisionUsable).toBe(false);
  expect(mapped.currentObservation?.officialDailyConfirmed).toBe(false);
});

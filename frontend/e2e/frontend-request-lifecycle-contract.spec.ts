import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createServer, type ServerResponse } from "node:http";
import { runInNewContext } from "node:vm";
import ts from "typescript";

import { expect, test } from "@playwright/test";

// Real HTTP headers and partial bodies, using the actual API module. No backend
// or provider participates; every socket is owned and closed by this fixture.
async function withStreamingApi(run: (host: {
  api: typeof import("../src/lib/api");
  headers: () => number;
  held: ServerResponse[];
}) => Promise<void>) {
  const held: ServerResponse[] = [];
  const server = createServer((request, response) => {
    if (request.url?.includes("/empty")) { response.writeHead(204).end(); return; }
    if (request.url?.includes("/invalid")) { response.end("{invalid"); return; }
    if (request.url?.includes("/http")) {
      response.writeHead(503, { "x-request-id": "fixture-request" });
      response.end(JSON.stringify({ error: { message: "unavailable", code: "fixture" } }));
      return;
    }
    if (request.url?.includes("/ok")) { response.end('{"ok":true}'); return; }
    response.writeHead(request.url?.includes("/error-body") ? 503 : 200, { "Content-Type": "application/json" });
    response.flushHeaders();
    response.write('{"ok":');
    held.push(response);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing fixture port");
  let headers = 0;
  const exports = {};
  runInNewContext(ts.transpileModule(source("src/lib/api.ts"), {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText, {
    exports, process: { env: {} }, window: { location: { origin: `http://127.0.0.1:${address.port}` } },
    URL, Headers, AbortController, Error, SyntaxError, TypeError, setTimeout, clearTimeout,
    fetch: async (...args: Parameters<typeof fetch>) => { const response = await fetch(...args); headers++; return response; },
  });
  try {
    await run({ api: exports as typeof import("../src/lib/api"), headers: () => headers, held });
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
}

async function boundedOutcome(promise: Promise<unknown>, waitMs: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      promise.then((value) => ({ value }), (error: unknown) => ({ error })),
      new Promise<{ pending: true }>((resolve) => { timer = setTimeout(() => resolve({ pending: true }), waitMs); }),
    ]);
  } finally { clearTimeout(timer); }
}

test.describe("API body lifecycle", () => {
  test("default GET deadline covers already returned headers and never-ending body", async () => {
    test.setTimeout(27_000);
    await withStreamingApi(async ({ api, headers }) => {
      const started = Date.now();
      const outcome = boundedOutcome(api.fetchJson("/api/stalled"), 20_750);
      await expect.poll(headers).toBe(1); // fetch() has resolved, body remains open.
      expect(Date.now() - started).toBeLessThan(5_000);
      expect(await outcome).toMatchObject({ error: { kind: "timeout", path: "/api/stalled" } });
      expect(Date.now() - started).toBeLessThan(20_750);
      expect(await api.fetchJson("/api/ok")).toEqual({ ok: true });
    });
  });

  for (const method of ["GET-error-body", "POST", "DELETE-error-body"]) {
    test(`${method} body uses the same request deadline`, async () => {
      await withStreamingApi(async ({ api, headers }) => {
        const options = { timeoutMs: 200 };
        const request = method === "POST" ? api.requestJson("/api/stalled", { method: "POST" }, undefined, options)
          : method === "DELETE-error-body" ? api.deleteRequest("/api/error-body", undefined, options)
            : api.fetchJson("/api/error-body", undefined, options);
        const outcome = boundedOutcome(request, 1_000);
        await expect.poll(headers).toBe(1);
        expect(await outcome).toMatchObject({ error: { kind: "timeout" } });
      });
    });
  }

  for (const timeoutMs of [0, 20_000]) {
    test(`external abort after headers remains AbortError with timeoutMs=${timeoutMs}`, async () => {
      await withStreamingApi(async ({ api, headers }) => {
        const controller = new AbortController();
        const outcome = boundedOutcome(api.requestJson("/api/stalled", { method: "POST", signal: controller.signal },
          undefined, { timeoutMs }), 1_000);
        await expect.poll(headers).toBe(1);
        controller.abort();
        expect(await outcome).toMatchObject({ error: { name: "AbortError" } });
      });
    });
  }

  test("body disconnect is network; malformed JSON and HTTP detail retain their own kinds", async () => {
    await withStreamingApi(async ({ api, headers, held }) => {
      const outcome = boundedOutcome(api.fetchJson("/api/stalled"), 1_000);
      await expect.poll(headers).toBe(1);
      held[0].destroy();
      expect(await outcome).toMatchObject({ error: { kind: "network" } });
      expect(await boundedOutcome(api.fetchJson("/api/invalid"), 1_000)).toMatchObject({ error: { kind: "invalid_response", status: 200 } });
      expect(await boundedOutcome(api.fetchJson("/api/http"), 1_000)).toMatchObject({ error: { kind: "http", status: 503, code: "fixture", requestId: "fixture-request" } });
      expect(await api.requestJson("/api/empty", { method: "POST" })).toBeNull();
      expect(await api.deleteRequest("/api/empty")).toBeUndefined();
      expect(await api.requestJson("/api/ok", { method: "POST", body: "{}" }, undefined, { timeoutMs: 0 })).toEqual({ ok: true });
    });
  });
});

function source(path: string) {
  return readFileSync(join(process.cwd(), path), "utf8");
}

function section(contents: string, start: string, end: string) {
  const startIndex = contents.indexOf(start);
  const endIndex = contents.indexOf(end, startIndex + start.length);
  expect(startIndex, `missing section start: ${start}`).toBeGreaterThanOrEqual(0);
  expect(endIndex, `missing section end: ${end}`).toBeGreaterThan(startIndex);
  return contents.slice(startIndex, endIndex);
}

test("dashboard SSR resolves the active market before bounded bootstrap reads", () => {
  const contents = source("src/app/page.tsx");
  const clientContents = source("src/components/MarketDashboardClient.tsx");

  expect(contents.indexOf("const initialMarket =")).toBeLessThan(
    contents.indexOf("] = await Promise.all([")
  );
  expect(contents).toContain('initialMarket === "tw"');
  expect(contents).toContain('initialMarket === "us"');
  expect(contents).toContain('initialMarket === "jp"');
  expect(contents).toContain('initialMarket === "kr"');
  expect(contents).not.toContain("/api/market/chart/");
  expect(contents).not.toContain("initialChartBundle");
  expect(contents).not.toContain("/api/market/ohlc/");
  expect(contents).not.toContain("/api/market/indicators/");
  expect(contents).not.toContain("/api/market/calendar-status");
  expect(clientContents).toContain('activeMarket !== "tw"');
  expect(clientContents).toContain('fetchJson<WatchlistGroupNode[]>("/api/watchlists/tree")');
  expect(clientContents).toContain("reconcileTaiwanExplorer(tree, items)");
});

test("Taiwan chart renders Bars before revision-bound Technical", () => {
  const contents = source(
    "src/components/stock-detail/useTaiwanStockChartData.ts"
  );

  expect(contents).toContain("TAIWAN_CHART_REFRESH_LIMIT = 8");
  expect(contents).toContain("TAIWAN_CHART_REFRESH_MIN_MS = 15_000");
  expect(contents).toContain("chartRefreshIntervalMs(interval)");
  expect(contents).toMatch(/fullSnapshot\s*\? requestLimit/);
  expect(contents).toContain(": TAIWAN_CHART_REFRESH_LIMIT");
  expect(contents).toContain("mergeTimedPoints(previous.trend, incomingTrend)");
  expect(contents).toContain("readTodayPresentation(");
  expect(contents).toContain("`/api/market/bars/${effectStockId}/chart`");
  expect(contents).toContain("fetchJson<TaiwanChartBarSeriesRead>");
  expect(contents).toContain("`/api/market/technical/${effectStockId}/series`");
  expect(contents).toContain("expected_snapshot_revision: expectedRevision");
  expect(contents).toContain("expected_series_revision: expectedRevision");
  expect(contents).toContain("lastSuccessfulTechnicalRevision === expectedRevision");
  expect(contents).toContain("contract: technical.parameter_contract ?? {}");
  expect(contents).toContain("technical.current_partial?.point ?? null");
  expect(contents).toContain(
    "mergeTimedPoints(finalizedIndicators, [currentPartialIndicator])"
  );
  expect(contents).toContain("expected_snapshot_revision: requestedExactRevision");
  expect(contents).toContain(
    '(!needsFullRecovery && responseSnapshotPhase !== "warming")'
  );
  expect(contents.indexOf("setLoadStateScope({ requestKey: effectRequestKey, state: \"success\" })")).toBeLessThan(
    contents.indexOf("void loadTechnical(series, fullSnapshot)")
  );
  expect(contents).not.toContain("/api/market/chart/${effectStockId}");
  expect(contents).not.toContain("initialChartBundle");
  expect(contents).not.toContain('ma_windows: "5,20,60"');
  expect(contents).not.toContain('volume_ma_windows: "5,20"');
  const panel = source("src/components/StockDetailPanel.tsx");
  expect(panel).toContain(
    "technicalParameterContract ?? technicalContract?.parameter_contract.defaults"
  );
});

test("Taiwan technical report cadence is independent of chart timestamps", () => {
  const contents = source(
    "src/components/stock-detail/useTaiwanTechnicalReport.ts"
  );

  expect(contents).toContain("TAIWAN_TECHNICAL_REPORT_REFRESH_MS = 60_000");
  expect(contents).toContain("TAIWAN_TECHNICAL_REPORT_INITIAL_DELAY_MS = 1_500");
  expect(contents).toContain(
    "}, TAIWAN_TECHNICAL_REPORT_INITIAL_DELAY_MS);"
  );
  expect(contents).not.toContain("todayUpdatedAt");
  expect(contents).toContain('const includeVolumePace = requestedTimeframe === "today"');
  expect(contents).toContain('const includeIntraday = requestedTimeframe === "today" || requestedTimeframe === "daily"');
  expect(contents).toContain('const shouldPoll = requestedTimeframe === "today" || requestedTimeframe === "daily"');
  expect(contents).toContain('["today", "daily", "weekly", "monthly"]');
  expect(contents).toContain("[effectiveTimeframe, enabled, isIndexProduct, stockId, settingsRevision]");
  expect(contents).toContain("reportSettingsRevision === settingsRevision");
});

test("Taiwan Ranking and Radar own separate request lifecycles", () => {
  const ranking = source(
    "src/components/market-dashboard/ranking/useTaiwanRankingState.ts"
  );
  const radar = source(
    "src/components/market-dashboard/radar/useTaiwanRadarState.ts"
  );

  expect(ranking).not.toContain("prepareCompanionLoad");
  expect(ranking).not.toContain("queueCompanionLoad");
  expect(ranking).toContain("WATCHLIST_RANKING_ROW_REVEAL_MS = 24");
  expect(ranking).toContain("for (const [rowIndex, row] of batch.results.entries())");
  expect(ranking).toContain("mergeRankingBatchRows(loadedRows, [row])");
  expect(ranking.match(/refreshDailyPrices/g)).toHaveLength(2);
  expect(radar).toContain("snapshot_only: snapshotOnly");
  expect(radar).toContain("snapshotOnly: true");
  expect(radar).toContain("error instanceof ApiError && error.status === 404");
  expect(radar).toContain('setLoadState("idle")');
  expect(radar).not.toContain(
    "radarParams(currentMode, useIntraday, false, false)"
  );
  expect(radar).not.toContain('ma_windows: "5,20,60"');
  expect(radar).not.toContain('volume_ma_windows: "5,20"');
  expect(ranking).not.toContain('ma_windows: "5,20,60"');
  expect(ranking).not.toContain('volume_ma_windows: "5,20"');
  expect(radar).toContain("WATCHLIST_RADAR_ENHANCEMENT_MS = 60_000");
  expect(radar).toContain("preferSnapshot: false");
  expect(radar).toContain("snapshotOnly: false");
});

test("Taiwan regular eligibility stops before the closing auction", () => {
  const marketTime = source("src/lib/taiwanMarketTime.ts");

  expect(marketTime).toContain(
    "TAIWAN_REGULAR_SESSION_END_MINUTES = 13 * 60 + 25"
  );
  expect(marketTime).toContain("minutes < TAIWAN_REGULAR_SESSION_END_MINUTES");
  expect(marketTime).toContain("TAIWAN_SESSION_END_MINUTES = 13 * 60 + 30");
});

test("Taiwan secondary surfaces stay cache-only until demanded", () => {
  const panel = source("src/components/StockDetailPanel.tsx");
  const overnight = source(
    "src/components/stock-detail/useTaiwanDetailContext.ts"
  );
  const priceMap = source(
    "src/components/stock-detail/useTaiwanStockPriceMap.ts"
  );

  expect(panel).toContain("enabled: dataSurfaceDemanded");
  expect(panel).toContain('useSurfaceDemand("0px", stockId)');
  expect(panel).toContain("ref={dataSurfaceRef}");
  expect(panel).toContain("enabled: secondarySurfaceDemanded");
  expect(panel).not.toContain(
    'enabled: secondarySurfaceDemanded && loadState === "success"'
  );
  expect(panel).toContain("demandDataSurface()");
  expect(panel).toContain("overnightEnabled: overnightDemanded");
  expect(panel).toContain("<TaiwanStockDetailRadarSurface");
  expect(panel).toContain("secondarySurfaceDemanded &&");
  expect(panel).toContain('(loadState === "success" || loadState === "error")');
  expect(priceMap).toContain("requestedCandidate === null ? 0 : 250");
  expect(priceMap).not.toContain("1_800");
  expect(priceMap).toContain("/price-map");
  expect(panel).toContain("onOvernightDemand={() => setOvernightDemanded(true)}");
  expect(panel).toContain(
    "quoteDepthCurrentObservation(selectedQuoteDepth)"
  );
  expect(panel).toContain("quoteDepth?.last_trade_price ?? null");
  expect(panel).not.toContain(
    "quoteDepth.actual_trade_occurred === true ? currentPrice : null"
  );
  expect(panel).toContain("taiwanReferencePrice(selectedQuoteDepth,");
  expect(panel).not.toContain("todayPreviousClose ??");
  expect(panel).toContain(
    "isIndexProduct ? selectedIndexSnapshot?.previous_close ?? null : null"
  );
  expect(overnight).toContain("{ refresh: false }");
  expect(overnight).not.toContain("requestBackfillJob");
  expect(overnight).not.toContain('method: "POST"');
});

test("Taiwan Stock Detail Radar v2 is the only production technical surface", () => {
  const panel = source("src/components/StockDetailPanel.tsx");
  const radar = source(
    "src/components/stock-detail/TaiwanStockDetailRadarSurface.tsx"
  );
  const priceMap = source("src/components/stock-detail/StockPriceMap.tsx");
  const marketTypes = source("src/types/market.ts");

  expect(panel.match(/<TaiwanStockDetailRadarSurface/g)).toHaveLength(1);
  expect(panel).not.toContain("<TechnicalCurrentStateOverview");
  expect(panel).not.toContain("<TechnicalCurrentStateEvidence");
  expect(panel).not.toContain("<TechnicalMetricBar");
  expect(panel).not.toContain("<OvernightImpactPanel");
  expect(radar).toContain('data-testid="tw-stock-detail-radar-v2"');
  expect(radar).toContain('data-testid="tw-stock-detail-radar-decision-changes"');
  expect(radar).toContain('testId="tw-stock-detail-radar-evidence"');
  expect(radar).toContain('testId="tw-stock-detail-radar-external"');
  expect(priceMap).toContain('data-testid="tw-stock-price-axis"');
  expect(priceMap).toContain("axisPosition(zone.anchor_price");
  expect(priceMap).toContain('data-testid="tw-stock-price-map-outside-axis"');
  expect(priceMap).toContain("zonesWithinAxis(map)");
  expect(priceMap).toContain("zonesOutsideAxis(map)");
  expect(priceMap).not.toContain("space-y-1 before:absolute");
  expect(marketTypes).toContain('version: "tw.stock.price_map.v4" | string');
  expect(marketTypes).toContain('range_kind: "display_range" | "unavailable"');
  expect(marketTypes).toContain("basis_revision: string");
  expect(marketTypes).toContain("evidence_lower_bound: number");
  expect(marketTypes).toContain("tier_label: string");
  expect(marketTypes).toContain("decision_changes: Array");
  expect(priceMap).toContain("layoutTriggers(map)");
  expect(priceMap).toContain("data-evidence-bounds");
  expect(priceMap).toContain('data-testid="tw-stock-price-map-accessible-details"');
});

test("Taiwan data panel loads stock identity before active-tab resources", () => {
  const contents = source(
    "src/components/stock-detail/useTaiwanDataPanel.ts"
  );
  const identityLoader = section(
    contents,
    "async function loadBasicDetail()",
    "function dataTabHasCurrentData("
  );

  expect(identityLoader).toContain("`/api/stocks/${requestedStockId}`");
  expect(identityLoader).not.toContain("/institutional/");
  expect(identityLoader).not.toContain("/margin/");
  expect(identityLoader).not.toContain("/revenue/");
  expect(contents).toContain("const shareholdingHistoryLimit = 2_400");
  expect(contents).toContain("{ limit: shareholdingHistoryLimit, ensure_history: false }");
  expect(contents).not.toContain("{ limit: 12_000, ensure_history: false }");
  expect(contents).toContain('setActiveDataTab("chips")');
});

test("Taiwan index detail only uses a current canonical previous close", () => {
  const panel = source("src/components/StockDetailPanel.tsx");
  const indexViews = source("src/components/stock-detail/IndexDataViews.tsx");

  expect(panel).not.toContain("todayPreviousClose={todayPreviousClose}");
  expect(indexViews).toContain('index?.previous_close_status === "current"');
  expect(indexViews).not.toContain(
    "todayPreviousClose ?? index?.previous_close ?? null"
  );
});

test("US detail chart, intraday, and supplemental resources have separate owners", () => {
  const contents = source("src/components/USStockDetailPanel.tsx");
  const chartLoader = section(
    contents,
    "const loadChartData = useCallback(",
    "const loadSupplementalData = useCallback("
  );
  const supplementalLoader = section(
    contents,
    "const loadSupplementalData = useCallback(",
    "useEffect(() => {"
  );

  expect(contents).not.toContain("loadSymbolData");
  expect(chartLoader).toContain("/api/us-market/ohlc/");
  expect(chartLoader).not.toContain("fetchUsIntradayTrend");
  expect(chartLoader).not.toContain("fetchUsSupplementalData");
  expect(supplementalLoader).toContain("fetchUsSupplementalData(symbol, tab, controller.signal)");
  expect(contents).toContain('if (tab === "financials")');
  expect(contents).toContain("institutional-holdings");
  expect(contents).toContain("!chartMatchesSelection");
  expect(contents).not.toContain("void loadSupplementalData(selectedSymbol, generation)");
  expect(contents).toContain("setTodaySessionScope(intradaySessionScope)");
  expect(contents).toContain('/api/us-market/truth/${encodeURIComponent(symbol)}');
  expect(contents).toContain('if (!selectedSymbol || timeframe !== "today") return;');
  expect(contents).not.toContain('/api/us-market/quote/${encodeURIComponent(symbol)}');
  expect(contents).toContain("since_revision: sinceRevision");
  expect(contents).toContain('today.response_mode === "unchanged"');
  expect(contents).toContain("snapshots.set(snapshotKey");
  expect(contents).toContain("todayIntervalRef.current,");
  expect(contents).toContain("US_TODAY_SNAPSHOT_CACHE_LIMIT = 48");
  expect(contents).toContain("chart?.snapshotRevision === dailySnapshotRevision");
  expect(contents).toContain(
    'status.freshness_status === "provider_error" && status.has_usable_data'
  );
  expect(contents).toContain(
    'status.status === "ok" || status.freshness_status === "current"'
  );
  expect(contents).toContain('chartLoadState === "loading" && timeframe !== "today"');
  expect(contents).toContain(
    'todayRequestState !== "error"'
  );
  expect(contents).toContain('t("usStockDetail.extendedHours.loadingCache")');
  expect(contents).not.toContain("response.bar_source_status ?? response.source_status");
  expect(contents).not.toContain('if (timeframe === "today" && !todayMatchesSelection) return;');
  expect(contents).not.toContain("finalIntradayRefreshDate");
  expect(contents).toContain('setTodayRequest({ key: requestKey, state: "error" })');
  expect(contents).toContain("canonicalIndicatorAuthority=\"backend\"");
  expect(contents).toContain("indicatorData={technicalIndicatorSeries}");
  expect(contents).toContain("indicatorData={professionalIndicatorData}");
  expect(contents).toContain("interval={todayInterval}");
  expect(contents).toContain("onIntervalChange={setTodayInterval}");
  expect(contents).toContain("{ bars: 260, timeframe: researchTimeframe }");
  expect(contents).not.toContain('canonicalIndicatorAuthority="presentation"');
  expect(contents).not.toContain("intradaySessionScope,\n      onCompanyProfileChange");
});

test("US market tape keeps Daily analytics separate from canonical headline polling", () => {
  const contents = source(
    "src/components/market-dashboard/tape/useRegionalMarketTapeState.ts"
  );
  const referenceLoader = section(
    contents,
    "async function fetchUsMarketTapeReferenceSnapshot",
    "async function fetchJpMarketTapeSnapshot"
  );
  const headlineLoader = section(
    contents,
    "function useUsMarketHeadlineItems",
    "function usRefreshDelay"
  );

  expect(referenceLoader).toContain("/api/us-market/ohlc/");
  expect(referenceLoader).not.toContain("/api/us-market/intraday/");
  expect(headlineLoader).toContain('"/api/us-market/indices"');
  expect(headlineLoader).not.toContain("/api/us-market/quote/");
  expect(headlineLoader).not.toContain("/api/us-market/ohlc/");
  expect(contents).toContain("refreshDelay: regionalDailyRefreshDelay");
  expect(headlineLoader).toContain(
    "authoritativeMarketSession = snapshot.market_session"
  );
  expect(headlineLoader).toContain(
    "usHeadlineRefreshDelay(authoritativeMarketSession)"
  );
  expect(contents).not.toContain("fetchUsMarketTapeLiveSnapshot");
  expect(contents).not.toContain("composeUsMarketTapeSnapshot");
});

test("US ranking requests current quotes without full-intraday fan-out", () => {
  const contents = source(
    "src/components/market-dashboard/ranking/useUsRankingState.ts"
  );
  const legacyPanel = source("src/components/USWatchlistRankingPanel.tsx");

  expect(contents).toContain("use_current_quote: marketState.isPollingWindow");
  expect(contents).not.toContain("use_intraday: marketState.isPollingWindow");
  expect(contents).toContain("requestAbortRef.current?.abort()");
  expect(legacyPanel).toContain("use_current_quote: marketState.isLiveWindow");
  expect(legacyPanel).not.toContain("use_intraday: marketState.isLiveWindow");
  expect(legacyPanel).toContain("requestAbortRef.current?.abort()");
});

test("US local calendar fallback is display-only and polling fails closed", () => {
  const contents = source("src/lib/usMarketTime.ts");
  const fallback = section(
    contents,
    "const isTradingDay = isUsWeekday(parts);",
    "export function getUsIntradayXRatio"
  );

  expect(fallback).toContain("calendarAuthoritative: false");
  expect(fallback).toContain("isPollingWindow: false");
  expect(fallback).toContain("isExtendedPollingWindow: false");
  expect(fallback).toContain("isLiveWindow: false");
  expect(fallback).toContain("isAfterClose: false");
});

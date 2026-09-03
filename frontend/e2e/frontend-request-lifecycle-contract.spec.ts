import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

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
  expect(contents).toContain("include_volume_pace: false");
  expect(contents).toContain("[effectiveTimeframe, enabled, isIndexProduct, stockId]");
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

  expect(panel).toContain("enabled: dataSurfaceDemanded");
  expect(panel).toContain('useSurfaceDemand("0px", stockId)');
  expect(panel).toContain("ref={dataSurfaceRef}");
  expect(panel).toContain("enabled: secondarySurfaceDemanded");
  expect(panel).not.toContain(
    'enabled: secondarySurfaceDemanded && loadState === "success"'
  );
  expect(panel).toContain("demandDataSurface()");
  expect(panel).toContain("overnightEnabled: overnightDemanded");
  expect(panel).toContain(
    "enabled: nextSessionDemanded && !isIndexProduct && !isEtfProduct"
  );
  expect(panel).toContain("onDemand={() => setNextSessionDemanded(true)}");
  expect(panel).toContain("onDemand={() => setOvernightDemanded(true)}");
  expect(panel).toContain(
    "todayCurrentObservation ?? quoteDepthCurrentObservation(selectedQuoteDepth)"
  );
  expect(panel).toContain("quoteDepth?.last_trade_price ?? null");
  expect(panel).not.toContain(
    "quoteDepth.actual_trade_occurred === true ? currentPrice : null"
  );
  expect(panel).toContain(
    "todayPreviousClose ?? selectedQuoteDepth?.previous_close ?? null"
  );
  expect(overnight).toContain("{ refresh: false }");
  expect(overnight).not.toContain("requestBackfillJob");
  expect(overnight).not.toContain('method: "POST"');
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
  expect(supplementalLoader).toContain("fetchUsSupplementalData(symbol, tab)");
  expect(contents).toContain('if (tab === "financials")');
  expect(contents).toContain("institutional-holdings");
  expect(contents).toContain("!chartMatchesSelection");
  expect(contents).not.toContain("void loadSupplementalData(selectedSymbol, generation)");
  expect(contents).toContain("setTodaySessionScope(intradaySessionScope)");
  expect(contents).toContain('/api/us-market/quote/${encodeURIComponent(symbol)}');
  expect(contents).toContain('if (!selectedSymbol || timeframe !== "today") return;');
  expect(contents).toContain('if (!selectedSymbol || timeframe === "today") return;');
  expect(contents).toContain("since_revision: sinceRevision");
  expect(contents).toContain('today.response_mode === "unchanged"');
  expect(contents).toContain("snapshots.set(snapshotKey");
  expect(contents).toContain("applyCachedTodaySnapshot(selectedSymbol, intradaySessionScope, cachedSnapshot)");
  expect(contents).toContain("US_TODAY_SNAPSHOT_CACHE_LIMIT = 48");
  expect(contents).toContain("if (today.quote_snapshot) setHeadlineQuote(today.quote_snapshot)");
  expect(contents).toContain(
    'status.freshness_status === "provider_error" && status.has_usable_data'
  );
  expect(contents).toContain(
    'status.status === "ok" || status.freshness_status === "current"'
  );
  expect(contents).toContain('chartLoadState === "loading" && timeframe !== "today"');
  expect(contents).toContain(
    'const todayIntradayLoading = timeframe === "today" && !todayMatchesSelection;'
  );
  expect(contents).toContain('t("usStockDetail.extendedHours.loadingCache")');
  expect(contents).not.toContain("response.bar_source_status ?? response.source_status");
  expect(contents).toContain('if (timeframe === "today" && !todayMatchesSelection) return;');
  expect(contents).toContain("visibleMarketResearch !== null ||");
  expect(contents).not.toContain("intradaySessionScope,\n      onCompanyProfileChange");
});

test("US market tape keeps daily reference and live polling on separate cadences", () => {
  const contents = source(
    "src/components/market-dashboard/tape/useRegionalMarketTapeState.ts"
  );
  const referenceLoader = section(
    contents,
    "async function fetchUsMarketTapeReferenceSnapshot",
    "async function fetchUsMarketTapeLiveSnapshot"
  );
  const liveLoader = section(
    contents,
    "async function fetchUsMarketTapeLiveSnapshot",
    "function composeUsMarketTapeSnapshot"
  );

  expect(referenceLoader).toContain("/api/us-market/ohlc/");
  expect(referenceLoader).not.toContain("/api/us-market/intraday/");
  expect(liveLoader).toContain("/api/us-market/quote/");
  expect(liveLoader).not.toContain("/api/us-market/intraday/");
  expect(liveLoader).not.toContain("/api/us-market/ohlc/");
  expect(contents).toContain("refreshDelay: regionalDailyRefreshDelay");
  expect(contents).toContain("refreshDelay: usRefreshDelay");
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

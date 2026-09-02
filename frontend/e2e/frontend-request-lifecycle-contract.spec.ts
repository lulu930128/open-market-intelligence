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
  expect(contents).toContain("/api/market/chart/${encodeURIComponent(stockId)}");
  expect(contents).not.toContain("/api/market/ohlc/");
  expect(contents).not.toContain("/api/market/indicators/");
  expect(contents).not.toContain("/api/market/calendar-status");
  expect(clientContents).toContain('activeMarket !== "tw"');
  expect(clientContents).toContain('fetchJson<WatchlistGroupNode[]>("/api/watchlists/tree")');
  expect(clientContents).toContain("reconcileTaiwanExplorer(tree, items)");
});

test("Taiwan chart mount hydrates the canonical bundle and polls a recent window", () => {
  const contents = source(
    "src/components/stock-detail/useTaiwanStockChartData.ts"
  );

  expect(contents).toContain("initialChartBundle: TaiwanChartBundleRead | null");
  expect(contents).toContain("TAIWAN_CHART_REFRESH_LIMIT = 8");
  expect(contents).toContain("hydratedBundle.consumed = true");
  expect(contents).toMatch(/showLoading\s*\? requestLimit/);
  expect(contents).toContain(": TAIWAN_CHART_REFRESH_LIMIT");
  expect(contents).toContain("mergeTimedPoints(previous.trend, incomingTrend)");
  expect(contents).not.toContain("initialChartData:");
  expect(contents).not.toContain("initialIndicatorData:");
});

test("Taiwan technical report cadence is independent of chart timestamps", () => {
  const contents = source(
    "src/components/stock-detail/useTaiwanTechnicalReport.ts"
  );

  expect(contents).toContain("TAIWAN_TECHNICAL_REPORT_REFRESH_MS = 60_000");
  expect(contents).not.toContain("todayUpdatedAt");
  expect(contents).toContain("[effectiveTimeframe, isIndexProduct, stockId]");
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
  expect(contents).toContain("[loadChartData, selectedSymbol, timeframe]");
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

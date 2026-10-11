import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, test } from "@playwright/test";
import ts from "typescript";

const source = readFileSync("src/components/USStockDetailPanel.tsx", "utf8");
const loader = source.slice(source.indexOf("  const loadChartData = useCallback("), source.indexOf("  const loadSupplementalData = useCallback("));

function chartHost() {
  const pending: Array<{ signal: AbortSignal; resolve: (data: unknown) => void; reject: (error: unknown) => void; params: unknown }> = [];
  const charts: unknown[] = [];
  const states: string[] = [];
  const sequence = { current: 1 };
  const run = runInNewContext(ts.transpileModule(`${loader}\nloadChartData;`, {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText, {
    AbortController,
    useCallback: (callback: unknown) => callback,
    chartControllerRef: { current: null }, requestSeq: sequence, chartRequestSeq: { current: 0 },
    chartReadInFlightRef: { current: false }, setChartCompletion: () => {},
    setLoadState: (value: string) => states.push(value),
    setChartRequestScope: () => {},
    setChart: (value: unknown) => charts.push(value),
    barsByTimeframe: { daily: 180, weekly: 120, monthly: 60 },
    getUsMarketIndexConfig: () => null,
    usSymbolKey: (value: string) => value.toUpperCase(),
    publishDetailDataStatus: () => {}, tRef: { current: (value: string) => value },
    onDailyPricesChangedRef: { current: null },
    fetchJson: (_path: string, params: unknown, options: { signal: AbortSignal }) => new Promise((resolve, reject) => {
      // Deliberately ignore abort completion to exercise generation as well as
      // transport cancellation; a late body must still be rejected.
      pending.push({ signal: options.signal, resolve, reject, params });
    }),
  }) as (symbol: string, timeframe: string, revision: string) => Promise<void>;
  return { run, pending, charts, states, sequence };
}

test("G4 superseded chart HTTP aborts and ignored-abort late bodies cannot overwrite", async () => {
  const host = chartHost();
  const old = host.run("SSO", "daily", "old");
  host.sequence.current += 1;
  const current = host.run("AMD", "daily", "new");
  expect(host.pending[0].signal.aborted).toBe(true);
  expect(host.pending[1].params).toEqual({ timeframe: "daily", bars: 180 });
  host.pending[1].resolve({ symbol: "AMD", timeframe: "daily", points: [{ close: 100 }] });
  await current;
  host.pending[0].resolve({ symbol: "SSO", timeframe: "daily", points: [{ close: 999 }] });
  await old;
  expect(host.charts).toEqual([{ symbol: "AMD", timeframe: "daily", points: [{ close: 100 }], snapshotRevision: "new" }]);
});

test("G4 symbol/timeframe mismatch and HTTP failure terminate without clearing valid chart", async () => {
  const host = chartHost();
  const valid = host.run("AAPL", "daily", "r1");
  host.pending[0].resolve({ symbol: "AAPL", timeframe: "daily", points: [{ close: 10 }] });
  await valid;
  const mismatch = host.run("AAPL", "daily", "r2");
  host.pending[1].resolve({ symbol: "AMD", timeframe: "weekly", points: [] });
  await mismatch;
  expect(host.states.at(-1)).toBe("error");
  expect(host.charts).toHaveLength(1);
  const failed = host.run("AAPL", "daily", "r2");
  host.pending[2].reject(new Error("API 500: fixture"));
  await failed;
  expect(host.states.at(-1)).toBe("error");
  expect(host.charts).toHaveLength(1);
});

test("G4 all supplemental leaf reads receive the tab AbortSignal and preserve partial results", async () => {
  const text = source.slice(source.indexOf("async function fetchUsSupplementalData("), source.indexOf("const usIntradaySession:"));
  const signals: AbortSignal[] = [];
  const controller = new AbortController();
  const fetch = async (path: string, _params: unknown, options: { signal: AbortSignal }) => {
    signals.push(options.signal);
    if (path.endsWith("/financials")) throw new Error("fixture timeout");
    return path.endsWith("/facts") ? [{ value: 10 }] : { symbol: "SSO" };
  };
  const run = runInNewContext(ts.transpileModule(`${text}\nfetchUsSupplementalData;`, {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText, { fetchJson: fetch, fetchOptionalJson: fetch });
  const partial = await run("SSO", "financials", controller.signal);
  expect(partial.factData).toEqual([{ value: 10 }]);
  expect(partial.financialData).toBeUndefined();
  expect(partial.requestErrors).toHaveLength(1);
  for (const tab of ["overview", "filings", "short", "insider", "institutions"]) await run("SSO", tab, controller.signal);
  expect(signals).toHaveLength(13);
  expect(signals.every((signal) => signal === controller.signal)).toBe(true);
  controller.abort();
  expect(signals.every((signal) => signal.aborted)).toBe(true);
});

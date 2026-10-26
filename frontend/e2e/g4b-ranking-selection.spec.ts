import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, test, type Page } from "@playwright/test";
import ts from "typescript";
import { usTruthResponse } from "./fixtures/usMarketTruth";
import usDistributionFixture from "./fixtures/usSectorDistribution.json";

// Reuse the current G4 route fixtures without modifying/registering its tests.
// Remove only top-level test registrations; fixture bodies stay intact.
const smokeSource = readFileSync("e2e/omi-smoke.spec.ts", "utf8");
const ast = ts.createSourceFile("omi-smoke.ts", smokeSource, ts.ScriptTarget.Latest, true);
const fixturesSource = ast.statements.filter((statement) => !(
  ts.isExpressionStatement(statement) && ts.isCallExpression(statement.expression) &&
  /^(test|test\..+)$/.test(statement.expression.expression.getText(ast))
)).map((statement) => statement.getFullText(ast)).join("\n");
type Responder = (request: { path: string; url: URL }) => unknown;
type Fixtures = {
  mockG4Detail: (page: Page, responder: Responder) => Promise<void>;
  mockOmiApi: (page: Page, options: Record<string, unknown>) => Promise<void>;
  usOhlcResponse: (symbol: string) => unknown;
  usMarketResearchResponse: (symbol: string, timeframe: string) => unknown;
  seededJpWatchlistTree: () => unknown;
  seededJpWatchlistItems: () => unknown;
  seededJpRankingRows: () => unknown;
  seededKrWatchlistTree: () => unknown;
  seededKrWatchlistItems: () => unknown;
  seededKrRankingRows: () => unknown;
};
const names = ["mockG4Detail", "mockOmiApi", "usOhlcResponse", "usMarketResearchResponse",
  "seededJpWatchlistTree", "seededJpWatchlistItems", "seededJpRankingRows",
  "seededKrWatchlistTree", "seededKrWatchlistItems", "seededKrRankingRows"];
const fixtures = runInNewContext(ts.transpileModule(`${fixturesSource}\n({${names.join(",")}});`, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
}).outputText, {
  exports: {}, URL, setTimeout, clearTimeout, console,
  require: (name: string) => {
    if (name === "@playwright/test") return { test, expect };
    if (name === "./fixtures/usMarketTruth") return { usTruthResponse };
    if (name === "./fixtures/usSectorDistribution.json") return usDistributionFixture;
    throw new Error(`Unexpected G4 fixture dependency: ${name}`);
  },
}) as Fixtures;

type Entry = { kind: string; symbol?: string; type?: string; url: string; prevented?: boolean };
async function instrument(page: Page) {
  await page.evaluate(() => {
    type Callback = (() => void) & { g4b?: boolean };
    type Row = { symbol: string; onSelect: Callback };
    type Fiber = { memoizedProps?: { rows?: Row[] }; pendingProps?: { rows?: Row[] }; return?: Fiber; alternate?: Fiber };
    type Handler = ((event: MouseEvent) => void) & { g4b?: boolean };
    const events: Array<Record<string, unknown>> = [];
    Object.assign(window, { g4bEvents: events });
    const stamp = (entry: Record<string, unknown>) => events.push({ at: performance.now(), url: location.search, ...entry });
    const wrap = () => {
      document.querySelectorAll<HTMLElement>("[data-ranking-symbol]").forEach((element) => {
        const record = element as unknown as Record<string, unknown>;
        const propsKey = Object.keys(element).find((key) => key.startsWith("__reactProps$"));
        if (propsKey) {
          const props = record[propsKey] as Record<string, Handler>;
          for (const name of ["onMouseDown", "onPointerUp", "onClick"]) {
            const original = props[name];
            if (!original || original.g4b) continue;
            props[name] = Object.assign((event: MouseEvent) => {
              stamp({ kind: "handler", type: name, symbol: element.dataset.rankingSymbol });
              original(event);
              stamp({ kind: "handler-result", type: name, symbol: element.dataset.rankingSymbol, prevented: event.defaultPrevented });
            }, { g4b: true });
          }
        }
        const fiberKey = Object.keys(element).find((key) => key.startsWith("__reactFiber$"));
        let fiber = fiberKey ? record[fiberKey] as Fiber : undefined;
        while (fiber) {
          for (const props of [fiber.memoizedProps, fiber.pendingProps, fiber.alternate?.memoizedProps, fiber.alternate?.pendingProps]) {
            for (const row of props?.rows ?? []) {
              if (row.onSelect.g4b) continue;
              const original = row.onSelect;
              row.onSelect = Object.assign(() => { stamp({ kind: "onSelect", symbol: row.symbol }); original(); }, { g4b: true });
            }
          }
          fiber = fiber.return;
        }
      });
    };
    for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click", "auxclick", "keydown"]) {
      document.addEventListener(type, (event) => {
        const target = (event.target as Element)?.closest<HTMLElement>("[data-ranking-symbol]");
        if (!target) return;
        wrap();
        const mouse = event as MouseEvent;
        stamp({ kind: "dom", type, symbol: target.dataset.rankingSymbol, button: mouse.button,
          x: mouse.clientX, y: mouse.clientY, rows: [...document.querySelectorAll<HTMLElement>("[data-ranking-symbol]")]
            .map((row) => ({ symbol: row.dataset.rankingSymbol, top: row.getBoundingClientRect().top })) });
      }, true);
    }
    new MutationObserver(wrap).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    wrap();
  });
}
const row = (page: Page, symbol: string) => page.locator(`[data-ranking-symbol="${symbol}"]`);
const events = (page: Page) => page.evaluate(() => (window as typeof window & { g4bEvents: Entry[] }).g4bEvents);
const selections = async (page: Page) => (await events(page)).filter((event) => event.kind === "onSelect").map((event) => event.symbol);

test.beforeEach(async ({ context }) => {
  // Fail closed before any page exists, including native modifier-click popups.
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const allowed = new URL(test.info().project.use.baseURL as string);
    if (url.origin !== allowed.origin) return route.abort("blockedbyclient");
    return route.continue();
  });
});

async function openUs(page: Page) {
  await fixtures.mockG4Detail(page, ({ path, url }) => {
    const symbol = path.split("/").at(-1)!;
    if (/\/ohlc\//.test(path)) return { body: fixtures.usOhlcResponse(symbol), delayMs: 300 };
    if (/\/truth\//.test(path)) return { body: usTruthResponse(symbol), delayMs: 60 };
    if (/\/research\//.test(path)) return { body: fixtures.usMarketResearchResponse(symbol, url.searchParams.get("timeframe") ?? "daily"), delayMs: 1800 };
    if (/\/sec\//.test(path)) return { body: {}, status: 503, delayMs: 1800 };
    return null;
  });
  await page.goto("/?market=us&group_id=17&symbol=SSO", { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("us-stock-kline-panel").getByRole("img")).toBeVisible();
  await instrument(page);
}

test("G4b mouse AAPL AMD SSO selects exactly once and ends SSO", async ({ page }, info) => {
  await openUs(page);
  const observations = [];
  try {
    for (const symbol of ["AAPL", "AMD", "SSO"]) {
      await row(page, symbol).click();
      await page.waitForTimeout(700); // Same observation window as the G4 P1 trace.
      observations.push({ requested: symbol, url: page.url(), heading: await page.getByTestId("us-stock-kline-panel").locator("h2").innerText() });
    }
    expect(await selections(page)).toEqual(["AAPL", "AMD", "SSO"]);
    await expect(page).toHaveURL(/symbol=SSO/);
    await expect(page.getByTestId("us-stock-kline-panel").locator("h2")).toContainText("SSO");
  } finally {
    await info.attach("mouse-trace", { body: JSON.stringify({ observations, events: await events(page) }, null, 2), contentType: "application/json" });
    await info.attach("mouse-end-state", { body: await page.screenshot(), contentType: "image/png" });
  }
});

test("G4b cross-row press release and standalone pointerup do not select", async ({ page }) => {
  await openUs(page);
  await row(page, "AAPL").hover();
  await page.mouse.down();
  expect(await selections(page)).toEqual([]);
  await expect(page).toHaveURL(/symbol=SSO/);
  await row(page, "AMD").hover();
  await page.mouse.up();
  await row(page, "AMD").dispatchEvent("pointerup", { button: 0, pointerType: "touch" });
  expect(await selections(page)).toEqual([]);
  await expect(page).toHaveURL(/symbol=SSO/);
  await row(page, "AAPL").hover();
  await page.mouse.down();
  await page.mouse.up();
  expect(await selections(page)).toEqual(["AAPL"]);
});

test("G4b rapid native clicks keep one callback per activation", async ({ page }) => {
  await openUs(page);
  const symbols = ["AAPL", "AMD", "SSO", "AMD", "AAPL", "SSO"];
  for (const symbol of symbols) await row(page, symbol).click();
  expect(await selections(page)).toEqual(symbols);
  await expect(page).toHaveURL(/symbol=SSO/);
  await expect(page.getByTestId("us-stock-kline-panel").locator("h2")).toContainText("SSO");
});

test("G4b keyboard Enter activates the anchor once with focus intact", async ({ page }) => {
  await openUs(page);
  await row(page, "AAPL").focus();
  await page.keyboard.press("Enter");
  expect(await selections(page)).toEqual(["AAPL"]);
  await expect(row(page, "AAPL")).toBeFocused();
  await expect(page).toHaveURL(/symbol=AAPL/);
  await expect(row(page, "AAPL")).toHaveAttribute("href", /symbol=AAPL/);
});

test.describe("G4b touch", () => {
  test.use({ hasTouch: true });
  test("native tap selects once", async ({ page }) => {
    await openUs(page);
    for (const symbol of ["AAPL", "AMD", "SSO"]) await row(page, symbol).tap();
    expect(await selections(page)).toEqual(["AAPL", "AMD", "SSO"]);
    await expect(page).toHaveURL(/symbol=SSO/);
  });
});

test("G4b modifiers and middle button preserve native anchor navigation", async ({ page, context }) => {
  await openUs(page);
  // Ctrl-click and middle-click exercise actual browser navigation to href.
  for (const options of [{ modifiers: ["Control"] as ("Control")[] }, { button: "middle" as const }]) {
    const popupPromise = context.waitForEvent("page");
    await row(page, "AAPL").click(options);
    const popup = await popupPromise;
    await popup.waitForURL(/symbol=AAPL/);
    await popup.close();
    expect(await selections(page)).toEqual([]);
    await expect(page).toHaveURL(/symbol=SSO/);
  }
  // Alt is platform-specific (download), Meta varies by OS. Observe cancellation
  // before suppressing only the browser default at document bubble phase.
  await page.evaluate(() => document.addEventListener("click", (event) => {
    if ((event.target as Element).closest("[data-ranking-symbol]")) event.preventDefault();
  }));
  for (const modifier of ["metaKey", "ctrlKey", "shiftKey", "altKey"]) {
    await row(page, "AAPL").dispatchEvent("click", { button: 0, [modifier]: true });
    expect((await events(page)).filter((event) => event.kind === "handler-result").at(-1)?.prevented).toBe(false);
  }
  expect(await selections(page)).toEqual([]);
});

for (const market of ["jp", "kr"] as const) {
  test(`G4b ${market} shared rows preserve selection and href`, async ({ page }) => {
    await fixtures.mockOmiApi(page, market === "jp" ? {
      jpWatchlistTree: fixtures.seededJpWatchlistTree(), jpWatchlistItems: fixtures.seededJpWatchlistItems(), jpRankingRows: fixtures.seededJpRankingRows(),
    } : {
      krWatchlistTree: fixtures.seededKrWatchlistTree(), krWatchlistItems: fixtures.seededKrWatchlistItems(), krRankingRows: fixtures.seededKrRankingRows(),
    });
    await page.goto(`/?market=${market}`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Reload" }).first().click();
    await page.getByText(market === "jp" ? "Japan Core" : "Korea Core", { exact: true }).first().click();
    await expect(page.locator("[data-ranking-symbol]")).toHaveCount(2);
    await instrument(page);
    const symbols = await page.locator("[data-ranking-symbol]").evaluateAll((elements) => elements.map((el) => el.getAttribute("data-ranking-symbol")!));
    for (const symbol of [...symbols, symbols[0]]) {
      await row(page, symbol).click();
      expect(new URL(page.url()).searchParams.get(`${market}_symbol`)).toBe(symbol);
      await expect(row(page, symbol)).toHaveClass(/omi-ranking-row-selected/);
      expect(new URL((await row(page, symbol).getAttribute("href"))!, page.url()).searchParams.get(`${market}_symbol`)).toBe(symbol);
    }
    await row(page, symbols[1]).press("Enter");
    expect(await selections(page)).toEqual([...symbols, symbols[0], symbols[1]]);
  });
}

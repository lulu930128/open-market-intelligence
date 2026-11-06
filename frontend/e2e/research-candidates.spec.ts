import { expect, test, type Page } from "@playwright/test";
import type { NominationSnapshot, ProposalRead } from "../src/types/researchTrade";

const api = "/api/research/trade-proposals";
const asOf = "2026-11-05T09:00:00Z";

function proposal(symbol = "2330", name = "台積電", direction: 1 | -1 = 1): ProposalRead {
  const snapshot: NominationSnapshot = {
    price_map: { payload: { stock_id: symbol, stock_name: name } },
    request: { nomination_origin: "OMI_SCREEN", horizon_sessions: 10 },
    assessment: { status: "qualified", reason_codes: ["SYNTHETIC_COVERAGE_LIMIT"] },
    selected_zones: [{ lower_bound: 99.123456, upper_bound: 100, zone_id: "test-zone" }],
    discovery: { sample_only: true, research_sample_only: true, coverage: { quality_status: "partial" } },
  };
  return {
    status: "proposed", valid_from_date: "2026-11-06", valid_until_date: "2026-11-19", eligibility: null,
    setup_evaluation: { status: "partial", gross_risk: "1234.56789", net_stop_loss: null,
      target_scenarios: [{ gross_rr: "11.3333333333333333333", net_rr: null }], missing_costs: ["commission_rate"] },
    proposal: {
      market: "TW", creation_id: `test-${symbol}`, revision_id: `revision-${symbol}`, revision: 1, supersedes: null, symbol,
      strategy: { version: "test", direction, mode: "aggressive", entry_rule: "at_or_below", entry_price: 99.123456,
        stop_price: 95, targets: [{ price: 110, fraction: 1 }], shares: 1000, thesis: "測試研究假設", counter_evidence: ["測試失效條件"],
        paper_eligibility: "test", qualification_refs: [] }, costs: { version: "test" }, recorded_at: asOf, effective_at: asOf,
      change_reason: "synthetic fixture", evidence_hash: "test", initial_risk_amount: 4123.456, calendar_verified: false, planned_trade_dates: [],
      evidence: { as_of_trade_date: "2026-11-05", cutoff: asOf, price_basis: "raw",
        items: [{ source_ref: "research.stock_nomination.v1", source_available_at: asOf, received_at: asOf, data_revision: "test", snapshot_json: JSON.stringify(snapshot) }] },
    },
  };
}

async function mockResearch(page: Page, items = [proposal(), proposal("3481", "群創", -1)], failList = false) {
  const writes: string[] = [];
  // Every API request is intercepted. These UI checks never write to the live journal.
  await page.route(/\/(?:api|omi-data)\//, async route => {
    const request = route.request();
    if (request.method() !== "GET") {
      writes.push(request.url());
      return route.fulfill({ status: 409, json: { detail: "Synthetic read-only test" } });
    }
    const path = new URL(request.url()).pathname.replace(/^\/omi-data(?=\/)/, "/api");
    const params = new URL(request.url()).searchParams;
    const filtered = items.filter(item => (!params.get("market") || item.proposal.market === params.get("market"))
      && (!params.get("direction") || (item.proposal.strategy.direction === 1 ? "long" : "short") === params.get("direction")));
    const offset = Number(params.get("offset") ?? 0);
    if (path === api) return route.fulfill(failList
      ? { status: 503, json: { detail: "Synthetic list unavailable" } }
      : { json: { projection: "research.proposal_list.summary.v1", evidence_included: false, execution_ready: false,
        as_of: asOf, items: filtered.slice(offset, offset + 20).map(read => {
          const p = read.proposal;
          let frozen: NominationSnapshot = {};
          try {
            const parsed: unknown = JSON.parse(p.evidence.items[0].snapshot_json);
            if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) frozen = parsed as NominationSnapshot;
          } catch { /* Malformed detail fixture has no list identity. */ }
          return { creation_id: p.creation_id, revision_id: p.revision_id, revision: p.revision,
            market: p.market, symbol: p.symbol, stock_name: frozen.price_map?.payload?.stock_id === p.symbol ? frozen.price_map.payload.stock_name ?? null : null,
            direction: p.strategy.direction === 1 ? "long" : "short", status: read.status,
            workflow_origin: read.workflow_origin ?? frozen.request?.nomination_origin,
            as_of_trade_date: p.evidence.as_of_trade_date, cutoff: p.evidence.cutoff,
            recorded_at: p.recorded_at, effective_at: p.effective_at, evidence_hash: p.evidence_hash,
            assessment_status: frozen.assessment?.status, reason_codes: frozen.assessment?.reason_codes ?? [] };
        }), limit: 20, offset, has_more: filtered.length > offset + 20 } });
    const item = items.find(row => path.startsWith(`${api}/${row.proposal.creation_id}`));
    if (item && path.endsWith("/revisions")) return route.fulfill({ json: { creation_id: item.proposal.creation_id, revisions: [item] } });
    if (item && path.endsWith("/monitor")) return route.fulfill({ json: {
      creation_id: item.proposal.creation_id, revision_id: item.proposal.revision_id, status: "DATA_BLOCKED", checked_at: asOf,
      reason_codes: ["SYNTHETIC_MISSING_QUOTE"], price_condition: "UNKNOWN", confirmation: "UNKNOWN", confirmation_basis: "test",
      quote: { freshness: { status: "missing" }, evidence: { value: null } },
      setup_evaluation: { status: "partial", missing_costs: ["commission_rate"], reason_codes: ["SYNTHETIC_CURRENT_COST_LIMIT"] },
      limitations: ["synthetic"], execution_ready: false,
    } });
    if (item) return route.fulfill({ json: item });
    return route.fulfill({ status: 503, json: { detail: "Synthetic unavailable" } });
  });
  return writes;
}

test("names, bounded precision, selection and editing retain original evidence", async ({ page }) => {
  const writes = await mockResearch(page);
  await page.goto("/research");
  const list = page.getByRole("list", { name: "已保存研究候選" });
  await expect(list.getByRole("button", { name: /台積電.*2330/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "台積電 2330" })).toBeVisible();
  await expect(list).not.toContainText("11.333333");
  await expect(page.getByText("11.33", { exact: true }).first()).toBeVisible();
  await expect(page.locator("dl[aria-label='已保存研究價位']")).toContainText("未提供"); // absent TP2
  await expect(page.getByText("SYNTHETIC_MISSING_QUOTE", { exact: false })).toBeVisible();
  await expect(page.getByText("當前情境計算限制：SYNTHETIC_CURRENT_COST_LIMIT", { exact: true })).toBeVisible();
  await expect(page.getByText("僅樣本，非完整市場研究", { exact: false })).toBeVisible();
  await expect(page.getByLabel("股票代號（1～5 檔）")).toBeHidden();
  await page.locator("summary").filter({ hasText: "指定股票研究" }).click();
  await expect(page.getByLabel("股票代號（1～5 檔）")).toBeVisible();
  await page.getByRole("button", { name: "修改提案", exact: true }).click();
  await expect(page.getByLabel("Entry", { exact: true })).toHaveValue("99.123456");
  await list.getByRole("button", { name: /群創.*3481/ }).click();
  await expect(page.getByRole("heading", { name: "群創 3481" })).toBeVisible();
  await expect(list.getByRole("button", { name: /群創.*3481/ })).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("篩選方向").selectOption("long");
  await expect(list.getByRole("button")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "台積電 2330" })).toBeVisible();
  expect(writes).toEqual([]);
});

for (const invalid of ["null", "{bad-json", JSON.stringify({ price_map: { payload: { stock_id: "9999", stock_name: "錯誤名稱" } } })]) {
  test(`missing or mismatched identity stays explicit: ${invalid}`, async ({ page }) => {
    const item = proposal(); item.proposal.evidence.items[0].snapshot_json = invalid;
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await mockResearch(page, [item]); await page.goto("/research");
    await expect(page.getByRole("heading", { name: "名稱未提供 2330" })).toBeVisible();
    await expect(page.getByText("錯誤名稱", { exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}

test("failed list read retains a visible error and reload action", async ({ page }) => {
  await mockResearch(page, [], true); await page.goto("/research");
  await expect(page.getByRole("region", { name: "已保存候選", exact: true }).getByRole("alert")).toBeVisible();
  await expect(page.getByRole("button", { name: "重新讀取清單" })).toBeEnabled();
  await expect(page.getByRole("list", { name: "已保存研究候選" })).toHaveCount(0);
});

for (const [width, theme] of [[390, "light"], [768, "dark"], [1440, "light"]] as const) {
  test(`${width}px ${theme}: readable without horizontal overflow`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(color => localStorage.setItem("omi:settings:color", color), theme);
    await mockResearch(page); await page.goto("/research");
    await expect(page.getByRole("heading", { name: "台積電 2330" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`research-${width}-${theme}.png`), fullPage: true });
  });
}

for (const [market, locale, label] of [["us", "zh-TW", "股票研究候選"], ["tw", "en-US", "Stock research"], ["jp", "ja-JP", "株式リサーチ"], ["kr", "zh-TW", "股票研究候選"], ["crypto", "zh-TW", "股票研究候選"]]) {
  test(`${market}: sidebar research link remains available when market data fails`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 720 });
    await page.addInitScript(language => localStorage.setItem("omi:settings:language", language), locale);
    await mockResearch(page);
    await page.goto(`/?market=${market}`);
    const link = page.getByRole("link", { name: label, exact: true });
    await expect(link).toBeVisible();
    await expect(link).toBeInViewport();
    await expect(link).toHaveAttribute("href", "/research");
    await link.click();
    await expect(page.getByRole("heading", { name: "股票研究候選", exact: true })).toBeVisible();
  });
}

function usProposal() {
  const item = proposal("NVDA", "NVIDIA", -1);
  item.proposal.market = "US";
  item.currency = "USD"; item.promotion_supported = false;
  Object.assign(item.proposal.strategy, { shares: 1, entry_rule: "at_or_above", entry_price: 150.1234,
    stop_price: 155.12, targets: [{ price: 140, fraction: 0.5 }, { price: 130, fraction: 0.5 }],
    thesis: "美股日線反彈壓力研究（測試資料）", counter_evidence: ["測試失效界線：155.12"] });
  item.setup_evaluation = { status: "ready", gross_risk: "4.9966", net_stop_loss: null,
    target_scenarios: [{ gross_rr: "2.0260577", net_rr: null }, { gross_rr: "4.0274194", net_rr: null }],
    missing_costs: ["commission_rate", "short_borrow_per_share_session"] };
  item.proposal.evidence.items[0].source_ref = "research.us_watchlist_nomination.v1";
  item.proposal.evidence.items[0].snapshot_json = JSON.stringify({
    request: { nomination_origin: "OMI_SCREEN", horizon_sessions: 10 },
    identity: { market: "US", symbol: "NVDA", venue: "NASDAQ" }, discovery: { scope: "enabled_us_watchlist" },
  });
  return item;
}

test("market change resets pagination and selection; US stays USD and research only", async ({ page }, testInfo) => {
  const items = Array.from({ length: 21 }, (_, i) => proposal(String(2300 + i), `台股${i}`));
  const writes = await mockResearch(page, [...items, usProposal()]);
  await page.goto("/research");
  await page.getByRole("button", { name: "下一頁", exact: true }).click();
  await expect(page.getByText("第 2 頁", { exact: true })).toBeVisible();
  const request = page.waitForRequest(req => new URL(req.url()).searchParams.get("market") === "US"
    && new URL(req.url()).searchParams.get("offset") === "0");
  await page.getByRole("combobox", { name: "市場", exact: true }).selectOption("US");
  await request;
  await expect(page.getByRole("heading", { name: "NVDA", exact: true })).toBeVisible();
  await expect(page.getByText("第 1 頁", { exact: true })).toBeVisible();
  await expect(page.getByText("USD 美元", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "採用為條件候選", exact: true })).toBeDisabled();
  await expect(page.getByRole("link", { name: "開啟既有個股圖表" })).toHaveAttribute("href", "/?market=us&symbol=NVDA");
  expect(writes).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("us-research-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("us-research-mobile.png"), fullPage: true });
  await page.getByRole("combobox", { name: "市場", exact: true }).selectOption("TW");
  await expect(page.getByRole("heading", { name: "台股0 2300" })).toBeVisible();
  await expect(page.getByRole("region", { name: "美股觀察名單掃描" })).toHaveCount(0);
});

test("US research has no scan panel, controls or scan-status requests", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", request => { if (request.url().includes("us-watchlist-scan")) requests.push(request.url()); });
  await mockResearch(page, [usProposal()]);
  await page.goto("/research?market=US");
  await expect(page.getByRole("heading", { name: "NVDA", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "美股觀察名單掃描" })).toHaveCount(0);
  await expect(page.getByText("手動補掃", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重新讀取掃描狀態" })).toHaveCount(0);
  expect(requests).toEqual([]);
});

test("old backend cannot show Taiwan proposals in the US list", async ({ page }) => {
  const writes = await mockResearch(page);
  await page.route(/\/(?:api|omi-data)\/research\/trade-proposals(?:\?|$)/, route => route.fulfill({
    json: { as_of: asOf, items: [proposal()], limit: 20, offset: 0, has_more: false },
  }));
  await page.goto("/research?market=US");
  await expect(page.getByText("後端回傳的市場與目前選擇不符", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "台積電 2330" })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "已保存研究候選" })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test("cross-market deep link cannot render proposal details or start monitoring", async ({ page }) => {
  const writes = await mockResearch(page);
  const monitors: string[] = [];
  page.on("request", request => { if (request.url().includes("/monitor")) monitors.push(request.url()); });
  await page.goto("/research?market=US&proposal_id=test-2330");
  await expect(page.getByText("後端回傳的市場與目前選擇不符", { exact: false })).toBeVisible();
  await expect(page.getByRole("heading", { name: "台積電 2330" })).toHaveCount(0);
  expect(monitors).toEqual([]);
  expect(writes).toEqual([]);
});

test("pending US nomination cannot return into another market", async ({ page }) => {
  await mockResearch(page, []);
  let release: () => void = () => {};
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(/\/(?:api|omi-data)\/research\/trade-proposals\/nominations$/, async route => {
    expect(route.request().postDataJSON().market).toBe("US");
    await pending;
    await route.fulfill({ status: 201, json: { status: "partial", nomination_origin: "USER_NOMINATION",
      coverage: { scope: "enabled_us_watchlist" }, scenarios: [] } });
  });
  await page.goto("/research?market=US");
  await page.locator("summary").filter({ hasText: "指定股票研究" }).click();
  await page.getByLabel("股票代號（1～5 檔）").fill("NVDA");
  await page.getByLabel("已完成日 K 截止日期").fill("2026-11-04");
  await page.getByRole("button", { name: "研究並保存", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "市場", exact: true })).toBeDisabled();
  release();
  await expect(page.getByRole("combobox", { name: "市場", exact: true })).toBeEnabled();
  await expect(page.getByRole("combobox", { name: "市場", exact: true })).toHaveValue("US");
});

for (const market of ["TW", "US"] as const) {
  test(`${market}: delete requires confirmation and stays removed after reload`, async ({ page }, testInfo) => {
    const items = [market === "US" ? usProposal() : proposal()];
    const saved = items[0].proposal;
    await mockResearch(page, items);
    let deletes = 0;
    await page.route(/\/(?:api|omi-data)\/research\/trade-proposals\/test-[^/?]+$/, async route => {
      if (route.request().method() !== "DELETE") return route.fallback();
      deletes++;
      expect(route.request().postDataJSON()).toEqual({ expected_revision_id: saved.revision_id });
      items.splice(0, 1);
      await route.fulfill({ json: { creation_id: saved.creation_id, revision_id: "deleted-revision", deleted_at: asOf, status: "deleted" } });
    });
    await page.goto(`/research?market=${market}`);
    await page.getByRole("button", { name: "刪除提案", exact: true }).click();
    const confirmation = page.getByRole("group", { name: "確認刪除提案" });
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole("button", { name: "取消", exact: true }).click();
    expect(deletes).toBe(0);
    await page.getByRole("button", { name: "刪除提案", exact: true }).click();
    await page.screenshot({ path: testInfo.outputPath(`delete-${market}-desktop.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`delete-${market}-mobile.png`), fullPage: true });
    await confirmation.getByRole("button", { name: "確認刪除", exact: true }).click();
    await expect(page.getByText("沒有符合條件的已保存提案。", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "刪除提案", exact: true })).toHaveCount(0);
    await page.reload();
    await expect(page.getByText("沒有符合條件的已保存提案。", { exact: true })).toBeVisible();
    expect(deletes).toBe(1);
  });
}

test("deleting the last item on a page returns to the previous page and freezes selection while pending", async ({ page }) => {
  const items = Array.from({ length: 21 }, (_, i) => proposal(String(2300 + i), `台股${i}`));
  const saved = items[20].proposal;
  await mockResearch(page, items);
  let release: () => void = () => {};
  let deletes = 0;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route(/\/(?:api|omi-data)\/research\/trade-proposals\/test-2320$/, async route => {
    if (route.request().method() !== "DELETE") return route.fallback();
    deletes++;
    await pending;
    items.splice(20, 1);
    await route.fulfill({ json: { creation_id: saved.creation_id, revision_id: "deleted-revision", deleted_at: asOf, status: "deleted" } });
  });
  await page.goto("/research");
  await page.getByRole("button", { name: "下一頁", exact: true }).click();
  await expect(page.getByRole("heading", { name: "台股20 2320", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "刪除提案", exact: true }).click();
  await page.getByRole("button", { name: "確認刪除", exact: true }).click();
  await expect(page.getByRole("button", { name: "刪除中…", exact: true })).toBeDisabled();
  await expect(page.getByRole("combobox", { name: "市場", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "上一頁", exact: true })).toBeDisabled();
  release();
  await expect(page.getByText("第 1 頁", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "台股0 2300", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "下一頁", exact: true })).toBeDisabled();
  expect(deletes).toBe(1);
});

for (const failure of ["conflict", "network"] as const) {
  test(`delete ${failure} preserves the proposal and does not retry automatically`, async ({ page }) => {
    await mockResearch(page, [proposal()]);
    let deletes = 0;
    await page.route(/\/(?:api|omi-data)\/research\/trade-proposals\/test-2330$/, async route => {
      if (route.request().method() !== "DELETE") return route.fallback();
      deletes++;
      if (failure === "network") return route.abort();
      return route.fulfill({ status: 409, json: { detail: { code: "REVISION_CONFLICT", message: "Reload before deleting." } } });
    });
    await page.goto("/research");
    await page.getByRole("button", { name: "刪除提案", exact: true }).click();
    await page.getByRole("button", { name: "確認刪除", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "請重新讀取提案" })).toBeVisible();
    await expect(page.getByRole("button", { name: "確認刪除", exact: true })).toBeDisabled();
    await expect(page.getByRole("heading", { name: "台積電 2330", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "重新讀取提案", exact: true }).click();
    await expect(page.getByRole("button", { name: "刪除提案", exact: true })).toBeEnabled();
    expect(deletes).toBe(1);
  });
}

test("deleted revision read cannot fall back to a stale current proposal", async ({ page }) => {
  await mockResearch(page);
  await page.route(/\/(?:api|omi-data)\/research\/trade-proposals\/test-2330\/revisions$/, route => route.fulfill({
    status: 410, json: { detail: { code: "PROPOSAL_DELETED", message: "The research proposal was deleted." } },
  }));
  await page.goto("/research?proposal_id=test-2330");
  await expect(page.getByRole("alert").filter({ hasText: "此提案已刪除" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "台積電 2330", exact: true })).toHaveCount(0);
});

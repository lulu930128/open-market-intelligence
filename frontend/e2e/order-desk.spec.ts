import { expect, test } from "@playwright/test";
import type { DeskSnapshot } from "../src/lib/order-desk/contract";
import { readDeskSnapshot } from "../src/lib/order-desk/contract";

test.beforeEach(async ({ page }) => {
  await page.goto("/order-desk");
});

test("雙 Space、修訂後重新預審、exact confirm、策略 revision 與拒絕", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Order Desk 預審與執行" })).toBeVisible();
  await expect(page.getByText("FAKE ONLY", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "讀回狀態", exact: true })).toBeDisabled();
  await expect(page.getByRole("region", { name: "選定提案" })).toContainText("未選定時");
  await page.getByRole("button", { name: "載入隔離 Fake session" }).click();
  await expect(page.getByRole("button", { name: "確認此版本" })).toBeEnabled();
  const selected = page.getByRole("region", { name: "選定提案" });
  await selected.getByRole("spinbutton", { name: "股數" }).fill("80");
  await expect(page.getByRole("button", { name: "確認此版本" })).toBeDisabled();
  await page.getByRole("button", { name: "儲存修訂，重新預審" }).click();
  await expect(page.getByRole("button", { name: "取得 Preview" })).toBeEnabled();
  await page.getByRole("button", { name: "取得 Preview" }).click();
  await page.getByRole("button", { name: "確認此版本" }).click();
  await expect(page.getByRole("article", { name: "Entry O0002" })).toContainText("80 股");
  await page.getByRole("button", { name: "建立本機策略" }).click();
  await expect(page.getByTestId("strategy-state")).toHaveText("ENTRY_ACTIVE");
  await page.getByRole("textbox", { name: "停損價", exact: true }).fill("485");
  await page.getByRole("button", { name: "套用 SL / TP 修訂" }).click();
  await expect(page.getByText("策略 revision 2", { exact: true })).toBeVisible();
  await page.getByLabel("顯示 Space").selectOption("AGENT_SPACE");
  await page.getByRole("button").filter({ hasText: "agent-review" }).click();
  await page.getByRole("button", { name: "拒絕提案" }).click();
  await expect(page.getByText("已拒絕，未建立 execution。請從其他提案繼續。")).toBeVisible();
});

test("60/100 → stop cancel40 exit60 → latefill15 exit15，ACK 不提前 CLOSED", async ({ page }) => {
  await page.getByRole("button", { name: "載入隔離 Fake session" }).click();
  await page.getByRole("button", { name: "查看 60 / 100 案例" }).click();
  await page.getByRole("button", { name: "注入 Entry 成交 60 / 100" }).click();
  await expect(page.getByTestId("entry-filled")).toHaveText("60");
  await expect(page.getByTestId("entry-remaining")).toHaveText("40");
  await page.getByRole("button", { name: "注入 480 停損：撤餘 40、退出 60" }).click();
  const entry = page.getByRole("article", { name: "Entry O0001" });
  await expect(entry).toContainText("ACK_ONLY");
  await expect(entry.getByRole("button", { name: "立即精確撤單 O0001" })).toBeDisabled();
  await expect(page.getByTestId("reserved-exit")).toHaveText("60");
  await page.getByRole("button", { name: "注入 Exit 成交 60", exact: true }).click();
  await expect(page.getByTestId("effective-position")).toHaveText("0");
  await expect(page.getByTestId("strategy-state")).not.toHaveText("CLOSED");
  await page.getByRole("button", { name: "注入晚到 Entry 成交 15" }).click();
  await expect(page.getByTestId("effective-position")).toHaveText("15");
  await expect(page.getByTestId("reserved-exit")).toHaveText("15");
  await expect(page.getByRole("article", { name: "Exit 2 O0003" })).toBeVisible();
  await page.getByRole("button", { name: "注入補充 Exit 成交 15" }).click();
  await expect(page.getByTestId("strategy-state")).not.toHaveText("CLOSED");
  await page.getByRole("button", { name: "注入最終撤單與相符證據" }).click();
  await expect(page.getByTestId("strategy-state")).toHaveText("CLOSED");
  await expect(page.getByTestId("entry-remaining")).toHaveText("0");
  await expect(page.getByTestId("exit-filled")).toHaveText("75");
  await expect(page.getByTestId("reserved-exit")).toHaveText("0");
  await expect(page.getByRole("region", { name: "事件時間軸" })).toContainText("CANCEL_ACK_ONLY");
  await page.screenshot({ path: "../.tmp/order-desk-phase4/desktop.png", fullPage: true });
});

test("partial/unavailable 與立即撤單，行動版無水平溢出，鍵盤可用", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳至選定單據" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("region", { name: "選定提案" })).toBeFocused();
  await page.getByRole("button", { name: "載入隔離 Fake session" }).click();
  await page.getByRole("button", { name: "查看 60 / 100 案例" }).click();
  await page.getByRole("button", { name: "立即精確撤單 O0001" }).click();
  await expect(page.getByRole("article", { name: "Entry O0001" })).toContainText("ACK_ONLY");
  await page.getByRole("button", { name: "注入 PARTIAL snapshot" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("列 Broker 回報已隔離");
  await page.getByRole("button", { name: "注入 UNAVAILABLE snapshot" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("UNAVAILABLE");
  await expect(page.getByRole("article", { name: "Entry O0001" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "../.tmp/order-desk-phase4/mobile.png", fullPage: true });
});

test("canonical transport exact selectors、duplicate cancel、read-only GET 與 typed projection", async ({ request }) => {
  let snapshot = readDeskSnapshot(await (await request.post("/order-desk/transport", { data: { type: "open_demo" } })).json());
  const session_id = snapshot.session_id;
  const review = snapshot.reviews.find(r => r.state === "PREVIEW")!;
  const send = (command: unknown) => request.post("/order-desk/transport", { data: { session_id, command } });
  await send({ type: "revise", review_id: review.review_id, expected_revision: 1,
    draft: { ...review.draft, command: { ...review.draft.command, quantity: 80 } } });
  const stale = await send({ type: "confirm", review_id: review.review_id, expected_revision: 1, expected_digest: review.snapshot!.digest });
  expect(stale.status()).toBe(409);
  expect((await stale.json()).code).toBe("STALE_REVIEW_REVISION");
  const first = snapshot.strategies[0].entry;
  const cancel = { type: "cancel", execution_id: first.execution_id,
    key: { account_id: snapshot.account_id, trade_date: first.trade_date, order_id: first.broker_order_id } };
  await send(cancel); await send(cancel);
  snapshot = readDeskSnapshot(await (await request.get("/order-desk/transport", { headers: { "x-desk-session": session_id } })).json());
  expect(snapshot.strategies[0].entry.cancel_stage).toBe("ACK_ONLY");
  expect(snapshot.reviews.flatMap(r => r.execution_audit).filter(e => e.kind === "CANCEL_CLAIMED")).toHaveLength(1);
  const again = readDeskSnapshot(await (await request.get("/order-desk/transport", { headers: { "x-desk-session": session_id } })).json());
  expect(again).toEqual(snapshot);
  expect(() => readDeskSnapshot({ ...snapshot, mode: "LIVE" })).toThrow("INVALID_EXECUTION_CONTRACT");
  expect(() => readDeskSnapshot({ ...snapshot, reviews: [{}] })).toThrow();
});

test("stale confirm 與 transport 失聯皆保留錯誤，不假報完成", async ({ page, request }) => {
  let opened: DeskSnapshot;
  page.on("response", async response => {
    if (response.url().endsWith("/order-desk/transport") && response.request().postDataJSON()?.type === "open_demo") opened = await response.json();
  });
  await page.getByRole("button", { name: "載入隔離 Fake session" }).click();
  await expect(page.getByRole("button", { name: "確認此版本" })).toBeEnabled();
  const review = opened!.reviews.find(r => r.state === "PREVIEW")!;
  await request.post("/order-desk/transport", { data: { session_id: opened!.session_id, command: {
    type: "revise", review_id: review.review_id, expected_revision: 1, draft: { ...review.draft, command: { ...review.draft.command, quantity: 90 } },
  } } });
  await page.getByRole("button", { name: "確認此版本" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("STALE_REVIEW_REVISION");
  await expect(page.getByRole("button", { name: "確認此版本" })).toBeDisabled();
  await page.getByRole("button", { name: "讀回狀態", exact: true }).click();
  await expect(page.getByRole("button", { name: "取得 Preview" })).toBeVisible();
  await page.route("**/order-desk/transport", route => route.abort("failed"));
  await page.getByRole("button", { name: "讀回狀態", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("FAKE_TRANSPORT_UNAVAILABLE");
  await expect(page.getByRole("region", { name: "選定提案" })).toContainText("90 股 @ 500");
});

test("UNKNOWN 無 Broker ID、保留 reconcile_required，不能猜配撤單", async ({ page }) => {
  await page.getByRole("button", { name: "載入隔離 Fake session" }).click();
  await page.getByRole("button", { name: "注入下次委託 UNKNOWN" }).click();
  await page.getByRole("button", { name: "確認此版本" }).click();
  const entry = page.getByRole("article", { name: "Entry UNKNOWN" });
  await expect(entry).toContainText("UNKNOWN");
  await expect(entry).toContainText("reconcile_required=true");
  await expect(entry.getByRole("button", { name: "立即精確撤單" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "確認此版本" })).toBeDisabled();
});

test("空清單與 malformed contract 不產生可操作的假單", async ({ page, request }) => {
  const snapshot = await (await request.post("/order-desk/transport", { data: { type: "open_demo" } })).json();
  await page.route("**/order-desk/transport", route => route.fulfill({ json: { ...snapshot, reviews: [], strategies: [] } }));
  await page.getByRole("button", { name: "載入隔離 Fake session" }).click();
  await expect(page.getByRole("complementary", { name: "雙 Space 預審清單" })).toContainText("此 Space 尚無提案");
  await expect(page.getByRole("button", { name: "確認此版本" })).toHaveCount(0);
  await page.unroute("**/order-desk/transport");
  await page.route("**/order-desk/transport", route => route.fulfill({ json: { ...snapshot, strategies: [{}] } }));
  await page.getByRole("button", { name: "讀回狀態", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("INVALID_EXECUTION_CONTRACT");
});

test("未設定 transport 回 503，不觸碰任何 broker", async ({ page, request }) => {
  for (const method of ["get", "post"] as const) {
    const response = await request[method]("http://127.0.0.1:3315/order-desk/transport");
    expect(response.status()).toBe(503);
    expect((await response.json()).code).toBe("LIVE_NOT_DEPLOYED_FAKE_NOT_CONFIGURED");
  }
  await page.goto("http://127.0.0.1:3315/order-desk");
  await expect(page.getByRole("button", { name: "載入隔離 Fake session" })).toBeDisabled();
  await expect(page.getByRole("main")).toContainText("操作已停用");
});

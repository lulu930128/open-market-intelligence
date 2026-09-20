import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import type { StockPriceMapRead, StockTechnicalReportRead } from "@/types/market";

test.describe("Taiwan technical timeframe live adoption", () => {
  test.skip(process.env.OMI_LIVE_BROWSER_ACCEPTANCE !== "1", "Requires the adopted local OMI runtime.");

  for (const stockId of ["2330", "3711", "5488"]) {
    test(`${stockId}: report, Radar, Price Map and chart switching`, async ({ page }, testInfo) => {
      test.setTimeout(420_000);
      const errors: string[] = [];
      page.on("pageerror", error => errors.push(error.message));
      const evidence: Record<string, unknown>[] = [];
      const maps: StockPriceMapRead[] = [];
      const ma20: unknown[] = [];
      page.on("requestfailed", request => {
        if (request.url().includes("/technical/")) console.log("technical request failed", request.url(), request.failure()?.errorText);
      });
      page.on("response", response => {
        if (response.url().includes("/technical/")) console.log("technical response", response.status(), Math.round(response.request().timing().responseStart), response.url());
      });
      await page.setViewportSize({ width: 1920, height: 1080 });
      await page.goto(`/?market=tw&stock_id=${stockId}&radar_live_acceptance=timeframes`);

      for (const timeframe of ["today", "daily", "weekly", "monthly"] as const) {
        const requested = (url: string, suffix = "") => {
          const parsed = new URL(url);
          return parsed.pathname.endsWith(`/market/technical/${stockId}${suffix}`)
            && parsed.searchParams.get("timeframe") === timeframe;
        };
        const reportResponse = page.waitForResponse(response => requested(response.url()), { timeout: 60_000 });
        const mapResponse = page.waitForResponse(response => requested(response.url(), "/price-map"), { timeout: 60_000 });
        await page.getByTestId(`timeframe-${timeframe}`).click();
        await expect(page.getByTestId("tw-stock-detail-radar-v2")).toHaveAttribute("data-timeframe", timeframe);
        expect(["pending", timeframe]).toContain(await page.getByTestId("tw-stock-price-map").getAttribute("data-requested-timeframe"));
        const [reportHttp, mapHttp] = await Promise.all([reportResponse, mapResponse]);
        expect(reportHttp.status()).toBe(200);
        expect(mapHttp.status()).toBe(200);
        const report = await reportHttp.json() as StockTechnicalReportRead;
        const map = await mapHttp.json() as StockPriceMapRead;
        expect(report.timeframe).toBe(timeframe);
        expect(map.requested_timeframe).toBe(timeframe);
        expect(map.structure_timeframe).toBe(timeframe === "today" ? "daily" : timeframe);
        const radar = page.getByTestId("tw-stock-detail-radar-v2");
        await expect(radar).toHaveAttribute("data-stock-id", stockId);
        await expect(radar).toHaveAttribute("data-timeframe", timeframe);
        await expect(page.getByTestId("tw-stock-price-map")).toHaveAttribute("data-requested-timeframe", timeframe);
        const state = report.data.current_state as Record<string, unknown>;
        expect(state).toBeTruthy();
        await expect(page.getByTestId("tw-technical-current-state")).toContainText((state.headline as { label: string }).label);
        if (timeframe === "today") {
          expect(state.basis).toBe("current_session_observation");
          await expect(page.getByTestId("tw-stock-price-map")).toContainText("日線結構 / 今日成交觀測");
          await expect(page.getByTestId("today-intraday-surface")).toBeVisible();
        } else {
          const indicator = (report.data.indicator ?? report.data.daily_indicator) as Record<string, unknown>;
          ma20.push((indicator.ma as Record<string, unknown>).ma20);
          maps.push(map);
          if (stockId === "5488" && timeframe !== "daily") {
            // This TPEX fixture has fewer than 60 completed periods in local
            // storage. Missing evidence must remain visible, without backfill.
            expect(report.decision_usable).toBe(false);
            expect(report.missing).toContain("TW_TECHNICAL_INSUFFICIENT_BARS");
            expect(map.status).toBe("partial");
            expect(map.zones).toHaveLength(0);
          } else {
            expect(map.zones.length).toBeGreaterThan(0);
            expect(map.evidence_timeframes).toContain(timeframe);
          }
          if (timeframe !== "daily") {
            expect(state.timeframe).toBe(timeframe);
            expect(state.basis).toBe("completed_period");
            expect(report.summary).not.toContain("日線");
          }
          await expect(page.getByTestId("stock-chart-card").locator("svg.w-full").first()).toBeVisible({ timeout: 30_000 });
          await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute("data-technical-load-state", "success", { timeout: 75_000 });
          if (stockId !== "5488") {
            expect(Number(await page.getByTestId("stock-detail-panel").getAttribute("data-technical-point-count"))).toBeGreaterThan(60);
            expect(Number(await page.getByTestId("stock-detail-panel").getAttribute("data-chart-indicator-point-count"))).toBeGreaterThan(60);
            await expect(page.getByTestId("stock-chart-card").locator("path.stroke-omi-chart-amber").first()).toHaveAttribute("d", /^M/);
          }
          evidence.push({ stockId, timeframe, status: report.status, decision_usable: report.decision_usable,
            input_quality: indicator.input_quality, ma: indicator.ma, rsi: indicator.rsi,
            basis_revision: map.basis_revision, evidence_timeframes: map.evidence_timeframes,
            zones: map.zones, map_status: map.status, map_missing: map.missing, map_warnings: map.warnings });
        }
        const screenshot = testInfo.outputPath(`${stockId}-${timeframe}.png`);
        await page.screenshot({ path: screenshot });
        await testInfo.attach(`${stockId}-${timeframe}`, { path: screenshot, contentType: "image/png" });
        writeFileSync(testInfo.outputPath(`${stockId}-timeframe-evidence.json`), JSON.stringify(evidence, null, 2));
      }
      if (stockId !== "5488") expect(new Set(ma20).size).toBe(3);
      expect(new Set(maps.map(map => map.basis_revision)).size).toBe(3);
      if (stockId !== "5488") expect(new Set(maps.map(map => JSON.stringify(map.zones.map(zone => [zone.lower_bound, zone.upper_bound])))).size).toBe(3);

      await page.getByTestId("stock-detail-expand").click();
      const professional = page.getByTestId("professional-chart-panel");
      await expect(professional).toBeVisible();
      for (const [timeframe, label] of [["daily", "日K"], ["weekly", "週K"], ["monthly", "月K"]]) {
        await professional.getByRole("button", { name: label, exact: true }).click();
        await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute("data-chart-timeframe", timeframe, { timeout: 60_000 });
        await expect(page.getByTestId("stock-detail-panel")).toHaveAttribute("data-technical-load-state", "success", { timeout: 75_000 });
        if (stockId !== "5488") expect(Number(await page.getByTestId("stock-detail-panel").getAttribute("data-chart-indicator-point-count"))).toBeGreaterThan(60);
        await expect(professional.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
      }
      const professionalScreenshot = testInfo.outputPath(`${stockId}-professional.png`);
      await page.screenshot({ path: professionalScreenshot });
      await testInfo.attach(`${stockId}-professional`, { path: professionalScreenshot, contentType: "image/png" });
      const evidencePath = testInfo.outputPath(`${stockId}-timeframe-evidence.json`);
      writeFileSync(evidencePath, JSON.stringify(evidence, null, 2));
      await testInfo.attach(`${stockId}-timeframe-evidence`, { path: evidencePath, contentType: "application/json" });
      expect(errors).toEqual([]);
    });
  }
});

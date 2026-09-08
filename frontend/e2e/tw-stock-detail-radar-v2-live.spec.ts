import { expect, test } from "@playwright/test";

const liveAcceptanceEnabled =
  process.env.OMI_LIVE_BROWSER_ACCEPTANCE === "1";
const randomSampleStock = process.env.OMI_RADAR_SAMPLE_STOCK ?? "5488";

const samples = [
  { stockId: "2330", referencePrice: "2410" },
  { stockId: "3711", referencePrice: "588" },
  { stockId: randomSampleStock, referencePrice: "12.1" },
];

test.describe("Taiwan Stock Detail Radar V2 live acceptance", () => {
  test.skip(
    !liveAcceptanceEnabled,
    "Set OMI_LIVE_BROWSER_ACCEPTANCE=1 against an adopted local OMI runtime."
  );

  test("three-stock contract and wide-screen layout", async ({ page }, testInfo) => {
    test.setTimeout(120_000);
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.setViewportSize({ width: 1920, height: 1080 });

    for (const sample of samples) {
      await page.goto(`/?market=tw&stock_id=${sample.stockId}&radar_live_acceptance=1`);

      const radar = page.getByTestId("tw-stock-detail-radar-v2");
      const priceMap = page.getByTestId("tw-stock-price-map");
      const axis = page.getByTestId("tw-stock-price-axis");
      await expect(radar).toHaveAttribute("data-stock-id", sample.stockId, {
        timeout: 30_000,
      });
      await expect(priceMap).toHaveAttribute("data-stock-id", sample.stockId);
      await expect(priceMap).toHaveAttribute(
        "data-version",
        "tw.stock.price_map.v3",
        { timeout: 30_000 }
      );
      await expect(priceMap).toHaveAttribute(
        "data-reference-price",
        sample.referencePrice,
        { timeout: 30_000 }
      );
      await expect(axis.locator("[data-axis-percent]")).toHaveCount(11);
      await expect(
        priceMap.getByTestId("tw-stock-price-map-marker-completed_reference")
      ).toHaveAttribute("data-marker-price", sample.referencePrice);
      const visibleZones = axis.locator("[data-tier]");
      expect(await visibleZones.count()).toBeGreaterThan(0);
      const zoneContracts = await visibleZones.evaluateAll((elements) =>
        elements.map((element) => ({
          evidenceBounds: element.getAttribute("data-evidence-bounds"),
          tier: element.getAttribute("data-tier"),
          zoneBounds: element.getAttribute("data-zone-bounds"),
        }))
      );
      for (const zone of zoneContracts) {
        expect(zone.tier).toMatch(/^(P0|R\d+|S\d+)$/);
        expect(zone.evidenceBounds).toMatch(/^\d+(\.\d+)?:\d+(\.\d+)?$/);
        const [lower, upper] = (zone.zoneBounds ?? "0:0").split(":").map(Number);
        expect(lower).toBeLessThan(upper);
      }
      await expect(priceMap.getByTestId("tw-stock-price-map-accessible-details")).toBeVisible();
      await expect(radar.locator('[role="alert"]')).toHaveCount(0);

      const overflow = await axis.evaluate((element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }));
      expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth);

      const labelCollisions = await axis.evaluate((element) => {
        const labels = Array.from(
          element.querySelectorAll<HTMLElement>(
            '[data-testid^="tw-stock-price-zone-label-"], ' +
              '[data-testid^="tw-stock-price-map-trigger-label-"], ' +
              '[data-testid="tw-stock-price-map-current-label"]'
          )
        ).map((label) => ({
          id: label.dataset.testid ?? "unknown",
          rect: label.getBoundingClientRect(),
        }));
        const collisions: string[] = [];
        for (let leftIndex = 0; leftIndex < labels.length; leftIndex += 1) {
          for (let rightIndex = leftIndex + 1; rightIndex < labels.length; rightIndex += 1) {
            const left = labels[leftIndex];
            const right = labels[rightIndex];
            const overlaps =
              left.rect.left < right.rect.right &&
              left.rect.right > right.rect.left &&
              left.rect.top < right.rect.bottom &&
              left.rect.bottom > right.rect.top;
            if (overlaps) collisions.push(`${left.id}/${right.id}`);
          }
        }
        return collisions;
      });
      expect(labelCollisions).toEqual([]);

      await testInfo.attach(`radar-${sample.stockId}-1920x1080`, {
        body: await page.screenshot(),
        contentType: "image/png",
      });
    }

    await page.setViewportSize({ width: 2560, height: 1440 });
    await page.goto("/?market=tw&stock_id=2330&radar_live_acceptance=wide");
    await expect(page.getByTestId("tw-stock-price-map")).toHaveAttribute(
      "data-reference-price",
      "2410",
      { timeout: 30_000 }
    );
    await testInfo.attach("radar-2330-2560x1440", {
      body: await page.screenshot(),
      contentType: "image/png",
    });

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});

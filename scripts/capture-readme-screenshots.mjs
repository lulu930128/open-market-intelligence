import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { chromium } from "../frontend/node_modules/playwright/index.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const outputDir = path.join(repoRoot, "docs", "assets", "readme");
const baseUrl = process.env.OMI_SCREENSHOT_BASE_URL ?? "http://127.0.0.1:3000";
const viewport = { width: 2560, height: 1440 };
const stockUrl = `${baseUrl}/?market=tw&group_id=3&stock_id=2330`;

await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({
  colorScheme: "light",
  locale: "zh-TW",
  viewport,
});
const page = await context.newPage();
const consoleErrors = [];

page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(error.message));

async function settle() {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(1_200);
}

async function capture(filename) {
  const outputPath = path.join(outputDir, filename);
  await page.screenshot({
    animations: "disabled",
    fullPage: false,
    path: outputPath,
    type: "png",
  });
  console.log(`${filename} ${viewport.width}x${viewport.height}`);
}

try {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Market Dashboard" }).waitFor();
  await settle();
  await capture("omi-v4-dashboard-radar-2k.png");

  await page.goto(stockUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "放大", exact: true }).waitFor();
  await settle();
  await capture("omi-v4-stock-research-2k.png");

  await page.getByRole("button", { name: "放大", exact: true }).click();
  await page.getByRole("button", { name: "日K", exact: true }).waitFor();
  await settle();
  await capture("omi-v4-professional-chart-2k.png");

  await page.getByRole("button", { name: "開啟 OMI 即時問答", exact: true }).click();
  await page.getByRole("button", { name: "收起 OMI 即時問答", exact: true }).waitFor();
  await settle();
  await capture("omi-v4-decision-dock-2k.png");
} finally {
  await browser.close();
}

if (consoleErrors.length > 0) {
  console.error("Browser console/page errors:");
  for (const message of consoleErrors) console.error(`- ${message}`);
  process.exitCode = 1;
}

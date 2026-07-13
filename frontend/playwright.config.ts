import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PLAYWRIGHT_PORT ?? 3100);
const host = process.env.PLAYWRIGHT_HOST ?? "127.0.0.1";
const baseURL = `http://${host}:${port}`;
const productionServer =
  process.env.CI || process.env.PLAYWRIGHT_SERVER_MODE === "production";
const serverCommand = productionServer
  ? `npm run start:e2e-production -- --hostname ${host} --port ${port}`
  : `npm run dev -- --hostname ${host} --port ${port}`;
process.env.API_PROXY_TARGET =
  process.env.PLAYWRIGHT_API_PROXY_TARGET ?? "http://127.0.0.1:9";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  timeout: 45_000,
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    ...(process.env.CI ? {} : { channel: "chrome" as const }),
    trace: "on-first-retry",
  },
  webServer: {
    command: serverCommand,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});

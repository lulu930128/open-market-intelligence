import { defineConfig } from "@playwright/test";
import path from "node:path";

const root = path.resolve(__dirname, "..");
const isolated = path.join(root, ".tmp/order-desk-phase4/frontend");
const port = 3314;

export default defineConfig({
  testDir: "./e2e", testMatch: "order-desk*.spec.ts", workers: 1, retries: 0,
  timeout: 30_000, reporter: "list",
  outputDir: "../.tmp/order-desk-phase4/test-results",
  use: { baseURL: `http://127.0.0.1:${port}`, channel: "chrome", screenshot: "only-on-failure" },
  webServer: [
    { command: '".venv/Scripts/python.exe" -m execution_runtime.tests.order_desk_server --port 38414',
      cwd: root, url: "http://127.0.0.1:38414/", reuseExistingServer: false, timeout: 30_000 },
    { command: `node scripts/start-e2e-standalone.mjs --hostname 127.0.0.1 --port ${port}`,
      cwd: isolated, url: `http://127.0.0.1:${port}/order-desk`, reuseExistingServer: false, timeout: 60_000,
      env: { OMI_ORDER_DESK_FAKE_PORT: "38414", API_PROXY_TARGET: "http://127.0.0.1:9" } },
    { command: "node .next/standalone/server.js", cwd: isolated,
      url: "http://127.0.0.1:3315/order-desk", reuseExistingServer: false, timeout: 60_000,
      env: { HOSTNAME: "127.0.0.1", PORT: "3315", OMI_ORDER_DESK_FAKE_PORT: "", API_PROXY_TARGET: "http://127.0.0.1:9" } },
  ],
});

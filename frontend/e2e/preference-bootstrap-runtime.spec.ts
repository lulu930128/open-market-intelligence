import { expect, test, type Page } from "@playwright/test";

type PreferenceFrame = {
  at: number;
  visibility: string;
  state: string | undefined;
  bootstrap: string | undefined;
  theme: string | undefined;
  contrast: string | undefined;
  locale: string | undefined;
  lang: string;
  storedLocale: string | null;
};

declare global {
  interface Window {
    omiPreferenceProbe: {
      frames: PreferenceFrame[];
      firstVisible?: PreferenceFrame;
      writes: Array<{ key: string; value: string }>;
    };
  }
}

async function observePreferences(page: Page, japanese: boolean, storageUnavailable = false) {
  await page.addInitScript(({ japanese, storageUnavailable }) => {
    if (japanese) {
      localStorage.setItem("omi:settings:language", "ja-JP");
      localStorage.setItem("omi:settings:color", "dark");
      localStorage.setItem("omi:settings:high-contrast", "true");
    }
    const probe = window.omiPreferenceProbe = {
      frames: [] as PreferenceFrame[],
      firstVisible: undefined as PreferenceFrame | undefined,
      writes: [] as Array<{ key: string; value: string }>,
    };
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (["omi:settings:language", "omi:settings:color", "omi:settings:high-contrast"].includes(key)) {
        probe.writes.push({ key, value });
      }
      return originalSetItem.call(this, key, value);
    };
    if (storageUnavailable) {
      Object.defineProperty(window, "localStorage", {
        get() { throw new DOMException("Storage disabled for regression", "SecurityError"); },
      });
    }
    function sample() {
      const root = document.documentElement;
      if (root && document.body && document.body.querySelector("button")) {
        const frame: PreferenceFrame = {
          at: performance.now(),
          visibility: getComputedStyle(document.body).visibility,
          state: root.dataset.omiPreferenceState,
          bootstrap: root.dataset.omiPreferenceBootstrap,
          theme: root.dataset.theme,
          contrast: root.dataset.contrast,
          locale: root.dataset.locale,
          lang: root.lang,
          storedLocale: storageUnavailable ? null : localStorage.getItem("omi:settings:language"),
        };
        const previous = probe.frames.at(-1);
        if (!previous || ["visibility", "state", "bootstrap", "theme", "contrast", "locale", "lang", "storedLocale"].some(
          (key) => previous[key as keyof PreferenceFrame] !== frame[key as keyof PreferenceFrame]
        )) probe.frames.push(frame);
        if (frame.visibility === "visible" && !probe.firstVisible) probe.firstVisible = frame;
      }
      requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  }, { japanese, storageUnavailable });
}

test.describe("preference bootstrap browser regression", () => {
  test.skip(process.env.OMI_PREFERENCE_LIVE !== "1", "Opt in against the existing OMI runtime with OMI_PREFERENCE_LIVE=1");
  for (const path of ["/", "/?market=us&symbol=AMD"]) {
    for (const japanese of [false, true]) {
      test(`${path} first visible content uses ${japanese ? "persisted ja dark high" : "defaults"}`, async ({ page, browser }, testInfo) => {
        await observePreferences(page, japanese);
        const pageErrors: string[] = [];
        const consoleErrors: string[] = [];
        const httpErrors: string[] = [];
        const scriptWarnings: string[] = [];
        page.on("pageerror", (error) => pageErrors.push(error.message));
        page.on("console", (message) => {
          if (message.type() === "error") consoleErrors.push(message.text());
          if (/Encountered a script tag while rendering React component|Scripts inside React components are never executed|Cannot render a sync or defer <script> outside the main document/i.test(message.text())) {
            scriptWarnings.push(message.text());
          }
        });
        page.on("response", (response) => {
          if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`);
        });
        const response = await page.goto(path, { waitUntil: "domcontentloaded" });
        expect(response?.status()).toBe(200);
        await page.waitForFunction(() => Boolean(window.omiPreferenceProbe.firstVisible));
        const expected = japanese
          ? { theme: "dark", contrast: "high", locale: "ja-JP", lang: "ja", storedLocale: "ja-JP" }
          : { locale: "zh-TW", lang: "zh-Hant", storedLocale: null };
        const first = await page.evaluate(() => window.omiPreferenceProbe.firstVisible!);
        expect(first).toMatchObject({ ...expected, visibility: "visible", state: "ready", bootstrap: "ready" });
        const samples = [];
        for (const elapsed of [2000, 5000]) {
          await page.waitForFunction((elapsed) => performance.now() - window.omiPreferenceProbe.firstVisible!.at >= elapsed, elapsed);
          const sample = await page.evaluate(() => ({
            theme: document.documentElement.dataset.theme,
            contrast: document.documentElement.dataset.contrast,
            locale: document.documentElement.dataset.locale,
            lang: document.documentElement.lang,
            storedLocale: localStorage.getItem("omi:settings:language"),
          }));
          expect(sample).toMatchObject(expected);
          samples.push({ elapsed, ...sample });
        }
        const probe = await page.evaluate(() => window.omiPreferenceProbe);
        expect(probe.frames.filter((frame) => frame.visibility === "visible").every(
          (frame) => frame.locale === expected.locale && frame.lang === expected.lang && frame.storedLocale === expected.storedLocale
        )).toBe(true);
        expect(probe.writes).toEqual([]);
        // The empty Next dev indicator/toast is not an error overlay.
        await expect(page.locator('[data-nextjs-dialog-overlay], [data-nextjs-error-overlay]')).toHaveCount(0);
        expect(pageErrors).toEqual([]);
        expect(consoleErrors).toEqual([]);
        expect(httpErrors).toEqual([]);
        expect(scriptWarnings).toEqual([]);
        const evidence = {
          browser: browser.version(), path, japanese, probe, samples,
          pageErrors, consoleErrors, httpErrors, scriptWarnings,
          paints: await page.evaluate(() => performance.getEntriesByType("paint").map(({ name, startTime }) => ({ name, startTime }))),
        };
        await testInfo.attach("preference-timing", { body: JSON.stringify(evidence, null, 2), contentType: "application/json" });
        console.log(JSON.stringify(evidence));
      });
    }
  }

  test("unavailable storage still releases the gate to the default locale", async ({ page }) => {
    await observePreferences(page, false, true);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("html")).toHaveAttribute("data-omi-preference-state", "ready");
    await expect(page.locator("html")).toHaveAttribute("data-locale", "zh-TW");
    await expect(page.locator("body")).toHaveCSS("visibility", "visible");
    expect(await page.evaluate(() => window.omiPreferenceProbe.writes)).toEqual([]);
  });

  test("CSS visibility fail-safe works when client scripts never execute", async ({ browser, baseURL }) => {
    const context = await browser.newContext({ javaScriptEnabled: false, reducedMotion: "reduce" });
    const page = await context.newPage();
    try {
      await page.goto(baseURL!, { waitUntil: "domcontentloaded" });
      await expect(page.locator("body")).toHaveCSS("visibility", "visible", { timeout: 3000 });
      await expect(page.locator("html")).toHaveAttribute("data-omi-preference-state", "pending");
      await expect(page.locator("html")).not.toHaveAttribute("data-omi-preference-bootstrap", "ready");
    } finally {
      await context.close();
    }
  });

  test("explicit settings persist immediately and storage events never write back", async ({ page, context }) => {
    await observePreferences(page, true);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator("html")).toHaveAttribute("data-omi-preference-state", "ready");
    await page.getByRole("button", { name: /開啟設定|Open settings|設定を開く/ }).click();
    const language = page.locator('select:has(option[value="ja-JP"])');
    const color = page.locator('select:has(option[value="dark"])');
    await expect(language).toHaveValue("ja-JP");
    await expect(color).toHaveValue("dark");
    await language.selectOption("en-US");
    await color.selectOption("light");
    await page.getByRole("switch").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator("html")).not.toHaveAttribute("data-contrast", "high");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    expect(await page.evaluate(() => window.omiPreferenceProbe.writes)).toEqual([
      { key: "omi:settings:language", value: "en-US" },
      { key: "omi:settings:color", value: "light" },
      { key: "omi:settings:high-contrast", value: "false" },
    ]);
    const other = await context.newPage();
    await other.goto("/", { waitUntil: "domcontentloaded" });
    await expect(other.locator("html")).toHaveAttribute("data-omi-preference-state", "ready");
    await other.evaluate(() => localStorage.setItem("omi:settings:language", "ja-JP"));
    await expect(page.locator("html")).toHaveAttribute("lang", "ja");
    await expect(language).toHaveValue("ja-JP");
    await other.evaluate(() => localStorage.removeItem("omi:settings:language"));
    await expect(language).toHaveValue("zh-TW");
    await page.evaluate(() => {
      localStorage.setItem("omi:settings:language", "en-US");
      window.dispatchEvent(new Event("omi:locale-change"));
    });
    await expect(language).toHaveValue("en-US");
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    expect(await page.evaluate(() => window.omiPreferenceProbe.writes)).toHaveLength(4);
    await other.close();
  });
});

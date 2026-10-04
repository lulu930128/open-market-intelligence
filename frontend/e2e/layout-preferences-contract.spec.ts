import { readFileSync } from "node:fs";
import { join } from "node:path";
import { runInNewContext } from "node:vm";

import { expect, test } from "@playwright/test";
import ts from "typescript";

const layoutSource = readFileSync(join(process.cwd(), "src/app/layout.tsx"), "utf8");
const layout = ts.createSourceFile("layout.tsx", layoutSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const i18nSource = readFileSync(join(process.cwd(), "src/i18n/I18nProvider.tsx"), "utf8");
const settingsSource = readFileSync(join(process.cwd(), "src/components/SettingsDock.tsx"), "utf8");
const css = readFileSync(join(process.cwd(), "src/app/globals.css"), "utf8");

function calls(source: string, names: string[]) {
  const file = ts.createSourceFile("component.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const matches: ts.CallExpression[] = [];
  function visit(node: ts.Node) {
    if (ts.isCallExpression(node) && names.includes(node.expression.getText(file))) matches.push(node);
    ts.forEachChild(node, visit);
  }
  visit(file);
  return matches.map((node) => node.getText(file));
}

function preferenceScript() {
  for (const statement of layout.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (
        declaration.name.getText(layout) === "preferenceInitScript" &&
        declaration.initializer &&
        ts.isNoSubstitutionTemplateLiteral(declaration.initializer)
      ) {
        return declaration.initializer.text;
      }
    }
  }
  throw new Error("RootLayout must retain its preference initializer");
}

test("RootLayout keeps one framework-managed initializer before hydration", () => {
  expect(layout.statements.some((statement) =>
    ts.isExpressionStatement(statement) &&
    ts.isStringLiteral(statement.expression) &&
    statement.expression.text === "use client"
  )).toBe(false);

  const scriptImport = layout.statements.find((statement) =>
    ts.isImportDeclaration(statement) &&
    ts.isStringLiteral(statement.moduleSpecifier) &&
    statement.moduleSpecifier.text === "next/script"
  );
  if (!scriptImport || !ts.isImportDeclaration(scriptImport)) {
    throw new Error("RootLayout must use the Next script lifecycle");
  }
  const scriptName = scriptImport.importClause?.name?.text;
  expect(scriptName).toBeTruthy();
  const initializers: ts.JsxSelfClosingElement[] = [];
  function visit(node: ts.Node) {
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(layout) === scriptName) {
      initializers.push(node);
    }
    if (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) {
      expect(node.tagName.getText(layout), "raw scripts can warn during client rendering").not.toBe("script");
    }
    ts.forEachChild(node, visit);
  }
  visit(layout);
  expect(initializers).toHaveLength(1);
  const attributes = initializers[0].attributes.properties;
  const attribute = (name: string) => attributes.find((property) =>
    ts.isJsxAttribute(property) && property.name.getText(layout) === name
  );
  expect(attribute("id")?.getText(layout)).toBe('id="omi-preference-init"');
  expect(attribute("strategy")?.getText(layout)).toBe('strategy="beforeInteractive"');
  expect(attribute("dangerouslySetInnerHTML")?.getText(layout)).toContain("__html: preferenceInitScript");
});

const cases = [
  { name: "defaults", stored: {}, theme: undefined, contrast: undefined, locale: undefined, lang: "zh-Hant" },
  { name: "light English", stored: { color: "light", language: "en-US" }, theme: "light", contrast: undefined, locale: "en-US", lang: "en" },
  { name: "dark Japanese high contrast", stored: { color: "dark", "high-contrast": "true", language: "ja-JP" }, theme: "dark", contrast: "high", locale: "ja-JP", lang: "ja" },
  { name: "legacy high contrast", stored: { color: "high-contrast", language: "zh-TW" }, theme: "dark", contrast: "high", locale: "zh-TW", lang: "zh-Hant" },
  { name: "explicit contrast opt-out overrides legacy", stored: { color: "high-contrast", "high-contrast": "false" }, theme: "dark", contrast: undefined, locale: undefined, lang: "zh-Hant" },
  { name: "light high contrast", stored: { color: "light", "high-contrast": "true" }, theme: "light", contrast: "high", locale: undefined, lang: "zh-Hant" },
  { name: "invalid preferences keep defaults", stored: { color: "invalid", "high-contrast": "invalid", language: "invalid" }, theme: undefined, contrast: undefined, locale: undefined, lang: "zh-Hant" },
];

for (const scenario of cases) {
  test(`RootLayout preference initialization: ${scenario.name}`, () => {
    const stored: Record<string, string | undefined> = scenario.stored;
    const documentElement = { dataset: { omiPreferenceState: "pending" } as Record<string, string>, lang: "zh-Hant" };
    runInNewContext(preferenceScript(), {
      window: { localStorage: { getItem: (key: string) => stored[key.replace("omi:settings:", "")] ?? null } },
      document: { documentElement },
      setTimeout: () => 0,
    }, { timeout: 1_000 });
    expect(documentElement).toEqual({
      dataset: { omiPreferenceState: "pending", omiPreferenceBootstrap: "ready", theme: scenario.theme, contrast: scenario.contrast, locale: scenario.locale },
      lang: scenario.lang,
    });
  });
}

test("RootLayout tolerates unavailable localStorage without changing defaults", () => {
  const documentElement = { dataset: { omiPreferenceState: "pending" }, lang: "zh-Hant" };
  expect(() => runInNewContext(preferenceScript(), {
    window: { localStorage: { getItem: () => { throw new Error("Storage access denied"); } } },
    document: { documentElement },
    setTimeout: () => 0,
  }, { timeout: 1_000 })).not.toThrow();
  expect(documentElement).toEqual({ dataset: { omiPreferenceState: "pending", omiPreferenceBootstrap: "ready" }, lang: "zh-Hant" });
});

test("preference gate preserves layout and has a JS-independent visibility deadline", () => {
  expect(layoutSource.match(/data-omi-preference-state="pending"/g)).toHaveLength(1);
  const gate = css.match(/html\[data-omi-preference-state="pending"\] body\s*\{([^}]+)\}/)?.[1];
  expect(gate).toContain("visibility: hidden");
  expect(gate).not.toContain("display:");
  expect(gate).toContain("omi-preference-visibility-failsafe 0s 1500ms forwards");
  expect(css).toMatch(/@keyframes omi-preference-visibility-failsafe\s*\{\s*to\s*\{\s*visibility: visible/);
});

test("bootstrap and its bounded watchdog never persist or release the gate", () => {
  expect(preferenceScript()).not.toMatch(/setItem|removeItem|clear\(/);
  const documentElement = { dataset: { omiPreferenceState: "pending" } as Record<string, string>, lang: "zh-Hant" };
  let watchdog: (() => void) | undefined;
  runInNewContext(preferenceScript(), {
    window: { localStorage: { getItem: () => null } },
    document: { documentElement },
    setTimeout: (callback: () => void, delay: number) => {
      expect(delay).toBeGreaterThan(0);
      expect(delay).toBeLessThanOrEqual(1500);
      watchdog = callback;
    },
  });
  expect(documentElement.dataset.omiPreferenceBootstrap).toBe("ready");
  expect(watchdog).toBeDefined();
  watchdog!();
  expect(documentElement.dataset.omiPreferenceState).toBe("pending");
  expect(documentElement.dataset.omiPreferenceBootstrap).toBe("timeout");
  documentElement.dataset.omiPreferenceState = "ready";
  documentElement.dataset.omiPreferenceBootstrap = "ready";
  watchdog!();
  expect(documentElement.dataset.omiPreferenceBootstrap).toBe("ready");
});

test("only explicit preference handlers persist and theme initialization is read-only", () => {
  for (const effect of calls(i18nSource, ["useEffect", "useLayoutEffect"])) {
    expect(effect).not.toContain("writeStoredLocale");
  }
  expect(calls(i18nSource, ["writeStoredLocale"])).toEqual(["writeStoredLocale(nextLocale)"]);
  expect(i18nSource).toContain("if (locale !== readStoredLocale()) return;");
  expect(calls(i18nSource, ["useLayoutEffect"])[0]).toMatch(/applyDocumentLocale\(locale\);\s*document.documentElement.dataset.omiPreferenceState = "ready"/);
  for (const effect of calls(settingsSource, ["useEffect", "useLayoutEffect"])) {
    expect(effect).not.toMatch(/storePreference|storeBooleanPreference|applyColorTheme|applyHighContrastTheme/);
  }
  expect(settingsSource).toContain("onChange={handleColorChange}");
  expect(settingsSource).toContain("onChange={handleHighContrastChange}");
  expect(settingsSource).toMatch(/function handleColorChange\([^}]+setColor\(nextColor\);\s*storePreference\(SETTINGS_COLOR_STORAGE_KEY, nextColor\);\s*applyColorTheme\(nextColor\);/);
  expect(settingsSource).toMatch(/function handleHighContrastChange\([^}]+setHighContrast\(nextHighContrast\);\s*storeBooleanPreference\(SETTINGS_HIGH_CONTRAST_STORAGE_KEY, nextHighContrast\);\s*applyHighContrastTheme\(nextHighContrast\);/);
});

for (const stored of ["ja-JP", null, "invalid", "unavailable"]) {
  test(`I18n layout phase reconciles without writing storage: ${stored}`, () => {
    const documentElement = { dataset: { omiPreferenceState: "pending", locale: "ja-JP" }, lang: "ja" };
    let snapshot = "zh-TW";
    const writes: string[][] = [];
    const effects: Array<() => void> = [];
    let value: { setLocale: (locale: string) => void } | undefined;
    const compiled = { exports: {} as { I18nProvider: (props: { children: null }) => void } };
    const result = ts.transpileModule(i18nSource, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    });
    runInNewContext(result.outputText, {
      exports: compiled.exports,
      require: (name: string) => {
        if (name === "react") return {
          createContext: () => ({ Provider: "provider" }),
          useSyncExternalStore: () => snapshot,
          useLayoutEffect: (effect: () => void) => effects.push(effect),
          useCallback: (callback: unknown) => callback,
          useMemo: (factory: () => typeof value) => factory(),
        };
        if (name === "react/jsx-runtime") return {
          jsx: (_: unknown, props: { value: typeof value }) => { value = props.value; },
        };
        if (name === "./messages") return { translate: () => "" };
        if (name === "./locales") return {
          DEFAULT_LOCALE: "zh-TW",
          LOCALE_STORAGE_KEY: "omi:settings:language",
          LOCALE_HTML_LANG: { "zh-TW": "zh-Hant", "ja-JP": "ja", "en-US": "en" },
          isEnabledLocale: (locale: string) => ["zh-TW", "ja-JP", "en-US"].includes(locale),
        };
        throw new Error(`Unexpected import: ${name}`);
      },
      window: {
        localStorage: {
          getItem: () => { if (stored === "unavailable") throw new Error("Denied"); return stored; },
          setItem: (...args: string[]) => writes.push(args),
        },
        dispatchEvent: () => {},
      },
      document: { documentElement },
      Event: class {},
    });
    compiled.exports.I18nProvider({ children: null });
    effects.splice(0).forEach((effect) => effect());
    if (stored === "ja-JP") {
      expect(documentElement.dataset.omiPreferenceState).toBe("pending");
      expect(documentElement.lang).toBe("ja");
      snapshot = stored;
      compiled.exports.I18nProvider({ children: null });
      effects.splice(0).forEach((effect) => effect());
    }
    expect(documentElement.dataset.omiPreferenceState).toBe("ready");
    expect(documentElement.dataset.locale).toBe(stored === "ja-JP" ? "ja-JP" : "zh-TW");
    expect(writes).toEqual([]);
    value!.setLocale("en-US");
    expect(writes).toEqual([["omi:settings:language", "en-US"]]);
    expect(documentElement.lang).toBe("en");
  });
}

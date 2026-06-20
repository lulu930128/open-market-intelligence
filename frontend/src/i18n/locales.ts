export type AppLocale = "zh-TW" | "en-US" | "ja-JP";

export const DEFAULT_LOCALE: AppLocale = "zh-TW";
export const LOCALE_STORAGE_KEY = "omi:settings:language";

export const LOCALE_OPTIONS: Array<{
  value: AppLocale;
  enabled: boolean;
}> = [
  { value: "zh-TW", enabled: true },
  { value: "en-US", enabled: true },
  { value: "ja-JP", enabled: true },
];

export const LOCALE_HTML_LANG: Record<AppLocale, string> = {
  "zh-TW": "zh-Hant",
  "en-US": "en",
  "ja-JP": "ja",
};

const enabledLocales = new Set<AppLocale>(
  LOCALE_OPTIONS.filter((option) => option.enabled).map((option) => option.value)
);

export function isAppLocale(value: string | null | undefined): value is AppLocale {
  return value === "zh-TW" || value === "en-US" || value === "ja-JP";
}

export function isEnabledLocale(value: string | null | undefined): value is AppLocale {
  return isAppLocale(value) && enabledLocales.has(value);
}

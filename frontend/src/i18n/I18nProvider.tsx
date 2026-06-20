"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import {
  DEFAULT_LOCALE,
  LOCALE_HTML_LANG,
  LOCALE_STORAGE_KEY,
  isEnabledLocale,
  type AppLocale,
} from "./locales";
import { translate, type TranslationFunction } from "./messages";

const LOCALE_CHANGE_EVENT = "omi:locale-change";

type I18nContextValue = {
  locale: AppLocale;
  setLocale: (locale: AppLocale) => void;
  t: TranslationFunction;
};

const I18nContext = createContext<I18nContextValue | null>(null);

function readStoredLocale() {
  if (typeof window === "undefined") return DEFAULT_LOCALE;

  try {
    const value = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return isEnabledLocale(value) ? value : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

function subscribeLocale(callback: () => void) {
  if (typeof window === "undefined") return () => {};

  function onStorage(event: StorageEvent) {
    if (event.key === LOCALE_STORAGE_KEY) callback();
  }

  window.addEventListener("storage", onStorage);
  window.addEventListener(LOCALE_CHANGE_EVENT, callback);

  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(LOCALE_CHANGE_EVENT, callback);
  };
}

function writeStoredLocale(locale: AppLocale) {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // Ignore local preference failures; in-memory locale switching still works.
  }
}

function applyDocumentLocale(locale: AppLocale) {
  if (typeof document === "undefined") return;

  document.documentElement.lang = LOCALE_HTML_LANG[locale];
  document.documentElement.dataset.locale = locale;
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const locale = useSyncExternalStore(
    subscribeLocale,
    readStoredLocale,
    () => DEFAULT_LOCALE
  );

  useEffect(() => {
    writeStoredLocale(locale);
    applyDocumentLocale(locale);
  }, [locale]);

  const setLocale = useCallback((nextLocale: AppLocale) => {
    if (!isEnabledLocale(nextLocale)) return;
    writeStoredLocale(nextLocale);
    applyDocumentLocale(nextLocale);
    window.dispatchEvent(new Event(LOCALE_CHANGE_EVENT));
  }, []);

  const t = useCallback<TranslationFunction>(
    (key, values) => translate(locale, key, values),
    [locale]
  );

  const value = useMemo(
    () => ({
      locale,
      setLocale,
      t,
    }),
    [locale, setLocale, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used inside I18nProvider.");
  }

  return context;
}

export function useT() {
  return useI18n().t;
}

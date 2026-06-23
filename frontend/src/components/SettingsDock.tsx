"use client";

import {
  LOCALE_OPTIONS,
  type AppLocale,
  type TranslationFunction,
  useI18n,
  useT,
} from "@/i18n";
import DispatchSettingsDialog from "@/components/settings/DispatchSettingsDialog";
import { fetchJson, requestJson } from "@/lib/api";
import {
  loadRefreshExecutionSettings,
  setCachedRefreshExecutionSettings,
  type RefreshExecutionField,
  type RefreshExecutionMarket,
  type RefreshExecutionSettingsRead,
  type RefreshExecutionSettingsWrite,
} from "@/lib/refreshExecutionSettings";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type SaveState = "idle" | "saving" | "success" | "error";
type ColorSetting = "light" | "dark";
type ParameterSectionKey = "moving" | "trend" | "momentum" | "volatility" | "flow";
type SettingsDockPlacement = "fixed" | "inline";

type SettingsDockProps = {
  placement?: SettingsDockPlacement;
};

type TechnicalAnalysisSettingsRead = {
  kind: string;
  version: string;
  source: string;
  windows: {
    ma: number[];
    volume_ma: number[];
    max_gap_days: number;
  };
  periods: {
    macd: {
      fast: number;
      slow: number;
      signal: number;
    };
    rsi: number;
    atr: number;
    adx: number;
    roc: number;
    mfi: number;
    donchian: number;
    bollinger: {
      period: number;
      std_dev: number;
    };
    kd: {
      period: number;
      smooth: number;
    };
    support_resistance: number;
  };
  thresholds: {
    volume_ratio: number;
    near_level_pct: number;
    adx_trend: number;
    rsi: {
      bull_min: number;
      bull_max: number;
      weak_below: number;
      overheated_at: number;
    };
    mfi: {
      inflow_min: number;
      inflow_max: number;
      outflow_below: number;
    };
    kd: {
      overbought_k: number;
      overbought_d: number;
      oversold_k: number;
      oversold_d: number;
    };
    atr: {
      high_volatility_pct: number;
      expansion_multiplier: number;
      expansion_min_pct: number;
    };
    bollinger_squeeze_bandwidth_pct: number;
  };
  query_defaults: {
    ma_windows: string;
    volume_ma_windows: string;
    volume_ratio_threshold: number;
  };
  indicator_keys: Record<string, string | null>;
};

type TechnicalAnalysisSettingsWrite = Pick<
  TechnicalAnalysisSettingsRead,
  "windows" | "periods" | "thresholds"
>;

type ParameterDraft = Record<string, string>;
type RefreshDraft = Record<string, string>;

type ParameterField = {
  key: string;
  label: string;
  hint: string;
  unit?: string;
  inputMode?: "text" | "numeric" | "decimal";
  min?: number;
  step?: number;
};

type ParameterFieldTemplate = Omit<ParameterField, "label" | "hint">;

type ParameterSection = {
  key: ParameterSectionKey;
  label: string;
  eyebrow: string;
  description: string;
  fields: ParameterField[];
};

type ParameterSectionTemplate = {
  key: ParameterSectionKey;
  fields: ParameterFieldTemplate[];
};

type RefreshMarketSection = {
  key: RefreshExecutionMarket;
  label: string;
  eyebrow: string;
  description: string;
  fields: ParameterField[];
};

type RefreshFieldTemplate = Omit<ParameterFieldTemplate, "key"> & {
  key: RefreshExecutionField;
};

type RefreshMarketSectionTemplate = {
  key: RefreshExecutionMarket;
  fields: RefreshFieldTemplate[];
};

const SETTINGS_COLOR_STORAGE_KEY = "omi:settings:color";
const SETTINGS_HIGH_CONTRAST_STORAGE_KEY = "omi:settings:high-contrast";

const colorSettingChoices: ColorSetting[] = ["light", "dark"];

const refreshMarketSectionTemplates: RefreshMarketSectionTemplate[] = [
  {
    key: "tw",
    fields: [
      {
        key: "subresource_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.1,
        unit: "seconds",
      },
      {
        key: "observed_stock_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.1,
        unit: "seconds",
      },
      {
        key: "market_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.1,
        unit: "seconds",
      },
    ],
  },
  {
    key: "us",
    fields: [
      {
        key: "subresource_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.5,
        unit: "seconds",
      },
      {
        key: "observed_stock_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.5,
        unit: "seconds",
      },
      {
        key: "market_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.5,
        unit: "seconds",
      },
    ],
  },
  {
    key: "jp",
    fields: [
      {
        key: "subresource_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.5,
        unit: "seconds",
      },
      {
        key: "observed_stock_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.5,
        unit: "seconds",
      },
      {
        key: "market_refresh_interval_seconds",
        inputMode: "decimal",
        min: 0.1,
        step: 0.5,
        unit: "seconds",
      },
    ],
  },
];

const parameterSectionTemplates: ParameterSectionTemplate[] = [
  {
    key: "moving",
    fields: [
      {
        key: "maWindows",
        inputMode: "text",
      },
      {
        key: "volumeMaWindows",
        inputMode: "text",
      },
      {
        key: "volumeRatio",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "x",
      },
    ],
  },
  {
    key: "trend",
    fields: [
      { key: "macdFast", inputMode: "numeric", min: 1, step: 1 },
      { key: "macdSlow", inputMode: "numeric", min: 1, step: 1 },
      { key: "macdSignal", inputMode: "numeric", min: 1, step: 1 },
      { key: "adxPeriod", inputMode: "numeric", min: 1, step: 1 },
      { key: "adxTrend", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "donchianPeriod", inputMode: "numeric", min: 1, step: 1 },
      {
        key: "supportResistance",
        inputMode: "numeric",
        min: 1,
        step: 1,
      },
    ],
  },
  {
    key: "momentum",
    fields: [
      { key: "rsiPeriod", inputMode: "numeric", min: 1, step: 1 },
      { key: "rsiBullMin", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "rsiBullMax", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "rsiWeakBelow", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "rsiOverheated", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "kdPeriod", inputMode: "numeric", min: 1, step: 1 },
      { key: "kdSmooth", inputMode: "numeric", min: 1, step: 1 },
      { key: "kdOverboughtK", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "kdOverboughtD", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "kdOversoldK", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "kdOversoldD", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "rocPeriod", inputMode: "numeric", min: 1, step: 1 },
    ],
  },
  {
    key: "volatility",
    fields: [
      { key: "atrPeriod", inputMode: "numeric", min: 1, step: 1 },
      {
        key: "atrHighPct",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "%",
      },
      {
        key: "atrExpansion",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "x",
      },
      {
        key: "atrExpansionMinPct",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "%",
      },
      {
        key: "bollingerPeriod",
        inputMode: "numeric",
        min: 1,
        step: 1,
      },
      {
        key: "bollingerStdDev",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
      },
      {
        key: "bollingerSqueeze",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "%",
      },
      {
        key: "nearLevelPct",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "%",
      },
      {
        key: "maxGapDays",
        inputMode: "numeric",
        min: 1,
        step: 1,
        unit: "days",
      },
    ],
  },
  {
    key: "flow",
    fields: [
      { key: "mfiPeriod", inputMode: "numeric", min: 1, step: 1 },
      { key: "mfiInflowMin", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "mfiInflowMax", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "mfiOutflowBelow", inputMode: "decimal", min: 0, step: 0.5 },
    ],
  },
];

function localizeParameterSections(t: TranslationFunction): ParameterSection[] {
  return parameterSectionTemplates.map((section) => ({
    ...section,
    label: t(`settings.technical.sections.${section.key}.label`),
    eyebrow: t(`settings.technical.sections.${section.key}.eyebrow`),
    description: t(`settings.technical.sections.${section.key}.description`),
    fields: section.fields.map((field) => ({
      ...field,
      label: t(`settings.technical.fields.${field.key}.label`),
      hint: t(`settings.technical.fields.${field.key}.hint`),
      unit: field.unit === "days" ? t("settings.technical.units.days") : field.unit,
    })),
  }));
}

function localizeRefreshMarketSections(t: TranslationFunction): RefreshMarketSection[] {
  return refreshMarketSectionTemplates.map((section) => ({
    ...section,
    label: t(`settings.refresh.markets.${section.key}.label`),
    eyebrow: t(`settings.refresh.markets.${section.key}.eyebrow`),
    description: t(`settings.refresh.markets.${section.key}.description`),
    fields: section.fields.map((field) => ({
      ...field,
      label: t(`settings.refresh.fields.${field.key}.label`),
      hint: t(`settings.refresh.fields.${field.key}.hint`),
      unit: field.unit === "seconds" ? t("settings.refresh.units.seconds") : field.unit,
    })),
  }));
}

function readStoredColorSetting(): ColorSetting {
  if (typeof window === "undefined") return "light";

  try {
    const value = window.localStorage.getItem(SETTINGS_COLOR_STORAGE_KEY);
    if (value === "high-contrast") return "dark";
    return colorSettingChoices.includes(value as ColorSetting)
      ? (value as ColorSetting)
      : "light";
  } catch {
    return "light";
  }
}

function readStoredHighContrastSetting() {
  if (typeof window === "undefined") return false;

  try {
    const explicit = window.localStorage.getItem(SETTINGS_HIGH_CONTRAST_STORAGE_KEY);
    if (explicit === "true") return true;
    if (explicit === "false") return false;
    return window.localStorage.getItem(SETTINGS_COLOR_STORAGE_KEY) === "high-contrast";
  } catch {
    return false;
  }
}

function storePreference(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore local preference failures; the app can still run with in-memory state.
  }
}

function storeBooleanPreference(key: string, value: boolean) {
  storePreference(key, value ? "true" : "false");
}

function applyColorTheme(value: ColorSetting) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = value;
}

function applyHighContrastTheme(value: boolean) {
  if (typeof document === "undefined") return;
  if (value) {
    document.documentElement.dataset.contrast = "high";
  } else {
    delete document.documentElement.dataset.contrast;
  }
}

function themePreferenceLabel(
  color: ColorSetting,
  highContrast: boolean,
  t: TranslationFunction
) {
  const base = t(`settings.colors.${color}`);
  return highContrast ? `${base} / ${t("settings.highContrast")}` : base;
}

function stringValue(value: number | string | null | undefined) {
  if (value === null || value === undefined) return "";
  return String(value);
}

function buildParameterDraft(settings: TechnicalAnalysisSettingsRead): ParameterDraft {
  return {
    maWindows: settings.query_defaults.ma_windows,
    volumeMaWindows: settings.query_defaults.volume_ma_windows,
    volumeRatio: stringValue(settings.thresholds.volume_ratio),
    macdFast: stringValue(settings.periods.macd.fast),
    macdSlow: stringValue(settings.periods.macd.slow),
    macdSignal: stringValue(settings.periods.macd.signal),
    adxPeriod: stringValue(settings.periods.adx),
    adxTrend: stringValue(settings.thresholds.adx_trend),
    donchianPeriod: stringValue(settings.periods.donchian),
    supportResistance: stringValue(settings.periods.support_resistance),
    rsiPeriod: stringValue(settings.periods.rsi),
    rsiBullMin: stringValue(settings.thresholds.rsi.bull_min),
    rsiBullMax: stringValue(settings.thresholds.rsi.bull_max),
    rsiWeakBelow: stringValue(settings.thresholds.rsi.weak_below),
    rsiOverheated: stringValue(settings.thresholds.rsi.overheated_at),
    kdPeriod: stringValue(settings.periods.kd.period),
    kdSmooth: stringValue(settings.periods.kd.smooth),
    kdOverboughtK: stringValue(settings.thresholds.kd.overbought_k),
    kdOverboughtD: stringValue(settings.thresholds.kd.overbought_d),
    kdOversoldK: stringValue(settings.thresholds.kd.oversold_k),
    kdOversoldD: stringValue(settings.thresholds.kd.oversold_d),
    rocPeriod: stringValue(settings.periods.roc),
    atrPeriod: stringValue(settings.periods.atr),
    atrHighPct: stringValue(settings.thresholds.atr.high_volatility_pct),
    atrExpansion: stringValue(settings.thresholds.atr.expansion_multiplier),
    atrExpansionMinPct: stringValue(settings.thresholds.atr.expansion_min_pct),
    bollingerPeriod: stringValue(settings.periods.bollinger.period),
    bollingerStdDev: stringValue(settings.periods.bollinger.std_dev),
    bollingerSqueeze: stringValue(settings.thresholds.bollinger_squeeze_bandwidth_pct),
    nearLevelPct: stringValue(settings.thresholds.near_level_pct),
    maxGapDays: stringValue(settings.windows.max_gap_days),
    mfiPeriod: stringValue(settings.periods.mfi),
    mfiInflowMin: stringValue(settings.thresholds.mfi.inflow_min),
    mfiInflowMax: stringValue(settings.thresholds.mfi.inflow_max),
    mfiOutflowBelow: stringValue(settings.thresholds.mfi.outflow_below),
  };
}

function refreshDraftKey(
  market: RefreshExecutionMarket,
  field: RefreshExecutionField
) {
  return `${market}.${field}`;
}

function buildRefreshDraft(settings: RefreshExecutionSettingsRead): RefreshDraft {
  return {
    [refreshDraftKey("tw", "observed_stock_refresh_interval_seconds")]: stringValue(
      settings.markets.tw.observed_stock_refresh_interval_seconds
    ),
    [refreshDraftKey("tw", "subresource_refresh_interval_seconds")]: stringValue(
      settings.markets.tw.subresource_refresh_interval_seconds
    ),
    [refreshDraftKey("tw", "market_refresh_interval_seconds")]: stringValue(
      settings.markets.tw.market_refresh_interval_seconds
    ),
    [refreshDraftKey("us", "observed_stock_refresh_interval_seconds")]: stringValue(
      settings.markets.us.observed_stock_refresh_interval_seconds
    ),
    [refreshDraftKey("us", "subresource_refresh_interval_seconds")]: stringValue(
      settings.markets.us.subresource_refresh_interval_seconds
    ),
    [refreshDraftKey("us", "market_refresh_interval_seconds")]: stringValue(
      settings.markets.us.market_refresh_interval_seconds
    ),
    [refreshDraftKey("jp", "observed_stock_refresh_interval_seconds")]: stringValue(
      settings.markets.jp.observed_stock_refresh_interval_seconds
    ),
    [refreshDraftKey("jp", "subresource_refresh_interval_seconds")]: stringValue(
      settings.markets.jp.subresource_refresh_interval_seconds
    ),
    [refreshDraftKey("jp", "market_refresh_interval_seconds")]: stringValue(
      settings.markets.jp.market_refresh_interval_seconds
    ),
  };
}

function parseWindowList(
  value: string | undefined,
  label: string,
  t: TranslationFunction
) {
  const windows = (value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item));

  if (!windows.length) {
    throw new Error(t("settings.validation.windowRequired", { label }));
  }

  for (const window of windows) {
    if (!Number.isInteger(window) || window <= 0) {
      throw new Error(t("settings.validation.positiveIntegers", { label }));
    }
  }

  return Array.from(new Set(windows)).sort((a, b) => a - b);
}

function parseNumberValue(
  draft: ParameterDraft,
  key: string,
  label: string,
  t: TranslationFunction,
  options: { integer?: boolean } = {}
) {
  const rawValue = draft[key]?.trim();
  if (!rawValue) {
    throw new Error(t("settings.validation.required", { label }));
  }

  const value = Number(rawValue);
  if (!Number.isFinite(value)) {
    throw new Error(t("settings.validation.number", { label }));
  }

  if (options.integer && !Number.isInteger(value)) {
    throw new Error(t("settings.validation.integer", { label }));
  }

  if (value <= 0) {
    throw new Error(t("settings.validation.positive", { label }));
  }

  return value;
}

function buildTechnicalSettingsWritePayload(
  draft: ParameterDraft,
  t: TranslationFunction
): TechnicalAnalysisSettingsWrite {
  const fieldLabel = (key: string) => t(`settings.technical.fields.${key}.label`);

  return {
    windows: {
      ma: parseWindowList(draft.maWindows, fieldLabel("maWindows"), t),
      volume_ma: parseWindowList(draft.volumeMaWindows, fieldLabel("volumeMaWindows"), t),
      max_gap_days: parseNumberValue(draft, "maxGapDays", fieldLabel("maxGapDays"), t, {
        integer: true,
      }),
    },
    periods: {
      macd: {
        fast: parseNumberValue(draft, "macdFast", fieldLabel("macdFast"), t, { integer: true }),
        slow: parseNumberValue(draft, "macdSlow", fieldLabel("macdSlow"), t, { integer: true }),
        signal: parseNumberValue(draft, "macdSignal", fieldLabel("macdSignal"), t, { integer: true }),
      },
      rsi: parseNumberValue(draft, "rsiPeriod", fieldLabel("rsiPeriod"), t, { integer: true }),
      atr: parseNumberValue(draft, "atrPeriod", fieldLabel("atrPeriod"), t, { integer: true }),
      adx: parseNumberValue(draft, "adxPeriod", fieldLabel("adxPeriod"), t, { integer: true }),
      roc: parseNumberValue(draft, "rocPeriod", fieldLabel("rocPeriod"), t, { integer: true }),
      mfi: parseNumberValue(draft, "mfiPeriod", fieldLabel("mfiPeriod"), t, { integer: true }),
      donchian: parseNumberValue(draft, "donchianPeriod", fieldLabel("donchianPeriod"), t, {
        integer: true,
      }),
      bollinger: {
        period: parseNumberValue(draft, "bollingerPeriod", fieldLabel("bollingerPeriod"), t, {
          integer: true,
        }),
        std_dev: parseNumberValue(draft, "bollingerStdDev", fieldLabel("bollingerStdDev"), t),
      },
      kd: {
        period: parseNumberValue(draft, "kdPeriod", fieldLabel("kdPeriod"), t, { integer: true }),
        smooth: parseNumberValue(draft, "kdSmooth", fieldLabel("kdSmooth"), t, { integer: true }),
      },
      support_resistance: parseNumberValue(
        draft,
        "supportResistance",
        fieldLabel("supportResistance"),
        t,
        { integer: true }
      ),
    },
    thresholds: {
      volume_ratio: parseNumberValue(draft, "volumeRatio", fieldLabel("volumeRatio"), t),
      near_level_pct: parseNumberValue(draft, "nearLevelPct", fieldLabel("nearLevelPct"), t),
      adx_trend: parseNumberValue(draft, "adxTrend", fieldLabel("adxTrend"), t),
      rsi: {
        bull_min: parseNumberValue(draft, "rsiBullMin", fieldLabel("rsiBullMin"), t),
        bull_max: parseNumberValue(draft, "rsiBullMax", fieldLabel("rsiBullMax"), t),
        weak_below: parseNumberValue(draft, "rsiWeakBelow", fieldLabel("rsiWeakBelow"), t),
        overheated_at: parseNumberValue(draft, "rsiOverheated", fieldLabel("rsiOverheated"), t),
      },
      mfi: {
        inflow_min: parseNumberValue(draft, "mfiInflowMin", fieldLabel("mfiInflowMin"), t),
        inflow_max: parseNumberValue(draft, "mfiInflowMax", fieldLabel("mfiInflowMax"), t),
        outflow_below: parseNumberValue(draft, "mfiOutflowBelow", fieldLabel("mfiOutflowBelow"), t),
      },
      kd: {
        overbought_k: parseNumberValue(draft, "kdOverboughtK", fieldLabel("kdOverboughtK"), t),
        overbought_d: parseNumberValue(draft, "kdOverboughtD", fieldLabel("kdOverboughtD"), t),
        oversold_k: parseNumberValue(draft, "kdOversoldK", fieldLabel("kdOversoldK"), t),
        oversold_d: parseNumberValue(draft, "kdOversoldD", fieldLabel("kdOversoldD"), t),
      },
      atr: {
        high_volatility_pct: parseNumberValue(draft, "atrHighPct", fieldLabel("atrHighPct"), t),
        expansion_multiplier: parseNumberValue(draft, "atrExpansion", fieldLabel("atrExpansion"), t),
        expansion_min_pct: parseNumberValue(draft, "atrExpansionMinPct", fieldLabel("atrExpansionMinPct"), t),
      },
      bollinger_squeeze_bandwidth_pct: parseNumberValue(
        draft,
        "bollingerSqueeze",
        fieldLabel("bollingerSqueeze"),
        t
      ),
    },
  };
}

function refreshFieldLabel(
  market: RefreshExecutionMarket,
  field: RefreshExecutionField,
  t: TranslationFunction
) {
  return `${t(`settings.refresh.markets.${market}.label`)} ${t(
    `settings.refresh.fields.${field}.label`
  )}`;
}

function buildRefreshMarketPolicyPayload(
  draft: RefreshDraft,
  market: RefreshExecutionMarket,
  t: TranslationFunction
) {
  return {
    observed_stock_refresh_interval_seconds: parseNumberValue(
      draft,
      refreshDraftKey(market, "observed_stock_refresh_interval_seconds"),
      refreshFieldLabel(market, "observed_stock_refresh_interval_seconds", t),
      t
    ),
    subresource_refresh_interval_seconds: parseNumberValue(
      draft,
      refreshDraftKey(market, "subresource_refresh_interval_seconds"),
      refreshFieldLabel(market, "subresource_refresh_interval_seconds", t),
      t
    ),
    market_refresh_interval_seconds: parseNumberValue(
      draft,
      refreshDraftKey(market, "market_refresh_interval_seconds"),
      refreshFieldLabel(market, "market_refresh_interval_seconds", t),
      t
    ),
  };
}

function buildRefreshSettingsWritePayload(
  draft: RefreshDraft,
  t: TranslationFunction
): RefreshExecutionSettingsWrite {
  return {
    markets: {
      tw: buildRefreshMarketPolicyPayload(draft, "tw", t),
      us: buildRefreshMarketPolicyPayload(draft, "us", t),
      jp: buildRefreshMarketPolicyPayload(draft, "jp", t),
    },
  };
}

function GearIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="none">
      <path
        d="M12 8.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7Z"
        stroke="currentColor"
        strokeWidth="1.7"
      />
      <path
        d="M19 13.2v-2.4l-2.1-.5a6.3 6.3 0 0 0-.7-1.6l1.1-1.8-1.7-1.7-1.8 1.1a6.3 6.3 0 0 0-1.6-.7L11.8 3H9.4L9 5.1a6.3 6.3 0 0 0-1.6.7L5.6 4.7 3.9 6.4 5 8.2a6.3 6.3 0 0 0-.7 1.6L2.2 10.2v2.4l2.1.5c.2.6.4 1.1.7 1.6l-1.1 1.8 1.7 1.7 1.8-1.1c.5.3 1 .5 1.6.7l.4 2.1h2.4l.5-2.1c.6-.2 1.1-.4 1.6-.7l1.8 1.1 1.7-1.7-1.1-1.8c.3-.5.5-1 .7-1.6l2.1-.4Z"
        stroke="currentColor"
        strokeWidth="1.45"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4" fill="none">
      <path d="m7.5 4.5 5 5.5-5 5.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4" fill="none">
      <path d="m5 5 10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function PreferenceSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Array<{ value: T; label: string; disabled?: boolean }>;
  onChange: (value: T) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
      <span className="font-semibold text-omi-text">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        className="h-8 max-w-[128px] border border-omi-border bg-omi-surface px-2 text-xs font-semibold text-omi-text-muted outline-none hover:border-omi-border-strong focus:border-omi-accent"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function PreferenceSwitch({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-omi-surface-subtle focus:outline-none focus-visible:ring-2 focus-visible:ring-omi-accent"
      onClick={() => onChange(!checked)}
    >
      <span className="font-semibold text-omi-text">{label}</span>
      <span
        aria-hidden="true"
        className={[
          "relative h-5 w-9 shrink-0 rounded-full border transition-colors",
          checked
            ? "border-omi-accent bg-omi-accent"
            : "border-omi-border bg-omi-surface-strong",
        ].join(" ")}
      >
        <span
          className={[
            "absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 rounded-full transition-transform",
            checked
              ? "translate-x-[18px] bg-omi-text-inverse"
              : "translate-x-0.5 bg-omi-text-muted",
          ].join(" ")}
        />
      </span>
    </button>
  );
}

function ParameterInput({
  field,
  value,
  onChange,
}: {
  field: ParameterField;
  value: string;
  onChange: (key: string, value: string) => void;
}) {
  const type = field.inputMode === "text" ? "text" : "number";

  return (
    <label className="grid gap-2 border-t border-omi-border-subtle px-4 py-3 first:border-t-0 sm:grid-cols-[180px_minmax(0,1fr)] sm:items-center">
      <span className="min-w-0">
        <span className="block text-sm font-bold text-omi-text">{field.label}</span>
        <span className="block text-xs leading-5 text-omi-text-muted">{field.hint}</span>
      </span>
      <span className="flex min-w-0 items-center gap-2">
        <input
          type={type}
          inputMode={field.inputMode}
          min={field.min}
          step={field.step}
          value={value ?? ""}
          onChange={(event) => onChange(field.key, event.target.value)}
          className="h-9 min-w-0 flex-1 border border-omi-border bg-omi-surface px-3 text-sm font-semibold text-omi-text-strong outline-none focus:border-omi-accent"
        />
        {field.unit ? (
          <span className="w-8 shrink-0 text-xs font-semibold text-omi-text-muted">
            {field.unit}
          </span>
        ) : null}
      </span>
    </label>
  );
}

function SourceLabel({
  settings,
}: {
  settings: { source: string; version: string } | null;
}) {
  if (!settings) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-omi-text-muted">
      <span className="border border-omi-border-subtle bg-omi-surface-subtle px-2 py-1 font-semibold text-omi-text-muted">
        {settings.source}
      </span>
      <span>{settings.version}</span>
    </div>
  );
}

export default function SettingsDock({ placement = "fixed" }: SettingsDockProps) {
  const t = useT();
  const { locale, setLocale } = useI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const [parametersOpen, setParametersOpen] = useState(false);
  const [refreshOpen, setRefreshOpen] = useState(false);
  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [refreshLoadState, setRefreshLoadState] = useState<LoadState>("idle");
  const [refreshSaveState, setRefreshSaveState] = useState<SaveState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [refreshErrorMessage, setRefreshErrorMessage] = useState<string | null>(null);
  const [refreshSaveMessage, setRefreshSaveMessage] = useState<string | null>(null);
  const [settings, setSettings] = useState<TechnicalAnalysisSettingsRead | null>(null);
  const [refreshSettings, setRefreshSettings] =
    useState<RefreshExecutionSettingsRead | null>(null);
  const [draft, setDraft] = useState<ParameterDraft>({});
  const [refreshDraft, setRefreshDraft] = useState<RefreshDraft>({});
  const [activeSectionKey, setActiveSectionKey] = useState<ParameterSectionKey>("moving");
  const [activeRefreshMarket, setActiveRefreshMarket] =
    useState<RefreshExecutionMarket>("tw");
  const [color, setColor] = useState<ColorSetting>(() => readStoredColorSetting());
  const [highContrast, setHighContrast] = useState(() => readStoredHighContrastSetting());
  const rootRef = useRef<HTMLDivElement | null>(null);

  const parameterSections = useMemo(() => localizeParameterSections(t), [t]);
  const refreshMarketSections = useMemo(() => localizeRefreshMarketSections(t), [t]);

  const activeSection = useMemo(
    () =>
      parameterSections.find((section) => section.key === activeSectionKey) ??
      parameterSections[0],
    [activeSectionKey, parameterSections]
  );

  const activeRefreshSection = useMemo(
    () =>
      refreshMarketSections.find((section) => section.key === activeRefreshMarket) ??
      refreshMarketSections[0],
    [activeRefreshMarket, refreshMarketSections]
  );

  const loadSettings = useCallback(async () => {
    setLoadState("loading");
    setErrorMessage(null);
    setSaveMessage(null);

    try {
      const payload = await fetchJson<TechnicalAnalysisSettingsRead>(
        "/api/settings/technical-analysis"
      );
      setSettings(payload);
      setDraft(buildParameterDraft(payload));
      setLoadState("success");
      setSaveState("idle");
    } catch (error) {
      setLoadState("error");
      setErrorMessage(error instanceof Error ? error.message : t("settings.loadError"));
    }
  }, [t]);

  const loadRefreshSettings = useCallback(async () => {
    setRefreshLoadState("loading");
    setRefreshErrorMessage(null);
    setRefreshSaveMessage(null);

    try {
      const payload = await loadRefreshExecutionSettings();
      setRefreshSettings(payload);
      setRefreshDraft(buildRefreshDraft(payload));
      setRefreshLoadState("success");
      setRefreshSaveState("idle");
    } catch (error) {
      setRefreshLoadState("error");
      setRefreshErrorMessage(
        error instanceof Error ? error.message : t("settings.loadError")
      );
    }
  }, [t]);

  useEffect(() => {
    storePreference(SETTINGS_COLOR_STORAGE_KEY, color);
    applyColorTheme(color);
  }, [color]);

  useEffect(() => {
    storeBooleanPreference(SETTINGS_HIGH_CONTRAST_STORAGE_KEY, highContrast);
    applyHighContrastTheme(highContrast);
  }, [highContrast]);

  useEffect(() => {
    if (!menuOpen) return;

    function closeOnOutsideClick(event: MouseEvent) {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (rootRef.current?.contains(target)) return;
      setMenuOpen(false);
    }

    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [menuOpen]);

  useEffect(() => {
    if (!parametersOpen && !refreshOpen && !dispatchOpen) return;

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setParametersOpen(false);
      setRefreshOpen(false);
      setDispatchOpen(false);
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [parametersOpen, refreshOpen, dispatchOpen]);

  function openParameterDialog() {
    setMenuOpen(false);
    setParametersOpen(true);
    if (loadState === "idle" || (loadState === "error" && settings === null)) {
      void loadSettings();
    }
  }

  function openRefreshDialog() {
    setMenuOpen(false);
    setRefreshOpen(true);
    if (
      refreshLoadState === "idle" ||
      (refreshLoadState === "error" && refreshSettings === null)
    ) {
      void loadRefreshSettings();
    }
  }

  function openDispatchDialog() {
    setMenuOpen(false);
    setDispatchOpen(true);
  }

  function updateDraftValue(key: string, value: string) {
    setSaveState("idle");
    setSaveMessage(null);
    setDraft((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function updateRefreshDraftValue(key: string, value: string) {
    setRefreshSaveState("idle");
    setRefreshSaveMessage(null);
    setRefreshDraft((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function resetDraft() {
    if (settings) {
      setDraft(buildParameterDraft(settings));
      setSaveState("idle");
      setSaveMessage(null);
    }
  }

  function resetRefreshDraft() {
    if (refreshSettings) {
      setRefreshDraft(buildRefreshDraft(refreshSettings));
      setRefreshSaveState("idle");
      setRefreshSaveMessage(null);
    }
  }

  async function saveTechnicalSettings() {
    setSaveState("saving");
    setSaveMessage(null);

    try {
      const payload = buildTechnicalSettingsWritePayload(draft, t);
      const response = await requestJson<TechnicalAnalysisSettingsRead>(
        "/api/settings/technical-analysis",
        {
          method: "PUT",
          body: JSON.stringify(payload),
        }
      );

      setSettings(response);
      setDraft(buildParameterDraft(response));
      setLoadState("success");
      setSaveState("success");
      setSaveMessage(t("settings.saveSuccess"));
    } catch (error) {
      setSaveState("error");
      setSaveMessage(error instanceof Error ? error.message : t("settings.saveError"));
    }
  }

  async function saveRefreshSettings() {
    setRefreshSaveState("saving");
    setRefreshSaveMessage(null);

    try {
      const payload = buildRefreshSettingsWritePayload(refreshDraft, t);
      const response = await requestJson<RefreshExecutionSettingsRead>(
        "/api/settings/refresh-execution",
        {
          method: "PUT",
          body: JSON.stringify(payload),
        }
      );

      setCachedRefreshExecutionSettings(response);
      setRefreshSettings(response);
      setRefreshDraft(buildRefreshDraft(response));
      setRefreshLoadState("success");
      setRefreshSaveState("success");
      setRefreshSaveMessage(t("settings.refresh.saveSuccess"));
    } catch (error) {
      setRefreshSaveState("error");
      setRefreshSaveMessage(
        error instanceof Error ? error.message : t("settings.saveError")
      );
    }
  }

  const inline = placement === "inline";
  const rootClassName = inline
    ? "relative z-[2147483645]"
    : "fixed bottom-4 left-4 z-[2147483645] sm:left-[206px]";
  const menuClassName = inline
    ? "absolute bottom-10 right-0 w-64 border border-omi-border bg-omi-surface text-left shadow-2xl"
    : "absolute bottom-12 right-0 w-64 border border-omi-border bg-omi-surface text-left shadow-2xl";
  const buttonClassName = inline
    ? "inline-flex h-8 items-center gap-2 whitespace-nowrap border border-omi-border bg-omi-surface-muted px-3 text-xs font-semibold text-omi-text-muted transition hover:bg-omi-surface-strong hover:text-omi-text"
    : "inline-flex h-10 items-center gap-2 border border-omi-control bg-omi-control px-3 text-sm font-bold text-omi-text-inverse shadow-lg transition hover:bg-omi-control-hover";

  return (
    <>
      <div
        ref={rootRef}
        className={rootClassName}
      >
        {menuOpen ? (
          <section className={menuClassName}>
            <div className="border-b border-omi-border-subtle bg-omi-control px-3 py-2 text-sm font-bold text-omi-text-inverse">
              {t("settings.title")}
            </div>
            <div className="divide-y divide-omi-border-subtle">
              <PreferenceSelect<AppLocale>
                label={t("settings.language")}
                value={locale}
                options={LOCALE_OPTIONS.map((option) => ({
                  value: option.value,
                  label: option.enabled
                    ? t(`locales.${option.value}`)
                    : `${t(`locales.${option.value}`)} (${t("common.reserved")})`,
                  disabled: !option.enabled,
                }))}
                onChange={setLocale}
              />
              <PreferenceSelect<ColorSetting>
                label={t("settings.color")}
                value={color}
                options={[
                  { value: "light", label: t("settings.colors.light") },
                  { value: "dark", label: t("settings.colors.dark") },
                ]}
                onChange={setColor}
              />
              <PreferenceSwitch
                label={t("settings.highContrast")}
                checked={highContrast}
                onChange={setHighContrast}
              />
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-omi-surface-subtle"
                onClick={openParameterDialog}
              >
                <span>
                  <span className="block font-semibold text-omi-text">
                    {t("settings.technicalParams")}
                  </span>
                  <span className="block text-xs text-omi-text-muted">
                    {t("settings.technicalAnalysis")}
                  </span>
                </span>
                <ChevronIcon />
              </button>
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-omi-surface-subtle"
                onClick={openRefreshDialog}
              >
                <span>
                  <span className="block font-semibold text-omi-text">
                    {t("settings.refreshExecution")}
                  </span>
                  <span className="block text-xs text-omi-text-muted">
                    {t("settings.refreshExecutionHint")}
                  </span>
                </span>
                <ChevronIcon />
              </button>
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-omi-surface-subtle"
                onClick={openDispatchDialog}
              >
                <span>
                  <span className="block font-semibold text-omi-text">
                    {t("settings.dispatch.title")}
                  </span>
                  <span className="block text-xs text-omi-text-muted">
                    {t("settings.dispatch.menuHint")}
                  </span>
                </span>
                <ChevronIcon />
              </button>
            </div>
          </section>
        ) : null}

        <button
          type="button"
          aria-expanded={menuOpen}
          aria-label={t("settings.open")}
          className={buttonClassName}
          onClick={() => setMenuOpen((value) => !value)}
        >
          <GearIcon />
          <span>{t("settings.title")}</span>
        </button>
      </div>

      {parametersOpen ? (
        <div className="fixed inset-0 z-[2147483646] flex items-center justify-center bg-omi-overlay p-4">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="technical-settings-title"
            className="flex h-[740px] max-h-[calc(100vh-2rem)] w-[920px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden border border-omi-control-border bg-omi-surface shadow-2xl"
          >
            <header className="flex shrink-0 items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
              <div className="min-w-0">
                <div className="text-xs font-bold uppercase tracking-[0.22em] text-omi-accent">
                  Settings
                </div>
                <h2 id="technical-settings-title" className="mt-1 text-xl font-black text-omi-text-strong">
                  {t("settings.technicalParams")}
                </h2>
                <div className="mt-2">
                  <SourceLabel settings={settings} />
                </div>
              </div>
              <button
                type="button"
                aria-label={t("settings.closeTechnicalParams")}
                className="grid h-8 w-8 shrink-0 place-items-center border border-omi-border text-omi-text-muted hover:border-omi-control hover:text-omi-text-strong"
                onClick={() => setParametersOpen(false)}
              >
                <CloseIcon />
              </button>
            </header>

            <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)]">
              <nav className="min-h-0 overflow-y-auto border-b border-omi-border-subtle bg-omi-surface-subtle p-3 md:border-b-0 md:border-r">
                <div className="grid gap-1">
                  {parameterSections.map((section) => (
                    <button
                      key={section.key}
                      type="button"
                      className={[
                        "w-full px-3 py-2 text-left transition",
                        activeSection.key === section.key
                          ? "bg-omi-control text-omi-text-inverse"
                          : "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong",
                      ].join(" ")}
                      onClick={() => setActiveSectionKey(section.key)}
                    >
                      <span className="block text-sm font-bold">{section.label}</span>
                      <span
                        className={
                          activeSection.key === section.key
                            ? "block text-[11px] text-omi-border"
                            : "block text-[11px] text-omi-text-muted"
                        }
                      >
                        {section.eyebrow}
                      </span>
                    </button>
                  ))}
                </div>
              </nav>

              <div className="min-h-0 overflow-y-auto overscroll-contain">
                <div className="border-b border-omi-border-subtle px-5 py-4">
                  <div className="text-xs font-bold uppercase tracking-[0.18em] text-omi-text-muted">
                    {activeSection.eyebrow}
                  </div>
                  <h3 className="mt-1 text-lg font-black text-omi-text-strong">
                    {activeSection.label}
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-omi-text-muted">
                    {activeSection.description}
                  </p>
                </div>

                {loadState === "loading" ? (
                  <div className="space-y-3 p-5" aria-live="polite">
                    {Array.from({ length: 6 }).map((_, index) => (
                      <div key={index} className="grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)]">
                        <div>
                          <div className="omi-skeleton h-4 w-24" />
                          <div className="mt-2 omi-skeleton h-3 w-36" />
                        </div>
                        <div className="omi-skeleton h-9 w-full" />
                      </div>
                    ))}
                  </div>
                ) : errorMessage ? (
                  <div className="m-5 border border-omi-danger-border bg-omi-danger-soft px-4 py-3 text-sm text-omi-danger">
                    <div className="font-bold">{t("settings.loadError")}</div>
                    <div className="mt-1 break-words text-xs leading-5">{errorMessage}</div>
                    <button
                      type="button"
                      className="mt-3 h-8 border border-omi-accent-border bg-omi-surface px-3 text-xs font-bold text-omi-danger hover:border-omi-danger"
                      onClick={() => void loadSettings()}
                    >
                      {t("settings.retry")}
                    </button>
                  </div>
                ) : (
                  <div>
                    {activeSection.fields.map((field) => (
                      <ParameterInput
                        key={field.key}
                        field={field}
                        value={draft[field.key] ?? ""}
                        onChange={updateDraftValue}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>

            <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-omi-border-subtle bg-omi-surface-subtle px-5 py-3">
              <div className="min-w-0">
                <div className="text-xs font-semibold text-omi-text-muted">
                  {settings
                    ? `${settings.kind} / ${t(`locales.${locale}`)} / ${themePreferenceLabel(
                        color,
                        highContrast,
                        t
                      )}`
                    : "technical_analysis_settings"}
                </div>
                {saveMessage ? (
                  <div
                    className={[
                      "mt-1 max-w-[520px] truncate text-xs font-semibold",
                      saveState === "error" ? "text-omi-danger" : "text-omi-success",
                    ].join(" ")}
                  >
                    {saveMessage}
                  </div>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-bold text-omi-text-muted hover:border-omi-control"
                  onClick={resetDraft}
                  disabled={!settings}
                >
                  {t("settings.reset")}
                </button>
                <button
                  type="button"
                  className={[
                    "h-9 border px-3 text-sm font-bold",
                    settings && loadState !== "loading" && saveState !== "saving"
                      ? "border-omi-accent bg-omi-accent text-omi-text-inverse hover:bg-omi-control"
                      : "cursor-not-allowed border-omi-border bg-omi-surface-strong text-omi-text-muted",
                  ].join(" ")}
                  disabled={!settings || loadState === "loading" || saveState === "saving"}
                  onClick={() => void saveTechnicalSettings()}
                >
                  {saveState === "saving" ? t("settings.saving") : t("settings.save")}
                </button>
              </div>
            </footer>
          </section>
        </div>
      ) : null}

      {refreshOpen ? (
        <div className="fixed inset-0 z-[2147483646] flex items-center justify-center bg-omi-overlay p-4">
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="refresh-settings-title"
            className="flex h-[560px] max-h-[calc(100vh-2rem)] w-[820px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden border border-omi-control-border bg-omi-surface shadow-2xl"
          >
            <header className="flex shrink-0 items-start justify-between gap-4 border-b border-omi-border-subtle px-5 py-4">
              <div className="min-w-0">
                <div className="text-xs font-bold uppercase tracking-[0.22em] text-omi-accent">
                  Settings
                </div>
                <h2 id="refresh-settings-title" className="mt-1 text-xl font-black text-omi-text-strong">
                  {t("settings.refreshExecution")}
                </h2>
                <div className="mt-2">
                  <SourceLabel settings={refreshSettings} />
                </div>
              </div>
              <button
                type="button"
                aria-label={t("settings.closeRefreshExecution")}
                className="grid h-8 w-8 shrink-0 place-items-center border border-omi-border text-omi-text-muted hover:border-omi-control hover:text-omi-text-strong"
                onClick={() => setRefreshOpen(false)}
              >
                <CloseIcon />
              </button>
            </header>

            <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)]">
              <nav className="min-h-0 overflow-y-auto border-b border-omi-border-subtle bg-omi-surface-subtle p-3 md:border-b-0 md:border-r">
                <div className="grid gap-1">
                  {refreshMarketSections.map((section) => (
                    <button
                      key={section.key}
                      type="button"
                      className={[
                        "w-full px-3 py-2 text-left transition",
                        activeRefreshSection.key === section.key
                          ? "bg-omi-control text-omi-text-inverse"
                          : "text-omi-text-muted hover:bg-omi-surface hover:text-omi-text-strong",
                      ].join(" ")}
                      onClick={() => setActiveRefreshMarket(section.key)}
                    >
                      <span className="block text-sm font-bold">{section.label}</span>
                      <span
                        className={
                          activeRefreshSection.key === section.key
                            ? "block text-[11px] text-omi-border"
                            : "block text-[11px] text-omi-text-muted"
                        }
                      >
                        {section.eyebrow}
                      </span>
                    </button>
                  ))}
                </div>
              </nav>

              <div className="min-h-0 overflow-y-auto overscroll-contain">
                <div className="border-b border-omi-border-subtle px-5 py-4">
                  <div className="text-xs font-bold uppercase tracking-[0.18em] text-omi-text-muted">
                    {activeRefreshSection.eyebrow}
                  </div>
                  <h3 className="mt-1 text-lg font-black text-omi-text-strong">
                    {activeRefreshSection.label}
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-omi-text-muted">
                    {activeRefreshSection.description}
                  </p>
                </div>

                {refreshLoadState === "loading" ? (
                  <div className="space-y-3 p-5" aria-live="polite">
                    {Array.from({ length: 3 }).map((_, index) => (
                      <div key={index} className="grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)]">
                        <div>
                          <div className="omi-skeleton h-4 w-24" />
                          <div className="mt-2 omi-skeleton h-3 w-36" />
                        </div>
                        <div className="omi-skeleton h-9 w-full" />
                      </div>
                    ))}
                  </div>
                ) : refreshErrorMessage ? (
                  <div className="m-5 border border-omi-danger-border bg-omi-danger-soft px-4 py-3 text-sm text-omi-danger">
                    <div className="font-bold">{t("settings.loadError")}</div>
                    <div className="mt-1 break-words text-xs leading-5">{refreshErrorMessage}</div>
                    <button
                      type="button"
                      className="mt-3 h-8 border border-omi-accent-border bg-omi-surface px-3 text-xs font-bold text-omi-danger hover:border-omi-danger"
                      onClick={() => void loadRefreshSettings()}
                    >
                      {t("settings.retry")}
                    </button>
                  </div>
                ) : (
                  <div>
                    {activeRefreshSection.fields.map((field) => (
                      <ParameterInput
                        key={field.key}
                        field={{
                          ...field,
                          key: refreshDraftKey(activeRefreshSection.key, field.key as RefreshExecutionField),
                        }}
                        value={
                          refreshDraft[
                            refreshDraftKey(activeRefreshSection.key, field.key as RefreshExecutionField)
                          ] ?? ""
                        }
                        onChange={updateRefreshDraftValue}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>

            <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-omi-border-subtle bg-omi-surface-subtle px-5 py-3">
              <div className="min-w-0">
                <div className="text-xs font-semibold text-omi-text-muted">
                  {refreshSettings
                    ? `${refreshSettings.kind} / ${t(`locales.${locale}`)} / ${themePreferenceLabel(
                        color,
                        highContrast,
                        t
                      )}`
                    : "refresh_execution_settings"}
                </div>
                {refreshSaveMessage ? (
                  <div
                    className={[
                      "mt-1 max-w-[520px] truncate text-xs font-semibold",
                      refreshSaveState === "error" ? "text-omi-danger" : "text-omi-success",
                    ].join(" ")}
                  >
                    {refreshSaveMessage}
                  </div>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="h-9 border border-omi-border bg-omi-surface px-3 text-sm font-bold text-omi-text-muted hover:border-omi-control"
                  onClick={resetRefreshDraft}
                  disabled={!refreshSettings}
                >
                  {t("settings.reset")}
                </button>
                <button
                  type="button"
                  className={[
                    "h-9 border px-3 text-sm font-bold",
                    refreshSettings && refreshLoadState !== "loading" && refreshSaveState !== "saving"
                      ? "border-omi-accent bg-omi-accent text-omi-text-inverse hover:bg-omi-control"
                      : "cursor-not-allowed border-omi-border bg-omi-surface-strong text-omi-text-muted",
                  ].join(" ")}
                  disabled={
                    !refreshSettings ||
                    refreshLoadState === "loading" ||
                    refreshSaveState === "saving"
                  }
                  onClick={() => void saveRefreshSettings()}
                >
                  {refreshSaveState === "saving" ? t("settings.saving") : t("settings.save")}
                </button>
              </div>
            </footer>
          </section>
        </div>
      ) : null}

      <DispatchSettingsDialog
        open={dispatchOpen}
        onClose={() => setDispatchOpen(false)}
      />
    </>
  );
}

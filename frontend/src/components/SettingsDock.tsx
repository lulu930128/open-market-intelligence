"use client";

import { fetchJson, requestJson } from "@/lib/api";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type LoadState = "idle" | "loading" | "success" | "error";
type SaveState = "idle" | "saving" | "success" | "error";
type LanguageSetting = "zh-TW" | "en-US";
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

type ParameterField = {
  key: string;
  label: string;
  hint: string;
  unit?: string;
  inputMode?: "text" | "numeric" | "decimal";
  min?: number;
  step?: number;
};

type ParameterSection = {
  key: ParameterSectionKey;
  label: string;
  eyebrow: string;
  description: string;
  fields: ParameterField[];
};

const languageLabels: Record<LanguageSetting, string> = {
  "zh-TW": "繁中",
  "en-US": "English",
};

const colorLabels: Record<ColorSetting, string> = {
  dark: "暗色",
  light: "白色",
};

const colorSettingChoices: ColorSetting[] = ["light", "dark"];

const parameterSections: ParameterSection[] = [
  {
    key: "moving",
    label: "均線與量能",
    eyebrow: "Moving Average",
    description: "全域 MA、量均線與量能放大判斷。",
    fields: [
      {
        key: "maWindows",
        label: "MA 週期",
        hint: "以逗號分隔，例如 5,20,60",
        inputMode: "text",
      },
      {
        key: "volumeMaWindows",
        label: "量均線週期",
        hint: "以逗號分隔，例如 5,20",
        inputMode: "text",
      },
      {
        key: "volumeRatio",
        label: "量能放大門檻",
        hint: "成交量相對均量倍數",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "x",
      },
    ],
  },
  {
    key: "trend",
    label: "趨勢",
    eyebrow: "Trend",
    description: "MACD、ADX、通道突破與支撐壓力週期。",
    fields: [
      { key: "macdFast", label: "MACD fast", hint: "快速 EMA 週期", inputMode: "numeric", min: 1, step: 1 },
      { key: "macdSlow", label: "MACD slow", hint: "慢速 EMA 週期", inputMode: "numeric", min: 1, step: 1 },
      { key: "macdSignal", label: "MACD signal", hint: "訊號線週期", inputMode: "numeric", min: 1, step: 1 },
      { key: "adxPeriod", label: "ADX 週期", hint: "趨勢強度計算天數", inputMode: "numeric", min: 1, step: 1 },
      { key: "adxTrend", label: "ADX 趨勢門檻", hint: "高於此值視為趨勢成立", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "donchianPeriod", label: "Donchian 週期", hint: "高低通道回看天數", inputMode: "numeric", min: 1, step: 1 },
      {
        key: "supportResistance",
        label: "支撐壓力週期",
        hint: "前高前低與關鍵位回看天數",
        inputMode: "numeric",
        min: 1,
        step: 1,
      },
    ],
  },
  {
    key: "momentum",
    label: "動能震盪",
    eyebrow: "Momentum",
    description: "RSI、KD、ROC 與超買超賣判斷。",
    fields: [
      { key: "rsiPeriod", label: "RSI 週期", hint: "RSI 計算天數", inputMode: "numeric", min: 1, step: 1 },
      { key: "rsiBullMin", label: "RSI 偏多下緣", hint: "偏多區間最小值", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "rsiBullMax", label: "RSI 偏多上緣", hint: "偏多區間最大值", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "rsiWeakBelow", label: "RSI 轉弱門檻", hint: "低於此值視為轉弱", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "rsiOverheated", label: "RSI 過熱門檻", hint: "高於此值視為過熱", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "kdPeriod", label: "KD 週期", hint: "KD RSV 回看天數", inputMode: "numeric", min: 1, step: 1 },
      { key: "kdSmooth", label: "KD 平滑", hint: "K / D 平滑週期", inputMode: "numeric", min: 1, step: 1 },
      { key: "kdOverboughtK", label: "K 超買", hint: "K 值超買門檻", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "kdOverboughtD", label: "D 超買", hint: "D 值超買門檻", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "kdOversoldK", label: "K 超賣", hint: "K 值超賣門檻", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "kdOversoldD", label: "D 超賣", hint: "D 值超賣門檻", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "rocPeriod", label: "ROC 週期", hint: "變動率計算天數", inputMode: "numeric", min: 1, step: 1 },
    ],
  },
  {
    key: "volatility",
    label: "波動通道",
    eyebrow: "Volatility",
    description: "ATR、Bollinger 與接近關鍵價位的門檻。",
    fields: [
      { key: "atrPeriod", label: "ATR 週期", hint: "真實波幅計算天數", inputMode: "numeric", min: 1, step: 1 },
      {
        key: "atrHighPct",
        label: "ATR 高波動門檻",
        hint: "ATR 佔價格百分比",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "%",
      },
      {
        key: "atrExpansion",
        label: "ATR 擴張倍數",
        hint: "相對前期放大的倍數",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "x",
      },
      {
        key: "atrExpansionMinPct",
        label: "ATR 擴張下限",
        hint: "擴張判斷的最低 ATR%",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "%",
      },
      {
        key: "bollingerPeriod",
        label: "Bollinger 週期",
        hint: "布林通道均線週期",
        inputMode: "numeric",
        min: 1,
        step: 1,
      },
      {
        key: "bollingerStdDev",
        label: "Bollinger 標準差",
        hint: "上下軌標準差倍數",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
      },
      {
        key: "bollingerSqueeze",
        label: "Bollinger 收斂門檻",
        hint: "帶寬百分比低於此值視為收斂",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "%",
      },
      {
        key: "nearLevelPct",
        label: "接近關鍵位",
        hint: "距離支撐壓力的百分比",
        inputMode: "decimal",
        min: 0,
        step: 0.1,
        unit: "%",
      },
      {
        key: "maxGapDays",
        label: "最大資料間隔",
        hint: "允許 OHLC 缺口天數",
        inputMode: "numeric",
        min: 1,
        step: 1,
        unit: "天",
      },
    ],
  },
  {
    key: "flow",
    label: "資金流",
    eyebrow: "Money Flow",
    description: "MFI 與資金流入流出判斷。",
    fields: [
      { key: "mfiPeriod", label: "MFI 週期", hint: "Money Flow 計算天數", inputMode: "numeric", min: 1, step: 1 },
      { key: "mfiInflowMin", label: "MFI 流入下緣", hint: "資金流入區間最小值", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "mfiInflowMax", label: "MFI 流入上緣", hint: "資金流入區間最大值", inputMode: "decimal", min: 0, step: 0.5 },
      { key: "mfiOutflowBelow", label: "MFI 流出門檻", hint: "低於此值視為資金流出", inputMode: "decimal", min: 0, step: 0.5 },
    ],
  },
];

function readStoredChoice<T extends string>(
  key: string,
  fallback: T,
  choices: readonly T[]
): T {
  if (typeof window === "undefined") return fallback;

  try {
    const value = window.localStorage.getItem(key);
    return choices.includes(value as T) ? (value as T) : fallback;
  } catch {
    return fallback;
  }
}

function storePreference(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore local preference failures; the app can still run with in-memory state.
  }
}

function applyColorTheme(value: ColorSetting) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = value;
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

function parseWindowList(value: string | undefined, label: string) {
  const windows = (value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item));

  if (!windows.length) {
    throw new Error(`${label} 至少需要一個週期。`);
  }

  for (const window of windows) {
    if (!Number.isInteger(window) || window <= 0) {
      throw new Error(`${label} 只能包含正整數，並以逗號分隔。`);
    }
  }

  return Array.from(new Set(windows)).sort((a, b) => a - b);
}

function parseNumberValue(
  draft: ParameterDraft,
  key: string,
  label: string,
  options: { integer?: boolean } = {}
) {
  const rawValue = draft[key]?.trim();
  if (!rawValue) {
    throw new Error(`${label} 不能空白。`);
  }

  const value = Number(rawValue);
  if (!Number.isFinite(value)) {
    throw new Error(`${label} 必須是數字。`);
  }

  if (options.integer && !Number.isInteger(value)) {
    throw new Error(`${label} 必須是整數。`);
  }

  if (value <= 0) {
    throw new Error(`${label} 必須大於 0。`);
  }

  return value;
}

function buildTechnicalSettingsWritePayload(
  draft: ParameterDraft
): TechnicalAnalysisSettingsWrite {
  return {
    windows: {
      ma: parseWindowList(draft.maWindows, "MA 週期"),
      volume_ma: parseWindowList(draft.volumeMaWindows, "量均線週期"),
      max_gap_days: parseNumberValue(draft, "maxGapDays", "最大資料間隔", {
        integer: true,
      }),
    },
    periods: {
      macd: {
        fast: parseNumberValue(draft, "macdFast", "MACD fast", { integer: true }),
        slow: parseNumberValue(draft, "macdSlow", "MACD slow", { integer: true }),
        signal: parseNumberValue(draft, "macdSignal", "MACD signal", { integer: true }),
      },
      rsi: parseNumberValue(draft, "rsiPeriod", "RSI 週期", { integer: true }),
      atr: parseNumberValue(draft, "atrPeriod", "ATR 週期", { integer: true }),
      adx: parseNumberValue(draft, "adxPeriod", "ADX 週期", { integer: true }),
      roc: parseNumberValue(draft, "rocPeriod", "ROC 週期", { integer: true }),
      mfi: parseNumberValue(draft, "mfiPeriod", "MFI 週期", { integer: true }),
      donchian: parseNumberValue(draft, "donchianPeriod", "Donchian 週期", {
        integer: true,
      }),
      bollinger: {
        period: parseNumberValue(draft, "bollingerPeriod", "Bollinger 週期", {
          integer: true,
        }),
        std_dev: parseNumberValue(draft, "bollingerStdDev", "Bollinger 標準差"),
      },
      kd: {
        period: parseNumberValue(draft, "kdPeriod", "KD 週期", { integer: true }),
        smooth: parseNumberValue(draft, "kdSmooth", "KD 平滑", { integer: true }),
      },
      support_resistance: parseNumberValue(
        draft,
        "supportResistance",
        "支撐壓力週期",
        { integer: true }
      ),
    },
    thresholds: {
      volume_ratio: parseNumberValue(draft, "volumeRatio", "量能放大門檻"),
      near_level_pct: parseNumberValue(draft, "nearLevelPct", "接近關鍵位"),
      adx_trend: parseNumberValue(draft, "adxTrend", "ADX 趨勢門檻"),
      rsi: {
        bull_min: parseNumberValue(draft, "rsiBullMin", "RSI 偏多下緣"),
        bull_max: parseNumberValue(draft, "rsiBullMax", "RSI 偏多上緣"),
        weak_below: parseNumberValue(draft, "rsiWeakBelow", "RSI 轉弱門檻"),
        overheated_at: parseNumberValue(draft, "rsiOverheated", "RSI 過熱門檻"),
      },
      mfi: {
        inflow_min: parseNumberValue(draft, "mfiInflowMin", "MFI 流入下緣"),
        inflow_max: parseNumberValue(draft, "mfiInflowMax", "MFI 流入上緣"),
        outflow_below: parseNumberValue(draft, "mfiOutflowBelow", "MFI 流出門檻"),
      },
      kd: {
        overbought_k: parseNumberValue(draft, "kdOverboughtK", "K 超買"),
        overbought_d: parseNumberValue(draft, "kdOverboughtD", "D 超買"),
        oversold_k: parseNumberValue(draft, "kdOversoldK", "K 超賣"),
        oversold_d: parseNumberValue(draft, "kdOversoldD", "D 超賣"),
      },
      atr: {
        high_volatility_pct: parseNumberValue(draft, "atrHighPct", "ATR 高波動門檻"),
        expansion_multiplier: parseNumberValue(draft, "atrExpansion", "ATR 擴張倍數"),
        expansion_min_pct: parseNumberValue(draft, "atrExpansionMinPct", "ATR 擴張下限"),
      },
      bollinger_squeeze_bandwidth_pct: parseNumberValue(
        draft,
        "bollingerSqueeze",
        "Bollinger 收斂門檻"
      ),
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
  options: Array<{ value: T; label: string }>;
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
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
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

function SourceLabel({ settings }: { settings: TechnicalAnalysisSettingsRead | null }) {
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
  const [menuOpen, setMenuOpen] = useState(false);
  const [parametersOpen, setParametersOpen] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [settings, setSettings] = useState<TechnicalAnalysisSettingsRead | null>(null);
  const [draft, setDraft] = useState<ParameterDraft>({});
  const [activeSectionKey, setActiveSectionKey] = useState<ParameterSectionKey>("moving");
  const [language, setLanguage] = useState<LanguageSetting>(() =>
    readStoredChoice<LanguageSetting>("omi:settings:language", "zh-TW", ["zh-TW", "en-US"])
  );
  const [color, setColor] = useState<ColorSetting>(() =>
    readStoredChoice<ColorSetting>("omi:settings:color", "light", colorSettingChoices)
  );
  const rootRef = useRef<HTMLDivElement | null>(null);

  const activeSection = useMemo(
    () =>
      parameterSections.find((section) => section.key === activeSectionKey) ??
      parameterSections[0],
    [activeSectionKey]
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
      setErrorMessage(error instanceof Error ? error.message : "設定讀取失敗");
    }
  }, []);

  useEffect(() => {
    storePreference("omi:settings:language", language);
  }, [language]);

  useEffect(() => {
    storePreference("omi:settings:color", color);
    applyColorTheme(color);
  }, [color]);

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
    if (!parametersOpen) return;

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setParametersOpen(false);
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [parametersOpen]);

  function openParameterDialog() {
    setMenuOpen(false);
    setParametersOpen(true);
    if (loadState === "idle" || (loadState === "error" && settings === null)) {
      void loadSettings();
    }
  }

  function updateDraftValue(key: string, value: string) {
    setSaveState("idle");
    setSaveMessage(null);
    setDraft((current) => ({
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

  async function saveTechnicalSettings() {
    setSaveState("saving");
    setSaveMessage(null);

    try {
      const payload = buildTechnicalSettingsWritePayload(draft);
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
      setSaveMessage("已儲存，全域技術分析會使用新的參數。");
    } catch (error) {
      setSaveState("error");
      setSaveMessage(error instanceof Error ? error.message : "設定儲存失敗");
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
              設定
            </div>
            <div className="divide-y divide-omi-border-subtle">
              <PreferenceSelect<LanguageSetting>
                label="語言"
                value={language}
                options={[
                  { value: "zh-TW", label: "繁體中文" },
                  { value: "en-US", label: "English" },
                ]}
                onChange={setLanguage}
              />
              <PreferenceSelect<ColorSetting>
                label="顏色"
                value={color}
                options={[
                  { value: "light", label: "白色" },
                  { value: "dark", label: "暗色" },
                ]}
                onChange={setColor}
              />
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-omi-surface-subtle"
                onClick={openParameterDialog}
              >
                <span>
                  <span className="block font-semibold text-omi-text">參數調整</span>
                  <span className="block text-xs text-omi-text-muted">技術分析</span>
                </span>
                <ChevronIcon />
              </button>
            </div>
          </section>
        ) : null}

        <button
          type="button"
          aria-expanded={menuOpen}
          aria-label="開啟設定"
          className={buttonClassName}
          onClick={() => setMenuOpen((value) => !value)}
        >
          <GearIcon />
          <span>設定</span>
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
                  參數調整
                </h2>
                <div className="mt-2">
                  <SourceLabel settings={settings} />
                </div>
              </div>
              <button
                type="button"
                aria-label="關閉參數調整"
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
                    <div className="font-bold">設定讀取失敗</div>
                    <div className="mt-1 break-words text-xs leading-5">{errorMessage}</div>
                    <button
                      type="button"
                      className="mt-3 h-8 border border-omi-accent-border bg-omi-surface px-3 text-xs font-bold text-omi-danger hover:border-omi-danger"
                      onClick={() => void loadSettings()}
                    >
                      重試
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
                  {settings ? `${settings.kind} / ${languageLabels[language]} / ${colorLabels[color]}` : "technical_analysis_settings"}
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
                  重設
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
                  {saveState === "saving" ? "儲存中" : "儲存"}
                </button>
              </div>
            </footer>
          </section>
        </div>
      ) : null}
    </>
  );
}

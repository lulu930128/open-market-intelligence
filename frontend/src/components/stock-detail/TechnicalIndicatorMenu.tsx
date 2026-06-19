"use client";

import {
  defaultIndicators,
  indicatorCategoryGroups,
  type IndicatorCategoryGroup,
  type IndicatorKey,
  type IndicatorParameters,
  type IndicatorSettings,
} from "@/components/StockKLineChart";
export type IndicatorTemplateKey = "basic" | "short" | "trend" | "swing" | "flow";

export const indicatorTemplates: Array<{
  key: IndicatorTemplateKey;
  label: string;
  indicators: IndicatorSettings;
  parameters?: Partial<IndicatorParameters>;
}> = [
  {
    key: "basic",
    label: "基本",
    indicators: defaultIndicators,
  },
  {
    key: "short",
    label: "短線",
    indicators: {
      ...defaultIndicators,
      ma: false,
      ema: true,
      hma: true,
      vwma: true,
      vwap: true,
      kd: true,
      momentum: true,
      mfi: true,
      signals: true,
      candlestickPatterns: true,
    },
    parameters: {
      emaFast: 5,
      emaSlow: 20,
      hmaPeriod: 16,
      vwmaPeriod: 20,
      kdPeriod: 9,
      momentumPeriod: 5,
      mfiPeriod: 14,
    },
  },
  {
    key: "trend",
    label: "趨勢",
    indicators: {
      ...defaultIndicators,
      ema: true,
      wma: true,
      psar: true,
      donchian: true,
      ichimoku: true,
      supertrend: true,
      atr: true,
      adx: true,
      choppiness: true,
      pivotPoints: true,
      supportResistance: true,
      signals: true,
    },
    parameters: {
      emaFast: 12,
      emaSlow: 26,
      wmaPeriod: 20,
      donchianPeriod: 20,
      ichimokuConversionPeriod: 9,
      ichimokuBasePeriod: 26,
      ichimokuSpanBPeriod: 52,
      ichimokuDisplacement: 26,
      supertrendAtrPeriod: 10,
      supertrendMultiplier: 3,
      atrPeriod: 14,
      adxPeriod: 14,
      choppinessPeriod: 14,
      pivotLookback: 1,
      supportResistanceLookback: 20,
    },
  },
  {
    key: "swing",
    label: "波段",
    indicators: {
      ...defaultIndicators,
      bollinger: true,
      bbWidth: true,
      keltner: true,
      rsi: true,
      macd: true,
      aroon: true,
      roc: true,
      trix: true,
      cci: true,
      tsi: true,
      awesomeOscillator: true,
      ultimateOscillator: true,
      signals: true,
      divergence: true,
      relativeStrength: true,
      beta: true,
      correlation: true,
    },
    parameters: {
      bollingerPeriod: 20,
      bollingerStdDev: 2,
      keltnerPeriod: 20,
      keltnerAtrPeriod: 10,
      keltnerMultiplier: 2,
      rsiPeriod: 14,
      aroonPeriod: 25,
      rocPeriod: 12,
      trixPeriod: 15,
      trixSignal: 9,
      cciPeriod: 20,
      bbWidthPeriod: 20,
      tsiShortPeriod: 13,
      tsiLongPeriod: 25,
      tsiSignalPeriod: 7,
      awesomeFastPeriod: 5,
      awesomeSlowPeriod: 34,
      ultimateShortPeriod: 7,
      ultimateMiddlePeriod: 14,
      ultimateLongPeriod: 28,
      relativeStrengthLookback: 20,
      betaPeriod: 60,
      correlationPeriod: 60,
    },
  },
  {
    key: "flow",
    label: "量價",
    indicators: {
      ...defaultIndicators,
      ma: false,
      vwap: true,
      obv: true,
      mfi: true,
      cmf: true,
      adLine: true,
      pvt: true,
      volume: true,
      signals: true,
    },
    parameters: {
      volumeMa: 20,
      obvMa: 10,
      mfiPeriod: 14,
      cmfPeriod: 20,
    },
  },
];

export default function TechnicalIndicatorMenu({
  indicators,
  activeTemplate,
  onApplyTemplate,
  onToggleIndicator,
  groups = indicatorCategoryGroups,
  includeParameters = false,
  parameters,
  onUpdateParameter,
  className = "w-80",
}: {
  indicators: IndicatorSettings;
  activeTemplate: IndicatorTemplateKey | null;
  onApplyTemplate: (templateKey: IndicatorTemplateKey) => void;
  onToggleIndicator: (key: IndicatorKey) => void;
  groups?: IndicatorCategoryGroup[];
  includeParameters?: boolean;
  parameters?: IndicatorParameters;
  onUpdateParameter?: (
    key: keyof IndicatorParameters,
    value: string,
    min: number,
    max: number
  ) => void;
  className?: string;
}) {
  return (
    <div
      className={[
        "absolute right-0 z-30 mt-2 max-h-[74vh] overflow-y-auto border border-omi-border-subtle bg-omi-surface p-3 text-left shadow-lg",
        className,
      ].join(" ")}
    >
      <div className="border-b border-omi-border-subtle pb-3">
        <div className="mb-2 text-xs font-bold text-omi-text-muted">快速組合</div>
        <div className="grid grid-cols-5 gap-1">
          {indicatorTemplates.map((template) => (
            <button
              key={template.key}
              type="button"
              onClick={() => onApplyTemplate(template.key)}
              className={[
                "h-8 border text-xs font-semibold",
                activeTemplate === template.key
                  ? "border-omi-accent bg-omi-accent text-omi-text-inverse"
                  : "border-omi-border bg-omi-surface text-omi-text hover:border-omi-control",
              ].join(" ")}
            >
              {template.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3 border-b border-omi-border-subtle py-3">
        {groups.map((group) => (
          <div key={group.key}>
            <div className="mb-1">
              <div className="text-xs font-bold text-omi-text">{group.label}</div>
              <div className="text-[11px] leading-4 text-omi-text-subtle">{group.description}</div>
            </div>
            <div className="space-y-0.5">
              {group.options.map((option) =>
                option.status === "available" ? (
                  <label
                    key={option.key}
                    className="flex cursor-pointer items-start gap-2 px-2 py-1.5 text-xs hover:bg-omi-surface-subtle"
                  >
                    <input
                      type="checkbox"
                      checked={indicators[option.key]}
                      onChange={() => onToggleIndicator(option.key)}
                      className="mt-0.5"
                    />
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 font-semibold text-omi-text">
                        <span>{option.label}</span>
                        <span className="text-[10px] font-medium uppercase text-omi-text-subtle">
                          {option.plot}
                        </span>
                      </span>
                      <span className="block text-omi-text-muted">{option.description}</span>
                    </span>
                  </label>
                ) : (
                  <div
                    key={option.key}
                    className="flex cursor-not-allowed items-start justify-between gap-3 px-2 py-1.5 text-xs opacity-60"
                  >
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 font-semibold text-omi-text-muted">
                        <span>{option.label}</span>
                        <span className="text-[10px] font-medium uppercase text-omi-text-subtle">
                          {option.plot}
                        </span>
                      </span>
                      <span className="block text-omi-text-muted">{option.description}</span>
                    </span>
                    <span className="shrink-0 bg-omi-surface-muted px-1.5 py-0.5 text-[10px] font-bold text-omi-text-muted">
                      待補
                    </span>
                  </div>
                )
              )}
            </div>
          </div>
        ))}
      </div>

      {includeParameters && parameters && onUpdateParameter ? (
        <div className="pt-3">
          <div className="mb-2 text-xs font-bold text-omi-text-muted">參數</div>
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: "MA短", key: "maShort", min: 1, max: 300 },
              { label: "MA中", key: "maMiddle", min: 1, max: 400 },
              { label: "MA長", key: "maLong", min: 1, max: 600 },
              { label: "EMA快", key: "emaFast", min: 1, max: 200 },
              { label: "EMA慢", key: "emaSlow", min: 2, max: 400 },
              { label: "WMA", key: "wmaPeriod", min: 1, max: 300 },
              { label: "HMA", key: "hmaPeriod", min: 2, max: 300 },
              { label: "VWMA", key: "vwmaPeriod", min: 1, max: 300 },
              { label: "BOLL週期", key: "bollingerPeriod", min: 2, max: 300 },
              { label: "BOLL倍數", key: "bollingerStdDev", min: 0.5, max: 5, step: 0.1 },
              { label: "BB寬度", key: "bbWidthPeriod", min: 2, max: 300 },
              { label: "StdDev", key: "stdDevPeriod", min: 2, max: 300 },
              { label: "CHOP", key: "choppinessPeriod", min: 2, max: 100 },
              { label: "量均", key: "volumeMa", min: 1, max: 300 },
              { label: "RSI", key: "rsiPeriod", min: 2, max: 100 },
              { label: "MACD快", key: "macdFast", min: 1, max: 100 },
              { label: "MACD慢", key: "macdSlow", min: 2, max: 200 },
              { label: "MACD Sig", key: "macdSignal", min: 1, max: 100 },
              { label: "KD", key: "kdPeriod", min: 2, max: 100 },
              { label: "Momentum", key: "momentumPeriod", min: 1, max: 200 },
              { label: "TSI短", key: "tsiShortPeriod", min: 1, max: 100 },
              { label: "TSI長", key: "tsiLongPeriod", min: 2, max: 200 },
              { label: "TSI Sig", key: "tsiSignalPeriod", min: 1, max: 100 },
              { label: "AO快", key: "awesomeFastPeriod", min: 1, max: 100 },
              { label: "AO慢", key: "awesomeSlowPeriod", min: 2, max: 200 },
              { label: "UO短", key: "ultimateShortPeriod", min: 1, max: 100 },
              { label: "UO中", key: "ultimateMiddlePeriod", min: 2, max: 150 },
              { label: "UO長", key: "ultimateLongPeriod", min: 3, max: 240 },
              { label: "ATR", key: "atrPeriod", min: 2, max: 100 },
              { label: "ADX", key: "adxPeriod", min: 2, max: 100 },
              { label: "DONCH", key: "donchianPeriod", min: 2, max: 300 },
              { label: "一目轉換", key: "ichimokuConversionPeriod", min: 2, max: 120 },
              { label: "一目基準", key: "ichimokuBasePeriod", min: 2, max: 240 },
              { label: "一目SpanB", key: "ichimokuSpanBPeriod", min: 2, max: 360 },
              { label: "一目位移", key: "ichimokuDisplacement", min: 0, max: 120 },
              { label: "ST ATR", key: "supertrendAtrPeriod", min: 2, max: 100 },
              { label: "ST倍數", key: "supertrendMultiplier", min: 0.5, max: 10, step: 0.1 },
              { label: "KC週期", key: "keltnerPeriod", min: 2, max: 300 },
              { label: "KC ATR", key: "keltnerAtrPeriod", min: 2, max: 100 },
              { label: "KC倍數", key: "keltnerMultiplier", min: 0.5, max: 10, step: 0.1 },
              { label: "Aroon", key: "aroonPeriod", min: 2, max: 200 },
              { label: "OBV MA", key: "obvMa", min: 1, max: 200 },
              { label: "MFI", key: "mfiPeriod", min: 2, max: 100 },
              { label: "CMF", key: "cmfPeriod", min: 2, max: 200 },
              { label: "CCI", key: "cciPeriod", min: 2, max: 200 },
              { label: "W%R", key: "williamsRPeriod", min: 2, max: 100 },
              { label: "ROC", key: "rocPeriod", min: 1, max: 200 },
              { label: "StochRSI", key: "stochRsiPeriod", min: 2, max: 100 },
              { label: "Stoch K", key: "stochRsiSmoothK", min: 1, max: 20 },
              { label: "Stoch D", key: "stochRsiSmoothD", min: 1, max: 20 },
              { label: "TRIX", key: "trixPeriod", min: 2, max: 100 },
              { label: "TRIX Sig", key: "trixSignal", min: 1, max: 50 },
              { label: "VPVR列", key: "volumeProfileRows", min: 8, max: 80 },
              { label: "Pivot回看", key: "pivotLookback", min: 1, max: 20 },
              { label: "S/R回看", key: "supportResistanceLookback", min: 2, max: 300 },
              { label: "Gap%", key: "gapMinPct", min: 0.1, max: 20, step: 0.1 },
              { label: "RS回看", key: "relativeStrengthLookback", min: 2, max: 260 },
              { label: "Beta週期", key: "betaPeriod", min: 8, max: 260 },
              { label: "Corr週期", key: "correlationPeriod", min: 8, max: 260 },
            ].map((field) => (
              <label key={field.key} className="text-xs">
                <span className="mb-1 block font-semibold text-omi-text-muted">{field.label}</span>
                <input
                  type="number"
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  value={parameters[field.key as keyof IndicatorParameters]}
                  onChange={(event) =>
                    onUpdateParameter(
                      field.key as keyof IndicatorParameters,
                      event.target.value,
                      field.min,
                      field.max
                    )
                  }
                  className="h-8 w-full border border-omi-border px-2 text-xs font-semibold text-omi-text"
                />
              </label>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

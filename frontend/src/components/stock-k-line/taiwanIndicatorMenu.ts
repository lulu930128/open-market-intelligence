import type { TaiwanTechnicalCapabilityContract } from "@/types/market";
import type { IndicatorCategoryGroup, IndicatorParameters, IndicatorSettings } from "./indicatorCatalog";
import { backendIndicatorCapabilities } from "./indicatorAuthority";

const capabilityKeys: Record<string, string> = {
  ...backendIndicatorCapabilities, adLine: "ad", pivotPoints: "pivot_points",
  volumeProfile: "volume_profile", relativeStrength: "relative_strength",
  candlestickPatterns: "candlestick_patterns",
};

function parameterDescription(key: string, p: IndicatorParameters) {
  const labels: Record<string, string> = {
    ma: `MA ${p.maShort} / ${p.maMiddle} / ${p.maLong}`,
    ema: `EMA ${p.emaFast} / ${p.emaSlow}`,
    macd: `MACD ${p.macdFast} / ${p.macdSlow} / ${p.macdSignal}`,
    rsi: `RSI ${p.rsiPeriod}`, atr: `ATR ${p.atrPeriod}`,
    adx: `ADX / DMI ${p.adxPeriod}`, mfi: `MFI ${p.mfiPeriod}`,
    roc: `ROC ${p.rocPeriod}`, kd: `KD ${p.kdPeriod}`,
    donchian: `Donchian ${p.donchianPeriod}`,
    bollinger: `BOLL ${p.bollingerPeriod} ± ${p.bollingerStdDev} SD`,
    supportResistance: `S/R ${p.supportResistanceLookback}`,
    volume: `VOL / MA ${p.volumeMa}`,
  };
  return labels[key];
}

export function projectTaiwanIndicatorMenu(
  groups: IndicatorCategoryGroup[],
  contract: TaiwanTechnicalCapabilityContract | null,
  interval: string,
  parameters: IndicatorParameters
): IndicatorCategoryGroup[] {
  return groups.map((group) => ({
    ...group,
    options: group.options.map((option) => {
      const capability = contract?.indicators[capabilityKeys[option.key] ?? option.key];
      const status = !contract ? "unavailable"
        : !capability ? "unsupported"
        : capability.status !== "available" ? "pending"
        : capability.applicable_intervals && !capability.applicable_intervals.includes(interval)
          ? "not_applicable"
          : !backendIndicatorCapabilities[option.key] ? "unavailable" : "available";
      return {
        ...option,
        // Never display hard-coded periods as the current Backend settings.
        canonicalDescription: parameterDescription(option.key, parameters) ?? option.label,
        status,
      } as IndicatorCategoryGroup["options"][number];
    }),
  }));
}

export function filterTaiwanIndicatorPreset(
  preset: IndicatorSettings,
  groups: IndicatorCategoryGroup[]
): IndicatorSettings {
  const enabled = new Set<string>(groups.flatMap((group) => group.options)
    .filter((option) => option.status === "available").map((option) => option.key));
  return Object.fromEntries(Object.entries(preset).map(([key, value]) =>
    [key, value && enabled.has(key)])) as IndicatorSettings;
}
